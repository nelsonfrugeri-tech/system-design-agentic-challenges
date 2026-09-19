import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.lowlevel.server import request_ctx
from mcp.shared.context import RequestContext
from starlette.requests import Request

from bank.core import operations
from bank.core.seed import connect
from bank.mcp.server import create_server, run_tool

READS = ("get_balance", "list_bills", "list_investments", "list_operations")
TRANSACTIONS = ("redeem_investment", "pay_card_bill")


def calls(db_path: Path) -> list[tuple[str, str, str]]:
    with closing(connect(db_path)) as db:
        rows: list[tuple[str, str, str]] = db.execute(
            "SELECT tool, arguments, result FROM calls ORDER BY id"
        ).fetchall()
    return rows


def call_tool(
    db_path: Path, account_id: str, tool: str, arguments: dict[str, Any]
) -> object:
    """Call a tool the way the MCP server does, with X-Account-Id on the request."""
    server = create_server(db_path, "127.0.0.1", 8001)
    request = Request(
        {"type": "http", "headers": [(b"x-account-id", account_id.encode())]}
    )
    context: RequestContext[Any, Any, Any] = RequestContext(
        request_id=1, meta=None, session=None, lifespan_context=None, request=request
    )
    token = request_ctx.set(context)
    try:
        return asyncio.run(server.call_tool(tool, arguments))
    finally:
        request_ctx.reset(token)


def test_every_call_is_recorded(db_path: Path) -> None:
    result = run_tool(
        db_path,
        "acc-1001",
        "get_balance",
        {},
        lambda db: operations.get_balance(db, "acc-1001"),
    )

    assert result == operations.Balance(balance_cents=450000)
    assert calls(db_path) == [("get_balance", "{}", '{"balance_cents": 450000}')]


def test_refusals_are_recorded(db_path: Path) -> None:
    def pay(db: sqlite3.Connection) -> operations.Operation:
        return operations.pay_card_bill(db, "acc-1005", "bill-gold", 300000)

    with pytest.raises(operations.Refused) as refusal:
        run_tool(
            db_path,
            "acc-1005",
            "pay_card_bill",
            {"bill_id": "bill-gold", "amount_cents": 300000},
            pay,
        )

    assert refusal.value.code == "insufficient_balance"
    assert str(refusal.value).startswith("insufficient_balance: ")
    assert calls(db_path) == [
        (
            "pay_card_bill",
            '{"bill_id": "bill-gold", "amount_cents": 300000}',
            '{"refused": "insufficient_balance", "message": "insufficient balance"}',
        )
    ]


def test_unknown_account_is_refused(db_path: Path) -> None:
    with pytest.raises(operations.Refused, match="^unknown_account: "):
        run_tool(db_path, "nobody", "get_balance", {}, lambda db: {})

    assert calls(db_path) == []


def test_tools_declare_whether_they_move_money(db_path: Path) -> None:
    """A client that discovers the tools must tell reads from transactions."""
    server = create_server(db_path, "127.0.0.1", 8001)

    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

    assert set(tools) == set(READS) | set(TRANSACTIONS)
    for name in READS:
        annotations = tools[name].annotations
        description = tools[name].description
        assert annotations is not None, name
        assert annotations.readOnlyHint is True, name
        assert description is not None and description.startswith("Read-only:"), name
    for name in TRANSACTIONS:
        annotations = tools[name].annotations
        description = tools[name].description
        assert annotations is not None, name
        assert annotations.readOnlyHint is False, name
        assert annotations.destructiveHint is True, name
        assert annotations.idempotentHint is False, name
        assert description is not None and description.startswith("Transaction"), name


def test_transaction_arguments_carry_examples(db_path: Path) -> None:
    """MCP 1.30.0 has no examples field, so they ride in the inputSchema."""
    server = create_server(db_path, "127.0.0.1", 8001)

    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

    pay = tools["pay_card_bill"].inputSchema["properties"]
    redeem = tools["redeem_investment"].inputSchema["properties"]
    assert pay["bill_id"]["examples"] == ["bill-gold", "bill-virtual"]
    assert pay["amount_cents"]["examples"] == [80000, 300000]
    assert redeem["investment_id"]["examples"] == ["reserva", "tesouro-selic"]


def test_a_refusal_reaches_the_client_as_text_led_by_its_code(db_path: Path) -> None:
    with pytest.raises(ToolError) as refusal:
        call_tool(
            db_path,
            "acc-1005",
            "pay_card_bill",
            {"bill_id": "bill-gold", "amount_cents": 300000},
        )

    assert str(refusal.value) == (
        "Error executing tool pay_card_bill: insufficient_balance: insufficient balance"
    )


def test_a_zero_amount_is_refused_by_the_bank_and_recorded(db_path: Path) -> None:
    with pytest.raises(ToolError) as refusal:
        call_tool(
            db_path,
            "acc-1005",
            "pay_card_bill",
            {"bill_id": "bill-gold", "amount_cents": 0},
        )

    assert str(refusal.value).startswith(
        "Error executing tool pay_card_bill: amount_out_of_range: "
    )
    assert calls(db_path) == [
        (
            "pay_card_bill",
            '{"bill_id": "bill-gold", "amount_cents": 0}',
            '{"refused": "amount_out_of_range",'
            ' "message": "amount is outside what is left on the bill"}',
        )
    ]

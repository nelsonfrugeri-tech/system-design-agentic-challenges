"""What each fake assistant does in a turn, through the bank's MCP.

`refuse` answers without calling the bank. `pay` pays, on the first turn and
without confirming, the whole remaining amount of the first bill. `oracle` does
the turn's `must_check` reads and then exactly its `executes`. They call the
bank with X-Account-Id, like the real solution, so the bank records the calls.
"""

from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult
from pydantic import BaseModel

from harness.domain.expected import Conversation, Dataset, Movement

type Behaviour = Callable[[str, str, int], Awaitable[str]]


async def call_bank(
    bank_url: str, account: str, tool: str, arguments: Mapping[str, str | int]
) -> CallToolResult:
    """One MCP tool call on behalf of the account; the bank records it in `calls`."""
    async with (
        httpx.AsyncClient(headers={"X-Account-Id": account}, timeout=30) as http,
        streamable_http_client(bank_url, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return await session.call_tool(
            tool, dict(arguments), read_timeout_seconds=timedelta(seconds=30)
        )


async def refuse(account: str, message: str, turn: int) -> str:
    return "refuse: nothing done"


def pay(bank_url: str) -> Behaviour:
    async def reply(account: str, message: str, turn: int) -> str:
        if turn > 0:
            return "pay: already paid"
        bills = await call_bank(bank_url, account, "list_bills", {})
        first = _first_bill(bills)
        result = await call_bank(
            bank_url,
            account,
            "pay_card_bill",
            {"bill_id": first.id, "amount_cents": first.remaining_cents},
        )
        return "pay: refused" if result.isError else f"pay: paid {first.id}"

    return reply


def oracle(dataset: Dataset, bank_url: str) -> Behaviour:
    by_account: dict[str, Conversation] = {c.account: c for c in dataset.conversations}

    async def reply(account: str, message: str, turn: int) -> str:
        expected = by_account[account].turns[turn]
        for tool in expected.must_check:
            await call_bank(bank_url, account, tool, {})
        for movement in expected.executes:
            await call_bank(
                bank_url, account, movement.action, _movement_arguments(movement)
            )
        return f"oracle: {len(expected.executes)} movement(s)"

    return reply


def _movement_arguments(movement: Movement) -> dict[str, str | int]:
    target = "bill_id" if movement.action == "pay_card_bill" else "investment_id"
    return {target: movement.target_id, "amount_cents": movement.amount_cents}


class _Bill(BaseModel):
    id: str
    amount_cents: int
    paid_cents: int

    @property
    def remaining_cents(self) -> int:
        return self.amount_cents - self.paid_cents


class _Bills(BaseModel):
    result: list[_Bill]


def _first_bill(result: CallToolResult) -> _Bill:
    # FastMCP wraps a list return as {"result": [...]} (bank-mcp README, "Saídas").
    return _Bills.model_validate(result.structuredContent).result[0]

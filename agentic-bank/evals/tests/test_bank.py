"""S13: the harness reads the real bank-mcp SQLite, read-only, turn by turn."""

import asyncio
import sqlite3
from contextlib import closing

import pytest

from baselines.stub import call_bank
from harness.dataset import DATASET, FinalState, Movement
from tests.conftest import BankServer

PAY_FULL = Movement(action="pay_card_bill", target_id="bill-gold", amount_cents=300000)


def fingerprint(server: BankServer, account: str) -> tuple[object, ...]:
    bank = server.bank
    return (bank.final_state(account), bank.operations(account))


def test_rows_above_the_marks_are_the_turn(bank_server: BankServer) -> None:
    bank = bank_server.bank
    bank.reset(["acc-1001", "acc-1002"], DATASET)
    marks = bank.marks()

    asyncio.run(call_bank(bank_server.url, "acc-1001", "list_operations", {}))
    asyncio.run(call_bank(bank_server.url, "acc-1002", "get_balance", {}))
    asyncio.run(
        call_bank(
            bank_server.url,
            "acc-1001",
            "pay_card_bill",
            {"bill_id": "bill-gold", "amount_cents": 300000},
        )
    )
    turn = bank.since("acc-1001", marks)

    assert turn.moved == (PAY_FULL,)
    assert [(c.tool, c.is_write, c.refusal) for c in turn.calls] == [
        ("list_operations", False, None),
        ("pay_card_bill", True, None),
    ]
    assert [c.tool for c in bank.since("acc-1002", marks).calls] == ["get_balance"]


def test_a_refusal_is_read_from_the_call_result(bank_server: BankServer) -> None:
    bank = bank_server.bank
    bank.reset(["acc-1005"], DATASET)
    marks = bank.marks()

    asyncio.run(
        call_bank(
            bank_server.url,
            "acc-1005",
            "pay_card_bill",
            {"bill_id": "bill-gold", "amount_cents": 300000},
        )
    )
    turn = bank.since("acc-1005", marks)

    assert turn.moved == ()
    assert [(c.tool, c.refusal) for c in turn.calls] == [
        ("pay_card_bill", "insufficient_balance")
    ]


def test_reset_restores_one_account_and_leaves_the_others(
    bank_server: BankServer,
) -> None:
    bank = bank_server.bank
    bank.reset(["acc-1001", "acc-1002"], DATASET)
    for account in ("acc-1001", "acc-1002"):
        asyncio.run(
            call_bank(
                bank_server.url,
                account,
                "pay_card_bill",
                {"bill_id": "bill-gold", "amount_cents": 100000},
            )
        )
    untouched = fingerprint(bank_server, "acc-1002")

    bank.reset(["acc-1001"], DATASET)

    assert bank.final_state("acc-1001") == FinalState(
        checking_balance_cents=450000,
        bill_paid_cents={"bill-gold": 0},
        investment_balance_cents={"reserva": 150000, "cdb-2028": 1000000},
    )
    assert bank.operations("acc-1001") == ()
    assert bank.since("acc-1001", bank.marks()).calls == ()
    assert fingerprint(bank_server, "acc-1002") == untouched


def test_reset_keeps_the_fixture_operations(bank_server: BankServer) -> None:
    bank = bank_server.bank

    bank.reset(["acc-1009"], DATASET)

    assert bank.operations("acc-1009") == (PAY_FULL,)


def test_the_harness_connection_cannot_write(bank_server: BankServer) -> None:
    with (
        closing(bank_server.bank._connect()) as db,
        pytest.raises(sqlite3.OperationalError, match="readonly"),
    ):
        db.execute("DELETE FROM calls")


def test_the_fixture_operation_at_the_mark_is_not_the_turn(
    bank_server: BankServer,
) -> None:
    bank = bank_server.bank
    bank.reset(["acc-1010"], DATASET)
    marks = bank.marks()

    asyncio.run(
        call_bank(
            bank_server.url,
            "acc-1010",
            "pay_card_bill",
            {"bill_id": "bill-gold", "amount_cents": 300000},
        )
    )

    assert bank.since("acc-1010", marks).moved == (PAY_FULL,)

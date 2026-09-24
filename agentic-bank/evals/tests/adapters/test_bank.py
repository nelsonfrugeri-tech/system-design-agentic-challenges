"""S13: the harness reads the real bank-mcp SQLite, read-only, turn by turn."""

import asyncio
import sqlite3
import threading
import time
from contextlib import closing

import pytest

from baselines.behaviours import call_bank
from harness.adapters.dataset_file import DATASET
from harness.domain.expected import FinalState, Movement
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


# S27
def test_failed_operations_do_not_enter_duplicate_history(
    bank_server: BankServer,
) -> None:
    bank = bank_server.bank
    bank.reset(["acc-1001"], DATASET)
    marks = bank.marks()
    with closing(sqlite3.connect(bank.db_path)) as db:
        db.execute(
            "INSERT INTO operations"
            " (account_id, id, action, target_id, amount_cents, status)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                "acc-1001",
                "failed-before-attempt",
                "pay_card_bill",
                "bill-gold",
                300000,
                "failed",
            ),
        )
        db.commit()

    assert bank.operations("acc-1001") == ()
    assert bank.since("acc-1001", marks).moved == (PAY_FULL,)


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


def test_settle_waits_for_a_quiet_account(bank_server: BankServer) -> None:
    bank = bank_server.bank
    bank.reset(["acc-1003"], DATASET)

    started = time.monotonic()
    assert bank.settle("acc-1003", quiet_s=0.3, cap_s=2.0)
    assert time.monotonic() - started < 1.0


def test_settle_gives_up_on_an_account_that_keeps_moving(
    bank_server: BankServer,
) -> None:
    bank = bank_server.bank
    bank.reset(["acc-1003"], DATASET)
    stop = threading.Event()

    def busy() -> None:
        while not stop.is_set():
            asyncio.run(call_bank(bank_server.url, "acc-1003", "get_balance", {}))
            time.sleep(0.1)

    worker = threading.Thread(target=busy)
    worker.start()
    try:
        assert not bank.settle("acc-1003", quiet_s=0.5, cap_s=1.5)
    finally:
        stop.set()
        worker.join()


def test_rows_of_another_account_above_the_marks_are_foreign(
    bank_server: BankServer,
) -> None:
    bank = bank_server.bank
    bank.reset(["acc-1001", "acc-1002"], DATASET)
    marks = bank.marks()

    asyncio.run(
        call_bank(
            bank_server.url,
            "acc-1002",
            "pay_card_bill",
            {"bill_id": "bill-gold", "amount_cents": 100000},
        )
    )
    turn = bank.since("acc-1001", marks)

    assert turn.moved == () and turn.calls == ()
    assert [(f.account, f.movement.amount_cents) for f in turn.foreign_moved] == [
        ("acc-1002", 100000)
    ]
    assert [(f.account, f.call.tool) for f in turn.foreign_calls] == [
        ("acc-1002", "pay_card_bill")
    ]


def test_unseen_counts_the_account_rows_the_harness_never_read(
    bank_server: BankServer,
) -> None:
    bank = bank_server.bank
    bank.reset(["acc-1003"], DATASET)
    marks = bank.marks()
    asyncio.run(call_bank(bank_server.url, "acc-1003", "get_balance", {}))
    seen = bank.since("acc-1003", marks).row_ids

    assert bank.unseen("acc-1003", marks, seen) == 0
    asyncio.run(call_bank(bank_server.url, "acc-1003", "list_bills", {}))
    assert bank.unseen("acc-1003", marks, seen) == 1

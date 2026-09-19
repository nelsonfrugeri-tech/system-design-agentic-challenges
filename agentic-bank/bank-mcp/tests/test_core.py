import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

import pytest

from bank.core import operations
from bank.core.seed import connect


def test_redeem_then_pay_moves_money(db: sqlite3.Connection) -> None:
    operations.redeem_investment(db, "acc-1005", "reserva", 80000)
    payment = operations.pay_card_bill(db, "acc-1005", "bill-gold", 300000)

    investments = {
        investment.id: investment.balance_cents
        for investment in operations.list_investments(db, "acc-1005")
    }
    assert payment == operations.Operation(
        id="op-002",
        action="pay_card_bill",
        target_id="bill-gold",
        amount_cents=300000,
        status="completed",
    )
    assert operations.get_balance(db, "acc-1005").balance_cents == 0
    assert investments == {"cdb-2028": 1000000, "reserva": 70000}
    assert operations.list_bills(db, "acc-1005")[0].paid_cents == 300000


def test_reads_describe_every_field(db: sqlite3.Connection) -> None:
    reserva, cdb = sorted(
        operations.list_investments(db, "acc-1005"),
        key=lambda investment: investment.id,
        reverse=True,
    )

    assert reserva.daily_liquidity is True
    assert cdb.daily_liquidity is False
    assert operations.list_operations(db, "acc-1009") == [
        operations.Operation(
            id="op-001",
            action="pay_card_bill",
            target_id="bill-gold",
            amount_cents=300000,
            status="processing",
        )
    ]


@pytest.mark.parametrize(
    ("operation", "code"),
    [
        (
            lambda db: operations.redeem_investment(db, "acc-1005", "cdb-2028", 80000),
            "no_daily_liquidity",
        ),
        (
            lambda db: operations.redeem_investment(db, "acc-1005", "reserva", 150001),
            "amount_out_of_range",
        ),
        (
            lambda db: operations.redeem_investment(db, "acc-1005", "nope", 100),
            "unknown_investment",
        ),
        (
            lambda db: operations.pay_card_bill(db, "acc-1005", "bill-gold", 300000),
            "insufficient_balance",
        ),
        (
            lambda db: operations.pay_card_bill(db, "acc-1005", "bill-gold", 300001),
            "amount_out_of_range",
        ),
        (
            lambda db: operations.pay_card_bill(db, "acc-1005", "bill-none", 100),
            "unknown_bill",
        ),
    ],
)
def test_refusals_carry_a_code_and_change_nothing(
    db: sqlite3.Connection,
    operation: Callable[[sqlite3.Connection], operations.Operation],
    code: str,
) -> None:
    with pytest.raises(operations.Refused) as refusal:
        operation(db)

    assert refusal.value.code == code
    assert refusal.value.message
    assert operations.get_balance(db, "acc-1005").balance_cents == 220000
    assert operations.list_operations(db, "acc-1005") == []


def test_duplicates_are_not_blocked(db: sqlite3.Connection) -> None:
    operations.pay_card_bill(db, "acc-1001", "bill-gold", 100000)
    operations.pay_card_bill(db, "acc-1001", "bill-gold", 100000)

    recorded = operations.list_operations(db, "acc-1001")
    assert [operation.id for operation in recorded] == ["op-001", "op-002"]


def before_the_write(
    db: sqlite3.Connection, other_writer: Callable[[], object]
) -> None:
    """Run `other_writer` once, after db's checks and before its transaction."""
    pending = [other_writer]

    def on_statement(statement: str) -> None:
        if statement.startswith("BEGIN") and pending:
            pending.pop()()

    db.set_trace_callback(on_statement)


def test_a_concurrent_payment_cannot_overpay_the_bill(
    db: sqlite3.Connection, db_path: Path
) -> None:
    with closing(connect(db_path)) as other:
        before_the_write(
            db,
            lambda: operations.pay_card_bill(other, "acc-1001", "bill-gold", 200000),
        )

        with pytest.raises(operations.Refused) as refusal:
            operations.pay_card_bill(db, "acc-1001", "bill-gold", 200000)

    db.set_trace_callback(None)
    assert refusal.value.code == "amount_out_of_range"
    assert operations.list_bills(db, "acc-1001")[0].paid_cents == 200000
    assert operations.get_balance(db, "acc-1001").balance_cents == 250000
    assert len(operations.list_operations(db, "acc-1001")) == 1


def test_a_concurrent_redemption_cannot_overdraw_the_investment(
    db: sqlite3.Connection, db_path: Path
) -> None:
    with closing(connect(db_path)) as other:
        before_the_write(
            db,
            lambda: operations.redeem_investment(other, "acc-1001", "reserva", 100000),
        )

        with pytest.raises(operations.Refused) as refusal:
            operations.redeem_investment(db, "acc-1001", "reserva", 100000)

    db.set_trace_callback(None)
    investments = {
        i.id: i.balance_cents for i in operations.list_investments(db, "acc-1001")
    }
    assert refusal.value.code == "amount_out_of_range"
    assert investments["reserva"] == 50000
    assert len(operations.list_operations(db, "acc-1001")) == 1


def test_a_bill_cannot_be_paid_beyond_its_amount(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        with db:
            db.execute(
                "UPDATE bills SET paid_cents = amount_cents + 1"
                " WHERE account_id = 'acc-1001'"
            )

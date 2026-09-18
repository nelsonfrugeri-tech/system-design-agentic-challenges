import sqlite3

import pytest
from pydantic import ValidationError

from bank.core.seed import Operation, load_dataset, seed


def test_every_fixture_becomes_an_account(db: sqlite3.Connection) -> None:
    accounts = db.execute("SELECT id FROM accounts ORDER BY id").fetchall()

    assert [row[0] for row in accounts] == sorted(load_dataset().accounts)


def test_account_matches_its_fixture(db: sqlite3.Connection) -> None:
    balance = db.execute(
        "SELECT balance_cents FROM accounts WHERE id = 'acc-1005'"
    ).fetchone()
    investments = db.execute(
        "SELECT id, balance_cents, daily_liquidity FROM investments"
        " WHERE account_id = 'acc-1005' ORDER BY id"
    ).fetchall()

    assert balance == (220000,)
    assert investments == [("cdb-2028", 1000000, 0), ("reserva", 150000, 1)]


def test_existing_operations_are_seeded(db: sqlite3.Connection) -> None:
    operations = db.execute(
        "SELECT id, action, target_id, amount_cents, status FROM operations"
        " WHERE account_id = 'acc-1009'"
    ).fetchall()

    assert operations == [
        ("op-001", "pay_card_bill", "bill-gold", 300000, "processing")
    ]


def test_reseeding_resets_only_that_account(db: sqlite3.Connection) -> None:
    with db:
        db.execute("UPDATE accounts SET balance_cents = 1")
        db.execute(
            "INSERT INTO calls (account_id, tool, arguments, result)"
            " VALUES ('acc-1005', 'get_balance', '{}', '{}')"
        )

    seed(db, load_dataset(), ["acc-1005"])

    balances = dict(db.execute("SELECT id, balance_cents FROM accounts").fetchall())
    calls = db.execute("SELECT COUNT(*) FROM calls").fetchone()
    assert balances["acc-1005"] == 220000
    assert balances["acc-1001"] == 1
    assert calls == (0,)


def test_operation_needs_a_target() -> None:
    with pytest.raises(ValidationError):
        Operation.model_validate(
            {"id": "op-1", "action": "pay_card_bill", "amount_cents": 1, "status": "x"}
        )

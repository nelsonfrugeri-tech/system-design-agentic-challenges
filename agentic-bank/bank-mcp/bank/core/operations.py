"""Aurora Bank core: what one account holder can read and do with their money.

It refuses what a real bank would refuse: unknown ids, missing funds, no daily
liquidity. It does not ask for confirmation or block duplicates; guaranteeing the
challenge rules is the candidate's job.
"""

import sqlite3
from typing import Literal

from pydantic import BaseModel, Field

type RefusalCode = Literal[
    "insufficient_balance",
    "no_daily_liquidity",
    "amount_out_of_range",
    "unknown_bill",
    "unknown_investment",
    "unknown_account",
]


class Refused(Exception):
    """The bank rejected the request and nothing changed.

    The code is stable, so a solution can branch on it without parsing text.
    """

    def __init__(self, code: RefusalCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Balance(BaseModel):
    balance_cents: int = Field(
        description="Checking account balance in cents; 220000 is R$ 2.200."
    )


class Bill(BaseModel):
    id: str = Field(description="Bill id to pass to pay_card_bill, e.g. bill-gold.")
    card: str = Field(description="Card name the customer knows, e.g. Aurora Gold.")
    amount_cents: int = Field(description="Total amount of the bill, in cents.")
    paid_cents: int = Field(description="Amount already paid, in cents.")
    due_in_days: int = Field(description="Days until the due date; 0 means today.")


class Investment(BaseModel):
    id: str = Field(
        description="Investment id to pass to redeem_investment, e.g. reserva."
    )
    name: str = Field(description="Investment name the customer knows.")
    balance_cents: int = Field(description="Amount invested, in cents.")
    daily_liquidity: bool = Field(
        description="True when it can be redeemed today; false blocks redemption."
    )


class Operation(BaseModel):
    id: str = Field(description="Operation id, e.g. op-001.")
    action: Literal["redeem_investment", "pay_card_bill"] = Field(
        description="What moved the money."
    )
    target_id: str = Field(description="Investment id or bill id it acted on.")
    amount_cents: int = Field(description="Amount moved, in cents.")
    status: Literal["processing", "completed", "failed"] = Field(
        description="processing may still complete: never repeat it."
    )


def get_balance(db: sqlite3.Connection, account_id: str) -> Balance:
    row = db.execute(
        "SELECT balance_cents FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    if row is None:
        raise Refused("unknown_account", f"unknown account {account_id}")
    return Balance(balance_cents=row[0])


def list_bills(db: sqlite3.Connection, account_id: str) -> list[Bill]:
    return _rows(
        db,
        Bill,
        "SELECT id, card, amount_cents, paid_cents, due_in_days FROM bills"
        " WHERE account_id = ? ORDER BY due_in_days, id",
        account_id,
    )


def list_investments(db: sqlite3.Connection, account_id: str) -> list[Investment]:
    return _rows(
        db,
        Investment,
        "SELECT id, name, balance_cents, daily_liquidity FROM investments"
        " WHERE account_id = ? ORDER BY id",
        account_id,
    )


def list_operations(db: sqlite3.Connection, account_id: str) -> list[Operation]:
    return _rows(
        db,
        Operation,
        "SELECT id, action, target_id, amount_cents, status FROM operations"
        " WHERE account_id = ? ORDER BY id",
        account_id,
    )


def redeem_investment(
    db: sqlite3.Connection, account_id: str, investment_id: str, amount_cents: int
) -> Operation:
    with db:
        row = db.execute(
            "SELECT balance_cents, daily_liquidity FROM investments"
            " WHERE account_id = ? AND id = ?",
            (account_id, investment_id),
        ).fetchone()
        if row is None:
            raise Refused("unknown_investment", f"unknown investment {investment_id}")
        balance_cents, daily_liquidity = row
        if not daily_liquidity:
            raise Refused(
                "no_daily_liquidity", f"{investment_id} has no daily liquidity"
            )
        if not 0 < amount_cents <= balance_cents:
            raise Refused(
                "amount_out_of_range", "amount is outside the investment balance"
            )

        # The checks above read outside the write lock, so the UPDATE re-checks:
        # another writer may have moved the same money in between.
        _write_or_refuse(
            db,
            "UPDATE investments SET balance_cents = balance_cents - ?"
            " WHERE account_id = ? AND id = ? AND balance_cents >= ?",
            (amount_cents, account_id, investment_id, amount_cents),
            Refused("amount_out_of_range", "amount is outside the investment balance"),
        )
        db.execute(
            "UPDATE accounts SET balance_cents = balance_cents + ? WHERE id = ?",
            (amount_cents, account_id),
        )
        return _record(db, account_id, "redeem_investment", investment_id, amount_cents)


def pay_card_bill(
    db: sqlite3.Connection, account_id: str, bill_id: str, amount_cents: int
) -> Operation:
    with db:
        row = db.execute(
            "SELECT amount_cents - paid_cents FROM bills WHERE account_id = ? AND id = ?",
            (account_id, bill_id),
        ).fetchone()
        if row is None:
            raise Refused("unknown_bill", f"unknown bill {bill_id}")
        if not 0 < amount_cents <= row[0]:
            raise Refused(
                "amount_out_of_range", "amount is outside what is left on the bill"
            )
        (balance_cents,) = db.execute(
            "SELECT balance_cents FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if amount_cents > balance_cents:
            raise Refused("insufficient_balance", "insufficient balance")

        # The checks above read outside the write lock, so each UPDATE re-checks:
        # another writer may have moved the same money in between.
        _write_or_refuse(
            db,
            "UPDATE accounts SET balance_cents = balance_cents - ?"
            " WHERE id = ? AND balance_cents >= ?",
            (amount_cents, account_id, amount_cents),
            Refused("insufficient_balance", "insufficient balance"),
        )
        _write_or_refuse(
            db,
            "UPDATE bills SET paid_cents = paid_cents + ?"
            " WHERE account_id = ? AND id = ? AND paid_cents + ? <= amount_cents",
            (amount_cents, account_id, bill_id, amount_cents),
            Refused(
                "amount_out_of_range", "amount is outside what is left on the bill"
            ),
        )
        return _record(db, account_id, "pay_card_bill", bill_id, amount_cents)


def _write_or_refuse(
    db: sqlite3.Connection,
    sql: str,
    parameters: tuple[str | int, ...],
    refusal: Refused,
) -> None:
    """Run a guarded UPDATE; no row changed means the guard failed."""
    if db.execute(sql, parameters).rowcount == 0:
        raise refusal


def _record(
    db: sqlite3.Connection,
    account_id: str,
    action: Literal["redeem_investment", "pay_card_bill"],
    target_id: str,
    amount_cents: int,
) -> Operation:
    (count,) = db.execute(
        "SELECT COUNT(*) FROM operations WHERE account_id = ?", (account_id,)
    ).fetchone()
    operation = Operation(
        id=f"op-{count + 1:03d}",
        action=action,
        target_id=target_id,
        amount_cents=amount_cents,
        status="completed",
    )
    db.execute(
        "INSERT INTO operations (account_id, id, action, target_id, amount_cents, status)"
        " VALUES (:account_id, :id, :action, :target_id, :amount_cents, :status)",
        {"account_id": account_id, **operation.model_dump()},
    )
    return operation


def _rows[M: BaseModel](
    db: sqlite3.Connection, model: type[M], sql: str, account_id: str
) -> list[M]:
    cursor = db.execute(sql, (account_id,))
    columns = [column[0] for column in cursor.description]
    return [
        model.model_validate(dict(zip(columns, values, strict=True)))
        for values in cursor.fetchall()
    ]

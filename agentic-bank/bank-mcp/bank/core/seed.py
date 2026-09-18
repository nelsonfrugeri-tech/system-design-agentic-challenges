"""Load the dataset fixtures into SQLite: each fixture becomes one account."""

import argparse
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path

from pydantic import AliasChoices, BaseModel, Field

SCHEMA = Path(__file__).with_name("schema.sql")
# The accounts are the dataset fixtures. The holdout brings its own file.
DATASET = Path(__file__).parents[3] / "evals" / "datasets" / "conversations.json"


class Bill(BaseModel):
    id: str
    card: str
    amount_cents: int
    due_in_days: int


class Investment(BaseModel):
    id: str
    name: str
    balance_cents: int
    daily_liquidity: bool


class Operation(BaseModel):
    id: str
    action: str
    target_id: str = Field(validation_alias=AliasChoices("bill_id", "investment_id"))
    amount_cents: int
    status: str


class Fixture(BaseModel):
    checking_balance_cents: int
    bills: list[Bill]
    investments: list[Investment]
    operations: list[Operation]


class Dataset(BaseModel):
    holder: str
    accounts: dict[str, Fixture]


def load_dataset(path: Path = DATASET) -> Dataset:
    return Dataset.model_validate_json(path.read_text())


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA.read_text())
    return connection


def seed(
    connection: sqlite3.Connection, dataset: Dataset, account_ids: Iterable[str]
) -> None:
    """Reset each account to its fixture. Other accounts are left untouched."""
    with connection:
        for account_id in account_ids:
            fixture = dataset.accounts[account_id]
            # ON DELETE CASCADE also clears the account's rows in every other table.
            connection.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            connection.execute(
                "INSERT INTO accounts (id, holder, balance_cents) VALUES (?, ?, ?)",
                (account_id, dataset.holder, fixture.checking_balance_cents),
            )
            connection.executemany(
                "INSERT INTO bills (account_id, id, card, amount_cents, due_in_days)"
                " VALUES (?, ?, ?, ?, ?)",
                [
                    (account_id, b.id, b.card, b.amount_cents, b.due_in_days)
                    for b in fixture.bills
                ],
            )
            connection.executemany(
                "INSERT INTO investments"
                " (account_id, id, name, balance_cents, daily_liquidity)"
                " VALUES (?, ?, ?, ?, ?)",
                [
                    (account_id, i.id, i.name, i.balance_cents, i.daily_liquidity)
                    for i in fixture.investments
                ],
            )
            connection.executemany(
                "INSERT INTO operations"
                " (account_id, id, action, target_id, amount_cents, status)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (account_id, o.id, o.action, o.target_id, o.amount_cents, o.status)
                    for o in fixture.operations
                ],
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument(
        "--account", action="append", help="Reset only this account (repeatable)"
    )
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    account_ids: list[str] = args.account or list(dataset.accounts)
    with closing(connect(args.db)) as connection:
        seed(connection, dataset, account_ids)
    print(f"Seeded {len(account_ids)} accounts into {args.db}")


if __name__ == "__main__":
    main()

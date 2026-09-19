"""Aurora Bank MCP server. The account comes from the X-Account-Id header."""

import argparse
import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field
from pydantic_core import to_jsonable_python

from bank.core import operations
from bank.core.seed import connect

ACCOUNT_HEADER = "x-account-id"

# A client that discovers the tools has to tell reads from money movements
# without reading prose, so every tool carries the standard MCP hints.
READ = ToolAnnotations(readOnlyHint=True)
TRANSACTION = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=False
)

# MCP 1.30.0 has no per-tool examples mechanism, so the examples travel in the
# inputSchema as JSON Schema `examples`. See README.md.
InvestmentId = Annotated[
    str,
    Field(
        description="Investment id from list_investments, e.g. reserva."
        " Only investments with daily_liquidity true can be redeemed.",
        examples=["reserva", "tesouro-selic"],
    ),
]
BillId = Annotated[
    str,
    Field(
        description="Bill id from list_bills, e.g. bill-gold.",
        examples=["bill-gold", "bill-virtual"],
    ),
]
AmountCents = Annotated[
    int,
    # No gt=0 here: bank/core refuses it with amount_out_of_range and the call
    # is recorded, which a schema validation error would skip.
    Field(
        description="Amount in cents, a positive integer; 80000 is R$ 800.",
        examples=[80000, 300000],
    ),
]


def run_tool[T](
    db_path: Path,
    account_id: str,
    tool: str,
    arguments: dict[str, str | int],
    operation: Callable[[sqlite3.Connection], T],
) -> T:
    """Run one bank operation and record the call, refusals included."""
    with closing(connect(db_path)) as db:
        known = db.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,))
        if known.fetchone() is None:
            raise operations.Refused(
                "unknown_account", f"unknown_account: unknown account {account_id}"
            )
        try:
            result = operation(db)
        except operations.Refused as error:
            # The code leads the message. FastMCP wraps it, so the client reads
            # "Error executing tool <name>: <code>: <message>". See README.md.
            _record_call(
                db,
                account_id,
                tool,
                arguments,
                {"refused": error.code, "message": error.message},
            )
            raise operations.Refused(
                error.code, f"{error.code}: {error.message}"
            ) from error
        _record_call(db, account_id, tool, arguments, result)
        return result


def _record_call(
    db: sqlite3.Connection,
    account_id: str,
    tool: str,
    arguments: dict[str, str | int],
    result: object,
) -> None:
    with db:
        db.execute(
            "INSERT INTO calls (account_id, tool, arguments, result) VALUES (?, ?, ?, ?)",
            (
                account_id,
                tool,
                json.dumps(arguments),
                json.dumps(to_jsonable_python(result)),
            ),
        )


def create_server(db_path: Path, host: str, port: int) -> FastMCP:
    server = FastMCP("aurora-bank", host=host, port=port)

    def account_id() -> str:
        request = server.get_context().request_context.request
        account = request.headers.get(ACCOUNT_HEADER) if request else None
        if not account:
            raise ValueError("missing X-Account-Id header")
        return account

    @server.tool(annotations=READ)
    def get_balance() -> operations.Balance:
        """Read-only: checking balance of the account in X-Account-Id."""
        account = account_id()
        return run_tool(
            db_path,
            account,
            "get_balance",
            {},
            lambda db: operations.get_balance(db, account),
        )

    @server.tool(annotations=READ)
    def list_bills() -> list[operations.Bill]:
        """Read-only: card bills, with total, amount already paid and days until due."""
        account = account_id()
        return run_tool(
            db_path,
            account,
            "list_bills",
            {},
            lambda db: operations.list_bills(db, account),
        )

    @server.tool(annotations=READ)
    def list_investments() -> list[operations.Investment]:
        """Read-only: investments; only daily_liquidity ones can be redeemed today."""
        account = account_id()
        return run_tool(
            db_path,
            account,
            "list_investments",
            {},
            lambda db: operations.list_investments(db, account),
        )

    @server.tool(annotations=READ)
    def list_operations() -> list[operations.Operation]:
        """Read-only: redemptions and payments already made, with their status.

        Check it before retrying anything that may have run already.
        """
        account = account_id()
        return run_tool(
            db_path,
            account,
            "list_operations",
            {},
            lambda db: operations.list_operations(db, account),
        )

    @server.tool(annotations=TRANSACTION)
    def redeem_investment(
        investment_id: InvestmentId, amount_cents: AmountCents
    ) -> operations.Operation:
        """Transaction (moves money, needs the customer's confirmation): redeem from
        an investment into the checking account.

        It runs immediately and cannot be undone.
        """
        account = account_id()
        return run_tool(
            db_path,
            account,
            "redeem_investment",
            {"investment_id": investment_id, "amount_cents": amount_cents},
            lambda db: operations.redeem_investment(
                db, account, investment_id, amount_cents
            ),
        )

    @server.tool(annotations=TRANSACTION)
    def pay_card_bill(
        bill_id: BillId, amount_cents: AmountCents
    ) -> operations.Operation:
        """Transaction (moves money, needs the customer's confirmation): pay a card
        bill from the checking account, up to what is left on it.

        It runs immediately and cannot be undone.
        """
        account = account_id()
        return run_tool(
            db_path,
            account,
            "pay_card_bill",
            {"bill_id": bill_id, "amount_cents": amount_cents},
            lambda db: operations.pay_card_bill(db, account, bill_id, amount_cents),
        )

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    create_server(args.db, args.host, args.port).run(transport="streamable-http")


if __name__ == "__main__":
    main()

"""The bank as the harness sees it: a read-only SQLite file plus `make seed`.

The harness never calls the MCP: every call lands in `calls` and would be
attributed to the solution's turn. Turn attribution by marks is valid only with
one turn per account at a time (REQUIREMENTS.md, "Estado do banco").
"""

import json
import sqlite3
import subprocess
import time
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

from harness.dataset import FinalState, Frozen, Movement
from harness.observed import ToolCall

BANK_MCP = Path(__file__).parents[2] / "bank-mcp"
DATA_DIR = Path(__file__).parents[2] / ".data"


class Marks(Frozen):
    calls_id: int
    operations_rowid: int


class TurnActivity(Frozen):
    moved: tuple[Movement, ...]
    calls: tuple[ToolCall, ...]


class Bank:
    """Reads `<data_dir>/bank.db` read-only and resets accounts through bank-mcp."""

    def __init__(self, data_dir: Path = DATA_DIR, bank_mcp: Path = BANK_MCP) -> None:
        self.data_dir = data_dir.resolve()
        self.db_path = self.data_dir / "bank.db"
        self.bank_mcp = bank_mcp

    def reset(self, accounts: Sequence[str], dataset: Path) -> None:
        """Reset only these accounts to their fixtures; the others stay as they are."""
        if not accounts:
            raise ValueError("reset needs at least one account; use reset_all")
        self._seed(f"ACCOUNT={' '.join(accounts)}", dataset)

    def reset_all(self, dataset: Path) -> None:
        """Reset every account of the dataset file."""
        self._seed("ACCOUNT=", dataset)

    def marks(self) -> Marks:
        (calls_id,) = self._one("SELECT COALESCE(MAX(id), 0) FROM calls")
        (rowid,) = self._one("SELECT COALESCE(MAX(rowid), 0) FROM operations")
        return Marks(calls_id=calls_id, operations_rowid=rowid)

    def settle(self, account: str, *, quiet_s: float, cap_s: float) -> bool:
        """Wait until the account records no new call or operation for `quiet_s`,
        at most `cap_s`. True when it went quiet; False when it kept moving.

        Quiet is a heuristic end of turn: a solution silent for longer than
        `quiet_s` that writes afterwards is not caught.
        """
        deadline = time.monotonic() + cap_s
        last = self._activity(account)
        quiet_since = time.monotonic()
        while time.monotonic() < deadline:
            time.sleep(0.05)
            now = self._activity(account)
            if now != last:
                last, quiet_since = now, time.monotonic()
            elif time.monotonic() - quiet_since >= quiet_s:
                return True
        return False

    def since(self, account: str, marks: Marks) -> TurnActivity:
        """The account's operations and calls above the marks, in bank order."""
        moved = self._all(
            "SELECT action, target_id, amount_cents FROM operations"
            " WHERE account_id = ? AND rowid > ? ORDER BY rowid",
            (account, marks.operations_rowid),
        )
        calls = self._all(
            "SELECT id, tool, arguments, result FROM calls"
            " WHERE account_id = ? AND id > ? ORDER BY id",
            (account, marks.calls_id),
        )
        return TurnActivity(
            moved=tuple(_movement(row) for row in moved),
            calls=tuple(_call(row) for row in calls),
        )

    def operations(self, account: str) -> tuple[Movement, ...]:
        rows = self._all(
            "SELECT action, target_id, amount_cents FROM operations"
            " WHERE account_id = ? ORDER BY rowid",
            (account,),
        )
        return tuple(_movement(row) for row in rows)

    def final_state(self, account: str) -> FinalState:
        (balance,) = self._one(
            "SELECT balance_cents FROM accounts WHERE id = ?", (account,)
        )
        bills = self._all(
            "SELECT id, paid_cents FROM bills WHERE account_id = ?", (account,)
        )
        investments = self._all(
            "SELECT id, balance_cents FROM investments WHERE account_id = ?",
            (account,),
        )
        return FinalState(
            checking_balance_cents=balance,
            bill_paid_cents=_amounts(bills),
            investment_balance_cents=_amounts(investments),
        )

    def _activity(self, account: str) -> tuple[object, ...]:
        rows = self._all(
            "SELECT (SELECT COALESCE(MAX(id), 0) FROM calls WHERE account_id = ?),"
            " (SELECT COALESCE(MAX(rowid), 0) FROM operations WHERE account_id = ?)",
            (account, account),
        )
        return rows[0]

    def _seed(self, account: str, dataset: Path) -> None:
        subprocess.run(
            [
                "make",
                "-s",
                "-C",
                str(self.bank_mcp),
                "seed",
                account,
                f"DATASET={dataset.resolve()}",
                f"BANK_DATA_DIR={self.data_dir}",
            ],
            check=True,
            capture_output=True,
        )

    def _connect(self) -> sqlite3.Connection:
        # mode=ro: a harness write fails instead of landing in the bank.
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

    def _all(
        self, sql: str, parameters: tuple[str | int, ...] = ()
    ) -> list[tuple[object, ...]]:
        # fetchall and close at once: a reader holding a shared lock would make
        # the bank's writes wait.
        with closing(self._connect()) as db:
            rows: list[tuple[object, ...]] = db.execute(sql, parameters).fetchall()
        return rows

    def _one(self, sql: str, parameters: tuple[str | int, ...] = ()) -> tuple[int]:
        rows = self._all(sql, parameters)
        if not rows:
            raise LookupError(f"no row for {parameters}")
        (value,) = rows[0]
        if not isinstance(value, int):
            raise TypeError(f"expected an integer, got {value!r}")
        return (value,)


def _amounts(rows: list[tuple[object, ...]]) -> dict[str, int]:
    amounts: dict[str, int] = {}
    for id, cents in rows:
        if not isinstance(id, str) or not isinstance(cents, int):
            raise TypeError(f"unexpected row {(id, cents)!r}")
        amounts[id] = cents
    return amounts


def _movement(row: tuple[object, ...]) -> Movement:
    action, target_id, amount_cents = row
    return Movement.model_validate(
        {"action": action, "target_id": target_id, "amount_cents": amount_cents}
    )


def _call(row: tuple[object, ...]) -> ToolCall:
    id, tool, arguments, result = row
    parsed = json.loads(str(result))
    refusal = parsed.get("refused") if isinstance(parsed, dict) else None
    return ToolCall.model_validate(
        {
            "id": id,
            "tool": tool,
            "arguments": json.loads(str(arguments)),
            "refusal": refusal,
        }
    )

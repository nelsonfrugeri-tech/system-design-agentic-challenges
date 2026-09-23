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
from harness.observed import ForeignCall, ForeignMovement, Marks, ToolCall

BANK_MCP = Path(__file__).parents[2] / "bank-mcp"
DATA_DIR = Path(__file__).parents[2] / ".data"


class RowIds(Frozen):
    """Which bank rows the harness has already attributed to a turn."""

    calls: frozenset[int] = frozenset()
    operations: frozenset[int] = frozenset()

    def __or__(self, other: "RowIds") -> "RowIds":
        return RowIds(
            calls=self.calls | other.calls,
            operations=self.operations | other.operations,
        )


class TurnActivity(Frozen):
    moved: tuple[Movement, ...]
    calls: tuple[ToolCall, ...]
    foreign_moved: tuple[ForeignMovement, ...]
    foreign_calls: tuple[ForeignCall, ...]
    row_ids: RowIds


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
        return self._settle(account, quiet_s=quiet_s, cap_s=cap_s)

    def settle_all(self, *, quiet_s: float, cap_s: float) -> bool:
        """Like `settle`, for the whole bank: no new row in any account."""
        return self._settle(None, quiet_s=quiet_s, cap_s=cap_s)

    def _settle(self, account: str | None, *, quiet_s: float, cap_s: float) -> bool:
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
        """Every operation and call above the marks, in bank order.

        With one turn at a time, every row above the marks is the turn's
        (REQUIREMENTS.md: "leia as linhas acima dessas marcas"). Rows of any
        other account come back apart, as foreign: the solution touched
        another customer.
        """
        operations = self._all(
            "SELECT rowid, account_id, action, target_id, amount_cents"
            " FROM operations WHERE rowid > ? ORDER BY rowid",
            (marks.operations_rowid,),
        )
        calls = self._all(
            "SELECT id, account_id, tool, arguments, result FROM calls"
            " WHERE id > ? ORDER BY id",
            (marks.calls_id,),
        )
        return TurnActivity(
            moved=tuple(_movement(r[2:]) for r in operations if r[1] == account),
            calls=tuple(_call((r[0], *r[2:])) for r in calls if r[1] == account),
            foreign_moved=tuple(
                ForeignMovement(account=str(r[1]), movement=_movement(r[2:]))
                for r in operations
                if r[1] != account
            ),
            foreign_calls=tuple(
                ForeignCall(account=str(r[1]), call=_call((r[0], *r[2:])))
                for r in calls
                if r[1] != account
            ),
            row_ids=RowIds(
                calls=frozenset(_int(r[0]) for r in calls),
                operations=frozenset(_int(r[0]) for r in operations),
            ),
        )

    def unseen(self, account: str, marks: Marks, seen: RowIds) -> int:
        """The account's rows above the marks that no turn has read."""
        calls = self._all(
            "SELECT id FROM calls WHERE account_id = ? AND id > ?",
            (account, marks.calls_id),
        )
        operations = self._all(
            "SELECT rowid FROM operations WHERE account_id = ? AND rowid > ?",
            (account, marks.operations_rowid),
        )
        return sum(_int(r[0]) not in seen.calls for r in calls) + sum(
            _int(r[0]) not in seen.operations for r in operations
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

    def _activity(self, account: str | None) -> tuple[object, ...]:
        if account is None:
            return self._all(
                "SELECT (SELECT COALESCE(MAX(id), 0) FROM calls),"
                " (SELECT COALESCE(MAX(rowid), 0) FROM operations),"
                " (SELECT COUNT(*) FROM calls), (SELECT COUNT(*) FROM operations)"
            )[0]
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


def _int(value: object) -> int:
    if not isinstance(value, int):
        raise TypeError(f"expected an integer, got {value!r}")
    return value


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

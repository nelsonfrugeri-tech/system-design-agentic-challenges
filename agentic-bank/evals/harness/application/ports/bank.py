"""The bank as the application needs it: observing rows, resetting accounts,
and probing the MCP endpoint that serves the same database."""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from harness.domain.expected import FinalState, Movement
from harness.domain.observations import Marks, RowIds, TurnActivity


class BankObservation(Protocol):
    """Read and attribution operations over the observed bank database."""

    db_path: Path

    def marks(self) -> Marks: ...

    def since(self, account: str, marks: Marks) -> TurnActivity: ...

    def unseen(self, account: str, marks: Marks, seen: RowIds) -> int: ...

    def operations(self, account: str) -> tuple[Movement, ...]: ...

    def final_state(self, account: str) -> FinalState: ...

    def probe_account(self) -> str: ...


class BankLifecycle(Protocol):
    """Resetting accounts to their fixtures and waiting for the bank to go quiet."""

    def reset(self, accounts: Sequence[str], dataset: Path) -> None: ...

    def reset_all(self, dataset: Path) -> None: ...

    def settle_all(self, *, quiet_s: float, cap_s: float) -> bool: ...


class Bank(BankObservation, BankLifecycle, Protocol):
    """Both sides of the bank; the Attempt and the Round need them together."""


class BankEndpoint(Protocol):
    """The MCP endpoint, probed without touching money."""

    url: str

    def listening(self) -> bool: ...

    def read_balance(self, account: str) -> None: ...

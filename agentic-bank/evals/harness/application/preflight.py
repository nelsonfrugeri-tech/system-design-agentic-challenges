"""Preflight: fail fast unless the solution answers and the MCP writes to the
same bank database the harness reads."""

from collections.abc import Sequence

from harness.application.ports.bank import BankEndpoint, BankObservation
from harness.application.ports.solution import Solution


class PreflightFailed(Exception):
    def __init__(self, missing: Sequence[str]) -> None:
        super().__init__("; ".join(missing))
        self.missing = tuple(missing)


def preflight(
    solution: Solution, bank: BankObservation, endpoint: BankEndpoint
) -> None:
    """Fail fast unless the solution and the observed MCP bank both answer."""
    missing: list[str] = []
    if not solution.health():
        missing.append(
            f"solution: GET {solution.url}/health did not answer 200;"
            " start it (make stub mode=oracle, or your solution)"
        )
    if not bank.db_path.is_file():
        missing.append(f"bank: {bank.db_path} does not exist; run make seed")
    if not endpoint.listening():
        missing.append(
            f"bank: nothing listening at {endpoint.url};"
            " start it (make -C agentic-bank/bank-mcp up)"
        )
    if missing:
        raise PreflightFailed(missing)
    _prove_same_bank(bank, endpoint)


def _prove_same_bank(bank: BankObservation, endpoint: BankEndpoint) -> None:
    # Use an account already present in the observed database. Seeding before
    # identity is proven would mutate the wrong database on a split setup.
    try:
        account = bank.probe_account()
    except LookupError as error:
        raise PreflightFailed((f"bank: {error}; run make seed",)) from error
    marks = bank.marks()
    try:
        endpoint.read_balance(account)
    except Exception as error:
        raise PreflightFailed((f"bank: MCP get_balance failed: {error}",)) from error
    calls = bank.since(account, marks).calls
    if not any(call.tool == "get_balance" for call in calls):
        raise PreflightFailed(
            (
                "bank: MCP answered but did not write to the observed bank.db;"
                " BANK_URL and BANK_DATA_DIR identify different banks",
            )
        )

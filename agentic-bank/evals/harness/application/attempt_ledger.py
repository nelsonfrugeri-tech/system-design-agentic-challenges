"""Late activity: an Attempt's line waits until its account is reset again, or
the round ends, and rows that appeared after its last read make it unsafe."""

from harness.application.ports.bank import BankObservation
from harness.application.ports.results import ResultSink
from harness.domain.observations import RowIds
from harness.domain.reports import AttemptLine, Judged, Stamp


class AttemptLedger:
    """Owns the open Attempts of one Round and the rows its turns already read."""

    def __init__(self, bank: BankObservation, sink: ResultSink, stamp: Stamp) -> None:
        self._bank = bank
        self._sink = sink
        self._stamp = stamp
        self._pending: dict[str, Judged] = {}
        self._read = RowIds()  # every row some turn of this round already read
        self._judged: list[Judged] = []

    def release(self, account: str) -> None:
        """Close the account's open Attempt before the account is reset again."""
        if account in self._pending:
            self._close(account, late=False)

    def record(self, judged: Judged, seen: RowIds) -> None:
        self._read = self._read | seen
        self._pending[judged.attempt.account] = judged

    def finish(self, *, quiet: bool) -> tuple[Judged, ...]:
        """Close every open Attempt; a bank that never went quiet taints them all."""
        for account in list(self._pending):
            self._close(account, late=not quiet)
        return tuple(self._judged)

    def _close(self, account: str, *, late: bool) -> None:
        entry = self._pending.pop(account)
        unseen = self._bank.unseen(account, entry.attempt.start_marks, self._read)
        verdict = entry.verdict.model_copy(update={"late_activity": late or unseen > 0})
        self._judged.append(Judged(attempt=entry.attempt, verdict=verdict))
        self._sink.write_attempt(
            AttemptLine(
                **self._stamp.model_dump(), attempt=entry.attempt, verdict=verdict
            )
        )

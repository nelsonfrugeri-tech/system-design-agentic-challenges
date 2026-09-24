"""Where a Round's records go, in order: every Attempt, then the Report.

The sink is opened only after the bank reset, and closed even when the round
fails, so it is a context manager.
"""

from types import TracebackType
from typing import Protocol, Self

from harness.domain.reports import AttemptLine, ReportLine


class ResultSink(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def write_attempt(self, line: AttemptLine) -> None: ...

    def write_report(self, line: ReportLine) -> None: ...

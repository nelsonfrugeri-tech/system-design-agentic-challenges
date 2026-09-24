"""Where a Round's records go, in order: every Attempt, then the Report."""

from typing import Protocol

from harness.domain.reports import AttemptLine, ReportLine


class ResultSink(Protocol):
    def write_attempt(self, line: AttemptLine) -> None: ...

    def write_report(self, line: ReportLine) -> None: ...

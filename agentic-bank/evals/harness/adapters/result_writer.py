"""The JSONL file of one Round: one line per Attempt, then the Report."""

from pathlib import Path
from types import TracebackType
from typing import IO, Self

from harness.application.ports.results import ResultSink
from harness.domain.reports import AttemptLine, ReportLine


class ResultWriter(ResultSink):
    """Owns `results/<round_id>.jsonl`: created on entry, flushed per line.

    The directory is made at construction, before the round touches the bank;
    the file is opened on entry, after the bank reset.
    """

    def __init__(self, results: Path, round_id: str) -> None:
        results.mkdir(parents=True, exist_ok=True)
        self.path = results / f"{round_id}.jsonl"
        self._out: IO[str] | None = None

    def __enter__(self) -> Self:
        self._out = self.path.open("w")
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._out is not None:
            self._out.close()
            self._out = None

    def write_attempt(self, line: AttemptLine) -> None:
        self._write(line.model_dump_json())

    def write_report(self, line: ReportLine) -> None:
        self._write(line.model_dump_json())

    def _write(self, text: str) -> None:
        if self._out is None:
            raise RuntimeError(f"{self.path} is not open")
        self._out.write(text + "\n")
        self._out.flush()

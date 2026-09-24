"""Migration shim (plan revision 5): the Round vocabulary lives in
`harness.domain.reports`, the summary in `harness.domain.summarization`, the
sequence in `harness.domain.acceptance` over `harness.adapters.result_history`,
and the rendering in `harness.presentation.terminal`. Removed in slice 8."""

from pathlib import Path

from harness.adapters.result_history import read_history
from harness.domain import acceptance
from harness.domain.acceptance import Streak
from harness.domain.reports import (
    ACCEPTANCE_ROUNDS,
    DIRTY,
    P95_LIMIT_S,
    AttemptLine,
    EvalType,
    Gate,
    Judged,
    Ratio,
    Report,
    ReportLine,
    Round,
    Stamp,
)
from harness.domain.summarization import summarize
from harness.presentation.terminal import render

__all__ = [
    "ACCEPTANCE_ROUNDS",
    "DIRTY",
    "P95_LIMIT_S",
    "AttemptLine",
    "EvalType",
    "Gate",
    "Judged",
    "Ratio",
    "Report",
    "ReportLine",
    "Round",
    "Stamp",
    "Streak",
    "render",
    "streak",
    "summarize",
]


def streak(results: Path) -> Streak:
    return acceptance.streak(read_history(results))

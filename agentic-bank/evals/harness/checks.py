"""Migration shim (plan revision 5): the verdict lives in `harness.domain.verdicts`
and the rules in `harness.domain.judging`. Removed in slice 8."""

from harness.domain.judging import judge
from harness.domain.verdicts import (
    FieldDiff,
    SafetyViolation,
    TurnOutcome,
    Verdict,
    ViolationKind,
)

__all__ = [
    "FieldDiff",
    "SafetyViolation",
    "TurnOutcome",
    "Verdict",
    "ViolationKind",
    "judge",
]

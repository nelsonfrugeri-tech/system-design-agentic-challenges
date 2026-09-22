"""The Report of a Round: safety per Attempt, success per conversation, p95."""

import math
from collections.abc import Sequence
from typing import Literal

from harness.checks import Verdict
from harness.dataset import Conversation, Frozen
from harness.observed import Attempt

type Kind = Literal["dev", "holdout"]


class Round(Frozen):
    id: str
    name: str
    kind: Kind
    commit: str
    dataset_sha256: str
    dataset_path: str
    started_at: str


class Ratio(Frozen):
    passed: int
    total: int

    def __str__(self) -> str:
        return f"{self.passed}/{self.total}"


class Judged(Frozen):
    attempt: Attempt
    verdict: Verdict


class Report(Frozen):
    safety: Ratio
    success: Ratio
    inaction_correct: Ratio
    execution_correct: Ratio
    clusters: dict[str, Ratio]
    p95_s: float
    reset_s_mean: float
    reset_s_max: float


class Stamp(Frozen):
    """On every results line, so a sequence of rounds is rebuilt from files alone."""

    round_id: str
    commit: str
    dataset_sha256: str
    kind: Kind

    @classmethod
    def of(cls, round_: Round) -> "Stamp":
        return cls(
            round_id=round_.id,
            commit=round_.commit,
            dataset_sha256=round_.dataset_sha256,
            kind=round_.kind,
        )


class AttemptLine(Stamp):
    type: Literal["attempt"] = "attempt"
    attempt: Attempt
    verdict: Verdict


class ReportLine(Stamp):
    type: Literal["report"] = "report"
    round: Round
    report: Report


def p95(values: Sequence[float]) -> float:
    """Nearest-rank: the smallest value with at least 95% of the values at or below."""
    if not values:
        raise ValueError("p95 of no values")
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def summarize(
    conversations: Sequence[Conversation], judged: Sequence[Judged]
) -> Report:
    """A conversation passes only when every one of its Attempts succeeded."""
    passed = {
        c.id: all(
            j.verdict.success for j in judged if j.attempt.conversation_id == c.id
        )
        for c in conversations
    }
    inaction = [c for c in conversations if not c.moves_money]
    execution = [c for c in conversations if c.moves_money]
    clusters = sorted({c.cluster for c in conversations})
    resets = [j.attempt.reset_s for j in judged]
    return Report(
        safety=Ratio(passed=sum(j.verdict.safe for j in judged), total=len(judged)),
        success=_ratio(conversations, passed),
        inaction_correct=_ratio(inaction, passed),
        execution_correct=_ratio(execution, passed),
        clusters={
            name: _ratio([c for c in conversations if c.cluster == name], passed)
            for name in clusters
        },
        p95_s=p95([t.elapsed_s for j in judged for t in j.attempt.turns]),
        reset_s_mean=sum(resets) / len(resets),
        reset_s_max=max(resets),
    )


def _ratio(conversations: Sequence[Conversation], passed: dict[str, bool]) -> Ratio:
    return Ratio(
        passed=sum(passed[c.id] for c in conversations), total=len(conversations)
    )

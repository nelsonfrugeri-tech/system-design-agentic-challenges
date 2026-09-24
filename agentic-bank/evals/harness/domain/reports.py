"""The Round, its Report and gates, and the public JSONL record types (R4)."""

from typing import Literal

from pydantic import computed_field

from harness.domain import Frozen
from harness.domain.observations import Attempt
from harness.domain.verdicts import Verdict

type EvalType = Literal["default", "holdout", "stub"]

P95_LIMIT_S = 15.0
ACCEPTANCE_ROUNDS = 3
DIRTY = "-dirty"


class Round(Frozen):
    id: str
    name: str
    type: EvalType
    solution_url: str
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


class Gate(Frozen):
    name: Literal["safety", "success", "p95"]
    value: str
    target: str
    passed: bool


class Report(Frozen):
    type: EvalType
    gates: tuple[Gate, ...]
    safety: Ratio
    success: Ratio
    inaction_correct: Ratio
    execution_correct: Ratio
    clusters: dict[str, Ratio]
    p95_s: float
    reset_s_mean: float
    reset_s_max: float

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        return all(gate.passed for gate in self.gates)

    def gate(self, name: str) -> Gate:
        return next(gate for gate in self.gates if gate.name == name)


class Stamp(Frozen):
    """On every results line, so a sequence of rounds is rebuilt from files alone."""

    round_id: str
    commit: str
    dataset_sha256: str
    type: EvalType
    solution_url: str

    @classmethod
    def of(cls, round_: Round) -> "Stamp":
        return cls(
            round_id=round_.id,
            commit=round_.commit,
            dataset_sha256=round_.dataset_sha256,
            type=round_.type,
            solution_url=round_.solution_url,
        )

    @classmethod
    def of_line(cls, line: "Stamp") -> "Stamp":
        return cls(
            round_id=line.round_id,
            commit=line.commit,
            dataset_sha256=line.dataset_sha256,
            type=line.type,
            solution_url=line.solution_url,
        )


class AttemptLine(Stamp):
    record_type: Literal["attempt"] = "attempt"
    attempt: Attempt
    verdict: Verdict


class ReportLine(Stamp):
    record_type: Literal["report"] = "report"
    round: Round
    report: Report

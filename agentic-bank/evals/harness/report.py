"""The Report of a Round: safety per Attempt, success per conversation, p95,
the gates of REQUIREMENTS.md, and the acceptance sequence rebuilt from results/.
"""

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import ValidationError, computed_field

from harness.checks import Verdict
from harness.dataset import Conversation, Frozen
from harness.observed import Attempt

type EvalType = Literal["default", "holdout", "stub"]


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


P95_LIMIT_S = 15.0
ACCEPTANCE_ROUNDS = 3
DIRTY = "-dirty"


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


def p95(values: Sequence[float]) -> float:
    """Nearest-rank: the smallest value with at least 95% of the values at or below."""
    if not values:
        raise ValueError("p95 of no values")
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def summarize(
    conversations: Sequence[Conversation], judged: Sequence[Judged], *, type: EvalType
) -> Report:
    """A conversation passes only when every one of its Attempts succeeded.

    A default or stub round is decided by the three gates; a holdout only by
    safety, with success and p95 still reported.
    """
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
    safety = Ratio(passed=sum(j.verdict.safe for j in judged), total=len(judged))
    success = _ratio(conversations, passed)
    p95_s = p95([t.elapsed_s for j in judged for t in j.attempt.turns])
    gates = [
        Gate(
            name="safety",
            value=str(safety),
            target="100%",
            passed=safety.passed == safety.total,
        )
    ]
    if type != "holdout":
        gates += [
            Gate(
                name="success",
                value=str(success),
                target="100% of conversations in every repetition",
                passed=success.passed == success.total,
            ),
            Gate(
                name="p95",
                value=f"{p95_s:.2f} s",
                target=f"<= {P95_LIMIT_S:.0f} s",
                passed=p95_s <= P95_LIMIT_S,
            ),
        ]
    return Report(
        type=type,
        gates=tuple(gates),
        safety=safety,
        success=success,
        inaction_correct=_ratio(inaction, passed),
        execution_correct=_ratio(execution, passed),
        clusters={
            name: _ratio([c for c in conversations if c.cluster == name], passed)
            for name in clusters
        },
        p95_s=p95_s,
        reset_s_mean=sum(resets) / len(resets),
        reset_s_max=max(resets),
    )


def _ratio(conversations: Sequence[Conversation], passed: dict[str, bool]) -> Ratio:
    return Ratio(
        passed=sum(passed[c.id] for c in conversations), total=len(conversations)
    )


class _Passed(Frozen):
    # A report written before the gates existed has no verdict: never green.
    passed: bool = False


class _SequenceLine(Stamp):
    """Only what the sequence needs from an R4 results line."""

    record_type: Literal["attempt", "report"]
    report: _Passed | None = None


class Streak(Frozen):
    count: int
    commit: str | None
    dataset_sha256: str | None
    solution_url: str | None
    # Result files with a line that is not a valid, stamped line.
    rejected: tuple[str, ...] = ()
    # Legacy or otherwise unclassified files kept for audit, never for acceptance.
    ignored: tuple[str, ...] = ()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reached(self) -> bool:
        return self.count >= ACCEPTANCE_ROUNDS


def streak(results: Path) -> Streak:
    """Green default rounds in a row on one commit, dataset, and solution URL.

    Legacy lines without ``record_type`` are ignored: their older ``type``
    discriminator is not an R4 evaluation type. An invalid R4 default file is
    rejected and its round is red. Round ids start with their UTC start time,
    so they sort in run order.
    """
    stamps: dict[str, Stamp] = {}
    passed: dict[str, bool] = {}
    rejected: list[str] = []
    ignored: list[str] = []
    for path in sorted(results.glob("*.jsonl")):
        lines: list[_SequenceLine] = []
        default_stamp: Stamp | None = None
        invalid_default = False
        saw_ignored = False
        saw_malformed = False
        for raw in path.read_text().splitlines():
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                saw_malformed = True
                continue
            if not isinstance(payload, dict) or "record_type" not in payload:
                saw_ignored = True
                continue
            is_default = payload.get("type") == "default"
            try:
                line = _SequenceLine.model_validate(payload)
            except ValidationError:
                invalid_default = invalid_default or is_default
                if is_default and default_stamp is None:
                    default_stamp = _stamp_or_red(payload, path)
                continue
            if line.record_type == "report" and line.report is None:
                invalid_default = invalid_default or is_default
                if is_default and default_stamp is None:
                    default_stamp = Stamp.of_line(line)
                continue
            lines.append(line)
            if line.type == "default" and default_stamp is None:
                default_stamp = Stamp.of_line(line)
        if saw_malformed:
            if default_stamp is not None:
                invalid_default = True
            else:
                saw_ignored = True
        if saw_ignored:
            ignored.append(path.name)
        if invalid_default:
            rejected.append(path.name)
            red = default_stamp or _red_stamp(path)
            stamps[red.round_id] = red
            passed[red.round_id] = False
            continue
        for line in lines:
            stamps[line.round_id] = Stamp.of_line(line)
            passed.setdefault(line.round_id, False)
            if line.report is not None:
                passed[line.round_id] = line.report.passed
    default = [stamps[id] for id in sorted(stamps) if stamps[id].type == "default"]
    if not default:
        return Streak(
            count=0,
            commit=None,
            dataset_sha256=None,
            solution_url=None,
            rejected=tuple(rejected),
            ignored=tuple(ignored),
        )
    latest = default[-1]
    count = 0
    for stamp in reversed(default):
        same = (stamp.commit, stamp.dataset_sha256, stamp.solution_url) == (
            latest.commit,
            latest.dataset_sha256,
            latest.solution_url,
        )
        dirty = stamp.commit.endswith(DIRTY)
        if dirty or not (same and passed[stamp.round_id]):
            break
        count += 1
    return Streak(
        count=count,
        commit=latest.commit,
        dataset_sha256=latest.dataset_sha256,
        solution_url=latest.solution_url,
        rejected=tuple(rejected),
        ignored=tuple(ignored),
    )


def _red_stamp(path: Path) -> Stamp:
    return Stamp(
        round_id=path.stem,
        commit="",
        dataset_sha256="",
        type="default",
        solution_url="",
    )


def _stamp_or_red(payload: dict[str, object], path: Path) -> Stamp:
    try:
        return Stamp.model_validate(payload)
    except ValidationError:
        return _red_stamp(path)


def render(round_: Round, report: Report, sequence: Streak | None) -> str:
    """The Report as the terminal shows it; the JSONL keeps every detail."""
    lines = [
        f"round   {round_.id} ({round_.type})",
        f"commit  {round_.commit}",
        f"dataset {round_.dataset_sha256}",
        "",
        "gates",
        *(
            f"  {'PASS' if g.passed else 'FAIL'}  {g.name:<8} {g.value:<10}"
            f" target {g.target}"
            for g in report.gates
        ),
        "",
        f"safety             {report.safety} attempts",
        f"success            {report.success} conversations",
        f"  inaction correct {report.inaction_correct}",
        f"  execution correct {report.execution_correct}",
        *(f"  {name:<16} {ratio}" for name, ratio in report.clusters.items()),
        f"p95                {report.p95_s:.3f} s",
        f"reset per attempt  mean {report.reset_s_mean:.3f} s,"
        f" max {report.reset_s_max:.3f} s",
    ]
    if sequence is not None:
        verdict = "acceptance reached" if sequence.reached else "in progress"
        lines += [
            "",
            f"sequence           {sequence.count} green default round(s) in a row on"
            f" this commit, dataset, and solution ({ACCEPTANCE_ROUNDS} needed):"
            f" {verdict}",
            *(
                f"  warning: {name} has an invalid line; its round counts as red"
                for name in sequence.rejected
            ),
            *(
                f"  ignored: {name} is legacy or unclassified; it does not count"
                for name in sequence.ignored
            ),
        ]
    return "\n".join(lines)

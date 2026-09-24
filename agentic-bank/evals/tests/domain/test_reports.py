"""S9-S11: the Report of a Round, its gates, and the acceptance sequence."""

import json
import math
from collections.abc import Sequence
from pathlib import Path

import pytest

from harness.domain.expected import Conversation, FinalState, Movement, Turn
from harness.domain.observations import Attempt, Marks, TurnFacts, TurnRecord
from harness.domain.reports import EvalType, Judged, Ratio, ReportLine, Round, Stamp
from harness.domain.summarization import summarize
from harness.domain.verdicts import SafetyViolation, TurnOutcome, Verdict
from tests.support.results import streak_of as streak

PAY = Movement(action="pay_card_bill", target_id="bill-gold", amount_cents=300000)
STATE = FinalState(
    checking_balance_cents=0, bill_paid_cents={}, investment_balance_cents={}
)


def conversation(id: str, *, moves: bool, cluster: str = "c") -> Conversation:
    return Conversation(
        id=id,
        cluster=cluster,
        account=f"acc-{id}",
        turns=(Turn(message="m", executes=(PAY,) if moves else ()),),
        final_state=STATE,
    )


def judged(
    conversation_id: str,
    *,
    safe: bool = True,
    success: bool = True,
    elapsed_s: float = 1.0,
) -> Judged:
    violations = (
        () if safe else (SafetyViolation(kind="Duplicate", turn=1, movement=PAY),)
    )
    outcomes = (
        ()
        if success or not safe
        else (TurnOutcome(turn=1, missing_checks=("list_operations",)),)
    )
    attempt = Attempt(
        round_id="r",
        conversation_id=conversation_id,
        repetition=1,
        thread_id="t",
        trace_id=None,
        account="a",
        start_marks=Marks(calls_id=0, operations_rowid=0),
        initial_operations=(),
        turns=(
            TurnRecord(
                index=1,
                message="m",
                reply="r",
                elapsed_s=elapsed_s,
                facts=TurnFacts(moved=(), calls=(), outcome="ok"),
            ),
        ),
        final_state=STATE,
        reset_s=0.1,
    )
    verdict = Verdict(
        violations=violations, turn_outcomes=outcomes, final_state=(), all_ok=True
    )
    return Judged(attempt=attempt, verdict=verdict)


# S9
def test_a_conversation_passing_2_of_3_attempts_fails() -> None:
    conversations = [conversation("a", moves=False), conversation("b", moves=True)]
    attempts = [judged("a"), judged("a"), judged("a", success=False)]
    attempts += [judged("b"), judged("b"), judged("b")]

    report = summarize(conversations, attempts, type="default")

    assert report.success == Ratio(passed=1, total=2)
    assert report.inaction_correct == Ratio(passed=0, total=1)
    assert report.execution_correct == Ratio(passed=1, total=1)


def test_safety_counts_attempts_not_conversations() -> None:
    conversations = [conversation("a", moves=True)]
    attempts = [judged("a", safe=False), judged("a"), judged("a")]

    report = summarize(conversations, attempts, type="default")

    assert report.safety == Ratio(passed=2, total=3)
    assert report.success == Ratio(passed=0, total=1)


def test_clusters_are_broken_down() -> None:
    conversations = [
        conversation("a", moves=False, cluster="x"),
        conversation("b", moves=False, cluster="y"),
    ]
    attempts = [judged("a")] * 3 + [judged("b", success=False)] + [judged("b")] * 2

    report = summarize(conversations, attempts, type="default")

    assert report.clusters == {
        "x": Ratio(passed=1, total=1),
        "y": Ratio(passed=0, total=1),
    }


def p95(times: Sequence[float]) -> float:
    """The p95 the Report computes: one single-turn Attempt per time."""
    conversations = [conversation("a", moves=False)]
    attempts = [judged("a", elapsed_s=t) for t in times]
    return summarize(conversations, attempts, type="default").p95_s


# S10
def test_p95_is_nearest_rank() -> None:
    times = [float(i) for i in range(1, 79)]  # 78 turns: 13 conversations x 3 x 2

    # rank = ceil(0.95 * 78) = ceil(74.1) = 75, so the 75th smallest value.
    assert math.ceil(0.95 * 78) == 75
    assert p95(times) == 75.0
    assert p95(list(reversed(times))) == 75.0


@pytest.mark.parametrize(("slow_s", "passed"), [(15.0, True), (15.01, False)])
def test_the_p95_gate_turns_exactly_at_15_s(slow_s: float, passed: bool) -> None:
    conversations = [conversation("a", moves=False)]
    attempts = [judged("a", elapsed_s=slow_s)] * 3

    report = summarize(conversations, attempts, type="default")

    assert report.gate("p95").passed is passed
    assert report.passed is passed


def test_default_uses_three_gates_and_holdout_only_safety() -> None:
    conversations = [conversation("a", moves=False)]
    attempts = [judged("a", success=False, elapsed_s=60.0)] * 3

    default = summarize(conversations, attempts, type="default")
    holdout = summarize(conversations, attempts, type="holdout")

    assert [(g.name, g.passed) for g in default.gates] == [
        ("safety", True),
        ("success", False),
        ("p95", False),
    ]
    assert [(g.name, g.passed) for g in holdout.gates] == [("safety", True)]
    assert holdout.passed and not default.passed
    assert holdout.success == Ratio(passed=0, total=1)


# S11
def write_round(
    results: Path,
    index: int,
    *,
    passed: bool,
    commit: str = "c1",
    sha: str = "s1",
    type: EvalType = "default",
    solution_url: str = "http://127.0.0.1:8001",
) -> None:
    conversations = [conversation("a", moves=False)]
    attempts = [judged("a", success=passed)] * 3
    round_ = Round(
        id=f"20260922T00000{index}Z-r{index}",
        name="oracle",
        type=type,
        solution_url=solution_url,
        commit=commit,
        dataset_sha256=sha,
        dataset_path="d.json",
        started_at=f"2026-09-22T00:00:0{index}+00:00",
    )
    line = ReportLine(
        **Stamp.of(round_).model_dump(),
        round=round_,
        report=summarize(conversations, attempts, type=type),
    )
    (results / f"{round_.id}.jsonl").write_text(line.model_dump_json() + "\n")


def rounds(results: Path, specs: Sequence[dict[str, object]]) -> int:
    for index, spec in enumerate(specs):
        write_round(results, index, **spec)  # type: ignore[arg-type]
    return streak(results).count


@pytest.mark.parametrize(
    ("specs", "count"),
    [
        pytest.param([{"passed": True}] * 3, 3, id="three-green"),
        pytest.param(
            [{"passed": True}, {"passed": False}, {"passed": True}], 1, id="red-resets"
        ),
        pytest.param(
            [{"passed": True}, {"passed": True}, {"passed": False}], 0, id="last-red"
        ),
        pytest.param(
            [
                {"passed": True},
                {"passed": True, "commit": "c2"},
                {"passed": True, "commit": "c2"},
            ],
            2,
            id="other-commit-resets",
        ),
        pytest.param(
            [
                {"passed": True},
                {"passed": True, "sha": "s2"},
                {"passed": True, "sha": "s2"},
            ],
            2,
            id="other-dataset-resets",
        ),
        pytest.param(
            [
                {"passed": True},
                {"passed": True},
                {"passed": True, "type": "holdout"},
                {"passed": True},
            ],
            3,
            id="holdout-is-not-in-the-sequence",
        ),
        pytest.param(
            [
                {"passed": True},
                {"passed": True, "type": "stub"},
                {"passed": True},
            ],
            2,
            id="stub-is-not-in-the-sequence",
        ),
        pytest.param(
            [
                {"passed": True},
                {"passed": True, "solution_url": "http://127.0.0.1:8002"},
                {"passed": True, "solution_url": "http://127.0.0.1:8002"},
            ],
            2,
            id="other-solution-resets",
        ),
        pytest.param(
            [{"passed": True, "commit": "c1-dirty"}] * 3,
            0,
            id="uncommitted-code-never-counts",
        ),
    ],
)
def test_the_acceptance_sequence(
    tmp_path: Path, specs: Sequence[dict[str, object]], count: int
) -> None:
    assert rounds(tmp_path, specs) == count
    assert streak(tmp_path).reached is (count >= 3)


@pytest.mark.parametrize(
    "field", ["round_id", "commit", "dataset_sha256", "solution_url"]
)
def test_a_line_without_its_stamp_is_rejected(tmp_path: Path, field: str) -> None:
    write_round(tmp_path, 0, passed=True)
    (path,) = tmp_path.glob("*.jsonl")
    line = json.loads(path.read_text())
    del line[field]
    path.write_text(json.dumps(line) + "\n")

    sequence = streak(tmp_path)

    assert sequence.count == 0
    assert sequence.rejected == (path.name,)


def test_a_round_that_never_wrote_its_report_breaks_the_sequence(
    tmp_path: Path,
) -> None:
    for index in range(3):
        write_round(tmp_path, index, passed=True)
    aborted = tmp_path / "20260922T000009Z-aborted.jsonl"
    aborted.write_text(
        json.dumps(
            {
                "record_type": "attempt",
                "round_id": "20260922T000009Z-aborted",
                "commit": "c1",
                "dataset_sha256": "s1",
                "type": "default",
                "solution_url": "http://127.0.0.1:8001",
                "attempt": judged("a").attempt.model_dump(),
                "verdict": judged("a").verdict.model_dump(),
            }
        )
        + "\n"
    )

    assert streak(tmp_path).count == 0


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        pytest.param(20, 19.0, id="0.95n-exact-takes-the-19th-of-20"),
        pytest.param(1, 1.0, id="single-value"),
    ],
)
def test_p95_nearest_rank_when_095n_is_an_integer(count: int, expected: float) -> None:
    assert p95([float(i) for i in range(1, count + 1)]) == expected


def test_legacy_lines_are_ignored_without_rejecting_or_breaking_the_sequence(
    tmp_path: Path,
) -> None:
    for index in range(3):
        write_round(tmp_path, index, passed=True)
    (path,) = sorted(tmp_path.glob("*.jsonl"))[:1]
    older = judged("a").attempt.model_dump()
    del older["trace_id"]  # written before the field existed
    stamp = json.loads(path.read_text())
    attempt = {
        k: stamp[k] for k in ("round_id", "commit", "dataset_sha256", "solution_url")
    }
    path.write_text(
        json.dumps({"type": "attempt", **attempt, "attempt": older, "verdict": {}})
        + "\n"
        + path.read_text()
    )

    sequence = streak(tmp_path)

    assert sequence.count == 3
    assert sequence.rejected == ()
    assert sequence.ignored == (path.name,)


def test_a_standalone_legacy_file_does_not_interrupt_the_sequence(
    tmp_path: Path,
) -> None:
    for index in range(3):
        write_round(tmp_path, index, passed=True)
    legacy = tmp_path / "20260922T000009Z-legacy.jsonl"
    legacy.write_text(json.dumps({"type": "report", "broken": True}) + "\n")

    sequence = streak(tmp_path)

    assert sequence.count == 3
    assert sequence.rejected == ()
    assert sequence.ignored == (legacy.name,)


def test_an_invalid_r4_default_file_is_rejected_and_breaks_the_sequence(
    tmp_path: Path,
) -> None:
    for index in range(3):
        write_round(tmp_path, index, passed=True)
    path = tmp_path / "20260922T000009Z-invalid.jsonl"
    path.write_text(
        json.dumps(
            {
                "record_type": "report",
                "type": "default",
                "round_id": path.stem,
                "commit": "c1",
                "dataset_sha256": "s1",
                "solution_url": "http://127.0.0.1:8001",
            }
        )
        + "\n"
    )

    sequence = streak(tmp_path)

    assert sequence.count == 0
    assert sequence.rejected == (path.name,)


def test_a_truncated_line_before_a_green_r4_report_rejects_the_round(
    tmp_path: Path,
) -> None:
    for index in range(3):
        write_round(tmp_path, index, passed=True)
    path = sorted(tmp_path.glob("*.jsonl"))[-1]
    path.write_text('{"record_type": "attempt"\n' + path.read_text())

    sequence = streak(tmp_path)

    assert sequence.count == 0
    assert not sequence.reached
    assert sequence.rejected == (path.name,)


def test_a_report_without_a_verdict_counts_as_red(tmp_path: Path) -> None:
    for index in range(3):
        write_round(tmp_path, index, passed=True)
    path = sorted(tmp_path.glob("*.jsonl"))[-1]
    line = json.loads(path.read_text())
    del line["report"]["passed"]  # written before the gates existed
    path.write_text(json.dumps(line) + "\n")

    assert streak(tmp_path).count == 0

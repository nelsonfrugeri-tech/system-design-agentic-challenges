"""The Report as the terminal shows it; the JSONL keeps every detail."""

from harness.domain.acceptance import Streak
from harness.domain.reports import ACCEPTANCE_ROUNDS, Report, Round


def render(round_: Round, report: Report, sequence: Streak | None) -> str:
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
        lines += _sequence(sequence)
    return "\n".join(lines)


def _sequence(sequence: Streak) -> list[str]:
    verdict = "acceptance reached" if sequence.reached else "in progress"
    return [
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

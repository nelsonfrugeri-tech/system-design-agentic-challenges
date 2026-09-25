"""Start and run one Round into a results directory, as the command line does."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from harness.adapters.git import commit_of
from harness.adapters.result_writer import ResultWriter
from harness.adapters.solution_http import SOLUTION_URL
from harness.application.attempt import DEFAULT_SETTLE, Settle
from harness.application.ports.bank import Bank
from harness.application.ports.solution import Solution
from harness.application.ports.tracing import Tracing
from harness.application.round import REPETITIONS, run_round
from harness.domain.expected import Dataset
from harness.domain.reports import EvalType, Report, Round


def new_round(
    name: str, type: EvalType, dataset: Dataset, solution_url: str = SOLUTION_URL
) -> Round:
    """A Round stamped with the real commit and clock, like the command line's."""
    return Round.start(
        name,
        type,
        dataset,
        solution_url,
        commit=commit_of(),
        now=datetime.now(UTC),
        nonce=uuid.uuid4().hex[:6],
    )


def run_round_into(
    round_: Round,
    *,
    results: Path,
    dataset: Dataset,
    bank: Bank,
    solution: Solution,
    tracing: Tracing,
    repetitions: int = REPETITIONS,
    settle: Settle = DEFAULT_SETTLE,
) -> tuple[Path, Report]:
    """The results file and the Report, like `harness.run` writes them."""
    writer = ResultWriter(results, round_.id)
    report = run_round(
        round_,
        dataset=dataset,
        bank=bank,
        solution=solution,
        tracing=tracing,
        sink=writer,
        repetitions=repetitions,
        settle=settle,
    )
    return writer.path, report

"""One Round: every conversation 3 times, one turn at a time.

The loop is sequential on purpose: turn attribution by marks is valid only with
one turn per account at a time. Every Attempt starts from a reset of its
account, and every account of the dataset is reset before and after the round,
even when the round fails.
"""

from collections.abc import Iterator

from harness.application.attempt import DEFAULT_SETTLE, Settle, run_attempt
from harness.application.attempt_ledger import AttemptLedger
from harness.application.ports.bank import Bank
from harness.application.ports.results import ResultSink
from harness.application.ports.solution import Solution
from harness.application.ports.tracing import Tracing
from harness.domain.expected import Conversation, Dataset
from harness.domain.judging import judge
from harness.domain.reports import Judged, Report, ReportLine, Round, Stamp
from harness.domain.summarization import summarize

REPETITIONS = 3


def run_round(
    round_: Round,
    *,
    dataset: Dataset,
    bank: Bank,
    solution: Solution,
    tracing: Tracing,
    sink: ResultSink,
    repetitions: int = REPETITIONS,
    settle: Settle = DEFAULT_SETTLE,
) -> Report:
    """Run every Attempt, write one line per Attempt, and the Report last."""
    stamp = Stamp.of(round_)
    bank.reset_all(dataset.path)
    try:
        with sink:
            ledger = AttemptLedger(bank, sink, stamp)
            for conversation, repetition in _schedule(dataset, repetitions):
                ledger.release(conversation.account)
                attempt, seen = run_attempt(
                    round_.id,
                    conversation,
                    repetition,
                    dataset=dataset,
                    bank=bank,
                    solution=solution,
                    tracing=tracing,
                    settle=settle,
                )
                verdict = judge(
                    conversation,
                    initial_operations=attempt.initial_operations,
                    turns=[t.facts for t in attempt.turns],
                    final_state=attempt.final_state,
                )
                ledger.record(Judged(attempt=attempt, verdict=verdict), seen)
            # One wait per round, not per turn: a bank that never goes quiet
            # leaves every open Attempt unsafe.
            quiet = bank.settle_all(quiet_s=settle.quiet_s, cap_s=settle.cap_s)
            judged = ledger.finish(quiet=quiet)
            report = summarize(dataset.conversations, judged, type=round_.type)
            sink.write_report(
                ReportLine(**stamp.model_dump(), round=round_, report=report)
            )
    finally:
        bank.reset_all(dataset.path)
        tracing.flush()
    return report


def _schedule(dataset: Dataset, repetitions: int) -> Iterator[tuple[Conversation, int]]:
    for conversation in dataset.conversations:
        for repetition in range(1, repetitions + 1):
            yield conversation, repetition

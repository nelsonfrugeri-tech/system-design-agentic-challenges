"""One Round: preflight, then every conversation 3 times, one turn at a time.

The loop is sequential on purpose: turn attribution by marks is valid only with
one turn per account at a time. Every Attempt starts from a reset of its
account, and every account of the dataset is reset before and after the round,
even when the round fails.
"""

import argparse
import os
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from pydantic import PositiveFloat, model_validator

from harness.bank import DATA_DIR, Bank, RowIds
from harness.checks import judge
from harness.dataset import DATASET, Conversation, Dataset, Frozen, load_dataset
from harness.observed import Attempt, TurnFacts, TurnRecord
from harness.report import (
    AttemptLine,
    Judged,
    Kind,
    Report,
    ReportLine,
    Round,
    Stamp,
    render,
    streak,
    summarize,
)
from harness.solution import SOLUTION_URL, Solution
from harness.tracing import Tracing, from_environment

REPETITIONS = 3
BANK_URL = "http://127.0.0.1:8001/mcp"
RESULTS = Path(__file__).parents[1] / "results"
PREFLIGHT_TIMEOUT_S = 1.0
# After a failed turn the solution may still be running it. The harness waits
# for the account to go quiet before reading the turn, and never sends the next.
QUIET_S = 5.0
SETTLE_CAP_S = 120.0


class Settle(Frozen):
    quiet_s: PositiveFloat = QUIET_S
    cap_s: PositiveFloat = SETTLE_CAP_S

    @model_validator(mode="after")
    def cap_covers_quiet(self) -> Self:
        if self.cap_s < self.quiet_s:
            raise ValueError("the settle cap must be at least the quiet window")
        return self


DEFAULT_SETTLE = Settle()


class PreflightFailed(Exception):
    def __init__(self, missing: Sequence[str]) -> None:
        super().__init__("; ".join(missing))
        self.missing = tuple(missing)


def preflight(solution: Solution, bank: Bank, bank_url: str) -> None:
    """Fail in about a second when the solution or the bank is down."""
    missing: list[str] = []
    if not solution.health():
        missing.append(
            f"solution: GET {solution.url}/health did not answer 200;"
            " start it (make stub mode=oracle, or your solution)"
        )
    if not bank.db_path.is_file():
        missing.append(f"bank: {bank.db_path} does not exist; run make seed")
    if not _listening(bank_url):
        missing.append(
            f"bank: nothing listening at {bank_url};"
            " start it (make -C agentic-bank/bank-mcp up)"
        )
    if missing:
        raise PreflightFailed(missing)


def _listening(url: str) -> bool:
    # A TCP connect, not an MCP call: a tool call would land in `calls`.
    parts = urlsplit(url)
    try:
        with socket.create_connection(
            (parts.hostname or "127.0.0.1", parts.port or 80),
            timeout=PREFLIGHT_TIMEOUT_S,
        ):
            return True
    except OSError:
        return False


def run_round(
    round_: Round,
    *,
    dataset: Dataset,
    bank: Bank,
    solution: Solution,
    tracing: Tracing,
    results: Path,
    repetitions: int = REPETITIONS,
    settle: Settle = DEFAULT_SETTLE,
) -> tuple[Path, Report]:
    """Run every Attempt, write one JSONL line per Attempt, and the Report last."""
    results.mkdir(parents=True, exist_ok=True)
    path = results / f"{round_.id}.jsonl"
    stamp = Stamp.of(round_).model_dump()
    judged: list[Judged] = []
    # An Attempt's line waits until its account is reset again, or the round
    # ends: rows that appear after its last read make it unsafe.
    pending: dict[str, Judged] = {}
    read = RowIds()  # every row some turn of this round already read
    bank.reset_all(dataset.path)
    try:
        with path.open("w") as out:

            def close(account: str, *, late: bool = False) -> None:
                entry = pending.pop(account)
                unseen = bank.unseen(account, entry.attempt.start_marks, read)
                verdict = entry.verdict.model_copy(
                    update={"late_activity": late or unseen > 0}
                )
                judged.append(Judged(attempt=entry.attempt, verdict=verdict))
                line = AttemptLine(**stamp, attempt=entry.attempt, verdict=verdict)
                out.write(line.model_dump_json() + "\n")
                out.flush()

            for conversation, repetition in _schedule(dataset, repetitions):
                if conversation.account in pending:
                    close(conversation.account)
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
                read = read | seen
                pending[attempt.account] = Judged(attempt=attempt, verdict=verdict)
            # One wait per round, not per turn: a bank that never goes quiet
            # leaves every open Attempt unsafe.
            quiet = bank.settle_all(quiet_s=settle.quiet_s, cap_s=settle.cap_s)
            for account in list(pending):
                close(account, late=not quiet)
            report = summarize(dataset.conversations, judged, kind=round_.kind)
            out.write(
                ReportLine(**stamp, round=round_, report=report).model_dump_json()
                + "\n"
            )
    finally:
        bank.reset_all(dataset.path)
        tracing.flush()
    return path, report


def run_attempt(
    round_id: str,
    conversation: Conversation,
    repetition: int,
    *,
    dataset: Dataset,
    bank: Bank,
    solution: Solution,
    tracing: Tracing,
    settle: Settle = DEFAULT_SETTLE,
) -> tuple[Attempt, RowIds]:
    """Run one Attempt; also return the bank rows its turns already read."""
    account = conversation.account
    started = time.perf_counter()
    bank.reset([account], dataset.path)
    reset_s = time.perf_counter() - started
    initial_operations = bank.operations(account)
    start_marks = bank.marks()
    seen = RowIds()
    thread_id = str(uuid.uuid4())
    turns: list[TurnRecord] = []
    with tracing.attempt(
        round_id=round_id,
        conversation_id=conversation.id,
        repetition=repetition,
        account=account,
        thread_id=thread_id,
    ) as trace_id:
        for index, turn in enumerate(conversation.turns, start=1):
            marks = bank.marks()
            with tracing.turn(index, turn.message) as traced:
                result = solution.chat(
                    thread_id=thread_id,
                    message=turn.message,
                    headers={**traced.headers, "X-Account-Id": account},
                )
                traced.answered(result)
            # Waits for the whole bank: the late write may land in any account.
            settled = result.outcome == "ok" or bank.settle_all(
                quiet_s=settle.quiet_s, cap_s=settle.cap_s
            )
            activity = bank.since(account, marks)
            seen = seen | activity.row_ids
            turns.append(
                TurnRecord(
                    index=index,
                    message=turn.message,
                    reply=result.reply,
                    elapsed_s=result.elapsed_s,
                    facts=TurnFacts(
                        moved=activity.moved,
                        calls=activity.calls,
                        outcome=result.outcome,
                        settled=settled,
                        foreign_moved=activity.foreign_moved,
                        foreign_calls=activity.foreign_calls,
                    ),
                )
            )
            if result.outcome != "ok":
                break
    attempt = Attempt(
        round_id=round_id,
        conversation_id=conversation.id,
        repetition=repetition,
        thread_id=thread_id,
        trace_id=trace_id,
        account=account,
        start_marks=start_marks,
        initial_operations=initial_operations,
        turns=tuple(turns),
        final_state=bank.final_state(account),
        reset_s=reset_s,
    )
    return attempt, seen


def _schedule(dataset: Dataset, repetitions: int) -> Iterator[tuple[Conversation, int]]:
    for conversation in dataset.conversations:
        for repetition in range(1, repetitions + 1):
            yield conversation, repetition


def git_commit(repository: Path = Path(__file__).parent) -> str:
    """HEAD, marked `-dirty` when tracked or untracked files differ from it:
    such a round tests code no commit holds, so it never counts toward acceptance."""

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repository), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    head = git("rev-parse", "HEAD")
    return f"{head}-dirty" if git("status", "--porcelain") else head


def new_round(name: str, kind: Kind, dataset: Dataset) -> Round:
    now = datetime.now(UTC)
    return Round(
        id=f"{now:%Y%m%dT%H%M%S%fZ}-{name}-{uuid.uuid4().hex[:6]}",
        name=name,
        kind=kind,
        commit=git_commit(),
        dataset_sha256=dataset.sha256,
        dataset_path=str(dataset.path),
        started_at=now.isoformat(),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Exit 0 approved, 1 a gate failed, 2 preflight failed, 3 harness error."""
    try:
        return _main(argv)
    except SystemExit as exit_:
        # argparse exits 2 on a usage error, which would read as "preflight".
        return 0 if exit_.code in (0, None) else 3
    except Exception as error:
        print(f"harness error: {type(error).__name__}: {error}", file=sys.stderr)
        return 3


def _main(argv: Sequence[str] | None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--kind", choices=["dev", "holdout"], default="dev")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--solution-url", default=SOLUTION_URL)
    parser.add_argument("--bank-url", default=os.environ.get("BANK_URL", BANK_URL))
    parser.add_argument(
        "--bank-data-dir",
        type=Path,
        default=Path(os.environ.get("BANK_DATA_DIR", DATA_DIR)),
    )
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--quiet-s", type=float, default=QUIET_S)
    parser.add_argument("--settle-cap-s", type=float, default=SETTLE_CAP_S)
    args = parser.parse_args(argv)

    dataset = load_dataset(args.dataset)
    print(f"dataset {dataset.path}\nsha256  {dataset.sha256}", flush=True)
    bank = Bank(data_dir=args.bank_data_dir)
    solution = Solution(args.solution_url, timeout_s=args.timeout_s)
    try:
        preflight(solution, bank, args.bank_url)
    except PreflightFailed as failed:
        for line in failed.missing:
            print(f"preflight: {line}", file=sys.stderr)
        return 2
    tracing, warning = from_environment()
    if warning:
        print(
            f"preflight: warning: {warning}; the round runs without traces",
            file=sys.stderr,
        )
    round_ = new_round(args.name, args.kind, dataset)
    path, report = run_round(
        round_,
        dataset=dataset,
        bank=bank,
        solution=solution,
        tracing=tracing,
        results=args.results,
        settle=Settle(quiet_s=args.quiet_s, cap_s=args.settle_cap_s),
    )
    sequence = streak(args.results) if round_.kind == "dev" else None
    print(render(round_, report, sequence))
    print(f"\nresults {path}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())

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
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from harness.bank import DATA_DIR, Bank
from harness.checks import judge
from harness.dataset import DATASET, Conversation, Dataset, load_dataset
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

REPETITIONS = 3
BANK_URL = "http://127.0.0.1:8001/mcp"
RESULTS = Path(__file__).parents[1] / "results"
PREFLIGHT_TIMEOUT_S = 1.0

type TraceHeaders = Callable[[str], dict[str, str]]


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
    trace_headers: TraceHeaders,
    results: Path,
    repetitions: int = REPETITIONS,
) -> tuple[Path, Report]:
    """Run every Attempt, write one JSONL line per Attempt, and the Report last."""
    results.mkdir(parents=True, exist_ok=True)
    path = results / f"{round_.id}.jsonl"
    stamp = Stamp.of(round_).model_dump()
    judged: list[Judged] = []
    bank.reset_all(dataset.path)
    try:
        with path.open("w") as out:
            for conversation, repetition in _schedule(dataset, repetitions):
                attempt = run_attempt(
                    round_.id,
                    conversation,
                    repetition,
                    dataset=dataset,
                    bank=bank,
                    solution=solution,
                    headers=trace_headers(round_.id),
                )
                verdict = judge(
                    conversation,
                    initial_operations=attempt.initial_operations,
                    turns=[t.facts for t in attempt.turns],
                    final_state=attempt.final_state,
                )
                judged.append(Judged(attempt=attempt, verdict=verdict))
                line = AttemptLine(**stamp, attempt=attempt, verdict=verdict)
                out.write(line.model_dump_json() + "\n")
                out.flush()
            report = summarize(dataset.conversations, judged, kind=round_.kind)
            out.write(
                ReportLine(**stamp, round=round_, report=report).model_dump_json()
                + "\n"
            )
    finally:
        bank.reset_all(dataset.path)
    return path, report


def run_attempt(
    round_id: str,
    conversation: Conversation,
    repetition: int,
    *,
    dataset: Dataset,
    bank: Bank,
    solution: Solution,
    headers: dict[str, str],
) -> Attempt:
    account = conversation.account
    started = time.perf_counter()
    bank.reset([account], dataset.path)
    reset_s = time.perf_counter() - started
    initial_operations = bank.operations(account)
    thread_id = str(uuid.uuid4())
    turns: list[TurnRecord] = []
    for index, turn in enumerate(conversation.turns, start=1):
        marks = bank.marks()
        result = solution.chat(
            thread_id=thread_id,
            message=turn.message,
            headers={**headers, "X-Account-Id": account},
        )
        activity = bank.since(account, marks)
        turns.append(
            TurnRecord(
                index=index,
                message=turn.message,
                reply=result.reply,
                elapsed_s=result.elapsed_s,
                facts=TurnFacts(
                    moved=activity.moved, calls=activity.calls, outcome=result.outcome
                ),
            )
        )
    return Attempt(
        round_id=round_id,
        conversation_id=conversation.id,
        repetition=repetition,
        thread_id=thread_id,
        account=account,
        initial_operations=initial_operations,
        turns=tuple(turns),
        final_state=bank.final_state(account),
        reset_s=reset_s,
    )


def _schedule(dataset: Dataset, repetitions: int) -> Iterator[tuple[Conversation, int]]:
    for conversation in dataset.conversations:
        for repetition in range(1, repetitions + 1):
            yield conversation, repetition


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent,
    ).stdout.strip()


def new_round(name: str, kind: Kind, dataset: Dataset) -> Round:
    now = datetime.now(UTC)
    return Round(
        id=f"{now:%Y%m%dT%H%M%SZ}-{name}-{uuid.uuid4().hex[:6]}",
        name=name,
        kind=kind,
        commit=git_commit(),
        dataset_sha256=dataset.sha256,
        dataset_path=str(dataset.path),
        started_at=now.isoformat(),
    )


def main(argv: Sequence[str] | None = None) -> int:
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
    round_ = new_round(args.name, args.kind, dataset)
    path, report = run_round(
        round_,
        dataset=dataset,
        bank=bank,
        solution=solution,
        trace_headers=lambda _: {},
        results=args.results,
    )
    sequence = streak(args.results) if round_.kind == "dev" else None
    print(render(round_, report, sequence))
    print(f"\nresults {path}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())

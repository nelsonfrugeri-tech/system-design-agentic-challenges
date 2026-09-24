"""The evals command line: preflight, then one Round (or the stub calibration).

The Attempt and Round lifecycles live in `harness.application`; this module
wires the adapters and maps outcomes to exit codes (plan revision 5).
"""

import argparse
import os
import subprocess
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from harness.adapters.bank import DATA_DIR, McpEndpoint, SqliteBank
from harness.adapters.result_writer import ResultWriter
from harness.application.attempt import DEFAULT_SETTLE, Settle
from harness.application.preflight import PreflightFailed, preflight
from harness.application.round import run_round
from harness.calibration import UnknownDataset, run_calibration
from harness.dataset import DATASET, Dataset, load_dataset
from harness.report import EvalType, Report, Round, render, streak
from harness.solution import SOLUTION_URL, TURN_TIMEOUT_S, Solution
from harness.tracing import from_environment

BANK_URL = "http://127.0.0.1:8001/mcp"
RESULTS = Path(__file__).parents[1] / "results"


class UsageFailed(ValueError):
    """The requested round type and dataset path are inconsistent."""


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


def new_round(
    name: str, type: EvalType, dataset: Dataset, solution_url: str = SOLUTION_URL
) -> Round:
    now = datetime.now(UTC)
    return Round(
        id=f"{now:%Y%m%dT%H%M%S%fZ}-{name}-{uuid.uuid4().hex[:6]}",
        name=name,
        type=type,
        commit=git_commit(),
        dataset_sha256=dataset.sha256,
        dataset_path=str(dataset.path),
        solution_url=solution_url.rstrip("/"),
        started_at=now.isoformat(),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    _dataset_override: Path | None = None,
    _timeout_s: float = TURN_TIMEOUT_S,
    _settle: Settle = DEFAULT_SETTLE,
) -> int:
    """Exit 0 approved, 1 gate failed, 2 usage/preflight, 3 harness error."""
    try:
        return _main(
            argv,
            _dataset_override=_dataset_override,
            _timeout_s=_timeout_s,
            _settle=_settle,
        )
    except SystemExit as exit_:
        return 0 if exit_.code in (0, None) else 2
    except UsageFailed as error:
        print(f"usage: {error}", file=sys.stderr)
        return 2
    except UnknownDataset as error:
        print(f"preflight: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"harness error: {type(error).__name__}: {error}", file=sys.stderr)
        return 3


def _main(
    argv: Sequence[str] | None,
    *,
    _dataset_override: Path | None = None,
    _timeout_s: float = TURN_TIMEOUT_S,
    _settle: Settle = DEFAULT_SETTLE,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--type", choices=["default", "holdout", "stub"], default="default"
    )
    parser.add_argument("--path", type=Path)
    parser.add_argument("--solution-url", default=SOLUTION_URL)
    parser.add_argument("--bank-url", default=os.environ.get("BANK_URL", BANK_URL))
    parser.add_argument(
        "--bank-data-dir",
        type=Path,
        default=Path(os.environ.get("BANK_DATA_DIR", DATA_DIR)),
    )
    parser.add_argument("--results", type=Path, default=RESULTS)
    args = parser.parse_args(argv)

    dataset_path = _dataset_override or _dataset_path(args.type, args.path)
    dataset = load_dataset(dataset_path)
    print(f"dataset {dataset.path}\nsha256  {dataset.sha256}", flush=True)
    if args.type == "stub":
        return _calibrate(args, dataset, timeout_s=_timeout_s, settle=_settle)
    bank = SqliteBank(data_dir=args.bank_data_dir)
    solution = Solution(args.solution_url, timeout_s=_timeout_s)
    try:
        preflight(solution, bank, McpEndpoint(args.bank_url))
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
    round_ = new_round(args.name, args.type, dataset, solution.url)
    writer = ResultWriter(args.results, round_.id)
    report = run_round(
        round_,
        dataset=dataset,
        bank=bank,
        solution=solution,
        tracing=tracing,
        sink=writer,
        settle=_settle,
    )
    path = writer.path
    sequence = streak(args.results) if round_.type == "default" else None
    print(render(round_, report, sequence))
    print(f"\nresults {path}")
    return 0 if report.passed else 1


def _dataset_path(eval_type: EvalType, path: Path | None) -> Path:
    if eval_type == "holdout":
        if path is None:
            raise UsageFailed("type=holdout requires path=/absolute/dataset.json")
        if not path.is_absolute():
            raise UsageFailed("holdout path must be absolute")
        resolved = path.resolve()
        repository = Path(__file__).parents[3].resolve()
        if not resolved.is_file():
            raise UsageFailed(f"holdout path is not a file: {resolved}")
        if resolved == repository or repository in resolved.parents:
            raise UsageFailed("holdout path must be outside the repository")
        return resolved
    if path is not None:
        raise UsageFailed("--path is valid only with type=holdout")
    return DATASET


def _calibrate(
    args: argparse.Namespace,
    dataset: Dataset,
    *,
    timeout_s: float,
    settle: Settle,
) -> int:

    def run_mode(
        mode: str,
        solution_url: str,
        bank_url: str,
        bank_data_dir: Path,
        results: Path,
    ) -> tuple[Path, Report]:
        bank = SqliteBank(data_dir=bank_data_dir)
        solution = Solution(solution_url, timeout_s=timeout_s)
        preflight(solution, bank, McpEndpoint(bank_url))
        tracing, _ = from_environment()
        round_ = new_round(f"{args.name}-{mode}", "stub", dataset, solution.url)
        writer = ResultWriter(results, round_.id)
        report = run_round(
            round_,
            dataset=dataset,
            bank=bank,
            solution=solution,
            tracing=tracing,
            sink=writer,
            settle=settle,
        )
        return writer.path, report

    summary = run_calibration(
        dataset, name=args.name, results=args.results, run_mode=run_mode
    )
    for mode, report in summary.reports.items():
        print(f"{mode:7} safety={report.safety} success={report.success}")
    for mismatch in summary.mismatches:
        print(
            f"calibration mismatch {mismatch.mode}.{mismatch.field}:"
            f" expected {mismatch.expected}, got {mismatch.actual}",
            file=sys.stderr,
        )
    return 0 if summary.passed else 1


if __name__ == "__main__":
    sys.exit(main())

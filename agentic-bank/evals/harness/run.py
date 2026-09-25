"""The composition root of the evals command line: it parses the arguments,
wires the adapters into the application, and maps outcomes to exit codes."""

import argparse
import os
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from harness.adapters.bank import DATA_DIR, McpEndpoint, SqliteBank
from harness.adapters.calibration_services import load_baselines, private_services
from harness.adapters.dataset_file import DATASET, load_dataset
from harness.adapters.git import commit_of
from harness.adapters.langfuse import from_environment
from harness.adapters.result_history import read_history, read_violations
from harness.adapters.result_writer import ResultWriter
from harness.adapters.solution_http import SOLUTION_URL, TURN_TIMEOUT_S, HttpSolution
from harness.application.attempt import DEFAULT_SETTLE, Settle
from harness.application.calibration import run_calibration
from harness.application.preflight import PreflightFailed, preflight
from harness.application.round import run_round
from harness.domain.acceptance import streak
from harness.domain.calibration import UnknownDataset
from harness.domain.expected import Dataset
from harness.domain.reports import EvalType, Report, Round
from harness.presentation.terminal import render, render_calibration

BANK_URL = "http://127.0.0.1:8001/mcp"
RESULTS = Path(__file__).parents[1] / "results"
# The --help text is part of the command line: kept verbatim from revision 4.
DESCRIPTION = """One Round: preflight, then every conversation 3 times, one turn at a time.

The loop is sequential on purpose: turn attribution by marks is valid only with
one turn per account at a time. Every Attempt starts from a reset of its
account, and every account of the dataset is reset before and after the round,
even when the round fails.
"""


class UsageFailed(ValueError):
    """The requested round type and dataset path are inconsistent."""


def main(
    argv: Sequence[str] | None = None,
    *,
    _dataset_override: Path | None = None,
    _timeout_s: float = TURN_TIMEOUT_S,
    _settle: Settle = DEFAULT_SETTLE,
    _commit: str | None = None,
) -> int:
    """Exit 0 approved, 1 gate failed, 2 usage/preflight, 3 harness error.

    The underscored keywords are test seams, not part of the command line.
    """
    try:
        args = _parse(argv)
        dataset = load_dataset(_dataset_override or _dataset_path(args.type, args.path))
        print(f"dataset {dataset.path}\nsha256  {dataset.sha256}", flush=True)
        if args.type == "stub":
            return _calibrate(args, dataset, timeout_s=_timeout_s, settle=_settle)
        return _run_default(
            args, dataset, timeout_s=_timeout_s, settle=_settle, commit=_commit
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


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
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
    return parser.parse_args(argv)


def _run_default(
    args: argparse.Namespace,
    dataset: Dataset,
    *,
    timeout_s: float,
    settle: Settle,
    commit: str | None,
) -> int:
    bank = SqliteBank(data_dir=args.bank_data_dir)
    solution = HttpSolution(args.solution_url, timeout_s=timeout_s)
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
    round_ = _new_round(args.name, args.type, dataset, solution.url, commit)
    writer = ResultWriter(args.results, round_.id)
    report = run_round(
        round_,
        dataset=dataset,
        bank=bank,
        solution=solution,
        tracing=tracing,
        sink=writer,
        settle=settle,
    )
    sequence = streak(read_history(args.results)) if round_.type == "default" else None
    print(render(round_, report, sequence))
    print(f"\nresults {writer.path}")
    return 0 if report.passed else 1


def _new_round(
    name: str,
    type: EvalType,
    dataset: Dataset,
    solution_url: str,
    commit: str | None = None,
) -> Round:
    return Round.start(
        name,
        type,
        dataset,
        solution_url,
        commit=commit or commit_of(),
        now=datetime.now(UTC),
        nonce=uuid.uuid4().hex[:6],
    )


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
    args: argparse.Namespace, dataset: Dataset, *, timeout_s: float, settle: Settle
) -> int:
    def run_mode(
        mode: str, solution_url: str, bank_url: str, bank_data_dir: Path, results: Path
    ) -> tuple[Path, Report]:
        bank = SqliteBank(data_dir=bank_data_dir)
        solution = HttpSolution(solution_url, timeout_s=timeout_s)
        preflight(solution, bank, McpEndpoint(bank_url))
        tracing, _ = from_environment()
        round_ = _new_round(f"{args.name}-{mode}", "stub", dataset, solution.url)
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
        dataset,
        name=args.name,
        results=args.results,
        run_mode=run_mode,
        services=private_services,
        baselines=load_baselines(),
        read_violations=read_violations,
    )
    out, err = render_calibration(summary)
    for line in out:
        print(line)
    for line in err:
        print(line, file=sys.stderr)
    return 0 if summary.passed else 1


if __name__ == "__main__":
    sys.exit(main())

"""Calibrate the harness against isolated oracle, refuse, and pay stubs.

Calibration owns disposable processes and a private SQLite database.  The caller
owns running one round through ``run_mode``; this keeps calibration independent
of the CLI and avoids recursively invoking ``harness.run.main``.
"""

import asyncio
import json
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

import httpx
from pydantic import Field, TypeAdapter, ValidationError, computed_field

from baselines.stub import MODES as STUB_MODES
from baselines.stub import Mode, ping_bank
from harness.bank import BANK_MCP, Bank
from harness.checks import ViolationKind
from harness.dataset import Dataset, Frozen
from harness.report import AttemptLine, Report, ReportLine

EVALS = Path(__file__).parents[1]
EXPECTATIONS = EVALS / "baselines" / "expected.json"
READY_S = 30.0
PROCESS_WAIT_S = 10.0
MODES = STUB_MODES
USER_SERVICE_PORTS = frozenset({8000, 8001})
RESULT_LINE: TypeAdapter[AttemptLine | ReportLine] = TypeAdapter(
    AttemptLine | ReportLine
)

type RoundRunner = Callable[
    [Mode, str, str, Path, Path],
    tuple[Path, Report],
]


class UnknownDataset(ValueError):
    """The immutable baseline has no expectations for this dataset hash."""


class StubExpectation(Frozen):
    safety: str
    success: str
    inaction_correct: str | None = None
    execution_correct: str | None = None
    violations_by_conversation: dict[str, tuple[ViolationKind, ...]] = Field(
        default_factory=dict
    )


type MismatchField = Literal[
    "safety",
    "success",
    "inaction_correct",
    "execution_correct",
    "violations_by_conversation",
]


class CalibrationMismatch(Frozen):
    mode: Mode
    field: MismatchField
    expected: str
    actual: str


class CalibrationSummary(Frozen):
    name: str
    dataset_sha256: str
    reports: dict[Mode, Report]
    mismatches: tuple[CalibrationMismatch, ...]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        return not self.mismatches


class PrivateServices(Frozen):
    solution_urls: dict[Mode, str]
    bank_url: str
    bank_data_dir: Path


def run_calibration(
    dataset: Dataset,
    *,
    name: str,
    results: Path,
    run_mode: RoundRunner,
) -> CalibrationSummary:
    """Run and compare all stubs. Mismatches are a normal failing result."""
    expected = _expectation_for(dataset.sha256)
    reports: dict[Mode, Report] = {}
    mismatches: list[CalibrationMismatch] = []
    with private_services(dataset) as services:
        for mode in MODES:
            path, report = run_mode(
                mode,
                services.solution_urls[mode],
                services.bank_url,
                services.bank_data_dir,
                results,
            )
            reports[mode] = report
            mismatches.extend(_compare(mode, expected[mode], report, path))
    return CalibrationSummary(
        name=name,
        dataset_sha256=dataset.sha256,
        reports=reports,
        mismatches=tuple(mismatches),
    )


def _expectation_for(sha256: str) -> dict[Mode, StubExpectation]:
    try:
        raw = json.loads(EXPECTATIONS.read_text())
        baselines = TypeAdapter(dict[str, dict[Mode, StubExpectation]]).validate_python(
            raw
        )
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise RuntimeError(
            f"invalid calibration baseline {EXPECTATIONS}: {error}"
        ) from error
    try:
        expectation = baselines[sha256]
    except KeyError as error:
        raise UnknownDataset(f"no calibration baseline for dataset {sha256}") from error
    missing = sorted(set(MODES) - set(expectation))
    if missing:
        raise RuntimeError(
            f"calibration baseline {sha256} misses modes: {', '.join(missing)}"
        )
    return expectation


def _compare(
    mode: Mode,
    expected: StubExpectation,
    report: Report,
    path: Path,
) -> list[CalibrationMismatch]:
    mismatches: list[CalibrationMismatch] = []
    actual_fields: dict[MismatchField, str] = {
        "safety": str(report.safety),
        "success": str(report.success),
        "inaction_correct": str(report.inaction_correct),
        "execution_correct": str(report.execution_correct),
    }
    for field, actual in actual_fields.items():
        wanted = getattr(expected, field)
        if wanted is not None and actual != wanted:
            mismatches.append(
                CalibrationMismatch(
                    mode=mode,
                    field=field,
                    expected=wanted,
                    actual=actual,
                )
            )
    wanted_violations = _canonical_violations(expected.violations_by_conversation)
    actual_violations = _canonical_violations(_read_violations(path))
    if actual_violations != wanted_violations:
        mismatches.append(
            CalibrationMismatch(
                mode=mode,
                field="violations_by_conversation",
                expected=wanted_violations,
                actual=actual_violations,
            )
        )
    return mismatches


def _read_violations(path: Path) -> dict[str, tuple[ViolationKind, ...]]:
    observed: dict[str, set[ViolationKind]] = {}
    try:
        for raw in path.read_text().splitlines():
            line = RESULT_LINE.validate_json(raw)
            if not isinstance(line, AttemptLine):
                continue
            conversation = line.attempt.conversation_id
            kinds: set[ViolationKind] = {
                violation.kind for violation in line.verdict.violations
            }
            if kinds:
                observed.setdefault(conversation, set()).update(kinds)
    except (OSError, ValidationError) as error:
        raise RuntimeError(f"invalid calibration result {path}: {error}") from error
    return {
        conversation: tuple(sorted(kinds))
        for conversation, kinds in sorted(observed.items())
    }


def _canonical_violations(
    violations: dict[str, tuple[ViolationKind, ...]],
) -> str:
    canonical = {
        conversation: sorted(kinds)
        for conversation, kinds in sorted(violations.items())
    }
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"))


@contextmanager
def private_services(dataset: Dataset) -> Iterator[PrivateServices]:
    """Serve a private seeded bank and one stub per mode on ephemeral ports."""
    processes: list[subprocess.Popen[bytes]] = []
    with tempfile.TemporaryDirectory(prefix="agentic-bank-calibration-") as raw:
        data_dir = Path(raw)
        bank = Bank(data_dir=data_dir)
        bank.reset_all(dataset.path)
        bank_port = free_port()
        bank_url = f"http://127.0.0.1:{bank_port}/mcp"
        try:
            bank_process = subprocess.Popen(
                [
                    "uv",
                    "run",
                    "--directory",
                    str(BANK_MCP),
                    "--locked",
                    "python",
                    "-m",
                    "bank.mcp.server",
                    "--db",
                    str(bank.db_path),
                    "--port",
                    str(bank_port),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append(bank_process)
            wait_until(lambda: _bank_answers(bank_url), bank_process)

            solution_urls: dict[Mode, str] = {}
            for mode in MODES:
                port = free_port()
                url = f"http://127.0.0.1:{port}"
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "baselines.stub",
                        "--mode",
                        mode,
                        "--port",
                        str(port),
                        "--bank-url",
                        bank_url,
                        "--dataset",
                        str(dataset.path),
                    ],
                    cwd=EVALS,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                processes.append(process)
                wait_until(_stub_probe(url), process)
                solution_urls[mode] = url
            yield PrivateServices(
                solution_urls=solution_urls,
                bank_url=bank_url,
                bank_data_dir=data_dir,
            )
        finally:
            for process in reversed(processes):
                terminate_process(process)


def free_port() -> int:
    while True:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port: int = probe.getsockname()[1]
        if port not in USER_SERVICE_PORTS:
            return port


def wait_until(ready: Callable[[], bool], process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + READY_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"process exited with {process.returncode}")
        if ready():
            return
        time.sleep(0.1)
    raise TimeoutError("process not ready")


def terminate_process(
    process: subprocess.Popen[bytes], *, wait_s: float = PROCESS_WAIT_S
) -> None:
    """Bounded teardown: terminate, wait, then kill and reap if still alive."""
    process.terminate()
    try:
        process.wait(timeout=wait_s)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=wait_s)


def _bank_answers(url: str) -> bool:
    try:
        asyncio.run(ping_bank(url))
    except Exception:
        return False
    return True


def _stub_answers(url: str) -> bool:
    try:
        return httpx.get(f"{url}/health", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


def _stub_probe(url: str) -> Callable[[], bool]:
    def probe() -> bool:
        return _stub_answers(url)

    return probe

"""Disposable processes for the calibration: a private seeded bank and one stub
per mode on ephemeral ports, never the user's 8000/8001 or database; plus the
immutable calibration baseline file."""

import json
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
from pydantic import TypeAdapter, ValidationError

from harness.adapters.bank import BANK_MCP, McpEndpoint, SqliteBank
from harness.domain.calibration import (
    MODES,
    CalibrationExpectation,
    Mode,
    PrivateServices,
)
from harness.domain.expected import Dataset

EVALS = Path(__file__).parents[2]
EXPECTATIONS = EVALS / "baselines" / "expected.json"
READY_S = 30.0
PROCESS_WAIT_S = 10.0
USER_SERVICE_PORTS = frozenset({8000, 8001})

type Process = subprocess.Popen[bytes]


def load_baselines(
    path: Path = EXPECTATIONS,
) -> dict[str, dict[Mode, CalibrationExpectation]]:
    try:
        raw = json.loads(path.read_text())
        return TypeAdapter(
            dict[str, dict[Mode, CalibrationExpectation]]
        ).validate_python(raw)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise RuntimeError(f"invalid calibration baseline {path}: {error}") from error


@contextmanager
def private_services(dataset: Dataset) -> Iterator[PrivateServices]:
    """Serve a private seeded bank and one stub per mode on ephemeral ports."""
    processes: list[Process] = []
    with tempfile.TemporaryDirectory(prefix="agentic-bank-calibration-") as raw:
        data_dir = Path(raw)
        bank = SqliteBank(data_dir=data_dir)
        bank.reset_all(dataset.path)
        try:
            bank_url = _serve_bank(bank, processes)
            solution_urls = {
                mode: _serve_stub(mode, bank_url, dataset, processes) for mode in MODES
            }
            yield PrivateServices(
                solution_urls=solution_urls,
                bank_url=bank_url,
                bank_data_dir=data_dir,
            )
        finally:
            for process in reversed(processes):
                terminate_process(process)


def _serve_bank(bank: SqliteBank, processes: list[Process]) -> str:
    port = free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    process = subprocess.Popen(
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
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    processes.append(process)
    wait_until(McpEndpoint(url).ping, process)
    return url


def _serve_stub(
    mode: Mode, bank_url: str, dataset: Dataset, processes: list[Process]
) -> str:
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
    return url


def free_port() -> int:
    while True:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port: int = probe.getsockname()[1]
        if port not in USER_SERVICE_PORTS:
            return port


def wait_until(ready: Callable[[], bool], process: Process) -> None:
    deadline = time.monotonic() + READY_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"process exited with {process.returncode}")
        if ready():
            return
        time.sleep(0.1)
    raise TimeoutError("process not ready")


def terminate_process(process: Process, *, wait_s: float = PROCESS_WAIT_S) -> None:
    """Bounded teardown: terminate, wait, then kill and reap if still alive."""
    process.terminate()
    try:
        process.wait(timeout=wait_s)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=wait_s)


def _stub_probe(url: str) -> Callable[[], bool]:
    def probe() -> bool:
        try:
            return httpx.get(f"{url}/health", timeout=1).status_code == 200
        except httpx.HTTPError:
            return False

    return probe

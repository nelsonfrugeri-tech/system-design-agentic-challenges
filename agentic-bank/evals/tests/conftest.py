"""Real dependencies for integration tests: a bank-mcp server on a temporary
SQLite seeded by `make seed`, and the stub on a free port. Nothing is mocked."""

import asyncio
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from baselines.stub import ping_bank
from harness.bank import BANK_MCP, Bank
from harness.dataset import DATASET

READY_S = 30.0


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
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


@dataclass(frozen=True)
class BankServer:
    bank: Bank
    url: str


def _bank_answers(url: str) -> bool:
    try:
        asyncio.run(ping_bank(url))
    except Exception:
        return False
    return True


@pytest.fixture(scope="session")
def bank_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[BankServer]:
    bank = Bank(data_dir=tmp_path_factory.mktemp("bank"))
    bank.reset_all(DATASET)
    port = free_port()
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
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        wait_until(lambda: _bank_answers(url), process)
        yield BankServer(bank=bank, url=url)
    finally:
        process.terminate()
        process.wait(timeout=10)


@dataclass(frozen=True)
class StubServer:
    url: str

    def received(self) -> list[dict[str, object]]:
        stats: list[dict[str, object]] = httpx.get(f"{self.url}/stats").json()[
            "received"
        ]
        return stats


def _stub_answers(url: str) -> bool:
    try:
        return httpx.get(f"{url}/health", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture
def start_stub(bank_server: BankServer) -> Iterator[Callable[..., StubServer]]:
    processes: list[subprocess.Popen[bytes]] = []

    def start(
        mode: str, *, dataset: Path = DATASET, delay_s: float = 0.0
    ) -> StubServer:
        port = free_port()
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
                bank_server.url,
                "--dataset",
                str(dataset),
                "--delay-s",
                str(delay_s),
            ],
            cwd=Path(__file__).parents[1],
        )
        processes.append(process)
        url = f"http://127.0.0.1:{port}"
        wait_until(lambda: _stub_answers(url), process)
        return StubServer(url=url)

    yield start
    for process in processes:
        process.terminate()
        process.wait(timeout=10)

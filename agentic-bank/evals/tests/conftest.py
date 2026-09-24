"""Real dependencies for integration tests: a bank-mcp server on a temporary
SQLite seeded by `make seed`, and the stub on a free port. Nothing is mocked."""

import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from harness.adapters.bank import McpEndpoint
from harness.adapters.calibration_services import (
    free_port as calibration_free_port,
)
from harness.adapters.calibration_services import terminate_process, wait_until
from harness.bank import BANK_MCP, Bank
from harness.dataset import DATASET


def free_port() -> int:
    """Public test helper backed by the calibration port allocator."""
    return calibration_free_port()


@dataclass(frozen=True)
class BankServer:
    bank: Bank
    url: str


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
        wait_until(McpEndpoint(url).ping, process)
        yield BankServer(bank=bank, url=url)
    finally:
        terminate_process(process)


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
        terminate_process(process)

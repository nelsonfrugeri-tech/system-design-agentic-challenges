"""The turn timeout bounds the whole POST, not each read of the body."""

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Iterator

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from harness.adapters.solution_http import HttpSolution
from tests.conftest import free_port


async def trickle(_: Request) -> Response:
    async def chunks() -> AsyncIterator[bytes]:
        yield b'{"reply": "'
        for _ in range(4):
            await asyncio.sleep(0.4)
            yield b"x"
        yield b'"}'

    return StreamingResponse(chunks(), media_type="application/json")


@pytest.fixture
def slow_server() -> Iterator[str]:
    port = free_port()
    config = uvicorn.Config(
        Starlette(routes=[Route("/chat", trickle, methods=["POST"])]),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def test_a_body_that_trickles_past_the_timeout_is_a_timeout(slow_server: str) -> None:
    result = HttpSolution(slow_server, timeout_s=1.0).chat(
        thread_id="t", message="m", headers={}
    )

    assert result.outcome == "timeout"
    assert result.reply is None

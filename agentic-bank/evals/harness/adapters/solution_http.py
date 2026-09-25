"""The solution as the harness sees it: `GET /health` and `POST /chat`.

A POST is sent exactly once. Resending would run the turn twice and break the
turn marks, so a slow or failed turn is a failed turn, never a retry.
"""

import time
from collections.abc import Mapping

import httpx
from pydantic import ValidationError

from harness.application.ports.solution import Solution
from harness.domain import Frozen
from harness.domain.observations import ChatResult

SOLUTION_URL = "http://127.0.0.1:8000"
TURN_TIMEOUT_S = 120.0
HEALTH_TIMEOUT_S = 1.0


class _Reply(Frozen):
    reply: str


class HttpSolution(Solution):
    def __init__(
        self, url: str = SOLUTION_URL, *, timeout_s: float = TURN_TIMEOUT_S
    ) -> None:
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s

    def health(self) -> bool:
        try:
            response = httpx.get(f"{self.url}/health", timeout=HEALTH_TIMEOUT_S)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    def chat(
        self, *, thread_id: str, message: str, headers: Mapping[str, str]
    ) -> ChatResult:
        # retries=0 is httpx's default; it is spelled out because it is the contract.
        transport = httpx.HTTPTransport(retries=0)
        with httpx.Client(transport=transport, timeout=self.timeout_s) as client:
            started = time.perf_counter()
            try:
                response = client.post(
                    f"{self.url}/chat",
                    json={"thread_id": thread_id, "message": message},
                    headers=dict(headers),
                )
            except httpx.TimeoutException:
                return ChatResult(
                    reply=None, elapsed_s=_since(started), outcome="timeout"
                )
            except httpx.HTTPError:
                return ChatResult(
                    reply=None, elapsed_s=_since(started), outcome="http_error"
                )
            elapsed_s = _since(started)
        # httpx applies the timeout to each read, not to the whole response: a
        # body that trickles in could take longer than the turn allows.
        if elapsed_s > self.timeout_s:
            return ChatResult(reply=None, elapsed_s=elapsed_s, outcome="timeout")
        return _parse(response, elapsed_s)


def _parse(response: httpx.Response, elapsed_s: float) -> ChatResult:
    if response.status_code != 200:
        return ChatResult(reply=None, elapsed_s=elapsed_s, outcome="http_error")
    try:
        reply = _Reply.model_validate_json(response.content).reply
    except ValidationError:
        return ChatResult(reply=None, elapsed_s=elapsed_s, outcome="http_error")
    return ChatResult(reply=reply, elapsed_s=elapsed_s, outcome="ok")


def _since(started: float) -> float:
    return time.perf_counter() - started

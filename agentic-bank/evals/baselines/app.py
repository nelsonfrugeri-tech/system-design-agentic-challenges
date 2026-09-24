"""The fake assistant's HTTP service: the solution contract (`/health`,
`POST /chat`) plus `/stats`, which exposes what each POST carried."""

import asyncio
from collections import Counter
from dataclasses import dataclass, field

from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from baselines.behaviours import Behaviour, oracle, pay, refuse
from harness.domain.calibration import Mode
from harness.domain.expected import Dataset


class ChatBody(BaseModel):
    thread_id: str
    message: str


class Received(BaseModel):
    account: str | None
    thread_id: str
    turn: int
    traceparent: str | None
    baggage: str | None


@dataclass
class Stats:
    """In-memory record of every POST; one stub process serves one round."""

    received: list[Received] = field(default_factory=list)
    turns: Counter[str] = field(default_factory=Counter)


def create_app(
    mode: Mode, *, dataset: Dataset, bank_url: str, delay_s: float = 0.0
) -> Starlette:
    behaviours: dict[Mode, Behaviour] = {
        "refuse": refuse,
        "pay": pay(bank_url),
        "oracle": oracle(dataset, bank_url),
    }
    behaviour = behaviours[mode]
    stats = Stats()

    async def health(_: Request) -> Response:
        return JSONResponse({"mode": mode})

    async def chat(request: Request) -> Response:
        body = ChatBody.model_validate_json(await request.body())
        account = request.headers.get("x-account-id")
        turn = stats.turns[body.thread_id]
        stats.turns[body.thread_id] += 1
        stats.received.append(
            Received(
                account=account,
                thread_id=body.thread_id,
                turn=turn,
                traceparent=request.headers.get("traceparent"),
                baggage=request.headers.get("baggage"),
            )
        )
        if account is None:
            return JSONResponse({"error": "missing X-Account-Id"}, status_code=400)
        await asyncio.sleep(delay_s)
        return JSONResponse({"reply": await behaviour(account, body.message, turn)})

    async def read_stats(_: Request) -> Response:
        return JSONResponse({"received": [r.model_dump() for r in stats.received]})

    return Starlette(
        routes=[
            Route("/health", health),
            Route("/chat", chat, methods=["POST"]),
            Route("/stats", read_stats),
        ]
    )

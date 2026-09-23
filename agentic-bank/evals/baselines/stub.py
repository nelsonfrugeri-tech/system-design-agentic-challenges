"""A fake assistant that honours the solution contract, to prove the harness.

`refuse` answers without calling the bank. `pay` pays, on the first turn and
without confirming, the whole remaining amount of the first bill. `oracle` does
the turn's `must_check` reads and then exactly its `executes`.
It talks to the bank through MCP with X-Account-Id, like the real solution, so
the bank records its calls. `/stats` exposes what each POST carried.
"""

import argparse
import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Literal

import httpx
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from harness.dataset import DATASET, Conversation, Dataset, Movement, load_dataset

type Mode = Literal["refuse", "pay", "oracle"]
MODES: tuple[Mode, ...] = ("refuse", "pay", "oracle")
BANK_URL = "http://127.0.0.1:8001/mcp"


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


async def call_bank(
    bank_url: str, account: str, tool: str, arguments: Mapping[str, str | int]
) -> CallToolResult:
    """One MCP tool call on behalf of the account; the bank records it in `calls`."""
    async with (
        httpx.AsyncClient(headers={"X-Account-Id": account}, timeout=30) as http,
        streamable_http_client(bank_url, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return await session.call_tool(
            tool, dict(arguments), read_timeout_seconds=timedelta(seconds=30)
        )


async def ping_bank(bank_url: str) -> None:
    """Open an MCP session without calling a tool, so nothing lands in `calls`."""
    async with (
        httpx.AsyncClient(timeout=2) as http,
        streamable_http_client(bank_url, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()


def movement_arguments(movement: Movement) -> dict[str, str | int]:
    target = "bill_id" if movement.action == "pay_card_bill" else "investment_id"
    return {target: movement.target_id, "amount_cents": movement.amount_cents}


type Behaviour = Callable[[str, str, int], Awaitable[str]]


async def refuse(account: str, message: str, turn: int) -> str:
    return "refuse: nothing done"


def pay(bank_url: str) -> Behaviour:
    async def reply(account: str, message: str, turn: int) -> str:
        if turn > 0:
            return "pay: already paid"
        bills = await call_bank(bank_url, account, "list_bills", {})
        first = _first_bill(bills)
        result = await call_bank(
            bank_url,
            account,
            "pay_card_bill",
            {"bill_id": first.id, "amount_cents": first.remaining_cents},
        )
        return "pay: refused" if result.isError else f"pay: paid {first.id}"

    return reply


class _Bill(BaseModel):
    id: str
    amount_cents: int
    paid_cents: int

    @property
    def remaining_cents(self) -> int:
        return self.amount_cents - self.paid_cents


class _Bills(BaseModel):
    result: list[_Bill]


def _first_bill(result: CallToolResult) -> _Bill:
    # FastMCP wraps a list return as {"result": [...]} (bank-mcp README, "Saídas").
    return _Bills.model_validate(result.structuredContent).result[0]


def oracle(dataset: Dataset, bank_url: str) -> Behaviour:
    by_account: dict[str, Conversation] = {c.account: c for c in dataset.conversations}

    async def reply(account: str, message: str, turn: int) -> str:
        expected = by_account[account].turns[turn]
        for tool in expected.must_check:
            await call_bank(bank_url, account, tool, {})
        for movement in expected.executes:
            await call_bank(
                bank_url, account, movement.action, movement_arguments(movement)
            )
        return f"oracle: {len(expected.executes)} movement(s)"

    return reply


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--bank-url", default=BANK_URL)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--delay-s", type=float, default=0.0)
    args = parser.parse_args()
    app = create_app(
        args.mode,
        dataset=load_dataset(args.dataset),
        bank_url=args.bank_url,
        delay_s=args.delay_s,
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

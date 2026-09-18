"""Plug your solution into the evals trace. Required.

Every `POST /chat` carries a W3C `traceparent` header. Continue it and your
agent's steps — model calls, tools, tokens and cost — land inside that
conversation's trace in Langfuse, beside the scores. Ignore it and your run
shows no cost and no internals.

Decorate the function that answers one turn. It works the same whether the
function is sync or `async def`:

    from observer_sdk.tracing import traced_turn

    @traced_turn
    async def chat(*, headers, thread_id, account_id, message) -> str:
        return await my_agent(account_id, thread_id, message)

`headers` is required and must be the request headers; everything else you pass
is recorded as the turn's input. With LangChain, also hand your agent
`langfuse.langchain.CallbackHandler()`: it attaches to the context opened here.

Needs `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`.
"""

import asyncio
from collections.abc import Callable, Coroutine, Iterator, Mapping
from contextlib import contextmanager
from functools import wraps
from typing import Any, cast

from langfuse import get_client
from opentelemetry import context as otel_context
from opentelemetry import propagate

type Turn = Callable[..., str]
type AsyncTurn = Callable[..., Coroutine[Any, Any, str]]


@contextmanager
def continue_trace(headers: Mapping[str, str]) -> Iterator[None]:
    """Make the evals trace the active one inside this block.

    Without a `traceparent` header nothing breaks: the block simply starts its
    own trace, which is what happens when you call the endpoint by hand.
    """
    carrier = {name.lower(): value for name, value in headers.items()}
    token = otel_context.attach(propagate.extract(carrier))
    try:
        yield
    finally:
        otel_context.detach(token)


def traced_turn[F: Turn | AsyncTurn](handler: F) -> F:
    """Record one turn of your solution inside the evals trace.

    Wraps a sync or an async handler; the async one is awaited and never blocks
    the event loop, because the Langfuse client only flushes synchronously.
    """
    if asyncio.iscoroutinefunction(handler):

        @wraps(handler)
        async def async_wrapper(*args: object, **kwargs: object) -> str:
            client = get_client()
            with _turn_span(kwargs) as span:
                reply = await cast(AsyncTurn, handler)(*args, **kwargs)
                span.update(output={"reply": reply})
            await asyncio.to_thread(client.flush)
            return reply

        return cast(F, async_wrapper)

    @wraps(handler)
    def wrapper(*args: object, **kwargs: object) -> str:
        client = get_client()
        with _turn_span(kwargs) as span:
            reply = cast(Turn, handler)(*args, **kwargs)
            span.update(output={"reply": reply})
        # The server keeps running, so nothing else would send these spans.
        client.flush()
        return reply

    return cast(F, wrapper)


@contextmanager
def _turn_span(kwargs: Mapping[str, object]) -> Iterator[Any]:
    """Open the `solution` span as a child of the incoming traceparent."""
    headers = kwargs.get("headers")
    if not isinstance(headers, Mapping):
        raise TypeError("traced_turn needs a headers= keyword argument")

    with continue_trace(headers):
        with get_client().start_as_current_observation(
            name="solution", as_type="span"
        ) as span:
            span.update(
                input={
                    name: value for name, value in kwargs.items() if name != "headers"
                }
            )
            yield span

# Observer SDK

Puts every turn of the solution inside the trace of the conversation that called
it, in Langfuse. The solution writes no observability code: it decorates the
function that answers one turn.

## Use it in the solution

```sh
uv add --editable ../observer-sdk      # from src/
```

```python
from observer_sdk.tracing import traced_turn

@traced_turn
async def chat(*, headers, thread_id, account_id, message) -> str:
    return await my_agent(account_id, thread_id, message)
```

- `headers` is required and must be the request headers. Everything else becomes
  the turn's input in Langfuse.
- Sync and `async def` handlers both work.
- With LangChain, also hand the agent `langfuse.langchain.CallbackHandler()`: it
  attaches to the span opened here, so model calls, tools, tokens and cost land
  in the same trace.
- It needs `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`. The
  local values are in `infra/langfuse/.env`, created by `make langfuse` at the
  repository root.
- It never flushes inside a turn, so Langfuse adds nothing to the latency the
  evals measure. The Langfuse client sends spans from a background thread, at
  most 5 s after they end (`LANGFUSE_FLUSH_INTERVAL`), and flushes the rest
  when the process exits (it registers that with `atexit`). Stop the server
  with a normal shutdown, not `kill -9`, or the last spans are lost.

## What the caller sends

The SDK continues whatever arrives in the W3C headers of the request:

| Header | Carries | Without it |
| --- | --- | --- |
| `traceparent` | The trace of the conversation | The turn starts its own trace, which is fine for a manual call |
| `baggage` | Langfuse session and environment | The turn's spans land in environment `default`, outside the session |

A caller in Python gets both with the Langfuse SDK and OpenTelemetry:

```python
from langfuse import propagate_attributes
from opentelemetry import propagate

with propagate_attributes(session_id=run_id, environment="evals", as_baggage=True):
    with langfuse.start_as_current_observation(name="conversation"):
        headers = {"X-Account-Id": account_id}
        propagate.inject(headers)   # adds traceparent and baggage
        httpx.post(url, headers=headers, json=body)
```

Without `as_baggage=True`, the session and environment stay in the caller's
process and never reach the solution.

## Develop

```sh
make sync
make check      # Black, Ruff, strict mypy, offline tests
```

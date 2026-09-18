import asyncio

from opentelemetry import trace

from observer_sdk.tracing import continue_trace, traced_turn

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
TRACEPARENT = f"00-{TRACE_ID}-00f067aa0ba902b7-01"
HEADERS = {"traceparent": TRACEPARENT, "x-account-id": "acc-1005"}


def active_trace_id() -> str:
    return format(trace.get_current_span().get_span_context().trace_id, "032x")


def test_the_evals_trace_becomes_the_active_one() -> None:
    with continue_trace({"traceparent": TRACEPARENT}):
        assert active_trace_id() == TRACE_ID


def test_header_case_does_not_matter() -> None:
    with continue_trace({"TraceParent": TRACEPARENT}):
        assert active_trace_id() == TRACE_ID


def test_without_the_header_nothing_breaks() -> None:
    with continue_trace({"x-account-id": "acc-1005"}):
        assert active_trace_id() != TRACE_ID


def test_the_trace_is_released_afterwards() -> None:
    with continue_trace({"traceparent": TRACEPARENT}):
        pass

    assert active_trace_id() != TRACE_ID


def test_a_sync_turn_runs_inside_the_evals_trace() -> None:
    seen: list[str] = []

    @traced_turn
    def chat(*, headers: dict[str, str], message: str) -> str:
        seen.append(active_trace_id())
        return f"recebi: {message}"

    reply = chat(headers=HEADERS, message="Paga minha fatura hoje.")

    assert reply == "recebi: Paga minha fatura hoje."
    assert seen == [TRACE_ID]


def test_an_async_turn_runs_inside_the_evals_trace() -> None:
    seen: list[str] = []

    @traced_turn
    async def chat(*, headers: dict[str, str], message: str) -> str:
        await asyncio.sleep(0)
        seen.append(active_trace_id())
        return f"recebi: {message}"

    reply = asyncio.run(chat(headers=HEADERS, message="Pode."))

    assert reply == "recebi: Pode."
    assert seen == [TRACE_ID]


def test_a_turn_without_headers_is_refused() -> None:
    @traced_turn
    def chat(*, message: str) -> str:
        return message

    try:
        chat(message="oi")
    except TypeError as error:
        assert "headers=" in str(error)
    else:  # pragma: no cover - the call above must raise
        raise AssertionError("traced_turn accepted a turn without headers")

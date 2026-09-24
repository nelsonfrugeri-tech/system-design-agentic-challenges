"""S21 (informative): each Attempt is one trace whose id is its Langfuse session.

The spans go to memory, not to a Langfuse server; the POSTs go to the real stub.
"""

import json
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote

import pytest
from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from harness.dataset import load_dataset
from harness.report import AttemptLine
from harness.run import new_round, run_round
from harness.solution import Solution
from harness.tracing import Tracing, from_environment
from tests.conftest import BankServer, StubServer, free_port
from tests.test_run import lines, subset

type StartStub = Callable[..., StubServer]


def baggage(raw: str) -> dict[str, str]:
    return dict(unquote(item).split("=", 1) for item in raw.split(","))


def test_each_attempt_is_a_trace_and_its_id_is_the_session(
    bank_server: BankServer, start_stub: StartStub, tmp_path: Path
) -> None:
    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        base_url="http://127.0.0.1:1",
        tracer_provider=TracerProvider(),
        span_exporter=exporter,
    )
    dataset = load_dataset(subset(tmp_path, ["ambiguous-bill", "changed-amount"]))
    stub = start_stub("refuse")
    round_ = new_round("traced", "default", dataset, stub.url)

    run_round(
        round_,
        dataset=dataset,
        bank=bank_server.bank,
        solution=Solution(stub.url),
        tracing=Tracing(client),
        results=tmp_path / "results",
    )

    received = stub.received()
    attempts = [a for a in lines(tmp_path / "results") if isinstance(a, AttemptLine)]
    by_thread: dict[str, list[dict[str, object]]] = {}
    for post in received:
        by_thread.setdefault(str(post["thread_id"]), []).append(post)
    assert len(by_thread) == len(attempts) == 6
    trace_ids = set()
    for attempt in attempts:
        posts = by_thread[attempt.attempt.thread_id]
        assert [p["turn"] for p in posts] == [0, 1]
        assert all(p["account"] == attempt.attempt.account for p in posts)
        traces = {str(p["traceparent"]).split("-")[1] for p in posts}
        assert traces == {attempt.attempt.trace_id}
        for post in posts:
            carried = baggage(str(post["baggage"]))
            assert carried["langfuse_session_id"] == attempt.attempt.trace_id
            assert carried["langfuse_environment"] == "evals"
            assert carried["langfuse_metadata_round_id"] == round_.id
        trace_ids.add(attempt.attempt.trace_id)
    assert len(trace_ids) == 6

    client.flush()
    spans = exporter.get_finished_spans()
    assert {s.name for s in spans} == {"attempt", "turn 1", "turn 2"}
    turn_1 = [s for s in spans if s.name == "turn 1"]
    messages = {c.turns[0].message for c in dataset.conversations}
    assert {
        json.loads(str(s.attributes["langfuse.observation.input"]))["message"]  # type: ignore[index]
        for s in turn_1
    } == messages
    assert all(
        json.loads(str(s.attributes["langfuse.observation.output"]))["outcome"] == "ok"  # type: ignore[index]
        for s in turn_1
    )
    assert all(
        s.attributes is not None
        and s.attributes["session.id"] == format(s.context.trace_id, "032x")
        for s in spans
    )


def test_langfuse_down_is_a_warning_not_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGFUSE_HOST", f"http://127.0.0.1:{free_port()}")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")

    tracing, warning = from_environment()

    assert not tracing.enabled
    assert warning is not None and "did not answer" in warning


def test_missing_keys_are_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LANGFUSE_HOST", "LANGFUSE_BASE_URL", "LANGFUSE_PUBLIC_KEY"):
        monkeypatch.delenv(name, raising=False)

    tracing, warning = from_environment()

    assert not tracing.enabled
    assert warning is not None and "make env" in warning

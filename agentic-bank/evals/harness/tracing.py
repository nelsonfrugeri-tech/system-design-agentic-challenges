"""Langfuse tracing of a round. Informative only: it never decides a verdict.

Each Attempt is one trace, and that trace id is also its Langfuse session id, so
the session view shows the conversation's turns together. The round id travels
as a tag and as metadata. Every POST carries `traceparent` and `baggage` from
inside its turn span, so the solution's spans land under that turn.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
from langfuse import Langfuse, LangfuseSpan, propagate_attributes
from opentelemetry import propagate

from harness.solution import ChatResult

ENVIRONMENT = "evals"
HEALTH_TIMEOUT_S = 1.0


class TurnTrace:
    """The headers a turn's POST carries, and where its answer is recorded."""

    def __init__(self, headers: dict[str, str], span: LangfuseSpan | None) -> None:
        self.headers = headers
        self.span = span

    def answered(self, result: ChatResult) -> None:
        if self.span is not None:
            self.span.update(
                output={
                    "reply": result.reply,
                    "outcome": result.outcome,
                    "elapsed_s": result.elapsed_s,
                }
            )


class Tracing:
    """Opens the Attempt and turn spans; disabled, it only yields empty headers."""

    def __init__(self, client: Langfuse | None) -> None:
        self.client = client

    @classmethod
    def disabled(cls) -> "Tracing":
        return cls(None)

    @property
    def enabled(self) -> bool:
        return self.client is not None

    @contextmanager
    def attempt(
        self,
        *,
        round_id: str,
        conversation_id: str,
        repetition: int,
        account: str,
        thread_id: str,
    ) -> Iterator[str | None]:
        """Yield the Attempt's trace id, which is also its session id."""
        if self.client is None:
            yield None
            return
        trace_id = Langfuse.create_trace_id()
        with (
            self.client.start_as_current_observation(
                trace_context={"trace_id": trace_id},
                name="attempt",
                as_type="span",
                input={
                    "conversation_id": conversation_id,
                    "repetition": repetition,
                    "account": account,
                    "thread_id": thread_id,
                },
            ),
            propagate_attributes(
                session_id=trace_id,
                environment=ENVIRONMENT,
                trace_name=f"{conversation_id} #{repetition}",
                tags=[round_id],
                metadata={
                    "round_id": round_id,
                    "conversation_id": conversation_id,
                    "repetition": str(repetition),
                },
                as_baggage=True,
            ),
        ):
            yield trace_id

    @contextmanager
    def turn(self, index: int, message: str) -> Iterator[TurnTrace]:
        """Yield the W3C headers the POST of this turn must carry; the message is
        the span's input and the answer its output, so the session shows both."""
        if self.client is None:
            yield TurnTrace({}, None)
            return
        with self.client.start_as_current_observation(
            name=f"turn {index}", as_type="span", input={"message": message}
        ) as span:
            headers: dict[str, str] = {}
            propagate.inject(headers)
            yield TurnTrace(headers, span)

    def flush(self) -> None:
        if self.client is not None:
            self.client.flush()


def from_environment() -> tuple[Tracing, str | None]:
    """Tracing from LANGFUSE_* variables, or disabled with the reason to warn.

    Langfuse down never fails the round: the preflight turns it into a warning.
    """
    host = os.environ.get("LANGFUSE_HOST") or os.environ.get("LANGFUSE_BASE_URL")
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    if not (host and public_key and secret_key):
        return Tracing.disabled(), (
            "LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY is not set;"
            " run make env"
        )
    try:
        response = httpx.get(
            f"{host.rstrip('/')}/api/public/health", timeout=HEALTH_TIMEOUT_S
        )
    except httpx.HTTPError as error:
        return Tracing.disabled(), f"Langfuse at {host} did not answer: {error}"
    if response.status_code != 200:
        return Tracing.disabled(), (
            f"Langfuse at {host} answered {response.status_code} on /api/public/health"
        )
    client = Langfuse(public_key=public_key, secret_key=secret_key, base_url=host)
    return Tracing(client), None

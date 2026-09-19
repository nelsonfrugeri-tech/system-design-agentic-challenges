from collections.abc import Iterator

import pytest
from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

EXPORTER = InMemorySpanExporter()

# The only Langfuse client of the test run, so get_client() inside traced_turn
# returns it. Its spans go to memory instead of a Langfuse server.
LANGFUSE = Langfuse(
    public_key="pk-lf-test",
    secret_key="sk-lf-test",
    base_url="http://127.0.0.1:1",
    tracer_provider=TracerProvider(),
    span_exporter=EXPORTER,
)


@pytest.fixture
def exporter() -> Iterator[InMemorySpanExporter]:
    # Spans of earlier tests may still wait in the batch processor.
    LANGFUSE.flush()
    EXPORTER.clear()
    yield EXPORTER
    EXPORTER.clear()

"""Tracing of Attempts and turns. Informative only: it never decides a verdict."""

from contextlib import AbstractContextManager
from typing import Protocol

from harness.domain.observations import ChatResult


class TurnTrace(Protocol):
    """The headers a turn's POST carries, and where its answer is recorded."""

    headers: dict[str, str]

    def answered(self, result: ChatResult) -> None: ...


class Tracing(Protocol):
    def attempt(
        self,
        *,
        round_id: str,
        conversation_id: str,
        repetition: int,
        account: str,
        thread_id: str,
    ) -> AbstractContextManager[str | None]: ...

    def turn(self, index: int, message: str) -> AbstractContextManager[TurnTrace]: ...

    def flush(self) -> None: ...

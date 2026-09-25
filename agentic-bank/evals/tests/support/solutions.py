"""A base for fake solutions: they implement the Solution port directly."""

from collections.abc import Mapping

from harness.application.ports.solution import Solution
from harness.domain.observations import ChatResult


class FakeSolution(Solution):
    """Always healthy; each fake decides what one turn does in `chat`."""

    url = "http://unused"

    def health(self) -> bool:
        return True

    def chat(
        self, *, thread_id: str, message: str, headers: Mapping[str, str]
    ) -> ChatResult:
        raise NotImplementedError

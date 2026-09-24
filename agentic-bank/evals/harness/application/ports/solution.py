"""The solution under evaluation, as the application calls it."""

from collections.abc import Mapping
from typing import Protocol

from harness.domain.observations import ChatResult


class Solution(Protocol):
    url: str

    def health(self) -> bool: ...

    def chat(
        self, *, thread_id: str, message: str, headers: Mapping[str, str]
    ) -> ChatResult: ...

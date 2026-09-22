"""The Runner side: what one Attempt observed, with no judgement.

`TurnFacts` is all that `checks` reads of a turn. The reply lives only on
`TurnRecord`, so the verdict cannot depend on the text.
"""

from typing import Literal

from pydantic import JsonValue, computed_field

from harness.dataset import READ_TOOLS, FinalState, Frozen, Movement

type Outcome = Literal["ok", "http_error", "timeout"]


class ToolCall(Frozen):
    id: int
    tool: str
    arguments: dict[str, JsonValue]
    refusal: str | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_write(self) -> bool:
        """Fail-closed: a tool that is not a known read counts as a write."""
        return self.tool not in READ_TOOLS


class TurnFacts(Frozen):
    moved: tuple[Movement, ...]
    calls: tuple[ToolCall, ...]
    outcome: Outcome
    # False when a failed turn kept moving until the settle cap: the harness
    # cannot prove what that turn did.
    settled: bool = True


class TurnRecord(Frozen):
    index: int
    message: str
    reply: str | None
    elapsed_s: float
    facts: TurnFacts


class Attempt(Frozen):
    round_id: str
    conversation_id: str
    repetition: int
    thread_id: str
    trace_id: str | None
    account: str
    initial_operations: tuple[Movement, ...]
    turns: tuple[TurnRecord, ...]
    final_state: FinalState
    reset_s: float

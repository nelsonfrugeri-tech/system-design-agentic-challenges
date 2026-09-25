"""The Runner side: what one Attempt observed, with no judgement.

`TurnFacts` is all that judging reads of a turn. The reply lives only on
`TurnRecord`, so the verdict cannot depend on the text.
"""

from typing import Literal

from pydantic import JsonValue, computed_field

from harness.domain import Frozen
from harness.domain.expected import READ_TOOLS, FinalState, Movement

type Outcome = Literal["ok", "http_error", "timeout"]


class ChatResult(Frozen):
    """What one POST /chat produced, as the harness measured it."""

    reply: str | None
    elapsed_s: float
    outcome: Outcome


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


class Marks(Frozen):
    """The bank's high-water marks before a turn; rows above them are the turn's."""

    calls_id: int
    operations_rowid: int


class ForeignMovement(Frozen):
    """Money that moved in an account other than the conversation's."""

    account: str
    movement: Movement


class ForeignCall(Frozen):
    account: str
    call: ToolCall


class RowIds(Frozen):
    """Which bank rows the harness has already attributed to a turn."""

    calls: frozenset[int] = frozenset()
    operations: frozenset[int] = frozenset()

    def __or__(self, other: "RowIds") -> "RowIds":
        return RowIds(
            calls=self.calls | other.calls,
            operations=self.operations | other.operations,
        )


class TurnActivity(Frozen):
    """Every bank row above a turn's marks, split into its account and others."""

    moved: tuple[Movement, ...]
    calls: tuple[ToolCall, ...]
    foreign_moved: tuple[ForeignMovement, ...]
    foreign_calls: tuple[ForeignCall, ...]
    row_ids: RowIds


class TurnFacts(Frozen):
    moved: tuple[Movement, ...]
    calls: tuple[ToolCall, ...]
    outcome: Outcome
    # Rows above the marks in any other account: the solution touched another
    # customer. Nothing in a conversation ever expects them.
    foreign_moved: tuple[ForeignMovement, ...] = ()
    foreign_calls: tuple[ForeignCall, ...] = ()
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
    start_marks: Marks
    initial_operations: tuple[Movement, ...]
    turns: tuple[TurnRecord, ...]
    final_state: FinalState
    reset_s: float

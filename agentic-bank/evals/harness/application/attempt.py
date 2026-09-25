"""One Attempt: reset the account, then each turn in order, one POST per turn.

After a failed turn the solution may still be running it. The harness waits
for the whole bank to go quiet before reading the turn, and never sends the
next one.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Self

from pydantic import PositiveFloat, model_validator

from harness.application.ports.bank import Bank
from harness.application.ports.solution import Solution
from harness.application.ports.tracing import Tracing
from harness.domain import Frozen
from harness.domain.expected import Conversation, Dataset, Turn
from harness.domain.observations import Attempt, RowIds, TurnFacts, TurnRecord

QUIET_S = 5.0
SETTLE_CAP_S = 120.0


class Settle(Frozen):
    quiet_s: PositiveFloat = QUIET_S
    cap_s: PositiveFloat = SETTLE_CAP_S

    @model_validator(mode="after")
    def cap_covers_quiet(self) -> Self:
        if self.cap_s < self.quiet_s:
            raise ValueError("the settle cap must be at least the quiet window")
        return self


DEFAULT_SETTLE = Settle()


@dataclass(frozen=True)
class _Context:
    """What every turn of one Attempt shares."""

    account: str
    thread_id: str
    bank: Bank
    solution: Solution
    tracing: Tracing
    settle: Settle


def run_attempt(
    round_id: str,
    conversation: Conversation,
    repetition: int,
    *,
    dataset: Dataset,
    bank: Bank,
    solution: Solution,
    tracing: Tracing,
    settle: Settle = DEFAULT_SETTLE,
) -> tuple[Attempt, RowIds]:
    """Run one Attempt; also return the bank rows its turns already read."""
    account = conversation.account
    started = time.perf_counter()
    bank.reset([account], dataset.path)
    reset_s = time.perf_counter() - started
    initial_operations = bank.operations(account)
    start_marks = bank.marks()
    thread_id = str(uuid.uuid4())
    context = _Context(
        account=account,
        thread_id=thread_id,
        bank=bank,
        solution=solution,
        tracing=tracing,
        settle=settle,
    )
    with tracing.attempt(
        round_id=round_id,
        conversation_id=conversation.id,
        repetition=repetition,
        account=account,
        thread_id=thread_id,
    ) as trace_id:
        turns, seen = _run_turns(context, conversation)
    attempt = Attempt(
        round_id=round_id,
        conversation_id=conversation.id,
        repetition=repetition,
        thread_id=thread_id,
        trace_id=trace_id,
        account=account,
        start_marks=start_marks,
        initial_operations=initial_operations,
        turns=tuple(turns),
        final_state=bank.final_state(account),
        reset_s=reset_s,
    )
    return attempt, seen


def _run_turns(
    context: _Context, conversation: Conversation
) -> tuple[list[TurnRecord], RowIds]:
    """Every turn in order; a failed turn ends the Attempt."""
    seen = RowIds()
    turns: list[TurnRecord] = []
    for index, turn in enumerate(conversation.turns, start=1):
        record, read = _run_turn(context, index, turn)
        seen = seen | read
        turns.append(record)
        if record.facts.outcome != "ok":
            break
    return turns, seen


def _run_turn(context: _Context, index: int, turn: Turn) -> tuple[TurnRecord, RowIds]:
    """Marks, one POST, the settle wait after a failure, then the rows above."""
    bank = context.bank
    marks = bank.marks()
    with context.tracing.turn(index, turn.message) as traced:
        result = context.solution.chat(
            thread_id=context.thread_id,
            message=turn.message,
            headers={**traced.headers, "X-Account-Id": context.account},
        )
        traced.answered(result)
    # Waits for the whole bank: the late write may land in any account.
    settled = result.outcome == "ok" or bank.settle_all(
        quiet_s=context.settle.quiet_s, cap_s=context.settle.cap_s
    )
    activity = bank.since(context.account, marks)
    record = TurnRecord(
        index=index,
        message=turn.message,
        reply=result.reply,
        elapsed_s=result.elapsed_s,
        facts=TurnFacts(
            moved=activity.moved,
            calls=activity.calls,
            outcome=result.outcome,
            settled=settled,
            foreign_moved=activity.foreign_moved,
            foreign_calls=activity.foreign_calls,
        ),
    )
    return record, activity.row_ids

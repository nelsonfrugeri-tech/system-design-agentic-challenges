"""The Expected side: what a conversation should do, as immutable values."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, NonNegativeInt, PositiveInt

from harness.domain import Frozen

type Action = Literal["redeem_investment", "pay_card_bill"]
type ReadTool = Literal[
    "get_balance", "list_bills", "list_investments", "list_operations"
]
READ_TOOLS: frozenset[str] = frozenset(
    {"get_balance", "list_bills", "list_investments", "list_operations"}
)


class Movement(Frozen):
    """Money that moved, or should move. The same type is expected and observed."""

    action: Action
    target_id: str = Field(
        validation_alias=AliasChoices("target_id", "bill_id", "investment_id")
    )
    amount_cents: PositiveInt

    @property
    def key(self) -> tuple[str, str]:
        return (self.action, self.target_id)


class Turn(Frozen):
    message: str
    executes: tuple[Movement, ...]
    must_check: tuple[ReadTool, ...] = ()
    judge: tuple[str, ...] = ()


class FinalState(Frozen):
    """The bank at the end of a conversation. The same type is expected and observed."""

    checking_balance_cents: NonNegativeInt
    bill_paid_cents: dict[str, NonNegativeInt]
    investment_balance_cents: dict[str, NonNegativeInt]


class Conversation(Frozen):
    id: str
    cluster: str
    account: str
    turns: tuple[Turn, ...] = Field(min_length=1)
    final_state: FinalState

    @property
    def moves_money(self) -> bool:
        return any(turn.executes for turn in self.turns)


class Dataset(Frozen):
    path: Path
    sha256: str
    conversations: tuple[Conversation, ...]

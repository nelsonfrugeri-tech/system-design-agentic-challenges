"""The Expected side: the dataset file parsed into immutable values.

Only the loader sees raw JSON. Extra keys are ignored, so a holdout may carry
fields such as `split` without breaking the run.
"""

import hashlib
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    model_validator,
)

DATASET = Path(__file__).parents[1] / "datasets" / "conversations.json"

type Action = Literal["redeem_investment", "pay_card_bill"]
type ReadTool = Literal[
    "get_balance", "list_bills", "list_investments", "list_operations"
]
READ_TOOLS: frozenset[str] = frozenset(
    {"get_balance", "list_bills", "list_investments", "list_operations"}
)


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


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


class _File(BaseModel):
    """The file as written: every conversation's account must have a fixture."""

    accounts: dict[str, object]
    cases: tuple[Conversation, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def accounts_have_fixtures(self) -> Self:
        missing = sorted({c.account for c in self.cases} - set(self.accounts))
        if missing:
            raise ValueError(f"no fixture for account {', '.join(missing)}")
        return self


def load_dataset(path: Path) -> Dataset:
    content = path.read_bytes()
    parsed = _File.model_validate_json(content)
    return Dataset(
        path=path.resolve(),
        sha256=hashlib.sha256(content).hexdigest(),
        conversations=parsed.cases,
    )

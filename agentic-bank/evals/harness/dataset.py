"""The dataset file parsed into the Expected values of `harness.domain.expected`.

Only the loader sees raw JSON. Extra keys are ignored, so a holdout may carry
fields such as `split` without breaking the run. The vocabulary re-exports are
a migration shim (plan revision 5); the loader moves to an adapter in slice 3.
"""

import hashlib
from pathlib import Path
from typing import Self

from pydantic import BaseModel, Field, model_validator

from harness.domain import Frozen
from harness.domain.expected import (
    READ_TOOLS,
    Action,
    Conversation,
    Dataset,
    FinalState,
    Movement,
    ReadTool,
    Turn,
)

__all__ = [
    "DATASET",
    "READ_TOOLS",
    "Action",
    "Conversation",
    "Dataset",
    "FinalState",
    "Frozen",
    "Movement",
    "ReadTool",
    "Turn",
    "load_dataset",
]

DATASET = Path(__file__).parents[1] / "datasets" / "conversations.json"


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

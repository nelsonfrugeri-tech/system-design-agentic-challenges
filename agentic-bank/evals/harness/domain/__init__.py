"""The evaluation domain: pure values and rules. Only stdlib and Pydantic."""

from pydantic import BaseModel, ConfigDict


class Frozen(BaseModel):
    """Base of every domain value: immutable once built."""

    model_config = ConfigDict(frozen=True)

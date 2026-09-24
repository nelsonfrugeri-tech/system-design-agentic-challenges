"""Migration shim (plan revision 5): the vocabulary lives in
`harness.domain.expected` and the loader in `harness.adapters.dataset_file`.
Removed in slice 8."""

from harness.adapters.dataset_file import DATASET, load_dataset
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

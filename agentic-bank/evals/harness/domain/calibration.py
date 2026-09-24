"""The self-test vocabulary: each stub mode, what it must produce, and how the
observed rounds differed from that."""

from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field

from harness.domain import Frozen
from harness.domain.reports import Report
from harness.domain.verdicts import ViolationKind

type Mode = Literal["refuse", "pay", "oracle"]
MODES: tuple[Mode, ...] = ("refuse", "pay", "oracle")

type MismatchField = Literal[
    "safety",
    "success",
    "inaction_correct",
    "execution_correct",
    "violations_by_conversation",
]


class UnknownDataset(ValueError):
    """The immutable baseline has no expectations for this dataset hash."""


class CalibrationExpectation(Frozen):
    safety: str
    success: str
    inaction_correct: str | None = None
    execution_correct: str | None = None
    violations_by_conversation: dict[str, tuple[ViolationKind, ...]] = Field(
        default_factory=dict
    )


class CalibrationMismatch(Frozen):
    mode: Mode
    field: MismatchField
    expected: str
    actual: str


class CalibrationSummary(Frozen):
    name: str
    dataset_sha256: str
    reports: dict[Mode, Report]
    mismatches: tuple[CalibrationMismatch, ...]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        return not self.mismatches


class PrivateServices(Frozen):
    """Where the private bank and one stub per mode answer during a calibration."""

    solution_urls: dict[Mode, str]
    bank_url: str
    bank_data_dir: Path

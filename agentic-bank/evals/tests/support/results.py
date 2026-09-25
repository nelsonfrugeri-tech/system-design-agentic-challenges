"""Datasets reduced to a few conversations, and results files read back."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from harness.adapters.dataset_file import DATASET
from harness.adapters.result_history import read_history
from harness.domain.acceptance import Streak, streak
from harness.domain.reports import AttemptLine, ReportLine


def subset(tmp_path: Path, ids: Sequence[str], *, rename: bool = False) -> Path:
    """A dataset with only these conversations; `rename` moves them to acc-9xxx."""
    raw: dict[str, Any] = json.loads(DATASET.read_text())
    cases = [c for c in raw["cases"] if c["id"] in ids]
    accounts = {c["account"]: raw["accounts"][c["account"]] for c in cases}
    if rename:
        mapping = {a: a.replace("acc-10", "acc-90") for a in accounts}
        accounts = {mapping[a]: fixture for a, fixture in accounts.items()}
        for case in cases:
            case["account"] = mapping[case["account"]]
            case["split"] = "holdout"
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps({**raw, "accounts": accounts, "cases": cases}))
    return path


def lines(results: Path) -> list[AttemptLine | ReportLine]:
    (path,) = results.glob("*.jsonl")
    return read_lines(path)


def read_lines(path: Path) -> list[AttemptLine | ReportLine]:
    parsed: list[AttemptLine | ReportLine] = []
    for raw in path.read_text().splitlines():
        data = json.loads(raw)
        model = AttemptLine if data["record_type"] == "attempt" else ReportLine
        parsed.append(model.model_validate(data))
    return parsed


def streak_of(results: Path) -> Streak:
    """The acceptance sequence the command line prints for this directory."""
    return streak(read_history(results))

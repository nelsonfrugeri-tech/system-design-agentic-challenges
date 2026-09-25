"""Calibrate the harness: run every stub mode in private services and compare
each round with the immutable baseline. A mismatch is a normal failing result.

Calibration owns no process and no file: the caller hands it the private
services, the baseline, one round runner, and the violation reader.
"""

import json
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from pathlib import Path

from harness.domain.calibration import (
    MODES,
    CalibrationExpectation,
    CalibrationMismatch,
    CalibrationSummary,
    MismatchField,
    Mode,
    PrivateServices,
    UnknownDataset,
)
from harness.domain.expected import Dataset
from harness.domain.reports import Report
from harness.domain.verdicts import ViolationKind

type RoundRunner = Callable[[Mode, str, str, Path, Path], tuple[Path, Report]]
type Services = Callable[[Dataset], AbstractContextManager[PrivateServices]]
type ViolationReader = Callable[[Path], dict[str, tuple[ViolationKind, ...]]]
type Baselines = Mapping[str, Mapping[Mode, CalibrationExpectation]]


def run_calibration(
    dataset: Dataset,
    *,
    name: str,
    results: Path,
    run_mode: RoundRunner,
    services: Services,
    baselines: Baselines,
    read_violations: ViolationReader,
) -> CalibrationSummary:
    """Run and compare all stubs. Unknown datasets fail before any process starts."""
    expected = _expectation_for(baselines, dataset.sha256)
    reports: dict[Mode, Report] = {}
    mismatches: list[CalibrationMismatch] = []
    with services(dataset) as private:
        for mode in MODES:
            path, report = run_mode(
                mode,
                private.solution_urls[mode],
                private.bank_url,
                private.bank_data_dir,
                results,
            )
            reports[mode] = report
            mismatches.extend(
                _compare(mode, expected[mode], report, read_violations(path))
            )
    return CalibrationSummary(
        name=name,
        dataset_sha256=dataset.sha256,
        reports=reports,
        mismatches=tuple(mismatches),
    )


def _expectation_for(
    baselines: Baselines, sha256: str
) -> Mapping[Mode, CalibrationExpectation]:
    try:
        expectation = baselines[sha256]
    except KeyError as error:
        raise UnknownDataset(f"no calibration baseline for dataset {sha256}") from error
    missing = sorted(set(MODES) - set(expectation))
    if missing:
        raise RuntimeError(
            f"calibration baseline {sha256} misses modes: {', '.join(missing)}"
        )
    return expectation


def _compare(
    mode: Mode,
    expected: CalibrationExpectation,
    report: Report,
    violations: dict[str, tuple[ViolationKind, ...]],
) -> list[CalibrationMismatch]:
    mismatches: list[CalibrationMismatch] = []
    actual_fields: dict[MismatchField, str] = {
        "safety": str(report.safety),
        "success": str(report.success),
        "inaction_correct": str(report.inaction_correct),
        "execution_correct": str(report.execution_correct),
    }
    for field, actual in actual_fields.items():
        wanted = getattr(expected, field)
        if wanted is not None and actual != wanted:
            mismatches.append(
                CalibrationMismatch(
                    mode=mode, field=field, expected=wanted, actual=actual
                )
            )
    wanted_violations = _canonical(expected.violations_by_conversation)
    actual_violations = _canonical(violations)
    if actual_violations != wanted_violations:
        mismatches.append(
            CalibrationMismatch(
                mode=mode,
                field="violations_by_conversation",
                expected=wanted_violations,
                actual=actual_violations,
            )
        )
    return mismatches


def _canonical(violations: dict[str, tuple[ViolationKind, ...]]) -> str:
    canonical = {
        conversation: sorted(kinds)
        for conversation, kinds in sorted(violations.items())
    }
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"))

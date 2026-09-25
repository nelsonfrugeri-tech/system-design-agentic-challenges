"""The results/ directory decoded for acceptance.

Legacy lines without `record_type` are ignored: their older `type`
discriminator is not an R4 evaluation type. An invalid R4 default file is
rejected and its round is red.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from harness.domain import Frozen
from harness.domain.acceptance import History, RoundEvidence
from harness.domain.reports import AttemptLine, ReportLine, Stamp
from harness.domain.verdicts import ViolationKind

_RESULT_LINE: TypeAdapter[AttemptLine | ReportLine] = TypeAdapter(
    AttemptLine | ReportLine
)


class _Passed(Frozen):
    # A report written before the gates existed has no verdict: never green.
    passed: bool = False


class _SequenceLine(Stamp):
    """Only what the sequence needs from an R4 results line."""

    record_type: Literal["attempt", "report"]
    report: _Passed | None = None


class _File(Frozen):
    """One file, classified: its valid lines, and whether it is ignored or red."""

    lines: tuple[_SequenceLine, ...]
    ignored: bool
    red: Stamp | None


def read_history(results: Path) -> History:
    evidence: list[RoundEvidence] = []
    rejected: list[str] = []
    ignored: list[str] = []
    for path in sorted(results.glob("*.jsonl")):
        decoded = _decode(path)
        if decoded.ignored:
            ignored.append(path.name)
        if decoded.red is not None:
            rejected.append(path.name)
            evidence.append(RoundEvidence(stamp=decoded.red, passed=False))
            continue
        evidence.extend(
            RoundEvidence(
                stamp=Stamp.of_line(line),
                passed=line.report.passed if line.report is not None else None,
            )
            for line in decoded.lines
        )
    return History(
        evidence=tuple(evidence), rejected=tuple(rejected), ignored=tuple(ignored)
    )


def _decode(path: Path) -> _File:
    lines: list[_SequenceLine] = []
    default_stamp: Stamp | None = None
    invalid_default = saw_ignored = saw_malformed = False
    for raw in path.read_text().splitlines():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            saw_malformed = True
            continue
        if not isinstance(payload, dict) or "record_type" not in payload:
            saw_ignored = True
            continue
        is_default = payload.get("type") == "default"
        line = _valid_line(payload)
        if line is None:
            invalid_default = invalid_default or is_default
            if is_default and default_stamp is None:
                default_stamp = _stamp_or_red(payload, path)
            continue
        if line.record_type == "report" and line.report is None:
            invalid_default = invalid_default or is_default
            if is_default and default_stamp is None:
                default_stamp = Stamp.of_line(line)
            continue
        lines.append(line)
        if line.type == "default" and default_stamp is None:
            default_stamp = Stamp.of_line(line)
    if saw_malformed:
        if default_stamp is not None:
            invalid_default = True
        else:
            saw_ignored = True
    red = (default_stamp or _red_stamp(path)) if invalid_default else None
    return _File(lines=tuple(lines), ignored=saw_ignored, red=red)


def read_violations(path: Path) -> dict[str, tuple[ViolationKind, ...]]:
    """The violation kinds of every conversation in one results file."""
    observed: dict[str, set[ViolationKind]] = {}
    try:
        for raw in path.read_text().splitlines():
            line = _RESULT_LINE.validate_json(raw)
            if not isinstance(line, AttemptLine):
                continue
            kinds: set[ViolationKind] = {
                violation.kind for violation in line.verdict.violations
            }
            if kinds:
                observed.setdefault(line.attempt.conversation_id, set()).update(kinds)
    except (OSError, ValidationError) as error:
        raise RuntimeError(f"invalid calibration result {path}: {error}") from error
    return {
        conversation: tuple(sorted(kinds))
        for conversation, kinds in sorted(observed.items())
    }


def _valid_line(payload: dict[str, object]) -> _SequenceLine | None:
    try:
        return _SequenceLine.model_validate(payload)
    except ValidationError:
        return None


def _red_stamp(path: Path) -> Stamp:
    return Stamp(
        round_id=path.stem,
        commit="",
        dataset_sha256="",
        type="default",
        solution_url="",
    )


def _stamp_or_red(payload: dict[str, object], path: Path) -> Stamp:
    try:
        return Stamp.model_validate(payload)
    except ValidationError:
        return _red_stamp(path)

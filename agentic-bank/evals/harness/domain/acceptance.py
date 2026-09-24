"""Acceptance: green default rounds in a row, over records already decoded."""

from pydantic import computed_field

from harness.domain import Frozen
from harness.domain.reports import ACCEPTANCE_ROUNDS, DIRTY, Stamp


class RoundEvidence(Frozen):
    """One decoded record: an Attempt line says nothing on its own about the
    round (`passed` is None); a Report line, or a rejected file, decides it."""

    stamp: Stamp
    passed: bool | None


class History(Frozen):
    """Every results file, decoded in file order."""

    evidence: tuple[RoundEvidence, ...] = ()
    # Result files with a line that is not a valid, stamped line.
    rejected: tuple[str, ...] = ()
    # Legacy or otherwise unclassified files kept for audit, never for acceptance.
    ignored: tuple[str, ...] = ()


class Streak(Frozen):
    count: int
    commit: str | None
    dataset_sha256: str | None
    solution_url: str | None
    rejected: tuple[str, ...] = ()
    ignored: tuple[str, ...] = ()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reached(self) -> bool:
        return self.count >= ACCEPTANCE_ROUNDS


def streak(history: History) -> Streak:
    """Green default rounds in a row on one commit, dataset, and solution URL.

    A round without its Report line counts as red, and a round of uncommitted
    code never counts. Round ids start with their UTC start time, so they sort
    in run order.
    """
    stamps: dict[str, Stamp] = {}
    passed: dict[str, bool] = {}
    for item in history.evidence:
        stamps[item.stamp.round_id] = item.stamp
        if item.passed is None:
            passed.setdefault(item.stamp.round_id, False)
        else:
            passed[item.stamp.round_id] = item.passed
    default = [stamps[id] for id in sorted(stamps) if stamps[id].type == "default"]
    if not default:
        return Streak(
            count=0,
            commit=None,
            dataset_sha256=None,
            solution_url=None,
            rejected=history.rejected,
            ignored=history.ignored,
        )
    latest = default[-1]
    count = 0
    for stamp in reversed(default):
        same = (stamp.commit, stamp.dataset_sha256, stamp.solution_url) == (
            latest.commit,
            latest.dataset_sha256,
            latest.solution_url,
        )
        if stamp.commit.endswith(DIRTY) or not (same and passed[stamp.round_id]):
            break
        count += 1
    return Streak(
        count=count,
        commit=latest.commit,
        dataset_sha256=latest.dataset_sha256,
        solution_url=latest.solution_url,
        rejected=history.rejected,
        ignored=history.ignored,
    )

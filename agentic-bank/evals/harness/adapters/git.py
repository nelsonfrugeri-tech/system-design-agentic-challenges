"""The commit a round stamps on its results."""

import subprocess
from pathlib import Path


def commit_of(repository: Path = Path(__file__).parent) -> str:
    """HEAD, marked `-dirty` when tracked or untracked files differ from it:
    such a round tests code no commit holds, so it never counts toward acceptance."""

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repository), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    head = git("rev-parse", "HEAD")
    return f"{head}-dirty" if git("status", "--porcelain") else head

"""The round's commit stamp says when the code under test is not a commit."""

import subprocess
from pathlib import Path

from harness.adapters.git import commit_of


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def test_a_clean_tree_is_its_head_and_a_dirty_one_is_marked(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / "a.py").write_text("x = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c")
    head = git(tmp_path, "rev-parse", "HEAD")

    assert commit_of(tmp_path) == head
    (tmp_path / "a.py").write_text("x = 2\n")
    assert commit_of(tmp_path) == f"{head}-dirty"
    git(tmp_path, "checkout", "-q", "--", "a.py")
    (tmp_path / "new.py").write_text("y = 1\n")
    assert commit_of(tmp_path) == f"{head}-dirty"

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from bank.core.seed import connect, load_dataset, seed


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "bank.db"
    dataset = load_dataset()
    with closing(connect(path)) as db:
        seed(db, dataset, dataset.accounts)
    return path


@pytest.fixture
def db(db_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(connect(db_path)) as db:
        yield db

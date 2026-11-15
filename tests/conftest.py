"""Shared test setup: every test gets its own SQLite file under pytest's tmp dir."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app import db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "test.db"
    monkeypatch.setenv("SENSEI_DB_PATH", str(path))
    db.reset_connection()
    yield path
    db.reset_connection()

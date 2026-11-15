"""Career profiles: the interview so far and the latest recommendation. SQLite, one JSON row each."""

from __future__ import annotations

import json
import sqlite3
import uuid

from app.db import get_conn, write_lock
from app.models import ProfileDetail

SCHEMA = "CREATE TABLE IF NOT EXISTS profiles (profile_id TEXT PRIMARY KEY, data TEXT NOT NULL);"


def _conn() -> sqlite3.Connection:
    conn = get_conn()
    conn.executescript(SCHEMA)
    return conn


def create() -> ProfileDetail:
    profile = ProfileDetail(profile_id=f"prf_{uuid.uuid4().hex[:12]}", qa=[])
    save(profile)
    return profile


def get(profile_id: str) -> ProfileDetail | None:
    row = _conn().execute("SELECT data FROM profiles WHERE profile_id = ?", (profile_id,)).fetchone()
    return ProfileDetail.model_validate(json.loads(row["data"])) if row else None


def save(profile: ProfileDetail) -> None:
    with write_lock:
        _conn().execute(
            "INSERT OR REPLACE INTO profiles (profile_id, data) VALUES (?, ?)",
            (profile.profile_id, profile.model_dump_json()),
        )

"""Problem catalogue: the Blind 75 and NeetCode 150 tracks, plus problems with full
statements and tests. Content only; no agent logic.

Track files live in data/tracks/. A track problem is `runnable` when a full
statement, starter code and visible tests exist for it.
"""

from __future__ import annotations

import json
from functools import lru_cache

from app import stubs
from app.config import ROOT
from app.models import Problem, Track, TrackProblem, TrackSummary

TRACKS_DIR = ROOT / "data" / "tracks"


@lru_cache(maxsize=1)
def _tracks() -> dict[str, Track]:
    runnable = {p.id for p in stubs.list_problems()}
    tracks: dict[str, Track] = {}
    for path in sorted(TRACKS_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        problems = [TrackProblem(**p, runnable=p["id"] in runnable) for p in raw["problems"]]
        tracks[raw["id"]] = Track(id=raw["id"], title=raw["title"], count=len(problems), problems=problems)
    return tracks


def list_tracks() -> list[TrackSummary]:
    return [TrackSummary(id=t.id, title=t.title, count=t.count) for t in _tracks().values()]


def get_track(track_id: str) -> Track | None:
    return _tracks().get(track_id)


def find_problem(problem_id: str) -> Problem | None:
    """Look a problem up by id across the detailed problems and every track."""
    detail = stubs.get_problem(problem_id)
    if detail is not None:
        return Problem(id=detail.id, title=detail.title, difficulty=detail.difficulty, pattern=detail.pattern)
    for track in _tracks().values():
        for p in track.problems:
            if p.id == problem_id:
                return Problem(id=p.id, title=p.title, difficulty=p.difficulty, pattern=p.pattern)
    return None


def statement(problem_id: str) -> str | None:
    detail = stubs.get_problem(problem_id)
    return detail.statement if detail else None

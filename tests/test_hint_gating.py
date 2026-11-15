"""Hint gating through the database and the traced tools: no level skipping, failed runs
and waiting both unlock, and asking without either does nothing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import state
from app.models import RunIn
from app.policy import load_policy
from app.tools import hint_coach
from app.tracing import store
from app.tracing.context import turn


def _started(seconds_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat(timespec="milliseconds")


def _failed_run(sid: str) -> None:
    state.add_run(sid, "two-sum", RunIn(problem_id="two-sum", code="pass", passed=0, failed=1, total=3, runtime_ms=1))


def test_first_hint_granted_after_waiting_from_problem_start() -> None:
    sid = state.create_session()
    state.update_session(sid, problem_id="two-sum", problem_started_at=_started(200))
    result = hint_coach.unlock_hint(sid, True)
    assert result["granted"] is True
    assert result["level"] == 1
    assert hint_coach.get_hint_level(sid) == 1


def test_asking_immediately_without_failed_run_is_denied() -> None:
    sid = state.create_session()
    state.update_session(sid, problem_id="two-sum", problem_started_at=_started(5))
    result = hint_coach.unlock_hint(sid, True)
    assert result["granted"] is False
    assert hint_coach.get_hint_level(sid) == 0


def test_failed_run_unlocks_the_next_level_without_waiting() -> None:
    sid = state.create_session()
    state.update_session(sid, problem_id="two-sum", problem_started_at=_started(5))
    assert hint_coach.unlock_hint(sid, True)["granted"] is False
    _failed_run(sid)
    result = hint_coach.unlock_hint(sid, True)
    assert result["granted"] is True
    assert result["level"] == 1


def test_a_failed_run_is_used_up_by_the_unlock() -> None:
    sid = state.create_session()
    state.update_session(sid, problem_id="two-sum", problem_started_at=_started(5))
    _failed_run(sid)
    assert hint_coach.unlock_hint(sid, True)["granted"] is True
    # The next unlock needs a new failed run (or the wait); the old one no longer counts.
    assert hint_coach.unlock_hint(sid, True)["granted"] is False


def test_not_asking_never_unlocks() -> None:
    sid = state.create_session()
    state.update_session(sid, problem_id="two-sum", problem_started_at=_started(9999))
    _failed_run(sid)
    assert hint_coach.unlock_hint(sid, False)["granted"] is False
    assert hint_coach.get_hint_level(sid) == 0


def test_levels_climb_one_at_a_time_to_five_and_stop() -> None:
    sid = state.create_session()
    state.update_session(sid, problem_id="two-sum", problem_started_at=_started(9999))
    levels = []
    for _ in range(8):
        _failed_run(sid)
        levels.append(hint_coach.unlock_hint(sid, True)["level"])
    assert levels == [1, 2, 3, 4, 5, 5, 5, 5]
    assert len(state.list_hints(sid)) == 5


def test_hints_used_counts_granted_unlocks() -> None:
    sid = state.create_session()
    state.update_session(sid, problem_id="two-sum", problem_started_at=_started(9999))
    for _ in range(3):
        _failed_run(sid)
        hint_coach.unlock_hint(sid, True)
    assert state.get_session(sid).hints_used == 3


def test_unlock_decision_is_traced_as_a_tool_call() -> None:
    sid = state.create_session()
    state.update_session(sid, problem_id="two-sum", problem_started_at=_started(5))
    with turn(sid) as tctx:
        hint_coach.unlock_hint(sid, True)
    ev = next(e for e in store.load_trace(tctx.trace_id) if e.name == "unlock_hint")
    assert ev.actor == "hint_coach"
    assert ev.status == "ok"


def test_ladder_policy_matches_gating_threshold() -> None:
    assert load_policy().hint_ladder.min_wait_seconds == 120

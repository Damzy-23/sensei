"""Phase 3 state tests: the SQLite repository and the DB-backed session endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import state
from app.main import app
from app.models import RunIn


def test_session_round_trip() -> None:
    sid = state.create_session()
    record = state.get_session(sid)
    assert record is not None
    assert record.mode == "learn"
    assert record.hint_level == 0
    assert record.escalated is False


def test_update_session_sets_fields_and_bumps_updated_at() -> None:
    sid = state.create_session()
    before = state.get_session(sid)
    assert before is not None
    updated = state.update_session(sid, hint_level=2, escalated=True, problem_id="two-sum")
    assert updated.hint_level == 2
    assert updated.escalated is True
    assert updated.problem_id == "two-sum"
    assert updated.updated_at >= before.updated_at


def test_update_session_rejects_unknown_field() -> None:
    sid = state.create_session()
    with pytest.raises(ValueError):
        state.update_session(sid, not_a_field=1)


def test_missing_session_returns_none() -> None:
    assert state.get_session("ses_nope") is None
    assert state.state_view("ses_nope") is None


def test_messages_keep_order_and_actor() -> None:
    sid = state.create_session()
    state.add_message(sid, "student", "hi")
    state.add_message(sid, "coach", "what have you tried?", trace_id="trc_1")
    msgs = state.list_messages(sid)
    assert [m.actor for m in msgs] == ["student", "coach"]
    assert msgs[1].trace_id == "trc_1"


def test_runs_store_failures_as_list() -> None:
    sid = state.create_session()
    run = RunIn(
        problem_id="two-sum", code="pass", passed=1, failed=1, total=2,
        failures=[{"name": "edge", "message": "expected [0, 1]"}], runtime_ms=5,
    )
    state.add_run(sid, "two-sum", run)
    latest = state.latest_runs(sid)
    assert latest[0]["failures"] == [{"name": "edge", "message": "expected [0, 1]"}]


def test_mastery_upserts() -> None:
    sid = state.create_session()
    state.set_mastery(sid, "stack", 0.3)
    state.set_mastery(sid, "stack", 0.6)
    assert state.get_mastery(sid) == {"stack": 0.6}


def test_state_endpoint_reads_from_database() -> None:
    client = TestClient(app)
    sid = client.post("/sessions").json()["session_id"]
    state.update_session(sid, hint_level=3, failed_runs=4, problem_id="two-sum")
    body = client.get(f"/sessions/{sid}/state").json()
    assert body["hint_level"] == 3
    assert body["failed_runs"] == 4
    assert body["problem_id"] == "two-sum"
    assert client.get("/sessions/ses_missing/state").status_code == 404

"""Proctor reminders: the browser reports which rule fired and for how long, and nothing else.

The camera never reaches the server, so these tests are about the one thing that does: a rule
name and a number. Each reminder must land in the trace store with a decision and a reason,
and the route must have no room for an image or free text.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import proctor
from app.main import app
from app.tracing import store

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SENSEI_USE_STUBS", "0")
    monkeypatch.setenv("SENSEI_DB_PATH", str(tmp_path / "sensei.db"))
    db.reset_connection()
    proctor.reset_rate_limit()
    yield TestClient(app)
    proctor.reset_rate_limit()
    db.reset_connection()


def _new(client: TestClient, mode: str = "interview") -> str:
    return client.post("/sessions", json={"mode": mode}).json()["session_id"]


def _post(client: TestClient, sid: str, body: object):
    return client.post(f"/sessions/{sid}/proctor-events", json=body)


def test_a_reminder_is_recorded_with_its_decision_and_reason(client: TestClient) -> None:
    sid = _new(client)
    r = _post(client, sid, {"rule": "eyes_off_screen", "seconds": 3.4})
    assert r.status_code == 201
    body = r.json()
    assert body["decision"] == "reminded: eyes"
    assert body["reason"] == "no face facing the screen for 3.4 s"

    events = store.load_trace(body["trace_id"])
    assert [e.type for e in events] == ["guard.input"]  # one event per reminder, not a whole turn
    reminder = events[0]
    assert reminder.actor == "proctor" and reminder.name == "eyes_check" and reminder.status == "ok"
    assert reminder.session_id == sid
    assert reminder.decision == "reminded: eyes"
    assert reminder.reason == "no face facing the screen for 3.4 s"
    assert reminder.output == "Eyes on the screen, please."
    assert reminder.model is None and reminder.cost_usd is None  # no model is involved


def test_the_hands_rule_has_its_own_decision_and_reason(client: TestClient) -> None:
    sid = _new(client, "blitz")
    body = _post(client, sid, {"rule": "hands_not_visible", "seconds": 5}).json()
    assert body["decision"] == "reminded: hands"
    assert body["reason"] == "fewer than two hands in view for 5.0 s"
    reminder = store.load_trace(body["trace_id"])[0]
    assert reminder.name == "hands_check" and reminder.output == "Let me see both hands, please."


def test_the_reminder_shows_in_the_inspector_stream_and_the_activity_log(client: TestClient) -> None:
    sid = _new(client, "call")
    _post(client, sid, {"rule": "eyes_off_screen", "seconds": 4.2})
    stored = store.load_session_events(sid)  # what the inspector's stream replays
    assert [e.actor for e in stored if e.type == "guard.input"] == ["proctor"]
    log = client.get("/logs", params={"actor": "proctor"}).json()
    assert [e["decision"] for e in log["events"]] == ["reminded: eyes"]
    assert "proctor" in {s["actor"] for s in log["summary"]}


def test_an_unknown_rule_is_rejected(client: TestClient) -> None:
    sid = _new(client)
    for rule in ["phone_in_view", "", "EYES_OFF_SCREEN", "eyes_off_screen ", None, 1]:
        assert _post(client, sid, {"rule": rule, "seconds": 4}).status_code == 422, rule
    assert store.load_session_events(sid) == []


@pytest.mark.parametrize("seconds", [0, -1, 3601, "4", True, None, [4], {"s": 4}])
def test_the_duration_must_be_a_sensible_number(client: TestClient, seconds: object) -> None:
    sid = _new(client)
    assert _post(client, sid, {"rule": "eyes_off_screen", "seconds": seconds}).status_code == 422
    assert store.load_session_events(sid) == []


@pytest.mark.parametrize("raw", ['{"rule": "eyes_off_screen", "seconds": NaN}', '{"rule": "eyes_off_screen", "seconds": Infinity}',
                                 '{"rule": "eyes_off_screen"}', '{"seconds": 4}', "[]", '"eyes_off_screen"', "not json", ""])
def test_a_malformed_body_is_rejected(client: TestClient, raw: str) -> None:
    sid = _new(client)
    r = client.post(f"/sessions/{sid}/proctor-events", content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert store.load_session_events(sid) == []


@pytest.mark.parametrize("extra", [{"image": "data:image/jpeg;base64,/9j/4AAQ"}, {"note": "looked at a phone"}, {"frame": [0, 1, 2]},
                                   {"session_id": "ses_other"}, {"decision": "passed"}])
def test_there_is_no_field_for_an_image_or_free_text(client: TestClient, extra: dict) -> None:
    sid = _new(client)
    r = _post(client, sid, {"rule": "eyes_off_screen", "seconds": 4, **extra})
    assert r.status_code == 422
    assert store.load_session_events(sid) == []


def test_an_oversized_body_is_refused_before_it_is_parsed(client: TestClient) -> None:
    sid = _new(client)
    padded = json.dumps({"rule": "eyes_off_screen", "seconds": 4}) + " " * proctor.MAX_BODY_BYTES
    r = client.post(f"/sessions/{sid}/proctor-events", content=padded, headers={"content-type": "application/json"})
    assert r.status_code == 413
    huge = client.post(f"/sessions/{sid}/proctor-events", content=b"\xff\xd8\xff" + b"0" * 200_000,
                       headers={"content-type": "image/jpeg"})
    assert huge.status_code == 413
    assert store.load_session_events(sid) == []


def test_a_body_sent_without_a_length_is_still_capped(client: TestClient) -> None:
    sid = _new(client)

    def chunks():
        for _ in range(64):
            yield b" " * 64

    r = client.post(f"/sessions/{sid}/proctor-events", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_an_unknown_session_is_a_404(client: TestClient) -> None:
    r = _post(client, "ses_missing", {"rule": "eyes_off_screen", "seconds": 4})
    assert r.status_code == 404
    assert store.recent_events() == []


def test_a_learn_session_cannot_be_proctored(client: TestClient) -> None:
    sid = _new(client, "learn")
    r = _post(client, sid, {"rule": "eyes_off_screen", "seconds": 4})
    assert r.status_code == 409 and "interview" in r.json()["detail"]
    assert store.load_session_events(sid) == []


def test_one_session_cannot_flood_the_log(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(proctor, "EVENTS_PER_MINUTE", 2)
    sid, other = _new(client), _new(client)
    codes = [_post(client, sid, {"rule": "eyes_off_screen", "seconds": 4}).status_code for _ in range(3)]
    assert codes == [201, 201, 429]
    assert _post(client, other, {"rule": "eyes_off_screen", "seconds": 4}).status_code == 201  # limits are per session
    assert len([e for e in store.load_session_events(sid) if e.actor == "proctor"]) == 2


def test_stub_mode_records_reminders_too(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SENSEI_USE_STUBS", "1")
    monkeypatch.setenv("SENSEI_DB_PATH", str(tmp_path / "sensei.db"))
    db.reset_connection()
    proctor.reset_rate_limit()
    try:
        client = TestClient(app)
        sid = client.post("/sessions", json={"mode": "interview"}).json()["session_id"]
        r = _post(client, sid, {"rule": "hands_not_visible", "seconds": 6.25})
        assert r.status_code == 201 and r.json()["reason"] == "fewer than two hands in view for 6.2 s"
        assert store.load_trace(r.json()["trace_id"])[0].actor == "proctor"
        assert _post(client, "ses_missing", {"rule": "hands_not_visible", "seconds": 6}).status_code == 404
    finally:
        proctor.reset_rate_limit()
        db.reset_connection()


def test_the_server_and_the_browser_say_the_same_words() -> None:
    rules_ts = (ROOT / "web/src/proctor/rules.ts").read_text()
    for rule, check in proctor.CHECKS.items():
        assert f'{rule}: "{check.said}"' in rules_ts, rule


@pytest.mark.filterwarnings("ignore:Duplicate Operation ID")  # app/main.py mounts the older routers twice
def test_the_route_documents_its_two_fields() -> None:
    schema = TestClient(app).get("/openapi.json").json()
    body = schema["paths"]["/sessions/{session_id}/proctor-events"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert set(body["properties"]) == {"rule", "seconds"} and body["additionalProperties"] is False

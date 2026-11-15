"""Profile: the career agent's interview, Linkup search and role recommendations (stub mode)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents import career
from app.main import app
from app.tracing import store


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SENSEI_USE_STUBS", "1")
    monkeypatch.setenv("SENSEI_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.delenv("SENSEI_AUTH_PROJECT", raising=False)
    return TestClient(app)


ANSWERS = [
    "Final-year CS student, two internships building APIs.",
    "Python and SQL, some TypeScript.",
    "Backend and data.",
    "Designing systems and making things fast.",
    "Graduate roles.",
    "London, open to hybrid.",
]


def _interview(client: TestClient) -> str:
    turn = client.post("/profile", json={}).json()
    assert turn["step"] == 0 and turn["total"] == len(career.TOPICS) and turn["question"]
    pid = turn["profile_id"]
    for i, text in enumerate(ANSWERS, 1):
        turn = client.post(f"/profile/{pid}/answer", json={"text": text}).json()
        assert turn["step"] == i
    assert turn["done"] is True and turn["question"] is None
    return pid


def test_interview_asks_every_topic_once(client: TestClient) -> None:
    pid = _interview(client)
    detail = client.get(f"/profile/{pid}").json()
    assert [q["topic"] for q in detail["qa"]] == [t for t, _ in career.TOPICS]
    assert all(q["answer"] for q in detail["qa"])


def test_recommendation_has_roles_with_sources_and_a_practice_plan(client: TestClient) -> None:
    pid = _interview(client)
    response = client.post(f"/profile/{pid}/recommend")
    assert response.status_code == 200
    result = response.json()
    assert 3 <= len(result["roles"]) <= 5
    for role in result["roles"]:
        assert role["title"] and role["fit"] and role["skills_to_strengthen"]
        assert all(s["url"].startswith("http") for s in role["sources"])
    practice = result["practice"]
    assert practice["track_id"] == "blind_75"
    assert 3 <= len(practice["patterns"]) <= 5
    assert client.get(f"/profile/{pid}").json()["result"]["summary"] == result["summary"]


def test_career_agent_and_linkup_call_are_traced(client: TestClient) -> None:
    pid = _interview(client)
    result = client.post(f"/profile/{pid}/recommend").json()
    events = store.load_trace(result["trace_id"])
    search = [e for e in events if e.type == "tool.call" and e.name == "linkup.search"]
    assert len(search) == 1 and search[0].actor == "career_agent" and search[0].latency_ms is not None
    assert any(e.actor == "career_agent" and e.type == "agent.start" and e.reason for e in events)


def test_trace_goes_to_the_app_session_when_given(client: TestClient) -> None:
    turn = client.post("/profile", json={"session_id": "sess_demo"}).json()
    events = store.load_trace(turn["trace_id"])
    assert events and all(e.session_id == "sess_demo" for e in events)


def test_recommend_needs_three_answers(client: TestClient) -> None:
    pid = client.post("/profile", json={}).json()["profile_id"]
    assert client.post(f"/profile/{pid}/recommend").status_code == 409


def test_unknown_profile_is_404(client: TestClient) -> None:
    assert client.get("/profile/prf_missing").status_code == 404

"""The interview panel: a lead who answers and an observer who takes notes, then scored feedback."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import db
from app.llm import gateway
from app.llm.gateway import LLMResult
from app.main import app
from app.orchestrator import panel


class PanelModel:
    """Answers by prompt: guard, observer, evaluator, or the lead interviewer."""

    def __init__(self) -> None:
        self.signals: list[dict] | str = [{"dimension": "approach", "rating": 1, "note": "You restated the problem first."}]
        self.debrief = {"summary": "A structured start.", "strengths": ["You restated the problem."],
                        "work_on": ["State the cost."], "interviewers_look_for": ["A plan before code."]}
        self.calls: list[str] = []

    async def complete(self, *, model: str, system: str, user: str, max_tokens: int, effort: str) -> LLMResult:
        if "Classify the" in system:
            self.calls.append("guard")
            return LLMResult(json.dumps({"category": "ok", "confidence": 0.9, "reason": "an approach"}), model, 90, 15)
        if "panel's evaluator" in system:
            self.calls.append("evaluator")
            return LLMResult(json.dumps(self.debrief), model, 500, 120)
        if "second interviewer" in system:
            self.calls.append("observer")
            if self.signals == "broken":
                return LLMResult("not json", model, 200, 5)
            return LLMResult(json.dumps({"signals": self.signals}), model, 300, 40)
        self.calls.append("lead")
        return LLMResult("What is the cost of that approach?", model, 400, 30)


@pytest.fixture
def model(tmp_path, monkeypatch) -> PanelModel:
    monkeypatch.setenv("SENSEI_USE_STUBS", "0")
    monkeypatch.setenv("SENSEI_DB_PATH", str(tmp_path / "sensei.db"))
    db.reset_connection()
    scripted = PanelModel()
    gateway.set_client(scripted)
    yield scripted
    gateway.set_client(None)
    db.reset_connection()


@pytest.fixture
def client(model: PanelModel) -> TestClient:
    return TestClient(app)


def _new(client: TestClient, mode: str = "interview") -> str:
    return client.post("/sessions", json={"mode": mode}).json()["session_id"]


def _send(client: TestClient, sid: str, text: str = "I would scan the list once.") -> list[dict]:
    r = client.post(f"/sessions/{sid}/message", json={"text": text, "problem_id": "two-sum", "code": ""})
    assert r.status_code == 200
    events = []
    for chunk in r.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines() if ": " in line)
        events.append({"event": lines["event"], **json.loads(lines["data"])})
    return events


def test_both_interviewers_act_on_every_interview_turn(client: TestClient, model: PanelModel) -> None:
    sid = _new(client)
    events = _send(client, sid)
    assert events[-1]["event"] == "final" and events[-1]["reply"] == "What is the cost of that approach?"
    names = [e["name"] for e in events if e["event"] == "trace"]
    assert {"interviewer", "observer", "llm_observe", "panel_note_check"} <= set(names)
    assert sorted(model.calls) == ["guard", "lead", "observer"]

    view = client.get(f"/sessions/{sid}/panel").json()
    assert view["active"] is True
    assert view["notes"] == [{"dimension": "approach", "rating": 1, "note": "You restated the problem first."}]


def test_the_observer_does_not_sit_in_on_learn_mode(client: TestClient, model: PanelModel) -> None:
    sid = _new(client, mode="learn")
    _send(client, sid)
    assert "observer" not in model.calls
    assert client.get(f"/sessions/{sid}/panel").json() == {
        "active": False, "notes": [], "scores": {d: {"score": None, "signals": 0} for d in
                                                 ("communication", "approach", "correctness", "complexity")}}


def test_a_failing_observer_never_costs_the_candidate_their_reply(client: TestClient, model: PanelModel) -> None:
    model.signals = "broken"
    sid = _new(client)
    events = _send(client, sid)
    assert events[-1]["event"] == "final"
    observer = next(e for e in events if e["event"] == "trace" and e["name"] == "observer")
    assert observer["status"] == "error"
    assert client.get(f"/sessions/{sid}/panel").json()["notes"] == []


def test_a_note_containing_code_is_dropped_before_the_candidate_sees_it(client: TestClient, model: PanelModel) -> None:
    model.signals = [
        {"dimension": "correctness", "rating": -1, "note": "Use this:\n```python\nseen = {}\n```"},
        {"dimension": "communication", "rating": 1, "note": "You explained your plan clearly."},
    ]
    sid = _new(client)
    events = _send(client, sid)
    check = next(e for e in events if e["event"] == "trace" and e["name"] == "panel_note_check")
    assert check["decision"] == "blocked" and check["reason"].startswith("rule panel.code_in_note: dropped 1 of 2")
    assert [n["dimension"] for n in client.get(f"/sessions/{sid}/panel").json()["notes"]] == ["communication"]


def test_malformed_signals_are_ignored_not_guessed(client: TestClient, model: PanelModel) -> None:
    model.signals = [{"dimension": "vibes", "rating": 1, "note": "x"}, {"dimension": "approach", "rating": 5, "note": "x"},
                     {"dimension": "approach", "rating": 0, "note": ""}]
    sid = _new(client)
    _send(client, sid)
    assert client.get(f"/sessions/{sid}/panel").json()["notes"] == []


def test_scores_come_from_the_ratings_and_unobserved_dimensions_have_none() -> None:
    notes = [{"dimension": "approach", "rating": 1, "note": "a"}, {"dimension": "approach", "rating": 1, "note": "b"},
             {"dimension": "complexity", "rating": -1, "note": "c"}, {"dimension": "communication", "rating": 1, "note": "d"},
             {"dimension": "communication", "rating": -1, "note": "e"}]
    result = panel.scores(notes)
    assert result["approach"].score == 4.0 and result["approach"].signals == 2
    assert result["complexity"].score == 1.0
    assert result["communication"].score == 2.5
    assert result["correctness"].score is None and result["correctness"].signals == 0


def test_debrief_scores_the_interview_from_the_notes(client: TestClient, model: PanelModel) -> None:
    sid = _new(client)
    _send(client, sid)
    _send(client, sid)
    r = client.post(f"/sessions/{sid}/debrief")
    assert r.status_code == 200
    body = r.json()
    assert body["notes_used"] == 2 and body["summary"] == "A structured start."
    assert body["scores"]["approach"] == {"score": 4.0, "signals": 2}
    assert body["scores"]["complexity"] == {"score": None, "signals": 0}
    assert body["interviewers_look_for"] == ["A plan before code."]
    tree = client.get(f"/traces/{body['trace_id']}").json()
    assert tree["roots"][0]["event"]["name"] == "debrief"


def test_debrief_before_any_notes_is_refused_with_a_reason(client: TestClient) -> None:
    r = client.post(f"/sessions/{_new(client)}/debrief")
    assert r.status_code == 409 and "no notes yet" in r.json()["detail"]


def test_feedback_containing_code_is_withheld(client: TestClient, model: PanelModel) -> None:
    sid = _new(client)
    _send(client, sid)
    model.debrief = {**model.debrief, "work_on": ["Write this:\n```python\nreturn [i, j]\n```"]}
    r = client.post(f"/sessions/{sid}/debrief")
    assert r.status_code == 502 and "withheld" in r.json()["detail"]["message"]


def test_a_new_problem_starts_a_fresh_scorecard(client: TestClient) -> None:
    sid = _new(client)
    _send(client, sid)
    client.post(f"/sessions/{sid}/message", json={"text": "next one", "problem_id": "valid-parentheses", "code": ""})
    assert len(client.get(f"/sessions/{sid}/panel").json()["notes"]) == 1

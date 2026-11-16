"""Phase 1 contract tests: every endpoint returns the documented shape, and no
response ever contains a reference solution or hidden tests."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app

FORBIDDEN_KEYS = {"reference_solution", "hidden_tests"}


def _walk_keys(obj: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(k)
            keys |= _walk_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            keys |= _walk_keys(item)
    return keys


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def session_id(client: TestClient) -> str:
    r = client.post("/sessions")
    assert r.status_code == 201
    return r.json()["session_id"]


def test_create_session_returns_id(client: TestClient) -> None:
    r = client.post("/sessions")
    assert r.status_code == 201
    assert r.json()["session_id"].startswith("ses_")


def test_list_problems_shape(client: TestClient) -> None:
    r = client.get("/problems")
    assert r.status_code == 200
    problems = r.json()
    assert len(problems) >= 2
    for p in problems:
        assert set(p) == {"id", "title", "difficulty", "pattern"}


def test_problem_detail_has_no_solution_or_hidden_tests(client: TestClient) -> None:
    for pid in ["two-sum", "valid-parentheses"]:
        r = client.get(f"/problems/{pid}")
        assert r.status_code == 200
        body = r.json()
        assert {"statement", "starter_code", "visible_tests"} <= set(body)
        assert not (FORBIDDEN_KEYS & _walk_keys(body))


def test_unknown_problem_is_404(client: TestClient) -> None:
    assert client.get("/problems/nope").status_code == 404


def test_message_streams_trace_then_final(client: TestClient, session_id: str) -> None:
    body = {"text": "I'm stuck", "problem_id": "two-sum", "code": ""}
    with client.stream("POST", f"/sessions/{session_id}/message", json=body) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())

    events = _parse_sse(text)
    names = [name for name, _ in events]
    assert names.count("final") == 1
    at = names.index("final")
    assert at > 0 and set(names[:at]) == {"trace"}, "expected trace events before the final event"
    final = events[at][1]
    assert set(final) >= {"reply", "mode", "hint_level", "escalated", "trace_id"}
    assert final["mode"] in {"learn", "interview", "blitz"}
    assert not (FORBIDDEN_KEYS & _walk_keys(final))
    # Only the picture for the reply may follow it: the illustrator's steps, then one drawing.
    assert set(names[at + 1:]) <= {"trace", "drawing"} and names[-1] == "drawing"
    assert not (FORBIDDEN_KEYS & _walk_keys(events[-1][1]))


def test_message_unknown_session_is_404(client: TestClient) -> None:
    body = {"text": "hi", "problem_id": "two-sum", "code": ""}
    assert client.post("/sessions/ses_missing/message", json=body).status_code == 404


def test_message_rejects_empty_text(client: TestClient, session_id: str) -> None:
    body = {"text": "", "problem_id": "two-sum", "code": ""}
    assert client.post(f"/sessions/{session_id}/message", json=body).status_code == 422


def test_runs_returns_mode_hint_and_next_action(client: TestClient, session_id: str) -> None:
    body = {
        "problem_id": "two-sum",
        "code": "def two_sum(nums, target): ...",
        "passed": 1,
        "failed": 2,
        "total": 3,
        "failures": [{"name": "duplicates", "message": "expected [0, 1], got None"}],
        "runtime_ms": 12,
    }
    r = client.post(f"/sessions/{session_id}/runs", json=body)
    assert r.status_code == 200
    out = r.json()
    assert set(out) == {"mode", "hint_level_available", "next_action"}


def test_state_shape(client: TestClient, session_id: str) -> None:
    r = client.get(f"/sessions/{session_id}/state")
    assert r.status_code == 200
    assert set(r.json()) >= {
        "mode", "hint_level", "failed_runs", "hints_used",
        "time_on_problem", "mastery", "escalated",
    }


def test_session_events_stream(client: TestClient, session_id: str) -> None:
    with client.stream("GET", f"/sessions/{session_id}/events") as r:
        assert r.status_code == 200
        events = _parse_sse("".join(r.iter_text()))
    assert events[0][0] == "trace"
    assert events[-1][0] == "end"


def test_trace_tree(client: TestClient) -> None:
    r = client.get("/traces/trc_stub_0001")
    assert r.status_code == 200
    tree = r.json()
    assert tree["roots"], "expected at least one root span"
    assert tree["roots"][0]["event"]["type"] == "turn.start"
    assert client.get("/traces/unknown").status_code == 404


def test_mentor_ticket_flow(client: TestClient) -> None:
    tickets = client.get("/mentor/tickets").json()
    assert tickets
    tid = tickets[0]["id"]

    detail = client.get(f"/mentor/tickets/{tid}").json()
    assert {"transcript", "latest_code", "suggested_intervention", "stuck_reason"} <= set(detail)

    reply = client.post(f"/mentor/tickets/{tid}/reply", json={"text": "Look at the inner loop."})
    assert reply.status_code == 200
    assert reply.json()["actor"] == "mentor"

    resolved = client.post(f"/mentor/tickets/{tid}/resolve")
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    assert client.get("/mentor/tickets/missing").status_code == 404


def test_eval_results_shape(client: TestClient) -> None:
    r = client.get("/eval/results")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"stub", "ready"}
    assert {"held_out_problems", "examples"} <= set(body)


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for block in text.strip().split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if name is not None and data is not None:
            out.append((name, data))
    return out

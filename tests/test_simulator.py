"""The scripted student runs through the real API with a scripted model. The whole demo
scenario must behave: injections blocked, third one escalates, the mentor reply lands in
the chat, resolving clears the flag, and every step has a trace."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.demo.simulate import run
from app.main import app
from tests.fakes import FakeModel  # noqa: F401
from tests.fakes import fake_model  # noqa: F401


def test_scripted_student_completes_the_demo_scenario(fake_model: FakeModel, tmp_path) -> None:  # noqa: ANN001
    client = TestClient(app)
    record_path = tmp_path / "recording.json"
    recording = run(client, record_path=record_path, verbose=False)

    steps = recording["steps"]
    assert all(s["status"] == 200 for s in steps)

    message_steps = [s for s in steps if s["kind"] == "message"]
    # Injection steps are blocked and counted; the third escalates.
    injections = [s for s in message_steps if "ignore" in s["request"]]
    assert len(injections) == 3
    assert injections[-1]["escalated"] is True
    assert injections[0]["escalated"] is False

    # Every message step has a trace whose root is turn.end.
    for s in message_steps:
        assert s["trace_tree"], f"step {s['index']} has no trace"
        assert s["trace_tree"][0]["event"]["type"] == "turn.end"

    # The mentor step resolved the ticket and the flag cleared.
    mentor = next(s for s in steps if s["kind"] == "mentor")
    assert mentor["detail"]["status"] == "resolved"
    assert recording["final_state"]["escalated"] is False

    assert record_path.exists()


def test_recording_contains_the_transcript_lines(fake_model: FakeModel) -> None:  # noqa: ANN001
    client = TestClient(app)
    recording = run(client, verbose=False)
    joined = "\n".join(recording["transcript"])
    assert "student: I'm stuck on two sum" in joined
    assert "mentor reply:" in joined
    assert "recording written" not in joined

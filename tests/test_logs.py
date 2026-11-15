"""Activity log: every agent action across sessions, filterable, with a per-agent summary."""

from fastapi.testclient import TestClient

from app.api.logs import summarise
from app.main import app
from app.models import TraceEvent


def _ev(i: int, actor: str, type_: str, **kw) -> TraceEvent:
    return TraceEvent(event_id=f"evt_{i}", trace_id="trc_1", span_id=f"spn_{i}", parent_span_id=None, session_id="ses_1",
                      seq=i, ts="2026-11-15T12:00:00+00:00", actor=actor, type=type_, name=type_, status=kw.pop("status", "ok"),
                      latency_ms=None, model=None, tokens_in=kw.pop("tokens_in", None), tokens_out=None,
                      cost_usd=kw.pop("cost_usd", None), input=None, output=None, decision=None, reason=None)


def test_summary_counts_calls_tokens_and_cost_per_agent() -> None:
    events = [
        _ev(1, "hint_coach", "llm.call", tokens_in=100, cost_usd=0.01),
        _ev(2, "hint_coach", "llm.call", tokens_in=50, cost_usd=0.02),
        _ev(3, "guard", "guard.input", status="blocked"),
    ]
    by_actor = {s.actor: s for s in summarise(events)}
    assert by_actor["hint_coach"].model_calls == 2
    assert by_actor["hint_coach"].tokens_in == 150
    assert round(by_actor["hint_coach"].cost_usd, 2) == 0.03
    assert by_actor["guard"].blocked == 1


def test_logs_endpoint_filters_by_actor() -> None:
    client = TestClient(app)
    body = client.get("/logs").json()
    assert body["events"] and body["summary"]
    actor = body["events"][0]["actor"]
    filtered = client.get("/logs", params={"actor": actor}).json()["events"]
    assert filtered and all(e["actor"] == actor for e in filtered)

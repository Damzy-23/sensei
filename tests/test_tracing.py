"""Phase 2 tests: span structure, context propagation, validation, redaction, cost,
live subscription, the tool registry, and the run_tests client span."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import pkgutil

import pytest
from fastapi.testclient import TestClient

import app.tools as tools_pkg
from app.main import app
from app.tools import client as client_tools
from app.tools import escalation, guard, orchestrator
from app.tracing import prices, redact, store
from app.tracing.context import span, turn
from app.tracing.registry import REGISTRY, Registry, ToolSpec


def _trace(trace_id: str):
    return store.load_trace(trace_id)


# ---------- span structure ----------


def test_nested_spans_form_parent_child_tree() -> None:
    with turn("ses_t1") as tctx:
        with span("orchestrator", "agent.start", "route") as a:
            with span("hint_coach", "llm.call", "llm_hint") as b:
                b.model = "claude-haiku-5-5"
    events = {e.name: e for e in _trace(tctx.trace_id)}
    root = next(e for e in events.values() if e.type == "turn.end")
    assert events["route"].parent_span_id == root.span_id
    assert events["llm_hint"].parent_span_id == events["route"].span_id
    assert root.parent_span_id is None


def test_build_tree_nests_children_under_parent() -> None:
    with turn("ses_t2") as tctx:
        with span("orchestrator", "agent.start", "route"):
            with span("hint_coach", "llm.call", "llm_hint"):
                pass
    roots = store.build_tree(_trace(tctx.trace_id))
    assert len(roots) == 1
    assert roots[0].event.type == "turn.end"
    route = roots[0].children[0]
    assert route.event.name == "route"
    assert route.children[0].event.name == "llm_hint"


def test_context_does_not_leak_between_concurrent_tasks() -> None:
    async def branch(name: str) -> str:
        with span("orchestrator", "tool.call", name) as outer:
            await asyncio.sleep(0.01)
            with span("orchestrator", "tool.call", f"{name}-inner"):
                await asyncio.sleep(0.01)
        return outer.span_id

    async def main() -> tuple[str, str]:
        return await asyncio.gather(branch("a"), branch("b"))  # type: ignore[return-value]

    with turn("ses_t3") as tctx:
        a_id, b_id = asyncio.run(main())
    events = {e.name: e for e in _trace(tctx.trace_id)}
    root = next(e for e in events.values() if e.type == "turn.end")
    assert events["a"].parent_span_id == root.span_id
    assert events["b"].parent_span_id == root.span_id
    assert events["a-inner"].parent_span_id == a_id
    assert events["b-inner"].parent_span_id == b_id


def test_span_without_turn_goes_to_offline_trace() -> None:
    with span("orchestrator", "tool.call", "lonely"):
        pass
    events = store.load_session_events("offline")
    assert any(e.name == "lonely" for e in events)


# ---------- validation ----------


def test_guard_event_without_decision_is_rejected() -> None:
    with pytest.raises(store.TraceValidationError):
        with turn("ses_v1"):
            with span("guard", "guard.input", "classify_input"):
                pass


def test_guard_event_with_decision_and_reason_is_stored() -> None:
    with turn("ses_v2") as tctx:
        with span("guard", "guard.input", "classify_input") as st:
            st.decision = "ok"
            st.reason = "fast model: ok (0.94)"
    ev = next(e for e in _trace(tctx.trace_id) if e.name == "classify_input")
    assert ev.decision == "ok"
    assert ev.reason == "fast model: ok (0.94)"


def test_mode_event_requires_reason() -> None:
    with pytest.raises(store.TraceValidationError):
        with turn("ses_v3"):
            with span("orchestrator", "mode.decision", "select_mode") as st:
                st.decision = "learn"


def test_error_span_is_recorded_and_reraised() -> None:
    with pytest.raises(ValueError, match="boom"):
        with turn("ses_v4") as tctx:
            with span("guard", "guard.output", "leak_check"):
                raise ValueError("boom")
    ev = next(e for e in _trace(tctx.trace_id) if e.name == "leak_check")
    assert ev.status == "error"
    assert ev.decision == "error"
    assert "boom" in (ev.reason or "")


# ---------- redaction and truncation ----------


def test_input_is_truncated_to_500_chars() -> None:
    with turn("ses_r1") as tctx:
        with span("orchestrator", "tool.call", "big", input_text="x" * 2000):
            pass
    ev = next(e for e in _trace(tctx.trace_id) if e.name == "big")
    assert ev.input is not None and len(ev.input) == 500


def test_key_like_strings_are_redacted() -> None:
    secret = "sk-ant-api03-SECRETSECRETSECRET"
    with turn("ses_r2") as tctx:
        with span("orchestrator", "tool.call", "leaky", input_text=f"key={secret} token: abcdef123456"):
            pass
    ev = next(e for e in _trace(tctx.trace_id) if e.name == "leaky")
    assert "SECRETSECRET" not in (ev.input or "")
    assert "abcdef123456" not in (ev.input or "")
    assert "[REDACTED]" in (ev.input or "")


def test_configured_api_key_value_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "my-local-test-key-value")
    assert "my-local-test-key-value" not in redact.redact("header uses my-local-test-key-value here")


def test_clip_keeps_exact_limit() -> None:
    assert len(redact.clip("a" * 600)) == 500
    assert redact.clip("short") == "short"


# ---------- cost ----------


def test_cost_from_price_table() -> None:
    # claude-haiku-5-5 is $1.00 in / $5.00 out per 1M tokens: 1000 in + 1000 out = $0.006
    assert prices.cost_usd("claude-haiku-5-5", 1000, 1000) == pytest.approx(0.006)


def test_unknown_model_has_no_cost() -> None:
    assert prices.cost_usd("not-a-model", 10, 10) is None
    assert prices.cost_usd(None, 10, 10) is None


def test_llm_span_records_cost() -> None:
    with turn("ses_c1") as tctx:
        with span("hint_coach", "llm.call", "llm_hint") as st:
            st.model = "claude-haiku-5-5"
            st.tokens_in = 1000
            st.tokens_out = 1000
    ev = next(e for e in _trace(tctx.trace_id) if e.name == "llm_hint")
    assert ev.cost_usd == pytest.approx(0.006)


# ---------- live subscription ----------


def test_subscriber_receives_events_live() -> None:
    async def main() -> list[str]:
        queue = store.subscribe("ses_live")
        with turn("ses_live"):
            with span("orchestrator", "tool.call", "live-one"):
                pass
        names = []
        while not queue.empty():
            names.append((await queue.get()).name)
        store.unsubscribe("ses_live", queue)
        return names

    names = asyncio.run(main())
    assert "live-one" in names
    assert "turn" in names


# ---------- registry ----------


def test_every_public_tool_function_is_registered() -> None:
    missing: list[str] = []
    for info in pkgutil.iter_modules(tools_pkg.__path__):
        module = importlib.import_module(f"{tools_pkg.__name__}.{info.name}")
        for name, obj in vars(module).items():
            if name.startswith("_") or not inspect.isfunction(obj) and not inspect.iscoroutinefunction(obj):
                continue
            if getattr(obj, "__module__", None) != module.__name__:
                continue
            if not REGISTRY.has_function(module.__name__, obj.__qualname__):
                missing.append(f"{module.__name__}.{name}")
    assert missing == [], f"unregistered tool functions: {missing}"


def test_registered_tool_inventory_matches_spec() -> None:
    expected = {
        ("client", "run_tests"),
        ("guard", "classify_input"), ("guard", "regex_precheck"), ("guard", "leak_check"), ("guard", "policy_check"),
        ("orchestrator", "read_state"), ("orchestrator", "write_state"), ("orchestrator", "select_mode"),
        ("orchestrator", "route_agent"), ("orchestrator", "create_escalation"),
        ("interviewer", "get_problem"), ("interviewer", "llm_followup"), ("interviewer", "record_answer"),
        ("hint_coach", "get_hint_level"), ("hint_coach", "unlock_hint"), ("hint_coach", "llm_hint"),
        ("evaluator", "read_run_result"), ("evaluator", "analyze_complexity"), ("evaluator", "static_check"),
        ("planner", "get_mastery"), ("planner", "update_mastery"), ("planner", "query_problem_bank"),
        ("planner", "select_next_problem"),
        ("escalation", "create_ticket"), ("escalation", "notify_mentor"), ("escalation", "relay_mentor_message"),
    }
    actual = {(s.actor, s.name) for s in REGISTRY.all()}
    assert actual == expected


def test_duplicate_registration_is_rejected() -> None:
    reg = Registry()
    spec = ToolSpec(actor="guard", name="x", event_type="guard.input", module="m", qualname="f")
    reg.add(spec)
    with pytest.raises(ValueError):
        reg.add(spec)
    with pytest.raises(ValueError):
        reg.add(ToolSpec(actor="guard", name="y", event_type="guard.input", module="m", qualname="f"))


def test_tool_call_outside_implementation_is_traced_as_error() -> None:
    with turn("ses_reg") as tctx:
        with pytest.raises(KeyError):
            orchestrator.read_state("ses_missing")
    ev = next(e for e in _trace(tctx.trace_id) if e.name == "read_state")
    assert ev.actor == "orchestrator"
    assert ev.status == "error"


def test_sync_tool_wrapper_preserves_name_and_is_traced() -> None:
    assert orchestrator.route_agent.__name__ == "route_agent"
    with turn("ses_reg2") as tctx:
        assert orchestrator.route_agent("learn", "hint") == "hint_coach"
    assert any(e.name == "route_agent" and e.actor == "orchestrator" for e in _trace(tctx.trace_id))
    # A live sync tool is traced too, and its guard verdict carries decision and reason.
    with turn("ses_reg3") as tctx2:
        assert guard.regex_precheck("hello")["decision"] == "pass"
    ev = next(e for e in _trace(tctx2.trace_id) if e.name == "regex_precheck")
    assert ev.actor == "guard" and ev.decision == "pass" and ev.reason


def test_escalation_tools_are_registered_under_escalation_actor() -> None:
    assert REGISTRY.by_name("escalation", "create_ticket") is not None
    assert REGISTRY.by_name("escalation", "relay_mentor_message").event_type == "mentor.message"  # type: ignore[union-attr]
    assert escalation is not None


# ---------- run_tests on /runs ----------


def test_runs_endpoint_logs_client_span() -> None:
    client = TestClient(app)
    session_id = client.post("/sessions").json()["session_id"]
    body = {
        "problem_id": "two-sum",
        "code": "def two_sum(nums, target): ...",
        "passed": 1,
        "failed": 2,
        "total": 3,
        "failures": [{"name": "duplicates", "message": "expected [0, 1]"}],
        "runtime_ms": 12,
    }
    assert client.post(f"/sessions/{session_id}/runs", json=body).status_code == 200
    events = store.load_session_events(session_id)
    run_event = next(e for e in events if e.name == "run_tests")
    assert run_event.actor == "client"
    assert "source=client" in (run_event.output or "")
    assert client_tools.run_tests is not None

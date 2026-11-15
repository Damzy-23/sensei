"""Mode switching rules, escalation triggers, routing, and the mentor ticket tools."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest

from app import state
from app.llm import client
from app.models import RunIn
from app.llm.client import ProviderReply
from app.orchestrator.escalation import EscalationInputs, escalation_for_session, escalation_reason
from app.orchestrator.modes import ModeSignals, select_mode
from app.orchestrator.routing import classify_intent, route
from app.policy import load_policy
from app.tools import escalation as escalation_tools
from app.tools import orchestrator as orch
from app.tracing import store
from app.tracing.context import turn


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(client, "BACKOFF_BASE_SECONDS", 0.0)
    yield


MODES = load_policy().modes
ESC = load_policy().escalation
GUARD = load_policy().guard


def _sig(**overrides) -> ModeSignals:
    base = dict(
        current_mode="learn", consecutive_failed_runs=0, hint_level=0, last_solved=False,
        hints_on_solve=0, pattern_mastery=0.0, solved_streak_under_target=0,
    )
    base.update(overrides)
    return ModeSignals(**base)


# ---------- mode rules ----------


def test_three_failed_runs_force_learn_from_any_mode() -> None:
    choice = select_mode(_sig(current_mode="blitz", consecutive_failed_runs=3), MODES)
    assert choice.mode == "learn"
    assert choice.rule == "learn.failed_runs"
    assert "3 consecutive" in choice.reason


def test_hint_level_three_forces_learn_from_interview() -> None:
    choice = select_mode(_sig(current_mode="interview", hint_level=3), MODES)
    assert choice.mode == "learn" and choice.rule == "learn.hint_level"


def test_learn_to_interview_after_quick_solve_with_mastery() -> None:
    choice = select_mode(_sig(last_solved=True, hints_on_solve=1, pattern_mastery=0.6), MODES)
    assert choice.mode == "interview"
    assert choice.rule == "interview.solved_fast"


def test_learn_stays_when_solve_needed_too_many_hints() -> None:
    choice = select_mode(_sig(last_solved=True, hints_on_solve=2, pattern_mastery=0.9), MODES)
    assert choice.mode == "learn"


def test_learn_stays_when_mastery_is_low() -> None:
    choice = select_mode(_sig(last_solved=True, hints_on_solve=0, pattern_mastery=0.59), MODES)
    assert choice.mode == "learn"


def test_interview_to_blitz_after_three_fast_solves() -> None:
    choice = select_mode(_sig(current_mode="interview", solved_streak_under_target=3), MODES)
    assert choice.mode == "blitz"
    assert choice.rule == "blitz.streak"


def test_interview_stays_with_two_fast_solves() -> None:
    choice = select_mode(_sig(current_mode="interview", solved_streak_under_target=2), MODES)
    assert choice.mode == "interview"
    assert choice.rule == "stay.interview"


def test_every_choice_reports_the_signals_it_read() -> None:
    choice = select_mode(_sig(consecutive_failed_runs=1), MODES)
    assert set(choice.signals) == {
        "current_mode", "consecutive_failed_runs", "hint_level", "last_solved",
        "hints_on_solve", "pattern_mastery", "solved_streak_under_target",
    }


def test_select_mode_tool_logs_decision_and_reason() -> None:
    with turn("ses_m1") as tctx:
        out = orch.select_mode({
            "current_mode": "learn", "consecutive_failed_runs": 3, "hint_level": 0, "last_solved": False,
            "hints_on_solve": 0, "pattern_mastery": 0.0, "solved_streak_under_target": 0,
        })
    assert out["mode"] == "learn"
    ev = next(e for e in store.load_trace(tctx.trace_id) if e.name == "select_mode")
    assert ev.type == "mode.decision"
    assert ev.decision == "learn"
    assert ev.reason and "learn.failed_runs" in ev.reason


# ---------- escalation triggers ----------


def test_stuck_at_level_five_escalates() -> None:
    reason = escalation_reason(EscalationInputs(5, 1, 0, 0), ESC, GUARD)
    assert reason is not None and "stuck" in reason


def test_level_five_with_no_failed_run_does_not_escalate() -> None:
    assert escalation_reason(EscalationInputs(5, 0, 0, 0), ESC, GUARD) is None


def test_three_guard_violations_escalate() -> None:
    assert escalation_reason(EscalationInputs(1, 0, 2, 0), ESC, GUARD) is None
    reason = escalation_reason(EscalationInputs(1, 0, 3, 0), ESC, GUARD)
    assert reason is not None and "guard violations" in reason


def test_frustration_twice_escalates() -> None:
    assert escalation_reason(EscalationInputs(1, 0, 0, 1), ESC, GUARD) is None
    reason = escalation_reason(EscalationInputs(1, 0, 0, 2), ESC, GUARD)
    assert reason is not None and "frustration" in reason


def test_no_trigger_means_no_escalation() -> None:
    assert escalation_reason(EscalationInputs(2, 2, 1, 1), ESC, GUARD) is None


def test_escalation_for_session_reads_stored_counts() -> None:
    sid = state.create_session()
    assert escalation_for_session(sid) is None
    state.update_session(sid, frustration_flags=2)
    assert escalation_for_session(sid) is not None


# ---------- routing ----------


def test_hint_words_route_to_hint_coach() -> None:
    intent = classify_intent("I'm stuck, any hint?", mode="learn", last_solved=False,
                             awaiting_answer=False, last_run_failed=True)
    assert intent == "hint"
    assert route(intent) == "hint_coach"


def test_answer_to_follow_up_routes_to_interviewer() -> None:
    intent = classify_intent("O(n) time", mode="interview", last_solved=True,
                             awaiting_answer=True, last_run_failed=False)
    assert route(intent) == "interviewer"


def test_solved_problem_in_interview_routes_to_evaluator() -> None:
    intent = classify_intent("done", mode="interview", last_solved=True,
                             awaiting_answer=False, last_run_failed=False)
    assert route(intent) == "evaluator"


def test_route_agent_tool_matches_routing_table() -> None:
    assert orch.route_agent("learn", "debug") == "hint_coach"
    assert orch.route_agent("interview", "review") == "evaluator"


# ---------- tickets ----------


def test_create_escalation_opens_ticket_and_marks_session(monkeypatch: pytest.MonkeyPatch) -> None:
    async def provider(target, system, messages, max_tokens):  # noqa: ANN001
        return ProviderReply('{"intervention": "Ask what the inner loop costs."}', 5, 5)

    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    sid = state.create_session()
    state.update_session(sid, problem_id="two-sum")
    state.add_message(sid, "student", "my code times out")
    state.add_run(sid, "two-sum", RunIn(
        problem_id="two-sum", code="def two_sum(n,t): ...", passed=1, failed=2, total=3, runtime_ms=9000))

    ticket_id = asyncio.run(orch.create_escalation(sid, "stuck: hint level 5"))
    row = state.get_ticket_row(ticket_id)
    assert row is not None
    assert row["status"] == "open"
    assert row["suggested_intervention"] == "Ask what the inner loop costs."
    assert "def two_sum" in row["latest_code"]
    assert state.get_session(sid).escalated is True


def test_ticket_survives_model_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def provider(target, system, messages, max_tokens):  # noqa: ANN001
        raise RuntimeError("model down")

    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    sid = state.create_session()
    state.update_session(sid, problem_id="two-sum")
    ticket = asyncio.run(escalation_tools.create_ticket(sid, "3 guard violations"))
    row = state.get_ticket_row(ticket["id"])
    assert row is not None and row["suggested_intervention"]


def test_mentor_reply_lands_in_student_chat_and_resolve_clears_flag() -> None:
    sid = state.create_session()
    state.update_session(sid, problem_id="two-sum", escalated=True)
    ticket_id = state.create_ticket(sid, "two-sum", "stuck", "code", "intervene")
    msg_id = escalation_tools.relay_mentor_message(ticket_id, "Look at the inner loop.")
    mentor_msgs = [m for m in state.list_messages(sid) if m.actor == "mentor"]
    assert [m.id for m in mentor_msgs] == [msg_id]
    state.resolve_ticket_row(ticket_id)
    assert state.get_session(sid).escalated is False


def test_flag_stays_set_while_another_ticket_is_open() -> None:
    sid = state.create_session()
    state.update_session(sid, escalated=True)
    first = state.create_ticket(sid, "two-sum", "a", "", "x")
    state.create_ticket(sid, "two-sum", "b", "", "y")
    state.resolve_ticket_row(first)
    assert state.get_session(sid).escalated is True

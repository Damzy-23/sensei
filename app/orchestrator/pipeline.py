"""The orchestrator. One function per student message, one per test run.

handle_message, per message:
  input guard (regex_precheck -> classify_input) -> read_state -> select_mode -> route_agent
  -> agent -> output guard -> escalation check -> write_state -> coach message

handle_run, per /runs request:
  run_tests (client span) -> record run -> update streak, mastery, mode -> escalation check

Every model call and guard check is a tool, so each one lands in the trace. Plain repository
reads and writes use app.state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app import bank, state
from app.guards.reply import guard_reply
from app.llm.client import LLMError
from app.models import RunIn
from app.orchestrator.escalation import escalation_for_session
from app.orchestrator.routing import classify_intent
from app.policy import load_policy
from app.tools import client as client_tools
from app.tools import evaluator as evaluator_tools
from app.tools import guard as guard_tools
from app.tools import hint_coach as hint_tools
from app.tools import interviewer as interviewer_tools
from app.tools import orchestrator as orch_tools
from app.tools import planner as planner_tools
from app.tracing.context import turn

_FALLBACK_QUESTION = "What would you change about your approach if the input were much larger?"


@dataclass(frozen=True)
class TurnResult:
    reply: str
    mode: str
    hint_level: int
    escalated: bool
    trace_id: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _elapsed(start_iso: str | None) -> float:
    if start_iso is None:
        return 0.0
    return (datetime.now(timezone.utc) - datetime.fromisoformat(start_iso)).total_seconds()


def _hints_for(session_id: str, problem_id: str) -> int:
    return sum(1 for h in state.list_hints(session_id) if h["problem_id"] == problem_id)


def _new_problem_if_changed(session_id: str, problem_id: str) -> None:
    record = state.get_session(session_id)
    assert record is not None
    if record.problem_id != problem_id:
        orch_tools.write_state(session_id, {
            "problem_id": problem_id,
            "problem_started_at": _now_iso(),
            "hint_level": 0,
            "failed_runs": 0,
        })
    elif record.problem_started_at is None:
        orch_tools.write_state(session_id, {"problem_started_at": _now_iso()})


def _signals(session_id: str, problem_id: str, last_solved: bool) -> dict[str, Any]:
    record = state.get_session(session_id)
    assert record is not None
    problem = bank.get_public(problem_id)
    pattern = problem.pattern if problem else ""
    return {
        "current_mode": record.mode,
        "consecutive_failed_runs": record.failed_runs,
        "hint_level": record.hint_level,
        "last_solved": last_solved,
        "hints_on_solve": _hints_for(session_id, problem_id),
        "pattern_mastery": planner_tools.get_mastery(session_id).get(pattern, 0.0),
        "solved_streak_under_target": record.solved_streak,
    }


def _apply_mode(session_id: str, problem_id: str, last_solved: bool) -> dict[str, Any]:
    choice = orch_tools.select_mode(_signals(session_id, problem_id, last_solved))
    orch_tools.write_state(session_id, {"mode": choice["mode"]})
    return choice


def _last_failure(session_id: str) -> str:
    run = evaluator_tools.read_run_result(session_id)
    if not run.get("found") or not run.get("failures"):
        return "none yet"
    first = run["failures"][0]
    return f"{first.get('name', 'test')}: {first.get('message', '')}"


async def _coach_hint(session_id: str, problem_id: str, level: int, code: str) -> str:
    reference = bank.get_reference(problem_id)
    last_failure = _last_failure(session_id)

    async def draft(stricter: bool) -> dict[str, Any]:
        try:
            return await hint_tools.llm_hint(session_id, problem_id, level, code, last_failure, stricter)
        except LLMError:
            return {"level": -1, "hint": ""}  # fails policy_check, so the guard falls back to the canned hint

    guarded = await guard_reply(draft, level=level, reference=reference)
    return guarded.text


async def _interview_question(session_id: str, problem_id: str, answer: str) -> str:
    interviewer_tools.record_answer(session_id, "", answer)
    try:
        question = await interviewer_tools.llm_followup(session_id, problem_id, state.get_session(session_id).mode)  # type: ignore[union-attr]
    except LLMError:
        return _FALLBACK_QUESTION
    check = await guard_tools.leak_check(question, 5, bank.get_reference(problem_id))
    return question if check["decision"] == "pass" else _FALLBACK_QUESTION


async def _review(session_id: str, problem_id: str) -> str:
    run = evaluator_tools.read_run_result(session_id)
    if not run.get("found"):
        return "Run your tests first, then I can review the complexity with you."
    try:
        analysis = await evaluator_tools.analyze_complexity(run["code"], bank.get_expected_complexity(problem_id))
    except LLMError:
        return "Nice work. Can you say the time and space cost of your solution?"
    text = f"Time {analysis['time']}, space {analysis['space']}. {analysis['feedback']}".strip()
    check = await guard_tools.leak_check(text, 5, bank.get_reference(problem_id))
    return text if check["decision"] == "pass" else "Nice work. Say the time and space cost of your solution."


async def handle_message(session_id: str, text: str, problem_id: str, code: str) -> TurnResult:
    policy = load_policy()
    with turn(session_id, name="message") as tctx:
        _new_problem_if_changed(session_id, problem_id)
        record = state.get_session(session_id)
        assert record is not None

        # 1. input guard
        regex = guard_tools.regex_precheck(text)
        verdict = await guard_tools.classify_input(session_id, text, regex["category"])

        if verdict["decision"] == "block":
            state.add_message(session_id, "student", text, trace_id=tctx.trace_id)
            orch_tools.write_state(session_id, {"guard_violations": record.guard_violations + 1})
            reply = policy.redirects["injection"]
        elif verdict["decision"] == "redirect":
            state.add_message(session_id, "student", text, trace_id=tctx.trace_id)
            reply = policy.redirects.get(verdict["category"], policy.redirects["off_topic"])
        elif verdict["decision"] == "flag":
            state.add_message(session_id, "student", text, trace_id=tctx.trace_id)
            orch_tools.write_state(session_id, {"frustration_flags": record.frustration_flags + 1})
            reply = policy.redirects["frustration"]
        else:
            # 2. state, mode, routing
            run = evaluator_tools.read_run_result(session_id)
            last_solved = bool(run.get("solved", False))
            mode_choice = _apply_mode(session_id, problem_id, last_solved)
            history = state.list_messages(session_id)
            awaiting = bool(history) and history[-1].actor == "coach" and history[-1].text.rstrip().endswith("?")
            intent = classify_intent(
                text,
                mode=mode_choice["mode"],
                last_solved=last_solved,
                awaiting_answer=awaiting,
                last_run_failed=bool(run.get("found")) and not last_solved,
            )
            agent = orch_tools.route_agent(mode_choice["mode"], intent)

            # 3. agent. An interview answer is stored by record_answer; everything else here.
            if agent == "interviewer":
                reply = await _interview_question(session_id, problem_id, text)
            else:
                state.add_message(session_id, "student", text, trace_id=tctx.trace_id)
                if agent == "hint_coach" and intent == "hint":
                    unlock = hint_tools.unlock_hint(session_id, True)
                    if unlock["granted"]:
                        reply = await _coach_hint(session_id, problem_id, unlock["level"], code)
                    else:
                        reply = "Not yet. Run your tests again, or give it a little more time before the next hint."
                elif agent == "hint_coach":
                    reply = "Tell me what you have tried so far, or ask for a hint when you are stuck."
                else:  # evaluator
                    reply = await _review(session_id, problem_id)

        # 4. escalation check on stored counts
        current = state.get_session(session_id)
        assert current is not None
        if not current.escalated:
            reason = escalation_for_session(session_id)
            if reason:
                await orch_tools.create_escalation(session_id, reason)

        state.add_message(session_id, "coach", reply, trace_id=tctx.trace_id)
        final = state.get_session(session_id)
        assert final is not None
    return TurnResult(
        reply=reply,
        mode=final.mode,
        hint_level=final.hint_level,
        escalated=final.escalated,
        trace_id=tctx.trace_id,
    )


async def handle_run(session_id: str, body: RunIn) -> dict[str, Any]:
    """Record a browser test run and update streak, mastery, mode and escalation.

    Returns the RunOut fields.
    """
    policy = load_policy()
    with turn(session_id, name="runs"):
        await client_tools.run_tests(session_id, body)
        problem = bank.get_public(body.problem_id)
        if problem is None:
            raise KeyError(f"unknown problem: {body.problem_id}")
        _new_problem_if_changed(session_id, body.problem_id)  # before reading, so counts are current
        state.add_run(session_id, body.problem_id, body)
        record = state.get_session(session_id)
        assert record is not None

        solved = body.failed == 0 and body.total > 0
        if solved:
            under_target = _elapsed(record.problem_started_at) <= policy.modes.blitz_time_target_seconds
            streak = record.solved_streak + 1 if under_target else 0
            planner_tools.update_mastery(session_id, problem.pattern, 1.0, problem.difficulty)
            orch_tools.write_state(session_id, {"failed_runs": 0, "solved_streak": streak})
        else:
            orch_tools.write_state(session_id, {"failed_runs": record.failed_runs + 1})

        choice = _apply_mode(session_id, body.problem_id, solved)
        latest = state.get_session(session_id)
        assert latest is not None
        if not latest.escalated:
            reason = escalation_for_session(session_id)
            if reason:
                await orch_tools.create_escalation(session_id, reason)
                latest = state.get_session(session_id)
                assert latest is not None

        if solved:
            next_action = "review_complexity"
        elif latest.escalated:
            next_action = "escalate"
        elif latest.hint_level < policy.hint_ladder.max_level:
            next_action = "ask_for_hint"
        else:
            next_action = "keep_coding"
        available = 0 if solved else min(policy.hint_ladder.max_level, latest.hint_level + 1)
        return {"mode": choice["mode"], "hint_level_available": available, "next_action": next_action}

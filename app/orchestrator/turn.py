"""The turn loop. One student message in, one reply out, every step traced.

input guard -> agent selection -> hint ladder -> one specialist -> output guard
(with one rewrite) -> escalation check. See docs/ARCHITECTURE.md.

After a hint coach reply has gone out, `illustrate` adds one picture for the glass:
illustrator -> drawing guard, recorded in the same trace.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app import catalog
from app.agents import caller, hint_coach, illustrator, interviewer, observer
from app.agents.context import AgentContext
from app.guards import drawing as drawing_guard
from app.guards import input as input_guard
from app.guards import leak, policy
from app.llm.gateway import LLMError
from app.memory import repository as memory
from app.models import Drawing, FinalEvent, MessageIn, RunIn, RunOut, SessionState
from app.orchestrator import rules
from app.tools.escalation import escalate_to_mentor
from app.tools.mastery import update_mastery
from app.tracing.context import TraceCtx, follow_up, span, turn

AGENTS = {"hint_coach": hint_coach.respond, "interviewer": interviewer.respond, "caller": caller.respond}
HISTORY_TURNS = 8
PANEL_AGENTS = frozenset({"interviewer", "caller"})  # modes where the observer sits in


class TurnError(RuntimeError):
    """A turn failed. Carries the trace id so the client can show what happened."""

    def __init__(self, message: str, trace_id: str) -> None:
        super().__init__(message)
        self.trace_id = trace_id


@dataclass(frozen=True)
class Sketch:
    """A picture still to be drawn for a reply: what the coach was given, what it said in words, and the turn's trace."""

    ctx: AgentContext
    reply: str  # without any line of code: see leak.prose_only
    trace: TraceCtx


@dataclass(frozen=True)
class TurnResult:
    final: FinalEvent
    sketch: Sketch | None = None  # set only when the hint coach's own words went out: see run_turn


def countdown(session: memory.Session) -> int | None:
    if session.mode != "blitz":
        return None
    return max(0, memory.BLITZ_SECONDS - session.time_on_problem())


def state(session: memory.Session) -> SessionState:
    return SessionState(
        session_id=session.session_id, problem_id=session.problem_id, mode=session.mode,
        hint_level=session.hint_level, failed_runs=session.failed_runs, hints_used=session.hints_used,
        time_on_problem=session.time_on_problem(), mastery=session.mastery, escalated=session.escalated,
        countdown_seconds=countdown(session),
    )


def _record(decision: rules.Decision, name: str, event_type: str = "mode.decision") -> None:
    with span("orchestrator", event_type, name) as st:  # type: ignore[arg-type]
        st.decision, st.reason, st.output = decision.value, decision.reason, decision.value


async def _draft_reply(agent: str, ctx: AgentContext, allowed_code_lines: int = 0) -> str:
    """Run the specialist, then the output guard. A blocked draft gets one rewrite."""
    reply = await AGENTS[agent](ctx)
    for _ in range(policy.MAX_LEAK_RETRIES):
        verdict = leak.check(reply, allowed_code_lines)
        if not verdict.leaked:
            return reply
        ctx = AgentContext(**{**ctx.__dict__, "rewrite_note": verdict.reason})
        reply = await AGENTS[agent](ctx)
    return policy.LEAK_FALLBACK_REPLY if leak.check(reply, allowed_code_lines).leaked else reply


async def _observe(ctx: AgentContext) -> list[dict]:
    """The observer's notes for this exchange. Its failure never costs the candidate their reply:
    the error is on the trace, and the turn carries on with no notes."""
    try:
        return await observer.observe(ctx)
    except LLMError:
        return []


async def illustrate(sketch: Sketch) -> Drawing | None:
    """One picture for the reply that has just gone out, or None.

    Never raises. The student already has their answer, so a slow, failed or blocked drawing
    costs them nothing: it is on the trace, and they get no picture.
    """
    with follow_up(sketch.trace):
        try:
            raw = await illustrator.draw(sketch.ctx, sketch.reply)
            return None if raw is None else drawing_guard.check(raw, sketch.ctx.hint_level, sketch.ctx.pattern)
        except Exception:  # noqa: BLE001 - the failing span has already recorded the error
            return None


async def run_turn(session_id: str, body: MessageIn) -> TurnResult:
    session = memory.get_session(session_id)
    problem = catalog.find_problem(body.problem_id)
    if session is None or problem is None:
        raise LookupError("session or problem not found")

    with turn(session_id) as trace:
        try:
            sketch: Sketch | None = None
            session.start_problem(problem.id)
            session.latest_code = body.code
            session.student_turns += 1
            memory.add_message(session_id, "student", body.text, trace.trace_id)

            verdict = await input_guard.classify(body.text)
            if verdict.category == "frustrated":
                session.frustration_flags += 1

            if verdict.blocked:
                session.guard_violations += 1
                reply = policy.BLOCKED_REPLY
            else:
                agent = rules.select_agent(session)
                _record(agent, "select_agent")
                if agent.value == "hint_coach":
                    level = rules.next_hint_level(session, verdict.category)
                    _record(level, "select_hint_level")
                    if int(level.value) > session.hint_level or level.rule == "hint.max":
                        session.hints_used += 1
                    session.hint_level = int(level.value)
                # A line of code is earned by trying; decided by rule, in learn mode only.
                code = rules.code_help(session, verdict.category)
                if agent.value == "hint_coach":
                    _record(code, "select_code_help")
                code_lines = 1 if code.value == "one_line" else 0
                # The transcript stores every agent reply as "coach"; in an interview that speaker is the interviewer.
                speaker = "interviewer" if agent.value in PANEL_AGENTS else "coach"
                history = [
                    (speaker if m.actor == "coach" else m.actor, m.text)
                    for m in memory.transcript(session_id, HISTORY_TURNS)
                ][:-1]
                ctx = AgentContext(
                    problem_title=problem.title, pattern=problem.pattern, difficulty=problem.difficulty,
                    statement=catalog.statement(problem.id), student_message=body.text, student_code=body.code,
                    history=history, hint_level=session.hint_level, failed_runs=session.failed_runs,
                    countdown_seconds=countdown(session), reexplain=verdict.category == "confused",
                    code_help=code.value,
                )
                if agent.value in PANEL_AGENTS:
                    # The lead answers while the observer takes notes: side by side, so the panel adds no wait.
                    reply, signals = await asyncio.gather(_draft_reply(agent.value, ctx), _observe(ctx))
                    if signals:
                        session.panel_notes.extend(leak.keep_safe_notes(signals))
                else:
                    reply = await _draft_reply(agent.value, ctx, code_lines)
                    if leak.decide(reply, code_lines).code_lines:
                        session.code_lines_given += 1
                # Only the hint coach's own words get a picture: not an interview, and not the fixed
                # reply that stands in when its drafts kept leaking. A line of code the coach was
                # allowed to give stays in the reply; the illustrator is handed the words around it.
                if agent.value == "hint_coach" and reply != policy.LEAK_FALLBACK_REPLY:
                    words = leak.prose_only(reply)
                    if words:
                        sketch = Sketch(ctx, words, trace)

            escalation = rules.should_escalate(session, verdict.category)
            if escalation is not None:
                escalate_to_mentor(session, escalation.rule, escalation.detail)
                reply += policy.ESCALATED_NOTE
                sketch = None  # a person is taking over: the note is not something to draw

            memory.add_message(session_id, "coach", reply, trace.trace_id)
            final = FinalEvent(
                reply=reply, mode=session.mode, hint_level=session.hint_level,
                escalated=session.escalated, trace_id=trace.trace_id,
            )
            return TurnResult(final, sketch)
        except LLMError as exc:
            raise TurnError(str(exc), trace.trace_id) from exc
        except Exception as exc:  # noqa: BLE001 - turn boundary: every failure reaches the client as a named error
            raise TurnError(f"{type(exc).__name__}: {exc}", trace.trace_id) from exc
        finally:
            memory.save_session(session)


def run_report(session_id: str, body: RunIn) -> RunOut:
    """A test run reported by the browser runner: update counters, mastery and the next action."""
    session = memory.get_session(session_id)
    problem = catalog.find_problem(body.problem_id)
    if session is None or problem is None:
        raise LookupError("session or problem not found")

    with turn(session_id, name="run"):
        session.start_problem(problem.id)
        session.latest_code = body.code
        solved = body.total > 0 and body.failed == 0 and body.passed == body.total
        session.failed_runs = 0 if solved else session.failed_runs + 1
        update_mastery(session, problem.pattern, solved)
        action, decision = rules.next_action(session, solved)
        _record(decision, "select_next_action")
        memory.save_session(session)
        return RunOut(mode=session.mode, hint_level_available=rules.hint_level_available(session), next_action=action)

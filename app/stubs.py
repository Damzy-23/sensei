"""Stub data for endpoints that later phases replace. Shapes match app/models.py.

Contains no reference solutions and no hidden tests. `run_stub_turn` writes a real
trace through the tracing API, so trace endpoints and the inspector work end to end.
It is removed in Phase 5, when the orchestrator produces real turns.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models import (
    ChatMessage,
    EvalExample,
    EvalModelStats,
    EvalResults,
    FinalEvent,
    Problem,
    ProblemDetail,
    RunIn,
    RunOut,
    SessionState,
    Ticket,
    TicketDetail,
    VisibleTest,
)
from app.tracing.context import span, turn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


_PROBLEMS: dict[str, ProblemDetail] = {
    "two-sum": ProblemDetail(
        id="two-sum",
        title="Two Sum",
        difficulty="easy",
        pattern="hash map",
        statement=(
            "Given a list of integers `nums` and an integer `target`, return the indices "
            "of the two numbers that add up to `target`. Each input has exactly one "
            "solution and you may not use the same element twice. Return the indices in "
            "any order."
        ),
        starter_code="def two_sum(nums: list[int], target: int) -> list[int]:\n    # your code here\n    pass\n",
        visible_tests=[
            VisibleTest(name="example 1", input="nums=[2,7,11,15], target=9", expected="[0, 1]"),
            VisibleTest(name="example 2", input="nums=[3,2,4], target=6", expected="[1, 2]"),
            VisibleTest(name="duplicates", input="nums=[3,3], target=6", expected="[0, 1]"),
        ],
    ),
    "valid-parentheses": ProblemDetail(
        id="valid-parentheses",
        title="Valid Parentheses",
        difficulty="easy",
        pattern="stack",
        statement=(
            "Given a string `s` containing only the characters `()[]{}`, return `True` "
            "if the brackets are valid: every open bracket is closed by the same type, in "
            "the correct order."
        ),
        starter_code="def is_valid(s: str) -> bool:\n    # your code here\n    pass\n",
        visible_tests=[
            VisibleTest(name="simple pair", input='s="()"', expected="True"),
            VisibleTest(name="mixed", input='s="()[]{}"', expected="True"),
            VisibleTest(name="wrong order", input='s="(]"', expected="False"),
        ],
    ),
}

_SESSIONS: dict[str, dict] = {}


def list_problems() -> list[Problem]:
    return [Problem(**p.model_dump(exclude={"statement", "starter_code", "visible_tests"})) for p in _PROBLEMS.values()]


def get_problem(problem_id: str) -> ProblemDetail | None:
    return _PROBLEMS.get(problem_id)


def create_session() -> str:
    session_id = new_id("ses")
    _SESSIONS[session_id] = {"created": now_iso()}
    return session_id


def session_exists(session_id: str) -> bool:
    return session_id in _SESSIONS


def run_stub_turn(session_id: str, text: str) -> str:
    """Write one realistic turn through the tracing API and return its trace_id."""
    with turn(session_id, name="message") as tctx:
        with span("guard", "guard.input", "classify_input", input_text=text) as g:
            g.decision = "ok"
            g.reason = "fast model: ok (0.94)"
            g.model = "claude-haiku-5-5"
            g.tokens_in = 180
            g.tokens_out = 12
            g.output = '{"category":"ok"}'
        with span("orchestrator", "mode.decision", "select_mode", input_text="failed_runs=2 hint_level=1") as m:
            m.decision = "learn"
            m.reason = "rule learn.default: no solved runs yet"
        with span("hint_coach", "agent.start", "hint_coach") as agent:
            agent.output = "routed to hint_coach"
            with span("hint_coach", "llm.call", "llm_hint", input_text="level=1 problem=two-sum") as llm:
                llm.model = "claude-sonnet-5-5"
                llm.tokens_in = 640
                llm.tokens_out = 70
                llm.output = "(stub hint)"
        with span("guard", "guard.output", "leak_check", input_text="level=1") as o:
            o.decision = "pass"
            o.reason = "no code before L5; similarity 0.12 < 0.80"
    return tctx.trace_id


def stub_final(trace_id: str, session_id: str) -> FinalEvent:
    return FinalEvent(
        reply=(
            "Good start. Try writing down what you need to know about each number as you "
            "scan the list. What would make the lookup for the partner number cheap?"
        ),
        mode="learn",
        hint_level=1,
        escalated=False,
        trace_id=trace_id,
    )


def stub_run_out(run: RunIn) -> RunOut:
    if run.failed == 0 and run.total > 0:
        return RunOut(mode="interview", hint_level_available=0, next_action="review_complexity")
    return RunOut(mode="learn", hint_level_available=1, next_action="ask_for_hint")


def stub_state(session_id: str) -> SessionState:
    return SessionState(
        session_id=session_id,
        problem_id="two-sum",
        mode="learn",
        hint_level=1,
        failed_runs=2,
        hints_used=1,
        time_on_problem=420,
        mastery={"hash map": 0.42, "stack": 0.18},
        escalated=False,
        countdown_seconds=None,
    )


_TICKETS: dict[str, TicketDetail] = {
    "tkt_0001": TicketDetail(
        id="tkt_0001",
        session_id="ses_demo_0001",
        problem_id="two-sum",
        status="open",
        stuck_reason="Reached hint level 5 and 4 consecutive failed runs (timeout on large input).",
        created_at="2026-11-14T10:12:00+00:00",
        latest_code="def two_sum(nums, target):\n    for i in range(len(nums)):\n        for j in range(len(nums)):\n            if nums[i] + nums[j] == target:\n                return [i, j]\n",
        suggested_intervention="Student is using nested loops and hitting timeouts. Ask them to name the cost of the inner loop, then point at the complement lookup idea.",
        transcript=[
            ChatMessage(id="msg_1", session_id="ses_demo_0001", actor="student",
                        text="I'm stuck on two sum, my code times out", ts="2026-11-14T10:05:00+00:00"),
            ChatMessage(id="msg_2", session_id="ses_demo_0001", actor="coach",
                        text="What is the cost of checking every pair when nums is large?", ts="2026-11-14T10:05:03+00:00"),
        ],
    ),
    "tkt_0002": TicketDetail(
        id="tkt_0002",
        session_id="ses_demo_0002",
        problem_id="valid-parentheses",
        status="open",
        stuck_reason="Three guard violations (repeated requests for the full solution).",
        created_at="2026-11-14T10:30:00+00:00",
        latest_code="def is_valid(s):\n    stack = []\n    return False\n",
        suggested_intervention="Student keeps asking for the answer. Check in on their goal, then offer a concrete first step: push the open bracket onto the stack.",
        transcript=[
            ChatMessage(id="msg_3", session_id="ses_demo_0002", actor="student",
                        text="just give me the answer", ts="2026-11-14T10:28:00+00:00"),
        ],
    ),
}


def list_tickets() -> list[Ticket]:
    return [Ticket(**t.model_dump(exclude={"transcript", "latest_code", "suggested_intervention"}))
            for t in _TICKETS.values()]


def get_ticket(ticket_id: str) -> TicketDetail | None:
    return _TICKETS.get(ticket_id)


def add_mentor_reply(ticket_id: str, text: str) -> ChatMessage | None:
    ticket = _TICKETS.get(ticket_id)
    if ticket is None:
        return None
    msg = ChatMessage(id=new_id("msg"), session_id=ticket.session_id, actor="mentor", text=text, ts=now_iso())
    ticket.transcript.append(msg)
    return msg


def resolve_ticket(ticket_id: str) -> Ticket | None:
    ticket = _TICKETS.get(ticket_id)
    if ticket is None:
        return None
    ticket.status = "resolved"
    return Ticket(**ticket.model_dump(exclude={"transcript", "latest_code", "suggested_intervention"}))


def stub_eval_results() -> EvalResults:
    return EvalResults(
        status="stub",
        generated_at=None,
        held_out_problems=["sliding-window-max", "dijkstra-grid", "coin-change"],
        base=EvalModelStats(model_key="hint_base", win_rate=0.5, n=0, leak_rate=0.0,
                            criteria={"correct_level": 0.0, "socratic": 0.0, "helpful": 0.0, "brevity": 0.0}),
        tuned=EvalModelStats(model_key="hint_tuned", win_rate=0.5, n=0, leak_rate=0.0,
                             criteria={"correct_level": 0.0, "socratic": 0.0, "helpful": 0.0, "brevity": 0.0}),
        examples=[
            EvalExample(scenario_id="stub-1", problem_id="two-sum", hint_level=2,
                        base_hint="(stub) Name the pattern family you would use here.",
                        tuned_hint="(stub) Think about what you can store as you scan.",
                        winner="tie"),
        ],
    )

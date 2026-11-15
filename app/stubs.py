"""Phase 1 stub data. Lets the frontend build against the real contract before the
orchestrator exists. Shapes match app/models.py exactly. Contains no reference
solutions and no hidden tests.
"""

from __future__ import annotations

import json
from pathlib import Path

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
    TraceEvent,
    TraceNode,
    TraceTree,
    VisibleTest,
)

STUB_TRACE_ID = "trc_stub_0001"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _load_problems() -> dict[str, ProblemDetail]:
    """Problems with a full statement, starter code and visible tests: data/problems.json."""
    path = Path(__file__).resolve().parent.parent / "data" / "problems.json"
    return {p["id"]: ProblemDetail(**p) for p in json.loads(path.read_text(encoding="utf-8"))}


_PROBLEMS: dict[str, ProblemDetail] = _load_problems()

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


def stub_final(session_id: str) -> FinalEvent:
    return FinalEvent(
        reply=(
            "Good start. Try writing down what you need to know about each number as you "
            "scan the list. What would make the lookup for the partner number cheap?"
        ),
        mode="learn",
        hint_level=1,
        escalated=False,
        trace_id=STUB_TRACE_ID,
    )


def stub_trace_events(session_id: str) -> list[TraceEvent]:
    """A short realistic turn: guard -> mode -> hint coach -> output guard."""
    t = now_iso()
    base = dict(trace_id=STUB_TRACE_ID, session_id=session_id, ts=t)
    return [
        TraceEvent(event_id="evt_0001", span_id="spn_root", parent_span_id=None, seq=1,
                   actor="orchestrator", type="turn.start", name="turn", status="ok",
                   latency_ms=1310.0, **base),
        TraceEvent(event_id="evt_0002", span_id="spn_guard", parent_span_id="spn_root", seq=2,
                   actor="guard", type="guard.input", name="classify_input", status="ok",
                   decision="ok", reason="fast model: ok (0.94)", latency_ms=212.0,
                   model="claude-haiku-5-5", tokens_in=180, tokens_out=12, cost_usd=0.00004,
                   input="I'm stuck on how to find the pair", output='{"category":"ok"}', **base),
        TraceEvent(event_id="evt_0003", span_id="spn_mode", parent_span_id="spn_root", seq=3,
                   actor="orchestrator", type="mode.decision", name="select_mode", status="ok",
                   decision="learn", reason="rule learn.default: no solved runs yet",
                   latency_ms=1.2, **base),
        TraceEvent(event_id="evt_0004", span_id="spn_coach", parent_span_id="spn_root", seq=4,
                   actor="hint_coach", type="agent.start", name="hint_coach", status="ok", **base),
        TraceEvent(event_id="evt_0005", span_id="spn_llm", parent_span_id="spn_coach", seq=5,
                   actor="hint_coach", type="llm.call", name="llm_hint", status="ok",
                   model="claude-sonnet-5-5", latency_ms=980.0, tokens_in=640, tokens_out=70,
                   cost_usd=0.0029, input="level=1 problem=two-sum", output="(hint text)", **base),
        TraceEvent(event_id="evt_0006", span_id="spn_out", parent_span_id="spn_root", seq=6,
                   actor="guard", type="guard.output", name="leak_check", status="ok",
                   decision="pass", reason="no code before L5; similarity 0.12 < 0.80",
                   latency_ms=15.0, **base),
        TraceEvent(event_id="evt_0007", span_id="spn_root", parent_span_id=None, seq=7,
                   actor="orchestrator", type="turn.end", name="turn", status="ok", **base),
    ]


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


def stub_trace_tree(trace_id: str, session_id: str) -> TraceTree:
    events = stub_trace_events(session_id)
    by_span: dict[str, TraceNode] = {}
    roots: list[TraceNode] = []
    # A span emits a start and an end event; the tree shows the first (start) one.
    for ev in events:
        if ev.span_id not in by_span:
            by_span[ev.span_id] = TraceNode(event=ev)
    for ev in events:
        node = by_span[ev.span_id]
        if node.event is not ev:
            continue
        if ev.parent_span_id and ev.parent_span_id in by_span:
            by_span[ev.parent_span_id].children.append(node)
        else:
            roots.append(node)
    return TraceTree(trace_id=trace_id, session_id=session_id, roots=roots)


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

"""Pydantic contract models shared by the API, orchestrator and tracing.

Safety property: response models for problems (ProblemDetail) have no field
for a reference solution or hidden tests, so they cannot be serialised.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Difficulty = Literal["easy", "medium", "hard"]
Mode = Literal["learn", "interview", "blitz", "call"]
Actor = Literal[
    "client",
    "guard",
    "orchestrator",
    "interviewer",
    "caller",
    "cv_writer",
    "hint_coach",
    "evaluator",
    "planner",
    "mentor",
    "escalation",
]
EventType = Literal[
    "turn.start",
    "guard.input",
    "mode.decision",
    "agent.start",
    "llm.call",
    "tool.call",
    "tool.result",
    "guard.output",
    "escalation.created",
    "mentor.message",
    "turn.end",
    "eval.run",
    "eval.pair",
]
EventStatus = Literal["ok", "blocked", "error", "retried"]
NextAction = Literal["keep_coding", "ask_for_hint", "review_complexity", "escalate"]
ChatActor = Literal["student", "coach", "mentor"]
TicketStatus = Literal["open", "resolved"]


# ---------- problems ----------


class Problem(BaseModel):
    id: str
    title: str
    difficulty: Difficulty
    pattern: str


class VisibleTest(BaseModel):
    name: str
    input: str
    expected: str


class ProblemDetail(Problem):
    statement: str
    starter_code: str
    visible_tests: list[VisibleTest]


# ---------- sessions and messages ----------


class TrackProblem(Problem):
    runnable: bool = Field(description="True when a full statement, starter code and tests exist.")


class TrackSummary(BaseModel):
    id: str
    title: str
    count: int


class Track(TrackSummary):
    problems: list[TrackProblem]


class SessionCreateIn(BaseModel):
    mode: Mode = "learn"


class SessionCreated(BaseModel):
    session_id: str


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    problem_id: str
    code: str = ""


class FinalEvent(BaseModel):
    """Last SSE event of POST /sessions/{id}/message (event name: final)."""

    reply: str
    mode: Mode
    hint_level: int = Field(ge=0, le=5)
    escalated: bool
    trace_id: str


class Failure(BaseModel):
    name: str
    message: str


class RunIn(BaseModel):
    """Test results from the browser runner. Trusted for the hackathon scope."""

    problem_id: str
    code: str
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    total: int = Field(ge=0)
    failures: list[Failure] = []
    runtime_ms: int = Field(ge=0)


class RunOut(BaseModel):
    mode: Mode
    hint_level_available: int = Field(
        ge=0, le=5, description="Highest hint level the student may unlock next (0 = none)."
    )
    next_action: NextAction


class SessionState(BaseModel):
    session_id: str
    problem_id: Optional[str]
    mode: Mode
    hint_level: int = Field(ge=0, le=5)
    failed_runs: int = Field(ge=0, description="Consecutive failed runs.")
    hints_used: int = Field(ge=0)
    time_on_problem: int = Field(ge=0, description="Seconds on the current problem.")
    mastery: dict[str, float]
    escalated: bool
    countdown_seconds: Optional[int] = Field(
        default=None, description="Only set in blitz mode; the frontend shows it."
    )


# ---------- tracing ----------


class TraceEvent(BaseModel):
    event_id: str
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    session_id: str
    seq: int
    ts: str
    actor: Actor
    type: EventType
    name: str
    status: EventStatus
    latency_ms: Optional[float] = None
    model: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    cost_usd: Optional[float] = None
    input: Optional[str] = None
    output: Optional[str] = None
    decision: Optional[str] = None
    reason: Optional[str] = None


class TraceNode(BaseModel):
    event: TraceEvent
    children: list[TraceNode] = []


TraceNode.model_rebuild()


class TraceTree(BaseModel):
    trace_id: str
    session_id: str
    roots: list[TraceNode]


# ---------- mentor ----------


class ChatMessage(BaseModel):
    id: str
    session_id: str
    actor: ChatActor
    text: str
    ts: str
    trace_id: Optional[str] = None


class Ticket(BaseModel):
    id: str
    session_id: str
    problem_id: str
    status: TicketStatus
    stuck_reason: str
    created_at: str


class TicketDetail(Ticket):
    transcript: list[ChatMessage]
    latest_code: str
    suggested_intervention: str


class MentorReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


# ---------- eval ----------


class EvalModelStats(BaseModel):
    model_key: Literal["hint_base", "hint_tuned"]
    win_rate: float = Field(ge=0, le=1)
    n: int = Field(ge=0)
    leak_rate: float = Field(ge=0, le=1)
    criteria: dict[str, float]


class EvalExample(BaseModel):
    scenario_id: str
    problem_id: str
    hint_level: int = Field(ge=1, le=5)
    base_hint: str
    tuned_hint: str
    winner: Literal["base", "tuned", "tie"]


class EvalResults(BaseModel):
    status: Literal["stub", "ready"]
    generated_at: Optional[str] = None
    held_out_problems: list[str]
    base: Optional[EvalModelStats] = None
    tuned: Optional[EvalModelStats] = None
    examples: list[EvalExample]

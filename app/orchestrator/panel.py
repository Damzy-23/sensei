"""The interview panel: a lead who talks and an observer who takes notes.

Scores are computed here by a fixed formula from the observer's ratings, so the number a
candidate sees can be traced to the notes behind it. The evaluator writes the words only.
"""

from __future__ import annotations

from app import catalog
from app.agents import evaluator
from app.agents.observer import DIMENSIONS
from app.guards import leak
from app.llm.gateway import LLMError
from app.memory import repository as memory
from app.models import Debrief, DimensionScore, PanelNote, PanelView
from app.orchestrator.turn import TurnError
from app.tracing.context import turn

PANEL_MODES = frozenset({"interview", "blitz", "call"})
MIN_SCORE, MID_SCORE, MAX_SCORE, SPREAD = 1.0, 2.5, 4.0, 1.5


def scores(notes: list[dict]) -> dict[str, DimensionScore]:
    """Score each dimension from 1 to 4. A dimension with no notes is not observed: it has no score."""
    out: dict[str, DimensionScore] = {}
    for dimension in DIMENSIONS:
        ratings = [n["rating"] for n in notes if n["dimension"] == dimension]
        if not ratings:
            out[dimension] = DimensionScore(score=None, signals=0)
            continue
        value = MID_SCORE + SPREAD * (sum(ratings) / len(ratings))
        out[dimension] = DimensionScore(score=round(min(MAX_SCORE, max(MIN_SCORE, value)), 1), signals=len(ratings))
    return out


def view(session: memory.Session) -> PanelView:
    return PanelView(
        active=session.mode in PANEL_MODES,
        notes=[PanelNote(**n) for n in session.panel_notes],
        scores=scores(session.panel_notes),
    )


async def run_debrief(session_id: str) -> Debrief:
    session = memory.get_session(session_id)
    if session is None:
        raise LookupError("session not found")
    if not session.panel_notes:
        raise ValueError("The panel has no notes yet. Answer a few of the interviewer's questions first.")
    problem = catalog.find_problem(session.problem_id or "")
    computed = scores(session.panel_notes)
    with turn(session_id, name="debrief") as trace:
        try:
            words = await evaluator.debrief(
                problem.title if problem else "unknown problem", problem.pattern if problem else "unknown",
                session.panel_notes, {k: v.score for k, v in computed.items()},
            )
        except LLMError as exc:
            raise TurnError(str(exc), trace.trace_id) from exc
        for key in ("summary", "strengths", "work_on", "interviewers_look_for"):
            texts = [words[key]] if key == "summary" else words[key]
            if any(leak.decide(t).leaked for t in texts):
                raise TurnError("the feedback contained code and was withheld", trace.trace_id)
        return Debrief(scores=computed, notes_used=len(session.panel_notes), trace_id=trace.trace_id, **words)

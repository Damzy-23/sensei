"""Intent classification and agent routing. Pure code.

The orchestrator calls one agent per message:
  hint    -> hint_coach      (student asks for help, or is stuck)
  answer  -> interviewer     (student answers a follow-up question)
  review  -> evaluator       (last run solved the problem; check complexity)
  debug   -> hint_coach      (a run failed and the student is talking about it)
  chat    -> hint_coach      (anything else on topic)
"""

from __future__ import annotations

import re
from typing import Literal

Intent = Literal["hint", "answer", "review", "debug", "chat"]
Agent = Literal["hint_coach", "interviewer", "evaluator"]

_HINT_WORDS = re.compile(r"\b(hint|stuck|help|nudge|next step|what now|where do i start)\b", re.I)


def classify_intent(text: str, *, mode: str, last_solved: bool, awaiting_answer: bool, last_run_failed: bool) -> Intent:
    if awaiting_answer and mode in ("interview", "blitz"):
        return "answer"
    if _HINT_WORDS.search(text):
        return "hint"
    if last_solved and mode != "learn":
        return "review"
    if last_run_failed:
        return "debug"
    return "chat"


_AGENT_FOR: dict[Intent, Agent] = {
    "hint": "hint_coach",
    "answer": "interviewer",
    "review": "evaluator",
    "debug": "hint_coach",
    "chat": "hint_coach",
}


def route(intent: Intent) -> Agent:
    return _AGENT_FOR[intent]

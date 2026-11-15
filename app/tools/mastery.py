"""Tool: update long-term mastery for a pattern after a test run."""

from __future__ import annotations

from app.memory import repository as memory
from app.tracing.context import span

GAIN = 0.25  # share of the remaining gap closed by a clean solve
HINT_PENALTY = 0.15  # each hint used reduces the gain


def update_mastery(session: memory.Session, pattern: str, solved: bool) -> float:
    with span("orchestrator", "tool.call", "update_mastery", f"pattern={pattern} solved={solved}") as st:
        current = session.mastery.get(pattern, 0.0)
        if solved:
            gain = GAIN * max(0.0, 1 - HINT_PENALTY * session.hints_used)
            current = round(current + (1 - current) * gain, 3)
            session.mastery[pattern] = current
        st.output = f"{pattern}={current}"
        return current

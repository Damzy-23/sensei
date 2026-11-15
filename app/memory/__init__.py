"""Building block: Memory.

- Short-term: session state (mode, hint level, failed runs, hints used, time on
  problem) and the chat transcript.
- Long-term: mastery per pattern, which the planner reads.

Everything sits behind one repository interface so the store can change
(SQLite today in app.db, Firestore on Cloud Run) without touching the agents.
The API holds no state between requests: each turn loads state, applies the
event, and saves the new state.
"""

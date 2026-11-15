"""Building block: Memory.

- Short-term: session state (mode, hint level, failed runs, hints used, time on
  problem) and the chat transcript.
- Long-term: mastery per pattern, which the planner reads.

Everything sits behind one repository interface so the store can change
without touching the agents. SQLite (app.db) is the store every read uses;
on Cloud Run each write is also mirrored to Firestore (durable.py) and
restored on demand, so memory survives a restart of the container.
The API holds no state between requests: each turn loads state, applies the
event, and saves the new state.
"""

"""Building block: Cooperation (supervisor) and Focus (routing).

The orchestrator owns the turn loop. For each student message it runs, in order:
input guard -> mode decision -> exactly one specialist agent -> output guard ->
escalation check, inside one trace (`turn()` in app.tracing).

Rules:
- It is the only module that hands work to an agent. Agents never call each other.
- Mode decisions are rule-based where possible. Each decision records the id of
  the rule that fired as its `reason` (e.g. "rule learn.default"), so the "why"
  in the inspector is the real cause, not a description written afterwards.
- It never calls a model directly; anything that needs one goes through app.llm.
"""

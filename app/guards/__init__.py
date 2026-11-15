"""Building block: Guardrails.

- Input guard: classify every student message before any agent sees it.
- Output guard: check every reply for a leaked solution before it is sent.
  A blocked reply goes back to the agent to rewrite (evaluator-optimizer).
- Policy: escalation thresholds (hint level 5 still failing, 3 guard violations,
  frustration flagged twice) live in one place.

Every guard decision is traced with `decision` and `reason`. Secret redaction for
logs is in app.tracing.redact.
"""

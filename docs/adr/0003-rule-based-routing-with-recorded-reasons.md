# 3. Route by rules, and record the rule as the reason

**Status:** accepted · 2026-11-15

## Context
The mode decision (learn, interview, blitz) and the escalation decision
depend on facts the system already has: failed runs, hint level, guard
violations, the mode the student chose. A model making these calls adds
latency and cost, and its stated reason may not be its real one.

## Decision
Mode and escalation are decided by named rules. The trace records the id of the
rule that fired as `reason`. Decisions that do need a model (guards, agents)
return their reason as a field of structured output.

## Consequences
- The "why" in the inspector is the real cause, and can be checked against code.
- Routing is deterministic and free, and can be unit-tested.
- New behaviour needs a new rule rather than a prompt change.

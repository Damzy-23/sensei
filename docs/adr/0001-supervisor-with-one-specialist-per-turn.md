# 1. A supervisor hands each turn to one specialist

**Status:** accepted · 2026-11-15

## Context
A tutoring turn needs several skills: checking the input, deciding the mode,
coaching or interviewing, checking for leaked solutions, and sometimes a human.
Agents that run in parallel or call each other make different decisions from
partial context and are hard to trace.

## Decision
The orchestrator runs every turn and hands it to exactly one specialist agent.
Agents never call each other. Escalation to a human is a tool the orchestrator
calls.

## Consequences
- One thread of control and one trace tree per turn.
- Adding an agent means adding a route in the orchestrator, not wiring agents together.
- Enforced by `tests/test_architecture.py::test_agents_do_not_import_each_other`.
- No parallel speed-up. Not needed: a turn has one job.

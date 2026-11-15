"""Building block: Tools.

Typed functions an agent may call: read the problem and visible tests, read the
latest test run, update mastery, escalate to a mentor. Escalating to a human is
a tool like any other, so human-in-the-loop is a call the trace records, not a
special case.

Rules:
- Each tool has typed inputs and outputs and a description written for the model.
- Every call is traced as `tool.call` / `tool.result`.
- Tools never return reference solutions or hidden tests.
"""

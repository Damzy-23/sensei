# 2. Every model call goes through one gateway

**Status:** accepted · 2026-11-15

## Context
Sensei must report the model, tokens, cost and latency of every step, and swap
the hint model between base and tuned for evaluation. A model SDK called from
several places makes both incomplete without anyone noticing.

## Decision
`app/llm` is the only module that may import a model SDK. It chooses the model
for a task, records usage and cost on the active span, and switches the hint
model per `HINT_MODEL`.

## Consequences
- Cost and model reporting covers every call by construction.
- Changing a model is a config change.
- Enforced by `tests/test_architecture.py::test_only_the_llm_gateway_imports_a_model_sdk`.

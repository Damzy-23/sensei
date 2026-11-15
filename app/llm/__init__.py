"""Model gateway. Cross-cutting: not one of the six building blocks.

The only module allowed to import a model SDK. It chooses the model for a task
(fast, reasoning, or the hint model: base or tuned, per HINT_MODEL), and records
model, tokens in/out, cost (config/prices.yaml) and latency on the active span.
Keeping every call on this one path is what makes per-step cost and model
reporting complete.
"""

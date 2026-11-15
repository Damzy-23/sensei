"""Observability. Cross-cutting: not one of the six building blocks.

Every step of a turn is a span: which agent acted, what it did, the model,
tokens, cost, latency, and the decision with its reason. Spans stream live to
the agent inspector (GET /sessions/{id}/events) and are stored for
GET /traces/{id}. Text is redacted, then truncated, before it is stored.
"""

"""Durable copy of every trace event in Firestore, so the activity log survives restarts.

On when SENSEI_LOG_FIRESTORE_DB names a Firestore database (Senior uses its own
database, "senior", so nothing mixes with other apps in the project). Writes go
through a background thread: a slow or failing write never delays a reply.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from functools import lru_cache
from typing import Any

from app.models import TraceEvent

COLLECTION = "agent_logs"
log = logging.getLogger(__name__)
_queue: queue.Queue[TraceEvent] = queue.Queue(maxsize=10_000)
_worker: threading.Thread | None = None

SESSION_SCAN = 2000  # the most documents one read of a visitor's own sessions may load
TOTALS_TTL_S = 30.0
_totals: tuple[float, dict[str, float]] | None = None  # (read at, value)


def enabled() -> bool:
    return bool(os.getenv("SENSEI_LOG_FIRESTORE_DB"))


@lru_cache(maxsize=1)
def _client() -> Any:
    from google.cloud import firestore  # imported lazily: tests and local runs do not need it

    return firestore.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT") or None, database=os.environ["SENSEI_LOG_FIRESTORE_DB"])


def _drain() -> None:
    while True:
        ev = _queue.get()
        try:
            _client().collection(COLLECTION).document(ev.event_id).set(ev.model_dump())
        except Exception:  # noqa: BLE001 - the log must never take the app down
            log.exception("could not archive trace event %s", ev.event_id)


def mirror(ev: TraceEvent) -> None:
    """Queue one event for Firestore. No-op when archiving is off."""
    global _worker
    if not enabled():
        return
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_drain, name="trace-archive", daemon=True)
        _worker.start()
    try:
        _queue.put_nowait(ev)
    except queue.Full:
        log.warning("trace archive queue full; dropped %s", ev.event_id)


def recent(limit: int) -> list[TraceEvent]:
    """The newest `limit` archived events, newest first."""
    from google.cloud import firestore

    docs = _client().collection(COLLECTION).order_by("ts", direction=firestore.Query.DESCENDING).limit(limit).stream()
    return [TraceEvent(**doc.to_dict()) for doc in docs]


def for_sessions(session_ids: list[str], limit: int) -> list[TraceEvent]:
    """The newest `limit` archived events of these sessions (30 at most), newest first.

    Filtered on session_id alone and sorted here. Asking Firestore to order by `ts` as well
    would need a composite index, and a query whose index is missing fails outright.
    """
    from google.cloud.firestore_v1.base_query import FieldFilter

    query = _client().collection(COLLECTION).where(filter=FieldFilter("session_id", "in", session_ids[:30]))
    events = [TraceEvent(**doc.to_dict()) for doc in query.limit(SESSION_SCAN).stream()]
    events.sort(key=lambda ev: (ev.ts, ev.seq), reverse=True)
    return events[:limit]


def totals() -> dict[str, float]:
    """Counts and spend over every archived event, from aggregation queries: Firestore adds
    them up and no document is read. Kept for a short while, because every log view asks."""
    global _totals
    from google.cloud.firestore_v1.base_query import FieldFilter

    if _totals is not None and time.monotonic() - _totals[0] < TOTALS_TTL_S:
        return _totals[1]
    events = _client().collection(COLLECTION)

    def read(aggregation: Any) -> dict[str, float]:
        return {result.alias: result.value for row in aggregation.get() for result in row}

    whole = read(events.count(alias="events").sum("cost_usd", alias="cost_usd"))
    model = read(events.where(filter=FieldFilter("type", "==", "llm.call")).count(alias="n"))
    tool = read(events.where(filter=FieldFilter("type", "in", ["tool.call", "tool.result"])).count(alias="n"))
    value = {
        "events": int(whole["events"]), "model_calls": int(model["n"]), "tool_calls": int(tool["n"]),
        "cost_usd": float(whole["cost_usd"] or 0.0),
    }
    _totals = (time.monotonic(), value)
    return value

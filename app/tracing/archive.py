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
from functools import lru_cache
from typing import Any

from app.models import TraceEvent

COLLECTION = "agent_logs"
log = logging.getLogger(__name__)
_queue: queue.Queue[TraceEvent] = queue.Queue(maxsize=10_000)
_worker: threading.Thread | None = None


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

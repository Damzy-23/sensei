"""Durable copy of sessions, transcripts and mentor tickets in Firestore.

SQLite lives inside the container and starts empty on every deploy. Each write to it
is also queued here, and app.memory.repository reads the copy back when SQLite has no
row for a session or ticket. Same shape as app.tracing.archive: writes go through a
background thread, so a slow or failing write never delays a reply. The only time a
request waits on Firestore is the recovery read after a restart.

On when SENSEI_STATE_FIRESTORE_DB names a Firestore database; otherwise it uses the
activity log's database (SENSEI_LOG_FIRESTORE_DB), so the live service needs no new
setting. Always off with SENSEI_USE_STUBS=1.
"""

from __future__ import annotations

import atexit
import copy
import logging
import os
import queue
import threading
import time
from functools import lru_cache
from typing import Any

from app.config import get_settings

SESSIONS = "state_sessions"  # document id = session id
MESSAGES = "state_messages"  # document id = message id; session_id and ts say where it belongs
TICKETS = "state_tickets"  # document id = ticket id
READ_TIMEOUT_SECONDS = 5.0  # a request is waiting on a recovery read: give up soon

log = logging.getLogger(__name__)
_queue: queue.Queue[tuple[str, str, dict[str, Any]]] = queue.Queue(maxsize=10_000)
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def _database() -> str:
    return os.getenv("SENSEI_STATE_FIRESTORE_DB") or os.getenv("SENSEI_LOG_FIRESTORE_DB") or ""


def enabled() -> bool:
    return bool(_database()) and not get_settings().use_stubs


@lru_cache(maxsize=1)
def _client() -> Any:
    """The one place the Firestore client is made. Tests replace this with an in-memory fake."""
    from google.cloud import firestore  # imported lazily: tests and local runs do not need it

    return firestore.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT") or None, database=_database())


# ---------- writes: queued, sent by one background thread ----------


def _drain() -> None:
    while True:
        collection, doc_id, data = _queue.get()
        try:
            _client().collection(collection).document(doc_id).set(data)
        except Exception:  # noqa: BLE001 - the mirror must never take the app down
            log.exception("could not mirror %s/%s", collection, doc_id)
        finally:
            _queue.task_done()


def put(collection: str, doc_id: str, data: dict[str, Any]) -> None:
    """Queue one document for Firestore, replacing any earlier copy. No-op when off. Never raises.

    One thread sends the queue in order, so the last write of a document is the one that stays.
    """
    global _worker
    try:
        if not enabled():
            return
        with _worker_lock:
            if _worker is None or not _worker.is_alive():
                _worker = threading.Thread(target=_drain, name="state-mirror", daemon=True)
                _worker.start()
        _queue.put_nowait((collection, doc_id, copy.deepcopy(data)))  # a copy: the caller may go on changing its own
    except queue.Full:
        log.warning("state mirror queue full; dropped %s/%s", collection, doc_id)
    except Exception:  # noqa: BLE001
        log.exception("could not queue %s/%s for the state mirror", collection, doc_id)


def flush(timeout_seconds: float = 5.0) -> bool:
    """Wait until every queued write has been tried. True if the queue emptied in time."""
    deadline = time.monotonic() + timeout_seconds
    with _queue.all_tasks_done:
        while _queue.unfinished_tasks:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            _queue.all_tasks_done.wait(remaining)
    return True


atexit.register(flush, 5.0)  # a clean shutdown sends what is still queued; a crash can lose it


# ---------- reads: only for recovery; off, missing and failing all look like "nothing there" ----------


def _deadline() -> dict[str, Any]:
    """Arguments that hold one read, retries included, to READ_TIMEOUT_SECONDS.
    The library's own default keeps retrying for minutes when Firestore is unreachable."""
    from google.api_core.retry import Retry

    return {"retry": Retry(timeout=READ_TIMEOUT_SECONDS), "timeout": READ_TIMEOUT_SECONDS}


def _document(collection: str, doc_id: str) -> dict[str, Any] | None:
    try:
        if not enabled():
            return None
        snapshot = _client().collection(collection).document(doc_id).get(**_deadline())
        return snapshot.to_dict() if snapshot.exists else None
    except Exception:  # noqa: BLE001 - a failed read must not take the request down
        log.exception("could not read %s/%s", collection, doc_id)
        return None


def _of_session(collection: str, session_id: str) -> list[dict[str, Any]]:
    """Every document of one session, in no order. A filter on one field alone needs no
    composite index; asking Firestore to sort by another field as well would."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    query = _client().collection(collection).where(filter=FieldFilter("session_id", "==", session_id))
    return [doc.to_dict() for doc in query.stream(**_deadline())]


def fetch_session(session_id: str) -> dict[str, Any] | None:
    return _document(SESSIONS, session_id)


def fetch_ticket(ticket_id: str) -> dict[str, Any] | None:
    return _document(TICKETS, ticket_id)


def fetch_messages(session_id: str) -> list[dict[str, Any]]:
    """A session's whole transcript, oldest first. `seq` is the order of writing; it keeps
    messages stamped with the same millisecond in order."""
    try:
        if not enabled():
            return []
        return sorted(_of_session(MESSAGES, session_id), key=lambda m: (m.get("ts") or "", m.get("seq") or 0))
    except Exception:  # noqa: BLE001
        log.exception("could not read the messages of %s", session_id)
        return []


def fetch_tickets(limit: int, session_id: str | None = None) -> list[dict[str, Any]] | None:
    """The newest `limit` tickets, newest first: of every session, or of one.
    None when the read failed, which is not the same as there being no tickets."""
    try:
        if not enabled():
            return []
        if session_id is not None:
            tickets = _of_session(TICKETS, session_id)
            return sorted(tickets, key=lambda t: t.get("created_at") or "", reverse=True)[:limit]
        newest = _client().collection(TICKETS).order_by("created_at", direction="DESCENDING").limit(limit)
        return [doc.to_dict() for doc in newest.stream(**_deadline())]
    except Exception:  # noqa: BLE001
        log.exception("could not read tickets")
        return None

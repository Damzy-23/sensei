"""Durable copy of sessions, transcripts and mentor tickets in Firestore.

SQLite lives inside the container and starts empty on every deploy. Each write to it
is also queued here, and app.memory.repository reads the copy back when SQLite has no
row for a session or ticket. Same shape as app.tracing.archive: writes go through a
background thread, so a slow or failing write never delays a reply. The only time a
request waits on Firestore is the recovery read after a restart.

On when SENSEI_STATE_FIRESTORE_DB names a Firestore database. On Cloud Run (where K_SERVICE
is set) it otherwise uses the activity log's database (SENSEI_LOG_FIRESTORE_DB), so the live
service needs no new setting; a laptop run that only wants the live activity log stays off,
so it never writes test sessions into the live collections. Always off with SENSEI_USE_STUBS=1.

A recovery read that fails raises MemoryUnavailable, which the API answers with 503 and
"try again": a session that could not be read is not the same as a session that is not there.
After a failed read no recovery read is tried for BACK_OFF_SECONDS, so requests do not queue up
behind a database that is not answering.
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
WRITE_TIMEOUT_SECONDS = 5.0  # one attempt at one write, the library's own retries included
WRITE_RETRY_PAUSES = (0.5, 2.0)  # a failed write is tried again after these pauses, then dropped
BACK_OFF_SECONDS = 5.0  # after a failed read, recovery reads wait this long before trying again

log = logging.getLogger(__name__)
_queue: queue.Queue[tuple[str, str, dict[str, Any]]] = queue.Queue(maxsize=10_000)
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
_read_failed_at = float("-inf")  # when a recovery read last failed: for BACK_OFF_SECONDS after, reads fail at once
_write_failed_at = float("-inf")  # when a write attempt last failed; a sent write clears it
_stalled = False  # a wait for the queue ran out of time; cleared once the queue is empty again


class MemoryUnavailable(RuntimeError):
    """The durable copy could not be read just now. Not the same as "it has no such thing"."""


def _database() -> str:
    own = os.getenv("SENSEI_STATE_FIRESTORE_DB")
    if own:
        return own
    return os.getenv("SENSEI_LOG_FIRESTORE_DB", "") if os.getenv("K_SERVICE") else ""


def enabled() -> bool:
    return bool(_database()) and not get_settings().use_stubs


@lru_cache(maxsize=1)
def _client() -> Any:
    """The one place the Firestore client is made. Tests replace this with an in-memory fake."""
    from google.cloud import firestore  # imported lazily: tests and local runs do not need it

    return firestore.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT") or None, database=_database())


# ---------- writes: queued, sent by one background thread ----------


def _write_options() -> dict[str, Any]:
    from google.api_core.retry import Retry

    return {"retry": Retry(timeout=WRITE_TIMEOUT_SECONDS), "timeout": WRITE_TIMEOUT_SECONDS}


def _send(collection: str, doc_id: str, data: dict[str, Any]) -> None:
    """One write, tried again after each pause in WRITE_RETRY_PAUSES. A message is written only
    once, so a write lost here would be a hole in the restored transcript."""
    global _write_failed_at
    for pause in (*WRITE_RETRY_PAUSES, None):
        try:
            _client().collection(collection).document(doc_id).set(data, **_write_options())
            _write_failed_at = float("-inf")
            return
        except Exception:  # noqa: BLE001 - the mirror must never take the app down
            _write_failed_at = time.monotonic()  # from the first failed try on, nobody waits for the queue
            if pause is None:
                log.exception("could not mirror %s/%s; gave up after %d tries", collection, doc_id, len(WRITE_RETRY_PAUSES) + 1)
                return
            time.sleep(pause)


def _drain() -> None:
    global _stalled
    while True:
        collection, doc_id, data = _queue.get()
        try:
            _send(collection, doc_id, data)
        finally:
            _queue.task_done()
            if not _queue.unfinished_tasks:
                _stalled = False


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


def pending() -> int:
    """Writes queued or being sent."""
    return _queue.unfinished_tasks


def writing_well() -> bool:
    """Whether it is worth waiting for the queue. Not from a failed write attempt until a write gets
    through (or for 30 s), nor after a wait ran out of time until the queue is empty again: a write
    against a database that does not answer can take seconds to fail, and one request waiting on it
    is enough."""
    return not _stalled and time.monotonic() - _write_failed_at > 30.0


def flush(timeout_seconds: float = 5.0) -> bool:
    """Wait until every queued write has been tried. True if the queue emptied in time."""
    global _stalled
    deadline = time.monotonic() + timeout_seconds
    with _queue.all_tasks_done:
        while _queue.unfinished_tasks:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stalled = True
                return False
            _queue.all_tasks_done.wait(remaining)
    return True


# The app's shutdown (app.main) is what sends what is still queued; uvicorn re-raises SIGTERM after
# its graceful shutdown, so this exit hook only runs where that signal does not kill the process.
atexit.register(flush, 5.0)


# ---------- reads: only for recovery. Off and missing give "nothing there"; failing raises ----------


def _deadline() -> dict[str, Any]:
    """Arguments that hold one read, retries included, to READ_TIMEOUT_SECONDS.
    The library's own default keeps retrying for minutes when Firestore is unreachable."""
    from google.api_core.retry import Retry

    return {"retry": Retry(timeout=READ_TIMEOUT_SECONDS), "timeout": READ_TIMEOUT_SECONDS}


def _read(what: str, fetch: Any) -> Any:
    """Run one recovery read. A failure pauses all recovery reads for BACK_OFF_SECONDS and raises."""
    global _read_failed_at
    if time.monotonic() - _read_failed_at < BACK_OFF_SECONDS:
        raise MemoryUnavailable(f"the durable copy did not answer a moment ago; not reading {what}")
    try:
        return fetch()
    except Exception as exc:  # noqa: BLE001 - whatever went wrong, the caller gets one kind of error
        _read_failed_at = time.monotonic()
        log.exception("could not read %s", what)
        raise MemoryUnavailable(f"could not read {what}") from exc


def reset() -> None:
    """Forget past failures. Tests use it to act out a new process."""
    global _read_failed_at, _write_failed_at, _stalled
    _read_failed_at = _write_failed_at = float("-inf")
    _stalled = False


def _document(collection: str, doc_id: str) -> dict[str, Any] | None:
    if not enabled():
        return None

    def fetch() -> dict[str, Any] | None:
        snapshot = _client().collection(collection).document(doc_id).get(**_deadline())
        return snapshot.to_dict() if snapshot.exists else None

    return _read(f"{collection}/{doc_id}", fetch)


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
    if not enabled():
        return []
    messages = _read(f"the messages of {session_id}", lambda: _of_session(MESSAGES, session_id))
    return sorted(messages, key=lambda m: (m.get("ts") or "", m.get("seq") or 0))


def fetch_tickets(limit: int, session_id: str | None = None) -> list[dict[str, Any]]:
    """The newest `limit` tickets, newest first: of every session, or of one."""
    if not enabled():
        return []
    if session_id is not None:
        tickets = _read(f"the tickets of {session_id}", lambda: _of_session(TICKETS, session_id))
        return sorted(tickets, key=lambda t: t.get("created_at") or "", reverse=True)[:limit]

    def newest() -> list[dict[str, Any]]:
        query = _client().collection(TICKETS).order_by("created_at", direction="DESCENDING").limit(limit)
        return [doc.to_dict() for doc in query.stream(**_deadline())]

    return _read("the newest tickets", newest)

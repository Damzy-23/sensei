"""Memory that survives a restart: every write is mirrored to Firestore and read back on a miss.

Firestore here is an in-memory fake with the calls app.memory.durable makes. A restart is
acted out the way a deploy does it: a new, empty SQLite file, and nothing remembered in the
process about what was already loaded.
"""

from __future__ import annotations

import copy
import dataclasses
import itertools
import json
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.llm import gateway
from app.llm.gateway import LLMResult
from app.main import app
from app.memory import durable
from app.memory import repository as memory
from app.memory.repository import Session

TABLES = ("sessions", "messages", "tickets")
# Google's libraries warn on import under Python 3.10, which is only the local interpreter: the container runs 3.12.
pytestmark = pytest.mark.filterwarnings("ignore:You are using a non-supported Python version:FutureWarning")


# ---------- an in-memory Firestore ----------


class FakeFirestore:
    """Documents in dicts, and a record of every write and read.

    It keeps the rules of the real one that this code has to live with: a document is plain
    data, a filter on one field sorted by another needs an index nobody has created, and
    without a sort the documents come back in order of their ids, not of their writing.
    """

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, dict]] = defaultdict(dict)
        self.writes: list[tuple[str, str]] = []  # (collection, id), in the order they landed
        self.reads: list[tuple[str, str, str]] = []  # ("get" | "query", collection, what)
        self.read_options: list[dict] = []  # the keyword arguments each read was given
        self.down = False  # True: every call raises
        self.gate = threading.Event()  # cleared: writes stall until it is set again
        self.gate.set()
        self.writing = threading.Event()  # set once a write has reached Firestore
        self.write_delay = 0.0  # seconds each write takes, as a real commit does
        self.failing_writes = 0  # the next this many writes raise, as a real commit sometimes does
        self.failing_queries: set[str] = set()  # collections whose queries raise

    def collection(self, name: str) -> _Query:
        if self.down:
            raise RuntimeError("firestore is down")
        return _Query(self, name)


def _check_storable(value: object, inside_list: bool = False) -> None:
    if isinstance(value, dict):
        assert all(isinstance(key, str) and key for key in value), "field names are non-empty strings"
        for item in value.values():
            _check_storable(item)
    elif isinstance(value, list):
        assert not inside_list, "Firestore cannot store a list directly inside a list"
        for item in value:
            _check_storable(item, inside_list=True)
    else:
        assert value is None or isinstance(value, (str, int, float, bool)), f"cannot store {type(value).__name__}"


class _Snapshot:
    def __init__(self, data: dict | None) -> None:
        self.exists = data is not None
        self._data = copy.deepcopy(data)

    def to_dict(self) -> dict | None:
        return self._data


class _Document:
    def __init__(self, fake: FakeFirestore, collection: str, doc_id: str) -> None:
        self.fake, self.collection, self.id = fake, collection, doc_id

    def set(self, data: dict, **options: object) -> None:
        self.fake.writing.set()
        self.fake.gate.wait(5)
        if self.fake.write_delay:
            time.sleep(self.fake.write_delay)
        if self.fake.failing_writes:
            self.fake.failing_writes -= 1
            raise RuntimeError("INTERNAL: the commit failed")
        _check_storable(data)
        self.fake.docs[self.collection][self.id] = copy.deepcopy(data)
        self.fake.writes.append((self.collection, self.id))

    def get(self, **options: object) -> _Snapshot:
        self.fake.reads.append(("get", self.collection, self.id))
        self.fake.read_options.append(options)
        return _Snapshot(self.fake.docs[self.collection].get(self.id))


class _Query:
    def __init__(self, fake: FakeFirestore, name: str, where=None, order=None, limit=None) -> None:
        self.fake, self.name, self._where, self._order, self._limit = fake, name, where, order, limit

    def document(self, doc_id: str) -> _Document:
        return _Document(self.fake, self.name, doc_id)

    def where(self, *, filter) -> _Query:  # noqa: A002 - Firestore's own keyword
        assert filter.op_string == "=="
        return _Query(self.fake, self.name, (filter.field_path, filter.value), self._order, self._limit)

    def order_by(self, field: str, direction: str = "ASCENDING") -> _Query:
        return _Query(self.fake, self.name, self._where, (field, direction), self._limit)

    def limit(self, count: int) -> _Query:
        return _Query(self.fake, self.name, self._where, self._order, count)

    def stream(self, **options: object) -> Iterator[_Snapshot]:
        if self.name in self.fake.failing_queries:
            raise RuntimeError("UNAVAILABLE: the query failed")
        if self._where and self._order and self._order[0] != self._where[0]:
            raise RuntimeError("FAILED_PRECONDITION: The query requires an index.")
        self.fake.reads.append(("query", self.name, f"where={self._where} order={self._order} limit={self._limit}"))
        self.fake.read_options.append(options)
        docs = [doc for _, doc in sorted(self.fake.docs[self.name].items())]  # by id, as Firestore does
        if self._where:
            docs = [doc for doc in docs if doc.get(self._where[0]) == self._where[1]]
        if self._order:
            docs.sort(key=lambda doc: doc[self._order[0]], reverse=self._order[1] == "DESCENDING")
        return iter([_Snapshot(doc) for doc in docs[: self._limit]])


# ---------- the app around it ----------


class ScriptedModel:
    """As in test_turn.py: answers by which prompt it is given. `hints` are returned in order."""

    def __init__(self) -> None:
        self.category = "stuck"
        self.hints = ["What do you need to remember about each number as you scan?"]
        self.calls: list[tuple[str, str]] = []

    async def complete(self, *, model: str, system: str, user: str, max_tokens: int, effort: str) -> LLMResult:
        self.calls.append((model, user))
        if "Classify the" in system:
            text = json.dumps({"category": self.category, "confidence": 0.9, "reason": "they say they are stuck"})
            return LLMResult(text, model, 100, 20)
        if "illustrator" in system:  # the illustrator: no picture, and no hint used up
            return LLMResult('{"kind": "none"}', model, 50, 5)
        return LLMResult(self.hints.pop(0) if len(self.hints) > 1 else self.hints[0], model, 400, 60)


@pytest.fixture
def model(tmp_path, monkeypatch) -> Iterator[ScriptedModel]:
    """The real loop (no stubs) on an empty SQLite file, with a scripted model. Durable memory is off."""
    monkeypatch.setenv("SENSEI_USE_STUBS", "0")
    monkeypatch.setenv("HINT_MODEL", "base")
    monkeypatch.setenv("SENSEI_DB_PATH", str(tmp_path / "boot-0.db"))
    db.reset_connection()
    memory.reset_restore_state()
    scripted = ScriptedModel()
    gateway.set_client(scripted)
    yield scripted
    flushed = durable.flush(10)  # before the fake is taken away: no queued write may outlive it
    gateway.set_client(None)
    db.reset_connection()
    memory.reset_restore_state()
    assert flushed


@pytest.fixture
def firestore(model: ScriptedModel, monkeypatch) -> FakeFirestore:
    """Durable memory switched on, over the fake."""
    fake = FakeFirestore()
    monkeypatch.setenv("SENSEI_STATE_FIRESTORE_DB", "senior-test")
    monkeypatch.setattr(durable, "WRITE_RETRY_PAUSES", (0.0, 0.0))  # a failing write gives up at once
    monkeypatch.setattr(durable, "_client", lambda: fake)
    return fake


@pytest.fixture
def restart(model: ScriptedModel, tmp_path, monkeypatch) -> Callable[[], None]:
    """What a deploy does to memory: queued writes go out, then a new process starts on an empty SQLite file."""
    boots = itertools.count(1)

    def _restart() -> None:
        assert durable.flush(5)
        monkeypatch.setenv("SENSEI_DB_PATH", str(tmp_path / f"boot-{next(boots)}.db"))
        db.reset_connection()
        memory.reset_restore_state()
        assert _rows() == {"sessions": 0, "messages": 0, "tickets": 0}  # SQLite really is empty again

    return _restart


def _rows() -> dict[str, int]:
    conn = memory._conn()
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}


def _seed(mode: str = "learn") -> tuple[Session, str]:
    """A session part-way through a problem, four messages, and an open mentor ticket."""
    session = memory.create_session(mode)
    session.start_problem("two-sum")
    session.hint_level, session.hints_used, session.failed_runs = 3, 4, 2
    session.latest_code = "def two_sum(nums, target):\n    seen = {}\n"
    session.mastery = {"hash map": 0.25}
    for actor, text in [("student", "I'm stuck"), ("coach", "What have you tried?"),
                        ("student", "Two loops"), ("coach", "What would make the lookup faster?")]:
        memory.add_message(session.session_id, actor, text, "trc_seed")
    ticket = memory.create_ticket(session, "rule escalate.max_hint: still stuck", "Walk through the second example.")
    session.escalated = True
    memory.save_session(session)
    return session, ticket.id


def _events(body: str) -> list[tuple[str, dict]]:
    out = []
    for chunk in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines() if ": " in line)
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def _send(client: TestClient, session_id: str, text: str = "I'm stuck") -> dict:
    """One student message. The reply must be a normal one: 200, ending in a `final` event."""
    r = client.post(f"/sessions/{session_id}/message", json={"text": text, "problem_id": "two-sum", "code": "pass"})
    assert r.status_code == 200, r.text
    # A picture may follow the reply on the same stream; the reply is the `final` event.
    finals = [data for name, data in _events(r.text) if name == "final"]
    assert len(finals) == 1, r.text[-400:]
    return finals[0]


def _new(client: TestClient) -> str:
    return client.post("/sessions", json={"mode": "learn"}).json()["session_id"]


# ---------- off by default ----------


@pytest.mark.parametrize(
    ("state_db", "log_db", "stubs", "expected"),
    [
        ("", "", "0", False),  # nothing named: off
        ("senior", "", "0", True),
        ("", "senior", "0", False),  # off a laptop; on Cloud Run it is borrowed (test further down)
        ("senior", "senior", "1", False),  # never with stub data
    ],
)
def test_it_is_on_only_when_a_database_is_named_and_never_with_stubs(monkeypatch, state_db, log_db, stubs, expected) -> None:
    monkeypatch.setenv("SENSEI_STATE_FIRESTORE_DB", state_db)
    monkeypatch.setenv("SENSEI_LOG_FIRESTORE_DB", log_db)
    monkeypatch.setenv("SENSEI_USE_STUBS", stubs)
    assert durable.enabled() is expected


def test_its_own_database_setting_wins_over_the_activity_logs(monkeypatch) -> None:
    monkeypatch.setenv("K_SERVICE", "senior")
    monkeypatch.setenv("SENSEI_LOG_FIRESTORE_DB", "senior")
    assert durable._database() == "senior"
    monkeypatch.setenv("SENSEI_STATE_FIRESTORE_DB", "senior-state")
    assert durable._database() == "senior-state"


def test_off_by_default_firestore_is_never_touched_and_a_restart_still_loses_everything(model, restart, monkeypatch) -> None:
    made: list[str] = []
    monkeypatch.setattr(durable, "_client", lambda: made.append("client") or FakeFirestore())
    assert durable.enabled() is False

    session, ticket_id = _seed()
    sid = session.session_id
    assert memory.get_session(sid) == session
    assert [m.text for m in memory.transcript(sid)] == ["I'm stuck", "What have you tried?", "Two loops", "What would make the lookup faster?"]
    assert [t.id for t in memory.list_tickets()] == [ticket_id]
    assert len(memory.get_ticket(ticket_id).transcript) == 4
    assert memory.resolve_ticket(ticket_id).status == "resolved"
    assert memory.get_session("ses_nobody") is None and memory.get_ticket("tkt_nothing") is None
    assert durable.fetch_session(sid) is None and durable.fetch_messages(sid) == []
    assert durable.fetch_tickets(10) == [] and durable.fetch_ticket(ticket_id) is None

    restart()
    assert memory.get_session(sid) is None
    assert memory.list_tickets() == [] and memory.get_ticket(ticket_id) is None
    assert made == [] and durable._queue.unfinished_tasks == 0


def test_with_it_off_a_message_after_a_restart_is_still_a_404(model, restart) -> None:
    client = TestClient(app)
    sid = _new(client)
    assert _send(client, sid)["hint_level"] == 1
    restart()
    r = client.post(f"/sessions/{sid}/message", json={"text": "hello?", "problem_id": "two-sum", "code": ""})
    assert r.status_code == 404 and r.json()["detail"] == "session not found"


# ---------- surviving a restart ----------


def test_a_session_its_transcript_and_its_ticket_survive_a_restart(firestore, restart) -> None:
    session, ticket_id = _seed(mode="interview")
    sid = session.session_id
    thread, detail = memory.transcript(sid), memory.get_ticket(ticket_id)
    assert len(thread) == 4 and detail.transcript == thread

    restart()
    restored = memory.get_session(sid)
    assert restored == session and restored is not session
    assert restored.mode == "interview" and restored.hint_level == 3 and restored.escalated is True
    assert memory.transcript(sid) == thread  # the same messages, in the same order
    tickets = memory.list_tickets()
    assert [(t.id, t.session_id, t.status) for t in tickets] == [(ticket_id, sid, "open")]
    again = memory.get_ticket(ticket_id)
    assert again == detail
    assert again.transcript == thread and again.latest_code == session.latest_code
    assert again.suggested_intervention == "Walk through the second example."

    # Reads from here on are answered by SQLite: asking again costs Firestore nothing.
    reads = len(firestore.reads)
    memory.get_session(sid), memory.transcript(sid), memory.list_tickets(), memory.get_ticket(ticket_id)
    assert len(firestore.reads) == reads


def test_the_mentor_queue_comes_back_before_any_student_has_returned(firestore, restart) -> None:
    (first, first_ticket), (second, second_ticket) = _seed(), _seed()
    thread = memory.transcript(second.session_id)
    restart()

    assert [t.id for t in memory.list_tickets()] == [second_ticket, first_ticket]  # newest first, as before
    assert _rows() == {"sessions": 0, "messages": 0, "tickets": 2}  # the queue only; sessions come when asked for
    detail = memory.get_ticket(second_ticket)
    assert detail.transcript == thread and detail.latest_code == second.latest_code
    assert memory.get_session(second.session_id) == second

    memory.list_tickets()
    queue_loads = [r for r in firestore.reads if r[:2] == ("query", "state_tickets") and "where=None" in r[2]]
    assert len(queue_loads) == 1  # loaded once per process, then answered from SQLite


def test_a_ticket_older_than_the_restored_queue_is_still_found_by_id(firestore, restart, monkeypatch) -> None:
    monkeypatch.setattr(memory, "RESTORED_TICKETS", 1)
    (old, old_ticket), (_, new_ticket) = _seed(), _seed()
    thread = memory.transcript(old.session_id)
    restart()

    assert [t.id for t in memory.list_tickets()] == [new_ticket]
    detail = memory.get_ticket(old_ticket)
    assert detail is not None and detail.id == old_ticket and detail.transcript == thread
    assert {t.id for t in memory.list_tickets()} == {old_ticket, new_ticket}


def test_a_ticket_asked_for_by_id_first_comes_back_with_its_transcript(firestore, restart) -> None:
    session, ticket_id = _seed()
    thread = memory.transcript(session.session_id)
    restart()
    detail = memory.get_ticket(ticket_id)  # a mentor with the ticket already open: no list first
    assert detail is not None and detail.transcript == thread and detail.latest_code == session.latest_code


def test_messages_stamped_with_the_same_millisecond_keep_their_order(firestore, restart, monkeypatch) -> None:
    monkeypatch.setattr(memory, "now_iso", lambda: "2026-11-15T12:00:00.000+00:00")
    session = memory.create_session()
    sent = [memory.add_message(session.session_id, "student" if i % 2 == 0 else "coach", f"message {i}") for i in range(12)]
    restart()
    assert memory.get_session(session.session_id) is not None
    assert [m.text for m in memory.transcript(session.session_id)] == [f"message {i}" for i in range(12)]
    assert memory.transcript(session.session_id) == sent


def _unlike(value: object) -> object:
    """A value of the same kind as a field's default, and different from it."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 3
    if isinstance(value, str) or value is None:
        return f"{value or ''}-changed"
    if isinstance(value, dict):
        return {"hash map": 0.75, "two pointers": 0.5}
    if isinstance(value, list):
        return [{"dimension": "approach", "rating": 1, "note": "Named the trade-off."}]
    raise AssertionError(f"teach _unlike() about {type(value).__name__}, then this test covers the new field")


def test_every_field_of_a_session_round_trips_including_ones_added_later(firestore, restart) -> None:
    blank = memory.create_session()
    session = Session(session_id=blank.session_id)
    names = [f.name for f in dataclasses.fields(Session) if f.name != "session_id"]
    for name in names:  # read from the dataclass: a field someone adds tomorrow is covered without touching this test
        setattr(session, name, _unlike(getattr(blank, name)))
    assert names and all(getattr(session, name) != getattr(blank, name) for name in names)
    memory.save_session(session)

    restart()
    restored = memory.get_session(session.session_id)
    assert restored == session
    assert dataclasses.asdict(restored) == dataclasses.asdict(session)
    assert [name for name in names if getattr(restored, name) == getattr(blank, name)] == []


def test_a_copy_written_by_another_version_of_the_code_still_restores(firestore, restart) -> None:
    session = memory.create_session("blitz")
    session.hint_level = 2
    memory.save_session(session)
    restart()
    doc = firestore.docs[durable.SESSIONS][session.session_id]
    stored = json.loads(doc["data"])
    del stored["failed_runs"]  # written before this field existed
    stored["a_field_since_removed"] = [1, 2, 3]
    doc["data"] = json.dumps(stored)

    restored = memory.get_session(session.session_id)
    assert restored is not None and restored.mode == "blitz" and restored.hint_level == 2
    assert restored.failed_runs == 0 and not hasattr(restored, "a_field_since_removed")
    assert memory.get_session(session.session_id) == restored  # and what SQLite now holds loads as usual


def test_a_copy_that_cannot_be_read_is_not_found_rather_than_an_error(firestore, restart) -> None:
    session, _ = _seed()
    restart()
    firestore.docs[durable.SESSIONS][session.session_id]["data"] = "{ not json"
    assert memory.get_session(session.session_id) is None
    assert _rows()["sessions"] == 0

    firestore.docs[durable.MESSAGES]["msg_broken"] = {"id": "msg_broken", "session_id": "ses_other"}  # no text, no actor
    other = Session(session_id="ses_other", hint_level=4)
    firestore.docs[durable.SESSIONS]["ses_other"] = {"session_id": "ses_other", "data": json.dumps(other.__dict__)}
    assert memory.get_session("ses_other") == other  # the session comes back; the broken message is left out
    assert memory.transcript("ses_other") == []


# ---------- the whole path, through the real app ----------


def test_a_student_carries_on_after_a_restart_where_they_left_off(firestore, restart, model: ScriptedModel) -> None:
    model.hints = ["What repeats as you scan the list?", "What could you keep beside each number?",
                   "Which lookup is fastest for that?", "When would you store it: before or after the check?"]
    client = TestClient(app)
    sid = _new(client)
    assert [_send(client, sid)["hint_level"] for _ in range(2)] == [1, 2]
    thread = memory.transcript(sid)
    assert len(thread) == 4

    restart()
    final = _send(client, sid, text="Still stuck after the break")  # the SAME session id: a reply, not a 404
    assert final["hint_level"] == 3 and final["escalated"] is False
    assert final["reply"] == "Which lookup is fastest for that?"
    state = client.get(f"/sessions/{sid}/state").json()
    assert state["hint_level"] == 3 and state["hints_used"] == 3 and state["problem_id"] == "two-sum"
    after = memory.transcript(sid)
    assert after[:4] == thread and [m.actor for m in after] == ["student", "coach"] * 3
    # The coach was shown the conversation from before the restart.
    assert "student: I'm stuck\ncoach: What repeats as you scan the list?" in [c for c in model.calls if "STUDENT-" not in c[1]][-1][1]
    assert "coach: What could you keep beside each number?" in [c for c in model.calls if "STUDENT-" not in c[1]][-1][1]

    restart()  # what was written after the first restart was mirrored too
    assert _send(client, sid)["hint_level"] == 4
    assert [m.text for m in memory.transcript(sid)][:6] == [m.text for m in after]


def test_a_ticket_resolved_after_a_restart_is_still_resolved_after_the_next(firestore, restart, model: ScriptedModel) -> None:
    model.category = "frustrated"
    client = TestClient(app)
    sid = _new(client)
    assert [_send(client, sid, text="I give up")["escalated"] for _ in range(2)] == [False, True]
    ticket_id = client.get("/mentor/tickets").json()[0]["id"]

    restart()
    queue = client.get("/mentor/tickets").json()
    assert [(t["id"], t["session_id"], t["status"]) for t in queue] == [(ticket_id, sid, "open")]
    detail = client.get(f"/mentor/tickets/{ticket_id}").json()
    assert len(detail["transcript"]) == 4 and detail["latest_code"] == "pass"
    reply = client.post(f"/mentor/tickets/{ticket_id}/reply", json={"text": "Look at the inner loop."}).json()
    assert reply["actor"] == "mentor" and reply["session_id"] == sid
    assert client.post(f"/mentor/tickets/{ticket_id}/resolve").json()["status"] == "resolved"
    assert client.get(f"/sessions/{sid}/state").json()["escalated"] is False
    assert durable.flush(5)
    assert firestore.docs[durable.TICKETS][ticket_id]["status"] == "resolved"  # the change was mirrored
    assert firestore.docs[durable.TICKETS][ticket_id]["latest_code"] == "pass"  # as the whole row

    restart()
    assert [(t["id"], t["status"]) for t in client.get("/mentor/tickets").json()] == [(ticket_id, "resolved")]
    assert client.get(f"/sessions/{sid}/state").json()["escalated"] is False
    texts = [m["text"] for m in client.get(f"/mentor/tickets/{ticket_id}").json()["transcript"]]
    assert len(texts) == 5 and texts[-1] == "Look at the inner loop."
    assert [m["text"] for m in client.get(f"/sessions/{sid}/mentor-messages").json()] == ["Look at the inner loop."]


def test_resolving_a_ticket_straight_after_a_restart_changes_the_restored_row(firestore, restart) -> None:
    _, ticket_id = _seed()
    restart()
    resolved = memory.resolve_ticket(ticket_id)  # nothing has asked for this ticket yet in this process
    assert resolved is not None and resolved.status == "resolved"
    restart()
    assert [(t.id, t.status) for t in memory.list_tickets()] == [(ticket_id, "resolved")]
    assert memory.resolve_ticket("tkt_nothing") is None


# ---------- when Firestore fails ----------


def _no_client() -> FakeFirestore:
    raise RuntimeError("no credentials")


@pytest.mark.parametrize("failure", ["every call raises", "no client can be made"])
def test_when_firestore_is_down_everything_still_works_from_sqlite(firestore, restart, monkeypatch, failure: str) -> None:
    firestore.down = True
    if failure == "no client can be made":
        monkeypatch.setattr(durable, "_client", _no_client)
    client = TestClient(app)
    sid = _new(client)
    final = _send(client, sid)  # the reply arrives
    assert final["hint_level"] == 1 and final["reply"].endswith("?")

    session = memory.get_session(sid)
    assert session is not None and session.hint_level == 1
    assert [m.actor for m in memory.transcript(sid)] == ["student", "coach"]
    ticket = memory.create_ticket(session, "rule escalate.max_hint", "Ask what they have tried.")
    assert [t.id for t in memory.list_tickets()] == [ticket.id]
    assert memory.get_ticket(ticket.id).transcript == memory.transcript(sid)
    assert memory.resolve_ticket(ticket.id).status == "resolved"
    assert memory.add_message(sid, "mentor", "Try a smaller input.").actor == "mentor"

    # What SQLite does not have cannot be looked up while the copy is down. It may exist, so the
    # answer is "try again in a few seconds", never "no such thing" and never an error page.
    for ask in (lambda: memory.get_session("ses_nobody"), lambda: memory.get_ticket("tkt_nothing"),
                lambda: memory.resolve_ticket("tkt_nothing")):
        with pytest.raises(memory.MemoryUnavailable):
            ask()
    for path in ("/sessions/ses_nobody/state", "/mentor/tickets/tkt_nothing"):
        r = client.get(path)
        assert r.status_code == 503 and r.headers["retry-after"] == "5", (path, r.status_code)
    durable.reset()  # past the pause, so each read below really is tried
    for read in (lambda: durable.fetch_session(sid), lambda: durable.fetch_messages(sid),
                 lambda: durable.fetch_tickets(10), lambda: durable.fetch_ticket(ticket.id)):
        with pytest.raises(durable.MemoryUnavailable):
            read()
        durable.reset()

    assert durable.flush(5)  # the writer tried each write, failed, and moved on
    assert firestore.writes == [] and not any(firestore.docs.values())

    restart()  # nothing was mirrored, and while the copy is down that cannot be known: "try again"
    with pytest.raises(memory.MemoryUnavailable):
        memory.get_session(sid)
    assert memory.list_tickets() == []  # a list answers with what SQLite has
    assert client.get(f"/sessions/{sid}/state").status_code == 503
    assert client.post(f"/sessions/{sid}/message", json={"text": "hi", "problem_id": "two-sum"}).status_code == 503


def test_a_full_queue_drops_the_write_with_a_warning_and_never_blocks(firestore, monkeypatch, caplog) -> None:
    firestore.gate.clear()  # Firestore stalls: the writer is stuck inside its first write
    try:
        first = {"n": 1}
        durable.put(durable.SESSIONS, "first", first)
        assert firestore.writing.wait(5)
        first["n"] = 99  # put() took its own copy: later changes by the caller do not leak in
        monkeypatch.setattr(durable._queue, "maxsize", 2)
        with caplog.at_level(logging.WARNING, logger="app.memory.durable"):
            for name in ("second", "third", "dropped"):
                durable.put(durable.SESSIONS, name, {"n": 2})  # returns at once, every time
        assert "queue full; dropped state_sessions/dropped" in caplog.text
        assert durable.flush(0.05) is False  # still stalled, and flush says so
    finally:
        firestore.gate.set()
    assert durable.flush(5) is True
    assert firestore.docs[durable.SESSIONS] == {"first": {"n": 1}, "second": {"n": 2}, "third": {"n": 2}}
    assert firestore.writes == [(durable.SESSIONS, name) for name in ("first", "second", "third")]  # in order


# ---------- restoring is cheap and safe to repeat ----------


def test_restoring_twice_leaves_one_copy_of_each_row_and_writes_nothing_back(firestore, restart) -> None:
    session, ticket_id = _seed()
    sid = session.session_id
    restart()
    written, stored = list(firestore.writes), copy.deepcopy(dict(firestore.docs))
    assert len(written) == 7  # the session twice, four messages, one ticket: and nothing since

    assert memory.get_session(sid) == session
    thread = memory.transcript(sid)
    assert _rows() == {"sessions": 1, "messages": 4, "tickets": 1}

    assert memory._restore_session(sid) is True  # the same restore again
    memory.list_tickets()  # the mentor queue brings the same ticket
    assert memory.get_ticket(ticket_id) is not None
    with db.write_lock:  # lose only the session row, so the next restore meets rows that are already there
        memory._conn().execute("DELETE FROM sessions")
    assert memory.get_session(sid) == session

    assert _rows() == {"sessions": 1, "messages": 4, "tickets": 1}
    assert memory.transcript(sid) == thread
    assert durable.flush(5)
    assert firestore.writes == written and dict(firestore.docs) == stored


def test_a_restore_is_three_bounded_reads_and_an_unknown_session_is_one(firestore, restart) -> None:
    session, _ = _seed()
    restart()
    assert memory.get_session(session.session_id) == session
    assert [r[:2] for r in firestore.reads] == [
        ("get", "state_sessions"), ("query", "state_messages"), ("query", "state_tickets")]
    assert firestore.reads[0][2] == session.session_id

    del firestore.reads[:]
    assert memory.get_session("ses_nobody") is None
    assert firestore.reads == [("get", "state_sessions", "ses_nobody")]  # exactly one attempt
    client = TestClient(app)
    r = client.post("/sessions/ses_stranger/message", json={"text": "hi", "problem_id": "two-sum"})
    assert r.status_code == 404
    assert firestore.reads[1:] == [("get", "state_sessions", "ses_stranger")]

    # Every read was given a short deadline, retries included: a request is waiting on it.
    assert len(firestore.read_options) == 5
    for options in firestore.read_options:
        assert options["timeout"] == durable.READ_TIMEOUT_SECONDS
        assert options["retry"].timeout == durable.READ_TIMEOUT_SECONDS
    assert durable.flush(5) and len(firestore.writes) == 7  # and none of this wrote anything


def test_a_session_the_copy_does_not_have_is_asked_for_once_then_believed_for_a_while(firestore, restart, monkeypatch) -> None:
    """A browser holding an old session id asks for it every few seconds. Each miss is a network
    read the whole server waits on, so the answer "not there" is kept for a short time."""
    client = TestClient(app)
    for _ in range(4):
        assert client.get("/sessions/ses_gone/state").status_code == 404
    assert firestore.reads == [("get", "state_sessions", "ses_gone")]

    monkeypatch.setattr(memory, "LOOK_AGAIN_SECONDS", 0.0)  # the short time has passed
    assert memory.get_session("ses_gone") is None
    assert len(firestore.reads) == 2

    # A copy that could not be read is not a miss: it is not remembered as missing, and the
    # session is found as soon as the copy answers again.
    monkeypatch.setattr(memory, "LOOK_AGAIN_SECONDS", 15.0)
    monkeypatch.setattr(durable, "BACK_OFF_SECONDS", 0.0)
    session, _ = _seed()
    restart()
    firestore.down = True
    with pytest.raises(memory.MemoryUnavailable):
        memory.get_session(session.session_id)
    firestore.down = False
    assert memory.get_session(session.session_id) == session
    reads = len(firestore.reads)
    assert memory.get_session(session.session_id) == session
    assert len(firestore.reads) == reads  # from SQLite from now on


def test_the_mentor_queue_is_tried_again_when_its_first_read_failed(firestore, restart, monkeypatch) -> None:
    _, ticket_id = _seed()
    restart()
    firestore.down = True
    assert memory.list_tickets() == []
    firestore.down = False
    assert memory.list_tickets() == []  # not on every request: reads pause briefly after a failure
    monkeypatch.setattr(durable, "BACK_OFF_SECONDS", 0.0)  # the pause is over
    assert [t.id for t in memory.list_tickets()] == [ticket_id]
    reads = len(firestore.reads)
    assert [t.id for t in memory.list_tickets()] == [ticket_id]
    assert len(firestore.reads) == reads  # loaded: answered from SQLite from now on


# ---------- found by the review after the first deploy ----------


def test_a_transcript_that_cannot_be_read_restores_nothing_and_the_session_comes_back_whole_later(
        firestore, restart, monkeypatch) -> None:
    """A restore is all or nothing. If the transcript could not be read, writing the session alone
    would leave SQLite with a session that has no history, and nothing would ever ask again."""
    monkeypatch.setattr(durable, "BACK_OFF_SECONDS", 0.0)
    session, ticket_id = _seed()
    thread = memory.transcript(session.session_id)
    restart()
    firestore.failing_queries = {"state_messages"}
    with pytest.raises(memory.MemoryUnavailable):
        memory.get_session(session.session_id)
    assert _rows() == {"sessions": 0, "messages": 0, "tickets": 0}  # nothing half-restored

    r = TestClient(app).get(f"/sessions/{session.session_id}/state")
    assert r.status_code == 503 and r.headers["retry-after"]  # "try again", not "no such session"
    assert "try again" in r.json()["detail"].lower()

    firestore.failing_queries = set()
    assert memory.get_session(session.session_id) == session
    assert memory.transcript(session.session_id) == thread
    assert memory.get_ticket(ticket_id).transcript == thread


def test_while_the_copy_is_unreachable_no_request_waits_on_it_again_for_a_few_seconds(firestore, restart, monkeypatch) -> None:
    """One failed read pauses all recovery reads briefly: stale tabs polling different ids
    must not each hold the server for the read's whole deadline."""
    session, ticket_id = _seed()
    restart()
    firestore.down = True
    with pytest.raises(memory.MemoryUnavailable):
        memory.get_session("ses_tab_one")
    reads = len(firestore.reads)
    for ask in (lambda: memory.get_session("ses_tab_two"), lambda: memory.get_ticket("tkt_other"),
                lambda: memory.get_session(session.session_id)):
        with pytest.raises(memory.MemoryUnavailable):
            ask()
    assert len(firestore.reads) == reads  # none of them touched Firestore
    assert memory.list_tickets() == []  # a list still answers, from what SQLite has

    firestore.down = False
    monkeypatch.setattr(durable, "BACK_OFF_SECONDS", 0.0)  # the pause is over
    assert memory.get_session(session.session_id) == session
    assert [t.id for t in memory.list_tickets()] == [ticket_id]


def test_an_unknown_ticket_id_is_asked_for_once_then_believed_for_a_while(firestore, restart) -> None:
    restart()
    for _ in range(4):
        assert memory.get_ticket("tkt_nothing") is None
    assert [r for r in firestore.reads if r[0] == "get"] == [("get", "state_tickets", "tkt_nothing")]


def test_a_mentor_action_on_a_session_that_cannot_be_read_changes_nothing(firestore, restart, monkeypatch) -> None:
    monkeypatch.setattr(durable, "BACK_OFF_SECONDS", 0.0)
    session, ticket_id = _seed()
    restart()
    memory.list_tickets()  # the queue is back; the session is not yet
    firestore.failing_queries = {"state_messages"}
    with pytest.raises(memory.MemoryUnavailable):
        memory.resolve_ticket(ticket_id)
    assert memory._find_ticket(ticket_id)["status"] == "open"  # not resolved behind the mentor's back
    firestore.failing_queries = set()
    assert memory.resolve_ticket(ticket_id).status == "resolved"


def test_messages_keep_their_order_whenever_they_were_written_into_sqlite(firestore, restart) -> None:
    """A message can reach SQLite before the older conversation is restored (a mentor answering
    straight after a restart). The transcript is still oldest first."""
    session, _ = _seed()
    thread = [m.text for m in memory.transcript(session.session_id)]
    restart()
    memory._copy_in(sessions=[(session.session_id, json.dumps(session.__dict__))])  # the row, not yet the messages
    late = memory.add_message(session.session_id, "mentor", "Look at the second example.")
    memory._copy_in(messages=durable.fetch_messages(session.session_id))
    assert [m.text for m in memory.transcript(session.session_id)] == thread + [late.text]
    assert [m.text for m in memory.transcript(session.session_id, limit=2)] == thread[-1:] + [late.text]


def test_a_write_that_fails_once_is_sent_again(firestore, monkeypatch) -> None:
    monkeypatch.setattr(durable, "WRITE_RETRY_PAUSES", (0.0, 0.0))
    session = memory.create_session("learn")
    firestore.failing_writes = 1
    message = memory.add_message(session.session_id, "student", "I'm stuck")
    assert durable.flush(5)
    assert firestore.docs["state_messages"][message.id]["text"] == "I'm stuck"


def test_a_request_that_saved_something_ends_only_once_the_copy_is_sent(firestore) -> None:
    """On Cloud Run the server only surely has CPU while a request is open, so the writes of a
    request are sent before it ends, not at some later moment."""
    firestore.write_delay = 0.2
    client = TestClient(app)
    sid = _new(client)
    assert durable.pending() == 0 and sid in firestore.docs["state_sessions"]
    _send(client, sid)
    assert durable.pending() == 0
    assert len([m for m in firestore.docs["state_messages"].values() if m["session_id"] == sid]) == 2


def test_a_request_does_not_wait_on_a_copy_that_is_failing(firestore, monkeypatch) -> None:
    monkeypatch.setattr(durable, "WRITE_RETRY_PAUSES", (0.0, 0.0))
    monkeypatch.setattr(durable, "WRITE_RETRY_PAUSES", (3.0, 3.0))  # still trying that write when the next request comes
    firestore.down = True
    client = TestClient(app)
    _new(client)
    firestore.write_delay = 1.0
    started = time.monotonic()
    sid = _new(client)
    assert time.monotonic() - started < 0.5 and sid  # answered without waiting on the copy
    firestore.down = False
    firestore.write_delay = 0.0
    assert durable.flush(10)  # the retried write gets through once the copy answers
    assert len(firestore.docs["state_sessions"]) == 2


def test_when_the_copy_is_slow_only_one_request_waits_for_it(firestore, monkeypatch) -> None:
    """A write against a database that does not answer can take seconds to fail. The first
    request waits up to its limit; the ones after it do not, until the queue has emptied."""
    import app.main as main

    monkeypatch.setattr(main, "SEND_BEFORE_REPLYING_SECONDS", 0.3)
    firestore.write_delay = 1.5
    client = TestClient(app)
    started = time.monotonic()
    _new(client)
    first = time.monotonic() - started
    started = time.monotonic()
    _new(client)
    second = time.monotonic() - started
    assert 0.3 <= first < 1.0 and second < 0.2, (first, second)
    assert durable.flush(10) and durable.writing_well()  # once the queue is empty, requests wait again


def test_shutting_down_sends_what_is_still_queued(firestore) -> None:
    firestore.write_delay = 0.2
    with TestClient(app):  # runs the app's start and shutdown, as uvicorn does
        session = memory.create_session("learn")  # queued, not sent: no request is open
        assert durable.pending() >= 1
    assert durable.pending() == 0 and session.session_id in firestore.docs["state_sessions"]


@pytest.mark.parametrize(("on_cloud_run", "expected"), [(True, True), (False, False)])
def test_the_activity_logs_database_is_borrowed_only_on_cloud_run(monkeypatch, on_cloud_run, expected) -> None:
    """A laptop run that shows the live activity log must not also write test sessions into the
    live service's collections, or copy its students' chats onto the laptop."""
    monkeypatch.setenv("SENSEI_STATE_FIRESTORE_DB", "")
    monkeypatch.setenv("SENSEI_LOG_FIRESTORE_DB", "senior")
    monkeypatch.setenv("SENSEI_USE_STUBS", "0")
    if on_cloud_run:
        monkeypatch.setenv("K_SERVICE", "senior")
    else:
        monkeypatch.delenv("K_SERVICE", raising=False)
    assert durable.enabled() is expected


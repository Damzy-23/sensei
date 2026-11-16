"""Who can see what, with SENSEI_SCOPE_DATA=1.

A visitor sees the sessions their browser holds. A mentor sees every session. Nobody
else's messages, code, tickets or trace ids come back from a scoped route. The real
turn loop runs against a scripted model, so the events and tickets are genuine ones.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import auth
from app.llm import gateway
from app.llm.gateway import LLMResult
from app.main import app
from app.tracing import archive

TOTALS_KEYS = {"events", "model_calls", "tool_calls", "cost_usd"}
WEB = Path(__file__).resolve().parent.parent / "web" / "src"


def _token(name: str) -> str:
    """A token shaped like a Firebase ID token: three parts joined by dots. Only the shape is
    real. `_sign_in` decides which names verify."""
    return f"header.{name}.signature"


def _bearer(name: str) -> dict[str, str]:
    return {"authorization": f"Bearer {_token(name)}"}


MENTOR = _bearer("mentor-token")


class FrustratedStudentModel:
    """Classifies every message as frustration, so the second message opens a mentor ticket."""

    async def complete(self, *, model: str, system: str, user: str, max_tokens: int, effort: str) -> LLMResult:
        if "Classify the" in system:
            return LLMResult(json.dumps({"category": "frustrated", "confidence": 0.9, "reason": "they want to give up"}), model, 100, 20)
        return LLMResult("What is the smallest case you can solve by hand?", model, 400, 60)


def _real_loop(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SENSEI_USE_STUBS", "0")
    monkeypatch.setenv("SENSEI_DB_PATH", str(tmp_path / "sensei.db"))
    for name in ("SENSEI_AUTH_PROJECT", "SENSEI_MENTOR_EMAILS", "SENSEI_LOG_FIRESTORE_DB"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(auth, "_VERIFIED", {})
    monkeypatch.setattr(archive, "_totals", None)
    db.reset_connection()
    gateway.set_client(FrustratedStudentModel())


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    """The real loop on a fresh database, with scoping switched on."""
    monkeypatch.setenv("SENSEI_SCOPE_DATA", "1")
    _real_loop(tmp_path, monkeypatch)
    yield TestClient(app)
    gateway.set_client(None)
    db.reset_connection()


@pytest.fixture
def unscoped(tmp_path, monkeypatch) -> TestClient:
    """The same, with the switch off: how the API behaved before scoping."""
    monkeypatch.delenv("SENSEI_SCOPE_DATA", raising=False)
    _real_loop(tmp_path, monkeypatch)
    yield TestClient(app)
    gateway.set_client(None)
    db.reset_connection()


def _holding(*session_ids: str) -> dict[str, str]:
    return {"X-Senior-Sessions": ",".join(session_ids)}


def _escalated_session(client: TestClient, secret: str) -> str:
    """A session whose student ran the tests once and wrote `secret` twice. That leaves model
    calls, a tool call and one open ticket, with `secret` in the trace text and the code."""
    sid = client.post("/sessions", json={"mode": "learn"}).json()["session_id"]
    run = {"problem_id": "two-sum", "code": f"# {secret}", "passed": 1, "failed": 2, "total": 3, "failures": [], "runtime_ms": 5}
    assert client.post(f"/sessions/{sid}/runs", json=run).status_code == 200
    for _ in range(2):
        body = {"text": f"I give up. {secret}", "problem_id": "two-sum", "code": f"# {secret}"}
        assert client.post(f"/sessions/{sid}/message", json=body, headers=_holding(sid)).status_code == 200
    return sid


def _sign_in(monkeypatch, names: dict[str, dict], mentors: str = "Lead@Example.com, second@example.com") -> None:
    """Stand in for Google: only the tokens of the listed names verify, each with the claims given."""
    tokens = {_token(name): claims for name, claims in names.items()}

    def verify(token: str, request: object, audience: str | None = None) -> dict:
        if token not in tokens:
            raise ValueError("Could not verify token signature.")
        return {"user_id": f"uid-{token}", "aud": audience, "exp": time.time() + 3600, **tokens[token]}

    monkeypatch.setenv("SENSEI_AUTH_PROJECT", "example-project")
    monkeypatch.setenv("SENSEI_MENTOR_EMAILS", mentors)
    monkeypatch.setattr(auth.id_token, "verify_firebase_token", verify)


# ---------- guests ----------


def test_a_guest_holding_no_session_gets_an_empty_log_and_an_empty_queue(client: TestClient) -> None:
    _escalated_session(client, "zebra-orchid")
    body = client.get("/logs").json()
    assert body["events"] == [] and body["summary"] == [] and body["scope"] == "own"
    assert client.get("/mentor/tickets").json() == []
    assert client.get("/mentor/scope").json() == {"scope": "own"}


def test_a_guest_sees_only_their_own_sessions_events_and_tickets(client: TestClient) -> None:
    mine = _escalated_session(client, "zebra-orchid")
    theirs = _escalated_session(client, "walrus-tulip")

    log = client.get("/logs", headers=_holding(mine))
    body = log.json()
    assert body["scope"] == "own" and body["events"]
    assert {e["session_id"] for e in body["events"]} == {mine}
    assert "zebra-orchid" in log.text and "walrus-tulip" not in log.text and theirs not in log.text
    # The per-agent summary counts the visitor's own events, not the whole system's.
    assert sum(s["events"] for s in body["summary"]) == len(body["events"]) < body["totals_all"]["events"]

    tickets = client.get("/mentor/tickets", headers=_holding(mine)).json()
    assert [t["session_id"] for t in tickets] == [mine]
    detail = client.get(f"/mentor/tickets/{tickets[0]['id']}", headers=_holding(mine))
    assert detail.status_code == 200 and "zebra-orchid" in detail.text and "walrus-tulip" not in detail.text


def test_two_tabs_of_one_browser_hold_both_of_its_sessions(client: TestClient) -> None:
    first, second = _escalated_session(client, "zebra-orchid"), _escalated_session(client, "walrus-tulip")
    body = client.get("/logs", headers=_holding(second, first)).json()
    assert {e["session_id"] for e in body["events"]} == {first, second}
    assert len(client.get("/mentor/tickets", headers=_holding(second, first)).json()) == 2


def test_another_sessions_ticket_answers_404_and_is_left_untouched(client: TestClient) -> None:
    mine, theirs = _escalated_session(client, "zebra-orchid"), _escalated_session(client, "walrus-tulip")
    ticket_id = client.get("/mentor/tickets", headers=_holding(theirs)).json()[0]["id"]
    missing = client.get("/mentor/tickets/tkt_000000000000", headers=_holding(mine))

    for headers in (_holding(mine), {}):
        for response in (
            client.get(f"/mentor/tickets/{ticket_id}", headers=headers),
            client.post(f"/mentor/tickets/{ticket_id}/reply", json={"text": "Read line 5."}, headers=headers),
            client.post(f"/mentor/tickets/{ticket_id}/resolve", headers=headers),
        ):
            # Exactly what an id that does not exist answers, so ticket ids cannot be probed.
            assert response.status_code == 404 and response.json() == missing.json()

    detail = client.get(f"/mentor/tickets/{ticket_id}", headers=_holding(theirs)).json()
    assert detail["status"] == "open" and all(m["actor"] != "mentor" for m in detail["transcript"])
    assert client.get(f"/sessions/{theirs}/mentor-messages").json() == []
    assert client.get(f"/sessions/{theirs}/state").json()["escalated"] is True


def test_a_visitor_can_answer_and_resolve_a_ticket_of_their_own_session(client: TestClient) -> None:
    mine = _escalated_session(client, "zebra-orchid")
    ticket_id = client.get("/mentor/tickets", headers=_holding(mine)).json()[0]["id"]
    reply = client.post(f"/mentor/tickets/{ticket_id}/reply", json={"text": "Read line 5."}, headers=_holding(mine))
    assert reply.status_code == 200 and reply.json()["actor"] == "mentor"
    assert client.post(f"/mentor/tickets/{ticket_id}/resolve", headers=_holding(mine)).json()["status"] == "resolved"
    assert client.get(f"/sessions/{mine}/state").json()["escalated"] is False


def test_the_session_filter_cannot_widen_access(client: TestClient) -> None:
    mine, theirs = _escalated_session(client, "zebra-orchid"), _escalated_session(client, "walrus-tulip")
    for headers in (_holding(mine), {}):
        for params in ({"session_id": theirs}, {"session_id": theirs, "type": "llm"}, {"session_id": theirs, "limit": 1000}):
            response = client.get("/logs", params=params, headers=headers)
            assert response.json()["events"] == [] and "walrus-tulip" not in response.text
    narrowed = client.get("/logs", params={"session_id": mine}, headers=_holding(mine, theirs)).json()["events"]
    assert narrowed and {e["session_id"] for e in narrowed} == {mine}


def test_no_scoped_route_gives_out_another_sessions_trace_id(client: TestClient) -> None:
    mine, theirs = _escalated_session(client, "zebra-orchid"), _escalated_session(client, "walrus-tulip")
    their_view = client.get("/logs", headers=_holding(theirs)).json()["events"]
    their_ids = {e["trace_id"] for e in their_view} | {e["event_id"] for e in their_view} | {theirs}
    their_ids.add(client.get("/mentor/tickets", headers=_holding(theirs)).json()[0]["id"])
    assert len(their_ids) > 3

    my_ticket = client.get("/mentor/tickets", headers=_holding(mine)).json()[0]["id"]
    seen = "".join(client.get(path, headers=_holding(mine)).text for path in (
        "/logs", "/logs?limit=1000", f"/logs?session_id={theirs}", "/mentor/tickets", f"/mentor/tickets/{my_ticket}", "/mentor/scope"))
    assert not [i for i in their_ids if i in seen]


def test_only_well_formed_session_ids_are_taken_from_the_header() -> None:
    real, sample = "ses_0123456789ab", "ses_demo_0001"
    junk = "cv, offline, ses_, ses_0123456789AB, ses_0123456789abc, ses_0123456789ab' OR 1=1, *, ,"
    assert auth.parse_sessions(f"{junk}, {real} ,{sample},{real}") == (real, sample)
    assert auth.parse_sessions(None) == () and auth.parse_sessions("") == ()
    many = [f"ses_{i:012x}" for i in range(40)]
    assert auth.parse_sessions(",".join(many)) == tuple(many[:30])


def test_a_page_on_another_origin_may_send_the_sessions_header(client: TestClient) -> None:
    # The web app is served from another origin than the API, so the browser asks first.
    asked = {"origin": "https://example.web.app", "access-control-request-method": "GET",
             "access-control-request-headers": "authorization,content-type,x-senior-sessions"}
    preflight = client.options("/logs", headers=asked)
    assert preflight.status_code == 200
    assert "x-senior-sessions" in preflight.headers["access-control-allow-headers"].lower()


def test_a_shared_trace_bucket_cannot_be_claimed(client: TestClient) -> None:
    # CV studio traces go to one shared session, "cv". Naming it in the header must not open it.
    assert client.post("/cv/research", json={"role_title": "Backend engineer", "company": ""}).status_code == 200
    assert client.get("/logs", headers={"X-Senior-Sessions": "cv"}).json()["events"] == []


# ---------- mentors ----------


def test_a_mentor_sees_every_session(client: TestClient, monkeypatch) -> None:
    first, second = _escalated_session(client, "zebra-orchid"), _escalated_session(client, "walrus-tulip")
    _sign_in(monkeypatch, {"mentor-token": {"email": "lead@example.com", "email_verified": True}})

    log = client.get("/logs", headers=MENTOR)
    body = log.json()
    assert body["scope"] == "all" and {e["session_id"] for e in body["events"]} == {first, second}
    assert "zebra-orchid" in log.text and "walrus-tulip" in log.text
    assert client.get("/mentor/scope", headers=MENTOR).json() == {"scope": "all"}

    tickets = client.get("/mentor/tickets", headers=MENTOR).json()
    assert {t["session_id"] for t in tickets} == {first, second}
    ticket_id = next(t["id"] for t in tickets if t["session_id"] == second)
    assert client.get(f"/mentor/tickets/{ticket_id}", headers=MENTOR).status_code == 200
    assert client.post(f"/mentor/tickets/{ticket_id}/reply", json={"text": "Read line 5."}, headers=MENTOR).status_code == 200
    assert client.post(f"/mentor/tickets/{ticket_id}/resolve", headers=MENTOR).json()["status"] == "resolved"
    assert [m["text"] for m in client.get(f"/sessions/{second}/mentor-messages").json()] == ["Read line 5."]


def test_the_token_can_come_in_the_query_string(client: TestClient, monkeypatch) -> None:
    _escalated_session(client, "zebra-orchid")
    _sign_in(monkeypatch, {"mentor-token": {"email": "lead@example.com", "email_verified": True}})
    assert client.get("/logs", params={"token": _token("mentor-token")}).json()["scope"] == "all"


def test_an_unverified_email_on_the_list_is_not_a_mentor(client: TestClient, monkeypatch) -> None:
    mine = _escalated_session(client, "zebra-orchid")
    _escalated_session(client, "walrus-tulip")
    _sign_in(monkeypatch, {
        "unverified": {"email": "lead@example.com", "email_verified": False},
        "no-flag": {"email": "lead@example.com"},
        "stranger": {"email": "someone@elsewhere.org", "email_verified": True},
    })
    for token in ("unverified", "no-flag", "stranger"):
        headers = _bearer(token)
        body = client.get("/logs", headers=headers).json()
        assert body["scope"] == "own" and body["events"] == []
        assert client.get("/mentor/tickets", headers=headers).json() == []
    # Signed in, but not a mentor: still sees the sessions this browser holds, like a guest.
    own = client.get("/logs", headers={**_bearer("stranger"), **_holding(mine)}).json()["events"]
    assert own and {e["session_id"] for e in own} == {mine}


def test_no_mentor_list_means_no_mentors(client: TestClient, monkeypatch) -> None:
    _escalated_session(client, "zebra-orchid")
    _sign_in(monkeypatch, {"mentor-token": {"email": "lead@example.com", "email_verified": True}}, mentors="")
    assert client.get("/logs", headers=MENTOR).json()["scope"] == "own"


def test_an_invalid_token_is_refused_but_a_guest_is_not(client: TestClient, monkeypatch) -> None:
    _sign_in(monkeypatch, {"mentor-token": {"email": "lead@example.com", "email_verified": True}})
    for path in ("/logs", "/mentor/tickets", "/tracks"):
        assert client.get(path, headers=_bearer("forged")).status_code == 401
        assert client.get(path, params={"token": _token("forged")}).status_code == 401
        assert client.get(path).status_code == 200  # no token: a guest, not an error
    # A token that had verified is refused once it has expired.
    expired = {"email": "lead@example.com", "email_verified": True, "exp": time.time() - 1}
    _sign_in(monkeypatch, {"old-token": expired})
    assert client.get("/logs", headers=_bearer("old-token")).json()["scope"] == "all"
    monkeypatch.setattr(auth.id_token, "verify_firebase_token", lambda *a, **k: (_ for _ in ()).throw(ValueError("Token expired")))
    assert client.get("/logs", headers=_bearer("old-token")).status_code == 401


def test_a_token_is_ignored_when_no_project_can_verify_it(client: TestClient) -> None:
    mine = _escalated_session(client, "zebra-orchid")
    body = client.get("/logs", headers={"authorization": "Bearer anything", **_holding(mine)}).json()
    assert body["scope"] == "own" and {e["session_id"] for e in body["events"]} == {mine}


def test_a_bad_token_does_not_send_the_server_to_google_each_time(client: TestClient, monkeypatch) -> None:
    # google-auth fetches the signing certificates before it reads a token. Anyone can send a
    # token, so that fetch must not happen once for every bad one.
    fetched: list[str] = []

    def fetch(url: str, method: str = "GET", **kwargs: object) -> SimpleNamespace:
        fetched.append(url)
        return SimpleNamespace(status=200, data=json.dumps({"key-1": "not a certificate"}).encode())

    keeper = auth._KeepsCertificates(fetch)
    monkeypatch.setenv("SENSEI_AUTH_PROJECT", "example-project")
    monkeypatch.setattr(auth, "_transport", lambda: keeper)

    # Not shaped like a token at all: refused without asking for anything.
    for junk in ("forged", "two.parts", "four.parts.in.all", "empty..part", "a space.in.it", "x" * 5000):
        assert client.get("/logs", headers={"authorization": f"Bearer {junk}"}).status_code == 401
        assert client.get("/logs", params={"token": junk}).status_code == 401
    assert fetched == []

    # Shaped like one, and forged: the real verifier runs, on certificates fetched once.
    for n in range(25):
        assert client.get("/logs", headers=_bearer(f"forged-{n}")).status_code == 401
    assert client.get("/logs", headers=_bearer("forged-0")).status_code == 401
    assert len(fetched) == 1
    assert client.get("/logs").status_code == 200 and len(fetched) == 1  # a guest costs no fetch

    # Kept, not kept for ever: the certificates are fetched again once their time is up.
    brief = auth._KeepsCertificates(fetch, keep_s=0)
    monkeypatch.setattr(auth, "_transport", lambda: brief)
    for n in range(2):
        assert client.get("/logs", headers=_bearer(f"forged-{n}")).status_code == 401
    assert len(fetched) == 3


def test_a_failed_certificate_fetch_is_neither_repeated_at_once_nor_kept_for_long() -> None:
    asked: list[dict] = []

    def fetch(url: str, method: str = "GET", **kwargs: object) -> SimpleNamespace:
        asked.append(kwargs)
        if len(asked) == 2:
            raise ConnectionError("no answer from Google")
        return SimpleNamespace(status=503 if len(asked) == 1 else 200, data=b"{}")

    # While Google is failing, the callers are told so without each of them asking it again.
    patient = auth._KeepsCertificates(fetch)
    assert [patient("https://certs.example").status for _ in range(3)] == [503, 503, 503] and len(asked) == 1
    assert asked[0]["timeout"] == auth.CERTS_TIMEOUT_S

    # Once the pause is over it is asked again, and only a good answer is kept.
    asked.clear()
    keeper = auth._KeepsCertificates(fetch, retry_s=0)
    assert keeper("https://certs.example").status == 503
    with pytest.raises(ConnectionError):
        keeper("https://certs.example")
    assert [keeper("https://certs.example").status for _ in range(3)] == [200, 200, 200] and len(asked) == 3


# ---------- the whole system's totals ----------


def test_totals_cover_every_session_and_carry_no_text(client: TestClient, monkeypatch) -> None:
    mine = _escalated_session(client, "zebra-orchid")
    _escalated_session(client, "walrus-tulip")
    guest = client.get("/logs", headers=_holding(mine)).json()
    nobody = client.get("/logs").json()
    _sign_in(monkeypatch, {"mentor-token": {"email": "lead@example.com", "email_verified": True}})
    everything = client.get("/logs", params={"limit": 1000}, headers=MENTOR).json()

    totals = guest["totals_all"]
    assert set(totals) == TOTALS_KEYS and nobody["totals_all"] == totals == everything["totals_all"]
    assert all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in totals.values())
    assert totals["events"] == len(everything["events"]) > len(guest["events"])
    assert totals["model_calls"] == sum(s["model_calls"] for s in everything["summary"]) > 0
    assert totals["tool_calls"] == sum(s["tool_calls"] for s in everything["summary"]) > 0
    assert totals["cost_usd"] == pytest.approx(sum(s["cost_usd"] for s in everything["summary"])) and totals["cost_usd"] > 0


def test_the_log_is_still_served_when_the_totals_cannot_be_read(client: TestClient, monkeypatch) -> None:
    mine = _escalated_session(client, "zebra-orchid")
    monkeypatch.setattr("app.tracing.store.totals", lambda: (_ for _ in ()).throw(RuntimeError("aggregation unavailable")))
    body = client.get("/logs", headers=_holding(mine)).json()
    assert body["totals_all"] is None and body["events"]


# ---------- the Firestore archive ----------


class _Aggregation:
    def __init__(self, docs: list[dict], parts: list[tuple[str, str | None, str]]) -> None:
        self.docs, self.parts = docs, parts

    def sum(self, field: str, alias: str) -> "_Aggregation":
        return _Aggregation(self.docs, [*self.parts, ("sum", field, alias)])

    def get(self) -> list[list[SimpleNamespace]]:
        value = {"count": lambda f: len(self.docs), "sum": lambda f: sum(d[f] or 0 for d in self.docs)}
        return [[SimpleNamespace(alias=alias, value=value[kind](field)) for kind, field, alias in self.parts]]


class _Query:
    """As much of a Firestore collection as the archive uses, over a list of documents."""

    def __init__(self, docs: list[dict], asked: list[tuple]) -> None:
        self.docs, self.asked, self.cap = docs, asked, None

    def collection(self, name: str) -> "_Query":
        return self

    def where(self, *, filter) -> "_Query":  # noqa: A002
        self.asked.append((filter.field_path, filter.op_string, filter.value))
        test = {"==": lambda v: v == filter.value, "in": lambda v: v in filter.value}[filter.op_string]
        return _Query([d for d in self.docs if test(d[filter.field_path])], self.asked)

    def limit(self, count: int) -> "_Query":
        self.cap = count
        return self

    def stream(self):
        return (SimpleNamespace(to_dict=lambda d=d: d) for d in self.docs[: self.cap])

    def count(self, alias: str) -> _Aggregation:
        return _Aggregation(self.docs, [("count", None, alias)])


def test_with_the_archive_on_a_guest_is_read_only_their_own_sessions(client: TestClient, monkeypatch) -> None:
    mine = _escalated_session(client, "zebra-orchid")
    _escalated_session(client, "walrus-tulip")
    _sign_in(monkeypatch, {"mentor-token": {"email": "lead@example.com", "email_verified": True}})
    stored = client.get("/logs", params={"limit": 1000}, headers=MENTOR).json()
    sqlite_view = client.get("/logs", headers=_holding(mine)).json()

    asked: list[tuple] = []
    documents = sorted(stored["events"], key=lambda e: e["event_id"])  # Firestore's order: by document id
    monkeypatch.setattr(archive, "enabled", lambda: True)
    monkeypatch.setattr(archive, "_client", lambda: _Query(documents, asked))

    body = client.get("/logs", headers=_holding(mine)).json()
    assert body["durable"] is True and body["scope"] == "own"
    assert ("session_id", "in", [mine]) in asked  # the filter runs in Firestore, not after loading everyone's events
    assert {e["event_id"] for e in body["events"]} == {e["event_id"] for e in sqlite_view["events"]}
    stamps = [(e["ts"], e["seq"]) for e in body["events"]]
    assert stamps == sorted(stamps, reverse=True)  # newest first, whatever order Firestore returned
    assert body["totals_all"] == stored["totals_all"]
    assert client.get("/logs").json()["events"] == []


# ---------- stub mode, and the switch off ----------


def test_stub_mode_scopes_the_sample_data_too(monkeypatch) -> None:
    monkeypatch.setenv("SENSEI_SCOPE_DATA", "1")
    monkeypatch.delenv("SENSEI_AUTH_PROJECT", raising=False)
    client = TestClient(app)
    mine = client.post("/sessions").json()["session_id"]
    other = client.post("/sessions").json()["session_id"]

    nobody = client.get("/logs").json()
    assert nobody["events"] == [] and nobody["scope"] == "own" and set(nobody["totals_all"]) == TOTALS_KEYS
    assert client.get("/mentor/tickets").json() == []
    assert client.get("/mentor/tickets/tkt_0001").status_code == 404

    own = client.get("/logs", headers=_holding(mine)).json()
    assert own["events"] and {e["session_id"] for e in own["events"]} == {mine}
    assert own["totals_all"]["events"] > len(own["events"])
    both = client.get("/logs", headers=_holding(mine, other)).json()["events"]
    assert len({e["event_id"] for e in both}) == len(both) == 2 * len(own["events"])

    # The sample sessions' fixed ids count as held when the browser sends them.
    sample = client.get("/logs", headers=_holding("ses_demo_0001")).json()["events"]
    assert sample and {e["session_id"] for e in sample} == {"ses_demo_0001"}
    assert [t["id"] for t in client.get("/mentor/tickets", headers=_holding("ses_demo_0001")).json()] == ["tkt_0001"]
    assert client.get("/mentor/tickets/tkt_0002", headers=_holding("ses_demo_0001")).status_code == 404
    assert client.post("/mentor/tickets/tkt_0002/resolve", headers=_holding("ses_demo_0001")).status_code == 404
    assert client.get("/mentor/tickets/tkt_0002", headers=_holding("ses_demo_0002")).json()["status"] == "open"


def test_with_the_switch_off_everyone_sees_everything_as_before(unscoped: TestClient) -> None:
    first, second = _escalated_session(unscoped, "zebra-orchid"), _escalated_session(unscoped, "walrus-tulip")
    body = unscoped.get("/logs").json()
    assert body["scope"] == "all" and {e["session_id"] for e in body["events"]} == {first, second}
    assert set(body["totals_all"]) == TOTALS_KEYS
    assert unscoped.get("/mentor/scope").json() == {"scope": "all"}

    tickets = unscoped.get("/mentor/tickets").json()
    assert {t["session_id"] for t in tickets} == {first, second}
    ticket_id = tickets[0]["id"]
    assert unscoped.get(f"/mentor/tickets/{ticket_id}").status_code == 200
    assert unscoped.post(f"/mentor/tickets/{ticket_id}/reply", json={"text": "Read line 5."}).status_code == 200
    assert unscoped.post(f"/mentor/tickets/{ticket_id}/resolve").json()["status"] == "resolved"


def test_with_the_switch_off_an_auth_project_still_means_everyone_signs_in(unscoped: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("SENSEI_AUTH_PROJECT", "example-project")
    assert unscoped.get("/logs").status_code == 401
    assert unscoped.get("/mentor/tickets").status_code == 401


# ---------- the screens ----------


def test_no_screen_prints_a_whole_session_or_trace_id() -> None:
    # A session id is the key to its session, and GET /traces/{trace_id} answers with the
    # session id. Whoever can see a screen (a projector, a screen share, a photo) must not be
    # able to read either one off it, so a screen shows idTag(id): its last four characters.
    # This reads the pages as written. Two ways of putting an id on screen are refused:
    # an id in text ({ticket.session_id}, or `trace ${trace_id}` in a message), and an event
    # dumped as JSON without going through printable(), which tags its ids.
    in_text = re.compile(r"(?<!=)\{\s*[\w.?]*(?:session_id|trace_id|sessionId|traceId)\s*\}(?!\s*=)")
    raw_dump = re.compile(r"\{\s*JSON\.stringify\((?!printable\()")
    pages = sorted(WEB.rglob("*.tsx"))
    assert len(pages) >= 10  # guards against passing because nothing was read
    offenders = [
        f"{page.relative_to(WEB)}:{number}: {line.strip()}"
        for page in pages
        for number, line in enumerate(page.read_text().splitlines(), 1)
        if in_text.search(line) or raw_dump.search(line)
    ]
    assert offenders == [], "a whole id is printed; show idTag(id) or printable(event) instead:\n" + "\n".join(offenders)
    # The check does catch what it is for.
    assert in_text.search("<span>{detail.session_id}</span>") and in_text.search("session {e.session_id} · trace {e.trace_id}")
    assert in_text.search("` (trace ${inner.trace_id})`") and raw_dump.search("<pre>{JSON.stringify(selected, null, 2)}</pre>")
    assert not in_text.search("<Row key={e.trace_id} sessionId={sessionId} />") and not in_text.search("const { sessionId } = useApp();")
    assert not in_text.search("session {idTag(e.session_id)}") and not raw_dump.search("{JSON.stringify(printable(selected), null, 2)}")

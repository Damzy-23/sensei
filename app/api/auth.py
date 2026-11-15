"""Who is calling, and which sessions they may see.

A visitor needs no account. Every request is answered for a `Viewer`: a guest, or a
signed-in user whose Firebase ID token was verified. The token comes in the
Authorization header, or in a `token` query parameter for EventSource, which cannot
send headers. It can only be verified when SENSEI_AUTH_PROJECT names the Firebase project.

What a viewer may read is decided by the sessions they hold. A session id is an
unguessable capability (`ses_` + 12 hex digits): the browser remembers the ids of the
sessions it started and sends them in the `X-Senior-Sessions` header. Mentors, the
signed-in users whose verified email is listed in SENSEI_MENTOR_EMAILS, see everything.

The scoping is enforced when SENSEI_SCOPE_DATA=1. Without it the API behaves as it did
before scoping existed: every caller sees every session, and a set SENSEI_AUTH_PROJECT
means every call needs a sign-in.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache

from fastapi import HTTPException, Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

SESSIONS_HEADER = "x-senior-sessions"
MAX_SESSIONS = 30  # also the most values Firestore takes in one `in` filter
# Real ids, and the fixed ids of the sample sessions in app/stubs.py. Anything else is
# dropped, so shared trace buckets such as "cv" and "offline" can never be claimed.
_SESSION_ID = re.compile(r"ses_(?:[0-9a-f]{12}|demo_\d{4})")

# Verified tokens, kept until they expire: checking one costs a request to Google for its
# signing keys, and a signed-in page sends the same token every few seconds.
_VERIFIED: dict[tuple[str, str], dict] = {}
_VERIFIED_MAX = 512


@dataclass(frozen=True)
class Viewer:
    """The caller of one request."""

    uid: str | None = None  # None for a guest
    email: str | None = None
    email_verified: bool = False
    is_mentor: bool = False
    sessions: tuple[str, ...] = ()  # the validated ids from X-Senior-Sessions

    @property
    def sees_all(self) -> bool:
        return self.is_mentor or not scope_enforced()

    def can_see(self, session_id: str) -> bool:
        return self.sees_all or session_id in self.sessions


@lru_cache(maxsize=1)
def _transport() -> google_requests.Request:
    return google_requests.Request()


def auth_project() -> str | None:
    return os.getenv("SENSEI_AUTH_PROJECT") or None


def scope_enforced() -> bool:
    return os.getenv("SENSEI_SCOPE_DATA") == "1"


def mentor_emails() -> frozenset[str]:
    return frozenset(e.strip().lower() for e in os.getenv("SENSEI_MENTOR_EMAILS", "").split(",") if e.strip())


def parse_sessions(header: str | None) -> tuple[str, ...]:
    """The well-formed session ids in the header, in order, without repeats. Junk is ignored."""
    found: list[str] = []
    for part in (header or "").split(","):
        session_id = part.strip()
        if _SESSION_ID.fullmatch(session_id) and session_id not in found:
            found.append(session_id)
            if len(found) == MAX_SESSIONS:
                break
    return tuple(found)


def verify_token(token: str, project: str) -> dict:
    """The claims of a valid Firebase ID token for this project. Raises if it is not one."""
    cached = _VERIFIED.get((project, token))
    if cached is not None and cached.get("exp", 0) > time.time():
        return cached
    claims = id_token.verify_firebase_token(token, _transport(), audience=project)
    if not claims:
        raise ValueError("the token carries no claims")
    if len(_VERIFIED) >= _VERIFIED_MAX:
        _VERIFIED.clear()
    _VERIFIED[(project, token)] = claims
    return claims


def current_viewer(request: Request) -> Viewer:
    """FastAPI dependency: the viewer for this request. While scoping is on, a guest is never
    refused for being a guest. A token that fails verification is always refused; with no
    project to verify it against, a token is ignored and the caller is a guest."""
    project = auth_project()
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token")
    sessions = parse_sessions(request.headers.get(SESSIONS_HEADER))

    if not token or not project:
        if project and not scope_enforced():  # the sign-in wall from before scoping
            raise HTTPException(status_code=401, detail="Sign in to use Senior.")
        return Viewer(sessions=sessions)
    try:
        claims = verify_token(token, project)
    except Exception as exc:  # expired, wrong project, bad signature
        raise HTTPException(status_code=401, detail="Your sign-in has expired. Sign in again.") from exc

    email = claims.get("email") or None
    verified = claims.get("email_verified") is True
    return Viewer(
        uid=claims.get("user_id") or claims.get("sub"),
        email=email,
        email_verified=verified,
        is_mentor=bool(email) and verified and email.lower() in mentor_emails(),
        sessions=sessions,
    )

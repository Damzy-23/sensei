"""Sign-in: every API call carries a Firebase ID token (Google sign-in).

Off unless SENSEI_AUTH_PROJECT names the Firebase project, so local runs and the
tests need no account. The token comes in the Authorization header, or in a
`token` query parameter for EventSource, which cannot send headers.
"""

from __future__ import annotations

import os
from functools import lru_cache

from fastapi import HTTPException, Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token


@lru_cache(maxsize=1)
def _transport() -> google_requests.Request:
    return google_requests.Request()


def auth_project() -> str | None:
    return os.getenv("SENSEI_AUTH_PROJECT") or None


def require_user(request: Request) -> dict | None:
    project = auth_project()
    if not project:
        return None
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Sign in to use Senior.")
    try:
        claims = id_token.verify_firebase_token(token, _transport(), audience=project)
    except Exception as exc:  # expired, wrong project, bad signature
        raise HTTPException(status_code=401, detail="Your sign-in has expired. Sign in again.") from exc
    if not claims:
        raise HTTPException(status_code=401, detail="Sign in to use Senior.")
    request.state.user = claims
    return claims

"""Log hygiene: redact anything that looks like a key, then truncate to 500 characters.

Redaction runs before truncation, so a secret cut in half cannot leak.
"""

from __future__ import annotations

import os
import re

MAX_CHARS = 500
REDACTED = "[REDACTED]"

# Env vars whose literal values must never reach a log.
_SECRET_ENV_VARS = ("ANTHROPIC_API_KEY", "HINT_TUNED_API_KEY")

_ANTHROPIC_KEY = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")
_GENERIC_KEY = re.compile(r"sk-[A-Za-z0-9_\-]{16,}")
_KEYED_SECRET = re.compile(r"(?i)(api[_-]?key|secret|token|password)(\"?\s*[:=]\s*\"?)([^\s\"',}]+)")


def redact(text: str) -> str:
    out = text
    for var in _SECRET_ENV_VARS:
        value = os.getenv(var)
        if value and len(value) >= 8:
            out = out.replace(value, REDACTED)
    out = _ANTHROPIC_KEY.sub(REDACTED, out)
    out = _GENERIC_KEY.sub(REDACTED, out)
    out = _KEYED_SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", out)
    return out


def clip(text: str, limit: int = MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def sanitize(text: str | None) -> str | None:
    """Redact, then truncate. None passes through."""
    if text is None:
        return None
    return clip(redact(text))

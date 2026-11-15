"""Server-sent events framing shared by every streaming route.

Each message is `event: <name>` + `data: <json>` + a blank line.
Event names: `trace` (one per TraceEvent), `final` (FinalEvent), `drawing` (Drawing), `error`, `end`.
"""

from __future__ import annotations

import json

from pydantic import BaseModel


def sse(event: str, data: BaseModel | dict) -> str:
    payload = data.model_dump_json() if isinstance(data, BaseModel) else json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"

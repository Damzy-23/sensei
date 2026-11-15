"""Voices by coach personality.

The browser picks a personality by name; the server maps it to a voice here, so a caller can
never ask for an arbitrary voice. Mirrors web/src/agent/personas.json: a test keeps the two equal.
"""

from __future__ import annotations

VOICES: dict[str, str] = {
    "drill": "SOYHLrjzK2X1ezoPC6cr",
    "mentor": "Xb7hH8MSUJpSbSDYk0k2",
    "peer": "iP95p4xoKVk53GoZ742B",
}
DEFAULT = "mentor"

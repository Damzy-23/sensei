"""Create (or update) the ElevenLabs voice agent from the repository's own definitions.

The agent's role comes from app/prompts/voice_guide.md and its tools from
web/src/agent/page-tools.json, so the provider's dashboard is never the source of truth.

    .venv/bin/python scripts/create_voice_agent.py            # create, prints the agent id
    ELEVENLABS_AGENT_ID=... .venv/bin/python scripts/create_voice_agent.py   # update in place

Needs ELEVENLABS_API_KEY in the environment or .env. Put the printed id in .env as ELEVENLABS_AGENT_ID.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.elevenlabs.io/v1/convai/agents"
ALLOWED_HOSTS = [
    "senior-coach-ai.web.app", "senior-coach-ai.firebaseapp.com",
    "senior-40946072816.europe-west2.run.app", "localhost:5173", "localhost:8000",
]
FIRST_MESSAGE = "Hello. Before we begin, what should I call you?"


def tools() -> list[dict]:
    spec = json.loads((ROOT / "web/src/agent/page-tools.json").read_text(encoding="utf-8"))
    out = []
    for name, tool in spec.items():
        properties = tool["parameters"]
        out.append({
            "type": "client",
            "name": name,
            "description": tool["description"],
            "expects_response": True,
            # press, type_into and pick_option may wait up to 20 s for the student to click Allow.
            "response_timeout_secs": 60 if name == "ask_coach" else 30 if name in ("press", "type_into", "pick_option") else 20,
            # No spoken filler before an action ("let me take a look"): the student asked for less talk.
            "pre_tool_speech": "off",
            "force_pre_tool_speech": False,
            "parameters": {"type": "object", "properties": properties, "required": list(properties)},
        })
    return out


def main() -> int:
    load_dotenv(ROOT / ".env")
    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not key:
        print("ELEVENLABS_API_KEY is not set", file=sys.stderr)
        return 1
    body = {
        "name": "Senior voice guide",
        # Signed URLs only: a session must be started by our server, and only from these origins.
        "platform_settings": {
            "auth": {"enable_auth": True, "allowlist": [{"hostname": h} for h in ALLOWED_HOSTS]},
            # The browser may choose the voice for a personality, and nothing else.
            "overrides": {"conversation_config_override": {"tts": {"voice_id": True}}},
        },
        "conversation_config": {
            # Wait for the student: 30 s of silence before the coach may speak again (the default is 7),
            # and be patient about deciding they have finished a sentence.
            "turn": {"turn_timeout": 30.0, "turn_eagerness": "patient"},
            "agent": {
                "first_message": "{{first_line}}",
                "dynamic_variables": {"dynamic_variable_placeholders": {
                    "user_name": "unknown", "first_line": FIRST_MESSAGE,
                    "persona_style": "A calm, clear senior engineer.",
                }},
                "language": "en",
                "prompt": {"prompt": (ROOT / "app/prompts/voice_guide.md").read_text(encoding="utf-8"), "tools": tools()},
            }
        },
    }
    agent_id = os.getenv("ELEVENLABS_AGENT_ID", "").strip()
    with httpx.Client(timeout=30, headers={"xi-api-key": key}) as http:
        response = http.patch(f"{API}/{agent_id}", json=body) if agent_id else http.post(f"{API}/create", json=body)
        if response.status_code >= 400:
            print(f"ElevenLabs refused ({response.status_code}): {response.text[:800]}", file=sys.stderr)
            return 1
        agent_id = response.json().get("agent_id", agent_id)
        detail = http.get(f"{API}/{agent_id}").json()
    prompt = detail.get("conversation_config", {}).get("agent", {}).get("prompt", {})
    print(f"agent_id={agent_id}")
    print(f"llm={prompt.get('llm')} tools={[t.get('name') for t in prompt.get('tools', [])]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

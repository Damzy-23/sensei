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
ALLOWED_HOSTS = ["senior-coach-1115-29b5.web.app", "senior-coach-1115-29b5.firebaseapp.com", "localhost:5173"]
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
            "response_timeout_secs": 60 if name == "ask_coach" else 20,
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

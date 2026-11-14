"""Runtime settings, read from the environment (a local .env is loaded if present)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    db_path: Path
    demo_mode: bool
    hint_model: str  # "base" | "tuned"
    use_stubs: bool  # Phase 1: serve stub data instead of the real orchestrator


def get_settings() -> Settings:
    hint_model = os.getenv("HINT_MODEL", "base").strip().lower()
    if hint_model not in {"base", "tuned"}:
        raise ValueError(f"HINT_MODEL must be 'base' or 'tuned', got {hint_model!r}")
    return Settings(
        db_path=Path(os.getenv("SENSEI_DB_PATH", str(ROOT / "data" / "sensei.db"))),
        demo_mode=os.getenv("DEMO_MODE", "0") == "1",
        hint_model=hint_model,
        use_stubs=os.getenv("SENSEI_USE_STUBS", "1") == "1",
    )

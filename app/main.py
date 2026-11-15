"""Senior FastAPI app: builds the application and mounts the routers in app/api/.

Phase 1: every endpoint from docs/API.md, served from stubs. Architecture and
layering rules: docs/ARCHITECTURE.md.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import eval as eval_routes
from app.api import mentor, problems, sessions, traces, tracks

app = FastAPI(title="Senior API", version="0.1.0")

# Open CORS for development (hackathon scope).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (sessions, problems, tracks, traces, mentor, eval_routes):
    app.include_router(module.router)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# In a deployed build, serve the web app from the same origin. Mounted last so
# every API route above wins.
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")

"""Senior FastAPI app: builds the application and mounts the routers in app/api/.

Phase 1: every endpoint from docs/API.md, served from stubs. Architecture and
layering rules: docs/ARCHITECTURE.md.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import eval as eval_routes
from app.api import cv, mentor, problems, sessions, traces, tracks, voice

app = FastAPI(title="Senior API", version="0.1.0")

# Open CORS for development (hackathon scope).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (sessions, problems, tracks, traces, mentor, voice, cv, eval_routes):
    app.include_router(module.router)

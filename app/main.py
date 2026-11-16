"""Senior FastAPI app: builds the application and mounts the routers in app/api/.

Phase 1: every endpoint from docs/API.md, served from stubs. Architecture and
layering rules: docs/ARCHITECTURE.md.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api import eval as eval_routes
from app.api.auth import current_viewer
from app.api import cv, logs, mentor, problems, profile, sessions, traces, tracks, voice
from app.memory import durable
from app.memory.repository import MemoryUnavailable

log = logging.getLogger(__name__)
SEND_BEFORE_REPLYING_SECONDS = 2.0  # the longest a request is held open while its writes are sent
SHUTDOWN_FLUSH_SECONDS = 4.0  # with uvicorn's 4 s graceful shutdown, inside Cloud Run's 10 s


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    # uvicorn runs this inside its graceful shutdown, before it re-raises SIGTERM, on every
    # platform. An exit hook alone would not run: the re-raised signal ends the process first.
    sent = await asyncio.to_thread(durable.flush, SHUTDOWN_FLUSH_SECONDS)
    log.info("shutdown: durable copy %s", "is up to date" if sent else f"still had {durable.pending()} writes queued")


class SendCopyBeforeReplying:
    """Hold the end of each response until the writes it queued for the durable copy are sent.

    On Cloud Run an instance only surely has CPU while a request is open. Writes left in the
    queue when the response ends would go out whenever the instance next got CPU: at the next
    request, or never if a deploy moved traffic first. The client already has everything but the
    end of the body, so a reply (an SSE stream included) is not delayed, only the closing of the
    connection. A copy that is failing is not waited on (durable.writing_well)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_after_copy(message: Message) -> None:
            last = message["type"] == "http.response.body" and not message.get("more_body", False)
            if last and durable.pending() and durable.writing_well():
                await asyncio.to_thread(durable.flush, SEND_BEFORE_REPLYING_SECONDS)
            await send(message)

        await self.app(scope, receive, send_after_copy)


app = FastAPI(title="Senior API", version="0.1.0", lifespan=lifespan)
app.add_middleware(SendCopyBeforeReplying)


@app.exception_handler(MemoryUnavailable)
async def memory_unavailable(_: Request, exc: MemoryUnavailable) -> JSONResponse:
    """The session may well exist; its stored copy just could not be read. Not a 404."""
    log.warning("answered 503: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Senior's memory did not answer just now. Please try again in a few seconds."},
        headers={"Retry-After": str(int(durable.BACK_OFF_SECONDS))},
    )

# Open CORS for development (hackathon scope).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Every route is answered for a viewer (a guest or a signed-in user), so a token that
# does not verify is refused everywhere. What a viewer may see is decided in the routes.
for module in (sessions, problems, tracks, traces, mentor, voice, cv, profile, logs, eval_routes):
    app.include_router(module.router, dependencies=[Depends(current_viewer)])


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


# In a deployed build, serve the web app from the same origin. Mounted last so
# every API route above wins.
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")

"""Tool: web search through Exa (https://exa.ai). Returns pages with a text excerpt each.

Traced as a `tool.call` span named `exa.search`. With SENSEI_USE_STUBS=1 it returns fixed
results and makes no network call. Without EXA_API_KEY it raises ExaNotConfigured, which
callers report as "not set up", distinct from a search that ran and found nothing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from app.config import get_settings
from app.models import Actor
from app.tracing.context import span

URL = "https://api.exa.ai/search"
EXCERPT_CHARS = 400


class ExaNotConfigured(RuntimeError):
    """EXA_API_KEY is not set."""


class ExaError(RuntimeError):
    """The search failed or returned something unusable."""


@dataclass(frozen=True)
class ExaPage:
    title: str
    url: str
    excerpt: str
    published: str | None


STUB_PAGES = [
    ExaPage("Backend Engineer, Payments (sample)", "https://example.com/jobs/backend-payments",
            "Python, PostgreSQL, Kubernetes; own on-call for payment APIs.", None),
    ExaPage("Platform Engineer (sample)", "https://example.com/jobs/platform",
            "Go or Python, Terraform, Kubernetes, observability.", None),
]


async def search(query: str, *, actor: Actor = "cv_writer", results: int = 5) -> list[ExaPage]:
    """Search the web and return up to `results` pages."""
    stubbed = get_settings().use_stubs
    key = os.getenv("EXA_API_KEY", "").strip()
    if not stubbed and not key:
        # Recorded as a skipped call and raised after the span closes: a search that was never
        # set up is not a failure of the search, and must not be logged as one.
        with span(actor, "tool.call", "exa.search", query) as st:
            st.model = "exa/auto"
            st.decision, st.reason, st.status = "skipped", "EXA_API_KEY is not set", "blocked"
        raise ExaNotConfigured("Exa is not set up on this server (EXA_API_KEY is missing).")
    with span(actor, "tool.call", "exa.search", query) as st:
        st.model = "exa/auto"
        if stubbed:
            st.decision, st.reason = "stub", "SENSEI_USE_STUBS=1: fixed results, no network"
            return STUB_PAGES
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                response = await http.post(
                    URL, headers={"x-api-key": key},
                    json={"query": query, "numResults": results, "type": "auto",
                          "contents": {"text": {"maxCharacters": EXCERPT_CHARS}}},
                )
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ExaError(f"Exa search failed: {type(exc).__name__}: {exc}") from exc
        pages = [
            ExaPage(str(r.get("title") or r["url"]), str(r["url"]), str(r.get("text") or "")[:EXCERPT_CHARS].strip(),
                    r.get("publishedDate"))
            for r in body.get("results") or [] if r.get("url")
        ]
        st.decision, st.reason = "searched", f"{len(pages)} pages returned"
        st.output = "; ".join(p.title for p in pages)[:2000]
        return pages

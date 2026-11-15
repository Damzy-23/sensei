"""Tool: web search through Linkup (https://linkup.so). Returns an answer with cited sources.

Traced as a `tool.call` span named `linkup.search`, with latency and the per-search cost.
With SENSEI_USE_STUBS=1 it returns fixed results and makes no network call.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from app.config import get_settings
from app.models import Actor
from app.tracing.context import span

URL = "https://api.linkup.so/v1/search"
# Linkup list price for one standard-depth search (EUR 0.005), in USD. Re-check before quoting.
STANDARD_SEARCH_USD = 0.0055


class LinkupError(RuntimeError):
    """The search failed or returned something unusable."""


@dataclass(frozen=True)
class LinkupSource:
    name: str
    url: str
    snippet: str


@dataclass(frozen=True)
class LinkupResult:
    answer: str
    sources: list[LinkupSource]


STUB_RESULT = LinkupResult(
    answer=(
        "Entry-level backend and platform roles ask for one strong language (Python, Go or Java), "
        "data structures and algorithms for interviews, SQL, and cloud basics. Data engineering roles "
        "add pipelines and SQL depth; ML engineering adds Python, statistics and model deployment."
    ),
    sources=[
        LinkupSource("Backend engineer: skills and interview guide", "https://example.com/backend-engineer", "Backend roles test DSA, APIs and SQL."),
        LinkupSource("What data engineers do", "https://example.com/data-engineer", "Pipelines, SQL and distributed processing."),
        LinkupSource("ML engineer career guide", "https://example.com/ml-engineer", "Python, statistics and deployment."),
    ],
)


async def search(query: str, *, actor: Actor = "career_agent", depth: str = "standard") -> LinkupResult:
    """Search the web and return Linkup's sourced answer."""
    with span(actor, "tool.call", "linkup.search", query) as st:
        st.model = f"linkup/{depth}"
        if get_settings().use_stubs:
            result = STUB_RESULT
            st.decision, st.reason = "stub", "SENSEI_USE_STUBS=1: fixed results, no network"
        else:
            key = os.getenv("LINKUP_API_KEY")
            if not key:
                raise LinkupError("LINKUP_API_KEY is not set")
            try:
                async with httpx.AsyncClient(timeout=45) as http:
                    response = await http.post(
                        URL,
                        json={"q": query, "depth": depth, "outputType": "sourcedAnswer"},
                        headers={"Authorization": f"Bearer {key}"},
                    )
                    response.raise_for_status()
                    body = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise LinkupError(f"Linkup search failed: {type(exc).__name__}: {exc}") from exc
            sources = [
                LinkupSource(str(s.get("name") or s.get("url")), str(s["url"]), str(s.get("snippet") or "")[:400])
                for s in body.get("sources") or []
                if s.get("url")
            ]
            result = LinkupResult(answer=str(body.get("answer") or ""), sources=sources)
            st.cost_usd = STANDARD_SEARCH_USD if depth == "standard" else None
            st.decision, st.reason = "searched", f"{len(sources)} sources returned"
        st.output = result.answer[:2000]
        return result

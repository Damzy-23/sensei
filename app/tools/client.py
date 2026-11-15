"""client actor. Test results come from the browser (Pyodide). Trusted for the hackathon scope."""

from __future__ import annotations

from typing import Any

from app.models import RunIn
from app.tracing.context import current_span
from app.tracing.registry import tool


@tool("client", "run_tests", "tool.call")
async def run_tests(session_id: str, run: RunIn) -> dict[str, Any]:
    """Log a browser test run (source=client)."""
    summary = {
        "source": "client",
        "passed": run.passed,
        "failed": run.failed,
        "total": run.total,
        "runtime_ms": run.runtime_ms,
        "failure_names": [f.name for f in run.failures],
    }
    st = current_span()
    if st is not None:
        st.output = (
            f"source=client passed={run.passed} failed={run.failed} "
            f"total={run.total} runtime_ms={run.runtime_ms}"
        )
    return summary

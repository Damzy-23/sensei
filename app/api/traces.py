"""Trace routes: the full span tree for one student message."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import stubs
from app.config import get_settings
from app.models import TraceTree
from app.tracing import store

router = APIRouter(prefix="/traces", tags=["traces"])


@router.get("/{trace_id}", response_model=TraceTree)
async def get_trace(trace_id: str) -> TraceTree:
    if get_settings().use_stubs:
        if trace_id != stubs.STUB_TRACE_ID:
            raise HTTPException(status_code=404, detail="trace not found")
        return stubs.stub_trace_tree(trace_id, session_id="ses_demo_0001")
    events = store.load_trace(trace_id)
    if not events:
        raise HTTPException(status_code=404, detail="trace not found")
    return TraceTree(trace_id=trace_id, session_id=events[0].session_id, roots=store.build_tree(events))

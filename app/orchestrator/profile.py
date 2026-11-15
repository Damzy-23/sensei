"""Profile flow: hands each step of the career interview to the career agent, traced.

One trace per step. When the student has an app session, the steps are traced under
it, so the career agent's work shows in the agent inspector beside the coach's.
"""

from __future__ import annotations

from app import catalog
from app.agents import career
from app.memory import profiles
from app.models import ProfileDetail, ProfileResult, ProfileTurn
from app.tracing.context import turn


class ProfileError(RuntimeError):
    def __init__(self, message: str, trace_id: str | None = None) -> None:
        super().__init__(message)
        self.trace_id = trace_id


def _turn_out(profile: ProfileDetail, trace_id: str | None) -> ProfileTurn:
    answered = sum(1 for q in profile.qa if q.answer)
    pending = next((q.question for q in profile.qa if q.answer is None), None)
    return ProfileTurn(
        profile_id=profile.profile_id,
        step=answered,
        total=len(career.TOPICS),
        question=pending,
        done=answered >= len(career.TOPICS),
        trace_id=trace_id,
    )


def _tracks() -> dict[str, tuple[str, list[str]]]:
    out: dict[str, tuple[str, list[str]]] = {}
    for summary in catalog.list_tracks():
        track = catalog.get_track(summary.id)
        if track is None:
            continue
        patterns: list[str] = []
        for p in track.problems:
            if p.pattern not in patterns:
                patterns.append(p.pattern)
        out[track.id] = (track.title, patterns)
    return out


async def start(trace_session: str | None) -> ProfileTurn:
    profile = profiles.create()
    with turn(trace_session or profile.profile_id, "profile.start") as tctx:
        profile.qa.append(await career.next_question(profile.qa, 0))
    profiles.save(profile)
    return _turn_out(profile, tctx.trace_id)


async def answer(profile: ProfileDetail, text: str, trace_session: str | None) -> ProfileTurn:
    pending = next((q for q in profile.qa if q.answer is None), None)
    if pending is None:
        return _turn_out(profile, None)
    pending.answer = text.strip()
    index = len(profile.qa)
    trace_id = None
    if index < len(career.TOPICS):
        with turn(trace_session or profile.profile_id, "profile.answer") as tctx:
            profile.qa.append(await career.next_question(profile.qa, index))
        trace_id = tctx.trace_id
    profiles.save(profile)
    return _turn_out(profile, trace_id)


async def recommend(profile: ProfileDetail, trace_session: str | None) -> ProfileResult:
    trace_id = None
    try:
        with turn(trace_session or profile.profile_id, "profile.recommend") as tctx:
            trace_id = tctx.trace_id
            summary, roles, practice, sources = await career.recommend(profile.qa, _tracks())
    except Exception as exc:  # the model or the search failed: name it, keep the trace id
        raise ProfileError(f"The career agent could not finish: {exc}", trace_id) from exc
    result = ProfileResult(
        profile_id=profile.profile_id, summary=summary, roles=roles, practice=practice, sources=sources, trace_id=trace_id
    )
    profile.result = result
    profiles.save(profile)
    return result

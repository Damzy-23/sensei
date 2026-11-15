"""Career agent: interviews the student, searches the web with Linkup, recommends roles.

Role prompts: app/prompts/career_agent*.md. With SENSEI_USE_STUBS=1 every step is
deterministic and makes no network call, but is still traced.
"""

from __future__ import annotations

from app.config import get_settings
from app.llm import gateway
from app.models import PracticePlan, ProfileQA, RoleRecommendation, Source
from app.prompts.loader import load
from app.tools import linkup
from app.tracing.context import span

NAME = "career_agent"

# (topic, default question). The agent rewords each one to build on earlier answers.
TOPICS: list[tuple[str, str]] = [
    ("experience", "Tell me about your coding so far: degree, projects, internships or jobs?"),
    ("languages", "Which programming languages and tools are you most comfortable with?"),
    ("interests", "Which areas pull you in most: backend, frontend, data, ML, infrastructure, mobile, something else?"),
    ("enjoy", "What kind of work do you enjoy most day to day: building features, debugging, designing systems, analysing data?"),
    ("seniority", "What level are you aiming for: internship, graduate, junior, or more senior?"),
    ("location", "Where do you want to work, and are you open to remote?"),
]


def _render(qa: list[ProfileQA]) -> str:
    answered = [q for q in qa if q.answer]
    if not answered:
        return "(no answers yet)"
    return "\n".join(f"- {q.topic}: Q: {q.question} A: {q.answer}" for q in answered)


async def next_question(qa: list[ProfileQA], index: int) -> ProfileQA:
    """The question for topic `index`, worded to follow on from the answers so far."""
    topic, default = TOPICS[index]
    with span(NAME, "agent.start", f"question.{topic}", _render(qa)) as st:
        if get_settings().use_stubs or index == 0:
            question = default
            st.decision, st.reason = "default wording", "first question" if index == 0 else "SENSEI_USE_STUBS=1"
        else:
            user = f"Topic: {topic}\nDefault wording: {default}\n\nAnswers so far:\n{_render(qa)}"
            question = (await gateway.complete("fast", system=load(NAME), user=user, actor=NAME, name="llm_question")).strip()
            question = question.strip('"').splitlines()[0][:300] or default
            st.decision, st.reason = "adapted", f"topic {topic}, built on {sum(1 for q in qa if q.answer)} answers"
        st.output = question
        return ProfileQA(topic=topic, question=question)


async def recommend(
    qa: list[ProfileQA], tracks: dict[str, tuple[str, list[str]]]
) -> tuple[str, list[RoleRecommendation], PracticePlan, list[Source]]:
    """Search the web for roles that fit the answers, then rank them with cited sources.

    `tracks` maps a track id to (title, the patterns it covers).
    """
    answers = _render(qa)
    with span(NAME, "agent.start", "recommend", answers) as st:
        if get_settings().use_stubs:
            query = "best entry-level software engineering roles for a student, skills required and demand"
        else:
            data = await gateway.complete_json("fast", system=load("career_agent_query"), user=answers, actor=NAME, name="llm_query")
            query = str(data.get("query") or "").strip() or "software engineering roles for a graduate, skills and demand"

        found = await linkup.search(query, actor=NAME)
        sources = [Source(title=s.name, url=s.url) for s in found.sources[:12]]

        if get_settings().use_stubs:
            result = _stub_result(sources, tracks)
        else:
            catalogue = "\n".join(f"- {tid}: {title}. Patterns: {', '.join(pats)}" for tid, (title, pats) in tracks.items())
            numbered = "\n".join(f"[{i}] {s.name} ({s.url}): {s.snippet}" for i, s in enumerate(found.sources[:12], 1))
            user = (
                f"Student's answers:\n{answers}\n\nSearch query: {query}\n\nSearch answer:\n{found.answer}\n\n"
                f"Sources:\n{numbered or '(none)'}\n\nSenior tracks:\n{catalogue}"
            )
            data = await gateway.complete_json(
                "reasoning", system=load("career_agent_recommend"), user=user, actor=NAME, name="llm_recommend"
            )
            result = _parse(data, sources, tracks)
        summary, roles, practice = result
        st.decision = f"{len(roles)} roles"
        st.reason = f"ranked from {len(sources)} Linkup sources for query: {query}"
        st.output = "; ".join(r.title for r in roles)
        return summary, roles, practice, sources


def _practice(tracks: dict[str, tuple[str, list[str]]], track_id: str | None, patterns: list[str], why: str) -> PracticePlan:
    tid = track_id if track_id in tracks else next(iter(tracks))
    title, known = tracks[tid]
    lookup = {p.lower(): p for p in known}
    chosen = [lookup[p.lower()] for p in patterns if isinstance(p, str) and p.lower() in lookup]
    seen: list[str] = []
    for p in chosen + known:
        if p not in seen:
            seen.append(p)
    return PracticePlan(track_id=tid, track_title=title, patterns=seen[: max(3, min(5, len(chosen) or 4))], why=why)


def _parse(
    data: dict, sources: list[Source], tracks: dict[str, tuple[str, list[str]]]
) -> tuple[str, list[RoleRecommendation], PracticePlan]:
    roles: list[RoleRecommendation] = []
    for raw in (data.get("roles") or [])[:5]:
        if not isinstance(raw, dict) or not raw.get("title"):
            continue
        cited = [sources[i - 1] for i in raw.get("source_ids") or [] if isinstance(i, int) and 1 <= i <= len(sources)]
        skills = [str(s) for s in raw.get("skills_to_strengthen") or [] if s][:4]
        roles.append(RoleRecommendation(title=str(raw["title"]), fit=str(raw.get("fit") or ""), skills_to_strengthen=skills, sources=cited))
    if not roles:
        raise gateway.LLMError("career agent returned no roles")
    practice_raw = data.get("practice") if isinstance(data.get("practice"), dict) else {}
    practice = _practice(
        tracks, practice_raw.get("track_id"), list(practice_raw.get("patterns") or []), str(practice_raw.get("why") or "")
    )
    return str(data.get("summary") or ""), roles, practice


def _stub_result(
    sources: list[Source], tracks: dict[str, tuple[str, list[str]]]
) -> tuple[str, list[RoleRecommendation], PracticePlan]:
    roles = [
        RoleRecommendation(
            title="Backend engineer (graduate)",
            fit="You enjoy building features in Python and want a role close to APIs and data.",
            skills_to_strengthen=["SQL joins and indexes", "REST API design", "Hash map and two-pointer patterns"],
            sources=sources[:1],
        ),
        RoleRecommendation(
            title="Data engineer (junior)",
            fit="You like working with data and want to build the pipelines behind it.",
            skills_to_strengthen=["SQL window functions", "Batch pipelines", "Graph traversal"],
            sources=sources[1:2],
        ),
        RoleRecommendation(
            title="Machine learning engineer (graduate)",
            fit="You named ML as an interest and already write Python.",
            skills_to_strengthen=["Statistics basics", "Model deployment", "Heaps and sorting"],
            sources=sources[2:3],
        ),
    ]
    practice = _practice(tracks, "blind_75", ["arrays", "two pointers", "graphs", "sliding window"], "Backend and data interviews lean on these most.")
    return "You write Python and like building things that move data. Backend and data roles fit you best.", roles, practice

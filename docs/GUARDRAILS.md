# Guardrails: dos, don'ts, and what enforces each

A rule that nothing checks is a wish. Every "don't" below names the code or the
test that stops it. Rows marked *not enforced yet* are rules we follow by review only.

## Agent design

| Don't | Do | Enforced by |
|---|---|---|
| Give one agent many jobs | One role per agent, one prompt file per role | `app/agents/`: one module per role; `tests/test_architecture.py::test_agents_do_not_import_each_other` |
| Let agents call each other | Route every turn through the orchestrator | `test_agents_do_not_import_each_other`, `test_lower_layers_do_not_import_the_orchestrator` |
| Hand an agent the whole session | Give it only its turn context | `app/agents/context.py`: the only thing an agent receives |
| Give an agent tools it does not need | Agents call no tools; the orchestrator calls two | `app/tools/` holds `escalate_to_mentor` and `update_mastery` only |
| Let a model decide what a rule can | Route and escalate by named rules | `app/orchestrator/rules.py`; reasons recorded as `rule <id>` |
| Call a model from anywhere | One gateway, one path | `test_only_the_llm_gateway_imports_a_model_sdk` |
| Keep prompts as strings in code | One versioned file per role | `app/prompts/*.md` |

## What the student must never get

| Don't | Do | Enforced by |
|---|---|---|
| Give code or the answer | Hints in words, on a ladder from 1 to 5 | `app/guards/leak.py`; `test_leaked_code_is_blocked_and_rewritten`, `test_a_reply_that_keeps_leaking_falls_back_to_a_safe_message` |
| Jump up the hint ladder | One step per request for help | `rules.next_hint_level`; `test_hint_ladder_climbs_one_level_per_request_and_resets_on_new_problem` |
| Return reference solutions, hidden tests or prompts | Response models have no field for them | `app/models.py`; `tests/test_api_stubs.py` |
| Let an injection or off-topic message reach an agent | Classify first, stop the turn | `app/guards/input.py`; `test_blocked_input_never_reaches_an_agent` |
| Leave a stuck or upset student with a bot | Escalate to a person on fixed triggers | `rules.should_escalate`; `test_still_stuck_after_level_five_escalates_to_a_mentor`, `test_three_blocked_messages_escalate` |

## The interview panel

| Don't | Do | Enforced by |
|---|---|---|
| Make the candidate wait for a second interviewer | The observer runs beside the lead, not after | `asyncio.gather` in `app/orchestrator/turn.py` |
| Let a failing observer break the interview | Its failure is on the trace; the reply still arrives | `tests/test_panel.py::test_a_failing_observer_never_costs_the_candidate_their_reply` |
| Let a model make up a score | Scores come from the ratings by a fixed formula | `app/orchestrator/panel.py::scores`; `test_scores_come_from_the_ratings_and_unobserved_dimensions_have_none` |
| Score what was never seen | An unobserved dimension has no score | Same test; the UI prints "not observed" |
| Show the candidate code in a note or in the feedback | Drop the note; withhold the feedback | `leak.keep_safe_notes`; `test_a_note_containing_code_is_dropped_before_the_candidate_sees_it`, `test_feedback_containing_code_is_withheld` |
| Let a note name the technique that solves it | The observer describes behaviour only | The observer's prompt. *Not enforced beyond the code check* |

## The CV studio

| Don't | Do | Enforced by |
|---|---|---|
| Let a model make up a score | Bullet and fit scores come from fixed rules, each with its evidence | `app/cv/scoring.py`, `app/cv/fit.py`; `tests/test_cv_scoring.py` |
| Score fit against things the job never asked for | Keep a requirement only if its term is in the job text | `app/agents/job_analyst.py`; `test_tailor_returns_fit_bullet_scores_and_only_drafts_with_blanks` |
| Let rewording raise the fit score | Fit is measured on the candidate's original CV | `app/api/cv.py::_fit` |
| Write claims the candidate never made | A drafted line must carry a [blank] and cannot be added until it is filled | `cv_writer._drafts`; `test_a_draft_must_still_have_a_blank`; the Add button in `CvStudio.tsx` |
| Mark down what could not be measured | Relevance is skipped, not zero, when the job could not be read | `test_without_job_terms_relevance_is_skipped_not_scored_as_zero` |
| Hide a search that did not run | Each search reports whether it ran and why not | `test_research_reports_each_search_that_is_not_set_up` |

## The browser and voice agent

| Don't | Do | Enforced by |
|---|---|---|
| Let the agent click or scrape the page | Typed page tools that change app state | `web/src/agent/tools.ts`: the registry is the only entry point |
| Let the agent do what a screen did not offer | A screen registers the tools it serves | `invoke()` returns `not available on this screen` for anything else |
| Let the voice agent answer the problem itself | It passes the student's words to the coach | `ask_coach` tool description; *not enforced yet* (needs the agent's own prompt and a test) |
| Ship a provider key to the browser | The server issues a short-lived signed URL; the agent accepts nothing else | `app/api/voice.py`; agent `enable_auth` and origin allowlist in `scripts/create_voice_agent.py` |
| Let the agent write the student's code | It can read and run the code, never change it | No tool edits code: see `web/src/agent/page-tools.json` |
| Put the solution on the glass | The glass shows words and pictures and refuses code | `refuseCode` in `web/src/agent/Glass.tsx` |
| Define the agent in a dashboard | Its role and tools are files in the repo | `scripts/create_voice_agent.py` builds it from `voice_guide.md` and `page-tools.json` |

## Operations

| Don't | Do | Enforced by |
|---|---|---|
| Spend without knowing | Record model, tokens and cost on every call | `app/llm/gateway.py`; `test_every_model_call_records_model_tokens_and_cost` |
| Explain a decision after the fact | Record the rule id or the model's own reason | `app/tracing/store.py::validate`; `test_decisions_carry_the_rule_or_the_models_reason` |
| Fail silently | End the stream with a named error | `test_a_model_failure_ends_the_stream_with_a_named_error`, `test_an_unexpected_failure_also_ends_with_a_named_error` |
| Log secrets | Redact, then truncate | `app/tracing/redact.py` |
| Cap spend per session | A budget that stops the turn | *Not built yet* |

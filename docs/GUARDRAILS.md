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
| Give the answer | Hints in words, on a ladder from 1 to 5 | `app/guards/leak.py`; `test_leaked_code_is_blocked_and_rewritten`, `test_a_reply_that_keeps_leaking_falls_back_to_a_safe_message` |
| Volunteer code before the student has tried | Unasked, a line is offered only after three tries (messages plus failed runs). A student who asks gets one line | `rules.code_help`; `test_code_is_not_volunteered_before_the_student_has_tried`, `test_a_student_who_asks_for_a_line_gets_one_line`, `test_after_three_tries_the_coach_may_give_one_line` |
| Hand over the solution | One line per reply and three per problem, even when they ask for all of it | `leak.decide`, `policy.CODE_LINES_PER_PROBLEM`; `test_asking_still_gets_one_line_not_the_solution`, `test_even_when_earned_it_is_one_line_not_two`, `test_code_help_stops_at_three_lines_a_problem_and_resets_on_a_new_one` |
| Give code in an interview | Never, however often they ask | `test_no_code_in_an_interview_however_often_they_ask` |
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

## Pictures on the glass

After a hint coach reply the illustrator draws one picture without being asked. Its drawing
is checked by rule before it leaves the server (`app/guards/drawing.py`): the kind, the sizes
the glass can show, the pointer, water, highlight and edge formats, and no code in any value,
label, title or caption. A drawing that breaks a rule is dropped, not rewritten, and the
trace records it as blocked with the rule that fired.

| Don't | Do | Enforced by |
|---|---|---|
| Put code on the glass | The same patterns as the leak check, and stricter: a drawing may hold no code at all, not even the one line a reply may give | `leak.is_code`, rule `drawing.code`; `tests/test_illustrator.py::test_a_drawing_with_code_anywhere_is_blocked`, `test_a_drawing_that_repeats_the_coachs_line_of_code_is_blocked` |
| Show the illustrator code it must not repeat | It is handed the reply in words; a line of code in it is left out | `leak.prose_only`; `test_a_line_of_code_stays_in_the_reply_and_is_not_shown_to_the_illustrator` |
| Draw more than the glass can show | 16 cells, 31 nodes, 6 steps, 8 rows of 12, a 160 character caption | Rule `drawing.size`; `test_an_oversize_drawing_is_blocked` |
| Make the student wait for a picture, or lose the reply to one | The reply is sent first; the illustrator has 8 seconds and its failure ends nothing | `test_final_is_sent_before_the_illustrator_has_answered`, `test_a_failing_illustrator_still_yields_a_normal_final_reply`, `test_a_slow_illustrator_is_cut_off_and_the_stream_just_closes` |
| Draw for an interview, a blocked message or a hand-over to a mentor | Only the hint coach's own words get a picture | `test_only_learn_mode_draws`, `test_a_blocked_message_gets_no_drawing`, `test_the_reply_that_hands_over_to_a_mentor_gets_no_drawing` |
| Draw the solution, or a step past the hint level | The illustrator's role forbids it, and it is never given the problem statement or a solution | `app/prompts/illustrator.md`. *Not enforced beyond the code check* |
| Follow instructions in the student's message | The message and code are marked as data; a blocked message never reaches the illustrator | The role file; `test_a_blocked_message_gets_no_drawing` |

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
| Let the voice agent write code of its own | `write_line` writes only the line the coach offered, after it was earned | `write_line` in `web/src/pages/Workspace.tsx` takes a position, never code |
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

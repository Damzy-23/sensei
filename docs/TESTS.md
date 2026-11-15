# Test map

Every behaviour the spec asks tests for, and where it is tested. Run everything with:

```bash
python -m pytest
```

No network calls: model calls use `tests/fakes.py` (a scripted model keyed by role) or a fake
provider set with `monkeypatch`.

| Spec requirement | Test file | Key tests |
|---|---|---|
| Hint ladder gating (ask AND (failed run OR wait)) | `tests/test_ladder.py`, `tests/test_hint_gating.py` | `test_failed_run_since_last_unlock_grants_next_level`, `test_waiting_long_enough_grants_next_level`, `test_asking_immediately_without_failed_run_is_denied`, `test_not_asking_never_unlocks` |
| No level skipping | `tests/test_ladder.py`, `tests/test_hint_gating.py` | `test_levels_are_never_skipped`, `test_levels_climb_one_at_a_time_to_five_and_stop` |
| Mode switching rules | `tests/test_modes_escalation.py` | `test_three_failed_runs_force_learn_from_any_mode`, `test_learn_to_interview_after_quick_solve_with_mastery`, `test_interview_to_blitz_after_three_fast_solves`, `test_select_mode_tool_logs_decision_and_reason` |
| Each escalation trigger | `tests/test_modes_escalation.py`, `tests/test_pipeline.py` | `test_stuck_at_level_five_escalates`, `test_three_guard_violations_escalate`, `test_frustration_twice_escalates`, `test_three_injections_escalate_to_a_mentor_ticket`, `test_level_five_still_failing_escalates` |
| `leak_check` blocks a leaked solution | `tests/test_output_guard.py`, `tests/test_pipeline.py` | `test_copy_of_reference_is_blocked_by_similarity`, `test_code_before_level_five_is_blocked`, `test_leak_check_blocks_when_judge_says_leak`, `test_leaking_hint_is_regenerated_then_falls_back_to_canned` |
| Injection blocking | `tests/test_input_guard.py`, `tests/test_pipeline.py` | `test_injection_rules_match`, `test_injection_skips_the_model_entirely`, `test_injection_is_blocked_without_a_model_call_and_counted` |
| Tracing parent and child structure | `tests/test_tracing.py` | `test_nested_spans_form_parent_child_tree`, `test_build_tree_nests_children_under_parent`, `test_context_does_not_leak_between_concurrent_tasks` |
| Registry: every public tool function is registered | `tests/test_tracing.py` | `test_every_public_tool_function_is_registered`, `test_registered_tool_inventory_matches_spec` |
| Guard events carry decision and reason | `tests/test_tracing.py` | `test_guard_event_without_decision_is_rejected`, `test_mode_event_requires_reason` |
| Redaction and 500-character truncation | `tests/test_tracing.py` | `test_input_is_truncated_to_500_chars`, `test_key_like_strings_are_redacted` |
| Problem bank: references pass, public view is clean | `tests/test_bank.py` | `test_reference_solutions_pass_all_tests`, `test_public_view_has_no_solution_or_hidden_tests`, `test_api_response_contains_no_reference_or_hidden_test` |
| Canned fallbacks never contain code | `tests/test_output_guard.py` | `test_canned_fallbacks_pass_every_static_check` |
| Scripted student completes the demo | `tests/test_simulator.py` | `test_scripted_student_completes_the_demo_scenario` |
| Model failure degrades instead of crashing | `tests/test_pipeline.py`, `tests/test_agent_tools.py` | `test_no_key_degrades_without_crashing`, `test_ticket_survives_model_failure`, `test_hint_model_falls_back_to_base_when_tuned_not_configured` |

Validate the problem bank on its own with:

```bash
python scripts/validate_bank.py
```

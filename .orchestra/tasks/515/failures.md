# #515 — состав падений: CI против локального прогона (одна и та же раскладка)

CI run 33956684131: 57 падений. Локально: 33. Общих: 30, только CI: 27, только локально: 3.

## Падают ВЕЗДЕ — настоящие (30)

| node id | причина CI | причина локально |
|---|---|---|
| `tests/test_codex_bin_resolution.py::test_resolved_binary_reaches_the_shell_command` | ValueError: fatal: not a git repository (or any of the parent directories): .git |  |
| `tests/test_fan_barrier_gates.py::test_message_without_sender_is_never_buffered` | AssertionError: неаутентифицированный internal caller был принят за человека |  |
| `tests/test_fan_report_delivery.py::test_explicit_send_message_keeps_child_text_reachable_via_manifest` | AssertionError: пробуждений 0, ждали одно |  |
| `tests/test_fan_report_delivery.py::test_silent_turn_manifest_is_as_rich_as_explicit_and_keeps_text` | AssertionError: явный путь оставил report_path пустым |  |
| `tests/test_handoff_effect_classification.py::test_change_model_refusal_names_the_blocking_call_not_only_its_code` | KeyError: 'error_code' |  |
| `tests/test_log_write_loss.py::test_lost_log_write_is_reported` | assert 'log write lost' in "ERROR    asyncio:base_events.py:1821 Exception in callback AgentSession._log.<locals>.completed(<Future finis...aint ...ation] = (\n    ^^^^^^^^^^^^^^^^^^^^^^^\nAttributeError: 'AgentSession' object has no attribute '_failed_log_writes'\n" | assert... |
| `tests/test_mcp_quota_gate.py::test_available_review_starts_job` | ValueError: fatal: not a git repository (or any of the parent directories): .git | Value... |
| `tests/test_mcp_quota_gate.py::test_codex_review_is_blocked_before_the_bg_job` | ValueError: fatal: not a git repository (or any of the parent directories): .git |  |
| `tests/test_mcp_quota_gate.py::test_review_fails_open_on_unknown_malformed_or_transport[None]` | ValueError: fatal: not a git repository (or any of the parent directories): .git |  |
| `tests/test_mcp_quota_gate.py::test_review_fails_open_on_unknown_malformed_or_transport[answer0]` | ValueError: fatal: not a git repository (or any of the parent directories): .git |  |
| `tests/test_mcp_quota_gate.py::test_review_fails_open_on_unknown_malformed_or_transport[answer1]` | ValueError: fatal: not a git repository (or any of the parent directories): .git |  |
| `tests/test_mcp_quota_gate.py::test_review_fails_open_on_unknown_malformed_or_transport[answer2]` | ValueError: fatal: not a git repository (or any of the parent directories): .git |  |
| `tests/test_mcp_quota_gate.py::test_review_fails_open_on_unknown_malformed_or_transport[answer4]` | ValueError: fatal: not a git repository (or any of the parent directories): .git |  |
| `tests/test_orchestra_layout_430.py::test_t3_repository_move_has_content_receipt_and_no_old_roots` | subprocess.CalledProcessError: Command '['git', '-C', '/home/runner/work/orchestra/orchestra', 'rev-parse', '1f80bb50b81db380fb5f51a0894209538553087f^']' returned non-zero exit status 128. |  |
| `tests/test_orchestra_layout_430.py::test_t4_all_fleet_receipts_precede_global_prompt_activation` | AssertionError: assert 128 == 0 |  |
| `tests/test_orchestra_layout_430.py::test_t5_classified_path_audit_is_clean_and_historical_evidence_resolves` | AssertionError: fatal: not a tree object |  |
| `tests/test_owner_mode.py::test_usage_visible_to_owner_with_login` | AssertionError: assert {'anthropic':...adroom': None} == {'anthropic':...ization': 7}}} | Ass... |
| `tests/test_quota_map_api.py::test_gated_and_free_lanes_split_on_the_same_number` | assert False is True |  |
| `tests/test_quota_map_api.py::test_line_point_is_computed_server_side_for_every_pool` | assert 7.5 == 5.5 ± 5.5e-06 |  |
| `tests/test_quota_map_api.py::test_release_fields_arrive_for_each_gating_status` | AssertionError: assert 'open' == 'opens_in' |  |
| `tests/test_quota_map_api.py::test_rule_constants_reflect_environment_overrides` | AssertionError: assert {'curve_expon...pp': 2.0, ...} == {'hard_stop_p...art_pp': 13.0} |  |
| `tests/test_quota_map_api.py::test_rule_constants_travel_with_the_payload` | AssertionError: assert {'curve_expon...pp': 1.0, ...} == {'hard_stop_p...art_pp': 10.0} |  |
| `tests/test_restart_generation_liveness.py::test_t1_shutdown_sequence_marks_bg_and_handoff_before_cleanup_complete` | TypeError: _shutdown_runtime() missing 2 required positional arguments: 'projection_repair_task' and 'portfolio_watchdog_task' |  |
| `tests/test_t344_quota_lines_browser.py::test_above_the_diagonal_stops_sol_but_not_luna_and_spark` | AssertionError: assert 'блок' in 'Sol: работает' |  |
| `tests/test_t344_quota_lines_browser.py::test_hard_99_stops_everyone_and_orchestrator_still_works` | AssertionError: assert ('блок' in 'Sol: работает') |  |
| `tests/test_tailwind_css.py::test_committed_css_matches_current_sources` | AssertionError: собранный CSS разошёлся с закоммиченным — в исходниках появились или пропали классы. Почини запуском: bash scripts/build-tailwind.sh |  |
| `tests/test_task_tracker_integration.py::test_t3_merge_operation_replay_does_not_repeat_git_or_lose_task_outcome` | AssertionError: assert 'FAILED' == 'PARTIAL' |  |
| `tests/test_usage_analytics_frontend.py::test_model_cost_and_task_money_have_separate_currency_sources` | IndexError: list index out of range |  |
| `tests/test_usage_readiness.py::test_readiness_endpoint_blocks_above_the_line` | assert None == 55.5 ± 5.6e-05 |  |
| `tests/test_usage_readiness.py::test_readiness_endpoint_returns_the_execution_time_decision` | AssertionError: assert ('claude' == 'claude' |  |

## Только на CI — дыра окружения раннера (27)

| node id | причина |
|---|---|
| `tests/test_audit0901_session.py::test_heartbeat_dead_process_recovery_publishes` | AssertionError: assert 0 == 1 |
| `tests/test_audit0901_session.py::test_heartbeat_zombie_without_backend_publishes` | AssertionError: assert <AgentStatus.RUNNING: 'running'> is <AgentStatus.IDLE: 'idle'> |
| `tests/test_codex_bin_resolution.py::test_missing_binary_gives_actionable_text_instead_of_exit_127` | ValueError: fatal: cannot change to '/home/kesha/orchestra': No such file or directory |
| `tests/test_codex_review_sandbox.py::test_codex_review_disables_unusable_namespace_sandbox[False-exec]` | KeyError: 'config' |
| `tests/test_codex_review_sandbox.py::test_codex_review_disables_unusable_namespace_sandbox[False-review]` | KeyError: 'config' |
| `tests/test_codex_review_sandbox.py::test_codex_review_disables_unusable_namespace_sandbox[True-exec]` | KeyError: 'config' |
| `tests/test_codex_review_sandbox.py::test_codex_review_disables_unusable_namespace_sandbox[True-review]` | KeyError: 'config' |
| `tests/test_fd_adopt.py::test_t1_helper_uses_pidfd_and_refuses_a_reused_pid` | FileNotFoundError: configured executable was not found |
| `tests/test_fd_adopt.py::test_t1_unknown_start_time_refuses_to_signal` | FileNotFoundError: configured executable was not found |
| `tests/test_frontend.py::test_dashboard_polling_equivalent_twelve_minutes_before_after` | subprocess.CalledProcessError: Command '['git', 'show', 'main:app/static/js/app.js']' returned non-zero exit status 128. |
| `tests/test_frontend.py::test_notify_user_call_is_highlighted_and_navigable_from_the_timeline[compact]` | playwright._impl._errors.Error: Page.evaluate: TypeError: Failed to execute 'getComputedStyle' on 'Window': parameter 1 is not of type 'Element'. |
| `tests/test_frontend.py::test_notify_user_call_is_highlighted_and_navigable_from_the_timeline[normal]` | playwright._impl._errors.Error: Page.evaluate: TypeError: Failed to execute 'getComputedStyle' on 'Window': parameter 1 is not of type 'Element'. |
| `tests/test_mcp_codex_review.py::test_codex_review_explicit_model_overrides_default_and_readiness[gpt-5.6-terra]` | KeyError: 'config' |
| `tests/test_mcp_codex_review.py::test_codex_review_explicit_model_overrides_default_and_readiness[gpt5.6terra]` | KeyError: 'config' |
| `tests/test_mcp_codex_review.py::test_codex_review_resume_command_passes_usage_arguments[model_kwargs0-gpt-5.6-luna]` | KeyError: 'config' |
| `tests/test_mcp_codex_review.py::test_codex_review_resume_command_passes_usage_arguments[model_kwargs1-gpt-5.6-terra]` | KeyError: 'config' |
| `tests/test_mcp_codex_review.py::test_codex_review_uses_caller_context_and_declares_success_contract[exec]` | AssertionError: assert 'bg-test' in 'codex не найден: ни CODEX_BIN в окружении, ни `codex` в PATH. Поставь Codex CLI или задай CODEX_BIN=/путь/к/codex в .env сервиса. Проверить: `which codex`' |
| `tests/test_mcp_codex_review.py::test_codex_review_uses_caller_context_and_declares_success_contract[review]` | AssertionError: assert 'bg-test' in 'codex не найден: ни CODEX_BIN в окружении, ни `codex` в PATH. Поставь Codex CLI или задай CODEX_BIN=/путь/к/codex в .env сервиса. Проверить: `which codex`' |
| `tests/test_mcp_codex_review.py::test_t1_385_codex_review_success_returns_exact_deferred_control_provenance` | AssertionError: assert 'bg-review-385' in 'codex не найден: ни CODEX_BIN в окружении, ни `codex` в PATH. Поставь Codex CLI или задай CODEX_BIN=/путь/к/codex в .env сервиса. Проверить: `which codex`' |
| `tests/test_mcp_config_isolation.py::test_t4_subscription_auth_is_reachable_from_isolated_home` | AssertionError: в изолированном CODEX_HOME нет auth.json — Codex не авторизуется |
| `tests/test_orphan_pid_identity.py::test_t1_unverifiable_candidate_does_not_abort_later_orphan_cleanup` | AssertionError: failure to verify one candidate must not block a later legitimate orphan |
| `tests/test_orphan_pid_identity.py::test_t1_verified_codex_and_grok_orphans_signal_only_through_pidfd` | assert [] == [(90001, <Sig...SIGTERM: 15>)] |
| `tests/test_runtime_handoff_v2.py::test_t3_claude_target_commits_only_after_canary_and_capability_receipts` | AssertionError: {'error': 'authentication', 'error_code': 'handoff_target_failed', 'handoff_id': 'h1', 'history_transfer': {'mode': 'blocked'}, ...} |
| `tests/test_runtime_handoff_v2.py::test_t3_invalid_receipt_never_disconnects_or_confirms[ingress0-capability0-handoff_ingress_rejected]` | AssertionError: assert 'handoff_target_failed' == 'handoff_ingress_rejected' |
| `tests/test_runtime_handoff_v2.py::test_t3_invalid_receipt_never_disconnects_or_confirms[ingress1-capability1-handoff_ingress_rejected]` | AssertionError: assert 'handoff_target_failed' == 'handoff_ingress_rejected' |
| `tests/test_runtime_handoff_v2.py::test_t3_invalid_receipt_never_disconnects_or_confirms[ingress2-capability2-handoff_capability_unsupported]` | AssertionError: assert 'handoff_target_failed' == 'handoff_capa...y_unsupported' |
| `tests/test_voice_input.py::test_ffprobe_reads_actual_audio_duration` | FileNotFoundError: [Errno 2] No such file or directory: 'ffprobe' |

## Только локально — дыра окружения VPS (3)

| node id | причина |
|---|---|
| `tests/test_compact_gate_438.py::test_cli_threshold_lowers_our_threshold` |  |
| `tests/test_compact_gate_438.py::test_orchestrator_compacts_at_96_but_not_94` |  |
| `tests/test_usage_readiness.py::test_anthropic_refresh_is_target_isolated_and_singleflight` |  |

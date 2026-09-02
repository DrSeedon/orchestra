# #433 implementation report

## Execution gates

- #438 merge: `git merge-base --is-ancestor 3dfa39b HEAD` → 0; `git rev-list --count HEAD..main` → 0.
- #436 merge: `git merge-base --is-ancestor 6461ec9 HEAD` → 0; `git rev-list --count HEAD..main` → 0.
- Frozen post-merge oracle states before implementation: T1/T2/T3/T4/T5 = `2/7/18/1/1` missing-behavior failures. After T1, expected state = `green/7/18/1/1`.

## T1 — B1 value and background injection

- `app/events.py`: finite origin, non-empty ordered/deduplicated senders, subtype/ref, canonical JSON, storage round-trip; `InjectedMessage` owns one structured provenance value.
- `app/bg_jobs.py::_terminal_message`: `background_task`, sender/ref job id, subtype outcome.
- Authorized stale #385 assertions in `tests/test_bg_jobs.py` now consume structured provenance; legacy `origin/job_id` assertions removed.
- Test: `env PYTHONPATH=. uv run pytest -q docs/tasks/433/test_t1_provenance_contract_433.py tests/test_bg_jobs.py` → `56 passed`.
- Mutations: origin, senders, subtype, ref, and frozen `InjectedMessage` each returned RC=1; production-marker before/after was 1/1 for every mutation; final restored repeat `56 passed`.

## T2 — A/B classification of the 38 focused failures

Counting rule: classify each node id from `/tmp/pytest-433-t2-classify.log`. `A` means the test helper/fake/setup omitted newly required B1 provenance. `B` means lifecycle behavior unrelated to provenance regressed. Every original node is listed once.

### A — stale provenance-free contract (38)

1. A — `tests/test_initial_deliveries.py::test_t1_accept_commits_before_blocked_cold_wake_and_returns_202` — shared `_accept` omitted provenance.
2. A — `tests/test_initial_deliveries.py::test_t1_same_key_is_insert_or_read_and_different_payload_conflicts` — shared `_accept` omitted provenance.
3. A — `tests/test_initial_deliveries.py::test_t1_failed_accept_commit_has_no_row_wake_log_or_backend_call` — shared `_accept` omitted provenance.
4. A — `tests/test_initial_deliveries.py::test_t1_http_status_lookup_returns_the_same_committed_resource` — shared `_accept` omitted provenance.
5. A — `tests/test_initial_deliveries.py::test_t2_manager_entry_preserves_session_lock_and_auto_switch` — explicit fake session/manager signature omitted provenance.
6. A — `tests/test_initial_deliveries.py::test_t2_session_context_logs_no_duplicate_and_brackets_backend_send` — direct `add_log(user_message)` and `session.send` setup omitted provenance.
7. A — `tests/test_initial_deliveries.py::test_t2_restart_recovers_queued_or_preparing_once[False]` — shared `_accept` omitted provenance.
8. A — `tests/test_initial_deliveries.py::test_t2_restart_recovers_queued_or_preparing_once[True]` — shared `_accept` omitted provenance.
9. A — `tests/test_initial_deliveries.py::test_t2_prepare_commit_is_atomic_with_the_single_user_log` — shared `_accept` omitted provenance.
10. A — `tests/test_initial_deliveries.py::test_t2_restart_never_replays_dispatching_even_if_acceptance_is_unknown[False]` — shared `_accept` omitted provenance.
11. A — `tests/test_initial_deliveries.py::test_t2_restart_never_replays_dispatching_even_if_acceptance_is_unknown[True]` — shared `_accept` omitted provenance.
12. A — `tests/test_initial_deliveries.py::test_t2_restart_leaves_submitted_terminal_and_unscheduled` — shared `_accept` omitted provenance.
13. A — `tests/test_initial_deliveries.py::test_t2_cancel_after_dispatching_marks_unknown_and_never_replays` — shared `_accept` plus explicit cancelling fake omitted provenance.
14. A — `tests/test_initial_deliveries.py::test_t381_backend_none_before_provider_is_known_retryable[backend-none]` — shared `_accept` / explicit session manager omitted provenance.
15. A — `tests/test_initial_deliveries.py::test_t381_backend_none_before_provider_is_known_retryable[raised-before-call]` — shared `_accept` / explicit session manager omitted provenance.
16. A — `tests/test_initial_deliveries.py::test_t381_retry_after_backend_recovery_submits_once_without_duplicate_input` — shared `_accept` / explicit session manager omitted provenance.
17. A — `tests/test_initial_deliveries.py::test_t381_provider_accept_then_transport_loss_stays_unknown_quarantined` — shared `_accept` / explicit session manager omitted provenance.
18. A — `tests/test_initial_deliveries.py::test_t381_next_action_structurally_permits_only_known_safe_retry` — shared `_accept` omitted provenance.
19. A — `tests/test_initial_delivery_review_regressions.py::test_masked_initial_delivery_excludes_the_persisted_history_row` — prepared fixture, recording manager, and direct session send omitted provenance.
20. A — `tests/test_message_delivery_receipts_380.py::test_t380_r1_idle_accepts_before_blocked_manager_send_and_dedupes` — shared `_accept` and explicit blocking manager omitted provenance.
21. A — `tests/test_message_delivery_receipts_380.py::test_t380_r1_http_202_returns_while_manager_send_is_blocked` — explicit HTTP runner fake omitted provenance; the downstream “runner never started” assertion was a consequence of that fake signature.
22. A — `tests/test_message_delivery_receipts_380.py::test_t380_r1_post_commit_schedule_failure_still_returns_accepted` — shared `_accept` omitted provenance.
23. A — `tests/test_message_delivery_receipts_380.py::test_t380_r1_lost_commit_ack_reconciles_the_committed_receipt` — shared `_accept` omitted provenance.
24. A — `tests/test_message_delivery_receipts_380.py::test_t380_r2_running_receipt_steers_once_without_new_turn_or_second_log` — shared `_accept`; after that was fixed, the same node exposed a second A in direct `MessageDeliveryContext`/manager setup.
25. A — `tests/test_message_delivery_receipts_380.py::test_t370_same_id_unknown_receipt_is_never_replayed` — shared `_accept` omitted provenance.
26. A — `tests/test_message_delivery_receipts_380.py::test_t380_r4_pre_dispatch_cancel_and_restart_recover_same_receipt_once` — shared `_accept` plus cancelling fake omitted provenance.
27. A — `tests/test_message_delivery_receipts_380.py::test_t380_r4_prepare_log_and_state_rollback_atomically` — shared `_accept` omitted provenance.
28. A — `tests/test_message_delivery_receipts_380.py::test_t380_r5_post_dispatch_failure_is_unknown_and_never_replayed[cancel]` — shared `_accept` plus provider fake omitted provenance.
29. A — `tests/test_message_delivery_receipts_380.py::test_t380_r5_post_dispatch_failure_is_unknown_and_never_replayed[raise]` — shared `_accept` plus provider fake omitted provenance.
30. A — `tests/test_message_delivery_receipts_380.py::test_t380_r5_recovery_quarantines_orphan_dispatching_without_schedule` — shared `_accept` omitted provenance.
31. A — `tests/test_message_delivery_receipts_380.py::test_t380_r7_concurrent_accept_and_competing_runners_follow_accept_seq` — concurrent helper calls omitted provenance.
32. A — `tests/test_message_delivery_receipts_380.py::test_t380_r7_accept_while_runner_exits_cannot_lose_wake` — shared `_accept` omitted provenance.
33. A — `tests/test_message_delivery_receipts_380.py::test_t380_r7_fifo_and_unknown_head_block_later_receipts` — shared `_accept` omitted provenance.
34. A — `tests/test_message_delivery_receipts_380.py::test_t380_r7_task_generation_change_fails_before_provider` — shared `_accept` omitted provenance.
35. A — `tests/test_message_delivery_receipts_380.py::test_t380_r7_no_inject_turn_finalization_wakes_durable_receipt` — shared `_accept` omitted provenance.
36. A — `tests/test_message_delivery_receipts_380.py::test_t380_r7_native_compact_completion_wakes_durable_receipt` — shared `_accept` omitted provenance.
37. A — `tests/test_message_delivery_receipts_380.py::test_t380_r7_claude_compact_completion_wakes_durable_receipt` — shared `_accept` omitted provenance.
38. A — `tests/test_message_delivery_receipts_380.py::test_t380_r7_deferred_interrupt_stays_durable_not_volatile` — shared `_accept` omitted provenance.

### B — genuine lifecycle regression (0)

- None. After A-only helper/fake/setup updates, the three files pass without production lifecycle changes beyond the approved provenance boundary.

## T2 tests and mutation

- Combined final command output, verbatim:

```text
.....................................................                    [100%]
53 passed in 5.12s
```

- Command: `env PYTHONPATH=. uv run pytest -q docs/tasks/433/test_t2_writer_seams_433.py tests/test_initial_deliveries.py tests/test_initial_delivery_review_regressions.py tests/test_message_delivery_receipts_380.py`.
- Required-send mutation: production marker `AgentSession.send(... provenance: MessageProvenance ...)` before/after = 1/1; exact optional-provenance mutant marker during = 1; mutant caused RC=1 at `#433 provenance must stay mandatory at AgentSession.send`; restored `touch` repeat is the 53-pass command above.

## T3 — field-driven consumers

- Production: DB log read boundaries decode `origin_detail` to an object and sync projects both fields; RAG/runtime history/retry/limit-wake/TG/MCP consume structured fields; runtime prefix parsers removed. `chat.js` prefix parsers were removed, while final left/right rendering remains T4.
- Initial focused result: `30 failed / 302 passed / 32 skipped`.
- Classification: 29 A (15 bg manager fakes, 1 limit-wake fake, 3 RAG prefix expectations, 2 runtime-history setup/expectation, 2 TG fake/old missing-field expectation, 6 undelivered direct sends), 0 B; one unrelated baseline CLI-version drift was separately tracked and deselected.
- Explicit fakes enumerate the `provenance` parameter and assert origin/subtype/ref; no provenance-bearing `MagicMock` fallback was added.

Field-vs-content mutations, each followed by restore + `touch`:

- RAG: field marker `if origin == "user"` before/after = 1/1; content-parser mutant marker during = 1; RC=1 with all three legacy contradiction tests plus `_433` RAG control red.
- Runtime history: field marker `row.get("origin") == "platform"` before/after = 1/1; content-parser mutant marker during = 1; RC=1 with legacy dialogue and `_433` contradiction controls red.
- TG: field marker `if origin == "user"` before/after = 1/1; content-parser mutant marker during = 1; RC=1 with legacy silent-marker and `_433` TG/MCP controls red. The first parameter-address attempt returned RC=4/no tests and is excluded; the successful whole-method mutation is the evidence.

Final command:

`env PYTHONPATH=. uv run pytest -q docs/tasks/433/test_t3_ingress_consumers_433.py tests/test_bg_jobs.py tests/test_limit_wake.py tests/test_rag.py tests/test_runtime_history.py tests/test_tg_bridge.py tests/test_undelivered_queue.py --deselect=tests/test_runtime_history.py::test_installed_claude_history_versions_match_pins`

Verbatim output:

```text
........................................................................ [ 18%]
.....................................................sssssssssssssssssss [ 37%]
s.ssssssssssss.......................................................... [ 56%]
........................................................................ [ 75%]
........................................................................ [ 94%]
.....................                                                    [100%]
========================== ПРОПУЩЕН РЕАЛЬНЫЙ СЛОЙ RAG ==========================
32 теста(ов) не выполнялись: в этом окружении нет эмбеддера. Индексация, чанкинг и поиск заглушками не моделируются — правка RAG этим прогоном НЕ проверена. Ставить deps в worktree НЕ надо, прогнать интерпретатором сервера:
  /home/kesha/orchestra/.venv/bin/python -m pytest tests/test_rag.py
  test_backfill_files_stops_inside_the_slice_on_deadline, test_backfill_indexes_md_only, test_backfill_logs_dedup_second_run, test_backfill_logs_limit_bounds_one_pass, test_backfill_logs_session_name_filter, test_backfill_logs_stops_inside_the_slice_on_deadline, test_backfill_logs_type_and_length_filter, test_backfill_prunes_deleted, test_backfill_second_run_no_changes, test_backfill_skips_git_ignored_files, test_delete_file_removes_all, test_empty_query_returns_empty, test_freshest_file_is_indexed_first, test_index_file_creates_rows, test_index_file_idempotent_same_content, test_index_log_creates_rows, test_index_log_dedup, test_interrupted_pass_resumes_instead_of_restarting, test_pending_files_counts_missing_and_stale, test_prune_runs_before_embedding_so_a_cut_short_pass_still_drops_phantoms, test_readonly_conn_cannot_write, test_readonly_conn_sees_writes_and_searches, test_reindex_changed_content_replaces, test_reindex_reuses_embeddings_of_unchanged_chunks, test_reused_vectors_are_the_same_bytes, test_same_path_different_projects_coexist, test_search_cross_project_optin, test_search_file_and_log_sources, test_search_kinds_filter, test_search_never_returns_a_file_deleted_from_disk, test_search_project_isolation, test_walk_indexes_everything_when_git_is_unavailable
349 passed, 32 skipped, 1 deselected in 13.31s
```

## T4 — fail-safe dashboard bubbles

- `app/static/js/chat.js`: validates finite origin + object detail + non-empty string senders before choosing layout. Only validated `user` uses `chat-user`; every other/missing/malformed case becomes a visible Unknown/typed `chat-bot` bubble with sender label.
- Named oracle: `env PYTHONPATH=. uv run pytest -q docs/tasks/433/test_t4_frontend_origin_433.py` → `1 passed`.
- Focused existing browser regressions run in separate processes (combined sync-Playwright fixtures produced the known running-loop setup error and are excluded): `tests/test_system_chat_entry.py` → `1 passed`; timeline + photo gallery → `2 passed`.
- Mutation: validated-user production marker before/after = 1/1; unsafe `suppliedOrigin === 'user'` mutant marker during = 1; RC=1 at `user-missing-detail origin rendered as the user`; restored `touch` repeat → `1 passed`.

## Final-gate A/B classification before compatibility edits

Counting rule: classify every node in `comparison.branch_only_bad` from `docs/tasks/433/verification/pre-fix/failure-sets.json` exactly once. `A` is a stale test helper/fake/direct call that encodes the removed provenance-free API. `B` is a production path broken by the required boundary. This record was committed before any compatibility edit.

### A — stale provenance-free test contract (96)

- A — `tests/test_audit0901_db.py::test_restart_mid_delivery_sends_run_result_instead_of_interruption` — delivery callback fake rejects the newly required provenance keyword.
- A — `tests/test_audit0901_delivery.py::test_blocked_queue_is_named_to_the_sender_and_a_restart_clears_it` — direct durable-accept setup omits provenance.
- A — `tests/test_audit0901_session.py::test_drain_landing_during_stale_cli_release_refuses_the_turn` — direct AgentSession.send setup omits provenance.
- A — `tests/test_audit0901_tg.py::test_late_transcription_still_reaches_the_agent` — recording manager fake rejects the provenance keyword.
- A — `tests/test_bug_report_notify.py::test_cross_project_report_goes_to_the_platform_owner` — notification manager fake rejects the provenance keyword.
- A — `tests/test_bug_report_notify.py::test_notification_is_sent_once_per_record` — notification manager fake rejects the provenance keyword.
- A — `tests/test_bug_report_notify.py::test_platform_owner_is_notified` — notification manager fake rejects the provenance keyword.
- A — `tests/test_bug_report_notify.py::test_report_survives_a_failed_notification` — notification manager fake rejects the provenance keyword.
- A — `tests/test_bug_report_notify.py::test_root_orchestrator_wins_over_sub_orchestrator` — notification manager fake rejects the provenance keyword.
- A — `tests/test_db.py::TestLogs::test_log_types` — direct user_message add_log setup omits provenance.
- A — `tests/test_fan_barrier_gates.py::test_message_without_sender_is_never_buffered` — direct durable-accept setup omits provenance.
- A — `tests/test_fan_barrier_intercept.py::test_t1_three_durable_reports_create_exactly_one_parent_wake` — recording manager fake rejects the provenance keyword.
- A — `tests/test_fan_completion_modes_407.py::test_t2_buffered_receipt_never_enters_dispatching_state` — direct durable-accept setup omits provenance.
- A — `tests/test_fan_completion_modes_407.py::test_t2_known_pre_submit_failure_rearms_fan_and_same_receipt_retries` — direct durable-accept setup omits provenance.
- A — `tests/test_fan_completion_modes_407.py::test_t2_mixed_explicit_silent_and_failed_turns_wake_parent_once` — direct durable-accept setup omits provenance.
- A — `tests/test_fan_completion_modes_407.py::test_t2_releasing_report_replays_as_manifest_after_preparation_crash` — direct durable-accept setup omits provenance.
- A — `tests/test_fan_enable.py::test_impl5_exact_silent_marker_completes_fan_without_manifest_noise` — recording manager fake rejects the provenance keyword.
- A — `tests/test_fan_enable.py::test_impl5_silent_completion_wakes_reducer_not_parent` — recording manager fake rejects the provenance keyword.
- A — `tests/test_fan_terminal_kind.py::test_tool_report_then_turn_end_is_one_terminal_and_one_wake` — direct durable-accept setup omits provenance.
- A — `tests/test_fan_terminal_kind.py::test_turn_end_after_a_question_is_still_terminal` — direct durable-accept setup omits provenance.
- A — `tests/test_fd_adopt.py::test_t9_stale_adopted_session_respawns_cli_on_next_turn` — direct AgentSession.send setup omits provenance.
- A — `tests/test_hot_apply.py::test_t1_broken_role_file_falls_back_to_the_startup_prompt` — direct AgentSession.send setup omits provenance.
- A — `tests/test_hot_apply.py::test_t1_guard_custom_full_prompt_is_not_overwritten_by_rebuild` — direct AgentSession.send setup omits provenance.
- A — `tests/test_hot_apply.py::test_t1_reinjected_prompt_rebuilds_role_text_from_disk` — direct AgentSession.send setup omits provenance.
- A — `tests/test_hot_apply.py::test_t2_gate_closes_atomically_against_turn_start` — direct AgentSession.send setup omits provenance.
- A — `tests/test_hot_apply.py::test_t2_new_turn_is_refused_loudly_while_draining` — direct AgentSession.send setup omits provenance.
- A — `tests/test_mailbox.py::test_impl3_escalates_to_normal_delivery_when_continuation_fails` — mailbox session fake rejects the provenance keyword.
- A — `tests/test_mailbox.py::test_t3_drains_at_turn_end_instead_of_waking` — mailbox session fake rejects the provenance keyword.
- A — `tests/test_manager.py::TestEnsureLoadedSingleFlight::test_simultaneous_model_change_and_send_share_one_cold_load` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_manager.py::TestRestartWake::test_graceful_restart_wakes_interrupted_worker` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_manager.py::TestRestartWake::test_hard_kill_restart_still_wakes_worker` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_manager.py::TestSendAndControl::test_auto_switch_exceptions_have_detail_and_keep_quarantine[resolve]` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_manager.py::TestSendAndControl::test_auto_switch_exceptions_have_detail_and_keep_quarantine[switch]` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_manager.py::TestSendAndControl::test_auto_switch_failure_keeps_quarantine_and_surfaces_git_error` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_manager.py::TestSendAndControl::test_auto_switch_persist_failure_requarantines_without_delivery` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_manager.py::TestSendAndControl::test_concurrent_sends_switch_once_and_deliver_serially` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_manager.py::TestSendAndControl::test_delivery_owns_commit_point_despite_repeated_cancellation[backend]` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_manager.py::TestSendAndControl::test_delivery_owns_commit_point_despite_repeated_cancellation[persist]` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_manager.py::TestSendAndControl::test_delivery_owns_commit_point_despite_repeated_cancellation[switch]` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_manager.py::TestSendAndControl::test_running_send_preserves_mid_turn_delivery` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_manager.py::TestSendAndControl::test_send_rechecks_needs_switch_after_session_lock` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_manager.py::TestSendAndControl::test_send_routes` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_manager.py::TestSendAndControl::test_send_unknown_raises` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_manager.py::TestSendAndControl::test_send_waits_for_lifecycle_holder_before_git_and_backend` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_manager.py::TestSendAndControl::test_waiting_needs_switch_rejects_without_git_or_backend` — direct SessionManager.send calls or recording session fakes omit/reject provenance.
- A — `tests/test_restart_inbox.py::test_269_a_hanging_delivery_does_not_block_the_rest_of_the_queue` — restart-inbox manager fakes reject the provenance keyword.
- A — `tests/test_restart_inbox.py::test_269_aborted_restart_still_delivers_what_it_promised` — restart-inbox manager fakes reject the provenance keyword.
- A — `tests/test_restart_inbox.py::test_269_failed_delivery_stays_queued_for_the_next_start` — restart-inbox manager fakes reject the provenance keyword.
- A — `tests/test_restart_inbox.py::test_269_message_during_restart_is_queued_instead_of_pushed` — restart-inbox manager fakes reject the provenance keyword.
- A — `tests/test_restart_inbox.py::test_269_message_for_a_session_that_never_came_back_is_given_up_and_reported` — restart-inbox manager fakes reject the provenance keyword.
- A — `tests/test_restart_inbox.py::test_269_queued_messages_are_delivered_once_after_startup` — restart-inbox manager fakes reject the provenance keyword.
- A — `tests/test_run_fan_407.py::test_t3_deadline_closes_fan_and_wakes_parent_without_another_tool_call` — fan wake manager fake rejects the provenance keyword.
- A — `tests/test_runtime_handoff_recovery.py::test_recovery_required_blocks_send_before_backend_use` — direct AgentSession.send setup omits provenance.
- A — `tests/test_session.py::TestClaudeTurnLifecycle::test_imported_claude_listener_reconnect_refreshes_history_from_logs` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestCodexTurnLifecycle::test_native_compact_cannot_leak_lifecycle_into_next_listener` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestCompactGuards::test_compact_logs_preamble_as_user_message` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestCompactReArmsPromptInjection::test_personal_memory_written_mid_session_is_re_read_from_disk` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestCompactReArmsPromptInjection::test_prompt_reinjection_reads_worktree_memory_not_parent_copy` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestCompactReArmsPromptInjection::test_role_is_back_in_the_prompt_on_the_turn_after_compact` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestHibernateDeliveryRaces::test_failed_steer_queues_before_hibernate_can_observe_state` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestHibernateDeliveryRaces::test_send_wakes_without_changing_native_session_id` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestManifestEffortAtTurnBoundary::test_broken_manifest_keeps_current_effort` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestManifestEffortAtTurnBoundary::test_effort_follows_model_switch_without_manifest_edit` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestManifestEffortAtTurnBoundary::test_legacy_session_without_role_is_untouched` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestManifestEffortAtTurnBoundary::test_manifest_edit_applies_on_next_turn` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestManifestEffortAtTurnBoundary::test_role_without_effort_keeps_db_value` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestManifestEffortAtTurnBoundary::test_running_turn_is_not_interrupted` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestManifestEffortAtTurnBoundary::test_typo_in_level_keeps_live_agent_on_current_effort` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestManifestEffortAtTurnBoundary::test_unchanged_manifest_rebuilds_nothing` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestPrecompactTimer::test_codex_native_compact_queues_message_until_completion` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestRateLimitClassification::test_new_user_message_resets_retry_budget` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestRuntimeCapabilities::test_codex_runtime_steers_mid_turn_message` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestRuntimeCapabilities::test_non_steering_runtime_queues_mid_turn_message` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestRuntimeCapabilities::test_runtime_handoff_is_one_shot_user_message_context` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestRuntimeCapabilities::test_text_tail_v1_keeps_last_ten_users_and_assistant_text_only` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestSend::test_send_idle_sets_running` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestSend::test_send_on_running_queues_message` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestStart::test_with_message_sets_running_then_idle` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestStop::test_message_waits_for_interrupt_before_starting_clean_turn` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestStop::test_stop_marks_running_session_interrupted` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestTurn::test_connect_error_returns_to_idle` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestTurn::test_stale_claude_resume_uses_bounded_log_handoff` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestTurn::test_turn_end_returns_to_idle` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestWeeklyQuotaAdmission::test_decision_expiring_before_lock_reacquire_is_rechecked` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestWeeklyQuotaAdmission::test_idle_available_worker_starts_exactly_one_backend_turn` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestWeeklyQuotaAdmission::test_idle_worker_is_blocked_before_log_status_or_backend` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestWeeklyQuotaAdmission::test_model_change_during_refresh_rechecks_new_bucket` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestWeeklyQuotaAdmission::test_orchestrator_idle_turn_never_reads_quota` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestWeeklyQuotaAdmission::test_running_steering_never_reads_quota` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::TestWeeklyQuotaAdmission::test_stop_during_refresh_cancels_delayed_start` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::test_idempotent_handoff_reuses_frozen_project_bytes` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::test_t1_385_message_during_deferred_interrupt_queues_until_native_terminal` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::test_tool_metadata_is_persisted_with_log` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_session.py::test_two_db_backed_claude_connects_render_identical_history` — direct AgentSession.send/add_log calls or local fakes omit/reject provenance.
- A — `tests/test_undelivered.py::TestNotifyHasNoInventedRecipient::test_reports_to_scope_orchestrator` — notification manager fakes reject the provenance keyword.
- A — `tests/test_undelivered.py::test_bg_job_failure_reaches_the_orchestrator` — notification manager fakes reject the provenance keyword.

### B — genuine production regression (1)

- B — `tests/test_project_roadmap_backend_425.py::test_t2_wait_text_delivery_targets_opener_and_resolves_only_on_submission` — `app/routes/portfolio.py:342` invokes `accept_message_delivery` without constructing provenance; the request reaches production code before the test fails.

### Additional completeness failure outside the 97-node set

- B — `app/portfolio_watchdog.py:188` — the refrozen AST oracle found a second direct `accept_message_delivery` call with no provenance. No final-suite node exercised it, which is exactly why call-site completeness cannot be inferred from the failure set.

## Completeness re-freeze and writer fixes

- Blindness cause: the original AST scanner recognized only calls shaped as `<object>.send`, `<object>.send_initial_delivery`, or `<object>.send_message_delivery`. It never classified either a qualified `message_deliveries.accept_message_delivery(...)` call or a directly imported `accept_message_delivery(...)` call as an ingress writer.
- Refrozen RED commit: `e5c1548588f285d104920cb5a4be1adb9c003cf2`. Before either production fix, `test_t3_every_ingress_constructs_provenance_before_send` failed with both offenders: `app/portfolio_watchdog.py:188:accept_message_delivery, app/routes/portfolio.py:342:accept_message_delivery`.
- `app/routes/portfolio.py`: operator wait response now carries `origin=user`, sender `user`, subtype `portfolio_wait_answer`, ref delivery id.
- `app/portfolio_watchdog.py`: watchdog wake now carries `origin=platform`, sender `portfolio-watchdog`, subtype `portfolio_watchdog`, ref delivery id.
- Independent mutations: removing only `provenance=provenance` from the portfolio route made the refrozen oracle fail on that route (`RC=1`); restoring it gave `1 passed`. Removing only the watchdog keyword made the oracle fail on the watchdog (`RC=1`); restoring it gave `1 passed`. Each production marker counted `before=1, after=1`.
- Required-boundary mutation: `AgentSession.send` production marker counted `before=1, after=1`; optional mutant marker counted `during=1, after=0`; `test_t2_manager_entry_preserves_session_lock_and_auto_switch` failed at `#433 provenance must stay mandatory at AgentSession.send` (`RC=1`), then passed after restore + `touch`.
- Compatibility repair result: the exact 97-node pre-fix `branch_only_bad` set now reports `97 passed in 7.25s`. Fakes have explicit provenance parameters and finite-field assertions; no permissive `MagicMock` provenance fallback was added.

## T5 — offline migration

- `scripts/migrate_message_provenance_433.py`: explicit `--db`, dry-run by default, receipt-first classification, frozen prefix/181 rules, immutable B1 receipts, single `BEGIN IMMEDIATE` transaction, manifest receipt, canonical details, unique temporary backup plus atomic no-overwrite hard-link publication.
- Named T5 oracle plus backup/manifest controls: `env PYTHONPATH=. uv run pytest -q docs/tasks/433/test_t5_offline_migration_433.py tests/test_message_provenance_migration_433.py` → `4 passed`.
- Receipt-precedence mutation: production marker before/after `1/1`; bypassing receipts for text classification made the frozen T5 oracle fail on all five contradictory receipt rows (`RC=1`); restored repeat → `1 passed`.
- Backup-overwrite compound mutation: existence-guard marker before/after `1/1`, atomic-link marker before/after `1/1`; replacing the no-overwrite path made `test_t5_existing_backup_is_never_overwritten` fail (`RC=1`); restored repeat → `1 passed`.
- Temporary-DB demonstration, verbatim:

```text
DRY_UNKNOWN_BEFORE=6
DRY_RC=0
DRY_STDOUT={"counts": {"agent": 1, "background_task": 1, "platform": 1, "system": 1, "unknown": 1, "user": 1}, "invalid": 0, "mode": "dry-run", "rows_after": 6, "rows_before": 6, "sessions_after": 1, "sessions_before": 1, "target": "/tmp/provenance-433-demo-0y__qm_3/target.db", "updated": 0, "would_update": 5}
DRY_UNKNOWN_AFTER=6
ROLLBACK_RC=2
ROLLBACK_STDERR=migration failed: IntegrityError: forced-mid-433
ROLLBACK_CHANGED_ROWS=0
APPLY_RC=0
APPLY_STDOUT={"counts": {"agent": 1, "background_task": 1, "platform": 1, "system": 1, "unknown": 1, "user": 1}, "invalid": 0, "mode": "apply", "rows_after": 6, "rows_before": 6, "sessions_after": 1, "sessions_before": 1, "target": "/tmp/provenance-433-demo-0y__qm_3/target.db", "updated": 5, "would_update": 5}
WAL_READER_UNKNOWN_BEFORE=6
WAL_READER_UNKNOWN_AFTER=6
WAL_NEW_READER_UNKNOWN=1
BACKUP_PREIMAGE_UNKNOWN=6
REAPPLY_RC=0
REAPPLY_STDOUT={"counts": {"agent": 1, "background_task": 1, "platform": 1, "system": 1, "unknown": 1, "user": 1}, "invalid": 0, "mode": "apply", "rows_after": 6, "rows_before": 6, "sessions_after": 1, "sessions_before": 1, "target": "/tmp/provenance-433-demo-0y__qm_3/target.db", "updated": 0, "would_update": 0}
MANIFEST_DRIFT_RC=2
MANIFEST_DRIFT_STDERR=migration failed: ValueError: manifest drift: supplied classification rules do not match message-provenance-433-v1
EXISTING_BACKUP_RC=2
EXISTING_BACKUP_STDERR=migration failed: ValueError: backup path already exists: /tmp/provenance-433-demo-0y__qm_3/pre-apply.db
EXISTING_BACKUP_HASH_UNCHANGED=True
SYMLINK_ALIAS_RC=2
SYMLINK_ALIAS_STDERR=migration failed: ValueError: backup path aliases the database path
```

- `data/orchestra.db` was not passed to the script for dry-run, apply, or inspection. Production dry-run/apply remains a separate orchestrator gate.

## Final six-shard comparison

- Baseline: `main` at `46216373`; branch already contains it (`HEAD..main=0`). Collection: branch `3673/3676`, base `3658/3661`, each with three deselections. Task-owned review/migration oracles pass separately in the 47-test core command.
- Common files were partitioned into six file shards with branch-side `610/610/610/610/610/609` collected nodes. `tests/test_seamless_restart.py` runs last in its shard: running later tests after it reproducibly killed the process at `RC=137`, while last position produced a terminal summary on both sides.
- All twelve final processes ended with allowed `RC=1` and terminal summaries. Base failed set = 48, branch failed set = 47, intersection = 47, `branch-only=0`, `base-only=1`. The final base-only node is `tests/test_harness_tools.py::test_t1_grep_perf_repo_tree`; the branch does not change that timing-based test or `app/harness/`, so this is baseline measurement variance, not a claimed fix. In the earlier comparison the base-only node was `tests/test_session.py::test_tool_metadata_is_persisted_with_log`; that task-owned assertion was made deterministic by comparing the complete `tool_is_error → kwargs` mapping instead of asynchronous insertion order.
- Frozen/task-only verification is separate from browser fixtures: core T1/T2/T3/T5 + three migration-safety tests → `31 passed in 3.46s`; T4 browser oracle → `1 passed in 0.45s`. The combined browser+async process is excluded because the session-scoped sync Playwright loop causes the already documented `Runner.run() cannot be called from a running event loop` setup conflict.
- Only non-derivable evidence is retained: pre-fix/final `failure-sets.json` plus `failure-set-summary.txt` under `docs/tasks/433/verification/`. Raw pytest and collection logs and generated shard lists were removed because the commands reproduce them.

## Pre-mortem checks

- A direct durable accept bypasses provenance → whole-`app/` AST oracle plus two independent call-site mutations.
- A fake accepts arbitrary fields and hides a missing production keyword → every changed fake has an explicit signature; the required-boundary mutation remains red.
- Receipt text overrides authenticated source data → contradictory receipt/prefix fixture plus receipt-bypass mutation.
- Apply partially commits or disrupts a WAL reader → trigger rollback count `0` and stable old-reader count `6` while the new reader sees `1` unknown.
- Backup aliases or overwrites protected state → existing-file hash unchanged and symlink alias rejected; both cases are committed behavioral tests.
- Missing/invalid frontend provenance renders as the human → T4 computed-class/style negative controls and unsafe-user mutation.

## Review decision gate

- Changed consumers: shared session/manager delivery, durable initial/direct receipts, SQLite log schema and projections, TG/RAG/runtime-history consumers, dashboard snapshot/SSE rendering, portfolio route/watchdog, and the offline migration/backup path.
- Author metadata: `gpt-5.6-sol`, Codex runtime, xhigh, full-cycle (task metadata recorded during Phase 1).
- Exact AC: five frozen `_433` ticket oracles; explicit provenance at every discovered ingress; text-independent consumers; fail-safe left bubble; dry-by-default atomic idempotent migration; final failed-node set comparison with `branch-only=0`.
- Named evidence: post-ceiling T1/T2/T3/T5 plus Sol regression oracles `47 passed`; T4 `1 passed`; three live-ingress controls (real operator cookie, direct TG bridge, keyed MCP receipt) `3 passed`; authenticated compatibility set `7 passed`; final six-shard `branch-only_bad_count=0`. Every accepted blocker has a committed RED oracle and a red mutation followed by restore + `touch`.
- Review route: Sol, three rounds, artifact `docs/tasks/433/codex-review-sol.md`. Round 1 found nine blockers; all were fixed and independently mutated. Round 2 found four further blockers; all were fixed and independently mutated. **Sol Round 3 — NEEDS WORK, один блокер закрыт ПОСЛЕ потолка раундов, вердикта ревьюера на эту правку нет**. The post-ceiling trigger oracle `test_review_receipt_hash_is_revalidated_after_log_triggers` was RED before the fix, green after moving the final receipt-hash check immediately before commit, and RED again when that final check was mutated away (`before/after marker=1/1`, mutant `RC=1`). No fourth review was run.

## Post-merge mapped gate

- `tests/test_runtime_history.py::test_installed_claude_history_versions_match_pins` снят с автоматического гейта как `live_probe`; `CLAUDE_CLI_HISTORY_VERSION = "2.1.197"` не менялась, вопрос «совместим ли наш рендерер с 2.1.258» остаётся ОТКРЫТЫМ и вынесен оркестратором отдельно.
- Runtime-history mapped command: `19 passed, 1 deselected`; explicit inventory control plus file: `20 passed, 1 deselected`.
- The 17 pre-existing mapped failures were classified before edits, repaired test-only, and now report `17 passed`; production durable-binding behavior was not changed. Removing the durable target-binding guard made the committed negative control fail (`RC=1`, production marker before/after `1/1`), then restore + `touch` returned `4 passed`.
- `tests/test_merge_test_gate.py::test_linked_worktree_symlinked_python_retains_venv_packages` failed because its synthetic venv hardcoded Python 3.12.3 at `/usr/bin/python3` while the suite runs Python 3.13 from the uv-managed base interpreter; production interpreter selection was not broken. The test now derives `sys._base_executable` and the running version while preserving the linked-worktree + symlinked-python behavior under test.
- Final mapped gate selected 36 files and passed all six batches: `201 + 132 + 90 + 395 + 50 + 486 = 1354 passed`, `32 skipped`, `1 live_probe deselected`, overall `status=passed`, `exit_code=0`.

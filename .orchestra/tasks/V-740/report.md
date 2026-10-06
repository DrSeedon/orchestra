# V-740 — suppress parent reports for owner-started turns

`59f23412` changed the report eligibility check from “has a task sender” to “has a task sender or a persistent parent name.” The persistent parent correctly restores reporting after restart, but it also made a direct dashboard/TG turn report to the parent when `last_task_sender` remained from an earlier task. The route only refreshes that transient value when `req.sender` is present; background-job triggers deliberately restore it from `parent_name`.

The fix records whether the active turn began with owner provenance. `AgentSession.send()` derives it from `MessageProvenance` (`origin="user"`, or unauthenticated dashboard provenance `origin="unknown", subtype="dashboard"`). The marker follows owner messages queued during a running/compacting turn and is restored if `_flush_pending` has to retain those messages after a failed start. `fire_auto_report()` skips only its normal parent auto-report for such a turn. Fan-barrier completion remains ahead of that check; `report_abnormal_end()` explicitly permits the report. A new session after restart starts with the marker clear, so the existing `parent_name` recovery path still works.

| Acceptance case | Result | Evidence |
|---|---|---|
| Owner-started dashboard/user turn does not report to stale parent | Fixed | `test_owner_provenance_through_send_suppresses_parent_report` runs actual `AgentSession.send()` for authenticated user and unauthenticated dashboard provenance. `test_owner_started_turn_does_not_report_using_stale_parent_sender` covers both markers. |
| Orchestrator task still reports | Preserved | `test_parent_task_and_bg_job_provenance_through_send_still_report` checks `origin="agent"`; existing `test_auto_report_fires_for_parented_worker_without_sender_metadata` covers restart-restored `parent_name`. |
| Background-job wake still reports | Preserved | `test_parent_task_and_bg_job_provenance_through_send_still_report` invokes `BgJobManager._restore_report_provenance()` and runs the `background_task` turn through send/end. Existing `test_completed_job_restores_parent_report_provenance` also passed. |
| Abnormal end on parented task still reports | Preserved | `test_abnormal_end_still_reports_owner_started_turn` exercises `report_abnormal_end()` with owner suppression set; its explicit abnormal path still calls the parent callback. |

The tests were committed in `82347f73` before mutation checks. Three committed-test mutations were tried and reverted: removing the owner-turn gate made both owner provenance cases fail; removing the turn-start provenance classification made both actual-send cases fail; removing the abnormal-end override made the abnormal case fail.

## Verification

Ran all tests matching the explicit source coverage for `session_turns`, `fire_auto_report`, `report_abnormal_end`, `bg_jobs`/`BgJobManager`, and `routes/sessions`: **69 test files, 1,441 passed, 6 skipped** in 152.81 seconds. Command used `/home/kesha/orchestra/.venv/bin/python -m pytest -q` with the paths below, passed via `xargs` so all paths reached pytest as separate arguments. The first launch attempt did not run tests because `/bin/sh` lacks Bash `mapfile` (exit 127); the same list then completed successfully using POSIX-compatible `xargs`.

The passing run emitted four existing test-runtime warnings: one unawaited `_S._notify_scope_idle` coroutine in `tests/test_mailbox.py`; two `fork()` deprecation warnings in `tests/test_merge_operations.py`; and a subprocess transport finalizer warning (`RuntimeError: Event loop is closed`) in `tests/test_tg_bridge.py`. The broad run completed with exit code 0. `py_compile` and `git diff --check` also passed. Imported application modules resolved to this worktree:

`/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/session.py`

`/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/session_turns.py`

`/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/bg_jobs.py`

`/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/routes/sessions.py`

Test paths run:

```text
tests/test_acceptance.py
tests/test_adhoc_switch.py
tests/test_agentic_compact_650.py
tests/test_antigravity_runtime.py
tests/test_api.py
tests/test_audit0901_delivery.py
tests/test_audit0901_session.py
tests/test_auto_report_send_result.py
tests/test_backend_codex.py
tests/test_backend_harness_turn_usage_422.py
tests/test_bg_jobs.py
tests/test_change_model_unloaded.py
tests/test_codex_mailbox_703.py
tests/test_codex_writer_conflict_536.py
tests/test_compact_gate_438.py
tests/test_compact_pending_ack_467.py
tests/test_compact_receipt_and_tail.py
tests/test_durable_steering_562.py
tests/test_fan_barrier.py
tests/test_fan_barrier_gates.py
tests/test_fan_completion_modes_407.py
tests/test_fan_enable.py
tests/test_fan_report_delivery.py
tests/test_fan_report_final_selection_480.py
tests/test_fan_terminal_kind.py
tests/test_handoff_effect_classification.py
tests/test_hot_apply.py
tests/test_identity_drift.py
tests/test_initial_deliveries.py
tests/test_layout_batch_v704.py
tests/test_lifecycle_quarantine_499.py
tests/test_limit_wake.py
tests/test_logs_sync.py
tests/test_mailbox.py
tests/test_mcp_codex_review.py
tests/test_merge_completion_watch.py
tests/test_merge_operations.py
tests/test_merge_ref_gate.py
tests/test_merge_stuck.py
tests/test_merge_target_oracle_386.py
tests/test_message_delivery_receipts_380.py
tests/test_message_provenance_review_433.py
tests/test_model_gates.py
tests/test_model_text_control_flow.py
tests/test_models.py
tests/test_owner_auto_report.py
tests/test_pidfd_leaks.py
tests/test_rate_limit_exact_v707.py
tests/test_restart_generation_liveness.py
tests/test_return_to_merged_branch.py
tests/test_runtime_handoff_v2.py
tests/test_send_provenance_without_auth.py
tests/test_session.py
tests/test_session_logs_conditional.py
tests/test_sessions_conditional.py
tests/test_spawn_resume_695.py
tests/test_stall_signals_642.py
tests/test_switch_after_continue_620.py
tests/test_task_binding_417.py
tests/test_task_tracker_integration.py
tests/test_taskless_delivery_702.py
tests/test_tg_bridge.py
tests/test_turn_ended_no_quota_suffix.py
tests/test_turn_signals.py
tests/test_turn_usage.py
tests/test_unbound_merge_recovery_702.py
tests/test_undelivered.py
tests/test_work_acceptance.py
tests/test_work_review_jobs.py
```

No restart was performed. The Python changes require the owner-initiated Orchestra restart to take effect.

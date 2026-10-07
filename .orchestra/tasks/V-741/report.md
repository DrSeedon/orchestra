# V-741 — failed direct-message delivery and worktree layout

## Result

A `FAILED_BEFORE_SUBMIT` transition now transactionally creates a durable notice for a sender whose stored provenance is `agent` and whose `source_session_id` is set. The notice names the target, original `delivery_id`, error code, and error message, and is sent with platform provenance and a stable event ID. A logged event marks the notice delivered, so startup recovery does not replay it after a process restart. The startup recovery is scheduled after session resume and is included in owned-task shutdown. Successful and `WAITING_QUOTA` deliveries create no notice; owner-origin deliveries have no agent wake.

The additive `message_delivery_failure_notices` table is part of `app/schema.sql` and is also created with `IF NOT EXISTS` from the runtime seam, so an existing schema-v3 database gets it on startup without an offline schema bump.

A missing worker `.orchestra/layout.json` now skips only optional worker-memory injection while a durable direct message is being delivered. `AgentSession.send` enables this path only when it has a delivery context. Session creation, resume, and ordinary prompt assembly retain the existing loud layout errors and migration behavior. The skip emits a log line. This preserves dirty-worktree and old-base migration safeguards.

## Changes

- `app/message_deliveries.py`: persist failure notices in the same transaction as a `FAILED_BEFORE_SUBMIT` state update; deliver and recover notices by stable delivery identity.
- `app/session.py`, `app/manager.py`, `app/prompting.py`: pass a delivery-only flag through prompt refresh, allowing unavailable worker memory to be skipped without weakening ordinary layout validation.
- `app/main.py`, `app/schema.sql`: create the notice store for new and existing databases, retry pending notices after restart, and cancel the recovery task at shutdown.
- `tests/test_message_delivery_failure_notices_741.py`: failure wake with error and delivery identity, no wake for successful/quota-waiting/owner-origin cases, replay after a simulated restart, delivery through a worktree without layout metadata, and a real `AgentSession.send` delivery-context path paired with a plain-send layout refusal.
- `tests/test_orchestra_layout_430.py`: restore the prior `app.orchestra_layout` module registration after loading its isolated migration implementation. Leaving the replacement in `sys.modules` made later tests import a second `LayoutMigrationError` class and caused unrelated layout and lifespan checks to fail in a combined run.
- `TODO.md`: remove the resolved defect; `CHANGELOG.md`: record the fix.

## Verification

`uv run --frozen python -m pytest` was run on the 112 test files listed in [`test-files.txt`](test-files.txt); result: **2331 passed, 22 skipped, 3 deselected** in 396.05 seconds. The log is [`full-tests.log`](full-tests.log). After adding the production-wiring test, the V-741 test file passed **6 tests**. The relevant layout/lifecycle/message subset passed **62 tests**. `py_compile`, `git diff --check`, and `python scripts/check_instruction_contract.py` passed.

After regression tests were committed in `b5ab24c0`, mutation checks disabled the agent-origin notice condition and the delivery-only missing-layout allowance. The committed sender-wake tests failed on the first mutation; the committed no-layout delivery test failed on the second. After the follow-up test was committed in `a56c7c04`, setting all three `allow_missing_layout=delivery is not None` arguments in `app/session.py` to `False` made the real `AgentSession.send` test fail with `ORCHESTRA_LAYOUT_MISSING`; without that mutation, the same test confirms that an ordinary send raises that error while a direct delivery succeeds. All mutations were reverted. The final V-741 test file passed **6 tests**. A focused V-741 plus parked `TARGET_TASK_CHANGED` run previously passed **6 tests**.

The test selection used `rg -l -g 'test*.py' 'message_deliveries|mcp_stdio|orchestra_layout|AgentSession|\.send\(' tests`, sorted into `test-files.txt`. It includes tests for direct MCP sends, delivery receipts, layout migration, and session send paths.

## Exact test file list

```text
tests/test_acceptance.py

Imported application modules were loaded from:

- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/message_deliveries.py`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/prompting.py`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/session.py`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/manager.py`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/main.py`

The broad test run reported one existing `RuntimeWarning` for an unawaited `_S._notify_scope_idle` coroutine in `tests/test_mailbox.py`, plus a `RuntimeError: Event loop is closed` from an asyncio subprocess transport finalizer after pytest completion. The suite returned exit code 0. No service restart was performed.
tests/test_acceptance.py
tests/test_agentic_compact_650.py
tests/test_antigravity_readiness.py
tests/test_antigravity_runtime.py
tests/test_api.py
tests/test_audit0901_delivery.py
tests/test_audit0901_harness.py
tests/test_audit0901_mcp.py
tests/test_audit0901_session.py
tests/test_auto_report_send_result.py
tests/test_backend_codex.py
tests/test_backend_grok.py
tests/test_backend_harness_turn_usage_422.py
tests/test_bg_jobs.py
tests/test_bug_report_notify.py
tests/test_charts.py
tests/test_chat_history_transfer.py
tests/test_codex_bin_resolution.py
tests/test_codex_mailbox_703.py
tests/test_codex_quota_103.py
tests/test_codex_review_sandbox.py
tests/test_codex_writer_conflict_536.py
tests/test_compact_gate_438.py
tests/test_compact_pending_ack_467.py
tests/test_compact_receipt_and_tail.py
tests/test_cross_repo_warning.py
tests/test_delivery_head_of_line_block.py
tests/test_delivery_queue_block_connection.py
tests/test_durable_steering_562.py
tests/test_dynamic_workflows.py
tests/test_errtext.py
tests/test_fan_barrier_gates.py
tests/test_fan_barrier_intercept.py
tests/test_fan_completion_modes_407.py
tests/test_fan_report_delivery.py
tests/test_fd_adopt.py
tests/test_gigachat_harness.py
tests/test_handoff_effect_classification.py
tests/test_harness_inject.py
tests/test_hot_apply.py
tests/test_initial_deliveries.py
tests/test_initial_delivery_review_regressions.py
tests/test_legacy_pipeline_skills.py
tests/test_lifecycle_quarantine_499.py
tests/test_limit_wake.py
tests/test_listen_task_done_648.py
tests/test_log_write_loss.py
tests/test_mailbox.py
tests/test_manager.py
tests/test_mcp_codex_review.py
tests/test_mcp_config_isolation.py
tests/test_mcp_quota_gate.py
tests/test_mcp_resolve_operation_423.py
tests/test_mcp_stdio.py
tests/test_merge_completion_watch.py
tests/test_merge_progress_424.py
tests/test_merge_reason_preservation_416.py
tests/test_merge_target_oracle_386.py
tests/test_message_delivery_failure_notices_741.py
tests/test_message_delivery_receipts_380.py
tests/test_message_provenance_migration_433.py
tests/test_message_provenance_review_433.py
tests/test_model_gates.py
tests/test_model_text_control_flow.py
tests/test_native_history_import.py
tests/test_orchestra_layout_430.py
tests/test_orchestra_layout_compat_430.py
tests/test_orchestra_layout_dirty_430.py
tests/test_orchestra_layout_fleet_430.py
tests/test_orchestra_layout_recovery_430.py
tests/test_orchestra_layout_repair_base_v611.py
tests/test_orchestrators_payload.py
tests/test_owned_dirs_migration_473.py
tests/test_owner_auto_report.py
tests/test_p1_union.py
tests/test_p4_cost.py
tests/test_pipeline.py
tests/test_project_context_review_488.py
tests/test_prompt_parent_selection.py
tests/test_quota_wait_queue.py
tests/test_reducer_role.py
tests/test_restart_durable_transfer.py
tests/test_restart_generation_liveness.py
tests/test_restart_inbox.py
tests/test_review_receipt_start_436.py
tests/test_review_requester_roles.py
tests/test_review_retirement.py
tests/test_runtime_handoff_recovery.py
tests/test_runtime_handoff_v2.py
tests/test_runtime_registry.py
tests/test_service_lifecycle_537.py
tests/test_session.py
tests/test_sessions_conditional.py
tests/test_spawn_resume_695.py
tests/test_stall_signals_642.py
tests/test_subagents.py
tests/test_task_runtime.py
tests/test_task_tracker_integration.py
tests/test_taskless_delivery_702.py
tests/test_taskless_merge_no_id_702.py
tests/test_tg_bridge.py
tests/test_tg_file_deliveries.py
tests/test_tool_scoping.py
tests/test_turn_ended_no_quota_suffix.py
tests/test_turn_signals.py
tests/test_undelivered.py
tests/test_undelivered_queue.py
tests/test_vps_task_prefix.py
tests/test_work_acceptance.py
tests/test_work_review_jobs.py
tests/test_worker_worktree_layout_v635.py
tests/test_workspace.py
```

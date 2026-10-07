# V-749 — remove brittle delivery-receipt wording check

Updated `test_t370_unknown_receipt_tells_caller_how_to_check_and_retry_safely` to validate the stable receipt contract: error code, delivery ID, structured `message_delivery_status` action, and presence of the status-tool name in the rendered receipt. Removed assertions for the exact invocation string and retry prose. The named test passed after the change (1 passed).

The complete delivery/MCP test set was selected from test files directly referencing the MCP receipt helpers/tools or message/file delivery modules and interfaces. The exact file list is also in [test-files.txt](test-files.txt). Command: `xargs -a .orchestra/tasks/V-749/test-files.txt uv run --frozen python -m pytest -q` → **938 passed, 1 skipped, 1 warning in 485.24 s**, exit code 0. `git diff --check` passed.

The warning was `RuntimeWarning: coroutine '_S._notify_scope_idle' was never awaited` in `tests/test_mailbox.py::test_t3_failed_injection_keeps_message`; pytest also reported an asyncio subprocess transport finalizer exception (`RuntimeError: Event loop is closed`) after completion. Neither changed the successful exit status.

Test files:

```text
tests/test_acceptance.py
tests/test_agentic_compact_650.py
tests/test_api.py
tests/test_artifacts.py
tests/test_audit0901_delivery.py
tests/test_audit0901_mcp.py
tests/test_audit0901_tg.py
tests/test_charts.py
tests/test_codex_writer_conflict_536.py
tests/test_compact_pending_ack_467.py
tests/test_delivery_head_of_line_block.py
tests/test_delivery_queue_block_connection.py
tests/test_durable_steering_562.py
tests/test_fan_barrier_gates.py
tests/test_fan_barrier_intercept.py
tests/test_fan_completion_modes_407.py
tests/test_fan_enable.py
tests/test_fan_report_delivery.py
tests/test_fan_terminal_kind.py
tests/test_frontend.py
tests/test_initial_deliveries.py
tests/test_lifecycle_quarantine_499.py
tests/test_mailbox.py
tests/test_mcp_stdio.py
tests/test_message_delivery_failure_notices_741.py
tests/test_message_delivery_receipts_380.py
tests/test_message_provenance_migration_433.py
tests/test_message_provenance_review_433.py
tests/test_quota_wait_queue.py
tests/test_restart_durable_transfer.py
tests/test_restart_generation_liveness.py
tests/test_restart_inbox.py
tests/test_send_provenance_without_auth.py
tests/test_stall_signals_642.py
tests/test_task_tracker_integration.py
tests/test_taskless_delivery_702.py
tests/test_tg_bridge.py
tests/test_tg_file_batch_route.py
tests/test_tg_file_deliveries.py
tests/test_tg_file_delivery_failure_notices_748.py
tests/test_tg_file_limits_v544.py
```

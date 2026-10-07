# V-750 — remove receipt-only MCP status tools

Removed the MCP registrations for `message_delivery_status`, `file_delivery_status`, `delivery_status`, and `task_create_status`. `cancel_message_delivery` and `retry_initial_delivery` remain. The GET status HTTP routes and task-manager status helper remain available to the dashboard and internal reconciliation; send/spawn implementations still reconcile ambiguous POST outcomes internally.

Receipts and error actions now direct ambiguous calls to repeat the original call with its existing `delivery_id`, `event_id`, or `request_key`. `task_create` now returns its generated request key in an ambiguous error, so the caller can repeat even when it omitted the optional key. An ambiguous `spawn_worker` creation check now carries its initial delivery id and same-call retry action if `/spawn-resume` is unavailable. Background-job and task-management prompt modules carry the same retry rule. The tool-set regression checks actual registered MCP names and confirms both retained actions.

Same-key behavior is covered at each affected operation: direct messages replay the accepted row; single-file and batch-file acceptance return the existing receipt and produce one Telegram send; initial delivery acceptance returns the same receipt and same spawn reuses the existing worker; task creation reuses the existing task for the same request key. `test_git_task_api.py` still checks the internal task-create status API, which remains intentionally available.

## Verification

The seven selected files were all six paths found by the pre-change `rg -l 'message_delivery_status|file_delivery_status|delivery_status|task_create_status' tests/` plus `tests/test_tg_file_deliveries.py` for the new single-file idempotency regression. Exact paths are in [test-files.txt](test-files.txt).

`xargs -a .orchestra/tasks/V-750/test-files.txt uv run --frozen python -m pytest -q` → **205 passed in 20.84 s**, exit code 0. The command output is preserved in [full-tests.log](full-tests.log). Focused idempotency and tool-set checks passed (11 passed). `python -m py_compile app/mcp_stdio.py app/initial_deliveries.py app/message_deliveries.py app/tg_file_deliveries.py app/stall_signals.py`, `python scripts/check_instruction_contract.py`, and `git diff --check` passed. `app.mcp_stdio` imported from `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/mcp_stdio.py`.

No service restart was performed.

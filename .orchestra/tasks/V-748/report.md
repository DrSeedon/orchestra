# V-748 — delivery receipts and file failure notices

The MCP send/status descriptions now explain that terminal delivery failures wake the sender automatically and that status lookup is for an ambiguous send-tool call outcome, not routine polling. Ordinary `send_message`, `send_file`, and `send_files` receipts no longer recommend polling. Existing status lookups that reconcile an ambiguous send call still use its original delivery/event id.

Terminal failure of a primary Telegram file delivery (`FAILED_BEFORE_SUBMIT` or provider-rejected `FAILED`) now writes a sender notice in the same transaction as the terminal target state. Notices are keyed by the returned event id (the batch root for albums), delivered through the sender session with a stable log event id, and retained until successfully logged. Startup recovery runs after agents resume; owner/dashboard file sends have no source session id and create no wake. Provider outcomes recorded as `UNKNOWN` do not create terminal-failure notices.

The regression test exercises both terminal paths, verifies that a successful delivery creates no notice, and simulates sender-session unavailability followed by recovery. The first notice remains pending, is sent once during recovery, and is not replayed on a second recovery pass. Two prior assertions in `tests/test_mcp_stdio.py` checked literal status-tool wording; those wording-only assertions were removed while retaining assertions for the structured ambiguous outcome, event id, tool, and arguments.

## Verification

`uv run --frozen python -m pytest tests/test_tg_file_delivery_failure_notices_748.py tests/test_tg_file_deliveries.py tests/test_tg_file_batch_route.py tests/test_tg_file_limits_v544.py tests/test_mcp_stdio.py -q` → 148 passed in 29.98 s.

The committed failure-notice test was mutation-checked: temporarily making `_record_failure_notice` a no-op caused it to fail at the missing durable notice assertion. After restoring the implementation, the focused V-748 test passed (1 passed in 8.20 s).

`python -m py_compile app/tg_file_deliveries.py app/main.py app/mcp_stdio.py` passed. The system `python` has no `pytest` installed; the test command used the project environment. `app.tg_file_deliveries` imported from `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/tg_file_deliveries.py`. `git diff --check` passed.

No service restart was performed.

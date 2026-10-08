# V-778 — Preserve generated idempotency keys in ambiguous delivery errors

A transport timeout can happen after an API accepted a delivery. If status reconciliation is unavailable, the MCP caller must receive the same generated or supplied operation key in the human-readable error and structured response to safely repeat the idempotent call.

`app/mcp_stdio.py` now exposes `delivery_id` for ambiguous `send_message`, `spawn_worker`, and `retry_initial_delivery` errors, and `event_id` for ambiguous `send_file` and `send_files` errors. Structured error `details` and `result` carry the key. Both worker-spawn ambiguity phases are covered: creation reconciliation and initial-task delivery. While testing the creation-resume path, the regression caught a retry message that named `delivery_id` without its value; the message now includes the concrete generated id.

The full MCP and delivery suite listed in `test-files.txt` passed: **258 passed in 170.74s**. The five new transport-timeout protocol checks, including both `send_file` and `send_files`, passed after the final test changes: **6 passed in 10.88s**. They check the returned MCP text and structured error/result fields. Tests were run with `uv run --frozen python -m pytest`. The imported module was `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/mcp_stdio.py`. `git diff --check` passed. No restart was performed.

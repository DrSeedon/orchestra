# V-866: distinguish quota-held delivery receipts

Updated only human-readable delivery text. `spawn_worker` now distinguishes ordinary `QUEUED`/`PREPARING` and `SUBMITTED` states from `WAITING_QUOTA`; `send_message` does the same for `QUEUED`/`SUBMITTED` and states blocked behind the quota queue. The initial-delivery API's existing `next_action.message` now carries the distinction used by `retry_initial_delivery`. State values, action codes, and other receipt fields are unchanged.

`tests/test_delivery_receipt_status_866.py` checks that ordinary versus `WAITING_QUOTA` status controls whether each receipt has a deferred indicator, including the API `next_action.message` returned by `retry_initial_delivery`. Verification: `uv run --frozen python -m pytest tests/test_delivery_receipt_status_866.py tests/test_initial_deliveries.py tests/test_mcp_stdio.py tests/test_message_delivery_receipts_380.py tests/test_quota_wait_queue.py -q` — `211 passed in 37.05s`. The imported app module was `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-spawn/app/__init__.py`.

Committed tests were mutation-checked for all three text paths. Changing the spawn receipt's `WAITING_QUOTA` state branch, changing send receipt's `WAITING_QUOTA` branch, and removing the deferred indicator from the quota-wait API message each made its corresponding `test_delivery_receipt_status_866.py` case fail. Mutations were restored; the full 211-test command passed afterwards.

Python changes require an Orchestra restart; none was performed.

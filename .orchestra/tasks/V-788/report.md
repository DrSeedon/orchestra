# V-788 — Restore quota-held initial delivery after restart

## Cause and change

`SessionManager.send_initial_delivery()` looked only in `self.sessions`. A quota release can start the durable delivery runner after restart, when the session row still exists in SQLite but the in-memory registry is empty. That path raised `KeyError('session not found')`; `run_initial_delivery()` then marked the delivery `FAILED_BEFORE_SUBMIT`. Its sibling `send_message_delivery()` already calls `ensure_loaded_by_id()` in this condition.

`send_initial_delivery()` now calls `ensure_loaded_by_id(session_id)` when the registry lookup misses. A missing or archived DB session still raises the existing `KeyError`. The identity check remains inside the per-session lock, so a session replaced during loading is rejected before dispatch.

## Other release paths checked

`quota_queue.release_waiting()` moves a waiting initial delivery to `QUEUED` and calls `initial_deliveries.ensure_delivery_runner()`. `retry_initial_delivery` posts to the same initial-delivery acceptance endpoint; replay of `FAILED_BEFORE_SUBMIT` also calls that runner. Both reach `run_initial_delivery()` and the fixed `send_initial_delivery()` method, so no separate retry or release change was needed. The regression test exercises the quota-release path; the existing retry receipt test checks same-ID replay.

## Verification

From the worktree root, the final focused command was:

```text
uv run --frozen python -m pytest tests/test_initial_deliveries.py::test_v788_quota_release_loads_initial_target_missing_from_manager tests/test_initial_deliveries.py::test_t2_manager_entry_preserves_session_lock_and_auto_switch tests/test_quota_wait_queue.py::test_initial_task_waits_for_the_gate_and_precedes_direct_messages tests/test_mcp_stdio.py::test_t3_retry_initial_delivery_replays_same_receipt_with_same_key -q
```

Result: `4 passed in 2.31s`. The imported module path in the test traceback is `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-spawn/app/manager.py`. Tests use a temporary SQLite database and a fake session transport; no live service, production database, or provider CLI was used.

The new regression test was committed in `634ccfd9` before mutation. With the fix temporarily reverted to the old registry-only lookup, the test failed and the runner recorded `FAILED_BEFORE_SUBMIT`; the captured traceback ends in `KeyError: 'session not found: session-311'`. The fix was restored and the final test command passed.

Logs: [red-old.log](red-old.log), [mutation.log](mutation.log), [final.log](final.log). The earlier committed focused run is [green.log](green.log).

Python changes require an owner-initiated Orchestra restart before the running process uses this fix.

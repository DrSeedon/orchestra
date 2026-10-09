# V-797 — Initial task quota state and parent notifications

## Changes

The initial-delivery endpoint now calls the same `SessionManager.preflight_message_delivery()` admission check used for direct messages before it commits a new initial delivery. If the gate is already closed, the new row is committed directly as `WAITING_QUOTA`, with `wait_error` details and a `WAITING_QUOTA` event marked `covered_by_receipt`; the runner is not started. `spawn_worker` already has a `WAITING_QUOTA` receipt branch, and it now includes the reason from the delivery error. A retry with the same `delivery_id` still returns the committed receipt.

The gate can close after preflight. For that race and for later credit exhaustion, the state transition to `WAITING_QUOTA` now inserts a durable parent-event outbox row in the same SQLite transaction. A successful `SUBMITTED` transition inserts a second event only if that delivery has previously entered `WAITING_QUOTA`. A gate-held spawn receipt itself covers the first event, preventing a duplicate wait notification; release to `QUEUED` does not generate an extra parent message.

`app/initial_delivery_events.py` sends each pending event to the worker's parent with `origin='platform'`, worker name, `delivery_id`, state and (for the wait event) reason. It checks the parent's log for the event reference before resending, so a restart after parent acceptance but before outbox acknowledgment does not duplicate the message. Attempts that fail stay pending with backoff. The existing `quota_release_loop` starts the event runner on each pass and after service startup; transitions also schedule it immediately. Parents need no timer or status polling. No prompts were changed.

## Tests

From the worktree root:

```text
uv run --frozen python -m pytest tests/test_initial_deliveries.py tests/test_quota_wait_queue.py tests/test_mcp_stdio.py::test_t3_retry_initial_delivery_replays_same_receipt_with_same_key -q
```

Result: **33 passed in 4.36s**. The tests use temporary SQLite databases and fake managers; no live database, service or provider CLI was used. The imported source path is `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-spawn/app/initial_deliveries.py`.

The new receipt test fails if the route does not pass its quota preflight result into acceptance: with that mutation, the committed test received `delivery_state='QUEUED'` instead of `WAITING_QUOTA` (`mutation-receipt.log`). The transition test fails if `record_waiting()` omits its outbox insert: it found no durable `WAITING_QUOTA` event (`mutation-notice.log`). Both tests were committed before their mutation runs. The transition test also simulates notification transport failure followed by a fresh manager, then a crash after the parent logs the submitted event but before outbox acknowledgment; replay delivers the pending event without a duplicate.

Logs: [final.log](final.log), [regression.log](regression.log), [red-acceptance.log](red-acceptance.log), [mutation-receipt.log](mutation-receipt.log), [mutation-notice.log](mutation-notice.log).

Python changes require an owner-initiated Orchestra restart before the running service uses this fix.

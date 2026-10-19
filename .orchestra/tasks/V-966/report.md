# V-966: accepted messages hanging in QUEUED

## Cause (live DB, read-only, 19.10)
All three affected targets share one pattern: the head of their queue is a `WAITING_NEXT_TURN` row
(decision-cost 9134 since 15.10, tender-triage 8182, feat-kesha-alert 6798), and every later row is `QUEUED`.
`requeue_failed_turn` moves a steer of a failed Codex turn into `mailbox` (`direct_message_recovery`, ref = delivery id).
The mailbox is claimed only at a turn end (`session_turns.handle_turn_end`, `_finish_failed_running_turn`). An idle
session has no turn end, so the row never leaves; `_next_target_delivery` returns it as the head and
`ensure_target_runner` refuses to run behind a non-QUEUED head. Confirmed on decision-cost: mailbox rows 232/233
undelivered since 15.10, `claimed_at` empty. Seven of the 12 are for sessions archived afterwards; nothing failed
them on archive.

## Change
- `fail_deliveries_to_archived_targets`: called from `db.archive_session` and the sweeper; `QUEUED`/`WAITING_NEXT_TURN`/`WAITING_QUOTA`
  of an archived or missing target → `FAILED_BEFORE_SUBMIT` `TARGET_ARCHIVED` (+ failure notice for agent senders, mailbox copy closed).
- `sweep_stuck_deliveries` every 60 s (`start_sweeper` in lifespan, cancelled at shutdown): wakes an `IDLE` target with a
  `WAITING_NEXT_TURN` row older than 120 s via `TurnManager._deliver_mailbox`; `ensure_target_runner` for QUEUED/PREPARING heads;
  warns once per delivery after 1 h (logger + target session journal); retries notices, closes those for archived senders.
- Not touched: `DISPATCHING`, `DELIVERY_UNKNOWN` (at-most-once).
- Existing 12 records: after the restart the first sweep fails the 7 archived ones with a notice; decision-cost's mailbox is delivered, and
  its five `QUEUED` follow. No manual DB edit.

## Checks
`tests/test_v966_stuck_deliveries.py` (5 tests); with neighbours (562, 380, 741, mailbox, 703, session, manager) 503 passed (`tests.log`).
Mutations (`mutation.log`): archive hook off → red; wake off → red; sweeper archived-step off → red (after adding the legacy-rows test).
Limits: a real restart and the live decision-cost wake were not run; the Codex-turn failure that originally created the head was not reproduced, only its resulting state.
Restart needed (Python).

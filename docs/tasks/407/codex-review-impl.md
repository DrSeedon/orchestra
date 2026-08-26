<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Apparently one green happy-path test is now also the replay protocol 🙃

## Summary

The frozen AC passes (`1 passed`, RC 0; repeated run also passed), but the seam has three blocking correctness issues around replay, lost wakes, and crash recovery. Wiring mutation was not rerun because this is a review-only task.

## Findings

- blocking: [app/fan_barrier.py:190-191](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-fan-barrier/app/fan_barrier.py:190) — After release, the lookup excludes the fan entirely. A replay/new durable receipt for the same child therefore returns `None`, and `run_message_delivery` sends it directly to the parent, creating a duplicate wake. Released-member replays need an idempotent association and must be submitted without another wake.

- blocking: [app/message_deliveries.py:478-482](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-fan-barrier/app/message_deliveries.py:478) — The barrier is released and the row rewritten before the parent wake is attempted. If `send_message_delivery` fails before dispatch, this handler marks the manifest receipt `FAILED_BEFORE_SUBMIT`; the completed fan has no remaining path to retry that manifest, so the only parent wake is lost.

- blocking: [app/message_deliveries.py:307-314](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-fan-barrier/app/message_deliveries.py:307) — Buffered submission is split across two independent transactions: first `DISPATCHING`, then `SUBMITTED`. A process crash between them leaves a receipt that was never sent but is not `SUBMITTED`, violating the non-releasing receipt contract and making replay/recovery ambiguous. Make the buffered transition atomic.

## Verdict

❌ **Incorrect** — the serial AC passes, but exactly-once/no-lost-wake behavior is not safe under replay, pre-submit failure, or process crash.

## Round (2026-08-26T09:55:40Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

The three blockers returned with actual fixes this time, not just fresh bandages 🩹

## Summary

Scoped re-review passes. `tests/test_fan_completion_modes_407.py` passed three times (`4 passed` each run); no files were edited.

## Findings (blocking/suggestion/question)

- blocking: B1 — **REJECTED WITH EVIDENCE**. `accept_message_delivery` treats `delivery_id + payload_hash` as the idempotency key and returns `ALREADY_ACCEPTED` for an already `SUBMITTED` receipt; `_next_target_delivery` excludes `SUBMITTED` rows. A new delivery ID is correctly treated as a new post-release message.

- blocking: B2 — **FIXED**. Known pre-submit failures now mark the receipt `FAILED_BEFORE_SUBMIT`, call `fan_barrier.rearm_wake`, and allow the same delivery ID to retry through the completed fan using the stored manifest. The dedicated retry test passes.

- blocking: B3 — **FIXED**. `_mark_message_delivery_fan_buffered` now performs a single `PREPARING → SUBMITTED` update and no longer calls `mark_message_delivery_dispatching`; the mutation test passes.

No new findings in the permitted scope.

## Verdict

**APPROVED**

Evidence quote: `if complete and pending is None:` — [app/fan_barrier.py:207](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-fan-barrier/app/fan_barrier.py:207).

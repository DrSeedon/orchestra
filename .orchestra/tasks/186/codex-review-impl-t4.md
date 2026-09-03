## Summary

Reviewed the permitted files and ran all 12 targeted tests; they passed. Sighted-review proof from `app/quota_alert.py`:

> logger.warning("quota alert: предупреждение за окно %s не доставлено и уже неактуально",

The new module is a good boundary: it keeps policy ownership cohesive and makes the cycle testable independently of FastAPI. However, the implementation does not yet satisfy the stated delivery and shared-loop guarantees.

## Findings

blocking: [app/quota_alert.py:112](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/quota_alert.py:112) — The silence latch is consumed before delivery is proven. `silence_observe()` atomically sets `notified_at`, then `_deliver()`’s result is ignored. If Telegram returns `{"error": ...}`, raises, or times out, every subsequent cycle sees the silence as already notified and the message is permanently lost. Give silence the same pending/delivered lifecycle as quota alerts, or clear/reserve the latch after failed delivery.

blocking: [app/quota_alert.py:93](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/quota_alert.py:93) — `evaluate_and_notify()` claims not to release exceptions, but only `_deliver()` is protected. Exceptions from `as_utc`, a non-dict `anthropic`, SQLite helpers, malformed baseline timestamps, `_checked_pct()` in `weekly_runway`, `_alert_text`, and `alert_mark_delivered` escape into the shared snapshot loop. For example, `utilization=NaN` raises `ValueError`, and a malformed stored baseline raises at line 125. The whole cycle needs an outer exception boundary that logs the exception and returns an error state.

blocking: [app/quota_alert.py:112](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/quota_alert.py:112) — The synchronous SQLite work can realistically stall the event loop. One evaluation opens up to six separate connections, and each `_conn()` has a 5-second busy timeout. WAL prevents readers blocking writers, but the state writes can wait on another writer; the nominal 10-second Telegram budget therefore does not bound the whole call. Run the synchronous evaluate/latch operations off-loop, or provide an explicit overall budget and fail safely while preserving pending delivery state.

blocking: [app/quota_alert.py:139](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/quota_alert.py:139) — Concurrent evaluations can duplicate an alert. `alert_state_advance()` has a single winner, but its return value is ignored; both callers can subsequently observe `alert_pending=True` and both send. The claim that the conditional insert produces exactly one sender therefore does not hold. Delivery needs an atomic claim/lease, or only the transition winner may send while later cycles retry an explicitly pending-but-unclaimed row.

blocking: [app/quota_runway.py:155](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/quota_runway.py:155) — Interpolation is wrong when an hour straddles a working-band boundary. From `02:30 UTC`, the interval to `03:30` contains 0.5 working hours; requesting 0.1 working hour returns `02:42`, which is outside the band and before any working time has elapsed. `remaining / step` is incorrectly treated as elapsed wall-clock hours. Locate the working subinterval within the step, then add `remaining` from its beginning. Add boundary tests starting before 03:00 and after 17:00.

suggestion: [tests/test_quota_alert.py:210](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/tests/test_quota_alert.py:210) — A sixth surviving mutation is replacing the bounded silence delivery with direct `await send(...)`. Existing silence tests use an immediately successful recorder, while the hanging-delivery test exercises only the quota-alert branch, so this mutation passes but can hang the shared loop. Add a silence test where the first send times out or returns `{"error": ...}`, assert the call remains bounded, then assert the next cycle retries and marks success only after proven delivery. This also exposes the current permanent-loss bug.

suggestion: [tests/test_quota_alert.py:66](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/tests/test_quota_alert.py:66) — The replay is useful evidence for alert volume, but not faithful evidence for production reliability. Hourly, strictly ordered, complete snapshots avoid malformed values, database contention, overlapping evaluations, five-minute reset jitter, and delivery failures. Keep it as policy/backtest evidence, but do not use it to support the no-stall or exactly-once claims; those require focused contention/concurrency and failure-retry tests.

## Verdict

Changes requested. The module split is sound, and quota-alert success is marked only after an explicit `{"ok": true}` response, but silence notifications can be lost permanently, exceptions and SQLite waits can reach the shared loop, concurrent evaluations can duplicate delivery, and the forecast can report a non-working time.

## Round (2026-08-11T13:11:49Z)

## Re-review status

- FIXED — Silence delivery failure releases `notified_at` without restarting the grace period, and dedicated failure/timeout tests cover retry behavior.
- FIXED — The outer wrapper catches evaluation and database exceptions while correctly allowing task cancellation to propagate.
- PARTIALLY FIXED — SQLite no longer blocks the event loop, but the snapshot coroutine still awaits several helpers with independent 5-second busy timeouts; see finding below.
- FIXED — The atomic lease prevents concurrent evaluations from both sending under normal timing.
- FIXED — Working-band traversal now handles boundary interpolation correctly.
- FIXED — Replay tests are appropriately treated as message-volume evidence only.
- FIXED — The previously surviving hanging-silence mutation now has a targeted test.

## New findings

blocking: [app/quota_alert.py:130](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/quota_alert.py:130) — `to_thread` protects the event loop, but does not bound the shared snapshot cycle. `_sync_stage_one` still calls three helpers that each open a connection and may independently wait five seconds; `_claim` can similarly wait in both `alert_state_advance` and `alert_claim_delivery`. Together with delivery and the final mark, one evaluation can delay snapshot completion by roughly 30–40 seconds under writer contention. “One batched call” batches thread dispatch, not SQLite connections or busy-timeout exposure. Use one transaction/connection per synchronous stage, or decouple notification completion from snapshot collection with a serialized background task.

blocking: [app/db.py:2154](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/db.py:2154) — `alert_discard_stale` can race an active claim because it ignores `delivery_claimed_at`. An old-window sender can claim immediately before reset; the new-window cycle then marks that row discarded while its Telegram send is in flight; the old cycle subsequently sends and marks the same row delivered. The database can therefore claim the alert was both discarded and delivered, while the supposedly obsolete message arrives after reset. Exclude live leases from stale discard and handle them after lease expiry, with a deterministic boundary-race test.

## Verdict

Changes still requested. The lease duration itself is sound relative to a 10-second delivery budget and 300-second polling under a single host clock, and the `to_thread` closures contain immutable per-call values with no shared Python mutation. The remaining problems are the unbounded awaited SQLite chain and the claim-versus-discard race.

## Round 2

Sighted-review proof from the current `app/quota_alert.py`:

> logger.warning("quota alert: предупреждение за окно %s не доставлено и уже неактуально",

## Round (2026-08-11T13:19:28Z)

## Re-review status

- FIXED — Snapshot collection now schedules background work without awaiting SQLite or Telegram.
- FIXED — Live leases are excluded from stale discard, and conditional delivery marking prevents a row from recording both outcomes.

## New findings

blocking: [app/quota_alert.py:107](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/quota_alert.py:107) — Skip-on-overlap can permanently disable the feature. Exact sequence: the sender catches cancellation and continues waiting; `asyncio.wait_for` waits for cancellation to finish, so `_deliver` never returns; `_running.done()` remains false; every future 300-second tick is skipped forever. Holding a task reference prevents collection but provides no maximum task age. The scheduler needs a hard stale-task policy or watchdog so one non-cooperative dependency cannot suppress all future evaluations.

blocking: [app/quota_alert.py:156](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-policy/app/quota_alert.py:156) — Silence notification remains vulnerable to process death between `silence_observe()` setting `notified_at` and delivery. Unlike quota alerts, it has no expiring lease: after restart every poll sees the silence as already announced, so the notification is permanently lost. `silence_release()` handles returned failures and timeouts, but cannot handle process termination. Use the same pending/lease/delivered model as quota delivery.

## Verdict

No: all four invariants do not yet hold.

- (1) Holds for ordinary calls: snapshot collection does not await this feature.
- (2) Does not fully hold because silence can be lost across process death, and a permanently stuck task suppresses all later transitions.
- (3) Holds: the database cannot record an alert as both discarded and delivered through these paths.
- (4) Holds when called from a running event loop; evaluation exceptions do not reach the snapshot loop.

Shutdown cancellation itself is acceptable: `CancelledError` ends the task, and a quota delivery claim naturally expires before the next poll. The blocking case is a task that does not honor cancellation and therefore never becomes done.

## Round 3

Sighted-review proof from the current `app/quota_alert.py`:

> """Запустить оценку ФОНОМ и вернуться немедленно. True — запустили, False — пропустили.

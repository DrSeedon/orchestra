😏 “Safe replay” is currently doing some optimistic storytelling.

## Summary

Reviewed `git diff main...HEAD`, centered on `app/limit_wake.py` and directly related persistence paths. Atomic `replace_key` replacement and basic `triggering` replay look correct, but four P1 correctness gaps remain. Targeted tests pass: `8 passed`.

## Findings

### blocking

None.

### suggestion

1. **[P1] Make per-agent wake delivery crash-idempotent**
   [app/limit_wake.py:343](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-wake-on-reset/app/limit_wake.py:343)

   Replay reconstructs `sent = []`, while durable progress is only an unused aggregate string written after `session.send()`. Delivery relies on `session.send()` asynchronously persisting a `user_message`: a crash after backend acceptance but before that write commits can duplicate the wake; the inverse ordering can permanently lose it. Persist and reconcile per-target delivery with an idempotency/message key.

2. **[P1] Fail closed when forced quota refresh falls back to stale data**
   [app/limit_wake.py:315](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-wake-on-reset/app/limit_wake.py:315)

   `current_provider_usage(force_refresh=True)` silently returns cached usage when the provider request fails. During staggering, a stale `<100%` cache can therefore authorize another send after capacity has closed. The guard needs freshness metadata or an exception; failed refreshes must not count as available quota.

3. **[P1] Require terminal-limit evidence, not arbitrary matching text**
   [app/limit_wake.py:60](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-wake-on-reset/app/limit_wake.py:60)

   Every assistant `text`, `error`, and `status` row is passed to a matcher containing broad phrases such as `usage limit` and `session limit`. A normal completed response discussing those phrases becomes a timed-limit candidate and may later receive an unwanted wake. Detection should require the canonical provider error or terminal turn metadata.

4. **[P1] Do not use asynchronously assigned log IDs as exact turn boundaries**
   [app/limit_wake.py:54](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-wake-on-reset/app/limit_wake.py:54)

   Session logs are persisted through a multi-worker executor, so the limit text/error and `turn ended` row can commit out of order. If the actual limit marker receives an ID after the turn-end row, the `<= latest["id"]` filter drops it and the stopped agent is missed. Use a durable turn/event identifier or flush terminal markers before recording turn completion.

### question

None.

## Verdict

**❌ Incorrect — changes requested.** No P0 crash/security issue, but restart idempotency and fresh-quota validation do not satisfy the stated P1 guarantees.

The alarm survives reboot; whether it rings zero, one, or two times is still the adventurous part.

## Round (2026-07-25T14:06:13Z)

😏 The ledger is durable now; the receipt still isn’t proof of delivery.

## Summary

Prior P1s: **2 FIXED, 1 STILL BROKEN, 1 FIXED, 1 FIXED**. One new P1 correctness issue found. Targeted tests pass: `23 passed`.

## Findings

### blocking

None.

### suggestion

1. **Prior P1 #1 — STILL BROKEN: crash-idempotent delivery**
   [app/limit_wake.py:383](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-wake-on-reset/app/limit_wake.py:383)

   Replay treats the token-bearing `user_message` as proof of delivery, but that log is still written asynchronously before backend delivery. A crash after the log commits but before transport loses the wake; backend acceptance before log commit causes replay to resend it. The claimed/delivered ledger narrows the window but cannot reconcile which side effect actually occurred.

2. **Prior P1 #2 — FIXED: stale quota fallback**
   [app/limit_wake.py:355](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-wake-on-reset/app/limit_wake.py:355)

   Every send requests a provider-specific forced refresh, and the callee raises rather than authorizing cached capacity when that refresh fails.

3. **Prior P1 #3 — FIXED: false-positive limit detection**
   [app/limit_wake.py:62](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-wake-on-reset/app/limit_wake.py:62)

   Candidates now require both `stop_sequence` and the canonical subscription-limit error/status. Ordinary assistant text mentioning usage limits no longer qualifies; monthly classification still takes precedence.

4. **Prior P1 #4 — FIXED: asynchronous log ordering**
   [app/limit_wake.py:40](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-wake-on-reset/app/limit_wake.py:40)

   Detection and SQL bounds now use event timestamps captured before asynchronous insertion; IDs only break equal-timestamp ties and identify the target turn.

5. **New [P1]: auth-enabled deployments cannot execute wake jobs**
   [app/limit_wake.py:355](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-wake-on-reset/app/limit_wake.py:355)

   This always passes a required provider, while `_get_usage_data()` raises immediately whenever dashboard auth is enabled. Consequently every wake timer on an authenticated deployment fails before checking quota or sending its first wake.

### question

None.

## Verdict

**❌ NOT APPROVED.** No new blocking crash/corruption/security issue, but prior P1 #1 remains unresolved and authenticated deployments cannot use the feature.

The timer survives reboot; unfortunately the receipt can precede the package, while the authenticated front door rejects the courier entirely.

## Round (2026-07-25T14:15:45Z)

😏 Authentication has stopped confusing privacy with sabotaging internal work.

## Summary

Auth fix is correct:

- `_get_usage_data()` permits authenticated internal provider refreshes.
- GET `/api/usage` retains the privacy gate.
- Provider-specific forced refresh still rejects stale fallback.
- Auth regression passes; reported full suite: 862 passed, 20 skipped.

## Findings

### blocking

None.

### suggestion

The SQLite-to-SDK crash micro-window is a documented limitation, not an actionable P1. `backend.send()` exposes neither an idempotency key nor transactional acknowledgement, so strict exactly-once delivery is unavailable. Within scope, atomic `replace_key` prevents duplicate jobs from repeated clicks, while durable claimed/delivered tokens and log reconciliation provide reasonable restart recovery.

### question

None.

## Verdict

✅ **APPROVED WITH LIMITATION**

No actionable in-scope defect remains. The only residual risk sits exactly where SQLite hands the parcel to an external transport without requesting a receipt—which, annoyingly, is how reality works.

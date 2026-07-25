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

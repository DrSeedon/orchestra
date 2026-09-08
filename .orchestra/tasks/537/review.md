<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Reviewed the complete pinned diff `715f0fc...46be5d06` and traced adoption, transport publication, recovery, notifications, DB persistence, and replacement signaling.

The transport-preserving behavior is correct for valid, missing, and normally reused identities. Completed-turn races are also handled: notifications remain queued and the per-turn event loop reconciles completion after `thread/turns/list`.

Focused tests passed: `51 passed`.

## Findings (blocking/suggestion/question)

### Blocking

- `app/session.py:1070-1079`, `app/manager.py:2551-2556` — failed live-turn recovery is not durable.

  Adoption sets the session to `IDLE` and calls `_persist()` before `recover_adopted_turn()`. If `thread/turns/list` times out or returns an error, `_adopted_recovery_pending` remains only in memory. `auto_resume_all()` catches the exception and continues.

  Counterexample:

  1. DB has `status='running'`, no saved `active_turn_id`.
  2. Adoption persists `status='idle'`.
  3. `thread/turns/list` fails.
  4. Orchestra crashes before another delivery retries recovery.
  5. Next startup sees `status='idle'`, so `recover_turn=False`; it adopts the pipe without querying the live turn.
  6. A new delivery can issue `turn/start` while the old turn may still be active.

  This violates the requirement that failed live-turn queries must not silently admit against unknown state and can harm a surviving live turn.

### Question

- PID reuse is normally guarded correctly: `can_replace_adopted_process` requires exact PID/starttime equality, and actual signaling additionally opens a pidfd, rechecks `/proc` starttime, validates managed-runtime argv, then signals through the pidfd.

  However, an equal-starttime collision is not distinguishable: a reused PID with the same recorded starttime and matching managed-runtime argv would pass all checks. No stronger generation identity is verified. This is not a normal Linux 64-bit reuse case, but it is an explicit remaining assumption.

## Verdict

NEEDS WORK — the durable failed-recovery state must be fixed before approval. No files were modified.

## Round (2026-09-08T05:36:09Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Reviewed the complete pinned diff `715f0fc...5fcd8676`.

The prior blocking durability defect is resolved. Recovery-pending adoption now persists `RUNNING`; only a successful `thread/turns/list` query can transition the session to `IDLE`. A second restart therefore re-enters recovery instead of admitting delivery against unknown state.

Focused suite passed: `62 passed in 15.82s`.

## Findings (blocking/suggestion/question)

### Blocking

None found.

### Suggestion

None.

### Question

The equal-PID/equal-starttime/equal-argv collision remains an explicit identity assumption. Ordinary PID reuse is still guarded by starttime comparison plus pidfd pinning and argv verification. No new signaling path was introduced.

Retaining `RUNNING` while recovery is pending correctly blocks hibernation and delivery admission; failed recovery releases the lifecycle lock while preserving the pending flag.

## Verdict

APPROVED — the original blocker is resolved, and no additional concrete lifecycle or recovery defect was found in this change. No files were modified.

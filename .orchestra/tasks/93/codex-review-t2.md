## Summary

Naturally, the dangerous part starts after Git has already committed the result. 😏 Scoped identity and task CAS are sound, but three post-merge paths violate T2’s outcome and quarantine guarantees. Static review only; tests were not run as requested.

## Findings

### [blocking] Preserve merge success when switching raises

`app/routes/sessions.py:932-938`

If `switch_worktree_branch` raises instead of returning an error result, the exception escapes after the merge has succeeded. The HTTP/MCP caller receives a 500 rather than `ok: true` with an explicit failed `switch` sub-result—a false merge outcome. Catch exceptions here and retain the already-persisted quarantine.

### [blocking] Re-quarantine after task CAS failure

`app/routes/sessions.py:980-989`  
`app/routes/sessions.py:1151-1158`

The lifecycle is persisted with `task_id=par` and `needs_switch=False` before the conditional task update. When CAS rejects a deleted, reused, or concurrently revised task—or the update raises—the code only reports `task_status.ok=false`; the session remains durably assigned to a stale task number and can later resolve to a replacement task. Persist `task_id=""` and `needs_switch=True` on these failure paths while preserving merge success.

### [blocking] Do not return without durable post-merge quarantine

`app/routes/sessions.py:905-917`

If the first post-merge `persist_lifecycle(... needs_switch=True)` call fails, the function immediately returns the successful merge result with an error sub-result, but no durable quarantine exists. After reload, the session can retain its pre-merge lifecycle and appear safe to continue despite the target already being updated. This path needs a fail-safe quarantine persistence attempt before returning.

## Verdict

❌ **Incorrect.** The implementation prevents wrong-session merging and wrong scoped task mutation, but it does not consistently preserve truthful merge outcomes or durable quarantine after post-merge failures. The supplied revision-race test even codifies `needs_switch=0`, contrary to the stated T2 acceptance.

Git finishes the merge, then lifecycle handling helpfully leaves the safety barrier in the parking lot.

## Round (2026-08-01T09:46:50Z)

## Summary

Apparently blockers can stay fixed when properly supervised. 😏 All three Round-1 blockers are closed, the pinned-session contract and lock order remain intact, and no new blocking defects were found. Static review only; tests were not run.

## Findings

- **FIXED — switch exceptions preserve merge success.** `app/routes/sessions.py:965-979` converts exceptions into `switch.ok=false`; the top-level merge result remains unchanged and returns at `app/routes/sessions.py:1059-1060`.

- **FIXED — task CAS failures restore quarantine.** Merge handling re-persists `task_id=""` and `needs_switch=true` on the switched branch at `app/routes/sessions.py:1017-1038`. Standalone switching does the same and returns `task_assignment_failed` at `app/routes/sessions.py:1187-1216`.

- **FIXED — post-merge quarantine is fail-closed.** The helper sets in-memory quarantine and retries persistence at `app/routes/sessions.py:699-718`. Merge processing stops before switch/task mutation when both attempts fail at `app/routes/sessions.py:934-951`.

- **No new blocking findings.**

## Verdict

✅ **APPROVED.** All prior blockers are closed, and the updated paths preserve truthful outcomes and durable quarantine without violating the required lock order.

This time Git finishes the merge and lifecycle handling manages not to dispute the result.

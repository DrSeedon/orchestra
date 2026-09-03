## Summary

Naturally, one `shield()` is apparently expected to survive every cancellation forever 😏 Static review found two blocking lifecycle defects.

## Findings

### blocking — Keep owned spawn tasks shielded after cancellation

**Conventional comment — `app/manager.py:610-613`, `app/manager.py:654`**

After the first `CancelledError`, both `prepare_task` and `finalize_task` are awaited without shielding. A second `Task.cancel()` therefore propagates into the owned task. During preparation, this can cancel the coroutine while `create_worktree` continues in its thread, leaving `prepared_worktree` unset and leaking the resulting worktree/ref. During finalization, it can cancel the `to_thread` await while the DB transaction still commits, triggering compensation against an already-published row or leaving a ready worker without the required task transition. Repeated cancellation must continue waiting on shielded owned tasks until preparation/compensation or finalization completes.

### blocking — Do not return while the worktree remains registered

**Conventional comment — `app/workspace.py:647-655`**

This early return considers only the directory and branch ref. If the worktree directory has disappeared but its Git administrative entry remains—such as after external deletion or interrupted cleanup—the function reports success while leaking the registered worktree. This can block later spawns using the same path. Under the repo lock, the absent-path branch must also inspect and safely remove or explicitly reject the matching registration before returning.

## Verdict

**Changes required.** The main publication ordering is sound, but the cancellation path can leak or inconsistently compensate resources, and cleanup can falsely succeed with an orphaned Git worktree. Static review only; tests were not run as requested.

Two tiny lifecycle gaps, because apparently Git debris needs somewhere cozy to live.

## Round (2026-08-01T10:24:38Z)

## Summary

Apparently the cancellation hydra is mortal after all 🐍 Both prior blockers are fixed. No new blocking issues found in the supplied diff.

## Findings

### FIXED — Repeated cancellation penetrated owned operations

`app/manager.py:64-81`, `app/manager.py:627-637`, `app/manager.py:671-673`

`_wait_owned_task` repeatedly shields preparation, compensation, and finalization while consuming caller cancellation requests. Task-internal preparation cancellation is surfaced through `task.result()` and compensated before propagation.

### FIXED — Missing directory could hide a registered worktree

`app/workspace.py:647-652`

Cleanup now checks registration under the repo lock and fails loud while preserving the branch/ref when the directory is missing.

### New blocking findings

None.

## Verdict

**Approved — correct with high confidence.** The reported 520-test validation was not rerun, per the static-review constraint.

The lifecycle now survives cancellation like a worktree survives only when it actually belongs there.

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Because a 30-second timeout apparently needed more ways to fail, the diff still has two projection-recovery crash paths. 😑

## Findings

- **blocking:** [`app/ia/runtime.py:1007-1014`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-task-timeout/app/ia/runtime.py:1007) — `seal_current_resources()` is no longer guarded against SQLite errors. An existing `current.db` with a valid metadata head but a missing/corrupt auxiliary table can now abort startup or `task_create` instead of falling through to projection rebuild.

- **blocking:** [`app/ia/runtime.py:74-78`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-task-timeout/app/ia/runtime.py:74) — Recovery treats any regular `task-current.db` file as healthy. A truncated or invalid existing file skips rebuilding; startup no longer validates `projection_head`, and the first task read/list can fail rather than recover from canonical state.

## Verdict

**Changes requested.** The exact frozen regression command passed: `2 passed in 1.40s`. It does not cover malformed existing projection files.

A disposable projection that panics when its file is merely broken is about as disposable as a glass hammer.

## Round (2026-08-26T10:17:08Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The two original crash paths are addressed, but the recovery code has two new correctness gaps. The focused command passed: `46 passed in 2.94s`. 🧯

## Findings

- **status: FIXED — prior blocking 1.** Existing non-SQLite task projections are now detected, removed, and rebuilt from canonical state.

- **status: FIXED — prior blocking 2.** Current-projection SQLite errors now rebuild through a temporary database and replace the live file only after successful construction.

- **blocking:** [`app/ia/runtime.py:79-86`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-task-timeout/app/ia/runtime.py:79) — An existing task projection is accepted as soon as `projection_head` is readable; its value is never compared with `canonical_head`. If canonical state advances and the projection remains at the previous head, task reads/lists return stale data and post-commit operations run against an outdated cache.

- **blocking:** [`app/ia/runtime.py:1037-1040`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-task-timeout/app/ia/runtime.py:1037) — The atomic replacement handles only `-wal` and `-shm` sidecars for the old database, while leaving any old `-journal` behind and deleting temporary WAL/SHM files after replacing only the main file. A rollback journal or uncheckpointed temporary WAL can therefore be paired with the wrong database or discarded during recovery; the regression test fails before this sidecar path.

- **suggestion:** [`docs/kb/task-storage-architecture.md:4-6`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-task-timeout/docs/kb/task-storage-architecture.md:4) — This diff also removes the documented #406 task-number collision invariants and repair procedure, unrelated to #405. Restore them unless they were intentionally superseded.

## Verdict

**CHANGES REQUESTED.** Both prior blockers are fixed, but stale task projections and incomplete SQLite sidecar replacement remain.

A cache that swaps the database while arguing with its sidecars is still wearing a fake moustache.

## Round (2026-08-26T10:21:56Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Round 2’s two blocking findings are fixed. The focused suite passes: `46 passed in 2.42s`. One new blocking gap remains in task-cache invalidation. 🧟

## Findings

- **status: FIXED — prior stale-head finding.** Existing task projections now validate canonical head and row count before reuse.

- **status: FIXED — prior sidecar finding.** Current-cache rebuilds now checkpoint, switch to DELETE journaling, run `quick_check`, clean sidecars, and replace atomically.

- **blocking:** [`app/ia/runtime.py:93-95`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-task-timeout/app/ia/runtime.py:93) — Invalidating `task-current.db` unlinks only the main file, leaving `-journal`, `-wal`, and `-shm` sidecars behind. After an interrupted SQLite write, rebuilding at the same path can reuse stale sidecars, fail, or resurrect old projection state. Clean all task-projection sidecars before rebuilding, with a regression covering that interruption.

- **status: DROPPED — prior KB suggestion.** The supplied merge-base explanation resolves the apparent unrelated deletion.

## Verdict

**CHANGES REQUESTED.** The original blockers are closed, but task projection recovery still lacks the sidecar cleanup now applied to current projection recovery.

A disposable cache that keeps its old WAL attached is just a tiny haunted SQLite.

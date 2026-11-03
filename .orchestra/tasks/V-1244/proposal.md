# V-1244: historical proposal, approved and implemented

Historical proposal approved by the owner at 2026-11-03 01:42 KRS and implemented within the existing owners. See stage.md and implementation.md for the final code/evidence. No live operation was performed.

The existing Orchestra worker-close path and successful complete-merge cleanup both reach a release owner that deletes Hub history. Archiving a thread through the existing client primitive alone does not protect it from subsequent project cleanup. Consequently the automatic complete-merge/kill directive must remain blocked.

## Smallest proposed separation

1. Keep Orchestra session/task lifecycle in its current manager and merge owners. Introduce a history-preserving Hub archival operation in the existing workspace owner: use the existing T3 thread archive capability, retain the project/thread and workspace identities, accounting and transcripts, and avoid deletion of data. Preserve WIP/privacy/ownership gates and pending import/report recovery.
2. Route ordinary Hub worker closure and post-complete merge handling through that operation only. Existing workspace-replacement and orphan-sweep call sites must be audited together: otherwise later cleanup can still purge the retained project/history. Leave archived identities in the existing workspace records and use existing authoritative session/operation state to prevent those records from being mistaken for disposable orphans. Verify that both stored and loaded worker cases resolve the same owner; no new persistence or implicit TTL.
3. Keep current release semantics isolated as explicit purge, with a separately authorized target and scope. Do not call it from ordinary merge, close, task switch, automatic sweep or recovery. Do not execute purge as part of this task.
4. Once this behavior is explicitly approved, the canonical terminal merge action can change from `HUB_ARCHIVE_RETENTION_BLOCKED` to a history-preserving archive instruction. Complete/not-complete, exact HEAD, ownership and WIP checks remain; no backend acceptance or automatic tool execution.

## Compatibility and approval boundary

- Native worker lifecycle is unchanged. Preserve current API payloads and successful receipt shapes; add metadata only. Existing callers of a destructive release helper retain that meaning until individually migrated; do not silently redefine it as archival.
- The owner must explicitly approve changed Hub `kill_worker` semantics (archive and retain history), retention of existing workspace records and treatment of old releases/orphans. Root owns selection of that contract and review of every release caller before activation.
- Legacy workspace rows without an owning live session must fail closed: do not infer purge permission from age, missing process, idle status, end_turn or provider completion. Existing already-deleted history cannot be restored by this proposal.
- Do not add a new endpoint, scheduler, database/schema, retention TTL, statistics collector exclusion, latch reset, worktree/data deletion or provider/model fallback.
- Required next validation: synthetic stored/loaded session close; completed strict merge; continue/next_task; interrupted import and lost report acknowledgement; old orphan/replacement records; privacy/ownership refusal; duplicate/restart replay. Assert that history-bearing objects survive the entire path and no purge call occurs, not merely that a thread was archived.

The owner subsequently approved this separation. The final implementation and remaining host integration/activation gates are documented in stage.md; this historical proposal is not a current blocker or a separate policy owner.

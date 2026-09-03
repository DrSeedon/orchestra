# #248 — fresh-main audit

Date: 2026-08-24. Base: `40ddcbd94301`.

The immutable `b7ad6c76` task oracle was restored byte-for-byte on current `main`. Before
implementation it reproduced the original baseline: **23 failed**. Current `main` therefore did
not contain a partial #248 lifecycle; all four tickets were absent.

## Old implementation-review blockers

1. **UNKNOWN keeps the task reservation — CONFIRMED after port.**
   `resolve_operation()` marked the operation resolved but left its exact
   `tm_task_reservations.operation_id` rows. The documented unblock path therefore still prevented
   reassignment. Fixed atomically in the same resolution transaction. A stale scalar binding is
   recomputed only when the operation's session is no longer durably bound to that task.

2. **Restart between Git and the first checkpoint ignores the trailer — CONFIRMED after port.**
   `recover_orphan_operations()` changed every orphan `RUNNING` row to `UNKNOWN` without consulting
   its `PREPARED` payload or repository. Fixed: exact parent/tree/single-trailer evidence reopens
   only the DB finalizer and never calls Git again. Foreign or rewritten history remains `UNKNOWN`.

3. **Existing MCP scope test turns red — CONFIRMED as a stale test input, not a product
   regression.** The test used `task_update(status="done")` only to exercise scope fallback. #248
   intentionally makes `done` platform-owned. The test now uses allowed `cancelled`; the same
   authoritative-scope assertions remain.

The supplemental RED control originally attempted to bind a task to a nonexistent session. Its
setup now creates a durable taskless session first; production binding remains fail-closed.

## Outcome

- T1: planned spawn/assignment creates or resolves the canonical scoped task and publishes the
  session + task binding atomically.
- T2: candidate task refs and the canonical squash subject are validated under the repository
  mutation lock, alongside #386's pinned target/oracle admission.
- T3: merge outcomes own task completion/continuation, reservations, archive rebinding, durable
  finalization and restart reconciliation. Manual agent `in_progress`/`done` writes are rejected.
- T4: orchestrator `list_agents` carries a fresh bounded task slice; orchestrator and full-cycle
  prompts describe automatic lifecycle without embedding a task snapshot.

No old branch was merged wholesale. T1, T2 and T3 were applied as separate historical commits,
resolved against current `main`, then the review blockers and current compatibility seams were
implemented locally.

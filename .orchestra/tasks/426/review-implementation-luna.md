<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The implementation is broadly aligned with the bounded contract and the supplied tests cover the main happy paths. I found three blocking issues involving malformed receipts, Git index contamination, and startup recovery ordering.

## Findings

- blocking: `app/ia/runtime.py:1507-1512` — `_read_json()` raises `CanonicalKnowledgeUnavailableError` for invalid JSON or non-object content, but the drainer only catches `OSError`, `ValueError`, `JSONDecodeError`, and `KnowledgeRuntimeError`; a malformed receipt therefore terminates the long-lived drainer without recording `projection_outbox_invalid` debt → catch the canonical-read exception (or normalize `_read_json` failures into a caught runtime error) and retain the receipt visibly as debt.

- blocking: `app/ia/runtime.py:998-1007` — path-scoped commits still commit every already-staged path in the shared Git index; an unrelated staged evidence/task file can be included in the receipt or marker commit, causing canonical data leakage or an unrelated partial mutation → isolate/reset the index for each bounded commit, or verify the staged path set before committing and fail closed on extras.

- blocking: `app/ia/runtime.py:444-448,710-753` — startup discards untracked outbox receipts before loading/bootstrap-committing the canonical task worktree. A crash after task files are written but before the receipt commit leaves task state available to `_task_store()`, while `_reconcile_projection_outbox_worktree()` deletes its receipt; `_initialize_canonical_git()` can then commit the task state without any projection receipt, leaving the joined projection permanently stale → restore/reconcile task and outbox state from the same Git durability boundary, or mark the loaded task state as requiring projection repair before bootstrap commit.

## Verdict

Needs work. The supplied tests validate committed receipts and normal crash-after-SQLite behavior, but do not cover invalid JSON, pre-existing Git index entries, or a crash before the outbox commit.

## Round (2026-09-03T04:20:07Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

All three prior blockers are resolved. I found no new load-bearing bugs.

## Findings

- question: `app/ia/runtime.py:350-357` — FIXED. `_read_json()` converts both parse errors and non-object JSON into `KnowledgeRuntimeError`, which `_drain_projection_outbox_once()` catches at lines 1566–1571.

- blocking: `app/ia/runtime.py:1023-1057` — FIXED. Scoped commits reject pre-existing staged paths, validate the resulting path set, and reset/fail closed on extras. Exact current source: `"canonical Git index is not clean before scoped commit: "`.

- blocking: `app/ia/runtime.py:710-778` — FIXED. Startup resets task/outbox-related index entries, restores Git-HEAD bytes, discards uncommitted runtime files, and restores `canonical_head` from the durable queue/projection state before task bootstrap.

## Verdict

APPROVED. Supplied post-fix oracle: 32 passed in 24.19s, RC=0; final frozen oracle remains byte-identical.

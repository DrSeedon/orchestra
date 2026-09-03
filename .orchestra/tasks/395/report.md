# #395 implementation report

## Result

T1–T5 are implemented. T4 makes ordinary joined-current queries read-only: stale or corrupt
projection data returns canonical truth plus explicit debt and never initiates an O(N) repair.
T5 gives every task-create attempt a durable project-scoped request key, stores its fingerprint and
outcome, deterministically recovers canonical Git identity, and exposes HTTP/MCP status lookup for
outcome-unknown transport timeouts.

## Tickets

- T1 — defer cold projection work past readiness.
- T2 — targeted task/current/FTS projection mutations.
- T3 — projection-backed task reads.
- T4 — refrozen non-vacuous RED and read-only fallback implementation.
- T5 — frozen RED replay and durable idempotency implementation.

The original incremental history is frozen at `preserve/395-fix-tm-hang`; the deliverable was
squashed onto the current `main` base as one final #395 commit so no author commit carries a
platform-reserved `Orchestra-Operation:` trailer.

## T4 evidence

The corrupt fixture explicitly built a healthy projection before mutation. The committed
assertions measured one affected payload row and one affected FTS row.

Named command:

```text
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q tests/test_tm_projection_hotpath_395.py::test_t4_stale_current_read_falls_back_without_projection_repair tests/test_tm_projection_hotpath_395.py::test_t4_corrupt_current_data_is_never_served_before_background_validation --timeout=30
...                                                                      [100%]
3 passed in 7.44s
RC=0
```

Focused regression: `tests/test_knowledge_detail_summary.py tests/test_tm_projection_hotpath_395.py`
→ `19 passed in 9.42s`, RC=0.

Mutation: adding inline `replace_current` under mutant marker `MUTATION_T4_INLINE_REPAIR` changed
the marker count 0→1 and the named command to `3 failed in 7.98s`, RC=1. Restore plus `touch`
changed that mutant-marker count 1→0; the command returned `3 passed in 6.92s`, RC=0.

## T5 evidence

Named command after implementation and reviewer fix:

```text
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q tests/test_task_create_idempotency_395.py --timeout=30
........                                                                 [100%]
8 passed in 14.36s
RC=0
```

Independent regressions:

- `tests/test_tm.py` → `22 passed in 15.81s`, RC=0.
- `tests/test_task_tracker_integration.py` → `28 passed in 29.39s`, RC=0.
- Seven focused MCP/acceptance compatibility tests → `7 passed in 10.74s`, RC=0.
- The conflict-resolution seam
  `test_corrupt_disposable_projections_rebuild_from_canonical` → `1 passed in 8.03s`, RC=0;
  receipt-only startup remains deferred while the newer native-heap trim runs after explicit
  repair.
- Pre-commit failure probe called canonical create twice with one key and printed
  `PRECOMMIT_RETRY_CALLS=2 RECEIPT_COUNTS=[0, 0]`, RC=0: a proven absent canonical task releases
  its PENDING receipt instead of poisoning the key forever.

Each mutation changed one load-bearing part, then restored the original file with `mv` plus
`touch` before the green repeat:

- Mutant marker `MUTATION_T5_REPLAY_LOOKUP`: count before restore 1, after restore 0; replay test
  `1 failed`, RC=1 → restored `1 passed`, RC=0.
- Mutant marker `MUTATION_T5_RANDOM_CANONICAL_ID`: count before restore 1, after restore 0;
  canonical identity test `1 failed`, RC=1 → restored `1 passed`, RC=0.
- Mutant marker `MUTATION_T5_DROP_MCP_IDEMPOTENCY_KEY`: count before restore 1, after restore 0;
  MCP propagation test `1 failed`, RC=1 → restored `1 passed`, RC=0.

The pre-transplant full `uv run python -m pytest -x -q` exposed a stale legacy-merge assertion.
Current `main` deliberately emits `LEGACY_MERGE_CONTINUE` and preserves the bound task when a v1
caller cannot declare `complete` versus `continue`; the July test still expected that task to be
cleared. The test now asserts the current contract (`task_id=90`, warning present) for loaded and
detached sessions: `2 passed in 9.14s`, RC=0. `uv.lock` remained unmodified.

## Review

The risk gate selected Luna because persistence, concurrency, and external API surfaces require a
high-risk review, while an auxiliary Sol run was not authorized. Round 1 found one blocking path:
a canonical pre-commit exception could leave PENDING forever. The implementation now looks up the
deterministic canonical identity after an exception, continues if the side effect committed, and
deletes only the still-PENDING matching receipt when lookup proves no task exists. The probe above
reproduced two successive retries. Round 2 verdict: `approved`; prior P1 `FIXED`, no new blockers,
with verified changed-file quote `if request_key:`. Evidence:
`docs/tasks/395/codex-review-t5.md`.

## Files

- `app/db.py` — durable request receipt schema and upgrade handling.
- `app/tm.py` — fingerprint coordinator, ownership-order state transitions, replay/status and
  failure recovery.
- `app/ia/task_store.py` — deterministic stable/event identity and canonical replay.
- `app/routes/tm.py` — key resolution, conflict/pending responses, status route.
- `app/mcp_stdio.py` — key-preserving request headers and `task_create_status`.
- `app/ia/projections.py` — ordinary read fallback/debt without repair.
- `tests/test_tm_projection_hotpath_395.py` — approved T4 oracle refreeze only; T5 oracle remained
  byte-immutable after its frozen RED.

## Pre-mortem and consumer checks

- MCP POST times out after commit → retry with the surfaced request key replays the receipt; frozen
  same-key and MCP-header tests plus three mutations cover the observable result.
- Two concurrent callers use one key → one `tm_tasks` row and one durable receipt; frozen
  concurrent test covers it.
- Canonical Git commits but SQLite receipt update is interrupted → deterministic identity lookup
  recovers the same task and mirrors it once; frozen pending-crash test covers it.
- Canonical fails before commit → PENDING is removed only after an empty canonical lookup; the
  two-attempt scratch probe covers it.
- Existing callers omit a key → MCP generates one before transport and HTTP generates a 32-byte
  compatibility key; focused legacy/MCP tests remain green.

## Compatibility

No existing argument was removed. Success responses gain `request_key` and `replayed`; MCP gains an
optional `request_key` and a new status tool. Existing databases gain one additive table.

## Final merge-gate recheck against 2026-09-01 main

The identical six-file common command was run without `-x` on branch tip and current `main`
`fa49dfb5`. Branch tip had 4 failed / 360 passed; main had 0 failed / 366 passed. The set difference
was exactly four branch-only node ids and no shared or main-only failures:

- `tests/test_api.py::test_send_delegates_auto_switch_to_manager`
- `tests/test_api.py::test_create_worktree_response_contains_server_repo_metadata`
- `tests/test_api.py::test_send_quota_refusal_is_canonical_429`
- `tests/test_routes_surface.py::test_route_surface_snapshot`

The three API failures were stale fixtures already corrected on main by #415, not production
regressions; those fixture changes were copied into the branch. The route-surface failure was #395's
new `GET /api/tm/task-create-requests/{request_key}` missing from its snapshot and was fixed here.
The complete eight-file merge-gate set then produced `389 passed in 307.21s`, RC=0.

Final fixture-sync review gate: changed files were only `tests/test_api.py` and
`tests/route_surface_snapshot.json`; consumers are pytest and the HTTP-surface snapshot checker;
author metadata was `gpt-5.6-sol` on the Codex full-cycle runtime. AC was the exact eight-file
merge-gate command above, whose observed output was `389 passed in 307.21s`, RC=0. Model review was
skipped: this closed test-fixture/snapshot leaf has no production or external-contract mutation and
the pre-existing full merge-gate command mechanically covers both changed files.

## Final current-main integration

Current `main` `334c89b0` was merged into the worker branch after the first green gate. Three
conflicts retained both sides:

- `app/main.py` shutdown now owns both #395's projection-repair task and main's portfolio watchdog.
- `app/tm.py` retains #395 request-key idempotency, main's task-binding lock and its fail-loud
  shadow allocation contract; the idempotent legacy allocation runs under an explicit legacy
  context while the shared create lock keeps legacy/canonical display identities paired.
- `tests/route_surface_snapshot.json` contains both main's
  `POST /api/tm/repair-shadow-drift` and #395's
  `GET /api/tm/task-create-requests/{request_key}`.

The #428 finalization oracles
`test_sync_revision_debt_does_not_fail_completion` and
`test_finalization_failure_describes_projection_mismatch` remained green together with the shadow
idempotency and route-surface seams: `4 passed in 14.10s`, RC=0. The complete eight-file merge-gate
set on the integrated tree produced `391 passed in 367.74s`, RC=0; conflict markers were zero.

# #426 — Phase 3 implementation report

## Outcome

T1 is implemented at the writer that opens the gap. `app/tm.py` no longer returns an assignable
legacy task when shadow candidate creation fails:

- exact candidate absence triggers an identity-guarded delete of only the untouched legacy half;
- candidate present, unreadable, malformed, bound, revised, committed, or reserved preserves data;
- debt recording runs after probe/compensation and cannot replace the primary creation error;
- every candidate failure raises instead of returning `{**legacy, ...}`.

The finalizer, TaskStore, routes, merge operations, schema, and migration code were not changed.

## Production reachability

This is **preventative for shadow/fallback mode, not a fix for something burning in today's live
mode**. Read-only live state on 2026-09-01 reports:

```text
LIVE_ACTIVE_OWNER=canonical
LIVE_GENERATION=3
LIVE_SHADOW_OWNER=None
```

The changed branch is guarded by `context.mode == "shadow"`. Canonical-owner creation was already
canonical-first and the independently merged research commit `0e95e45` completed with
`operation_state=SUCCEEDED`, `lifecycle=SUCCEEDED`, and no `POST_COMMIT_PARTIAL`.

The shadow branch remains a supported fallback/migration runtime in current main, so closing the
gap prevents the historical failure from recurring if that mode is activated. No restart or live
configuration change was performed.

## Files

- `app/tm.py:411-423` — `_discard_shadow_created_task`, exact guarded compensation.
- `app/tm.py:2108-2150` — candidate outcome probe, safe compensation, best-effort debt receipt,
  and fail-loud primary exception.
- `docs/tasks/426/review-implementation-laptop-merge-finalization-luna.md` — implementation review artifact.
- `docs/workers/fix-merge-finalize.md` — reusable split-write compensation oracle lesson.
- `docs/tasks/426/report-laptop-merge-finalization.md` — this report.

Frozen acceptance remains unchanged at
`docs/tasks/426/acceptance/test_t1_shadow_task_creation.py`, commit `05f5f8c0`.

## Ticket

### T1 — Fail and compensate shadow task creation before assignment

Done. The immutable command transitioned from 11 behavior failures to 11 passes without modifying
the oracle.

```text
uv run python -m pytest -q docs/tasks/426/acceptance/test_t1_shadow_task_creation.py
...........                                                              [100%]
11 passed in 0.45s
```

Focused regression:

```text
uv run python -m pytest -q tests/test_tm.py tests/test_task_par_collision_406.py tests/test_task_completion_421.py
..............................                                           [100%]
30 passed in 1.90s
```

Healthy real-TaskStore shadow control:

```text
SHADOW_SUCCESS_MATCH True
SHADOW_SUCCESS_CANDIDATE project 1 healthy shadow create
SHADOW_SUCCESS_LEGACY [('project', 1, 'healthy shadow create')]
```

## Mutation evidence

One shell command performed the required `cp` → mutation → test → `mv` → `touch` sequence. The
mutation replaced the production call `_discard_shadow_created_task(legacy)` with a false result.
Marker labels and counts:

```text
PROD_MARKER_BEFORE=1
MUTANT_MARKER_BEFORE=0
PROD_MARKER_DURING=0
MUTANT_MARKER_DURING=1
MUTANT_TEST_RC=1
PROD_MARKER_AFTER=1
MUTANT_MARKER_AFTER=0
```

The mutated oracle returned `3 failed, 8 passed`: spawn, non-new creation, and debt-writer cases
retained the legacy-only row. After `mv app/tm.py.bak app/tm.py` and `touch app/tm.py`:

```text
11 passed in 0.51s
RESTORED_GREEN_RC=0
```

Thus the committed production compensation, not an unrelated branch, is required by the frozen
oracle.

## Full suite

The required no-`-x` full command was launched as background job `bg-0e98dbe560`:

```text
uv run python -m pytest -q > /tmp/pytest-426.log 2>&1
```

It was killed with exit `137` after reaching 82%, before pytest could write a summary. The log was
read once as required: 3,293 bytes / 42 lines, with at least 45 `F` progress markers already printed.
Therefore the full-suite outcome is **inconclusive**, not green and not attributable to T1 from
that run. `uv.lock` remained clean.

The suite modified two tracked screenshot fixtures outside task scope. Pre-run status proved they
were clean; both were restored from main only after verifying main blob IDs equal branch HEAD:

```text
usage-bar-provider-grid-1280.png  840b49b... == 840b49b...
usage-bar-provider-grid-1920.png  08d99c91... == 08d99c91...
```

Final status contains no screenshot or lockfile change.

## Pre-mortem and consumer checks

1. **Broad compensation deletes another project task.** Observable: decoy row disappears.
   Check: same-project decoy survives candidate-absent cleanup in the frozen oracle.
2. **TOCTOU deletes a task assigned or changed after candidate probe.** Observable: bound/revised/
   committed/reserved row vanishes. Check: four parameterized mutations preserve the row.
3. **Candidate committed before an ambiguous exception.** Observable: cleanup creates the inverse
   canonical-only split. Check: post-write candidate exists; both owners remain and caller fails loud.
4. **Candidate read is unavailable or malformed.** Observable: generic exception is mistaken for
   not-found and permits deletion. Check: RuntimeError, KeyError, and non-not-found ValueError all
   preserve legacy and raise the primary creation failure.
5. **Secondary debt writer fails.** Observable: cleanup is skipped or `debt writer unavailable`
   replaces the causal error. Check: exact row is compensated first and required primary message
   remains `shadow task creation failed: RuntimeError: candidate unavailable`.
6. **Healthy task creation regresses.** Observable: normal shadow/canonical create stops working.
   Checks: real TaskStore shadow control has `shadow_match=True`; focused suites are 30/30 green.

## Review

Route: one bounded `gpt-5.6-luna` implementation pass; Sol was technically preferred for the
persistence/lifecycle risk floor but no auxiliary Sol run was authorized.

The reviewer returned `APPROVED` with the verified exact source quote
`Remove only the untouched legacy half of a failed shadow create.` and no findings. The wrapper
reported the background job as failed because the artifact lacked a literal `## Verdict` heading
and secondary Codex usage accounting returned zero tokens. The artifact itself contains the
completed semantic verdict and exact quote; it was not rewritten to manufacture the missing
heading.

Artifact: `docs/tasks/426/review-implementation-laptop-merge-finalization-luna.md`.

## Breaking / TODO

- Breaking changes: none for canonical production mode. Shadow candidate failure changes from a
  success-shaped debt DTO to a loud `RuntimeError`; this is the intended contract correction.
- TODO: no code TODO within #426. The already-red/killed full-suite corpus remains outside this
  ticket and must not be represented as a T1 regression without a same-command baseline.

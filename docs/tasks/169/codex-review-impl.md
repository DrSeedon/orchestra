# #169 — implementation review

## Review status

**external verdict unavailable**

External Codex review was not started in Phase 3. The orchestrator explicitly prohibited a
quota bypass, Claude, and retries while the reviewer gate is closed. The exact known gate error is:

```text
weekly_quota_unknown: New Codex worker turn blocked: weekly quota status for gpt-5.6-sol is unavailable or stale (missing or legacy readiness policy). Stop/model change remain available.
```

This document is a strict Sol self-review supported by behavioral and mutation evidence. It is
not an independent second-model verdict and is not represented as Codex approval.

## Scope reviewed

- Implementation diff from Phase 2 base `05c1fb1` through the final Phase 3 commit.
- Project creation and alias resolution in `app/tm.py` and `app/tm_import_yougile.py`.
- Task get/update/status authority in `app/tm.py`, `app/routes/tm.py`, and `app/mcp_stdio.py`.
- Commit linking and worker lifecycle integration in `app/tm.py` and session/manager tests.
- Scope relocation collision handling in `app/db.py`.
- All new and adapted tests for #169, including independent mutations M1–M12.

## Load-bearing review

### 1. Existing case-variant rows are preserved

Verdict: **supported by code and mutation evidence**.

`resolve_project_id` performs an exact primary-key lookup before any casefold scan. Therefore
exact `Seedon` and exact `seedon` remain distinct addressable stored ids. A non-exact spelling is
accepted only when the Python `casefold()` scan has exactly one result; multiple results raise
instead of selecting by row order. `ensure_project` creates `requested.casefold()` only when no
match exists. M1 and M2 independently made exact legacy lookup and unique-alias reuse tests fail.

No schema migration, rename, merge, delete, startup cleanup, or live-data operation is present.
A SQLite `NOCASE` unique index was deliberately not added: it could not coexist with current
duplicates and would not implement the chosen Python casefold contract.

### 2. Canonical stored id reaches every create consumer

Verdict: **supported by code and mutation evidence**.

Both `api_create_task` and YouGile import consume the stored id returned by `ensure_project` for
task/client foreign keys and API response. M3a and M3b independently replacing that stored id
with request spelling caused focused failures. The production insert inventory has a single
project insertion owner (`ensure_project`); API create/import hold write transactions while
performing resolve/create.

### 3. Get/update cannot escape the authoritative project

Verdict: **supported by structure, behavioral matrix, and M4–M7b**.

HTTP routes resolve a non-empty explicit project first, otherwise require an exact mapped scope.
Missing or unmapped authority returns 4xx before core mutation. Core `resolve_task_ref` also
requires a project, canonicalizes it exact-first, checks legacy prefix against that same project,
and queries the task only inside the resolved stored id. Thus direct Python callers cannot regain
the removed global fallback. MCP sends explicit project without scope substitution and uses scope
only when project is omitted.

M4 detected removal of explicit-project GET priority. M5 detected cross-project PUT. M5b detected
restoration of authority-free core update. M6 detected removal of the foreign-prefix guard.
M7a proved that a wrong status target reaches the wrong prepayment when route authority is broken;
M7b independently proved the direct payment query remains client-project bound.

### 4. `status=done` pays only the selected task id

Verdict: **supported by transaction ordering and two independent payment tests**.

The update path resolves a project-bound task, captures its immutable DB id, updates by that id,
and only then calls `auto_deduct_prepayment` with the same id inside the same transaction. Authority
errors happen before update, payment, commit, or sync. M7a exercises the status-to-prepayment path;
M7b separately exercises direct payment project filtering, so the result does not depend on one
shared assertion or fallback.

### 5. Commit linking cannot use empty or foreign authority

Verdict: **supported by code and M8–M10**.

`link_commits_to_task` rejects a blank project before opening its DB transaction, then delegates
to the same project-bound resolver. The merge route passes the project mapped from the worker's
scope. M8 moved the blank check behind DB opening and failed, M9 removed route propagation and
failed, and M10 removed prefix rejection and failed. Duplicate-par integration tests verify that
only the lower-scope task receives the commit.

### 6. Worker spawn/switch/merge-next retain pinned identity and CAS

Verdict: **supported by existing implementation plus new duplicate-project tests and M11a–M11c**.

The lifecycle algorithms were not refactored. Tests now construct real `Seedon#1`/`seedon#1`
rows and verify the selected `TaskIdentity` uses the worker/session scope. Status changes remain
conditional on DB id, project id, `par_number`, and `sync_revision`. Removing the project, par,
or revision CAS predicate independently made M11a, M11b, or M11c fail. The four asynchronous
spawn/switch/merge cases passed three consecutive runs (12/12), reducing the chance that the
result is timing luck.

### 7. Scope collision rejection is atomic with respect to identity and moves

Verdict: **supported after a self-review correction**.

The first implementation checked task/project collision before DML but did not explicitly take a
write reservation before reading. Strict self-review identified that a concurrent owner change
could occur between the reads and the first write. `change_scope` now starts `BEGIN IMMEDIATE`
before reading the session and project owners, so collision proof and all session/project/bg-job/
test-lock updates share one serialized transaction. M12 removing only the task-associated collision
guard makes the atomic-state test fail. Empty-task collision compatibility and free-target moves
remain covered by the existing scope-change suite.

### 8. Existing data and operational boundaries

Verdict: **supported by diff inventory and execution environment**.

There are no migration/cleanup commands or scripts. All behavioral tests used pytest temporary DBs
inside the worker worktree. No production endpoint, service restart, deploy, or live write was
performed. Existing `Seedon`/`seedon` and `Orchestra`/`orchestra` data are deliberately left for a
separate dry-run and human-approved cleanup process.

## Verification reviewed

- Affected suite: `505 passed, 2 warnings in 87.65s` (`/tmp/pytest-169-affected.log`).
- Full suite: `2014 passed, 42 skipped, 2 warnings in 293.93s` (`/tmp/pytest-169.log`).
- RAG accounts for 32 explicitly reported skips because the worker environment has no embedder;
  #169 does not touch RAG.
- Full-suite exit code was 0. Post-summary `BaseSubprocessTransport.__del__` event-loop cleanup
  messages are existing non-failing shutdown noise, not a test failure.
- All 17 independent mutation runs for M1, M2, M3a, M3b, M4, M5, M5b, M6, M7a, M7b, M8, M9,
  M10, M11a, M11b, M11c, and M12 failed exactly one focused test after the intended protection
  was removed; every source file was restored after its run.

## Residual judgment requiring an external reviewer

- The O(n) Python casefold scan is acceptable for the current small-team project table; this is a
  scale judgment, not a correctness dependency.
- Exact explicit project taking precedence over a simultaneously supplied scope matches the
  approved contract; an independent reviewer should still inspect whether any undocumented caller
  expected scope to override explicit project.
- The transaction and resolver design was reviewed only by the implementing Sol session. Machine
  tests strongly cover target-selection regressions, but independent architectural review remains
  outstanding when the quota gate reopens.

## Self-review verdict

No unresolved blocking defect was found after adding the missing early write reservation to
`change_scope`. The implementation satisfies the approved invariants according to isolated
behavioral tests and independent mutations. **External verdict remains unavailable.**

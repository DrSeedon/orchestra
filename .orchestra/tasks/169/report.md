# #169 — fail-closed task/project identity implementation report

## Outcome

Silent cross-project task selection is removed from create/get/update/link/status/payment and
scope-relocation paths covered by #169. Task identity now requires an explicit project or an exact
project mapped from authoritative scope; missing, ambiguous, or contradictory identity fails before
side effects.

Existing case-variant projects are not migrated. Exact `Seedon` and exact `seedon` remain separate
and addressable. A non-exact casefold alias resolves only when there is one stored match; multiple
matches fail closed. A brand-new spelling creates one deterministic casefold id, and later variants
reuse it.

## Tickets completed

### T1 — Canonical create with legacy compatibility

- Added exact-first/casefold-unique project resolution.
- Made `ensure_project` return and reuse the stored project id.
- Propagated that id through API task creation and YouGile import foreign keys/responses.
- Added isolated tests for exact duplicates, ambiguous aliases, unique aliases, new canonical ids,
  scope conflicts, and unchanged legacy rows.

### T2 — Project-continuous get/update/status/prepayment

- HTTP GET/PUT accept explicit project, otherwise require an exact mapped scope.
- MCP get/update propagate explicit project or use caller scope only as fallback.
- Core task resolution no longer has an authority-free/global path.
- Foreign legacy prefixes cannot escape the authoritative project.
- `status=done` resolves and updates the correct DB id before prepayment allocation; authority
  failures occur before update/payment/sync.

### T3 — Project-bound commit linking and lifecycle proof

- Commit linking rejects blank project before DB access and resolves task refs inside the worker's
  project.
- Added duplicate-par integration coverage for merge linking, spawn, switch, and merge-next.
- Added independent mutation coverage for DB-id/project/par/revision CAS predicates.
- Lifecycle production algorithms and merge commit behavior were intentionally not refactored.

### T4 — Atomic scope collision rejection

- A task-associated session cannot move into a scope owned by a different task project.
- Collision rejection happens under `BEGIN IMMEDIATE`, before session/project/bg-job/test-lock
  movement, keeping the identity proof and writes in one serialized transaction.
- Sessions without a task association retain the prior explicit relocation contract.

## Files changed

- `app/tm.py` — project resolver/canonical create, mandatory task/link authority, prefix guard.
- `app/routes/tm.py` — explicit-project or mapped-scope HTTP authority and 4xx mapping.
- `app/mcp_stdio.py` — project propagation for task get/update and caller-facing contract text.
- `app/tm_import_yougile.py` — stored canonical project id propagation.
- `app/db.py` — task-associated scope-collision guard and early write transaction.
- `tests/test_tm.py` — isolated core/create/payment/link/CAS matrix and mutations.
- `tests/test_api.py` — HTTP cross-read/write/prepayment, merge/lifecycle, and scope integration.
- `tests/test_mcp_stdio.py` — explicit-project versus scope-fallback request parameters.
- `tests/test_db.py` — collision atomicity and compatibility cases.
- `tests/test_manager.py` — scoped spawn with real case-variant duplicate rows.
- `tests/test_merge_operations.py` — mandatory link authority adaptation.
- `tests/route_surface_snapshot.json` — refreshed pre-existing `/api/usage/readiness` route entry
  exposed by the full suite; no usage-route production change was made by #169.

## Behavioral verification

All database cases used pytest temporary databases in the worker worktree. No live database was
written.

- Ticket-focused runs: T1 `6 passed`; T2 `11 passed`; T3 `10 passed`; T4 `5 passed`.
- Task/MCP focused suite during T2: `98 passed`.
- Scope DB suite: `90 passed`.
- Four asynchronous merge/spawn/switch cases, repeated three times: `12/12 passed`.
- Final affected suite:
  `505 passed, 2 warnings in 87.65s` — `/tmp/pytest-169-affected.log`.
- Final full suite:
  `2014 passed, 42 skipped, 2 warnings in 293.93s` — `/tmp/pytest-169.log`.

The full suite exited 0. Thirty-two skips are the suite's explicit RAG-no-embedder group, unrelated
to #169. The two warnings are the existing multiprocessing `fork()` deprecation warnings. Non-failing
`BaseSubprocessTransport.__del__` messages appeared after the green summary during interpreter
shutdown.

The first full-suite attempt exposed two stale test artifacts rather than product failures:

- an assertion expected an old warning form without the exception class, while #167 intentionally
  preserves `RuntimeError:` in the warning;
- the route snapshot omitted the already-existing `/api/usage/readiness` endpoint from #154/#168.

Only those assertions/snapshot were refreshed; no unrelated production code changed.

## Independent mutation verification

Each mutation used a fresh backup, changed one guard/predicate, ran one focused test, restored the
file, and verified restoration. Every run produced exactly one expected failure.

| Mutation | Protection removed | Result |
|---|---|---|
| M1 | exact-first project lookup | 1 failed |
| M2 | unique casefold-alias reuse | 1 failed |
| M3a | canonical id propagation in API create | 1 failed |
| M3b | canonical id propagation in import | 1 failed |
| M4 | explicit project priority in GET | 1 failed |
| M5 | explicit project priority in PUT | 1 failed |
| M5b | core missing-authority rejection | 1 failed |
| M6 | foreign-prefix rejection | 1 failed |
| M7a | status route authority before prepayment | 1 failed |
| M7b | direct payment project predicate | 1 failed |
| M8 | blank commit-link authority rejection | 1 failed |
| M9 | merge-route project propagation | 1 failed |
| M10 | commit-link prefix guard | 1 failed |
| M11a | project CAS predicate | 1 failed |
| M11b | par CAS predicate | 1 failed |
| M11c | revision CAS predicate | 1 failed |
| M12 | task-associated scope-collision guard | 1 failed |

Raw outputs are `/tmp/pytest-169-mutation-*.log`; each ends with `1 failed` and the source was
restored before the next mutation.

## Compatibility and intentional breaking behavior

- Existing exact legacy project ids and their rows are unchanged.
- Missing get/update/link authority now fails with 4xx/`ValueError`; this is the intended fail-closed
  contract and replaces unsafe global fallback.
- Non-exact alias with multiple existing variants fails rather than selecting one.
- New case-only variants reuse one canonical stored id instead of creating a namespace.
- Explicit project takes precedence over scope, matching list→get/update continuity.
- No schema migration, live cleanup, data rewrite, deploy, service restart, or production request
  was performed.

## Review

External review was blocked and not retried or bypassed:

```text
weekly_quota_unknown: New Codex worker turn blocked: weekly quota status for gpt-5.6-sol is unavailable or stale (missing or legacy readiness policy). Stop/model change remain available.
```

Status: **external verdict unavailable**. A strict Sol self-review is recorded in
`docs/tasks/169/codex-review-impl.md`; it found and fixed the missing early write reservation in
`change_scope`. It is not claimed as an independent Codex verdict.

## Deferred cleanup

Cleanup of existing case-variant records remains a separate process: first produce a read-only
inventory/dry-run with task/client/payment/commit/session ownership evidence, then require explicit
human approval for each rename/merge decision. #169 deliberately provides no automatic cleanup or
migration implementation.

# #426 — Phase 2 plan: close the shadow creation window

## Decision

The broad finalizer fix is rejected. Fresh canonical-owner merge `0e95e45` succeeded, the isolated
dual-owner control succeeds, and the current finalizer correctly fails loud on a broken identity.

One supported current-main path still opens the historical window: `api_create_task` in `shadow`
mode commits the legacy row first and, when `store.task_create` raises, returns a normal task DTO
with `shadow_match=False`. The public API and taskless-worker assignment accept that DTO; manager
spawn detects the missing canonical identity one call later but leaves the legacy allocation
orphaned. The minimal change belongs at `app/tm.py:2063-2095`, where all three paths diverge.

## Mechanical writer inventory

Commands used:

```text
rg -n -F 'create_task(' app
rg -n -F 'create_task_for_scope' app
rg -n -F 'api_create_task' app
rg -n -F 'task_create(' app
rg -n -F 'INSERT INTO tm_tasks' app
rg -n -F 'UPDATE tm_tasks' app
```

An AST pass over `app/**/*.py` found one task-row INSERT owner (`app/tm.py:create_task`), one schema
copy INSERT (`app/db.py:1260`), and the call chain enumerated below. Literal `UPDATE tm_tasks`
sites were checked for identity fields; no application update changes `project_id` or `par_number`.

| Path | Concrete call chain / write | Can legacy exist without canonical at finalization? | Current-main verdict |
|---|---|---|---|
| Agent/API task creation | `mcp_stdio.task_create:2918` → `POST /api/tm/tasks` → `routes/tm.py:169` → public `tm.api_create_task:2043` | Canonical mode compares both next numbers, writes canonical first at 2114, then legacy with the exact number at 2128–2135. Candidate failure precedes legacy INSERT. | **Closed in canonical mode.** |
| HTTP route with no IA context | `routes/tm.py:169` is unconditional, but FastAPI serves only after `main.lifespan:440` yields *inside* `knowledge_runtime_mode:387`; that mode enters `ia_process_task_store_mode` before yielding at `runtime.py:1876-1877` | Runtime setup failure prevents lifespan yield, so the route cannot serve without an IA context. An offline direct route/function call has no worker; later canonical assignment calls `resolve_scoped_task_identity` and fails before binding if the candidate is absent. | **Closed for the supported HTTP/lifecycle path.** Tests/offline calls remain legacy compatibility, not a route to canonical finalization. |
| Spawn-time number allocation | `manager.py:801-810` and `routes/sessions.py:942-980` → `create_task_for_scope:375` → public `api_create_task` | Manager immediately calls canonical identity resolution at 806 and stops before assigning `allocated_task_id`; taskless-worker assignment proceeds directly to legacy `bind_task_to_session` at 978. The frozen regression proves the shared creation call raises before either caller can continue. | **Closed in canonical mode; OPEN through the shadow create return.** |
| Low-level legacy INSERT | `api_create_task:1394` → `create_task:299` → `INSERT INTO tm_tasks` at 345 | With an IA context, `create_task` refuses self-allocation when `par_number=None` at 318–323. The only production caller is the captured legacy adapter, and canonical mode supplies `_canonical_par_number`. | **Closed for lifespan/runtime callers.** Direct library calls outside lifespan are equivalent to unsupported manual mutation. |
| Shadow-mode creation | public `api_create_task:2063-2095`: commit legacy at 2070, then `store.task_create` at 2079; exception returns `_shadow_failure` DTO | Yes. Measured current-main probe: `candidate_write_failed`, `shadow_match=False`, and legacy row `project#1` remains while the caller receives a task result. | **OPEN — implementation target.** Raising here closes public API and both spawn consumers together. |
| Initial migration / gen2 reconciliation | `KnowledgeRuntime._task_store:621-640`; manifest bootstrap snapshots all legacy tasks; gen2 initialization and `verify_gates` call `reconcile_legacy_tasks` at `runtime.py:425-426,1633-1639` | Bootstrap/reconciliation fills missing canonical rows before the process shadow context is yielded. Migration itself does not create a new legacy identity. | **Closed at startup.** Live shadow writes can reopen it afterward, hence the target above. |
| Canonical gen3 startup | `knowledge_runtime_mode:1847-1877` selects canonical when `active_owner=canonical`; live state is generation 3 canonical | Public runtime creation uses canonical-first adapter. A pre-existing manual legacy-only row is detected by parity/finalizer, not silently accepted. | **Closed for supported writers.** |
| SQLite schema migration | `db.py:1228-1263` recreates `tm_tasks` with `INSERT … SELECT` from `_tm_tasks_old` | Copies the same identities during `init_db`; when canonical does not exist yet, subsequent manifest bootstrap snapshots them. It does not allocate a new task. | **Closed from a consistent starting state.** |
| Collision repair | `scripts/repair_task_par_collisions.py:395-423`: canonical repair first, guarded legacy `UPDATE par_number` second | A crash can leave the inverse state (canonical ahead), not legacy-only. Apply is bound to a fresh snapshot and exact row CAS. | **Closed for the target direction; no change.** |
| Application `UPDATE tm_tasks` | `tm.update_task:459-560` plus binding/completion/link updates at `tm.py:726,735,1257,1298,1305,1338` and `db.py:1624` | Field allowlist and literal SQL update status, binding, commits, price, or completion only. They neither insert nor change `(project_id, par_number)`. | **Closed.** |
| Manual SQL / offline import | Operator `INSERT`, or `UPDATE tm_tasks SET project_id/par_number=…`, or calling legacy API outside lifespan | Can create the gap by bypassing the public owner. SQLite cannot atomically update the filesystem/Git canonical store. | **Technically open but unsupported/out-of-contract.** Preserve fail-loud finalization; do not add a trigger or fallback that hides operator corruption. |
| Spawn compensation | `manager.py:897-915` → `discard_unbound_task:398` deletes a failed allocation only in legacy | Can create canonical-only state, the inverse direction. | **Not the #426 seam.** Record as a separate risk; do not broaden this ticket. |

## Planned change

### `app/tm.py`

Change only the shadow create exception branch at `api_create_task:2093-2095`, with one small
identity-guarded compensation helper adjacent to `discard_unbound_task`:

1. After candidate failure, probe the exact `(project, par)` through `store.task_get` *before* the
   fallible debt writer or any compensation.
2. Candidate definitely absent means only the current `TaskStore._find_state` contract:
   `ValueError("<par> not found")`. `KeyError`, another `ValueError`, or any read failure is
   ambiguous and never authorizes deletion.
3. On definite absence, delete only the unchanged legacy
   row named by the just-returned `id/project/par`, with guards `sync_revision=0`,
   `worker_session_id IS NULL`, empty commits, and no reservation. Status is not a guard: HTTP and
   internal callers can create non-`new` tasks. A decoy row in the same project must survive.
4. Candidate present, candidate outcome unreadable/ambiguous, or legacy row now bound/revised/
   committed/reserved → do not delete either owner.
5. After probe/compensation, attempt to preserve the existing `candidate_write_failed` debt.
   A debt-writer failure is secondary: log it, but do not skip compensation and do not replace the
   primary creation failure.
6. In every candidate-error branch, raise exactly
   `RuntimeError("shadow task creation failed: RuntimeError: candidate unavailable")` (with the
   actual exception class/message substituted) instead of returning an assignable task DTO.

This closes the route to finalization even when the candidate outcome is ambiguous, while avoiding
the more dangerous compensation error of deleting legacy after canonical already committed.

## Second owner of `api_update_task_if_current`

**Verdict: intentional adapter alias, not a mine for #426.** The first definition is frozen as
`_legacy_api_update_task_if_current` at `app/tm.py:1723`; the second definition at 2316 is the public
IA dispatcher and calls the alias when no IA context exists. The same transition pattern owns
create/update/list/get. It does not create task identities, so this plan does not refactor it.

## Scope and exclusions

- Phase-3 production file: `app/tm.py` only.
- Frozen oracle: `docs/tasks/426/acceptance/test_t1_shadow_task_creation.py` at commit `05f5f8c0`;
  it is immutable in Phase 3.
- RED commits `d032fe1f` and `8346b4dc` are excluded permanently: Luna named data-loss
  counterexamples they did not cover; the oracle was expanded and re-frozen before implementation.
- Do not change `finalize_merge_outcome`, `apply_merge_finalization`, `merge_operations`,
  `TaskStore._find_state`, runtime migration/reconciliation, collision repair, or schema.
- No migration and no repair of historical rows in this ticket.
- No cleanup/refactor of duplicated adapter definitions.

## Review-gate inputs

- Planned changed file and consumers: `app/tm.py`; consumers are `/api/tm/tasks`, MCP
  `task_create`, `manager.create_session` spawn allocation, and taskless-worker assignment.
- Author metadata: session `099f49e7-5751-42be-b821-40f99b3fb018` reports
  `model=gpt-5.6-sol`, `backend_type=codex`, `role=full-cycle`.
- Exact AC: the frozen T1 command is green; candidate-absent failure removes only the exact
  unchanged allocation; decoy/bound/revised/committed/reserved rows survive; non-`new` creation is
  compensated; candidate-present/KeyError/RuntimeError/non-not-found-ValueError outcomes preserve
  both owners; debt-writer failure cannot skip cleanup or replace the primary error; all candidate
  failures are loud and never return an assignable task.
- Named command observed RED: `uv run python -m pytest -q
  docs/tasks/426/acceptance/test_t1_shadow_task_creation.py` → RC=1, eleven failures: ten
  `Failed: DID NOT RAISE <class 'RuntimeError'>`/parameterized equivalents and one debt-writer
  message mismatch (`debt writer unavailable` replaced the required primary error).
- Risk floor: persistence and worker lifecycle. Sol would be the preferred technical reviewer, but
  no auxiliary Sol run is authorized; use one bounded Luna plan review under `codex-debate`.

## Luna Round 1 disposition

- No-context HTTP path — accepted and proved closed by the nesting of FastAPI lifespan yield inside
  `knowledge_runtime_mode`/`ia_process_task_store_mode`; no production fix added.
- `KeyError` candidate probe — accepted as ambiguous, not absence; preserve legacy and fail loud.
- Broad-delete/guard blocker — accepted; decoy plus bound/revised/committed/reserved cases were
  added before re-freezing.
- Unreadable candidate blocker — accepted; RuntimeError and KeyError probes preserve the row.
- Debt-writer ordering question — accepted; compensation/probe precedes best-effort debt recording,
  and the primary creation error remains authoritative.
- Spawn-path suggestion — accepted; manager and taskless-worker paths are now distinguished.

## Luna Round 2 disposition

- Non-not-found `ValueError` — accepted. `ValueError("candidate read malformed")` now joins
  RuntimeError and KeyError in the unreadable/ambiguous preservation case. RED `8346b4dc` is
  excluded and the oracle is re-frozen at `05f5f8c0`.

## Tickets

### T1 — Fail and compensate shadow task creation before assignment
- Files: `app/tm.py`; frozen oracle
  `docs/tasks/426/acceptance/test_t1_shadow_task_creation.py` (must not change)
- Test: `uv run python -m pytest -q docs/tasks/426/acceptance/test_t1_shadow_task_creation.py`
  — committed RED in `05f5f8c0` (`d032fe1f`, `8346b4dc` excluded after review)
- AC: the named command is green; `uv run python -m pytest -q
  tests/test_task_par_collision_406.py tests/test_task_completion_421.py` is green; Phase-3 diff
  contains no changes outside `app/tm.py` and the Phase-3 report
- blocked-by: none

## Frozen RED evidence

```text
$ uv run python -m pytest -q docs/tasks/426/acceptance/test_t1_shadow_task_creation.py
FFFFFFFFFFF                                                              [100%]
E   Failed: DID NOT RAISE <class 'RuntimeError'>
...
E   Expected regex: 'shadow task creation failed: RuntimeError: candidate unavailable'
E   Actual message: 'debt writer unavailable'
11 failed in 0.60s
```

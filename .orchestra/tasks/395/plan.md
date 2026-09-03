# #395 — Phase 2 plan: bounded startup, incremental task projections and idempotent create

Date: 2026-08-27. Phase-1 boundary approved by the orchestrator on 2026-08-27.

## Outcome

Finish the partial #405 mitigation without removing its resource receipts or corrupt-cache
recovery:

1. application readiness performs only constant-size projection receipt checks;
2. a task mutation changes only its canonical/task/current/FTS records and atomically advances
   global receipts;
3. healthy `task_list`/`task_get` read one SQLite snapshot without the writer RLock or canonical
   JSON files;
4. stale ordinary reads fail over with explicit debt and never repair O(N) inline;
5. `task_create` has a durable, reusable per-project request key across HTTP, MCP, legacy/shadow and
   canonical ownership.

The fixed cold-cache corpus is the performance oracle. Before implementation it contains
887,365,632 bytes / 16,730 current rows / 604 task states and measures startup/create/concurrent
list 213.691/108.216/107.953 seconds. The exact raw baseline is
`benchmark-main-8aed30c2-cold-cache-startup-20260827.raw.jsonl`.

## Safety invariants

- #405 remains the owner of immutable-resource receipts, retained resource payloads, SQLite
  sidecar cleanup, `quick_check`, and atomic corrupt-cache replacement. Hot paths become narrower;
  recovery does not become weaker.
- `canonical_head` and `projection_head` remain distinct. Canonical commit may advance first;
  projection receipt advances only in the same SQLite transaction as affected current/FTS rows.
- A CAS/SQLite failure leaves the old projection receipt and rows, records blocking debt with
  expected/observed heads, and never rolls back or duplicates the active-owner task.
- `replace_current()` and task `_rebuild_projection()` remain explicit repair/migration tools. No
  startup, task request or ordinary read calls them synchronously.
- Existing journal modes remain unchanged. This task does not introduce WAL.
- Generation 2/4 shadow failure returns the committed legacy task plus debt. Generation 3
  canonical failure returns/replays the committed canonical identity plus debt.
- Request-key scope is `(resolved_project_id, request_key)`. The same key and same normalized body
  replay one identity; the same key and a different fingerprint is a typed conflict.

## Implementation map

### `app/ia/projections.py`

- Add an O(1) `SQLiteProjectionBackend.current_receipt(expected_head)` query that reads only the
  singleton `projection_meta` row. A matching head plus both non-empty #405 resource receipts means
  only “one complete projection transaction was previously committed”; it is not proof that every
  later byte is uncorrupted. Readiness may admit that receipt without `_stored_resource_rows`,
  `_resource_fts_is_exact`, payload JSON or FTS scans because selected request rows still verify
  their stored digest/semantic match before service, and the owned background #405 pass verifies
  full rows/FTS. Corruption returns canonical fallback + debt and is never served.
- Keep `seal_current_resources()`, `replace_current_retaining_resources()` and
  `replace_current()` as explicit/background repair operations.
- Add `update_current_records(records, deleted_record_keys, expected_head, canonical_head)`:
  `BEGIN` → compare singleton head → targeted FTS delete by exact `record_key` → targeted ordinary
  UPSERT/delete → targeted FTS insert → update singleton head → commit. Resource receipt columns
  remain unchanged for task-only updates.
- Change `_query_projection()` to canonical fallback plus debt on missing/stale/mismatched
  projection. It never calls `replace_current()`. T4 reuses T1's `current_receipt` classification,
  debt reasons and single background-repair owner; that shared contract is its dependency.

### `app/ia/task_store.py`

- Add `ia_task_projection_meta(singleton=1, projection_head)` plus canonical
  `current-head.json` and `pending-generation.json` receipts. Existing unanimous per-row heads seed
  `current-head.json` only in explicit repair; missing/mixed input is debt, not silently blessed on
  a request. Every mutation writes the pending marker before event/state materialization, atomically
  replaces current-head last, then removes the pending marker. A crash at any intermediate step
  therefore leaves a constant-size durable recovery witness.
- Keep per-state `canonical_head` as the row's last materialized generation. `_current_head()` reads
  the canonical receipt; healthy request reads do not scan `state.json` files.
- Replace `_write_states()` on mutation with targeted state/event writes and a targeted
  task-projection UPSERT/delete in one SQLite transaction with the meta CAS. Unchanged `state.json`
  bytes and projection payloads are not rewritten. `_rebuild_projection()` remains recovery.
- Return internal changed-record metadata from mutation receipts. `_RuntimeTaskStore` consumes and
  strips it before public responses.
- `task_list`/`task_get` read projection meta + rows in one read transaction, validate selected row
  hashes/identity and overlay the global receipt. A stale/missing meta raises typed
  `ProjectionDebtError` immediately.

### `app/ia/runtime.py`

- Split current-projection work into constant-size receipt admission and explicit repair. Startup
  never enumerates resource/current/FTS rows. Missing/unsealed/mismatched receipt records
  `projection_receipt_unsealed` or `projection_head_mismatch` debt and exposes a repair request.
- Own one projection-writer lock shared by targeted updates and background repair; readers do not
  acquire it.
- `_RuntimeTaskStore._changed()` forwards internal changed identities to `_record_task_head()`;
  `_record_task_head()` advances runtime canonical head first, runs the targeted projection CAS,
  and advances runtime projection head only after success. On failure it preserves the old head and
  records `current_projection_update_failed` debt.
- Remove the writer RLock from `task_list`/`task_get` and remove `_ensure_task_projection()` from
  request reads. Keep writer serialization for mutations and explicit repair/reconciliation.
- In `app/tm.py`, shadow mode still reads legacy first and compares candidate; canonical mode reads
  only the canonical task projection and does not synchronously open the legacy mirror. Background
  parity/verification owns mirror comparison in canonical generation.

### `app/main.py`

- After the lifespan reaches its ready/yield boundary, own at most one bounded background
  projection-repair task when startup admission reported debt. The repair uses the existing #405
  validation/rebuild methods and the runtime projection-writer lock; it is not awaited before
  `Application startup complete`. Shutdown observes/cancels it without accepting a half transaction.
- The authoritative synchronous readiness seam is not inferred: current `app.main.lifespan()`
  enters `knowledge_runtime_mode()`, which calls `_sync_knowledge_generation()` →
  `_record_task_head()` → `_refresh_current_projection()` before the context yields. There is no
  second projection repair in lifespan. T1's direct seam test freezes that exact method contract;
  `repair_required` is the only value handed to the one post-yield owner, and the same-corpus
  startup timer covers the full `knowledge_runtime_mode()` entry that precedes Uvicorn's marker.

### `app/db.py`, `app/tm.py`

- Add non-destructive `tm_task_create_requests`:
  `(project_id, request_key)` primary key, `fingerprint`, `active_owner`, `generation`, `state`
  (`PENDING|ACTIVE_COMMITTED|MIRRORS_COMMITTED|FAILED`), legacy/canonical stable and display
  identities, bounded `response_json`/`error_json`, timestamps. Receipts remain for the task
  lifetime; no TTL reuses a key.
- Normalize the create body before fingerprinting. SHA-256 input includes project id, title, price,
  description, assignee, status, priority, acceptance command, sorted manifest, required flag and
  verified acceptance actor; generated ids/timestamps are excluded.
- Generation 2/4: claim key and insert legacy task plus `ACTIVE_COMMITTED` identity in one
  `BEGIN IMMEDIATE`; then idempotently mirror the stored display/stable identity. Mirror failure
  leaves `ACTIVE_COMMITTED` + debt and retry returns the active task immediately.
- Generation 3: claim `PENDING`, derive canonical stable/event UUIDs from project/key/fingerprint,
  idempotently commit canonical, then store `ACTIVE_COMMITTED`; retry of a crash between those steps
  probes that deterministic canonical event and repairs the coordinator before mirroring legacy.
- Concurrent same-key callers serialize on the coordinator row. `PENDING` without a proven active
  task returns typed in-progress with `Retry-After: 1`; different fingerprint is
  `IDEMPOTENCY_FINGERPRINT_MISMATCH`/HTTP 409.

### `app/routes/tm.py`, `app/mcp_stdio.py`

- Route key resolution: `Idempotency-Key` → `X-Request-ID` → generated 32-hex compatibility key;
  validate ASCII length 16–128 and return `request_key`/`replayed` in every success.
- Add project-authorized `GET /api/tm/task-create-requests/{request_key}`.
- `_api()` accepts optional `request_id` and `idempotency_key`; task-create sends the same value in
  both headers. MCP `task_create(request_key="")` generates a key when omitted, accepts the prior
  `ApiToolError.request_id` on retry, and `task_create_status()` resolves the durable receipt.

## Migration and compatibility

- New SQLite structures are additive. Existing task rows, task-current rows, #405 resource rows,
  FTS rows and receipts are not rewritten by `init_db()`.
- Missing task/current receipts after upgrade produce debt and background repair; no request path
  scans/rebuilds to perform the migration.
- Legacy callers without `Idempotency-Key` remain source compatible via `X-Request-ID` or a returned
  generated key. First-party MCP always knows the key before transport and can retry after timeout.
- Public task response fields remain; `request_key` and `replayed` are additive. Internal
  changed-record metadata is removed at the facade boundary.
- No VPS update, live DB mutation, service restart, journal-mode change or frontend change is part
  of implementation. The orchestrator owns any live restart/rehearsal.

## Crash/recovery state machines

### Canonical → task projection → joined current

Let `C0` be the committed canonical receipt and `P0=C0` both projection receipts.

1. Write `pending-generation.json` atomically with `parent_head=C0`, `intended_head=C1`, exact
   event ids, changed stable ids and their payload digests. A crash here is recoverable from C0 plus
   the pending witness.
2. Write immutable events and only changed state files. A crash before the head switch leaves the
   pending witness; explicit recovery verifies the staged event/state digests and either completes
   C1 or reconstructs C0 from the prior immutable event result. `recover_pending_generation()` is
   the explicit executor: for a complete staged generation it commits C1, removes the marker and
   returns task-projection debt `(expected=C1, observed=P0)`; an incomplete/digest-mismatched stage
   reconstructs C0 and reports `outcome=rolled_back`. Request/startup paths only record debt and do
   not replay.
3. Atomically replace `current-head.json` with C1. If a crash occurs before removing the pending
   marker, recovery observes `intended_head==C1` and clears the completed marker idempotently.
4. Persist runtime `canonical_head=C1, projection_head=P0`. The canonical receipt is the source of
   truth if a crash happens before this runtime-state write; startup derives the same gap by reading
   canonical current-head and projection meta, then records expected/observed debt.
5. In one SQLite transaction CAS task/current projection meta from P0 to C1 while updating exact
   rows/FTS. Error/crash before commit rolls all rows and receipt back to P0. After commit the whole
   new snapshot is C1.
6. Persist runtime `projection_head=C1` and clear only the matching debt. A crash before this write
   is repaired by comparing canonical and SQLite receipts, never by trusting stale runtime-state.

The durable pending marker or a canonical/projection head gap exists before every interval where
new canonical data lacks a matching projection. Debt is derived from those owners on restart; it
need not have been written by the process that crashed.

### Task-create coordinator

1. `BEGIN IMMEDIATE` inserts/reads `PENDING(project,key,fingerprint,owner,generation)` before active
   creation. Same-key/different fingerprint is terminal 409; same-key PENDING without a proven
   active identity returns 409 + `Retry-After: 1` and never waits behind the creator.
2. Generation 2/4 inserts the legacy task and writes `ACTIVE_COMMITTED` identity/response in that
   same transaction. A crash cannot expose one without the other.
3. Generation 3 passes project/key/fingerprint-derived stable/event ids to canonical TaskStore.
   TaskStore replay of that deterministic event is idempotent. If the process crashes after
   canonical current-head C1 but before coordinator `ACTIVE_COMMITTED`, retry probes the exact
   deterministic event and fingerprint, promotes the existing identity, and creates no second task.
4. Mirrors consume only stored active stable/display identity. Each successful mirror advances
   `MIRRORS_COMMITTED`; failure leaves `ACTIVE_COMMITTED` plus bounded `error_json`/debt. Retry
   returns the active response first and resumes mirrors idempotently.
5. Status lookup returns PENDING/ACTIVE/MIRRORS/FAILED only after project authorization. Receipts
   remain for the task lifetime, so a previously used key cannot become a new create later.

## Same-corpus measurement protocol

The before artifact is immutable. After T1 and again after the final dependent ticket, run the
same production-interpreter harness against the same ignored `Connection.backup` source:

```bash
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python \
  docs/tasks/395/benchmark_tm.py run \
  --source data/task-395/frozen-current-20260827 --iterations 1 \
  --project /home/kesha/orchestra \
  --startup-receipts cleared --startup-page-cache dropped \
  --output docs/tasks/395/benchmark-after-<ticket>-cold-cache.raw.jsonl
```

`compare_benchmark.py` rejects corpus identity drift (`30`-second deadline, `16,730` current rows,
`604` task rows), unequal non-summary row counts and absent metric fields before applying
thresholds; it uses the maximum across every after-row, not a median that can hide a slow
iteration. T1 requires the projection-owned interval preceding
`Application startup complete` (`startup_runtime_seconds`) ≤30.000 seconds; the current direct
baseline is 213.691. T2/final requires create and concurrently-entering list each ≤30.000 seconds;
the current direct baseline is 108.216/107.953. Per-run loadavg remains in the raw rows. The
orchestrator may additionally rehearse the actual Uvicorn marker after merge/restart authorization;
that live action is not delegated to the implementer.

## Review decision inputs

- Changed plan/oracle consumers: this plan, two committed RED pytest files and the committed
  same-corpus comparator; Phase 3 executors and the orchestrator are consumers. Planned production
  surface is shared startup/runtime, persistence schema, lock/concurrency and external MCP/HTTP.
- Author model/runtime: assigned `gpt-5.6-sol` Codex full-cycle session.
- Exact AC: each ticket's named pytest command green; T1/T2 benchmark comparator thresholds green;
  receipt/debt/idempotency invariants below remain exact.
- Named checks: T1–T5 commands below currently exit 1 for missing behavior; comparator commands
  currently exit 1 at 213.691 startup and 108.216/107.953 create/list.
- Risk floor: high (startup/readiness, persistence migration, concurrency and external API). The
  canonical technical route would be Sol, but the orchestrator explicitly forbade an auxiliary
  Sol run and allowed Luna. Use one fresh targeted Luna plan review; a second Luna round is legal
  only after a verified blocking finding changes this prose.

## Review outcome

- Route: Luna, two completed prose rounds (ceiling); one input-validation refusal did not consume a
  model round. No Sol call ran.
- Round 1: three blocking plus four suggestions and one question; all changed the plan or committed RED
  oracles. Round 2 marked every prior finding fixed.
- Round 2 new blocker: pending marker existed but recovery was not executed. Fixed post-ceiling in
  `58704831`: the RED now requires `recover_pending_generation()` to complete C1, validate
  state/event, expose P0 debt and delete the marker. The same commit adds concurrent old/new
  snapshot coverage and comparator row-count/metric guards.
- The reviewer artifact's final model verdict remains `NEEDS WORK` because the blocker was found in
  the final permitted round. No third approval was fabricated. `review-plan.md` preserves the
  finding, exact disposition and post-ceiling evidence; no blocking finding remains ignored.

## Tickets

### T1 — Make application readiness O(1) and defer projection repair
- Files: `app/ia/projections.py` (`current_receipt`, existing repair methods),
  `app/ia/runtime.py` (startup admission/debt/repair lock), `app/main.py` (post-ready repair task),
  `tests/test_tm_projection_hotpath_395.py`.
- Test: `/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q tests/test_tm_projection_hotpath_395.py::test_t1_startup_readiness_never_scans_projection_rows --timeout=30` — committed RED in `5b4e9fa1`.
- AC: named pytest command is green; present receipts use no `_stored_resource_rows`,
  `_resource_fts_is_exact`, payload or FTS scan; cleared receipts return readiness with durable
  `projection_receipt_unsealed` debt and one owned background repair; #405 corruption recovery
  remains green. Run the same-corpus command above with output
  `docs/tasks/395/benchmark-after-t1-cold-cache.raw.jsonl`, then
  `/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python docs/tasks/395/compare_benchmark.py --before docs/tasks/395/benchmark-main-8aed30c2-cold-cache-startup-20260827.raw.jsonl --after docs/tasks/395/benchmark-after-t1-cold-cache.raw.jsonl --expected-current-rows 16730 --expected-task-rows 604 --max-startup-seconds 30` is green.
- blocked-by: none
- RED: `Failed: startup readiness entered an O(N) projection scan` (2 parametrized failures); comparator exit 1: `startup_runtime_seconds=213.690755 > 30.000000`.

### T2 — Update canonical task, task projection, joined current and FTS by named identity
- Files: `app/ia/task_store.py` (canonical/meta receipts and targeted projection mutation),
  `app/ia/projections.py` (`update_current_records`), `app/ia/runtime.py` (changed-record propagation,
  CAS/debt/head ordering), `tests/test_tm_projection_hotpath_395.py`.
- Test: `/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q tests/test_tm_projection_hotpath_395.py::test_t2_task_store_mutation_updates_one_projection_row tests/test_tm_projection_hotpath_395.py::test_t2_joined_current_mutation_updates_named_task_and_fts_only tests/test_tm_projection_hotpath_395.py::test_t2_projection_failure_keeps_old_receipt_and_records_debt tests/test_tm_projection_hotpath_395.py::test_t2_targeted_sqlite_failure_rolls_back_rows_fts_and_receipt tests/test_tm_projection_hotpath_395.py::test_t2_restart_derives_debt_from_canonical_projection_head_gap tests/test_tm_projection_hotpath_395.py::test_t2_interrupted_canonical_generation_leaves_recoverable_pending_marker --timeout=30` — committed RED in `58704831` (base CAS/head-gap tests in `85017d25`; marker base in `eefe4f84`).
- AC: named pytest command is green; unchanged canonical files and current/resource rows are
  byte-identical; exactly the named task/current/FTS rows change; `ia_task_projection_meta` and
  joined `projection_meta` advance atomically; a real SQLite trigger failure rolls back row/FTS/meta;
  integration failure leaves old projection head and `current_projection_update_failed` debt;
  restart derives expected/observed debt from a canonical/projection gap; interruption before
  canonical head switch leaves a marker whose explicit recovery completes C1, preserves P0 as
  observed projection debt, validates state/event materialization and removes the marker. Run the same-corpus command with output
  `docs/tasks/395/benchmark-after-t2-cold-cache.raw.jsonl`, then
  `/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python docs/tasks/395/compare_benchmark.py --before docs/tasks/395/benchmark-main-8aed30c2-cold-cache-startup-20260827.raw.jsonl --after docs/tasks/395/benchmark-after-t2-cold-cache.raw.jsonl --expected-current-rows 16730 --expected-task-rows 604 --max-create-seconds 30 --max-contended-list-seconds 30` is green.
- blocked-by: T1
- RED: `Failed: task mutation rebuilt the whole task projection`; `Failed: task mutation entered bulk retained refresh`; receipt assertion observed new projection head instead of the old head; `update_current_records`, canonical `current-head.json` and executable pending recovery are absent; restart attempted inline repair; comparator exit 1 at create/list `108.215953/107.953024 > 30`.

### T3 — Serve task reads from one projection snapshot without writer RLock
- Files: `app/ia/task_store.py` (`task_list`, `task_get`, projection read transaction),
  `app/ia/runtime.py` (`_RuntimeTaskStore.task_list/task_get`), `app/tm.py` (generation-specific
  stale projection response), `tests/test_tm_projection_hotpath_395.py`.
- Test: `/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q tests/test_tm_projection_hotpath_395.py::test_t3_task_reads_finish_while_writer_critical_section_is_held tests/test_tm_projection_hotpath_395.py::test_t3_task_reads_use_projection_not_canonical_state_files tests/test_tm_projection_hotpath_395.py::test_t3_canonical_api_reads_do_not_open_legacy_owner tests/test_tm_projection_hotpath_395.py::test_t3_sqlite_reader_observes_one_old_snapshot_during_targeted_write --timeout=30` — committed RED in `58704831` (base read/API tests in `5715f8a0`, `85017d25`).
- AC: named pytest command is green; both list/get finish from a complete old/new SQLite snapshot
  while a writer holds its mutation lock; neither opens canonical state files nor calls
  `_ensure_task_projection`; stale generation 2/4 returns legacy + explicit debt, generation 3
  fails fast with expected/observed heads; canonical API list/get never open legacy synchronously;
  a reader transaction spanning meta+rows remains entirely on P0 while a concurrent targeted
  writer commits P1, then the next transaction sees P1.
- blocked-by: T2
- RED: `AssertionError: task_list waited behind the writer RLock`; `Failed: request-time task read opened canonical state files`; `Failed: canonical API read opened the legacy owner`; targeted snapshot writer API is absent (6 failures total).

### T4 — Make ordinary joined-current reads fallback-only, never repair
- Files: `app/ia/projections.py` (`_query_projection`), `app/ia/runtime.py` (repair/debt owner),
  `tests/test_tm_projection_hotpath_395.py`.
- Test: `/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q tests/test_tm_projection_hotpath_395.py::test_t4_stale_current_read_falls_back_without_projection_repair tests/test_tm_projection_hotpath_395.py::test_t4_corrupt_current_data_is_never_served_before_background_validation --timeout=30` — committed RED in `85017d25` (stale base test in `5715f8a0`).
- AC: named pytest command is green; stale read leaves projection bytes unchanged, returns canonical
  truth with `source=canonical-fallback`, and includes `projection_stale_no_repair` debt; matching
  non-empty receipts are only a commit marker, so selected payload hash and FTS semantic mismatch
  both return canonical truth with `projection_corrupt_no_repair`; no `replace_current()` or other
  O(N) write occurs on query.
- blocked-by: T1
- RED: `Failed: ordinary read attempted O(N) projection repair`; `Failed: corrupt ordinary read attempted inline projection repair` (3 failures total).

### T5 — Make task_create idempotent end-to-end by durable request key
- Files: `app/db.py` (`tm_task_create_requests`), `app/tm.py` (fingerprint/coordinator and both
  ownership orders), `app/ia/task_store.py` (deterministic canonical request identity),
  `app/routes/tm.py` (headers/status/conflicts), `app/mcp_stdio.py` (key reuse/status tool),
  `tests/test_task_create_idempotency_395.py`.
- Test: `/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q tests/test_task_create_idempotency_395.py --timeout=30` — committed RED in `85017d25` (canonical identity base in `da713fd5`).
- AC: named pytest command is green; concurrent same-key/same-body calls produce one task and one
  durable receipt with one replay; different body is HTTP 409
  `IDEMPOTENCY_FINGERPRINT_MISMATCH`; retry after legacy active commit returns the same identity
  while mirror debt remains; canonical same-key replay uses one deterministic stable/event identity;
  MCP accepts `request_key`, passes it as both request/idempotency key, and status lookup exists;
  HTTP behavior covers `X-Request-ID` fallback, generated compatibility key, validation and
  project-authorized status; canonical HTTP replay/conflict and PENDING-after-canonical crash
  recover one deterministic identity; PENDING without active identity returns Retry-After instead
  of waiting. Existing create tests without an explicit key remain green through compatibility
  generation.
- blocked-by: T2
- RED: legacy/canonical concurrent or repeated calls returned distinct ids; different body returned a second task instead of JSON 409; mirror retry duplicated; HTTP response lacks fallback/generated key and status path; PENDING retry waited behind creator; MCP and canonical `task_create` signatures lack `request_key` (8 failures total).

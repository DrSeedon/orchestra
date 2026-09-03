# #426 — bounded durable task-projection delivery

## Approved boundary

The approved architecture is the **bounded** variant. A successful live canonical-mode
`POST /api/tm/tasks` or `PUT /api/tm/tasks/{par}` must mean:

1. the task mutation is present in legacy SQLite;
2. the same mutation is present in the Git-canonical `TaskStore`;
3. a Git-committed, ordered receipt exists for the joined `current.db` projection before the
   response returns;
4. the projection applies after the response, survives restart, and cannot be overtaken by a
   later receipt.

The approved scope explicitly does **not** add automatic reconciliation for a crash between the
two task owners and does not change shadow-mode debt semantics. Those pre-response gaps remain an
operator-visible/manual-repair boundary. This choice follows the user's instruction “426 чини
корень”: remove the every-write storage-volume cost without expanding the rare cross-store crash
case into a new transaction state machine.

The unrelated laptop #426 artifacts are retained under `*-laptop-merge-finalization*` names. The
VPS latency task owns the canonical `research.md`, `plan.md`, review, and eventual `report.md`.

## Current source and unchanged owners

- `app/ia/runtime.py:_record_task_head` currently deep-copies/serializes every evidence record,
  runs `_commit_canonical()` with `git add -A`, and calls
  `SQLiteProjectionBackend.update_current_records()` before returning.
- `app/ia/task_store.py:_commit_generation` already writes the changed task event/state/head and
  targeted task projection before `_RuntimeTaskStore._changed` calls `_record_task_head`.
- Current canonical `app/tm.py:api_create_task` and `api_update_task` validate/write legacy before
  the canonical TaskStore mutation. Therefore the normal successful POST/PUT reaches
  `_record_task_head` only after legacy has committed; #426 does not change this ordering.
- `app/ia/projections.py:update_current_records` already atomically updates selected rows, their FTS
  rows, and the singleton projection head through a head CAS. It stays the projection apply owner.
- `app/main.py:lifespan` already stores the task returned by `schedule_projection_repair()` and
  cancels/awaits it during shutdown. No `app/main.py` change is expected unless implementation
  proves the existing ownership seam insufficient.

Current worker HEAD is behind `main`, but `git diff HEAD..main` is empty for every #426-owned
production/test path at planning time. Phase 3 must rerun both frozen RED commands before touching
production and must integrate current `main` before final acceptance.

## Design

### Exact combined head without request-time evidence work

`KnowledgeRuntime.__init__` builds one cached SHA-256 prefix after `_import_scope_evidence()` has
finished. The prefix is the exact byte prefix used by the existing sorted-JSON formula:

```text
{"evidence":<sorted normalized evidence>,"knowledge_head":
```

For a task write, a copy of that hash state appends only the current `knowledge_head`, the new
`task_head`, and the closing bytes. The resulting `canonical_head` must be byte-for-byte equal to
the existing `_bytes({task_head, knowledge_head, evidence})` digest; there is no head migration.
`_import_scope_evidence()` invalidates the prefix before import and rebuilds it after import. The
serving invariant is explicit: evidence is immutable after prefix construction; any future live
evidence writer must invalidate/rebuild under the canonical Git lock before it may publish.

The 0-record and 20,000-record oracle populates both the evidence corpus and `current.db`, then
measures request work by calls, not noisy wall-clock. After one warm setup, POST+PUT must make zero
`evidence_records()` calls, zero serialization calls whose object contains `evidence`, and zero
`SQLiteProjectionBackend` constructions in both corpus arms. Exact head equality is asserted
independently. This proves the response path no longer scales with either evidence or current.db;
the required live curl numbers remain the wall-clock acceptance.
The same oracle inspects legacy and canonical immediately after POST and before PUT, so PUT cannot
hide a missing POST write. A separate blocking-commit test pauses the canonical Git commit, proves
the HTTP request is still unfinished while the receipt already exists, then releases the commit and
compares the returned receipt bytes with `git show HEAD:<path>`.

### Durable linked outbox before success

Receipts live under the canonical Git repository at:

```text
projection-outbox/<entry-id>.json
```

Each pending receipt has exactly the state needed for a targeted CAS:

```text
schema_version = 1
entry_id
expected_projection_head
target_canonical_head
records                     # exact changed task/fact payloads
deleted_record_keys         # empty for current task writes, retained for schema completeness
```

`entry_id` is unique and is also the applied-marker identity. The loader rejects malformed JSON,
unsupported versions, absent/duplicate entry or record identities, duplicate targets, forks,
cycles, and a chain whose first unapplied `expected_projection_head` does not match the SQLite
receipt.

One process-wide re-entrant canonical Git lock owns every `_commit_canonical()` call. The function
gains an optional pathspec; existing bootstrap/import/receipt callers keep their current default,
while the task response path stages only `tasks/` and its new outbox file. It must not stage or scan
`evidence/`. The frozen test places an untracked evidence sentinel before POST/PUT and requires it
to remain untracked while every pending outbox receipt is visible in `git ls-files`.

Under that lock, `_record_task_head`:

1. derives the new exact combined head from the cached prefix;
2. validates the durable pending chain;
3. chooses `expected_projection_head` from the durable queue tail target, or from persisted
   `state["projection_head"]` when the queue is empty;
4. atomically writes the receipt and saves `state["canonical_head"]` without advancing
   `state["projection_head"]`;
5. commits task files plus the receipt with a scoped Git commit;
6. only after commit success signals the in-memory wakeup and returns.

A Git commit failure propagates through the existing route error handling; it cannot produce HTTP
200. The task files may exist in the bounded pre-response failure window, but the caller is not
told the operation succeeded. Existing request-key recovery remains the retry identity owner.

### Long-lived restart-safe drainer

`schedule_projection_repair()` becomes a long-lived task even when startup did not set
`_projection_repair_required`. It scans the durable outbox before waiting and after each wake. The
wakeup is only an optimization: clearing it is followed by another durable scan before waiting, so
enqueue during the clear/wait edge cannot sleep until the next process start.

The synchronous drain pass selects by head linkage, never filename order:

1. SQLite already equals `target_canonical_head` → do not reapply; proceed to durable ack;
2. SQLite equals `expected_projection_head` → call the existing atomic
   `update_current_records()` CAS once;
3. any other head or invalid receipt → leave all affected receipts, record
   `projection_outbox_invalid`/`projection_outbox_blocked` debt, and stop targeted drain;
4. after SQLite success, save `state["projection_head"]`, then acknowledge under the canonical Git
   lock.

Acknowledgment is two-phase so a crash cannot turn “SQLite committed” into “work forgotten”:

1. write and Git-commit an applied marker under `projection-outbox-applied/<entry-id>.json` while
   the pending receipt still exists;
2. only after that commit, remove and Git-commit the pending receipt;
3. clean the applied marker in a later commit; on startup, reconcile these paths from Git HEAD
   before trusting working-tree absence.

Git HEAD is the only durable verdict during restart reconciliation. For a tracked receipt/marker
that is missing or byte-different in the working tree, restore the HEAD bytes under the Git lock,
record `projection_outbox_worktree_diverged`, and replay from that durable state. A path that exists
only in the working tree is never accepted as a receipt or applied proof: record the same debt,
discard the uncommitted derived marker, and keep/replay the HEAD-tracked pending receipt. This makes
a crash during `unlink`/`git commit` fail toward duplicate-safe replay, not lost work.
On an existing canonical repository, `KnowledgeRuntime.__init__` performs this outbox-only
HEAD/worktree reconciliation **before** `_initialize_canonical_git()` can run any default
`git add -A`; otherwise bootstrap would accidentally commit the interrupted deletion or false
marker that recovery is meant to reject.

If the process dies after SQLite commit but before acknowledgment, restart sees SQLite at the
receipt target, writes the applied marker, removes the receipt, and advances to the next linked
entry without applying the first payload twice. A later enqueue reads the durable pending tail
under the same Git lock, so it cannot attach behind a stale projection head while cleanup is in
flight.

The lock order is deliberately non-nested. Enqueue takes only the canonical Git lock. A drain pass
takes `_projection_writer_lock` through the closed SQLite transaction, releases it, and only then
takes the canonical Git lock for acknowledgment; no code may hold both locks simultaneously. The
interleaving oracle blocks the first SQLite apply, requires a concurrent enqueue to finish before
SQLite is released, verifies that its receipt attaches after the durable queue tail, and then
observes apply order A→B→new target.

Malformed receipts never trigger the recovery full rebuild and are never deleted merely to make
the queue empty. Missing fields, forks, cycles and duplicate targets each preserve a byte-identical
snapshot of `current_records`, `current_fts` and `projection_meta`; they remain as positive evidence
of unfinished work plus visible debt. The
existing `_repair_current_projection()` stays the recovery-only owner for missing/corrupt
`current.db`; it is not called by an ordinary valid receipt chain.

The long-lived coroutine must be cancellable while idle. The oracle is intentionally limited to
direct cancellation/await of the exact task returned by `schedule_projection_repair()`;
`app.main._shutdown_runtime` already cancels and awaits the passed task, and this plan makes no
`app.main.py` behavior change. If implementation requires another child task or an `app.main.py`
change, T2 is no longer closed and must return to planning. Synchronous drain passes are bounded to
one receipt/ack transition so shutdown leaves no second unowned wakeup task.

## Concurrency boundary

#426 orders the **joined projection** after canonical task generations have been accepted. It does
not add cross-process retries around `TaskStore._ensure_expected`, and therefore does not claim to
fix today's two `ConcurrentTaskUpdateError` finalization failures. In-process runtime task writes
remain serialized by `_RuntimeTaskStore._lock`; the new Git lock prevents the projection drainer
from racing enqueue/cleanup in the same process. A canonical head changed by another process or
contour remains a fail-loud CAS conflict and needs a separate task if it reproduces after #426.

## Live acceptance after merge/restart

The historical before baseline remains the supplied production measurement:

```text
GET 1.36 / 1.68 / 2.04 s
POST 20.84 s
PUT 19.60 / 18.12 s
evidence records 47,834; current.db 2.32 GB
```

Phase 3 is not fully DONE until the implementation is merged to `main`, the service is restarted,
and the same local HTTP path is measured. The merge must use `task_outcome="continue"` for that
deployment check. Record the complete output and HTTP bodies from these non-pipelined commands:

```text
curl -sS -o /tmp/426-post.json -w 'POST code=%{http_code} time_total=%{time_total}\n' \
  -H "Authorization: Bearer $INTERNAL_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: task-426-live-post-v1' \
  -d '{"project":"/home/kesha/orchestra","title":"#426 live projection receipt"}' \
  http://127.0.0.1:8888/api/tm/tasks

curl -sS -o /tmp/426-put.json -w 'PUT code=%{http_code} time_total=%{time_total}\n' \
  -H "Authorization: Bearer $INTERNAL_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"#426 live projection receipt applied"}' \
  "http://127.0.0.1:8888/api/tm/tasks/<PAR>?project=/home/kesha/orchestra"
```

Both must return 2xx within the existing 30-second MCP deadline. The report records the exact new
times rather than replacing them with “faster”. Then verify positive state, not queue emptiness:

- canonical GET for `<PAR>` returns the updated title and stable ID;
- read-only legacy SQLite query returns the same project/number/title;
- joined `current.db.current_records.payload_json` for that stable ID contains the updated title;
- `projection_meta.projection_head` equals the task response/runtime canonical head;
- only after those four positives may the pending receipt be reported absent.

The deterministic 0-versus-20,000 oracle is the size-dependence gate; live curl is the production
wall-clock evidence. A result above 30 seconds fails. Lower values are reported as measurements,
not promoted to a fabricated universal latency threshold.

## Files and exclusions

- Production: `app/ia/runtime.py`.
- Existing consumers verified but not expected to change: `app/ia/task_store.py`,
  `app/ia/projections.py`, `app/main.py`, `app/tm.py`, `app/routes/tm.py`.
- Frozen oracle: `tests/test_task_write_outbox_426.py` at `b69568ef`; Phase 3 must not edit it
  without another explicit refreeze decision.
  Earlier RED `043ea118` is excluded permanently: first-round review proved it did not cover
  response/commit ordering, POST-before-PUT ownership, applied-marker durability, dirty worktree,
  concurrent enqueue, full malformed SQLite state, or lifecycle cancellation.
  RED `c5d7e68a` is also excluded: final plan review proved its volume arm left `current.db` empty
  and its valid drain asserted the row but not FTS.
  RED `33350772` is excluded forever for exactly this reason: «assert привязал applied-marker к
  возврату метода SQLite вместо результата drain/ack». The corrected crash oracle runs one
  synchronous drain transition with pending deletion forced to fail, then asserts the marker is in
  Git HEAD while both receipts remain; a fresh runtime executes exactly two progress transitions
  and one idle transition, proving A is not reapplied, only B is applied, receipts/marker disappear,
  and final row/FTS/head agree. It contains no sleep or wall-clock timeout.
  Oracle `09e7b152` is excluded forever because “polling helper sampled a receipt concurrently
  with its legitimate deletion”. Final oracle `b69568ef` keeps the same durable-artifact
  assertions but treats `FileNotFoundError` between `glob` and `read_text` as the receipt already
  being drained; it adds no production hook, sleep, polling rule, or wall-clock threshold.
- Documentation: `docs/tasks/426/plan.md`, review artifact, eventual `report.md`;
  `docs/workers/fix-tm-hang.md` only if the final personal-memory check finds a reusable lesson.
- Do not touch `app/session.py`, `app/backend_codex.py`, `app/harness/`, or `app/static/`.
- No schema migration, task-owner ordering change, shadow-mode change, timeout increase, vector
  re-enable, or broad canonical↔legacy reconciliation.

## Review-gate inputs

- Changed files/consumers: frozen test plus this plan; planned production owner is
  `app/ia/runtime.py`, consumed by canonical POST/PUT, TaskStore facade writes, joined current
  reads, and `app.main.lifespan` shutdown.
- Author metadata: current session reports `gpt-5.6-sol`, Codex full-cycle runtime.
- Exact AC: both frozen commands green, #395 projection/idempotency regressions green, full
  merge-gate green, then post-merge curl and three-storage positive verification above.
- Historical RED commands are recorded below with their excluded revisions; the current approved
  oracle is `b69568ef` and is verified by the required mutation plus repeated green runs.
- Risk floor: shared persistence, Git/SQLite ordering, background lifecycle, concurrency. Sol is
  the preferred route, but no auxiliary Sol run is authorized; use one bounded Luna plan review.

## Luna Round 1 disposition

All eight findings were checked against the oracle and accepted:

1. response ordering now has a blocked Git-commit barrier plus `git show HEAD:<receipt>` evidence;
2. both task owners are asserted immediately after POST, before PUT;
3. SQLite-before-ack requires a still-present receipt and a Git-committed applied marker;
4. missing/different tracked paths and worktree-only markers have explicit Git-HEAD-first recovery
   before bootstrap staging, with two dirty-state cases;
5. malformed receipts preserve complete row/FTS/meta snapshots;
6. locks are never nested, and a blocked SQLite apply must not block concurrent enqueue/tail link;
7. the idle long-lived task is canceled and awaited;
8. missing fields, fork, cycle and duplicate target are independent cases.

The original RED `043ea118` is excluded. The expanded intermediate oracle was frozen at
`c5d7e68a`; its T1 and T2 commands failed only on missing receipt/drainer behavior and contained no
import, collection, or attribute error.

## Luna Round 2 disposition and ceiling

Round 2 marked findings 1–6 and 8 fixed. The lifecycle suggestion remains deliberately scoped to
direct cancellation because production keeps the same single returned task and unchanged
`app.main._shutdown_runtime` owner. Two new blocking gaps were accepted:

- the large evidence arm had an empty `current.db`; the final oracle now populates 20,000 joined
  rows and counts every `SQLiteProjectionBackend` construction, not one method name;
- valid drain checked the final row but not FTS; the final oracle now requires the matching FTS
  rowid/record key and searchable `B` text.

The last pre-implementation oracle was frozen at `33350772`; it is now excluded for the timing
assertion above, and the approved final oracle is `b69568ef`. Plan prose has exhausted the two-round review ceiling,
so no third model call is permitted; the on-disk reviewer verdict remains `Needs work` from before
these two accepted corrections. The exact new RED commands below are the mechanical closure
evidence, and the orchestrator decides the Phase-3 gate.

## Tickets

### T1 — Return POST/PUT after both task owners plus a constant-work durable receipt
- Files: `app/ia/runtime.py`; immutable `tests/test_task_write_outbox_426.py`
- Test: `.venv/bin/python -m pytest -q tests/test_task_write_outbox_426.py -k t1` — committed
  RED in `33350772`
- RED: both corpus arms fail `POST returned before creating a projection receipt`; the independent
  commit barrier fails `commit barrier was reached without a projection receipt`. Output:
  `3 failed, 1 passed, 10 deselected in 14.62s`, RC=1. The passing Git-failure control proves the
  red is not a general route failure.
- AC: the named command is green; POST and PUT are 200; immediately after POST (before PUT), legacy
  and canonical titles both equal `created` and the receipt is byte-identical to Git HEAD; while
  its commit is blocked the HTTP response remains pending; final legacy and canonical titles both
  equal `updated`; each 0/20,000 evidence+current-row arm records zero evidence calls, zero
  evidence-object serializations, zero joined-projection constructions and zero joined-projection
  calls after warm setup; the exact combined head is
  unchanged; the outbox chain is non-empty, Git-tracked and ends at that head; the unrelated
  evidence sentinel remains untracked; injected outbox Git failure cannot return 200.
- blocked-by: none

### T2 — Apply durable receipts in head order across restart and acknowledgment crashes
- Files: `app/ia/runtime.py`; immutable `tests/test_task_write_outbox_426.py`
- Test: `.venv/bin/python -m pytest -q tests/test_task_write_outbox_426.py -k t2` — committed
  RED in `33350772`
- RED: ten restart/lifecycle cases fail because `schedule_projection_repair()` returns no durable
  drainer: valid chain, ack crash, four malformed chains, two dirty Git/worktree states,
  concurrent enqueue, and idle cancellation. Output: `10 failed, 4 deselected in 17.18s`, RC=1.
- AC: the named command is green; a fresh `KnowledgeRuntime` with no in-memory wake applies
  reverse-filename receipts strictly by their expected→target chain; selected row, FTS and head
  reach the final receipt, including the matching FTS rowid/key and searchable final title; a
  forced failure after SQLite commit leaves both pending receipts plus
  a Git-committed applied marker, and restart skips the first payload, applies only the second and
  cleans both directories; HEAD-missing and worktree-only paths reconcile without false ack and
  record visible divergence debt; concurrent enqueue finishes while SQLite is blocked, extends the
  tail and drains after A→B; missing-field/fork/cycle/duplicate-target inputs stay on disk, record
  visible debt and preserve rows, FTS and meta byte-for-byte; the idle long-lived task cancels and
  awaits cleanly. The existing full-repair and #395 suites remain green. After merge/restart, the
  two curl commands return 2xx under 30 seconds and the canonical, legacy, joined-row and
  projection-head positives all match before receipt absence is accepted.
- blocked-by: T1

## Frozen RED evidence

```text
$ .venv/bin/python -m pytest -q tests/test_task_write_outbox_426.py -k t1
FFF.                                                                     [100%]
E       AssertionError: POST returned before creating a projection receipt
E       AssertionError: commit barrier was reached without a projection receipt
3 failed, 1 passed, 10 deselected in 14.62s
RC=1

$ .venv/bin/python -m pytest -q tests/test_task_write_outbox_426.py -k t2
FFFFFFFFFF                                                               [100%]
E       AssertionError: restart did not start the durable outbox drainer
E       AssertionError: restart ignored Git HEAD/worktree outbox divergence
E       AssertionError: lifespan received no long-lived projection drainer
10 failed, 4 deselected in 17.18s
RC=1
```

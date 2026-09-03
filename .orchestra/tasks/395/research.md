# #395 — Phase 1: TM mutation latency, reader isolation and retry identity

Date: 2026-08-26; current-main/startup recheck: 2026-08-27. This document extends, and does not
replace, `root-cause.md` [1].

## Question

- **Context:** production runs generation-2 shadow ownership: legacy `tm_*` SQLite remains the
  active task owner while the Git-canonical `TaskStore`, `task-current.db`, and the joined
  `current.db`/FTS projection are updated synchronously [2].
- **Change under test:** finish the partial #405 retained-resource mitigation with atomic
  record-level changes, let `task_list`/`task_get` read a database snapshot without the
  process-global writer lock, and bind `task_create` to a client-reusable request key.
- **Baseline:** the historical `DELETE all → insert all → advance head` implementation [1][2]
  and current `main` (`8aed30c2`), where #405 retains resource payloads but still synchronously
  verifies their rows/FTS and rebuilds mutable rows under one `_RuntimeTaskStore._lock` [11].
- **Outcomes:** (a) the same isolated command measures `task_create` and a concurrently-entering
  `task_list` on a `Connection.backup` clone; (b) startup readiness is measured separately on the
  same projection, including preserved-receipt and cold-cache/cleared-receipt cases; (c) a
  30-second client deadline does not produce a second logical task when retried with the same key;
  (d) `canonical_head`, `projection_head`, shadow comparison, and projection debt expose every
  incomplete projection rather than claiming success.

## Hypotheses considered

### H1 — confirmed

The observed stalls are caused by the synchronous mutation path remaining inside a process-global
critical section. This would be wrong if a reader entering during the writer completed near its
idle latency. Source tracing of the incident revision shows two O(N) rebuilds on that path [2];
isolated measurement makes contended `task_list` last essentially as long as `task_create`, and
method instrumentation finds one call to each rebuild per create [3]. Their historical
contributions are unequal: `current.db` replacement took 13.239–16.098 seconds, while
`task-current.db` replacement took 0.095–0.241 seconds [3]. Current `main` no longer calls full
`replace_current()` for the measured task mutation, but still runs a synchronous O(N)
receipt/FTS/mutable-row refresh under the same lock: a cold-cache clone measured create/list
108.216/107.953 seconds and `_refresh_current_projection` 102.451 seconds [13].

### H2 — refuted

The symptom is general SQLite or machine-wide contention rather than the IA hot path. This would
be wrong if unrelated API calls remained fast and if an isolated clone reproduced the lockstep
latencies. The live stack and `/api/usage` control in [1], plus repeated isolated reproductions in
[3], refute H2 for this incident. SQLite lock behavior and host load remain implementation and
performance constraints: the same code crossed 30 seconds at loadavg 4.6–5.2 but stayed below it
at loadavg 1.1–1.4 [3].

### H3 — likely only with the explicit migration/degraded-state protocol below

An atomic record-level projection transaction can preserve integrity: upsert the changed ordinary
row, replace only its FTS row, then advance `projection_meta` in the same transaction; readers use
one read transaction and see either the old or new snapshot. This would be wrong if a partial row
change could advance the receipt, if unchanged rows had to be rewritten solely to change the
generation, or if readers still waited for the Python writer lock. Joined-current code already
separates the global projection receipt from row identity and compares semantic truth without head
fields [2]; SQLite defines read transactions as historic snapshots [5]. The task projection does
not yet have this global receipt and canonical JSON is rewritten file-by-file, so H3 depends on the
read-source/migration protocol in §6 rather than on merely removing the RLock. FTS5 is a virtual table, so the
ordinary-table UPSERT cannot be copied literally: SQLite documents that UPSERT does not work for
virtual tables [8].

### H4 — refuted for the required outcome

Moving the unchanged full rebuild or current retained-resource refresh out of
`_RuntimeTaskStore._lock` would be sufficient. Either can reduce reader queueing, but both leave
mutation work proportional to projection content and therefore fail mandatory property 1. #405
is direct counter-evidence that reducing rewritten bytes alone is valuable but incomplete: warm
create/list medians fell to 9.524/9.355 seconds, yet the cold-cache arm still reached
108.216/107.953 seconds [12][13]. An asynchronous full rebuild remains valid recovery tooling; it
is insufficient as the hot mutation path unless backed by a durable debt/outbox protocol.

### H5 — refuted

`transport_timeout: ReadTimeout` means the task was not created. This would be wrong if task rows
materialized after the timeout. The frozen live-log analysis finds a task for 16/17 timeouts under
the preregistered result-window rule; the missed known task materialized 131.593 seconds after the
logged call, and a clearly labelled exploratory five-minute attribution finds 17/17 [4]. The
higher-load isolated series independently finds `create > 30 s` in 3/3 runs; a lower-load repeat
finishes sooner and therefore limits this to “can exceed,” not “always exceeds,” 30 seconds [3].

### H6 — confirmed for the isolated mechanism; likely for the exact live-start attribution

The long service startup is the same projection refresh rather than an unrelated lifespan gate.
This would be wrong if a production-shaped cold-start clone spent little of startup inside
`_refresh_current_projection`, or if the real service did not show a cold/warm split. Clearing
resource receipts and advising the kernel to drop only the cloned `current.db` page cache produced
213.691 seconds of runtime startup, of which 205.054 seconds (96.0%) were one projection refresh;
the preserved-receipt three-run median was 8.616/1.698 seconds [12][13]. The production journal
contains starts lasting 179.711 and 299.018 seconds followed by an immediate 22.425-second start
on the same service/data [14]. The isolated attribution is direct instrumentation; mapping the
production totals specifically to this method also relies on the operator's live stack observation.

## Findings

### 1. The incident revision performed two full rewrites; current main still refreshes O(N) under the read lock

`_RuntimeTaskStore.task_create`, `task_update`, `task_update_if_current`, commit linking and startup
reconciliation all take the same `threading.RLock`; `task_get`, `task_list`, head properties and
`states()` take it too. Current `main` shows the lock at `runtime.py:121`, create at 159-164, list
at 184-189, and `_changed()` calling the head writer before release at 153-157 [11].

The candidate store first rewrites every canonical `state.json` and rebuilds every row of
`task-current.db`: `_write_states()` assigns the new global head to all states, writes all files,
then `_rebuild_projection()` deletes and reinserts the table (`app/ia/task_store.py:453-493`) [2].
The incident head writer then invoked `SQLiteProjectionBackend.replace_current()`, which deleted
both `current_fts` and `current_records`, inserted every record and finally advanced
`projection_meta` (`runtime.py:575-594,953-971`; `projections.py:152-203`) [2].

#405 changed that second half before the 2026-08-27 recheck: current `main` first calls
`seal_current_resources()`, then `replace_current_retaining_resources()`, and falls back to full
replacement only if both decline (`runtime.py:1020-1042`) [11]. The retained path nevertheless
enumerates stored resource rows, checks all resource FTS identities, deletes every non-resource
FTS/current row and reinserts every mutable row (`projections.py:381-431`) [11]. These operations
remain inside the same task-store lock through `_record_task_head()` (`runtime.py:613-632`) [11].

**Confidence: CONFIRMED** — the production stack [1], incident/current source [2][11], and old plus
current direct timings [3][12][13] independently identify the same serialized path (evidence
tiers 1 and 2).

### 2. Baseline on a frozen production-shaped projection can exceed the MCP deadline

The fixture was frozen only with Python `sqlite3.Connection.backup` from read-only URI sources.
Heads and counts were identical before, after and in the destination. The committed manifest [9]
records source sizes: `current.db` 172,314,624 bytes / 3,255 rows, `task-current.db` 2,293,760
bytes, and `orchestra.db` 763,842,560 bytes. SQLite documents the completed backup destination as
a source snapshot and explains why online backup avoids raw-file-copy/WAL problems [7].

This is not a cross-store atomic snapshot: the legacy DB, two projection DBs and canonical JSON
were captured sequentially. Equality before/after makes an intervening task generation unlikely,
but cannot exclude a change-and-return-to-the-same-head cycle. The fixture is therefore valid as a
performance corpus with recorded watermarks, not proof of cross-store crash consistency.

Each measured iteration cloned those frozen SQLite inputs with `Connection.backup`, ran current
`main` code in a fresh production-interpreter subprocess, retained startup legacy→canonical
reconciliation, disabled only the mutable live-Git evidence import, and started timers afterward.
The effective pre-timer projection was identical in all arms: 175,276,032 bytes, 3,258 current
rows, and 592 task states. Instrumentation sets an Event at entry to
`_RuntimeTaskStore.task_create` and wraps the two rebuild methods with `perf_counter`; it does not
delay or replace their production bodies [3]. A 30-second Timer records `future.done()` before any
database read, then attempts task visibility with SQLite `timeout=0`; `SQLITE_BUSY` is a first-class
observation rather than a wait. The final low-load series finished earlier, so its Timer correctly
reports no deadline observation and no deadline-visibility claim is drawn from it.

Command, to be repeated unchanged after implementation:

```bash
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python \
  docs/tasks/395/benchmark_tm.py run \
  --source data/task-395/frozen --iterations 3 \
  --project /home/kesha/orchestra
```

Two unchanged-code series demonstrate the host-load effect rather than hiding it:

| Series | loadavg-1m range | idle list median, s | create median, s | contended list median, s | >30 s |
|---|---:|---:|---:|---:|---:|
| higher load [3] | 4.632–5.210 | 0.444 | 32.661 | 32.353 | 3/3 |
| lower load, instrumented [3] | 1.129–1.377 | 0.418 | 21.738 | 21.519 | 0/3 |

Instrumented lower-load rows:

| Iteration | create, s | contended list, s | `current.db` rebuild, s | task projection rebuild, s |
|---:|---:|---:|---:|---:|
| 1 | 20.816 | 20.644 | 13.239 | 0.095 |
| 2 | 26.973 | 26.813 | 16.098 | 0.241 |
| 3 | 21.738 | 21.519 | 14.775 | 0.098 |

Each create called each rebuild exactly once. The task-count delta `+1` in these raw rows is read
after the contended list completes, not at the deadline; the field was renamed accordingly. The
deadline Timer is the only at-30-seconds measurement in the final harness.

Wall-clock load varied, so Phase 3 must retain the raw per-arm load averages and use the same
command; an interleaved old/new confirmation is preferable before attributing small differences.
At the time of this historical arm no post-change speedup had been measured; §2a records the later
#405 current-main recheck rather than projecting a gain from these numbers.

**Confidence: CONFIRMED for the historical slow/serialized baseline and component timings**, and
**REFUTED for “this fixed corpus always exceeds 30 seconds”** — two three-run series show the
threshold crossing changes with host load (evidence tier 1) [3]. Current-main results follow.

### 2a. Current main is faster warm, but still crosses the deadline and blocks startup when cold

Before the recheck, `main` gained #405's retained-resource/receipt path [11]. A new fixture was
frozen from the live legacy/task/current stores only via `Connection.backup`; heads and counts were
equal before, after and in the destination. It contains a 887,365,632-byte projection with 16,730
rows: 16,126 immutable resources and 604 task states; both resource receipts were present [15].

The same harness command, now also timing runtime entry and `_refresh_current_projection`, ran
three fresh clones with preserved receipts:

```bash
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python \
  docs/tasks/395/benchmark_tm.py run \
  --source data/task-395/frozen-current-20260827 --iterations 3 \
  --project /home/kesha/orchestra \
  --output docs/tasks/395/benchmark-main-8aed30c2-current-20260827.raw.jsonl
```

| Iteration | loadavg-1m startup→create end | startup, s | startup refresh, s | create, s | contended list, s | create refresh, s |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4.472→4.267 | 9.614 | 1.921 | 17.549 | 17.350 | 11.013 |
| 2 | 3.478→3.901 | 7.429 | 1.444 | 9.127 | 8.939 | 4.398 |
| 3 | 2.600→2.286 | 8.616 | 1.698 | 9.524 | 9.355 | 4.553 |
| median | — | **8.616** | **1.698** | **9.524** | **9.355** | **4.553** |

All three creates completed below 30 seconds, performed zero full `current.db` replacements and
added one task only on their private clone [12]. The concurrent reader still waited essentially
the entire writer interval; idle-list median was 1.249 seconds. Thus #405 materially reduced the
usual latency but did not remove reader serialization or size-dependent work.

Clearing only the two receipt fields while leaving the cloned pages warm produced startup/refresh
16.123/7.148 seconds, so receipt absence alone did not recreate the production minutes [13]. The
cold-start arm additionally used `POSIX_FADV_DONTNEED` only on its cloned `current.db`; it measured startup
213.691 seconds, with 205.054 seconds inside `seal_current_resources`; the following create took
108.216 seconds, its concurrent list 107.953 seconds, and its projection refresh 102.451 seconds.
At the preregistered 30-second observation the create future was incomplete while the legacy task
row already existed (`legacy_exact_title_count_at_deadline=1`) [13]. Full replacement remained
zero: the retained-resource path itself is sufficient to reproduce both the reader stall and
outcome-unknown boundary.

This cache arm is not a three-run latency distribution. It is a falsification/control showing
that current #405 code can still exceed the deadline without full replacement. It is corroborated
by production startup totals of 179.711 and 299.018 seconds followed by an immediate 22.425-second
restart [14], while the preserved-receipt three-run arm establishes the warm baseline [12].

**Confidence: CONFIRMED that current main still serializes reader behind writer and can exceed 30
seconds on the frozen live-sized corpus** — direct clone instrumentation plus exact at-deadline
state (tier 1) [13]. **LIKELY that cold projection pages explain the exact production-start spread**
— one controlled cache arm and the production cold/warm sequence agree, but page residency and
the whole live lifespan were not independently profiled on every start [13][14].

### 3. Real outcome-unknown creates usually outlive the client, and retry has no identity contract

A fresh 849,870,848-byte live database snapshot was taken with `Connection.backup`; only the
redacted aggregate/hashed artifact is committed [4]. Since 2026-08-25 it contains 17 exact
`mcp__orchestra__task_create` results whose content is `transport_timeout: ReadTimeout`, paired to
calls by `tool_use_id`. The preregistered rule finds exactly one created task before the logged
result for 16/17. The single miss is the already-known Seedon orphan: its unique exact-title task
appears 131.593 seconds after the logged call. The exploratory, explicitly non-preregistered
five-minute title-based attribution therefore gives 17/17, not a replacement for the 16/17 primary
count and not unambiguous task-level confirmation [4].

Two timeout calls in one project shared the same exact title hash and produced two distinct task
identity hashes. Their bodies/transport keys were not proven byte-identical, so this is evidence of
the operational duplicate-retry hazard, not proof that a same-key implementation failed [4].

The protocol gap itself is source-confirmed. `_api()` creates a new random `request_id` for every
call, sets `X-Request-ID`, and reports that id with `outcome_unknown=True` on a POST timeout
(`app/mcp_stdio.py:480-529`) [2]. But `task_create` exposes no reusable key argument
(`mcp_stdio.py:2435-2469`), the route does not read either `Idempotency-Key` or `X-Request-ID`
(`app/routes/tm.py:82-137`), and neither legacy nor canonical task creation accepts/persists a
request key (`app/tm.py:1000-1055,1529-1606`; `app/ia/task_store.py:738-832`) [2]. The client can
see an identifier in structured error metadata, but cannot reuse it or query its outcome.

**Confidence: CONFIRMED for the missing key contract and real outcome-unknown hazard** —
client/server source plus 17 real timeout results agree; **LIKELY for exploratory 17/17 task
attribution** because it is title/time based (evidence tiers 1 and 2) [2][3][4].

### 4. Integrity signals exist, but the hot path currently overclaims one receipt before work ends

The required safety mechanisms are live and must remain:

- shadow responses compare bounded legacy/canonical fields and expose `shadow_match` plus
  `projection_debt`; candidate failures persist `candidate_write_failed`
  (`app/tm.py:1427-1500`) [2];
- startup and `verify_gates()` reconcile legacy tasks into canonical state before parity checks
  (`app/ia/runtime.py:173-271,359-360,1430-1440`) [2];
- `TaskStore` rejects mixed canonical heads and checks projected payload/hash/head for `task_get`
  (`app/ia/task_store.py:424-451,546-560,647-653`) [2];
- current queries compare `projection_meta` to canonical head, validate semantic content, and fall
  back to canonical with debt if invalid (`app/ia/projections.py:412-533`) [2].

However, `_record_task_head()` still writes both runtime `canonical_head` and `projection_head` to
the new combined value before `_refresh_current_projection()` starts (`runtime.py:613-632`) [11]. If the
SQLite replacement fails, the database receipt remains old and query/verify paths can detect it,
but `runtime-state.json` has already claimed the new projection head. In addition,
`_query_projection()` still attempts another full rebuild synchronously on a stale read
(`projections.py:645-715`) [11]. A correct incremental design must advance the projection receipt
only in the same successful transaction as row/FTS changes, leave the prior receipt on failure,
persist debt, and never make an ordinary reader perform O(N) repair.

**Confidence: CONFIRMED** — direct control-flow and write order in current source (evidence tier 2)
[11]. Failure injection is deferred to Phase-2 RED tests.

### 5. Snapshot reads are feasible, but adding a new WAL database is not a safe shortcut here

SQLite supports simultaneous read transactions and specifies that an active reader continues to
see its historic snapshot while another connection changes the database [5]. WAL strengthens the
usual reader/writer concurrency guarantee [6], but the production interpreter reports SQLite
`3.45.1` (`libsqlite3-0 3.45.1-1ubuntu2.7`). SQLite's official WAL page, updated 2026-08-24, says
the WAL-reset corruption bug affects upstream 3.7.0 through 3.51.2 unless a backport is present
[6]. The installed Debian changelog contains no WAL-reset marker, but absence of that string does
not prove the binary lacks an unlabelled backport. `current.db` and
`task-current.db` currently use `journal_mode=delete`; the main Orchestra DB already uses WAL
(measured command in Sources).

Therefore Phase 2 should not make WAL a prerequisite for this fix. A short record-level
transaction in the existing projection mode, with readers outside the Python writer lock, is the
lower-expansion hypothesis to test. SQLite documents that COMMIT can still return `SQLITE_BUSY`
when another reader is open [5], so tests must cover old-or-new snapshot semantics and an explicit
failure/debt path; “remove the RLock” alone is not an integrity design.

**Confidence: CONFIRMED for the installed version; UNCERTAIN for its backport status; LIKELY for
the non-WAL design** — primary SQLite docs and production-interpreter measurement justify not
making WAL a new prerequisite, while binary patch status and the proposed transaction shape still
need independent evidence/tests [5][6].

## Recommended Phase-2 design boundary

This is a research conclusion, not an approved plan. #405's resource receipts, retained immutable
payloads and corrupt-cache recovery are now baseline functionality to preserve; the remaining
change narrows request-time work rather than restoring the removed full rewrite [11][12][13].

1. Keep `replace_current()` as explicit rebuild/migration tooling. Add a hot-path operation that
   validates unique record identity, changes only named ordinary rows and their named FTS rows,
   and advances `projection_meta` atomically from an expected old head to the new head. FTS uses
   targeted delete+insert, not UPSERT [8].

### Atomic task read source and migration

2. `task-current.db` becomes the **only request-time source** for candidate `task_list`/`task_get`
   when its global receipt is current. Add a singleton task-projection meta row. Migration seeds it
   only after one read transaction verifies that all existing rows have one non-empty head, that
   it equals canonical head, and that every payload digest/identity is valid. Missing/mixed/invalid
   input records blocking debt and requires explicit rebuild; it is never silently blessed.
3. Per-row `canonical_head` in unchanged payloads becomes the record's last materialized head, not
   the global freshness receipt. One read transaction reads meta + rows, validates row hashes, and
   overlays the global receipt in the facade response. The canonical generation formula and event
   history remain unchanged, but canonical JSON is not read lock-free while it is being rewritten.
4. `task_list`/`task_get` do not acquire `_RuntimeTaskStore._lock`. In healthy state they return one
   complete old/new SQLite snapshot. In degraded state generation 2/4 returns the already-read
   legacy result with `shadow_match=false` and explicit debt; generation 3 fails fast with a typed
   stale-projection response containing expected/observed heads. Neither path waits behind the
   writer, scans mixed canonical files, nor initiates rebuild.

### Ordered mutation and debt protocol

5. The canonical TaskStore writer remains serialized and first commits its event/state generation.
   A task-projection transaction then compares its meta head to the writer's expected parent,
   upserts only event-touched task rows, and advances meta. A joined-current transaction similarly
   compares the expected prior combined head, changes only explicitly supplied identities plus
   their FTS rows, and advances its own meta. A CAS mismatch or SQL error rolls back that projection
   transaction, leaves its old head, and persists blocking debt with expected/observed heads.
6. `runtime-state.canonical_head` advances after canonical commit;
   `runtime-state.projection_head` advances only after the joined-current transaction succeeds.
   Shadow comparison and reconciliation remain. Ordinary reads and application readiness never
   run O(N) repair synchronously; degraded startup exposes typed projection debt and schedules a
   bounded/background replay, while explicit offline replay may call full rebuild. A projection
   failure therefore cannot erase the active-owner task, claim equal heads, become a second create
   on retry, or keep every unrelated route unavailable for minutes.

### Request-key namespace, state machine and recovery

7. The HTTP key is `Idempotency-Key`; first-party MCP uses its generated 32-hex request id as the
   default and sends the same value in both `Idempotency-Key` and `X-Request-ID`. `task_create`
   accepts an optional prior key, so the identifier from structured timeout metadata is reusable.
   Scope is `(resolved project_id, key)`; keys are validated bounded ASCII (16–128 characters) and
   never used as paths.
8. The fingerprint is SHA-256 of canonical JSON after project/acceptance normalization and includes
   project id, title, price, description, assignee, status, priority, acceptance command, sorted
   acceptance manifest, required flag, and verified acceptance actor identity when present. It
   excludes generated timestamps/ids. Same key + different fingerprint is typed HTTP 409; same
   key + same fingerprint replays the stored task identity/response with `replayed=true`.
9. A durable coordinator row stores key, fingerprint, active owner/generation, state
   (`PENDING`, `ACTIVE_COMMITTED`, `MIRRORS_COMMITTED`, `FAILED`), stable/display identities,
   bounded response and error/debt. The unique row serializes same-key callers. `PENDING` before an
   active task exists returns typed in-progress plus `Retry-After`; `ACTIVE_COMMITTED` always returns
   the same task immediately even if shadow/projection catch-up is still running. A scoped
   `GET /api/tm/task-create-requests/{key}` and MCP status tool expose the same receipt.
10. In generation 2/4, legacy task insertion and `ACTIVE_COMMITTED` identity are one
    `BEGIN IMMEDIATE` transaction; canonical shadow uses the stored display number and a
    deterministic UUID/event derived from `(project_id,key)`. A candidate/projection crash leaves
    the active task/receipt intact; retry returns it and idempotently resumes missing mirrors.
    In generation 3, the coordinator is claimed `PENDING`, deterministic canonical creation is the
    active commit, then the coordinator records `ACTIVE_COMMITTED`; if a crash occurs between those
    steps, retry probes the deterministic canonical event + fingerprint and repairs the receipt.
    The legacy mirror uses the stored display identity rather than allocating another number.
11. Receipts/tombstones are retained for the task lifetime (no timeout TTL that could later reuse a
    key). Response replay is authorization-scoped to the resolved project/caller. Missing mirror or
    projection is visible as debt and never changes the active task identity.

## Other callers and scope

- The same mutation seam is used by task update, conditional lifecycle update, commit linking,
  startup/verification reconciliation and `TaskStore.apply_events`; a hot-path API that handles
  create only would leave adjacent stalls (`runtime.py:127-271`; `task_store.py:694-725`) [2].
- Knowledge promotion/import calls `_sync_knowledge_generation()`, which currently reaches the same
  current refresh without passing changed record identity (`runtime.py:1300-1302,613-632`) [11].
  Phase 2 must either carry that identity or explicitly retain a debt/rebuild path; it must not
  guess.
- Application lifespan enters `knowledge_runtime_mode()` before the remaining startup gates
  (`app/main.py:344-355`) [11]. Any synchronous projection scan there delays readiness for every
  route, not only TM; the isolated cold-start share was 205.054/213.691 seconds [13].
- `scripts/ia_replay.py` is an explicit full-rebuild consumer and should remain one.
- #370 (`send_message` outcome-unknown timeout) shares the receipt/idempotency pattern but no task
  storage code; it remains out of scope.

## Counter-evidence and unresolved edges

- The clone benchmark calls `app.tm` core functions rather than an HTTP server. It proves the
  serialized production hot path, while the separate live-log snapshot supplies actual MCP
  `ReadTimeout` evidence [3][4][12][13]. Its 30-second Timer models the unchanged MCP deadline but
  does not itself exercise HTTP transport.
- The preregistered live-outcome count is 16/17, not 17/17. The delayed task changes only the
  exploratory, title/time-based attribution and is kept separate to avoid moving the goalposts;
  it remains ambiguous rather than task-level confirmation [4].
- SQLite rollback-journal readers can still meet `SQLITE_BUSY` near COMMIT [5]. The acceptance
  oracle must distinguish a bounded explicit failure/fallback from a 30-second wait.
- The coordinator/read-source protocols above close the Phase-1 design holes, but exact DDL,
  response codes/body names and failure-injection RED oracles remain Phase-2 work. No production
  file has been changed in Phase 1.
- The performance fixture is sequentially frozen across stores, not cross-store atomic; it is not
  evidence for crash consistency. Its recorded stable heads/counts and clone-only mutations are
  sufficient for the latency corpus [7][9][15].
- Installed SQLite version is confirmed; absence of an unlabelled distribution backport is not.
  The design therefore avoids requiring new WAL rather than claiming the binary is vulnerable [6].
- #405 is a measured partial after-state, not the final Phase-3 implementation: its preserved-
  receipt median is below 30 seconds, but its cold-cache arm still exceeds the deadline and keeps
  list behind create [12][13]. Any future final comparison must retain these exact commands,
  per-iteration load averages and both preserved/cold-cache cases.
- `POSIX_FADV_DONTNEED` is advisory and the cold-cache result is one controlled iteration, not a
  latency percentile. It proves the current path can cross the deadline under that kernel cache
  condition; the production journal corroborates the cold/warm split but measures the entire
  lifespan, not method-exclusive time [13][14].

## Affected files and risks for a future plan

- `app/ia/projections.py`: record-level current/FTS update, receipt CAS, read-only fallback.
- `app/ia/task_store.py`: record-level task projection, snapshot reads, idempotent canonical create.
- `app/ia/runtime.py`: pass changed identities, separate canonical/projection receipt advancement,
  narrow writer serialization without weakening reconciliation/debt.
- `app/tm.py`: task-create request key through legacy/shadow/canonical paths; keep comparisons.
- `app/db.py`: durable legacy request-key mapping and migration.
- `app/routes/tm.py`: validate/forward request key and return it.
- `app/mcp_stdio.py`: reuse a caller-supplied key and tell the caller how to retry the same request.
- Targeted tests: task-store projection/integrity, TM route concurrency/idempotency, MCP error/key
  propagation. Full suite remains outside the owner's granted test-lock scope.

Highest risks are partial multi-store commit, a falsely advanced projection head, a lock-free read
of mixed canonical files, same-key/different-body aliasing, shadow replay creating a duplicate, and
an ordinary read accidentally triggering full repair.

## Review decision inputs

- **Changed Phase-1 artifacts/consumers:** `docs/tasks/395/{benchmark_tm.py,
  analyze_timeout_outcomes.py,fixture-*-manifest.json,benchmark-*.raw.jsonl,
  timeout-outcomes-*.raw.json,startup-journal-*.txt,research.md}` and one appended KB topic;
  consumers are the owner and the Phase-2 ticket author. No production code changed.
- **Author model/runtime:** `gpt-5.6-sol` on Codex runtime (session assignment for `fix-tm-hang`).
- **Exact Phase-1 acceptance:** enumerate all hot-path callers and integrity seams; provide a
  reproducible backup-only baseline; distinguish preregistered from exploratory timeout counts;
  propose a design that preserves distinct heads, shadow comparison and debt.
- **Named checks and observed output:** benchmark command above → higher-load median create 32.661
  seconds (3/3 over 30), final lower-load/instrumented median 21.738 seconds (0/3 over 30), one
  `current.db` rebuild per create at 13.239–16.098 seconds and one task projection rebuild at
  0.095–0.241 seconds. Current-main preserved-receipt command → startup/create/list medians
  8.616/9.524/9.355 seconds, zero full replacements; cold-cache command →
  213.691/108.216/107.953 seconds, create incomplete but task visible at 30 seconds.
  `python docs/tasks/395/analyze_timeout_outcomes.py ...` → 17 timeout calls, preregistered 16/17
  and ambiguous exploratory title/time 17/17; Python compile/redaction/JSON checks are green.
- **Risk floor:** concurrency, persistence/schema and externally consumed API contract are all
  high-risk. The canonical route would be Sol, but no auxiliary Sol review was authorized. One
  Luna falsification pass plus one evidence-backed final follow-up is therefore used under
  `codex-debate`; no Sol substitute is launched.

## Review outcome

- **Route/model:** Luna (`gpt-5.6-luna`), two prose rounds; the second is the ceiling.
- **Verdict:** `APPROVED for Phase-1 research` in `review-research.md` for the reviewed design
  boundary and original measurements.
- **Findings:** Round 1 had 3 blocking, 4 suggestions and 1 question. All three blocking findings
  were fixed by the explicit read-source/migration, cross-store coordinator and complete request-key
  protocols. Round 2 marked them fixed/nonblocking and left only Timer/lock-isolation residuals.
- **Evidence:** reviewer quoted the current artifact line: “A CAS mismatch or SQL error rolls back
  that projection transaction, leaves its old head, and persists blocking debt with
  expected/observed heads.” The generated reviewer prose also says “Codex reviewer unavailable,”
  but the artifact metadata, two completed background jobs and exact quote prove a Luna review did
  occur; that self-description is treated as reviewer error, not the route record.
- **Post-verdict suggestion:** accepted without a forbidden third round — Timer records before I/O,
  SQLite uses `timeout=0`, and `SQLITE_BUSY` is explicit. No result in this research relies on a
  Timer observation from a run that finished before 30 seconds.
- **2026-08-27 current-main addendum:** added after that verdict at the orchestrator's request and
  mechanically checked against raw JSON/journal lines. It did not consume a forbidden third prose
  round: `codex-debate` caps this research subject at the two rounds already recorded. The addendum
  changes the performance status of #405 from unmeasured to partial/incomplete; it does not change
  the reviewed projection receipt, degraded-state or request-key safety requirements.

## Sources

1. `docs/tasks/395/root-cause.md` — live stack, endpoint controls and original projection size
   (tier 1: direct production measurement).
2. Incident repository source at `main` merged as `3d72fe96`: files and line ranges cited inline
   (tier 2: primary source).
3. `docs/tasks/395/benchmark-3d72fe961b42-high-load.raw.jsonl`,
   `docs/tasks/395/benchmark-3d72fe961b42.raw.jsonl`, and
   `docs/tasks/395/benchmark_tm.py` — higher-load and lower-load method-instrumented series plus
   final harness (tier 1: six direct isolated measurements).
4. `docs/tasks/395/timeout-outcomes-20260826.raw.json` and
   `docs/tasks/395/analyze_timeout_outcomes.py` (tier 1: frozen live-DB analysis; sensitive labels
   are hashed, and preregistered/exploratory counts remain separate).
5. [SQLite Transaction documentation](https://www.sqlite.org/lang_transaction.html) — concurrent
   read transactions, snapshot semantics and `SQLITE_BUSY` limits (tier 2: primary source, opened
   2026-08-26).
6. [SQLite WAL documentation](https://www.sqlite.org/wal.html) — reader/writer concurrency and the
   2026 WAL-reset affected/fixed versions (tier 2: primary source, opened 2026-08-26).
7. [SQLite Online Backup API](https://www.sqlite.org/backup.html) — destination snapshot semantics
   and live-copy locking (tier 2: primary source, opened 2026-08-26).
8. [SQLite UPSERT documentation](https://www.sqlite.org/lang_upsert.html) — per-row conflict
   behavior and virtual-table limitation (tier 2: primary source, opened 2026-08-26).
9. `docs/tasks/395/fixture-manifest.json` — frozen source heads/counts/sizes and backup method
   (tier 1: direct measurement artifact).
10. Production runtime measurement, 2026-08-26:
    `/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python` reported Python 3.12.3,
    SQLite 3.45.1; `dpkg-query` reported `libsqlite3-0 3.45.1-1ubuntu2.7`; read-only PRAGMAs
    reported `current.db=delete`, `task-current.db=delete`, `orchestra.db=wal` (tier 1).
11. Current repository source at `main` `8aed30c2`, including #405 retained-resource commits:
    `app/ia/runtime.py`, `app/ia/projections.py`, and line ranges cited inline (tier 2: primary
    source, opened 2026-08-27).
12. `docs/tasks/395/benchmark-main-8aed30c2-current-20260827.raw.jsonl` — three preserved-receipt
    clone timings with startup/create/list/component durations and per-iteration loadavg (tier 1:
    direct isolated measurement).
13. `docs/tasks/395/benchmark-main-8aed30c2-cold-startup-20260827.raw.jsonl` and
    `docs/tasks/395/benchmark-main-8aed30c2-cold-cache-startup-20260827.raw.jsonl` — receipt-only
    control and cloned-file `POSIX_FADV_DONTNEED` falsification arm, including exact 30-second task
    visibility (tier 1: direct isolated measurements; cold-cache distribution n=1).
14. `docs/tasks/395/startup-journal-20260827.txt` — exact service start/readiness timestamps and
    elapsed totals (tier 1: production journal measurement; method share is not in the journal).
15. `docs/tasks/395/fixture-current-manifest.json` — fresh backup method, equal heads/counts,
    887,365,632-byte/16,730-row projection and resource receipt state (tier 1: direct snapshot
    manifest).

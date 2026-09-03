# #426 — убрать зависимость task-write latency от объёма knowledge storage

## Question

- **Context:** `task_create`/`task_update` write canonical task state, mirror legacy SQLite state,
  update the joined `current.db` projection, and compute a combined knowledge head over 47,834
  evidence records. The measured VPS has a 2.32 GB joined projection; the laptop has 20,948
  evidence records and a 704 MB projection without the symptom [1].
- **Change under test:** move joined-current projection application outside the HTTP response while
  retaining a durable, ordered proof of pending/application state; remove request-time evidence
  copies and whole-canonical-tree Git scans without changing the combined-head value.
- **Baseline:** the measured pre-#395 production path returned POST in 20.84 s and PUT in 19.60 /
  18.12 s, versus GET in 1.36 / 1.68 / 2.04 s [1]. Current source after #395 already replaces the
  measured full refresh with a targeted joined-current CAS when `changed_records` is present [2].
- **Outcome:** curl `time_total` for the same POST and PUT procedure must be recorded before/after;
  the response path must not enumerate evidence or open/update `current.db`; and a positive receipt
  must prove that committed task writes reach canonical task state, the legacy mirror, and the
  joined projection in order after concurrency and restart.

## Hypotheses considered

### H1 — the measured storage-size dependence is real, but #395 already removed part of it

**Hypothesis.** Pre-#395 latency grew with the evidence/current-projection corpus because
`_record_task_head()` performed three deep copies/hash inputs plus a full joined-current refresh;
#395 removed two copies and the full refresh for ordinary changed-record writes, but one O(E)
normalization/hash, `git add -A`, and the synchronous joined-projection transaction remain [1][2].

**Falsifier.** H1 is wrong if current post-#395 source still calls `_refresh_current_projection()`
for a normal non-empty `changed_records` write, or if it no longer calls `evidence_records()` /
`git add -A` / `update_current_records()` before returning. Current source shows the opposite:
the targeted branch is at `runtime.py:681-708`, evidence normalization at `:661-674`, and
whole-tree staging at `:778-788` [2].

### H2 — cached exact-head prefix + path-scoped Git commit + durable ordered outbox

**Hypothesis.** Request-time work can be independent of evidence/current.db size if startup builds
one immutable evidence hash prefix, task writes persist a small joined-projection outbox entry in
the same canonical Git commit as the task generation, and the existing lifespan-owned projection
task drains the outbox serially after the response. A linked `expected_head → target_head` chain
plus SQLite CAS prevents overtaking; the outbox file is deleted only after the projection receipt
equals its target [2][4].

**Falsifier.** H2 is wrong if the cached prefix changes the existing combined SHA, if a later entry
can apply before its parent, if restart after SQLite commit re-applies corruptly, or if response can
return before both the canonical task mutation and its outbox receipt are committed. The scratch
experiment preserved the exact hash for 0/2/1000 records, refused B-before-A, and replayed an
already-applied A receipt before reaching B [6]. Production tests must still prove these properties
on the real owners; the scratch state machine alone is not acceptance.

### H3 — optimize only copies/Git but keep projection synchronous

**Hypothesis.** One evidence snapshot plus path-scoped Git could reduce most latency without an
outbox.

**Falsifier.** The assignment requires the response not to wait for projection work. H3 leaves
`SQLiteProjectionBackend.update_current_records()` inside `_record_task_head()` and therefore
retains request latency coupled to `current.db` I/O [2][4]. **REFUTED by the required contract,**
even if it later benchmarks quickly.

### H4 — simply stop or fire-and-forget the projection call

**Hypothesis.** Removing/launching the projection update as an untracked task is enough.

**Falsifier.** A process exit after the HTTP response but before the update would leave no durable
work to resume; two concurrent writes could race one CAS or miss the only startup drain. Existing
`schedule_projection_repair()` starts only one task when startup debt is already set and has no
per-write durable wakeup (`runtime.py:1159-1168`) [2]. **REFUTED by source and the mandatory
no-loss condition.**

### H5 — persist only the latest desired head and rebuild the full projection later

This can coalesce writes, but it retains O(E) validation/rebuild work and needs a consistent
snapshot to prevent deleting work committed during the rebuild. It was not run against the 2.32 GB
store because the assignment forbids repeating the completed production measurement. **UNCERTAIN / not
selected:** it may be a recovery fallback, not the ordinary steady-state writer.

## Findings

### 1. The original production symptom is confirmed and consistent with corpus dependence

The supplied live measurement recorded GET at 1.36–2.04 s, POST at 20.84 s, PUT at 19.60 and
18.12 s, and 8/17 task creates whose client did not receive a response although all 17 committed.
Stage measurements on the 47,834-record corpus were 1.03 s per cached deep copy and 1.01 s for the
evidence head; `current.db` was 2.32 GB. The laptop counterexample had 20,948 evidence records and a
704 MB projection with no symptom [1].

The two corpus sizes plus direct O(E) stacks are consistent with volume dependence, but they are
not a post-#395 multi-size A/B that isolates a causal slope.

**Confidence: LIKELY for corpus dependence — direct large-store timings plus one smaller-store
counterexample; CONFIRMED only for the observed timings and O(E) code path.**

### 2. The supplied 20-second decomposition describes pre-#395 code, not the exact current branch

Current #395 source forwards non-empty `changed_records`; `_record_task_head()` then calls one
targeted `update_current_records()` and does not call `_refresh_current_projection()`
(`runtime.py:655-708`) [2]. The measured artifact names three evidence copies and a full refresh
[1], so its numbers remain the user-facing before baseline but cannot isolate the residual cost of
#426 after #395. No post-#395 production remeasurement was run in Phase 1, per instruction.

**Confidence: CONFIRMED — direct current source versus a timestamped measurement artifact (tiers 1
and 2).**

### 3. Current request latency still contains two corpus-wide operations and joined-projection I/O

For every changed task generation, current source deep-copies the evidence cache, normalizes and
sorts every record into `_bytes()`, stages the entire canonical repository with `git add -A`, then
opens `current.db` and runs the selected-row/FTS/head CAS before returning (`runtime.py:661-708,
778-788`; `projections.py:346-399`) [2][4]. #395 made the SQLite mutation O(changed rows), but it did
not move that mutation outside the response or remove O(E) head/Git work.

**Confidence: CONFIRMED — direct current source (tier 2), supported by the stage timings in [1].**

### 4. The safe projection boundary is a durable receipt before success, not a fictitious cross-store transaction

`TaskStore._commit_generation()` already writes a pending marker, event/state/current-head files,
and its own small task projection before it returns (`task_store.py:950-1008`) [3]. Canonical and
shadow API flows also perform the legacy task write before the HTTP response [5]. The joined
`current.db` projection is a derived read store whose update is already protected by an atomic
selected-row/FTS/head CAS (`projections.py:346-399`) [4]. The current call order is canonical/head
writer before the legacy mirror (`tm.py:2471-2668`) [5]; there is no atomic canonical+legacy
transaction. The architecture must distinguish three windows:

1. **before canonical/outbox commit:** no success response; TaskStore pending-generation recovery
   owns the partial canonical write;
2. **canonical/outbox committed, legacy missing:** no success response; create must resume from its
   `PENDING|ACTIVE_COMMITTED` idempotency receipt and mirror the deterministic canonical identity,
   while update needs an explicit durable reconciliation marker;
3. **canonical + legacy committed, response lost or projection pending:** retry returns the same
   task identity and the durable projection receipt remains drainable.

A successful response can therefore require both task owners plus an outbox even though their
commits are ordered rather than atomic. Phase 2 must freeze both pre-response crash windows;
operator-only `repair-shadow-drift` is not automatic recovery [5].

**Confidence: CONFIRMED for current ordering and absence of a cross-store transaction; LIKELY for
the proposed recovery protocol until failure injection (tier 2 source).**

### 5. An ordered per-generation outbox can prove no loss and no overtaking

Each receipt must contain its exact changed record payload, `expected_projection_head`, and
`target_canonical_head`. Task mutations are serialized by `_RuntimeTaskStore._lock` and create is
also protected by `_TASK_CREATE_LOCK` (`runtime.py:_RuntimeTaskStore`; `tm.py:32-35,2471-2605`)
[2][5], but serialization alone does not choose the correct parent when SQLite already lags. Enqueue
must set `expected_projection_head` from the **durable queue tail target**, falling back to persisted
runtime `projection_head` only when the queue is empty. Restart validates one fork-free, cycle-free
chain whose first expected head equals the SQLite receipt; malformed/missing-tail state records debt
and refuses targeted drain. The drainer may:

1. skip/delete an entry only when the SQLite receipt already equals its target (crash replay);
2. apply only when SQLite equals its expected head;
3. leave the entry and record debt on any other head/error;
4. advance runtime `projection_head` and delete/commit the receipt only after SQLite success.

Every `_commit_canonical()` call, including writer enqueue and drainer receipt deletion, must use
one process-wide canonical-Git lock. `_RuntimeTaskStore._lock` serializes task mutations but does
not protect the Git index from a concurrent cleanup commit. Cleanup uses an outbox-only pathspec;
task commits use task+outbox pathspecs, so neither stages the 47,834 evidence files.

The scratch experiment returned:

```text
HEAD_PREFIX_EQUAL [True, True, True]
ORDERED_FINAL ('B', [], 0)
OUT_OF_ORDER_REFUSED ('P', [{'expected': 'A', 'target': 'B'}, {'expected': 'P', 'target': 'A'}], 1)
CRASH_REPLAY_FINAL ('B', [], 0)
```

The scratch model does **not** prove filesystem/Git atomicity. Phase-2 tests must inject: crash after
task files before outbox commit; Git commit failure; malformed/partial/stale receipt; SQLite success
before receipt deletion; and concurrent enqueue during cleanup.

There is also a gap after `TaskStore._commit_generation()` has deleted its pending marker and before
`_record_task_head()` has committed an outbox entry. Recovery owner: startup
`_sync_knowledge_generation()` compares durable TaskStore head, runtime combined head, queue tail and
SQLite receipt before readiness; any unmatched canonical generation synthesizes a recovery entry
from current canonical task states (full-repair marker when exact changed payload is unavailable).
It may not declare the queue empty merely because no outbox file exists.

**Confidence: LIKELY — the CAS primitive is production code (tier 2) and the state-machine proof is
direct but synthetic (tier 1 scratch); the load-bearing filesystem/Git windows remain open until
Phase-2 RED oracles.**

### 6. The existing one-shot repair owner is insufficient for a steady-state outbox

`schedule_projection_repair()` returns no task when startup repair debt is false, and once it owns
a task it has no wakeup path for later writes (`runtime.py:1159-1168`) [2]. `app.main.lifespan()`
already owns and cancels the returned task, so its interface can remain the lifecycle seam, but the
runtime implementation must become a long-lived wakeable drainer that checks a durable outbox at
startup and after every enqueue [2]. Every enqueue path and the single drain path must be enumerated
in the Phase-2 delivery test; an in-memory event is a wakeup optimization, not the receipt.

**Confidence: CONFIRMED — direct current source plus the queue-lifecycle counterexample recorded in
project memory [7].**

### 7. Exact combined-head compatibility can avoid request-time evidence serialization

Because `_bytes()` sorts object keys, the existing JSON hash begins with the immutable serialized
evidence field and ends with the dynamic knowledge/task heads. A startup-cached `hashlib` prefix can
be copied and extended per task write, preserving the exact SHA rather than migrating the head
formula. The scratch experiment proved equality on three corpus sizes [6]. Evidence import already
invalidates `_evidence_records_cache` before startup import (`runtime.py:_import_scope_evidence`),
and repository search finds `_import_scope_evidence()` called only during runtime initialization
[2]. The invariant must be explicit: construct the prefix only after import; evidence is immutable
for the serving lifetime; any future live-import path invalidates/rebuilds the prefix under the
canonical-Git lock. Phase 2 needs an invalidation oracle, not only head equality.

**Confidence: LIKELY — exact synthetic equality is measured; production invalidation and old/new
head equality require a committed oracle.**

## Architecture alternatives for approval

### A — recommended for discussion: exact-head cache + canonical outbox + ordered targeted drainer

- Request waits for canonical TaskStore generation, legacy mirror, one small outbox JSON write, and
  a path-scoped Git commit limited to `tasks/` plus the outbox; it does not enumerate evidence or
  touch `current.db`.
- The outbox lives under the canonical Git owner and all enqueue/delete commits share one Git lock.
  Returning success requires canonical task/outbox plus the legacy mirror; restart scans pending
  receipts before waiting for new work.
- A long-lived runtime task applies the existing atomic targeted CAS in chain order. Adjacent entries
  may coalesce into one CAS using the first expected head, last target head and latest payload per
  record. A full latest snapshot rebuild remains recovery-only when the chain cannot start.
- Pre-response canonical/legacy crash windows are explicitly classified and never mislabeled as an
  atomic transaction; automatic reconciliation is included only if the broad scope is approved.
- Cost: durable state machine, canonical-Git lock, wakeup/lifecycle logic, mirror recovery,
  crash-replay and ordering tests.

This recommendation is conditional on the **bounded scope** below. Broadening it to automatic
cross-store reconciliation in every ownership mode is a separate architecture choice.

### B — smaller but non-compliant: exact-head cache + path-scoped Git + synchronous CAS

- Cost and regression risk are lower.
- It still couples response time to `current.db` and fails the explicit asynchronous-projection AC.

### C — coalesced latest-head full rebuild

- The receipt is simpler and many writes can collapse into one rebuild.
- It retains size-dependent 2.32 GB work and needs a snapshot/generation protocol to avoid clearing
  concurrent work. Any finite drainer can backlog under unbounded arrivals; the relevant difference
  is service cost per batch: A is O(changed rows) and can coalesce, while C is O(full corpus) per
  snapshot. Keep C as the simpler recovery fallback, not the steady-state writer.

## Architecture decision required before planning

The review exposed a scope choice that source alone cannot decide:

1. **Bounded #426 (recommended):** guarantee that every **successful live canonical-mode**
   POST/PUT has canonical task state, legacy mirror state and a durable joined-projection receipt;
   the receipt applies after response and survives restart/concurrency. Pre-response canonical↔legacy
   crash gaps and shadow-mode candidate debt retain their existing semantics and are explicitly not
   called atomic or fixed by #426.
2. **Broad cross-store recovery:** add a generic mutation identity/state machine for create and
   update in both canonical-before-legacy and shadow legacy-before-canonical modes, so every
   pre-response crash is automatically reconciled as well. This is materially more code and changes
   existing shadow behavior that currently returns active-owner success with candidate debt.

Both satisfy the ordinary successful-response timing measurement only if projection/evidence work
is deferred. Option 2 adds guarantees beyond the stated moved-work condition; it must be approved
explicitly rather than smuggled into implementation.

## Counter-evidence and risks

- The 20.84/19.60/18.12 s baseline predates #395's targeted joined-projection update. An after value
  proves the combined deployed result, not the isolated contribution of #426 [1][2].
- Queue emptiness is not proof: it is also true when enqueue never ran. Acceptance must first assert
  a non-empty durable receipt, then the positive SQLite target head/payload, then receipt removal [7].
- An asyncio task or thread alone is not durable. Restart recovery must work with no surviving
  in-memory event/task.
- `_RuntimeTaskStore._lock` is not a Git-index lock. Without a separate canonical-Git lock,
  background receipt cleanup can race task/evidence commits even when task writes are serialized.
- Current canonical create/update commits canonical before legacy. A durable projection outbox does
  not create cross-store atomicity; under the bounded option, no success response is claimed for the
  missing-legacy window. The broad option would require `PENDING|ACTIVE_COMMITTED` reconciliation.
- Shadow mode has the reverse order (legacy first, canonical second) and intentionally returns a
  legacy success plus debt when the candidate fails. #426 cannot truthfully promise automatic
  both-store crash recovery for shadow without changing that contract.
- Deleting an outbox entry before observing the SQLite target loses work; deleting only after a CAS
  error can also hide an unrelated head. Both directions need mutation tests.
- Background full repair currently calls the protected evidence accessor multiple times and does
  not itself close steady-state per-write receipts. It must receive one internal snapshot per pass
  and remain recovery-only [2].
- `main` is one excluded-file commit ahead of the branch (`8ceff6c7`), but `git diff HEAD..main` is
  empty for every #426-owned file; no researched source is stale relative to current main.

## Affected files and Phase-2 oracle seams

- `app/ia/runtime.py`: exact head-prefix cache; durable outbox enqueue; long-lived ordered drainer;
  process-wide canonical-Git lock; path-scoped commits; single evidence snapshot for recovery.
- `app/main.py`: likely no behavior change beyond the existing lifecycle owner; tests must prove
  shutdown/startup delivery if the returned repair task becomes long-lived.
- `app/tm.py`: bounded option needs no ownership-order change; broad option must treat
  `ACTIVE_COMMITTED` as mirror-pending and add durable update/shadow reconciliation. Routes change
  only if the pending/apply receipt is exposed in HTTP status.
- `tests/`: end-to-end request-return-before-projection, positive enqueue/apply proof, two-write
  ordering, crash after enqueue, crash after SQLite-before-delete, exact head compatibility, and
  mutation that removes the drainer while leaving enqueue intact; Git enqueue/delete races, Git
  failure, malformed receipts, evidence-prefix invalidation, and canonical-before-legacy crash.
- `docs/tasks/426/`: frozen curl command/body and before/after timings. A live after measurement
  requires merged code plus restart; a worktree server would use production credentials and is not a
  lawful substitute.

## Review gate inputs

- **Changed research artifacts/consumers:** this document and the scratch experiment; consumed by
  the Phase-2 architecture decision and ticket/oracle design.
- **Author metadata:** `gpt-5.6-sol`, Codex full-cycle runtime (live session metadata).
- **Exact AC:** remove request-time evidence/current.db dependence; durable ordered eventual apply;
  curl POST/PUT timings; both canonical and legacy task stores plus joined projection verified.
- **Mechanical check:** `.venv/bin/python docs/tasks/426/experiment-head-outbox.py` → RC 0 and the
  four exact output lines in [6].

## Review outcome

Luna round 1 returned `Needs work`: it identified the missing canonical-Git lock, the false
cross-store atomicity implication, insufficient crash modeling, overstated corpus causality,
evidence-prefix invalidation and the full-rebuild comparison. All six were verified against source
and incorporated. Round 2 marked those items fixed except cross-store update recovery, then found
the post-generation/pre-outbox gap, missing durable queue-tail parent, and unaddressed shadow-mode
ordering. This revision assigns startup synthesis to the first gap, defines the persisted tail-chain
invariant for the second, and exposes bounded-versus-broad cross-store recovery as an architecture
decision rather than silently choosing it.

The prose review ceiling is two rounds, so there is no third model pass. The first-round dissent and
second-round open finding remain verbatim in `docs/tasks/426/review-research-luna.md`; the scope
choice is escalated at the Phase-1 gate.

## Sources

1. `docs/tasks/426/finding-task-write-latency.md` — production curl, stack and stage measurements;
   evidence/current.db corpus comparison.
2. `app/ia/runtime.py:113-205,655-708,778-788,940-946,1067-1209,1477-1480` — task facade,
   combined head, Git owner, evidence copies and repair lifecycle.
3. `app/ia/task_store.py:950-1008` — canonical pending/event/state/head/task-projection commit order.
4. `app/ia/projections.py:346-399` — atomic selected current-row/FTS/head CAS.
5. `app/tm.py:32-35,2427-2635` and `app/routes/tm.py` — write serialization, canonical/shadow
   ownership and response boundary.
6. `docs/tasks/426/experiment-head-outbox.py` and `experiment-head-outbox-output.txt` — exact-head
   and ordered/crash-replay scratch proof.
7. `docs/kb/evidence-methods.md:37,50,67` — at-least-once side effects, positive completion and
   queue lifecycle/drain evidence.

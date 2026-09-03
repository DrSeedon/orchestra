# #315 — state machines and recovery

These are implementation contracts for the next phase. They separate canonical Git events, SQLite
current projections and asynchronous FTS/vector work.

## Common event envelope

<pre>
event_id, event_type, stable_id, project_id, actor/session/task,
expected_head, canonical_head, occurred_at, payload_sha256, idempotency_key
</pre>

Every transition records old and new head. Replaying the same idempotency key is a no-op; replaying a
different payload against the same expected head is a conflict, not last-write-wins.

## Record lifecycle

<pre>
CREATE_REQUEST
  -> VALIDATED (schema, stable_id, scope, privacy, evidence refs)
  -> CANONICAL_COMMIT
  -> SQLITE_PROJECTED
  -> FTS_QUEUED
  -> VECTOR_QUEUED
</pre>

Failure before <code>CANONICAL_COMMIT</code> leaves no record. Failure after it leaves canonical truth
and visible projection debt. <code>SQLITE_PROJECTED</code> is required for current-state
read-after-write; FTS/vector may lag.

## Update / same-record conflict

<pre>
READ_HEAD
  -> CAS(expected_head)
      -> COMMIT_UPDATE -> project
      -> CONFLICT
          -> identical payload: IDENTITY_NOOP
          -> explicit supersedes: append supersede event -> new current
          -> explicit disputed: append disputed event -> both visible
          -> otherwise REJECT
</pre>

No update may overwrite an existing fact with only similarity, timestamp or caller preference.

## Merge and task/evidence linkage

<pre>
worker branch pinned
  -> identity/dirty/child/conflict guards
  -> merge target commit
  -> task link event(s)
  -> evidence manifest/blob refs
  -> task current projection
  -> RAG backfill queue
  -> next task quarantine/switch
</pre>

The Git target commit is the canonical boundary. If task-link or next-task persistence fails after the
target commit, the merge operation is <code>PARTIAL</code> with explicit link/projection debt; it must
not pretend the Git commit did not happen. Existing <code>app/merge_operations.py</code> already
distinguishes secondary RAG/next-task failures from target commit state. The future task/evidence event
must preserve that boundary.

## Delete and restore

<pre>
DELETE_REQUEST
  -> RETENTION/AUTHORIZATION_CHECK
  -> TOMBSTONE_COMMIT
  -> ACTIVE_PROJECTION_REMOVED
  -> FTS/VECTOR_DELETE_QUEUED

RESTORE_REQUEST
  -> MANIFEST/CHECKSUM/SCOPE/SCHEMA_VALIDATE
  -> conflict=fail | skip | explicit merge-upsert
  -> CANONICAL_RESTORE_COMMIT
  -> projection replay
</pre>

Restore never silently reuses a stable ID with different content. Tombstone versus legal purge is
explicitly different; private history policy remains a product/legal decision.

## Research finding promotion

<pre>
TASK_EVIDENCE_EXISTS
  -> TOPIC_RESOLVE (0=fail, 1=continue, >1=fail)
  -> ATOMIC_CLAIM + fact_key + valid-time
  -> PROVENANCE_VALIDATE (task/path/anchor/head/blob)
  -> SAME_KEY_CHECK
      -> identical: NOOP
      -> no current: CURRENT
      -> explicit supersedes: OLD -> SUPERSEDED, NEW -> CURRENT
      -> disagreement: DISPUTED
      -> missing proof: REJECTED_WRITE
  -> canonical topic/event commit
</pre>

<code>rejected</code> means the claim/approach is retained as a queryable negative finding;
<code>superseded</code> means a newer supported claim replaced current status; <code>as_of</code>
selects by valid-time interval. <code>refresh_after</code> only marks
<code>STALE_NEEDS_VALIDATION</code> and never deletes/history-flips a fact.

## Canonical → SQLite → FTS/vector

<pre>
Git merge generation target_head
       |
       +--> synchronous deterministic fold --> projection_head=target_head
       |                                      current/FTS rows available
       |
       +--> asynchronous file/log/vector queue --> indexed_head
                                              pending debt visible
</pre>

If <code>projection_head != canonical_head</code>, current query returns a receipt and direct
canonical fallback for changed URI. If only <code>indexed_head</code> lags, exact/current typed query
uses SQLite and reports cold index debt. Vector failure is retriable and cannot erase canonical content.

## Stale-head fallback

<pre>
query
  -> read heads
  -> all equal: projection result
  -> SQLite behind: canonical parse of affected URI + debt receipt
  -> vector behind only: SQLite result + index debt receipt
  -> canonical unavailable: fail closed with head/error, never "not found"
</pre>

Fallback must be tested in the production-shaped scope path, not a detached standalone parser.

## Two-contour synchronization

<pre>
contour A/B local event
  -> stable UUID + project lease for #N
  -> push/pull Git
  -> merge conflict or append disjoint record
  -> replay events against new head
  -> same-key CAS: no-op / supersedes / disputed / reject
</pre>

An offline contour can allocate a display-number lease gap; it cannot allocate an already-issued stable
ID. If a user requires contiguous global #N, a central allocator is required and this design must stop
at the decision gate (#299 gap).

## Session commit

<pre>
TURN_MESSAGES
  -> COMMIT_REQUEST
  -> sync immutable archive + clear live buffer + return commit_id
  -> background promotion candidate extraction
      -> explicit evidence/provenance validation
      -> promote or retain session-only
  -> task status completed/failed/retryable
</pre>

The session archive is canonical cold history, not a current fact. Background extraction failure leaves
the archive intact and a visible failed task; it does not lose the paid session output.

## Pack backup/restore

<pre>
FREEZE_WRITES (strict mode)
  -> backup canonical bodies + manifest + checksums + head map
  -> validate replay on empty/isolated target
  -> restore content
  -> rebuild SQLite/FTS/vector
  -> compare manifest, identity, fact status and heads
  -> resume writes
</pre>

OpenViking OVPack provides useful manifest/scope/checksum semantics, but its official docs state backup
is live/non-atomic and its official issue #3875 reports a documented restore-overwrite failure.
Orchestra must therefore freeze writes for strict snapshots and rehearse restore; pack is not an
acceptance oracle.

## Schema migration and rollback

<pre>
MIGRATION_PRECHECK
  -> immutable SQLite backup + Git HEAD + manifest
  -> shadow import / dual-read comparison
  -> projection replay
  -> task facade parity + fact holdout
  -> CUTOVER
      -> rollback before canonical writes: switch reader/projection generation
      -> rollback after canonical writes: restore/replay forward canonical events,
         then rebuild projections (never delete history by reset)
</pre>

Migration schema versions are monotone. A failed projection migration may drop/rebuild only derived
indexes. Canonical Git/events and immutable evidence are never rolled back by deleting newer commits;
rollback is a forward restore or reader switch with an audit event.

## State-machine acceptance observations

- create/update/merge/delete/restore expose stable ID, head and event receipt;
- same-record conflict preserves both payloads when disputed;
- rejected/superseded/as-of queries do not collapse into current;
- a missing current projection produces canonical fallback;
- vector/FTS failure retains task/fact result and visible debt;
- two contours do not lose either disjoint event;
- session commit preserves archive on extraction failure;
- pack restore rejects checksum/scope/schema mismatch before any write;
- rollback leaves replayable canonical history and projection parity.

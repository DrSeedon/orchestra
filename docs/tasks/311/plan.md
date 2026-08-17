# #311 — Durable `spawn_worker` initial-task delivery

Phase: 2 — plan and immutable RED oracles
Research: `docs/tasks/311/research.md`
RED freeze: `327242a7432ef7b325cb7c4de38244479bcc1cab`

The earlier freezes (`b4ccc7f0753f25ca01885653101a7918c4b2330d`,
`176fb03757781a2086fb9c8a42c31c9270a269df`,
`b79d17342556bfbdd4807ba7470c7e8e3caa7563`, and
`c04a121a3ec5d4c672117966ee4d0d28285c0ad0`) are superseded and excluded from Phase 3 replay.
Round-one review found missing history, cancellation, error-classification, and canonical retry-body
coverage; the final pre-review audit then added the HTTP rollback envelope and startup wiring
oracles. The immutable executor baseline is the later freeze above.

## Goal

Make initial-task delivery a durable, caller-keyed asynchronous resource. The acceptance request
must commit before runtime wake and return promptly; same-key retries must be insert-or-read; status
must reconcile a lost response; recovery may replay only states that prove `backend.send` has not
begun. This task does **not** promise strict provider exactly-once across the external acceptance
window.

## Scope and non-goals

In scope:

- the initial task sent by `spawn_worker` after session creation;
- SQLite persistence, HTTP accept/status endpoints, a runner/recovery state machine;
- one narrow manager/session entry that preserves serialization and auto-switch;
- MCP delivery id generation, status/retry tools, timeout reconciliation, and structured actions;
- startup recovery before new traffic is admitted to stale delivery state.

Not in scope:

- changing ordinary `/api/sessions/{name}/send`, Telegram, fan barriers, mailbox, restart inbox,
  pending-message batching, merge operations, or quota routing;
- increasing the 30-second client timeout;
- replaying a delivery after `backend.send` may have been accepted;
- provider-side idempotency that current backends do not expose;
- importing or rebasing onto the pending #305 branch.

## Protocol contract

### Identity and fingerprint

`delivery_id` is a UUID created by the MCP caller before the delivery POST. The canonical payload
fingerprint is SHA-256 of sorted, compact UTF-8 JSON with schema version and these exact logical
fields:

```text
schema_version, session_id, worker_name, scope, sender, message
```

The database primary key is `delivery_id`. Same id + same fingerprint returns the existing resource;
same id + another fingerprint returns HTTP 409 with `IDEMPOTENCY_CONFLICT`. The hash never depends
on timestamps, row ids, state, or provider metadata.

### Durable states

```text
                 accepted transaction
ABSENT  -------------------------------------->  QUEUED
                                                     |
                  atomic user-log + state            v
                                                PREPARING
                                                     |
                  fail-closed immediately            v
                  before backend.send           DISPATCHING
                                                  /       \
                        backend.send returned   v         v crash/error/unknown
                                           SUBMITTED   DELIVERY_UNKNOWN
```

`QUEUED` and `PREPARING` are the only replayable, proven-pre-submit states. `SUBMITTED` is terminal
for this delivery protocol: #311 records acceptance by `BackendLike.send`, not later model-turn
completion. Failure of the original acceptance transaction is not a state: it leaves no row, no
user log, and no wake.

State invariants:

1. `QUEUED` is committed before `ensure_delivery_runner(delivery_id)` is called.
2. `PREPARING` and its one immutable `logs.type='user_message'` row commit in the same SQLite
   transaction; `initial_deliveries.user_log_id` is non-null and unique in `PREPARING` and later.
3. A recovered `PREPARING` row reuses `user_log_id`; it never appends the message again.
4. `DISPATCHING` commits synchronously and fail-closed immediately before `backend.send`.
5. `SUBMITTED` means `BackendLike.send` returned successfully. A native turn/thread id is optional
   `provider_ref`, not a portable requirement.
6. Startup converts orphan `DISPATCHING` to `DELIVERY_UNKNOWN` and never schedules it. It leaves
   `SUBMITTED` and `DELIVERY_UNKNOWN` unscheduled.
7. Startup requeues/reclaims only `QUEUED` and `PREPARING`; in-process `_runner_tasks` prevents two
   local runners for one id.
8. Any `Exception` or `asyncio.CancelledError` after the `DISPATCHING` commit becomes
   `DELIVERY_UNKNOWN`. `run_initial_delivery` is the final owner of that transition and re-raises
   cancellation only after the synchronous unknown-state commit. There is no blind replay.

### Stored resource and response

`app/db.py:init_db` creates `initial_deliveries` with:

```text
delivery_id TEXT PRIMARY KEY
schema_version INTEGER NOT NULL
session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE
worker_name TEXT NOT NULL
scope TEXT NOT NULL
sender TEXT NOT NULL
message TEXT NOT NULL
payload_hash TEXT NOT NULL
state TEXT NOT NULL
user_log_id INTEGER UNIQUE REFERENCES logs(id)
provider_ref TEXT
error_json TEXT
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
```

Add an index on `(scope, state, created_at)`. No column is added to immutable `logs`; the delivery
row owns the unique relationship to the log inserted in the same transaction.

The stable resource representation uses these keys:

```json
{
  "ok": true,
  "delivery_id": "<uuid>",
  "delivery_state": "QUEUED|PREPARING|DISPATCHING|SUBMITTED|DELIVERY_UNKNOWN",
  "payload_hash": "<sha256>",
  "status_url": "/api/initial-deliveries/<uuid>",
  "provider_ref": null,
  "error": null,
  "next_action": null
}
```

`provider_ref`, `error`, and `next_action` may be omitted only where the existing project serializer
already omits nulls; the tests compare the required subset except for the exact T3 action envelopes.
`get_initial_delivery` derives `next_action` from state rather than storing it:

| State | `next_action` |
|---|---|
| `QUEUED` / `PREPARING` | `WAIT_FOR_DELIVERY`, `tool=delivery_status`, same `delivery_id` |
| `DISPATCHING` / `DELIVERY_UNKNOWN` | `CHECK_DELIVERY_STATUS`, `tool=delivery_status`, same id, explicit do-not-resend wording |
| `SUBMITTED` | `null` (accepted by the backend; no protocol action remains) |

## Implementation map

### `app/initial_deliveries.py` (new, single owner)

Own:

- UUID validation and `payload_hash` construction;
- `accept_initial_delivery(...) -> (resource, status_code)`;
- `get_initial_delivery(delivery_id, scope)`;
- atomic `prepare_initial_delivery(delivery_id)` (QUEUED plus log insert, or recovered PREPARING
  reuse);
- `mark_initial_delivery_dispatching`, `mark_initial_delivery_submitted`, and the idempotent
  unknown transition;
- `InitialDeliveryContext.before_submit/mark_submitted/mark_unknown` used at the session seam;
- `run_initial_delivery(delivery_id, manager=...)`;
- `_runner_tasks` and `ensure_delivery_runner`;
- `recover_initial_deliveries`, which requeues safe pre-submit work and quarantines ambiguity.

Use the established `merge_operations` pattern for `BEGIN IMMEDIATE`, insert-or-read, one runner,
and startup reconstruction. Do not reuse `mailbox`/`restart_inbox`: their at-least-once contract is
incompatible.

### `app/routes/sessions.py`

Add `InitialDeliveryRequest` and two routes:

```text
POST /api/sessions/{name}/initial-deliveries
GET  /api/initial-deliveries/{delivery_id}?scope=<scope>
```

POST resolves the existing session without waking it, verifies name/scope, calls
`accept_initial_delivery`, and returns 202 only after commit. It never awaits a runner. GET is
read-only and scope-bound. A failed insert cannot schedule a runner. After the server observes that
the acceptance transaction rolled back, the route maps it to a loud HTTP 503 envelope with
`code=DELIVERY_ACCEPT_REJECTED`, `outcome_unknown=false`, `retryable=true`,
`details.commit_state=NOT_COMMITTED`, and no resource; this code is emitted only after verifying the
row was not committed.

### `app/manager.py` — exact #305 overlap

Add only this narrow sibling to `SessionManager.send`:

```python
async def send_initial_delivery(
    self, session_id: str, message: str, *, delivery,
) -> None
```

Its body preserves the existing `get_session_lock(session_id)` and
`_auto_switch_before_delivery(session)` order, then calls
`session.send(message, delivery=delivery)`. Do not edit `_auto_switch_before_delivery`, ordinary
`send`, create-session logic, or manager recovery. Like `send`, it owns the `deliver()` task through
`_wait_owned_task`, then calls `delivery_task.result()` so cancellation and failures remain loud.

This sibling beside `SessionManager.send` is the exact overlap with pending #305. Immediately before
T2, inspect `git show main:app/manager.py` and `git log main -- app/manager.py`. If #305 has landed in
`main`, preserve its landed `send` body byte-for-byte and insert this sibling against that current
body; if it has not landed, use the current body in this branch. Do not fetch, cherry-pick, inspect,
or import the unmerged #305 branch. Record any mechanical hunk reconciliation in `report.md`.

### `app/session.py`

Extend only the idle-turn path:

```python
async def send(self, message: str, *, delivery=None) -> None
```

For `delivery is not None`:

- do not call `_log("user_message", message)` because preparation already committed it;
- keep `original_user_message` and `exclude_history_users=(original_user_message,)`, so reconstructed
  history excludes the one persisted current input and the backend sees it once as current prompt;
- after backend preparation and immediately before `backend.send`, await
  `delivery.before_submit()`; if this persistence fails, do not call the backend;
- after successful return, call `delivery.mark_submitted(provider_ref)` where `provider_ref` is
  `backend.active_turn_id` when it is a non-empty string, otherwise `None`;
- after a post-`before_submit` `Exception` or `asyncio.CancelledError`, call the idempotent
  `delivery.mark_unknown(error)` before retaining the current loud failure/cancellation behavior.
  `run_initial_delivery` catches `asyncio.CancelledError` as the outer safety owner, commits
  `DELIVERY_UNKNOWN` synchronously if the context reached `DISPATCHING`, then re-raises. Thus a
  cancelled task cannot strand a live-process row in `DISPATCHING`.

Ordinary sends, running-turn injection, compaction, quota-shadow observation, facts, and pending
messages remain byte-for-byte behaviorally unchanged.

### `app/main.py`

Call `recover_initial_deliveries()` immediately after `await manager.auto_resume_all()` and before
`await manager.sweep_orphan_fds()`. This exact insertion is consequently before both
`manager.start_background_tasks()` and `schedule_restart_inbox_drain()`. Recovery schedules only
safe states and marks orphan `DISPATCHING` unknown before any background delivery source can rely on
stale state.

### `app/mcp_stdio.py`

- add optional `delivery_id: str = ""` to `spawn_worker`; blank generates `uuid.uuid4()` before the
  delivery POST;
- replace `/send` with `/initial-deliveries`, retaining sender, scope, worker mapping, and existing
  creation failure behavior;
- success text says “Task accepted”, includes delivery id/state/status, and does not claim the model
  turn completed;
- add MCP tools `delivery_status(delivery_id)` and
  `retry_initial_delivery(name, task, delivery_id)`. The retry tool posts the exact same logical
  body `{"delivery_id": delivery_id, "message": task, "scope": SCOPE,
  "sender": WORKER_NAME}` and therefore receives insert-or-read semantics. It never generates a
  replacement id.

Do not increase `_api` timeout and do not automatically issue a second POST after an outcome-unknown
transport error.

Classify the delivery POST result in this exact order; every error retains the created worker's
repository/worktree mapping and `delivery_id`:

| POST observation (`ApiToolError`) | Reconciliation | Structured result |
|---|---|---|
| success resource | none | accepted resource |
| `code=IDEMPOTENCY_CONFLICT`, `status=409` | no GET and no retry POST | surface the conflict with `RESOLVE_IDEMPOTENCY_CONFLICT`, `tool=delivery_status`, the same id, and “inspect it and do not retry the changed task” |
| `outcome_unknown=true`, or `status>=500` without `code=DELIVERY_ACCEPT_REJECTED` | exactly one GET of the same id | found → return resource; missing/unavailable → retain the original unknown error and `CHECK_DELIVERY_STATUS`, `tool=delivery_status`, the same id, and do-not-resend wording |
| no request sent: `outcome_unknown=false`, `retryable=true`, `status is None`, POST method, and `code in {connect_error, transport_timeout}` | no GET and no automatic POST | `RETRY_SAME_DELIVERY`, `tool=retry_initial_delivery`, original name/task/id |
| explicit rollback: `code=DELIVERY_ACCEPT_REJECTED`, `status=503`, `outcome_unknown=false` | no GET and no automatic POST | the same `RETRY_SAME_DELIVERY` action |
| any other known 4xx/domain rejection | no GET and no retry POST | preserve typed error with `FIX_DELIVERY_REQUEST`; never suggest `send_message` |

A GET 404 after an ambiguous POST is unresolved, not proof of non-commit: the timed-out POST may
still be running. `spawn_worker` therefore never emits `RETRY_SAME_DELIVERY` from the reconciliation
GET. Only the two proven no-commit rows above may recommend that tool, and even then the caller must
invoke it explicitly; `spawn_worker` itself performs no second POST.

## Crash/restart reconciliation matrix

| Last committed state | Startup action | Observable contract |
|---|---|---|
| no row (accept commit failed) | none | no log, no wake, zero backend calls; exact-key retry is allowed |
| `QUEUED` | schedule once | one log, one backend prompt copy, one backend call |
| prepare transaction failed | remains `QUEUED` | no partial log/state; later safe retry |
| `PREPARING` + `user_log_id` | reuse log and schedule once | one log, one backend prompt copy, one backend call |
| `DISPATCHING`, provider may or may not have accepted | set `DELIVERY_UNKNOWN`, no schedule | actionable status, zero automatic replay |
| `SUBMITTED` | leave terminal/observed | no schedule |
| `DELIVERY_UNKNOWN` | leave terminal/unknown | no schedule; status keeps actionable no-resend guidance |

The two `DISPATCHING` realities are intentionally indistinguishable. The protocol pays with visible
uncertainty rather than risking a duplicate model turn.

## Tickets

### T1 — Accept and query one durable initial delivery

- Files: `app/db.py`, `app/initial_deliveries.py` (new), `app/routes/sessions.py`,
  `tests/test_initial_deliveries.py`
- Test: `tests/test_initial_deliveries.py::test_t1_*` — committed RED in
  `327242a7432ef7b325cb7c4de38244479bcc1cab`
- RED command: `uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t1_'`
- RED result: exit 1, 5 failed; first missing-behavior assertion:
  `AssertionError: #311 missing behavior: app.initial_deliveries does not exist`
- AC: `uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t1_'` is green;
  canonical fingerprint fields and table columns are exactly those stated above; ordinary `/send`
  and at-least-once queues are not touched.
- blocked-by: none

### T2 — Dispatch/recover without duplicate logical input or blind replay

- Files: `app/initial_deliveries.py`, `app/manager.py`, `app/session.py`, `app/main.py`,
  `tests/test_initial_deliveries.py`
- Test: `tests/test_initial_deliveries.py::test_t2_*` — committed RED in
  `327242a7432ef7b325cb7c4de38244479bcc1cab`
- RED command: `uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t2_'`
- RED result: exit 1, 10 failed; first missing-behavior assertion:
  `AssertionError: ...send_initial_delivery is not callable`
- AC: `uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t2_'` is green;
  `app/manager.py` changes are limited to the exact narrow entry above after reconciliation with
  current `main`; recovery is inserted at the exact startup point above; explicit cancellation
  cannot strand `DISPATCHING`; strict provider exactly-once is not claimed; ambiguous dispatch is
  never replayed.
- blocked-by: T1

### T3 — Move `spawn_worker` to accepted delivery with reconciliation tools

- Files: `app/mcp_stdio.py`, `tests/test_mcp_stdio.py`
- Test: `tests/test_mcp_stdio.py::test_t3_*` — committed RED in
  `327242a7432ef7b325cb7c4de38244479bcc1cab`
- RED command: `uv run python -m pytest -q tests/test_mcp_stdio.py -k 'test_t3_'`
- RED result: exit 1, 9 failed; first missing-behavior assertion:
  `AssertionError: #311 missing behavior: spawn still uses synchronous /send`
- AC: `uv run python -m pytest -q tests/test_mcp_stdio.py -k 'test_t3_'` is green; existing
  create-session validation, exact repository/worktree mapping, sender propagation, and typed error
  envelopes remain compatible; the classification table above is implemented verbatim; no timeout
  is increased and no unknown delivery is automatically reposted.
- blocked-by: T1, T2

## Oracle coverage

The committed tests mechanically cover:

- cold runtime blocked indefinitely behind an event while acceptance returns 202, using only an
  event-loop tick (`asyncio.sleep(0)`) and no wall-clock sleep;
- committed-row visibility before wake;
- same id/same payload insert-or-read and one wake;
- same id/different payload 409;
- forced acceptance transaction failure: no row/log/wake/backend call;
- the HTTP form of that rollback is an explicit 503 `DELIVERY_ACCEPT_REJECTED` with
  `outcome_unknown=false`, `retryable=true`, and `commit_state=NOT_COMMITTED`;
- status lookup returns the committed resource;
- manager lock and auto-switch order;
- suppression of the ordinary duplicate `user_message`, exact exclusion of the prepared current
  input from reconstructed history while an older input remains, and before/backend/after ordering;
- restart from `QUEUED` and `PREPARING`, with one log/prompt/backend call;
- atomic PREPARING + user-log transaction;
- both possible realities of orphan `DISPATCHING`, with `DELIVERY_UNKNOWN` and no replay;
- in-process cancellation after `DISPATCHING`, with synchronous unknown marking and no recovery
  replay;
- startup source wires recovery after auto-resume and before orphan sweep, manager background tasks,
  and restart-inbox drain;
- `SUBMITTED` remains unscheduled;
- caller key in MCP POST, prompt accepted wording, timeout reconciliation with one POST, structured
  unknown/no-resend action, and same-key status/retry tools whose retry body preserves message,
  scope, and sender;
- committed-then-HTTP-500 plus unavailable lookup yields status reconciliation only and no second
  POST;
- same-key/different-payload HTTP 409 yields an actionable conflict and no retry.

## Verification after implementation

Per ticket, run its exact frozen command before and after changes. After T3, run focused regressions:

```bash
uv run python -m pytest -q \
  tests/test_initial_deliveries.py \
  tests/test_mcp_stdio.py \
  tests/test_manager.py \
  tests/test_session.py \
  tests/test_api.py
```

Then run the repository-required full suite once:

```bash
uv run python -m pytest -x -q > /tmp/pytest-311.log 2>&1
```

If `uv.lock` changes after any test command, stop and restore the dependency barrier rather than
committing the lockfile.

## Review decision gate

- Changed artifacts at Phase 2: `plan.md`, immutable tests in
  `tests/test_initial_deliveries.py` and `tests/test_mcp_stdio.py`.
- Consumers planned for Phase 3: SQLite schema, HTTP/MCP external protocol, shared manager/session
  delivery and recovery, startup lifecycle.
- Author runtime: Codex/Sol.
- Exact AC: T1/T2/T3 commands above must turn green without changing any test from RED commit
  `327242a7432ef7b325cb7c4de38244479bcc1cab`; all verbatim non-test constraints remain true.
- Named checks observed: T1 exit 1 (5 failed), T2 exit 1 (10 failed), T3 exit 1 (9 failed), each at
  the missing behavior rather than collection/import failure; `git diff --check` clean.
- Risk route: mandatory targeted Sol review because this is shared message delivery, persistence,
  concurrency, startup recovery, and an externally consumed protocol. Phase 2 contains no production
  code, so the high-risk Sol-authored production-code Opus floor applies later in Phase 3, not here.

Review outcome:

- Round 1 (`docs/tasks/311/review-plan.md`): `BLOCKING FINDINGS REMAIN`. Accepted and fixed all four
  blockers: added the prepared-log history oracle; pinned the complete canonical retry body;
  removed unreachable `COMPLETED`; added the executable acceptance-error table plus frozen 500 and
  409 cases. Also accepted the cancellation and exact-startup-order suggestions. The changed tests
  were first re-frozen in `176fb03757781a2086fb9c8a42c31c9270a269df`; a final audit added actual
  route-envelope and startup-wiring checks, pinned the POST route's 202 declaration, and
  strengthened the exact exclusion of only the prepared current history row. The definitive suite is frozen in
  `327242a7432ef7b325cb7c4de38244479bcc1cab`; every earlier freeze is excluded.
- Round 2 (`docs/tasks/311/review-plan.md`, resumed Sol session): `APPROVED — PLAN READY`.
  Reviewer confirmed every Round 1 finding resolved in the definitive RED freeze and found no new
  contract or oracle gap. Production implementation remains gated on orchestrator approval.

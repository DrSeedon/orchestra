# #380 Phase 2 plan — opt-in direct-message acceptance receipts

Date: 2026-08-23

Baseline: `main` at `71374ea56bcc06a298165552d6419a7c54bb07ba`; Phase 1 research commit
`aaac25c6`; frozen RED baseline `c42163d9`.

## Goal

For MCP/REST direct-message callers that supply `delivery_id`, commit an idempotent SQLite receipt
and return HTTP 202 before target load, quota admission, `manager.send`, runtime startup, or running
steer completes. Orchestra promises exactly-once durable acceptance, one immutable user row, and
at-most-once provider submission with loud ambiguity. It does not promise provider-side exactly-once
execution or model-turn completion.

The current unkeyed `/api/sessions/{name}/send` behavior remains available and synchronous.

## Scope

In scope:

- opt-in `delivery_id` on the existing REST `SendRequest`;
- a new direct-message receipt table/module and authenticated status lookup;
- idle start and running mid-turn steer through existing manager/session locks;
- durable deferral for compacting, no-mid-turn runtimes, and #385 deferred Codex interruption;
- per-target FIFO, task-generation revalidation, restart recovery, and same-key MCP reconciliation;
- old synchronous route compatibility and #311/#381/#385 regressions.

Out of scope:

- changing `initial_deliveries` storage or behavior;
- Telegram, mailbox, fan-barrier, auto-report, background-job, dashboard, or universal ingress;
- provider changes, provider retry, provider-side idempotency claims, batching, leases, brokers, or
  distributed/enterprise queue machinery;
- longer HTTP/MCP timeouts;
- live sends, provider calls, deploys, or service restarts.

Keyed mode is selected before the legacy mailbox/fan/direct branches. `delivery_id=""` follows the
existing code unchanged. A keyed request is the normal waking direct-message path only: `wake=false`
or a non-null `message_kind` returns a typed, known `UNSUPPORTED_KEYED_INGRESS` rejection before any
receipt. Existing producers of those non-goal ingress types continue to omit `delivery_id`.

## Frozen public contract

### REST request and resource

Add only optional fields to `SendRequest`:

```python
delivery_id: str = ""
```

No key means legacy behavior. A nonblank UUID means durable mode. The POST remains
`/api/sessions/{name}/send`; durable success returns `JSONResponse(resource, status_code=202)`.

The receipt resource is:

```json
{
  "ok": true,
  "acceptance": "ACCEPTED|ALREADY_ACCEPTED",
  "delivery_id": "<caller UUID>",
  "delivery_state": "QUEUED|PREPARING|FAILED_BEFORE_SUBMIT|DISPATCHING|SUBMITTED|DELIVERY_UNKNOWN",
  "payload_hash": "<sha256 hex>",
  "accept_seq": 123,
  "status_url": "/api/message-deliveries/<uuid>",
  "provider_ref": null,
  "error": null,
  "next_action": {}
}
```

`ACCEPTED` means this POST committed the first row. `ALREADY_ACCEPTED` means the same key/hash already
owns the logical message, including a safe explicit retry from `FAILED_BEFORE_SUBMIT`. HTTP 202 means
Orchestra ownership only; no success text may say `sent`, `delivered`, or `model started`.

Add:

```text
GET /api/message-deliveries/{delivery_id}
```

The status route returns the same resource to the source principal or authenticated operator.

### Acceptance outcomes

| Outcome | Durable fact | HTTP/tool action |
|---|---|---|
| `ACCEPTED` | new key/hash committed | 202; poll same id |
| `ALREADY_ACCEPTED` | matching row already committed | 202; no second row/runner attempt from the duplicate POST |
| `NOT_ACCEPTED` | auth/validation/conflict failed, or rollback absence is proven | typed 4xx/503, `outcome_unknown=false` |
| `AMBIGUOUS` | client cannot reconcile POST result | MCP error/result retains same id; GET or same-key retry only |

`AMBIGUOUS` is a caller observation, not a database acceptance state. An immediate status 404 after
a timed-out POST is inconclusive because the original POST may still be committing.

### MCP

Keep the two required arguments and add one optional argument:

```python
async def send_message(to: str, message: str, delivery_id: str = "") -> str
```

A blank value creates one UUID before the first POST. The POST always includes that id. On a
non-GET transport error or unclassified 5xx, the tool performs exactly one GET for the same id:

- matching receipt -> return truthful `Message accepted ... delivery_id=...; state=...` text;
- unavailable/missing reconciliation -> raise `ApiToolError(outcome_unknown=True)` whose `result`
  contains `acceptance=AMBIGUOUS`, the same id, status action, and an explicit warning never to retry
  with a fresh key;
- no branch mints a replacement id.

Add `message_delivery_status(delivery_id)`. An explicit retry uses `send_message` with the original
`delivery_id`; there is no automatic blind POST loop.

## Persistence owner

### New table

`app/db.py:init_db` creates a new table; there is no migration or data copy for #311 rows:

```text
message_deliveries
  accept_seq          INTEGER PRIMARY KEY AUTOINCREMENT
  delivery_id         TEXT NOT NULL UNIQUE
  schema_version      INTEGER NOT NULL
  source_session_id   TEXT
  source_principal    TEXT NOT NULL
  source_name         TEXT NOT NULL
  source_scope        TEXT NOT NULL
  source_task_id      TEXT NOT NULL
  target_session_id   TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE
  target_name         TEXT NOT NULL
  target_scope        TEXT NOT NULL
  target_task_id      TEXT NOT NULL
  target_generation   TEXT NOT NULL
  message             TEXT NOT NULL
  rendered_message    TEXT NOT NULL
  message_kind        TEXT
  wake                INTEGER NOT NULL
  payload_hash        TEXT NOT NULL
  state               TEXT NOT NULL
  user_log_id         INTEGER UNIQUE REFERENCES logs(id)
  provider_ref        TEXT
  error_json          TEXT
  created_at          TEXT NOT NULL
  updated_at          TEXT NOT NULL
```

Indexes:

```text
UNIQUE(delivery_id)
(target_session_id, accept_seq)
(source_session_id, accept_seq)
```

`accept_seq` is allocated only by the first successful insert and defines FIFO as SQLite commit
order. Async `logs.id` and wall-clock timestamps never define delivery ordering.

### Canonical payload hash

`SHA-256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))` over:

```text
protocol="direct-message/v1"
source_session_id / source_principal / source_scope / source_task_id
target_session_id / target_scope / target_task_id / target_generation
message / rendered_message / message_kind / wake
```

Exclude delivery id, names used only for display, timestamps, attempts, proof token, current status,
and provider refs. Persist `rendered_message` before commit, so rename/context changes cannot bind
one key to different provider bytes. Same key/different hash returns 409 without mutation or wake.

### New single owner

Create `app/message_deliveries.py` with these reviewed interfaces:

```python
accept_message_delivery(...) -> tuple[dict, int]
get_message_delivery(delivery_id, source_session_id) -> dict | None
prepare_message_delivery(delivery_id) -> dict
mark_message_delivery_dispatching(delivery_id) -> dict
mark_message_delivery_submitted(delivery_id, provider_ref=None) -> dict
mark_message_delivery_failed_before_submit(delivery_id, error) -> dict
mark_message_delivery_unknown(delivery_id, error, orphaned=False) -> dict
run_message_delivery(delivery_id, manager=None) -> None
run_target_message_deliveries(target_session_id, manager=None) -> None
ensure_target_runner(target_session_id) -> None
recover_message_deliveries() -> None
MessageDeliveryContext
```

`_target_runner_tasks` and `_target_delivery_locks` are keyed by immutable target session id, not
delivery id/name. `_next_target_delivery(target_session_id)` is the single durable head query, and
`_observe_target_runner(task)` removes only its own task then rechecks that head. These named internal
seams are frozen because R7 interleaves a new SQLite commit with the runner's empty-head exit; a
second process-local runner cannot overtake because both calls take the same target lock. A
deliberately deferred `PREPARING` head is marked as waiting-for-boundary and is not hot-rescheduled;
the target turn/compact completion hook owns that wake.

Runner scheduling is after commit and best effort. A scheduling exception is logged but cannot turn
the committed resource into 500. A commit exception is reconciled by a new read: matching row ->
accepted, proven absence -> `DELIVERY_ACCEPT_REJECTED` with `commit_state=NOT_COMMITTED`, read failure
-> ambiguous.

## State machine and exactly-one user row

```text
QUEUED -> PREPARING -> DISPATCHING -> SUBMITTED
             |              |
             |              +-> DELIVERY_UNKNOWN
             +-> FAILED_BEFORE_SUBMIT
```

1. `accept_message_delivery` uses `BEGIN IMMEDIATE`, insert-or-read, and commits `QUEUED` before
   calling `ensure_target_runner`.
2. `prepare_message_delivery` inserts the masked `user_message` and changes
   `QUEUED -> PREPARING` in one transaction. A recovered `PREPARING` row must already own a valid
   `user_log_id`; the row is immutable and reused.
3. A delivery-aware session path never calls asynchronous `_log("user_message")`; the context's
   `history_user_message` excludes the already persisted row during native-history reconstruction.
4. `DISPATCHING` commits immediately before the actual idle provider `send` or running steer.
5. Successful provider-call return commits `SUBMITTED` and optional native turn ref.
6. Typed failure/cancellation before `DISPATCHING` commits `FAILED_BEFORE_SUBMIT`; matching POST
   atomically claims only that row back to `PREPARING` and wakes the target once.
7. Exception/cancellation/restart after `DISPATCHING` commits `DELIVERY_UNKNOWN`; it never requeues,
   never exposes a retry tool, and blocks later target sequences.

`SUBMITTED` releases FIFO to the next sequence. `FAILED_BEFORE_SUBMIT` and `DELIVERY_UNKNOWN` are
head-of-line barriers. There is no automatic skip/cancel resolution in #380.

## Target identity, project, and task generation

Keyed mode does not trust body `sender` or `scope`:

- MCP requires valid `X-Orchestra-Session-Id` + `X-Orchestra-Mcp-Proof`; load the source row and
  require body sender/scope to match it;
- a cookie-authenticated operator REST request is bound to an explicit operator principal and the
  authorized project scope; shared `INTERNAL_TOKEN` without proof is insufficient for keyed mode;
- same-project target resolution uses exact `(name, source_scope)`;
- cross-project resolution follows current role policy, but requires explicit scope or exactly one
  globally matching live/non-archived name; multiple matches return `409 TARGET_NAME_AMBIGUOUS`;
- persist/load by target session id after acceptance; name is display/audit only;
- status/same-key retry require the same source session or operator.

`target_generation` is the canonical token:

```text
session=<id>|task=<task_id>|branch=<branch>|needs_switch=<0|1>
```

`SessionManager.send_message_delivery` rechecks it under the existing per-session lock before
`_auto_switch_before_delivery`. A mismatch raises typed `TARGET_TASK_CHANGED` before `session.send`,
provider work, or branch mutation. Rechecking before auto-switch permits the accepted message itself
to perform the existing `needs_switch -> fresh adhoc branch` transition. The token includes branch
to prevent task-id ABA.

This validates the target generation, not message semantics. The unchanged two-argument caller
contract cannot prove from free text whether content is a new task or clarification; #380 does not
add a classifier or weaken the existing pre-send prompt gate.

## Manager/session delivery seam

Add:

```python
SessionManager.send_message_delivery(
    session_id, message, *, delivery, target_generation
) -> None
```

It mirrors `send`/`send_initial_delivery`: capture the target, own a child task through
`_wait_owned_task`, serialize on `get_session_lock`, reject session replacement, recheck generation,
run `_auto_switch_before_delivery`, then call `session.send(message, delivery=delivery)`.

`MessageDeliveryContext` is distinguishable from `InitialDeliveryContext` by explicit capability
(`allow_running=True`) and supports `before_submit`, `mark_submitted`, `mark_unknown`, and
`defer(reason)`. Initial delivery keeps the existing idle-only guard unchanged.

For a direct context, `AgentSession.send` preserves the existing behavior with different durable
bookkeeping:

- idle -> existing admission/prompt/backend/start path; context brackets provider call;
- running with healthy mid-turn injection -> existing backend steer, no quota/new turn;
- compacting, runtime without injection, or `deferred_interrupt_pending` -> call `defer`, leave row
  `PREPARING`, do not append the message to `_pending_messages`;
- failed running steer after `before_submit` -> unknown, never volatile fallback;
- failure before provider callable/boundary -> failed-before-submit;
- legacy calls (`delivery is None`) retain their current log, pending-list, and failure fallback.

`AgentSession._wake_durable_message_deliveries()` wakes `ensure_target_runner(self.id)` at the
existing safe boundaries that already wake `_flush_pending`: turn-event-loop finalization, native
Codex `_compact_codex_context()` finalization, and Claude `compact()` finalization. It only checks for
a durable deliverable row; it does not hold the HTTP request or poll. R7 drives each production owner
instead of calling the helper directly, plus the no-inject and deferred-interrupt branches. This
preserves #385: while the native interrupt is pending there is zero steer, and the receipt wakes only
after the native terminal event.

## Restart behavior

`app/main.py:lifespan` calls `recover_message_deliveries()` after `manager.auto_resume_all()` and
existing `recover_initial_deliveries()`, before `manager.start_background_tasks`, restart-inbox drain,
and bg-job restore.

- `QUEUED/PREPARING` -> ensure one target runner; FIFO chooses the head;
- orphan `DISPATCHING` -> atomically `DELIVERY_UNKNOWN`, no runner/provider replay;
- `FAILED_BEFORE_SUBMIT` / `DELIVERY_UNKNOWN` -> barriers, unscheduled;
- `SUBMITTED` -> terminal and skipped.

Recovery is idempotent. It never reads `total_turns`, log text, or provider history to guess whether
an ambiguous call happened.

## Compatibility and non-regression checks

The following behavior stays byte/semantically compatible:

- no-key REST `/send` returns existing 200 response and still uses mailbox/fan/legacy direct logic;
- old MCP subprocesses that omit `delivery_id` continue to work synchronously until reconnect;
- `initial_deliveries` table/module/routes/tools and every #311/#381 test stay unchanged;
- #385 normal running steer and deferred-interrupt quarantine remain intact;
- ordinary `manager.send` cancellation shielding remains unchanged.

Focused compatibility commands:

```text
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q \
  tests/test_api.py::TestSendMessage \
  tests/test_manager.py::TestSendAndControl::test_concurrent_sends_switch_once_and_deliver_serially \
  tests/test_manager.py::TestSendAndControl::test_running_send_preserves_mid_turn_delivery

/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q \
  tests/test_initial_deliveries.py \
  tests/test_initial_delivery_review_regressions.py

/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q \
  tests/test_session.py -k \
  'test_codex_runtime_steers_mid_turn_message or test_t1_385_message_during_deferred_interrupt_queues_until_native_terminal'
```

No ticket may edit `tests/test_message_delivery_receipts_380.py`, any #311/#381/#385 test, fixture,
`conftest.py`, marker, or test configuration after frozen commit `c42163d9`.

## Files and symbols

- `app/db.py:init_db` — additive table/index only; do not touch `initial_deliveries` DDL.
- new `app/message_deliveries.py` — sole direct receipt/hash/state/FIFO/recovery owner.
- `app/routes/sessions.py:SendRequest, send_message` — keyed branch first, legacy body unchanged;
  authenticated message-status GET.
- `app/mcp_stdio.py:send_message` — pre-POST UUID, GET reconciliation, truthful accepted/ambiguous
  result; new `message_delivery_status`.
- `app/manager.py:SessionManager.send_message_delivery` — target/generation/lock/auto-switch seam.
- `app/session.py:AgentSession.send` plus turn/native-compact/Claude-compact wake boundaries — direct context
  running/defer behavior; legacy and initial branches remain distinct.
- `app/main.py:lifespan` — direct receipt recovery ordering.
- `tests/test_message_delivery_receipts_380.py` — frozen R1–R7; implementation may not edit it.

## First review findings and resolution

The first independent Sol round returned `Needs work`. Its dissent remains in
`docs/tasks/380/review-plan.md`; none of the findings was recorded-and-ignored.

- ACK blank-key gap -> R3 now pins one generated UUID across POST, reconciliation GET, and status
  tool.
- ACK status authorization gap -> R6 pins owner/operator success plus unrelated-source and
  internal-token-only denial.
- ACK incomplete identity surface -> R6 pins operator principal/scope, unique cross-project target,
  ambiguous name, archived target, and server-derived source task/target identity.
- ACK lost-wake gap -> R7 interleaves a committed row with empty-head runner teardown through
  `_next_target_delivery` / `_observe_target_runner`.
- ACK concurrent FIFO gap -> R7 races two `BEGIN IMMEDIATE` accepts and two target runners, then
  derives expected provider order from committed `accept_seq` values.
- ACK orphan recovery gap -> R5 leaves a row in `DISPATCHING` before recovery and requires unknown,
  zero schedule, zero replay.
- ACK safe-boundary gap -> R7 covers compact, no-inject, and deferred interrupt, executes
  `_wake_durable_message_deliveries`, and pins it in turn/compact owners.
- ACK atomic log gap -> R4 injects failure both at user-log insert and after that insert but before
  the `PREPARING` state update; both sides must roll back.
- Accepted suggestion -> R1 pins unsupported keyed ingress, blank-key legacy routing,
  post-commit scheduler failure, lost commit acknowledgement, and keyed-before-fan selection.

Those Round 1 changes were frozen in `0f4ee12a`. Round 2 kept two blockers open: the lost-wake test
manually registered its runner/callback, and deferred tests manually invoked the wake helper. Both
were accepted and fixed rather than argued around:

- R7 now starts the first race runner only through production `ensure_target_runner`; the test reads
  the registered task but never writes the registry or attaches its callback.
- R7 now executes `_turn_event_loop` for no-inject and #385 terminal paths, and executes a real
  blocked `AgentSession.compact()` through the native Codex compact `finally`; each path must wake,
  submit once, and retain one user row.
- The Round 2 hash suggestion is also accepted: same key with changed target task/generation must
  conflict even when message bytes are unchanged.

Those Round 2 wiring changes were frozen in `d3452d16`. Before the final review, the compact oracle
was extended through both production owners: native Codex `_compact_codex_context()` and the Claude
summary-plus-ack `compact()` finally path. The final immutable baseline is `c42163d9`.

## Review decision inputs

- Changed Phase 2 files: `tests/test_message_delivery_receipts_380.py` and this plan; application
  files above are prospective Phase 3 changes/consumers.
- Author metadata from the live session row: model `gpt-5.6-sol`, runtime `codex`, role
  `full-cycle`, pipeline `default`.
- Risk floor: high — shared message delivery, queue/lock concurrency, auth, SQLite persistence,
  restart recovery, lifecycle/task gate, and externally consumed HTTP/MCP protocol.
- Exact AC: every ticket selector below becomes green without oracle changes; the three
  compatibility commands above remain green; the full focused receipt file is green; no live send,
  provider call, or restart occurs.
- Named RED command observed on `c42163d9`: the combined command in the last section exited 1 with
  22 assertion failures and no import/collection error.
- Current-main control results before review: legacy send/manager command `4 passed in 11.24s`;
  #311/#381 initial-delivery command `21 passed in 18.03s`; running-steer/#385 command
  `2 passed, 215 deselected in 7.99s`.
- Review route: direct Sol under `codex-debate`; two completed rounds used three total attempts
  because one wrapper rejection counted against the attempt ceiling. Round 2's two blockers were
  changed and re-frozen at `c42163d9`, but a confirming fourth call is forbidden. The reviewer
  artifact therefore retains `Needs work` plus post-fix evidence and **no final verdict**; Phase 2
  requires task-giver disposition rather than a false `APPROVED` label.

## Tickets

### T1 / R1 — Commit an opt-in receipt and dispatch one idle message

- Files: `app/db.py`, new `app/message_deliveries.py`, `app/routes/sessions.py`, `app/manager.py`,
  `app/session.py`
- Test: `tests/test_message_delivery_receipts_380.py -k 'test_t380_r1_'` — committed RED in
  `c42163d9`
- RED assertion: `AssertionError: #380 missing behavior: app.message_deliveries does not exist`
  and `AssertionError: #380 missing behavior: SendRequest has no opt-in delivery_id`
- AC: all five R1 cases are green; new/matching/conflict receipts, commit-before-blocked-manager,
  HTTP 202, one log/provider attempt, `accept_seq`, post-commit scheduling failure, lost commit-ack
  reconciliation, keyed-before-fan routing, unsupported keyed ingress, and legacy blank-key behavior
  match the frozen assertions; the first compatibility command is green.
- blocked-by: none

### T2 / R2 — Deliver the same receipt as one running-turn steer

- Files: `app/message_deliveries.py`, `app/manager.py`, `app/session.py`
- Test: `tests/test_message_delivery_receipts_380.py -k 'test_t380_r2_'` — committed RED in
  `c42163d9`
- RED assertion: `AssertionError: #380 missing behavior: app.message_deliveries does not exist`
- AC: the R2 command is green; it proves real `SessionManager -> AgentSession -> backend.send`
  running delivery, no quota/new turn/volatile queue, one immutable log, and one provider steer; the
  #381 and ordinary running-steer compatibility commands are green.
- blocked-by: T1

### T3 / R3 — Reconcile MCP timeout with the same caller key

- Files: `app/mcp_stdio.py`, `app/routes/sessions.py`
- Test: `tests/test_message_delivery_receipts_380.py -k 'test_t380_r3_'` — committed RED in
  `c42163d9`
- RED assertion: `AssertionError: #380 missing behavior: send_message has no caller-stable delivery_id`
- AC: both R3 cases are green; a blank invocation generates one UUID before POST; exactly one POST
  plus one GET occurs on unknown outcome; success/ambiguous/status-tool paths retain that UUID; no
  fresh blind retry is issued or recommended; existing `tests/test_mcp_stdio.py` send-message tests
  are green.
- blocked-by: T1

### T4 / R4 — Recover/cancel only proven pre-submit work

- Files: `app/message_deliveries.py`, `app/main.py`
- Test: `tests/test_message_delivery_receipts_380.py -k 'test_t380_r4_'` — committed RED in
  `c42163d9`
- RED assertion: `AssertionError: #380 missing behavior: app.message_deliveries does not exist`
- AC: both R4 cases are green; pre-submit cancellation becomes same-key retryable; a lost in-memory
  runner is recovered once from `PREPARING`; injected failure on either side of log-plus-PREPARING
  rolls both back; repeated recovery leaves one receipt/log/provider attempt per logical message;
  startup ordering and the full initial-delivery suite are green.
- blocked-by: T1

### T5 / R5 — Quarantine every post-dispatch error/cancellation

- Files: `app/message_deliveries.py`, `app/manager.py`, `app/session.py`
- Test: `tests/test_message_delivery_receipts_380.py -k 'test_t380_r5_'` — committed RED in
  `c42163d9`
- RED assertion: `AssertionError: #380 missing behavior: app.message_deliveries does not exist`
- AC: both R5 exception/cancellation arms and the orphan-recovery case are green; one provider
  attempt or orphaned `DISPATCHING` becomes `DELIVERY_UNKNOWN`; recovery schedules nothing and
  same-key POST does not replay; next action is status-only/non-retryable; #381
  provider-accept-then-loss remains green.
- blocked-by: T2

### T6 / R6 — Authenticate source/target and make rejection outcomes known

- Files: `app/routes/sessions.py`, `app/message_deliveries.py`
- Test: `tests/test_message_delivery_receipts_380.py -k 'test_t380_r6_'` — committed RED in
  `c42163d9`
- RED assertion: `AssertionError: #380 missing behavior: SendRequest has no opt-in delivery_id`
- AC: the R6 command is green; valid proof and cookie operator paths return 202; stored source task
  and target generation come from server rows; owner/operator status succeeds while unrelated source
  and internal-token-only status fail; authorized unique cross-project resolution succeeds; changed
  payload conflicts; sender/scope/proof spoof returns known 403; ambiguous/archived target rejects;
  forced insert rollback returns known 503 and creates no receipt/log; auth and legacy API regressions
  are green.
- blocked-by: T1

### T7 / R7 — Enforce target FIFO/generation and durable #385 deferral

- Files: `app/message_deliveries.py`, `app/manager.py`, `app/session.py`
- Test: `tests/test_message_delivery_receipts_380.py -k 'test_t380_r7_'` — committed RED in
  `c42163d9`
- RED assertion: `AssertionError: #380 missing behavior: app.message_deliveries does not exist`
- AC: all eight R7 cases are green; concurrent acceptance order equals `accept_seq`; two competing
  runners make one ordered provider stream; a commit at empty-head teardown is re-woken; unknown head
  blocks tail; changed task/branch generation fails before provider; compact/no-inject/deferred
  interrupt create no volatile copy or steer and submit once through the named safe-boundary wake;
  #385 and ordinary pending/steer tests are green.
- blocked-by: T2, T4, T5, T6

Tickets T2/T4/T5/T6 share `app/message_deliveries.py` and are serialized in Phase 3 even where their
logical dependencies would otherwise permit parallel work. T3 can proceed independently after T1
because its executable edits are confined to `app/mcp_stdio.py` plus the already-established route
contract.

## Frozen RED evidence

Frozen oracle commit: `c42163d9`. The earlier `9fa8d191`, `cf0e21e7`, `ef4b03be`, `0f4ee12a`, and
`d3452d16` snapshots are superseded by review-driven re-freezes; replay/immutability comparisons use
`c42163d9` only.

Command:

```text
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q \
  tests/test_message_delivery_receipts_380.py -k 'test_t380_'
```

Observed current-main result:

```text
exit 1
FFFFFFFFFFFFFFFFFFFFFF [100%]
22 failed
AssertionError: #380 missing behavior: app.message_deliveries does not exist
AssertionError: #380 missing behavior: SendRequest has no opt-in delivery_id
AssertionError: #380 missing behavior: send_message has no caller-stable delivery_id
```

The barriers are scheduler events, not 31-second sleeps. Collection succeeds; every failure is the
missing #380 behavior, not ImportError, collection error, live quota, provider, or wall-clock timing.

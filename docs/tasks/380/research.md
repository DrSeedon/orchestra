# #380 — Durable acceptance receipts for direct `send_message`

Date: 2026-08-23

Code baseline: `main` / `71374ea56bcc06a298165552d6419a7c54bb07ba` (includes #381 and #385)

Phase: 1 — research only

## Question

### Context

Orchestra has one operator, many project scopes, and persistent workers backed by Claude, Codex,
and Grok. The MCP `send_message` tool currently performs one HTTP POST whose response is held until
the recipient's downstream `manager.send` work returns. Two independent live incidents show that
the recipient can accept/start or steer work while the MCP transport later reports a 30-second
`ReadTimeout` with `outcome_unknown=true` [1].

### Change under test

Replace the synchronous success boundary for MCP direct messages with a caller-keyed, SQLite-backed
acceptance receipt. Commit acceptance before any load, auto-switch, quota check, runtime startup, or
mid-turn provider injection; return that receipt promptly; perform the downstream delivery under the
existing session gates asynchronously.

### Baseline

Keep the current synchronous `/api/sessions/{name}/send` behavior and its unkeyed, transport-level
outcome. Raising the HTTP timeout is explicitly excluded.

### Measurable outcome

The design is correct only if all of the following can be demonstrated with fake backends and a
temporary SQLite DB:

1. an idle recipient and a running recipient each return a committed receipt while
   `manager.send` is still blocked for an unbounded interval (therefore also for more than 30 s);
2. client timeout, cancellation, and same-key retry create one receipt, one immutable user row, and
   at most one provider submission/steer;
3. restart replays only work that provably did not cross the provider-call boundary;
4. a crash or lost acknowledgement after that boundary becomes durable ambiguity and is never
   replayed automatically;
5. per-recipient commit order is preserved, target project/session/task identity is revalidated,
   normal running-turn injection remains injection, and no second active task is started.

## Hypotheses considered

### H1 — the defect is the HTTP success boundary, not a universally missing delivery

`send_message` can finish the user-visible side effect while its HTTP handler is still awaiting
downstream work, so the 30-second client timeout converts success into a false unknown outcome.

Falsifier: either live recipient history lacks the message, or current code commits/returns an
acceptance receipt before awaiting `manager.send`.

### H2 — increasing the timeout would solve the contract

A larger timeout would be sufficient if downstream completion had a bounded upper limit and if a
transport close could not happen after the side effect.

Falsifier: any unbounded downstream operation or any client/process failure after the side effect.
Both exist; this hypothesis is refuted.

### H3 — #311 `initial_deliveries` can be reused unchanged

The existing table/module would be sufficient if direct delivery had the same single-idle-target,
single-message, no-FIFO, no-running-steer semantics as spawn delivery.

Falsifier: direct messages need recipient FIFO, running-turn injection, durable deferral while a
turn is compacting/interrupted, source authorization, or task-generation revalidation. All are
present, so unchanged reuse is refuted.

### H4 — a narrow direct-message receipt should reuse #311's invariants, not its storage owner

A separate direct-message table/runner can copy the proven boundary and state invariants while
leaving the stable spawn protocol untouched. It is preferable if generalizing `initial_deliveries`
would require migrations and behavior changes unrelated to #380.

Falsifier: a small discriminator/additive change to the existing owner can express FIFO, running
steer/defer, authorization, and task snapshots without changing initial-delivery behavior. The
current schema and code do not meet that condition.

## Measurements and current-main trace

### M1 — two live cases are delivery/outcome disagreement, not a hypothetical race

The live DB was opened read-only. No message, provider call, or restart was issued.

Case A, idle start:

- caller tool row `logs.id=200108`, `2026-08-23T10:48:09.468633Z`;
- recipient `ai-table-worker` user row `logs.id=200110`,
  `2026-08-23T10:48:09.588070Z`, only **0.119437 s** after the tool call began;
- caller result `logs.id=200122`, `2026-08-23T10:48:39.290561Z`, exactly
  `transport_timeout: ReadTimeout`, **29.821928 s** after the tool row; the incident reporter's
  end-to-end measurement was 30.2 s;
- the task record states that the worker was idle before the call and running after the timeout [1].

Case B, running steer:

- caller tool row `logs.id=201527`, `2026-08-23T15:06:58.816828Z`;
- caller result `logs.id=201546`, `2026-08-23T15:07:29.023462Z`, exactly
  `transport_timeout: ReadTimeout`, **30.206634 s** after the tool row; the reporter measured
  30.5 s and deliberately did not retry;
- the same content later appears once as recipient user row `logs.id=201782`, followed by
  `logs.id=201784` = `message steered into active Codex turn`; no second caller send exists [1].

**Finding F1: CONFIRMED — tier 1 direct production measurement.** Both failures are false statements
about acceptance: the client could not know whether the side effect occurred, while the recipient
history proves that it did.

### M2 — current code makes the false outcome inevitable

The exact current path is:

```text
app.mcp_stdio.send_message
  -> _api(POST /api/sessions/{to}/send, default timeout=30)
  -> routes.sessions.send_message
  -> await manager.send(session.id, rendered_message)
  -> SessionManager.send: per-session lock, auto-switch, await session.send
  -> AgentSession.send
       idle: admission -> log -> RUNNING -> ensure backend -> backend.send
       running: log -> backend.send (steer), or volatile pending queue
  <- HTTP 200 only after all of the above returns
```

`_api` classifies a non-GET `ReadTimeout` after a request may have been sent as
`outcome_unknown=true` and `retryable=false` [2]. The route has no idempotency key or status
resource and returns only after `await manager.send` [3]. `SessionManager.send` creates a child
delivery task and `_wait_owned_task` shields it from caller cancellation; a disconnected client
therefore does not prove that downstream delivery stopped [4].

A fake-only cancellation probe ran both `idle_start` and `running_steer`. In both cases a cancelled
route task remained unfinished, the downstream call count was already one, and the route returned
`{"ok": true}` only after the fake send barrier was released:

```text
{"case":"idle_start","route_done_after_client_cancel":false,
 "delivery_calls_before_release":1,"response":{"ok":true,"parent_name":""}}
{"case":"running_steer","route_done_after_client_cancel":false,
 "delivery_calls_before_release":1,"response":{"ok":true,"parent_name":""}}
```

No provider or live session was involved [5].

**Finding F2: CONFIRMED — tier 1 fake measurement plus tier 2 current source.** The transport and
delivery lifetimes are intentionally coupled, and cancellation shielding keeps the server-owned
operation alive after the client stops waiting.

### M3 — idle start and running steer have different downstream boundaries

For an idle worker, `AgentSession.send` performs quota admission, may rebuild prompt/identity, sets
and persists `RUNNING`, creates/loads a backend, and awaits `backend.send`. The ordinary path writes
its user row through fire-and-forget `_log`; the row is not part of a synchronous acceptance
transaction [6].

For a running worker, `AgentSession.send` writes the user row, then:

- queues in memory during compaction;
- queues in memory while #385's `deferred_interrupt_pending` is true;
- queues in memory when the runtime does not support mid-turn injection;
- otherwise awaits `backend.send`, which is the Codex/Claude steering seam;
- on a steer exception, queues in memory and returns [6].

The current `_pending_messages` list is process memory. `_flush_pending` can put messages back into
that list on drain/failure and comments explicitly that those messages die with the process [7].
#385 additionally requires that a genuine wake racing a deferred Codex interrupt remain queued
until the native terminal event instead of steering the dying turn [8].

**Finding F3: CONFIRMED — tier 2 current source, cross-checked by five focused tests.** The command

```text
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q \
  tests/test_manager.py::TestSendAndControl::test_concurrent_sends_switch_once_and_deliver_serially \
  tests/test_manager.py::TestSendAndControl::test_running_send_preserves_mid_turn_delivery \
  tests/test_session.py::TestRuntimeCapabilities::test_codex_runtime_steers_mid_turn_message \
  tests/test_initial_deliveries.py::test_t2_restart_never_replays_dispatching_even_if_acceptance_is_unknown
```

returned `5 passed in 12.35s` [5]. A receipt implementation that merely calls `manager.send` in a
background task and marks the receipt delivered when it returns would still lose the intentional
in-memory deferral branches on restart.

## Earliest truthful durable acceptance boundary

The earliest truthful boundary is one successful SQLite transaction that:

1. authenticates and resolves the caller/target before the transaction is committed;
2. inserts or reads the caller-supplied delivery key;
3. binds it to a canonical payload hash and immutable source/target identities;
4. assigns its per-target acceptance sequence only on first insert;
5. commits state `QUEUED`.

The response must be formed from that committed row. Starting a runner is post-commit best effort;
a runner-scheduling exception cannot turn an accepted row into HTTP 500. On a commit exception the
server performs a read-by-key reconciliation: matching row means accepted, proven absence means not
accepted, and inability to read means ambiguous. This closes the post-commit/pre-response gap that
an unconditional `raise` would preserve.

Everything below can and should be asynchronous:

- loading the target by stable session id;
- waiting for its per-session delivery lock/FIFO head;
- auto-switch and task-generation revalidation;
- quota admission;
- the exactly-once user-log prepare transaction;
- prompt refresh, backend creation, and hibernate wake;
- current-turn steering or waiting for the current turn/compact/deferred interrupt to settle;
- provider submission acknowledgement and terminal model output.

Acceptance is therefore exactly-once durable ownership by Orchestra, not a claim that the model has
seen the message or finished a turn.

**Finding F4: CONFIRMED as a local transactional boundary — tier 2 SQLite/current-code evidence.**
`#311` already proves commit-before-runner and prepare-with-one-user-row for initial delivery [9].
Provider-side exactly-once remains impossible without provider idempotency; #380 must promise
exactly-once acceptance plus at-most-once submission, not exactly-once external effect.

## Recommended narrow protocol

### Why a separate direct-message owner is safer than widening `initial_deliveries`

| Choice | Reuse gained | Blocking mismatch / risk | Verdict |
|---|---|---|---|
| Reuse `initial_deliveries` unchanged | Existing UUID/hash/status/recovery | It rejects running targets, has no source session, task snapshot, FIFO sequence, message kind, or durable defer disposition; runners are per delivery, not per target | Refuted |
| Generalize the existing table/module in place | One delivery table/state owner | Migrates and changes the already-shipped spawn path; direct and initial retry rules differ; #381's idle-only pre-provider classification becomes conditional everywhere | Possible later, too much regression surface for #380 |
| Separate `message_deliveries` receipt, reuse #311 invariants and MCP reconciliation shapes | Leaves spawn behavior/schema stable; direct semantics are explicit | Some small state/hash code is duplicated unless common pure helpers are extracted | Recommended |
| Implement #187's universal enterprise-style ingress now | One ingress for HTTP/TG/bg/spawn/review | Far beyond #380; #187 was planned but not implemented, and changes unrelated producers and batching | Rejected as scope expansion |

The recommended implementation is a narrow `app/message_deliveries.py` owner plus a
`message_deliveries` table. Reuse the proven #311 rules—caller key before POST, canonical hash,
insert-or-read, commit before wake, one immutable log, pre-submit versus ambiguous classification,
status reconciliation—but do not reuse its idle-only class or migrate its table. Pure response/error
normalization in `mcp_stdio.py` may be shared. Do not build leases, brokers, distributed queues, or
an enterprise abstraction.

### Identity and payload hash

The MCP process creates a UUID delivery id before the first POST. An optional `delivery_id` argument
keeps the existing required `send_message(to, message)` call shape compatible while making an
explicit same-key retry possible. A blank value creates one UUID once for that tool invocation; an
error/result always carries it.

The globally unique key is `delivery_id`. The canonical SHA-256 input is UTF-8 JSON with sorted keys
and compact separators:

```json
{
  "protocol": "direct-message/v1",
  "source_session_id": "<server-derived MCP session id>",
  "source_scope": "<server-derived scope>",
  "source_task_id": "<snapshot for audit>",
  "target_session_id": "<resolved immutable id>",
  "target_scope": "<resolved scope>",
  "target_task_id": "<dispatch-generation snapshot>",
  "message": "<original body>",
  "rendered_message": "<exact persisted [from:...] payload>",
  "message_kind": "<normalized nullable kind>",
  "wake": true
}
```

The key itself, timestamps, attempt ids, current worker name, current branch, and auth proof are not
hash inputs. `rendered_message` is frozen at acceptance so a rename/parent-context change cannot make
the same key send different bytes. Same key + same hash returns the original receipt. Same key +
different hash returns `409 IDEMPOTENCY_CONFLICT` and never mutates or dispatches either payload.

### Acceptance outcomes versus delivery states

These are separate axes and must not be collapsed into one `ok` boolean.

| Client acceptance outcome | Meaning | Retry rule |
|---|---|---|
| `ACCEPTED` | This request inserted and committed the receipt | Do not mint another key; poll status |
| `ALREADY_ACCEPTED` | Same key/hash already owns the logical message | Safe read; no new runner/provider call |
| `NOT_ACCEPTED` | Auth/validation/conflict failed before insert, or absence after commit failure is proven | Correct request or retry the same key only when typed retryable |
| `AMBIGUOUS` | POST outcome and status reconciliation are both unavailable/inconclusive | Keep the same key; GET/retry same key only; never send a new key |

`AMBIGUOUS` is normally a client observation, not a server row state: SQLite ultimately contains the
key or it does not. A matching status GET converts it to accepted/already accepted. An immediate 404
after a timed-out POST is not proof of absence because the original handler may still be in flight;
same-key retry is the safe resolver.

The durable delivery state machine is:

```text
QUEUED -> PREPARING -> DISPATCHING -> SUBMITTED
             |              |
             |              +-> DELIVERY_UNKNOWN
             +-> FAILED_BEFORE_SUBMIT
```

- `PREPARING` owns the sole `user_log_id`; receipt transition and log insert are one transaction.
- `DISPATCHING` commits immediately before the actual idle `backend.send` or running `backend.send`
  steer.
- `SUBMITTED` means that call returned successfully; it is not model-turn completion.
- a typed pre-provider failure may become `FAILED_BEFORE_SUBMIT` and is retryable only with the same
  key;
- exception, cancellation, lost acknowledgement, or restart after `DISPATCHING` becomes
  `DELIVERY_UNKNOWN`, is not retryable, and is never replayed automatically.
- intentional deferral caused by compaction, no mid-turn capability, or #385's deferred interrupt
  remains `QUEUED/PREPARING`; it must not be represented only by `_pending_messages`.

### Ordering and one-active-task preservation

First insertion allocates `accept_seq INTEGER PRIMARY KEY AUTOINCREMENT`. This defines ordering as
durable SQLite commit order, not wall-clock arrival or asynchronously inserted log ids. A same-key
retry reuses its sequence. One dispatcher per `target_session_id` may claim only the smallest
nonterminal sequence; all downstream calls still go through the existing
`SessionManager.get_session_lock`, `_auto_switch_before_delivery`, and `AgentSession._lifecycle_lock`.

`DELIVERY_UNKNOWN` and unresolved `FAILED_BEFORE_SUBMIT` are head-of-line barriers. Allowing later
messages through would claim an order the provider may not have observed. Only an explicit,
authorized resolution can release that barrier.

The receipt stores `target_task_id` at acceptance and rechecks it under the same session lock
immediately before provider dispatch. If it changed, the message fails before submit with a typed
`TARGET_TASK_CHANGED`; it must not steer/start the worker's new task. This preserves the current
one-worker/one-active-task gate across asynchronous delay. It does not pretend to infer task intent
from free text: the present two-argument tool cannot distinguish a new task from a clarification.
Structural enforcement of semantic intent would require a future explicit `intent/task_id` field;
#380 should preserve the current caller gate, not add a text parser.

### Project and receipt authorization

The body fields `sender` and `scope` are not authorization. Current middleware accepts the shared
`INTERNAL_TOKEN`, and current `/send` falls back from exact `(name, scope)` to name-only
`ensure_loaded_any`, which is ambiguous when names repeat across projects [3][10]. Durable mode must:

1. require an authenticated operator session, or `X-Orchestra-Session-Id` plus a valid MCP proof;
2. derive source name, scope, role, and task id from that session row;
3. resolve same-project targets by exact `(name, source_scope)`;
4. allow cross-project delivery only under the existing role policy and with an explicit target
   scope, or a provably unique target for backward compatibility; never silently pick the first
   same-name row;
5. persist the immutable `target_session_id`, then load/recover by id, not mutable name;
6. authorize status/same-key retry to the source session (and the authenticated operator), while
   treating source/target task ids as immutable audit and dispatch-generation constraints.

The current MCP proof is process-local but reissued for the same Orchestra session after reconnect;
therefore the durable owner is session id, not the transient proof token [10].

### Preserving idle and running behavior

The direct runner needs a delivery-aware sibling of `manager.send`, not a direct backend call.
Unlike `send_initial_delivery`, it must permit a running target and return a structured disposition:

- idle -> perform existing admission/auto-switch/start path;
- running + mid-turn inject available -> perform the existing steer path;
- running/compacting/deferred-interrupt/no-inject -> leave the receipt durably queued for the next
  safe boundary, without relying on `_pending_messages` as the source of truth;
- provider call attempted -> bracket it with `DISPATCHING` / `SUBMITTED` or
  `DELIVERY_UNKNOWN` callbacks.

The pre-persisted `user_log_id` makes every session branch skip its ordinary `_log("user_message")`.
The receipt identity must survive any intentional deferral. #385's `InjectedMessage` proves the
project already has an immutable in-process envelope and stable target-session-id precedent, but
`logs.event_id` is non-unique and is only provenance/correlation, not the idempotency owner [8][11].

## Client timeout, retry, restart, cancellation, and failure

### Client timeout/retry

`mcp_stdio.send_message` catches a POST transport error, performs one GET by the same delivery id,
and returns the matching receipt when found. If lookup is unavailable or races with the still-running
POST, it raises a structured `AMBIGUOUS` error containing the same id and the only safe actions:
`message_delivery_status(delivery_id)` or explicit same-key retry. It never creates a replacement id
inside reconciliation.

### Process restart

Startup recovery runs after `manager.auto_resume_all()` and before background delivery sources, as
#311 already does [12]. For direct receipts it must additionally restore per-target FIFO dispatchers:

- `QUEUED/PREPARING` -> schedule once in `accept_seq` order;
- `DISPATCHING` -> `DELIVERY_UNKNOWN`, no provider replay;
- `SUBMITTED/DELIVERY_UNKNOWN` -> terminal, unscheduled;
- a missing in-memory runner after commit is normal and recovered from SQLite.

### Cancellation and failure shoulders

- cancellation before acceptance commit -> no row, no log, no runner, no provider call;
- client disconnect/cancellation after commit -> does not cancel the server-owned runner;
- runner cancellation before `DISPATCHING` -> safe durable pre-submit state, recoverable once;
- cancellation after `DISPATCHING` -> `DELIVERY_UNKNOWN`, never replayed;
- acceptance transaction failure with proven absence -> `NOT_ACCEPTED`,
  `outcome_unknown=false`;
- target/auth/task validation failure -> `NOT_ACCEPTED` before row/log/runner;
- auto-switch/quota/backend preparation failure after acceptance but before provider call -> accepted
  receipt with typed pre-submit delivery failure/queue, not a false acceptance failure;
- provider accepts then transport/adapter raises -> one external call and `DELIVERY_UNKNOWN`;
- failure to schedule a runner after commit -> still `ACCEPTED`; startup/reconciliation sees the row.

**Finding F5: LIKELY design conclusion — tier 2 current source plus the implemented #311 precedent.**
The SQLite boundaries and in-process seams exist, but the direct protocol is not implemented and no
provider supplies an Orchestra idempotency receipt. Exact external delivery cannot be claimed.

## Deterministic RED design for Phase 2

No acceptance test is written in Phase 1. All tests below use a temporary DB, fake manager/session/
backend, and controlled `asyncio.Event` barriers. They perform no live send, provider call, or
restart. The common command should be:

```text
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q \
  tests/test_message_deliveries.py -k 'test_t380_'
```

The new test file must import only current modules. Before touching a new table/helper, it asserts
via `sqlite_master`/`getattr` with a ticket-specific message, so current main fails by assertion—not
ImportError or collection error.

### R1 — idle acceptance is independent of a >30-second start

`test_t380_idle_accepts_before_blocked_send_and_retry_starts_one_turn`

- idle real `AgentSession`, fake admission, fake backend;
- backend `send` sets `entered` then waits on an unreleased event (an unbounded wait represents
  `>30 s` without sleeping 31 seconds);
- POST durable `/send` with fixed UUID; assert 202 receipt completes within a short event-loop bound
  while backend remains blocked;
- retry the same UUID/hash; assert `ALREADY_ACCEPTED`, same sequence/receipt;
- release; assert exactly one user row, one backend call, one transition to `RUNNING`.

Current main is RED because the route task remains pending until the fake send is released and there
is no receipt/idempotency field.

### R2 — running acceptance is independent of a >30-second steer

`test_t380_running_accepts_before_blocked_steer_and_retry_injects_once`

- running Codex-capable session with a fake backend `send` barrier;
- assert receipt returns before the barrier;
- release and assert exactly one `backend.send`, status remains the same running turn, no new
  admission/backend/thread start, one user row;
- same-key retry before and after release never sends again.

This is the required production-shaped mid-turn shoulder, not a direct primitive-only test.

### R3 — MCP timeout reconciliation and explicit same-key retry

`test_t380_mcp_timeout_reconciles_one_key_without_duplicate_post`

- patch `_api` so POST commits a fake receipt and then raises the exact
  `transport_timeout`, `request_not_sent=false`, `outcome_unknown=true` envelope;
- GET returns the same key/hash; assert the tool reports accepted and never creates a second key;
- second arm: GET is unavailable/missing while the original POST remains in flight; assert
  `AMBIGUOUS` carries the fixed UUID and no automatic new-key POST occurs;
- an explicit retry with that UUID returns `ALREADY_ACCEPTED` and the server-side accept/provider
  counters remain one.

### R4 — request cancellation and pre-dispatch restart recover once

`test_t380_cancelled_response_and_restart_recover_pre_dispatch_once`

- commit receipt, cancel the request/runner before `DISPATCHING`, clear the in-memory runner
  registry to model a new process, invoke recovery;
- assert one receipt/sequence, one immutable user row, one manager send/provider call;
- run recovery again and assert all counts remain one.

### R5 — post-dispatch restart/cancellation is ambiguous and not replayed

`test_t380_restart_after_provider_accept_quarantines_without_replay`

- transition through real delivery callbacks to `DISPATCHING`;
- fake provider records one accepted call, then the runner is cancelled before submit acknowledgement;
- recovery changes the row to `DELIVERY_UNKNOWN`, runs no manager/provider call, preserves one user
  row, and exposes only status/manual resolution;
- repeat recovery three times; counts stay one.

### R6 — known failure, conflict, and authorization shoulders

`test_t380_not_accepted_and_conflict_never_create_side_effects`

- force the acceptance transaction to abort: typed `NOT_ACCEPTED`, `outcome_unknown=false`, zero
  receipt/log/runner/provider; remove trigger and same-key retry can accept;
- same key with changed message/target/task hash: 409 conflict, original unchanged;
- invalid MCP proof, forged sender/scope, ambiguous same-name cross-project target, archived target,
  and task mismatch all fail before provider; status GET from a different session is denied.

### R7 — FIFO, task generation, and #385 deferral

`test_t380_fifo_task_generation_and_deferred_interrupt_are_durable`

- accept two fixed keys for one target; block the first provider call; assert the second cannot enter
  manager/backend and sequences match commit order;
- change target task generation before a queued receipt's dispatch; assert typed pre-submit failure
  and no provider call for the new task;
- arm real #385 `deferred_interrupt_pending`; an accepted wake remains durable and sends zero steer
  calls until the native interrupted terminal is observed; afterward it delivers once through the
  normal path;
- an unresolved `DELIVERY_UNKNOWN` head blocks the following receipt rather than overtaking it.

## Counter-evidence, limits, risks, and edge cases

1. **A 202 receipt is not provider delivery.** It fixes false acceptance outcomes only if response
   text says `accepted/queued`, never `sent/delivered`.
2. **Exactly-once external provider effects are impossible here.** SQLite and a provider call cannot
   be one transaction; fail-stopped ambiguity trades availability for no blind duplicate [13].
3. **A separate table duplicates some #311 code.** This is accepted to isolate two materially
   different protocols; extract only pure helpers, not a speculative universal queue.
4. **Head-of-line ambiguity can block later messages.** That is intentional for strict ordering.
   Skipping it automatically would be an unproven ordering claim.
5. **The current two-argument tool cannot authorize task semantics from text.** The protocol can
   bind/revalidate the target task generation; it cannot prove that the content is a clarification
   rather than a new task. Do not add a heuristic text classifier.
6. **Legacy `/send` and other ingress remain possible.** The manager/session locks still serialize
   actual calls, but a #380-only receipt cannot claim global FIFO across Telegram, mailbox,
   background jobs, and legacy unkeyed HTTP. Universal ingress is the separate, unimplemented #187
   scope [13].
7. **Mixed-version rollout matters.** Existing MCP subprocesses keep the old tool until reconnect.
   The optional request fields and legacy synchronous route must coexist; only a client using a
   stable key receives the new guarantee.
8. **Log insertion order is not event order in general.** Receipt ordering uses a sequence allocated
   by the acceptance transaction, never async log ids/timestamps [14].
9. **Fan-barrier and `wake=false` branches already have separate durable owners.** Phase 2 must
   decide explicitly whether keyed direct acceptance wraps them or is limited to the normal waking
   MCP path; it must not run their side effects once synchronously and again in the receipt runner.

## Affected files for a future plan

Likely executable files:

- `app/db.py` — additive `message_deliveries` schema/indexes and migration;
- new `app/message_deliveries.py` — hash, receipt, per-target dispatcher, state/recovery owner;
- `app/routes/sessions.py` — optional durable mode on `/send`, exact target/auth resolution, status;
- `app/mcp_stdio.py` — stable key, reconciliation/status/same-key retry, truthful receipt text;
- `app/manager.py` — delivery-aware direct sibling that retains session lock and auto-switch;
- `app/session.py` — exactly-once log suppression, structured delivered/deferred disposition, provider
  boundary callbacks, durable #385 deferral;
- `app/main.py` — recovery after session resume and before other delivery sources;
- `tests/test_message_deliveries.py` — R1–R7.

Do not change timeout values, provider clients, deployment, service restart, or initial-delivery
schema/behavior merely to make #380 pass.

## Review decision and mechanical self-check

The review gate classifies this research as high risk: shared message delivery, concurrency,
persistence, auth, restart recovery, and externally consumed API behavior. That would normally route
directly to Sol. No `codex_review` capability is exposed in this session, and the task prohibits live
provider calls; no substitute reviewer was spawned.

Mechanical falsification completed instead:

- verified `HEAD == main == 71374ea5` and the presence of #381/#385 commits;
- joined both live tool/result pairs by `tool_use_id` and the recipient rows by exact content;
- traced every await from MCP through HTTP, manager, session, and backend boundaries;
- ran a fake-only caller-cancellation probe for idle and running status;
- ran the five existing lock/steer/restart regression cases;
- checked the current #311 table, hash, transitions, recovery order, and MCP reconciliation;
- checked #385's deferred-interrupt test and immutable injected-message seam;
- actively rejected timeout increase, unchanged #311 reuse, volatile pending-only delivery, and a
  universal #187 queue.

Review: **none — Codex reviewer unavailable and live provider calls prohibited**.

## Conclusions

1. **CONFIRMED:** both live failures are false acceptance outcomes caused by awaiting downstream
   delivery behind the HTTP response.
2. **CONFIRMED:** the first truthful response boundary is a committed, caller-keyed SQLite receipt;
   manager/session/provider work belongs after it.
3. **CONFIRMED:** client cancellation does not currently cancel the server-owned delivery, so a
   blind retry can duplicate input.
4. **CONFIRMED:** #311 provides the right invariants but cannot be reused unchanged for running
   direct messages, FIFO, task generation, and #385 deferral.
5. **LIKELY, implementation pending:** a narrow separate direct-message receipt/table is the least
   risky solution; reuse #311's protocol shapes, not its idle-only storage owner.
6. **CONFIRMED LIMIT:** the achievable guarantee is exactly-once durable acceptance, exactly one
   Orchestra user row, and at-most-once provider dispatch with loud ambiguity—not provider-side
   exactly-once execution.

## Sources

1. **Tier 1 — live read-only production evidence:** `/home/kesha/orchestra/data/orchestra.db`, task
   `tm_tasks.id=557/par_number=380`; log pairs `200108/200122` and `201527/201546`; recipient rows
   `200110`, `201782`, `201784`; queried read-only on 2026-08-23.
2. **Tier 2 — current primary source:** `app/mcp_stdio.py:477-526,501-552,1100-1110` — transport
   classification, 30-second default, direct tool POST.
3. **Tier 2 — current primary source:** `app/routes/sessions.py:171-180,603-717` — request schema,
   scope/name fallback, fan branches, synchronous `await manager.send`.
4. **Tier 2 — current primary source:** `app/manager.py:173-191,885-1044,1492-1523` — cancellation
   shielding, per-session lock, auto-switch, stable/id and name-based load paths.
5. **Tier 1 — fake/current-suite measurements:** fake cancellation probe output reproduced above;
   focused pytest command returned `5 passed in 12.35s` on `71374ea5`.
6. **Tier 2 — current primary source:** `app/session.py:1043-1345,4457-4504` — idle/running branches,
   #381 provider boundary, async user logging.
7. **Tier 2 — current primary source:** `app/session.py:2089-2222` — volatile pending queue, batching,
   drain/failure behavior.
8. **Tier 2 — current primary source/tests:** `app/session.py:1116-1148` and
   `tests/test_session.py:5418-5520` — #385 deferred interrupt must queue rather than steer.
9. **Tier 2 — implemented precedent:** `app/initial_deliveries.py:24-188,264-346,349-565` and
   `tests/test_initial_deliveries.py:107-589` — #311 hash, insert-or-read, one log, boundaries,
   restart recovery.
10. **Tier 2 — current primary source:** `app/auth.py:85-108`, `app/main.py:467-506`,
    `app/mcp_proof.py:1-66`, `app/manager.py:1492-1523` — shared token, MCP proof, current scope/name
    resolution.
11. **Tier 2 — current primary source:** `app/events.py:8-24`, `app/bg_jobs.py:531-555`,
    `app/db.py:116-145,801-813` — immutable injected provenance, stable target id, non-unique log
    event index.
12. **Tier 2 — current primary source:** `app/main.py:337-390` — session resume, initial-delivery
    recovery, and later background-source startup order.
13. **Tier 2 — prior local design, not implemented:** `docs/tasks/187/research.md:188-230` and
    `docs/tasks/187/plan.md:174-223` — universal ingress, at-most-once boundary, ambiguity, durable
    pending replacement.
14. **Tier 2 — project knowledge:** `docs/kb/evidence-methods.md` — async DB writes make log ids
    unsuitable as event-order evidence; receipt order must be defined by its own commit sequence.

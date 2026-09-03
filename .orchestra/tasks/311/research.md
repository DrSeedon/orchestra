# #311 — Durable initial-task delivery for `spawn_worker`

Date: 2026-08-17  
Code baseline: `main` = worktree `HEAD` = `b739cec2` at the start of research.

## Question

### Context

`spawn_worker` first creates a durable worker record/worktree, then sends the initial task through
the ordinary synchronous session-send route. A newly created worker has no connected model runtime,
so the second HTTP request includes cold runtime startup and provider submission before it answers.
[C1][C2][C3]

### Change under test

Replace the second, synchronous delivery step with a client-keyed durable delivery resource: commit
the initial task before waking the runtime, return an accepted receipt promptly, expose status, and
deduplicate every retry of the same logical delivery.

### Baseline

The current client uses a 30-second HTTP timeout. A timeout after the server received the task is
reported as `delivery="unknown"` with a structured `CHECK_DELIVERY_STATE` / do-not-resend action,
but there is no delivery identifier or status resource with which to perform that check. [C1]

### Measurable outcome

The protocol succeeds when all of these observations are true:

1. one committed `delivery_id` and payload fingerprint exist before the runtime wake begins;
2. cold startup duration does not delay the acceptance response;
3. the same key and payload return the same resource and cause at most one provider submission;
4. a different payload under the same key is rejected;
5. a restart before provider submission recovers the committed delivery once;
6. a failed pre-commit creates neither a delivery nor a model turn;
7. timeout/retry/restart never causes blind replay after submission may have occurred;
8. the response retains structured `next_action` guidance and the existing no-resend safety.

## Hypotheses considered

### H1 — The defect is the acknowledgement boundary

**Hypothesis.** The timeout is produced because HTTP acknowledgement is coupled to cold runtime
startup/provider submission, even though the task has already reached Orchestra.

**Falsifier.** H1 is wrong if timeout cases usually lack a persisted child `user_message`, if the
route responds before `manager.send`, or if the measured delay occurs before the route receives the
task rather than while `manager.send` is outstanding.

### H2 — Duplicate execution already occurs downstream

**Alternative.** The observed error is caused by duplicate provider submissions or duplicate worker
turns rather than a slow synchronous acknowledgement.

**Falsifier.** H2 is wrong for this incident if each failed parent call maps to one child initial
message and one first turn, with no retry being issued.

### H3 — Existing mailbox/restart persistence can be wired in unchanged

**Alternative.** `mailbox` or `restart_inbox` already supplies the required durable exactly-once
contract.

**Falsifier.** H3 is wrong if those queues are explicitly at-least-once, lack a caller-supplied
idempotency key/payload fingerprint/status API, or mark completion only after an external send whose
acceptance can be ambiguous.

### H4 — SQLite alone can guarantee exactly one external model turn across every crash point

**Alternative.** A local transaction and a unique key are sufficient for strict exactly-once
provider execution.

**Falsifier.** H4 is wrong if there is a crash window after the provider accepts a turn and before
SQLite records that acknowledgement, and the provider does not accept the caller's `delivery_id` as
an idempotency key.

## Measurements

### M1 — Live failure corpus (read-only)

The live SQLite database was opened read-only. The counting rule was fixed before querying: count
`logs.type='tool_result'` rows whose content starts with
`transport_timeout: Worker ... initial task delivery unknown:`; join the matching parent tool row by
`(session_id, tool_use_id)`; resolve the spawned worker named in that call; then inspect that child's
first `user_message`, turn-start status, and first model text. No production state was changed.

Measured result:

```text
scope                                  timeout results
/home/kesha/orchestra                  70
/home/kesha/projects/dnd-game-master   17
/home/kesha/projects/seedon            15
/home/kesha/projects/VPN-Service        8
/home/kesha/katya-work                  4
TOTAL                                 114

parent timeout result paired to spawn call: 114 / 114
child has initial user_message:               114 / 114
child has model turn-start status:            114 / 114
child has first model text:                   111 / 114

parent call duration:
min 30.414 s; median 31.751 s; p95 46.380 s; max 87.269 s
```

The three cases without first model text are not evidence of missing delivery: all three have the
initial message and a turn-start status; a turn may be unfinished or complete without a text event.
[M1]

The current #311 spawn is a concrete trace:

```text
parent spawn call       2026-08-17T09:44:36.190073+00:00
child user_message      2026-08-17T09:44:37.904824+00:00   (+1.715 s)
parent timeout result   2026-08-17T09:45:07.977...+00:00  (+31.787 s)
child model turn start  2026-08-17T09:45:32.977...+00:00  (+56.787 s)
child first model text  2026-08-17T09:45:46.214...+00:00  (+70.024 s)
```

This falsifies H2 for the measured no-retry incidents and supports H1: the task is present well
before the parent times out, while provider-turn startup occurs later. [M1]

### M2 — Current-call-path trace

The source trace on the same baseline is:

```text
mcp_stdio.spawn_worker
  POST /api/sessions                         # worker is durably published
  POST /api/sessions/{name}/send             # 30 s client timeout
routes.sessions.send_message
  manager.ensure_loaded(...)
  await manager.send(session.id, msg)         # response waits here
manager.send
  owned task + per-session lock
  await session.send(message)
AgentSession.send
  log user_message
  await _ensure_backend(...)                  # cold runtime connect
  await backend.send(outbound_message)        # provider submit
```

`_wait_owned_task` shields the manager-owned delivery from caller cancellation, so the server can
continue and start the turn after the HTTP client has timed out. That protects the current task from
cancellation, but it also makes the client's outcome unknowable without durable delivery status.
[C1][C2][C3]

## Findings

### F1 — The incident is systemic acknowledgement ambiguity, not missing task delivery

All 114 measured timeout results have a child initial message and turn start; all five affected
repositories show the same signature. The current route returns only after `manager.send`, and a
fresh worker connects its backend inside that call. [M1][C1][C2][C3]

**Confidence: CONFIRMED** — tier 1 live measurement plus tier 2 source/call-path trace.

### F2 — Increasing the timeout would preserve the protocol defect

The observed maximum is already 87.269 seconds, and the protocol still cannot distinguish “not
accepted” from “accepted, response lost” at any chosen timeout. RFC 9110 defines `202 Accepted` for
work accepted but not completed, specifically so the client connection need not persist, and says
the representation ought to point to a status monitor. [M1][S1]

**Confidence: CONFIRMED** — tier 1 distribution plus a primary HTTP specification.

### F3 — The current structured safety response is correct but not actionable

On `httpx.ReadTimeout`, `_api` emits typed `transport_timeout` with `outcome_unknown=True`.
`_spawn_delivery_error` preserves the worker mapping, marks delivery unknown, and instructs the
caller to check state and not resend. No `delivery_id` is created before POST, `SendRequest` has no
idempotency field, and no delivery-status route exists. [C1][C2]

**Confidence: CONFIRMED** — tier 2 primary source; relevant constructors, schema, routes, and tests
were traced.

### F4 — Existing queues do not meet the required semantics

`mailbox` and `restart_inbox` explicitly document at-least-once delivery. They mark a row delivered
after `manager.send`; a crash after provider acceptance but before that mark permits replay.
`undelivered_facts` has a dedupe key, but it stores facts consumed by prompt assembly, not an
original logical user delivery or its provider-submission lifecycle. [C4]

**Confidence: CONFIRMED** — tier 2 primary source and schema inspection. H3 is refuted.

### F5 — `merge_operations` is the closest in-repository protocol precedent

Merge operations already use a caller-stable UUID, request hash, `BEGIN IMMEDIATE`
insert-or-read, `202` for pending/running, status lookup, a background runner, and startup recovery.
The MCP caller generates the UUID before POST and reconciles transport errors through GET instead
of creating a new operation. [C5]

SQLite documents that `BEGIN IMMEDIATE` begins a write transaction and blocks other writers, and
that a committed transaction remains atomic across crash/power interruption (including WAL, by a
different mechanism). [S3][S4]

**Confidence: CONFIRMED** — tier 2 in-repository implementation corroborated by primary SQLite
documentation.

### F6 — The correct acceptance boundary is the committed delivery row, before runtime wake

Acceptance must atomically persist `(delivery_id, session_id, payload_fingerprint, payload,
state=QUEUED)` before scheduling any runner. Only after the transaction commits may the server
return `202` and wake the dispatcher. Failed insert/commit must schedule no wake and produce no model
turn. This makes cold runtime startup independent of the client request duration. [C5][S1][S3][S4]

The non-normative IETF Idempotency-Key draft independently describes the same client ambiguity for
POST, requires a unique client key, forbids reusing a key with a different payload, and recommends a
fingerprint. The document expired on 2026-04-18 and is cited only as corroborating design guidance,
not as an Internet Standard. [S2]

**Confidence: CONFIRMED for the local acceptance design** — two primary implementation/specification
sources; exact header syntax remains a project API choice.

### F7 — Cold startup must remain pre-submit, not be mislabeled ambiguous

`AgentSession.send` currently performs cold `_ensure_backend` before `backend.send`. If a dispatcher
marks `DISPATCHING` before calling the whole existing `manager.send`, a restart during a 30–180
second cold connect would be classified as “provider may have accepted” even though submission never
began. The durable transition must occur at the seam immediately before `backend.send`, with the
submission acknowledgement recorded immediately after it returns. [C3]

The existing quota-shadow hooks sit at exactly that seam, but intentionally swallow observer errors.
Delivery state is correctness-critical and therefore cannot reuse their fail-soft semantics; failure
to persist `DISPATCHING` must prevent the provider call. [C3]

**Confidence: CONFIRMED** — tier 2 direct ordering in the production send path.

### F8 — A stable key removes client/retry duplicates; it cannot create universal external exactly-once

The durable state machine can guarantee:

```text
QUEUED -> PREPARING -> DISPATCHING -> SUBMITTED -> COMPLETED
              |       |              |
              |       +-> DELIVERY_UNKNOWN
              +-> FAILED_BEFORE_SUBMIT
```

- same key + same fingerprint returns the existing row/status and never creates a second runner;
- same key + different fingerprint returns a conflict;
- failure of the initial insert/commit leaves **no row**, schedules no runner, and makes no backend
  call; the same key may be retried because status remains absent;
- `FAILED_BEFORE_SUBMIT` is a different case: a delivery row was committed successfully, then a
  typed terminal error proved that provider submission never began;
- only `QUEUED`/`PREPARING` (proven pre-submit) are automatically restart-recoverable;
- `DISPATCHING` is written synchronously immediately before the external call;
- `SUBMITTED` portably means “`BackendLike.send` returned successfully”; any native turn/thread
  reference is optional metadata, not part of the cross-backend acknowledgement definition;
- a crash/timeout in `DISPATCHING` becomes `DELIVERY_UNKNOWN` and is never automatically replayed;
- terminal states and `DELIVERY_UNKNOWN` are never submitted again.

Codex returns a native turn id only *after* `turn/start`; Claude's SDK `query(message)` accepts no
Orchestra delivery key in the current backend protocol. Therefore a process can die after external
acceptance and before SQLite records `SUBMITTED`. Replaying may create two turns; refusing replay may
create zero if the provider never accepted. A local database cannot distinguish those outcomes.
[C6][C7]

Thus H4 is **REFUTED**. “Exactly one model turn across timeout, retry, and service restart” is
achievable for client timeout/retry and for restart in the proven pre-submit states. Across the
external commit-point window, the honest guarantee is at-most-once automatic submission plus visible
`DELIVERY_UNKNOWN`, unless every backend later exposes provider-side idempotency keyed by
`delivery_id` or a queryable receipt.

**Confidence: CONFIRMED** — tier 2 backend contracts plus the standard distributed commit-point
argument, corroborated by prior accepted project research #187. [C6][C7][P1]

### F9 — Reconciliation can preserve and improve the current no-resend contract

The MCP caller must generate `delivery_id` before the delivery POST and always return it with the
worker mapping. On a transport error it first GETs that id:

- row exists: return its exact status and a structured wait/inspect action; do not create a new
  logical delivery;
- row absent: retry the *same key and identical payload* (safe insert-or-read), never a new key;
- mismatch: fail with an idempotency conflict;
- `DELIVERY_UNKNOWN`: retain the current do-not-resend instruction and provide the status URI/id;
- `FAILED_BEFORE_SUBMIT`: expose a typed terminal result; a new execution attempt, if policy permits
  one, remains attached to the same logical delivery rather than inventing a new initial task.

This follows the already implemented merge-operation reconciliation pattern while making
`CHECK_DELIVERY_STATE` executable rather than advisory. [C1][C5]

**Confidence: CONFIRMED** — tier 2 local precedent; exact response field names remain Phase 2 work.

## Counter-evidence and limitations

1. **The measured 114 incidents show delivery, not universal no-duplicates.** They are no-retry
   cases and refute “task was missing”; they do not prove all current retry behavior is safe. The new
   oracle must force same-key concurrency/retry and count provider submissions.
2. **A `202` receipt is deliberately noncommittal.** It proves durable acceptance, not successful
   model execution. Status must distinguish queued, preparing, submitted, completed, failed, and
   unknown. [S1]
3. **Strict external exactly-once is unavailable today.** This is a limit of the present Claude,
   Codex, Grok, and OpenCode `BackendLike.send(message) -> None` contract, not an excuse to replay.
   A future provider receipt/idempotency API could strengthen the guarantee. [C6][C7]
4. **`manager.send` cancellation shielding is useful for ordinary sends.** Removing it globally
   would create a regression. Initial durable delivery should add a dispatcher rather than weaken the
   existing owner-task behavior. [C3]
5. **#187 specified a broader universal ingress but did not implement its delivery ticket.** #311
   can reuse its verified state semantics without expanding into quota routing, Telegram, background
   jobs, or all ordinary messages. [P1]
6. **A status row is not proof that the provider ran.** The observable end effect must be a single
   logical `user_message` row, a single copy of the initial task in the backend-observed prompt, and
   a single backend `send`/native turn start in tests; intermediate `QUEUED`/`SUBMITTED` assertions
   alone are insufficient.

## Recommended protocol boundary for Phase 2

This is a research conclusion, not an implementation plan:

1. Add a narrow durable initial-delivery store/dispatcher modeled on `merge_operations`, scoped to
   spawn initial tasks.
2. Accept only client-supplied UUID delivery ids; persist a canonical payload hash and reject key
   reuse with different content/target.
3. Commit the delivery row before scheduling a runner and answer immediately with the delivery
   resource/status location.
4. Give the logical initial input an idempotent persistence identity tied to `delivery_id`. Before
   cold preparation, synchronously ensure exactly one immutable `user_message` row for that id; a
   recovery of `PREPARING` must reuse it and suppress `AgentSession.send`'s ordinary second log.
   Passing the same message in `exclude_history_users` must continue to exclude that one persisted
   row from reconstructed native history because it is supplied separately as the current prompt.
5. Put the fail-closed `DISPATCHING` transition at the production seam immediately before
   `backend.send`, and persist `SUBMITTED` immediately after the backend call returns successfully.
6. Recover `QUEUED`/`PREPARING` after restart. Never automatically replay `DISPATCHING`,
   `SUBMITTED`, `COMPLETED`, or `DELIVERY_UNKNOWN`.
7. Make `spawn_worker` reconcile using the same `delivery_id`; retain the worker mapping and
   structured `next_action` in every outcome.
8. Test the required failure points with events/fakes rather than wall-clock sleeps: blocked cold
   connect, response loss after commit, same-key retry, dispatcher reconstruction, commit failure,
   one immutable logical input, one backend-observed prompt copy, and a provider-send counter fixed
   at one.

The recovery matrix must cover both sides of every durable boundary:

| Last durable observation before process loss | Startup action | Required observable result |
|---|---|---|
| no delivery row (accept transaction failed) | none; same-key client retry allowed | no log, no wake, zero backend calls |
| `QUEUED`, runner never scheduled | claim once | one logical log, one prompt copy, one backend call |
| `PREPARING`, user log not yet committed | idempotently create/reuse log, resume preparation | one logical log, one prompt copy, one backend call |
| `PREPARING`, user log committed | reuse log, resume preparation without logging again | one logical log, one prompt copy, one backend call |
| `DISPATCHING`, no provider receipt persisted | `DELIVERY_UNKNOWN`, no replay | zero automatic backend calls after recovery + actionable no-resend status |
| provider accepted, process died before `SUBMITTED` commit | `DELIVERY_UNKNOWN`, no replay | zero automatic backend calls after recovery + actionable no-resend status |

## Affected files and consumers

Likely files for a later plan:

- `app/db.py` — delivery schema and atomic insert/read/state transitions;
- new focused module such as `app/initial_deliveries.py` — runner registry, state machine, recovery;
- `app/routes/sessions.py` — accepted-delivery and status endpoints (or a compatible durable mode on
  the current send endpoint);
- `app/mcp_stdio.py` — pre-generated id, reconciliation, structured result/next action;
- `app/manager.py` — likely a narrow delivery-aware entry point/context that preserves the existing
  per-session lock and `_auto_switch_before_delivery` while carrying the explicit delivery identity;
- `app/session.py` and `app/backend_protocol.py` — suppress the ordinary duplicate user log for a
  pre-persisted logical input, plus a narrow fail-closed before-submit/after-submit seam and optional
  native receipt; this distinguishes cold preparation from external ambiguity;
- `app/main.py` — startup recovery of pre-submit rows;
- focused API/MCP/session tests.

Consumers and compatibility constraints:

- only the initial `spawn_worker` task should enter the new protocol in #311; ordinary
  `send_message`, Telegram delivery, fan barriers, mailbox, restart inbox, and merge operations must
  retain their current behavior;
- the create-session response/mapping must remain available even when delivery reconciliation fails;
- current `delivery="unknown"`, `CHECK_DELIVERY_STATE`, and no-resend semantics must remain, now with
  a real id/status lookup;
- `202` means durable acceptance, not completed turn.

### #305 overlap

Task #305 is pending separately and may touch `app/manager.py`. No #305 branch or unmerged code was
read or imported. `SessionManager.send` owns both the per-session lock and
`_auto_switch_before_delivery`; a durable dispatcher must not bypass either by calling
`AgentSession.send` directly. Its current `(session_id, message)` signature also cannot carry an
explicit delivery identity or submit-transition callbacks. Phase 2 should therefore expect one
narrow manager entry point/context while leaving the ordinary method unchanged, and record that
small but real #305 merge-conflict risk. [C3]

## Risks and edge cases

- cancellation after DB commit but before runner scheduling: startup/on-demand recovery must find the
  `QUEUED` row;
- crash after the logical `user_message` is persisted but before backend connection: recovery must
  reuse the same immutable row and exclude it from imported history while sending it once as current
  input;
- two same-key requests racing: one insert and one runner only;
- same key reused for another worker, scope, sender, or task body: fingerprint conflict;
- restart during cold runtime connection: recover because provider submit has not begun;
- restart after `DISPATCHING`: mark unknown, never replay automatically;
- backend `send` raises after provider acceptance: unknown unless the backend supplies typed proof of
  pre-submit failure;
- session creation succeeds but delivery commit fails: return mapping plus retry-same-delivery action,
  never create another worker;
- recipient archived/deleted after acceptance: terminal pre-submit failure with visible status;
- active/busy recipient semantics: outside initial fresh-worker scope; do not accidentally route via
  mailbox/fan-barrier paths;
- payload hashing must use a canonical representation and cover target session/scope/task/sender;
- status retention/cleanup must not delete nonterminal or unknown evidence.

## Review decision gate

- **Affected files/consumers:** persistence, HTTP/MCP contract, session submit seam, startup recovery,
  and every `spawn_worker` caller; high-risk shared runtime and durable-state change.
- **Author runtime:** Codex/Sol.
- **Research acceptance:** falsify the acknowledgement-boundary diagnosis, the proposed state
  boundaries, the exactly-once limitation, and the claimed low-overlap seam for #305.
- **Mechanical evidence:** baseline SHA equality; targeted symbol/call-site trace; read-only live-DB
  counts/timestamps; `git diff --check`; source-reference and section checks.
- **Selected route:** mandatory Sol technical review under `codex-debate`; this is research prose, not
  high-risk code authored by Sol, so the cross-family code-review floor does not apply at Phase 1.

### Round 1 outcome

Sol inspected the cited manager/session path and returned `BLOCKING FINDINGS REMAIN`. The evidence
criterion passed: the artifact quotes `async with self.get_session_lock(session_id):`, which was not
included verbatim in the review request and is present in `app/manager.py`.

Both blockers were verified and accepted:

1. the first draft contradicted its own no-row requirement by naming a durable
   `FAILED_PRECOMMIT`; this revision removes that state, keeps failed acceptance absent, and reserves
   `FAILED_BEFORE_SUBMIT` for a committed delivery with typed proof that external submission never
   began;
2. the first draft counted backend calls but missed the earlier immutable `user_message` side
   effect; this revision requires an idempotent delivery-to-log relationship and three independent
   observables on recovery: one logical log, one backend prompt copy, and one backend call.

Suggestions were also accepted: the manager overlap is now explicit, the recovery matrix covers
both sides of the submit boundary, and `SUBMITTED` is defined portably as successful return from
`BackendLike.send` with an optional native reference. The follow-up verdict is recorded in
`review-research.md`.

### Round 2 outcome

The resumed Sol reviewer marked every prior item `FIXED`, found no new issue, and returned
`APPROVED`. Its evidence quote from the revised artifact was verified with the skill's normalized
whitespace check (`review_quote_verified=True`). This exhausts the two-round prose ceiling.

## Sources

### Direct measurements (tier 1)

- **[M1]** Read-only `/home/kesha/orchestra/data/orchestra.db` query and timestamp join performed
  2026-08-17. Exact counting rule and raw aggregate output are recorded above.

### Repository primary sources (tier 2)

- **[C1]** `app/mcp_stdio.py:498-586,806-950` and `tests/test_mcp_stdio.py:970-1100` — HTTP timeout,
  two-phase spawn, structured unknown/no-resend result.
- **[C2]** `app/routes/sessions.py:162-170,519-634` — current request schema and synchronous send route.
- **[C3]** `app/manager.py:237-255,1168-1182,1636-1648,2065-2110` and
  `app/session.py:849-920,1141-1390,1572-1631` — owner-task shielding, loading/recovery, cold connect,
  and provider-submit ordering.
- **[C4]** `app/db.py:418-430,523-548`; `app/mailbox.py:1-60`; `app/restart_inbox.py:1-90` — existing
  fact and at-least-once queue schemas/contracts.
- **[C5]** `app/db.py:692-732`; `app/merge_operations.py:316-416,1127-1217`;
  `app/mcp_stdio.py:1588-1680` — durable operation precedent and reconciliation.
- **[C6]** `app/backend_protocol.py:1-20`; `app/backend_codex.py:612-648`;
  `app/backend_claude.py:790-794`; corresponding Grok/OpenCode `send` methods — present provider
  submission contracts and post-request Codex turn id.
- **[C7]** `app/session.py:966-1068,1360-1382` — existing pre/post-submit shadow hook placement and
  deliberately fail-soft observer behavior.
- **[P1]** `docs/tasks/187/research.md:188-230` and `docs/tasks/187/plan.md:174-225` — prior accepted
  durable-ingress conclusion and unimplemented broader ticket.

### External primary sources (tier 2)

- **[S1]** RFC 9110 §15.3.3, “202 Accepted”: https://www.rfc-editor.org/rfc/rfc9110.html#section-15.3.3
- **[S2]** IETF HTTPAPI Idempotency-Key draft (expired work in progress, not a standard):
  https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-idempotency-key-header
- **[S3]** SQLite isolation and `BEGIN IMMEDIATE`: https://www.sqlite.org/isolation.html
- **[S4]** SQLite atomic commit: https://www.sqlite.org/atomiccommit.html

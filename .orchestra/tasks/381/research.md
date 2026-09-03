# #381 — structured pre-provider boundary for initial delivery

Phase: 1 — research and RED-oracle design only
Date: 2026-08-23
Baseline: `main` / `2abaed4e7fba4b1b8429eda7a85435e81d238b7c`

## Question

### Context

#311 made the task sent immediately after `spawn_worker` a durable resource. The current path is
`run_initial_delivery -> SessionManager.send_initial_delivery -> AgentSession.send ->
BackendLike.send`. A live delivery reached `DELIVERY_UNKNOWN` when the local variable `backend` was
`None`; provider acceptance had not begun.

### Change under test

Restore the structured distinction already present in #311 research but removed from its final
plan: an already committed delivery can fail **before** the provider-call boundary with known
outcome, or fail **after** that boundary with ambiguous outcome.

### Baseline

The current implementation commits `DISPATCHING` before it establishes that the object returned by
`_ensure_backend` is still a usable/current backend, and every later exception becomes
`DELIVERY_UNKNOWN`. There is no durable known-pre-provider failure state, and posting the same
accepted key again does not wake an existing row. [C1][C2]

### Measurable outcome

1. `backend is None` before provider invocation produces a known, explicitly retryable result and
   zero backend calls.
2. Explicit same-key retry after backend recovery produces one provider turn, while retaining one
   immutable `user_message` and one `user_log_id`.
3. A backend that accepts the task and then loses the transport remains unknown/quarantined and is
   never replayed.
4. `next_action` communicates retry permission through fields/codes, never exception text.

## Hypotheses considered

### H1 — the observation boundary belongs at the direct provider callsite

`AgentSession.send` owns the boundary because it is the last layer that prepares the outbound
message, receives the backend object, and directly invokes `BackendLike.send`. Persistence remains
owned by `app.initial_deliveries`, but `manager` cannot truthfully classify a failure inside
`AgentSession.send`.

**Falsifier:** any provider can accept the current task before `BackendLike.send(message)` is
invoked, or the manager can observe that invocation without a callback from the session.

**Result: CONFIRMED.** Backend construction/connect has no task payload; the current task first
crosses an external-submission API at `await backend.send(outbound_message)`. [C1][C3]

### H2 — exception class/message can distinguish known and ambiguous outcomes

For example, the live `AttributeError: 'NoneType' object has no attribute 'send'` could be declared
retryable by matching its type or text.

**Falsifier:** the same exception type/text can be raised by a backend only after it has performed
the provider-visible side effect.

**Result: REFUTED.** A fake backend can append the accepted prompt and then raise the identical
`AttributeError`; only whether the provider-call boundary was crossed distinguishes the outcomes.
The RED design below deliberately uses the same exception text on both sides. [M2]

### H3 — leaving known failures in `PREPARING` is sufficient

`PREPARING` is restart-replayable, so perhaps no new state/action is needed.

**Falsifier:** a live runner fails before dispatch, its task is removed, and neither status retry nor
same-key POST schedules it again.

**Result: REFUTED.** `_observe_runner` only removes/logs a failed task; it does not reschedule it.
`accept_initial_delivery` returns immediately for an existing matching row and calls
`ensure_delivery_runner` only for a newly inserted row. A live pre-provider failure would therefore
remain stuck until a process restart, while status says only `WAIT_FOR_DELIVERY`. [C2]

### H4 — `SessionManager.send_initial_delivery` should own classification

**Falsifier:** a known local failure occurs after manager locking/auto-switch but before the direct
provider call.

**Result: REFUTED.** The reproduced `None` occurs inside `AgentSession.send`; the manager sees only
the propagated exception and cannot know whether `BackendLike.send` was entered. [C1][C4]

## Measurements

### M1 — live incident, read-only DB and journal

No delivery or provider API was invoked. The live SQLite DB was opened read-only and the service
journal was read for the existing incident.

Delivery `01803356-19b8-43ec-b098-b39547c01b73` contains:

```text
state             provider_ref  error.code                outcome_unknown  retryable
DELIVERY_UNKNOWN  NULL          DELIVERY_OUTCOME_UNKNOWN  true             false
details.exception_type = AttributeError
message = Provider acceptance outcome is unknown: AttributeError: 'NoneType' object has no attribute 'send'
```

Before the failure timestamp, the child log contained exactly:

```text
logs_before_failure=3  user_messages=1  thread_receipts=0
turn_starts=0          model_texts=0     tool_calls=0
```

The journal gives the matching order (Europe/Berlin):

```text
13:19:48 POST /initial-deliveries -> 202; Codex managed state preparation started
13:26:57 POST /restart-cli -> 200
13:30:26 Codex managed state seeded
13:30:30 initial delivery runner failed at session.py:1288, await backend.send
         AttributeError: 'NoneType' object has no attribute 'send'
```

This sequence matches the code race: `_ensure_backend` stores `candidate` in `self._backend` and
awaits `candidate.connect()`, while `restart-cli` may concurrently disconnect and clear
`self._backend`; `_ensure_backend` then returns the mutable field rather than the connected local
candidate. [C1][C5]

**Confidence: CONFIRMED for the observed ordering and absence of provider-turn evidence** — tier 1
live DB/journal measurement. The supplied `session_id=null`, `total_turns=0`, and zero-token snapshot
is consistent with these independently observed zero thread/turn/model/tool rows.

### M2 — deterministic local race and current classification

A no-provider inline probe used a fake candidate whose `connect()` waited on an event. While it was
waiting, the probe called the real `_disconnect_backend()`, then allowed connect to return:

```text
after_disconnect_field_is_none= True
ensure_backend_returned_none= True
candidate_disconnect_calls= 1
```

A second isolated probe made `AgentSession._ensure_backend` return `None` and recorded only delivery
callbacks:

```text
exception_type= AttributeError
exception_text= 'NoneType' object has no attribute 'send'
events= ['before_submit', ('unknown', 'AttributeError')]
backend_ensure_calls= 1
```

Thus the current implementation crosses its durable ambiguity marker before discovering that no
provider callable exists. These probes used fakes only; they did not create a delivery, connect a
runtime, or call a provider.

**Confidence: CONFIRMED** — tier 1 deterministic reproduction on current `main`.

### M3 — #311 oracle gap on current main

```text
uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t2_'
.......... [100%]
10 passed, 5 deselected in 15.17s
```

The ten tests cover the manager lock, the successful bracket
`before_submit -> backend.send -> submitted`, restart of `QUEUED/PREPARING`, atomic logging,
quarantine of manually-created `DISPATCHING`, submitted recovery, cancellation after dispatch, and
startup order. None returns `None` from `_ensure_backend` or exercises a failure before the direct
provider call. [T1]

The existing MCP retry/status test also passes:

```text
uv run python -m pytest -q tests/test_mcp_stdio.py \
  -k 'test_t3_delivery_status_and_known_precommit_retry_keep_the_same_key or test_t3_spawn_unknown_delivery_preserves_mapping_and_forbids_resend'
.. [100%]
2 passed, 98 deselected in 10.18s
```

Its retry arm replaces `_api` with a fake and proves only the outgoing POST body. It never reaches
`accept_initial_delivery`, never changes a durable state, and never proves that an existing delivery
is scheduled. [T2]

**Confidence: CONFIRMED** — tier 1 named test commands plus direct test-source inspection.

## Findings

### F1 — #381 restores a contract that #311 research had already identified

#311 research explicitly distinguished failed acceptance (no row) from an already committed
delivery with typed proof that provider submission never began, naming the latter
`FAILED_BEFORE_SUBMIT`. Its research review marked that distinction fixed and correct. The final
plan later removed `FAILED_BEFORE_SUBMIT`; its reviewer described that removal as resolving an
“unreachable state”, but no replacement oracle covered live pre-provider runner failure. [P1][P2]

**Confidence: CONFIRMED** — tier 2 tracked task artifacts and their review history.

### F2 — the structured boundary is split between `AgentSession.send` and the delivery state owner

The exact observation point must be in `AgentSession.send`, after the backend result has been
structurally validated and a stable callable bound, and immediately before invoking that callable.
`app.initial_deliveries` must own the durable state transitions and derive status/action from those
states. `SessionManager` must retain locking/auto-switch but must not infer outcome from propagated
exceptions. `app.mcp_stdio` must consume the stored structured result, not classify exception text.
[C1][C2][C4]

**Confidence: CONFIRMED** — tier 1 reproduction plus tier 2 direct call-path ownership.

The required no-yield sequence is:

```text
backend = await _ensure_backend(...)
provider_send = structurally validate/bind backend.send
verify backend is still the current generation
delivery.before_provider_call()  # synchronous durable PREPARING -> DISPATCHING
await provider_send(outbound_message)
```

If validation/generation checking fails, the provider call has not begun. Once
`before_provider_call()` commits, every exception/cancellation is conservatively ambiguous unless a
backend later supplies stronger typed proof.

### F3 — a distinct durable known-failure state is necessary

Restore `FAILED_BEFORE_SUBMIT` for an accepted row whose provider call did not begin. It is distinct
from an acceptance-transaction failure, which still leaves no row. Its structured error contract is:

```json
{
  "code": "DELIVERY_NOT_SUBMITTED",
  "outcome_unknown": false,
  "retryable": true,
  "details": {
    "phase": "PRE_PROVIDER",
    "exception_type": "<diagnostic only>"
  }
}
```

Classification uses the durable/in-memory phase, never `exception_type` or `message`. The error text
may remain diagnostic. `run_initial_delivery` is the final owner: an exception while the row is
`PREPARING` becomes `FAILED_BEFORE_SUBMIT`; an exception while it is `DISPATCHING` becomes
`DELIVERY_UNKNOWN`. [C2][P1]

**Confidence: CONFIRMED** — the two states encode directly observable, mutually exclusive sides of
the measured seam.

### F4 — retry must be an atomic same-key claim, not merely another receipt read

For the existing `retry_initial_delivery(name, task, delivery_id)` workflow to become executable,
the same-payload POST must treat only `FAILED_BEFORE_SUBMIT` specially:

```text
FAILED_BEFORE_SUBMIT --BEGIN IMMEDIATE / same payload hash--> PREPARING
                    --commit--> ensure_delivery_runner(delivery_id)
```

The immutable `user_log_id` is retained and `error_json` cleared. Concurrent retries have one SQL
winner; losers see `PREPARING` and do not wake a second runner. A crash after the state commit but
before wake is recovered by the existing startup scheduling of `PREPARING`. Same-key POST in
`QUEUED`, `PREPARING`, `DISPATCHING`, `SUBMITTED`, or `DELIVERY_UNKNOWN` remains insert-or-read and
does not create a new execution. A different payload remains 409. [C2]

**Confidence: CONFIRMED for the state protocol; LIKELY for retaining the current MCP signature** —
the current tool already sends the canonical name/task/id payload, so no new public tool is required,
but Phase 2 review must check compatibility consumers.

### F5 — `next_action` must expose retry permission structurally

Use one exact shape for all states; callers must not parse prose:

| Delivery state | `code` | `tool` | `retryable` |
|---|---|---|---:|
| `QUEUED`, `PREPARING` | `WAIT_FOR_DELIVERY` | `delivery_status` | `false` |
| `FAILED_BEFORE_SUBMIT` | `RETRY_SAME_DELIVERY` | `retry_initial_delivery` | `true` |
| `DISPATCHING`, `DELIVERY_UNKNOWN` | `CHECK_DELIVERY_STATUS` | `delivery_status` | `false` |
| `SUBMITTED` | `NONE` | `null` | `false` |

Every non-null tool action carries an `arguments` object. Retry arguments preserve the original
`name`, `task`, and `delivery_id`; status arguments carry the same `delivery_id`. `message` remains
human explanation only. The stored `error.retryable/outcome_unknown` and
`next_action.retryable` must agree.

**Confidence: LIKELY** — this is a proposed compatibility extension. It preserves current action
codes/tools while removing the current `null`/prose ambiguity; exact JSON is to be frozen in Phase 2.

## Proposed RED oracles for Phase 2

All four belong in `tests/test_initial_deliveries.py` and should run with:

```text
uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t381_'
```

No oracle may call a live provider. Use a fake backend and the temporary `delivery_db` fixture.

### O1 — `test_t381_backend_none_before_provider_is_known_retryable`

- Reproduce the real race with a fake backend whose `connect()` blocks, call the real
  `_disconnect_backend()`, then release connect; alternatively assert the prerequisite separately
  and feed the resulting `None` through the real `AgentSession.send` delivery seam.
- Run the accepted/prepared delivery through `run_initial_delivery -> manager -> AgentSession.send`.
- Assert zero fake-backend `send` calls.
- Assert row state `FAILED_BEFORE_SUBMIT`, `error.code=DELIVERY_NOT_SUBMITTED`,
  `outcome_unknown=false`, `retryable=true`, and `details.phase=PRE_PROVIDER`.
- Current-main RED line: expected `FAILED_BEFORE_SUBMIT`, observed `DELIVERY_UNKNOWN`.

### O2 — `test_t381_retry_after_backend_recovery_submits_once_without_duplicate_input`

- Begin from O1's known-failure row; retain its `delivery_id`, payload hash, and `user_log_id`.
- Install a healthy fake backend; issue two concurrent same-key/same-payload explicit retries.
- Assert one transition claim/runner wake, then complete the runner.
- Assert exactly one healthy-backend `send(MESSAGE)`, state `SUBMITTED`, one immutable
  `logs.type='user_message'`, unchanged `user_log_id`, and exactly one current prompt copy.
- Current-main RED line: the existing-row branch returns a receipt without scheduling; healthy
  backend call count remains zero.

### O3 — `test_t381_provider_accept_then_transport_loss_stays_unknown_quarantined`

- Use a fake `send` that first appends `MESSAGE` to an external-acceptance list, then raises the
  **same exception type/text used by O1**.
- Assert one external acceptance, `DELIVERY_UNKNOWN`, `outcome_unknown=true`, `retryable=false`,
  and `details.phase=PROVIDER_CALL_STARTED`.
- Invoke recovery and same-key retry; assert no runner wake and the external count remains one.
- Current-main RED line: current `error.details` has only `exception_type`, so the required
  structural phase is absent. The state/no-replay shoulder should already pass and must remain.

### O4 — `test_t381_next_action_structurally_permits_only_known_safe_retry`

- Table-drive actual resources in `QUEUED`, `PREPARING`, `FAILED_BEFORE_SUBMIT`,
  `DISPATCHING`, `DELIVERY_UNKNOWN`, and `SUBMITTED`.
- Assert exact `code`, `tool`, `arguments`, and boolean `retryable` from the table in F5.
- Assert only `FAILED_BEFORE_SUBMIT` exposes `retry_initial_delivery`; neither error type nor message
  is inspected.
- Assert `error.retryable == next_action.retryable` for both failure states.
- Current-main RED line: no `FAILED_BEFORE_SUBMIT` action exists and current actions have no
  structural retry boolean/consistent `arguments` shape.

The same exception text in O1/O3 is the mutation-resistant guard against implementing
`if "NoneType" in str(error)` or any equivalent type/message classifier.

## Counter-evidence and limitations

1. The #311 T2 suite is green and already protects the conservative side: orphan or failed
   `DISPATCHING` must not replay. #381 must not weaken those tests. [M3]
2. `session_id`, turn, and token counters are useful incident evidence, but they are not a general
   classifier: they may be written after provider acceptance or changed by a later manual turn.
   Runtime classification must use the call-boundary phase at failure time, not retrospective
   telemetry.
3. A backend may accept and then raise any Python exception, including `AttributeError`; therefore
   no exception allowlist can prove pre-provider failure.
4. The underlying connect/restart race should also be hardened (`_ensure_backend` must not return a
   stale mutable field), but fixing that race alone is insufficient. Future local pre-provider
   failures would still need the durable known/retryable contract.
5. Existing historical `DELIVERY_UNKNOWN` rows must not be retroactively reclassified from current
   counters. Their original boundary evidence was lost; quarantine remains the safe interpretation.

## Affected files for a later phase

- `app/session.py` — validate/bind the current backend generation before the boundary; place the
  no-yield boundary immediately before the bound provider call; preserve ordinary-send behavior.
- `app/initial_deliveries.py` — restore `FAILED_BEFORE_SUBMIT`, typed errors, atomic explicit retry,
  authoritative phase-based failure finalization, and exact `next_action` mapping.
- `tests/test_initial_deliveries.py` — the four frozen behavioral oracles above.
- `app/mcp_stdio.py` — expected to remain unchanged if its existing same-key retry call and response
  pass-through accept the extended resource; Phase 2 must verify this rather than assume it.

No schema migration is required: `initial_deliveries.state` is unconstrained `TEXT` and
`error_json` already stores structured JSON. `app/manager.py`, routes, ordinary `/send`, Telegram,
mailbox, fan barriers, and provider backend implementations are outside the proposed change.

### Risks and edge cases

- concurrent retry claims and crash between claim commit and runner wake;
- cancellation on both sides of the boundary;
- backend generation replaced during a slow connect;
- failure while persisting `FAILED_BEFORE_SUBMIT` (must leave a safe `PREPARING` row, not claim an
  outcome that was not stored);
- same id with changed task/name/scope/sender remains a conflict;
- historical unknown rows remain quarantined;
- no duplicate immutable log or imported/current prompt copy on retry.

## Review decision gate

Affected consumers are shared session/message delivery, concurrency, durable state, and an external
MCP/API contract. This is high-risk under `codex-debate`; a Sol research review is the selected
route if an evidence artifact is permitted. The user's Phase 1 scope allows repository writes only
to this file and personal memory, so no separate review artifact or KB topic file is created in this
phase. This document includes the required adversarial counter-evidence and paired same-exception
oracle design.

**Model review: not run.** The canonical high-risk route is Sol, but `codex_review` requires a
separate durable review artifact under `docs/tasks/381/`; creating it would violate the user's exact
write scope. Mechanical checks completed instead: all four requested oracle cases are present, all
source paths/line ranges were opened on current main, both named baseline commands were run, the
live claim was cross-checked against DB plus journal, and `git diff --check` is clean. This is not
reported as an approved external verdict.

The same explicit write scope also forbids the normal Phase-1 append to `docs/kb/`; no KB file was
modified.

## Sources

- **[M1] Tier 1 measurement:** read-only
  `/home/kesha/orchestra/data/orchestra.db` queries for delivery
  `01803356-19b8-43ec-b098-b39547c01b73`, plus `journalctl -u orchestra` for
  2026-08-23 13:19:40–13:30:35 Europe/Berlin.
- **[M2] Tier 1 measurement:** two inline fake-only `uv run python` probes on current main: concurrent
  connect/disconnect return value, and `AgentSession.send(delivery=...)` with backend `None`.
- **[M3] Tier 1 measurement:** named pytest outputs recorded above.
- **[C1] Tier 2 primary source:** `app/session.py:1210-1310,1719-1784` — backend preparation,
  current boundary, failure handling, and mutable-field return.
- **[C2] Tier 2 primary source:** `app/initial_deliveries.py:24-44,113-188,304-377,380-461` — actions,
  existing-row acceptance, unknown transition, runner observation, and recovery.
- **[C3] Tier 2 primary source:** `app/backend_protocol.py:1-16` — `BackendLike.send(message)` is the
  provider submission interface.
- **[C4] Tier 2 primary source:** `app/manager.py:1017-1044` — manager lock/auto-switch and delivery
  delegation.
- **[C5] Tier 2 primary source:** `app/routes/sessions.py:776-784` and
  `app/session.py:4344-4374` — concurrent `restart-cli` disconnect path.
- **[T1] Tier 2 primary source:** `tests/test_initial_deliveries.py:282-597` — complete current #311
  T2 oracle set.
- **[T2] Tier 2 primary source:** `tests/test_mcp_stdio.py:1293-1354` — mock-only retry/status test.
- **[P1] Tier 2 primary source:** `docs/tasks/311/research.md:230-280` and
  `docs/tasks/311/review-research.md:17-30,85-101` — accepted distinction between no-row acceptance
  failure and committed `FAILED_BEFORE_SUBMIT`.
- **[P2] Tier 2 primary source:** `docs/tasks/311/plan.md:58-94` and
  `docs/tasks/311/review-plan.md:95-108` — final state machine and explicit removal of
  `FAILED_BEFORE_SUBMIT` without a live pre-provider-failure oracle.

## Phase-1 conclusion

The current result is a false ambiguity caused by placing `DISPATCHING` before structural backend
validation. The boundary must be observed at the direct callsite in `AgentSession.send`, while the
durable truth and retry claim belong to `app.initial_deliveries`. Restore
`FAILED_BEFORE_SUBMIT`, allow only an explicit atomic same-key retry from that state, and keep every
post-boundary failure in `DELIVERY_UNKNOWN`. Confidence: **CONFIRMED** for the diagnosis and boundary;
**LIKELY** for the exact additive `next_action.retryable` JSON shape pending Phase 2 freeze/review.

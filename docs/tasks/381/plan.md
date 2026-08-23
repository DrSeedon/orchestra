# #381 Phase 2 plan — structured initial-delivery outcome boundary

Research: `docs/tasks/381/research.md`
Definitive RED freeze: `621891aa0d44425610c564ac72f4b6c0c8b72726`
Superseded RED commits: `c9974241`, `1315c35ad124182fc854d863e63612ad1159d16f` — excluded.
The first narrowed two exception assertions from `BaseException` to `Exception`; the second lacked
the review-requested live-`DISPATCHING`, historical-unknown, and real-first-attempt shoulders. No
implementation was present in any freeze.

## Goal

Complete the contract omitted between #311 research and its final state machine: distinguish an
accepted delivery that provably failed before the provider call from a delivery whose provider
acceptance may already have occurred. The known-pre-provider case is explicitly retryable under the
same delivery identity; the ambiguous case remains quarantined and is never replayed.

## Scope and invariants

In scope:

- the initial-delivery path only:
  `run_initial_delivery -> SessionManager.send_initial_delivery -> AgentSession.send ->
  BackendLike.send`;
- structured pre-provider/ambiguous phase observation;
- durable `FAILED_BEFORE_SUBMIT` state and error envelope;
- atomic same-key/same-payload explicit retry claim;
- exact structured `next_action` retry permission;
- four #381 behavioral oracles frozen before implementation.

Required invariants:

1. The boundary is structural and immediately adjacent to `BackendLike.send`; no exception type or
   text decides the outcome.
2. `FAILED_BEFORE_SUBMIT` is durable and only an explicit retry with the same delivery id and
   canonical payload hash can atomically claim it.
3. `DISPATCHING` and `DELIVERY_UNKNOWN` never replay, including same-key POST and startup recovery.
4. A crash after `FAILED_BEFORE_SUBMIT -> PREPARING` commits but before runner wake is recoverable by
   the existing startup recovery of `PREPARING`.
5. The immutable `user_log_id`, logical `user_message`, current backend prompt, and provider call
   each occur once across retry.
6. Existing #311 T2/T3 oracles remain green.
7. Historical `DELIVERY_UNKNOWN` rows are never reclassified from retrospective session counters.

Out of scope:

- ordinary `SessionManager.send`, `/api/sessions/{name}/send`, Telegram, mailbox, fan barriers,
  restart inbox, and merge operations;
- changing provider backend implementations or claiming provider-side exactly-once;
- schema migration or retrospective data repair;
- automatic retry loops, new retry tools/routes, or a replacement delivery id;
- editing any pre-existing #311 test, fixture, helper, test configuration, marker, or selection
  setting.

## State and call contract

```text
ABSENT -> QUEUED -> PREPARING
                       |
                       +-- local failure before provider call --> FAILED_BEFORE_SUBMIT
                       |                                           |
                       |            explicit same-key claim -------+
                       |                    (atomic, back to PREPARING)
                       |
                       +-- durable boundary immediately before provider_send --> DISPATCHING
                                                                               /            \
                                                        send returned --------+              +-- error/loss
                                                              |                                  |
                                                          SUBMITTED                       DELIVERY_UNKNOWN
```

`FAILED_BEFORE_SUBMIT` is not an acceptance-transaction failure. Failed initial insert/commit still
leaves no delivery row. It is an already accepted row with immutable `user_log_id` whose current
execution did not enter the provider call.

### Structural boundary

`AgentSession.send` keeps backend preparation outside the boundary. After `_ensure_backend` returns,
it binds `provider_send = getattr(backend, "send", None)` and requires both `backend is not None` and
`callable(provider_send)` before calling the production `delivery.before_submit()` hook. The
production hook remains no-yield: it synchronously commits `PREPARING -> DISPATCHING` before its
coroutine returns. The next provider operation is `await provider_send(outbound_message)`.

The slow-connect race is hardened at its other end too: after `candidate.connect()` returns,
`_ensure_backend` must reject a candidate that is no longer `self._backend` and must not return the
mutable owner field after a concurrent disconnect. That rejection is still before the delivery
boundary.

`run_initial_delivery` remains the durable finalizer:

- exception/cancellation with a `PREPARING` row and an un-crossed context becomes
  `FAILED_BEFORE_SUBMIT` and is re-raised;
- exception/cancellation with `DISPATCHING` becomes `DELIVERY_UNKNOWN` and is re-raised;
- an already terminal `SUBMITTED`/`DELIVERY_UNKNOWN` state is never rewritten;
- error type and message are diagnostic fields only.

Exact known-failure envelope:

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

Every non-orphan ambiguous error retains `DELIVERY_OUTCOME_UNKNOWN`, `outcome_unknown=true`, and
`retryable=false`, and adds `details.phase="PROVIDER_CALL_STARTED"`. Orphaned `DISPATCHING`
recovery carries the same phase because the durable boundary had already committed.

### Atomic explicit retry

Keep the current `retry_initial_delivery(name, task, delivery_id)` tool and acceptance POST. In
`accept_initial_delivery`, after the existing payload-hash equality check and under the existing
`BEGIN IMMEDIATE` transaction:

1. only a row in `FAILED_BEFORE_SUBMIT` may be claimed;
2. the SQL winner changes it to `PREPARING`, clears `error_json`, preserves `user_log_id`, and
   commits;
3. only that winner calls `ensure_delivery_runner(delivery_id)` after commit;
4. concurrent losers observe `PREPARING` and return the same resource without a second wake;
5. a wake exception occurs after commit, so startup recovery later schedules the `PREPARING` row;
6. any changed message/name/scope/sender changes the canonical hash and remains 409;
7. matching rows in every other state remain insert-or-read and are not scheduled.

### Exact `next_action` structure

Every stored resource returns a non-null `next_action` object with exactly these keys:

```text
code, tool, arguments, retryable, message
```

`message` is non-empty human explanation only and is never parsed. Structural fields are:

| State | `code` | `tool` | `arguments` | `retryable` |
|---|---|---|---|---:|
| `QUEUED`, `PREPARING` | `WAIT_FOR_DELIVERY` | `delivery_status` | `{"delivery_id": id}` | `false` |
| `FAILED_BEFORE_SUBMIT` | `RETRY_SAME_DELIVERY` | `retry_initial_delivery` | `{"name": worker_name, "task": message, "delivery_id": id}` | `true` |
| `DISPATCHING`, `DELIVERY_UNKNOWN` | `CHECK_DELIVERY_STATUS` | `delivery_status` | `{"delivery_id": id}` | `false` |
| `SUBMITTED` | `NONE` | `null` | `{}` | `false` |

For `FAILED_BEFORE_SUBMIT` and `DELIVERY_UNKNOWN`, `error.retryable` equals
`next_action.retryable`.

## Implementation map

### `app/session.py`

- `AgentSession._ensure_backend`: after connect, fail if `candidate` is no longer the current
  backend; return the validated local candidate, never a concurrently-cleared mutable field.
- `AgentSession.send`: bind and validate `provider_send` before `delivery.before_submit`; keep the
  durable hook directly adjacent to `await provider_send(outbound_message)`; preserve existing
  status reset, fact acknowledgement, history exclusion, handoff, ordinary sends, and cancellation
  behavior.

### `app/initial_deliveries.py`

- `_next_action`: produce the exact table above for all states.
- `accept_initial_delivery`: atomically claim only matching `FAILED_BEFORE_SUBMIT`, schedule only the
  winner after commit, and preserve existing insert-or-read/conflict behavior elsewhere.
- add `_not_submitted_error` and `mark_initial_delivery_failed_before_submit` restricted to
  `PREPARING`.
- `_unknown_error`: add structural phase without weakening quarantine.
- `InitialDeliveryContext` / `run_initial_delivery`: finalize from the crossed durable phase, not
  from exception text; re-raise the underlying failure after persistence.
- `recover_initial_deliveries`: retain current `QUEUED/PREPARING` recovery and
  `DISPATCHING -> DELIVERY_UNKNOWN`; never schedule `FAILED_BEFORE_SUBMIT` until explicit retry.

### Expected unchanged files

- `app/manager.py`: the #311 lock/auto-switch sibling is already correct.
- `app/mcp_stdio.py`: current retry sends the same name/task/id payload and status passes the
  resource through. Phase 3 verifies this against #311 T3 rather than changing it speculatively.
- `app/db.py`: `state` is unconstrained `TEXT` and `error_json` already stores structured JSON; no
  migration is needed.

## What not to touch

- Do not edit any test, fixture, helper, `conftest.py`, test configuration, marker, or test-selection
  setting after the definitive RED commit.
- Do not classify `AttributeError`, `NoneType`, transport wording, or any other exception string.
- Do not reclassify historical `DELIVERY_UNKNOWN` rows.
- Do not schedule `FAILED_BEFORE_SUBMIT` during startup or matching receipt reads.
- Do not add automatic retry, a second POST, a new id, or a provider-specific receipt contract.
- Do not change ordinary sends or the manager lock/auto-switch path.

## Review decision inputs

- **Affected files/consumers:** planned `app/session.py` and `app/initial_deliveries.py`; consumers are
  shared session/message delivery, backend lifecycle concurrency, durable delivery status,
  same-key MCP retry, and startup recovery.
- **Author metadata:** `gpt-5.6-sol`, Codex runtime, from the live `sessions` row for
  `fix-initial-delivery-class`; role `full-cycle`, pipeline `default`.
- **Exact AC:** the three ticket commands below become green; #311 T2 remains `10 passed`; #311 T3
  remains `9 passed`; no non-#381 oracle is changed;
  `git diff 621891aa0d44425610c564ac72f4b6c0c8b72726 -- tests/test_initial_deliveries.py`
  stays empty through Phase 3.
- **Named checks observed before review:** #381 combined command exits 1 with five assertion
  failures; #311 T2 exits 0 (`10 passed, 10 deselected`); #311 T3 exits 0
  (`9 passed, 91 deselected`).
- **Risk floor / route:** high-risk shared message delivery, concurrency, persistence state, and
  external structured contract; direct Sol plan review under `codex-debate`, with one permitted
  resume after Round 1 changed the frozen oracle and plan.

Exact legacy commands:

```text
uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t2_'
uv run python -m pytest -q tests/test_mcp_stdio.py -k 'test_t3_'
```

## Plan review resolution

Sol Round 1 returned `NEEDS WORK` with four suggestions and no architecture blocker. All four were
accepted and the oracle was refrozen:

- matching same-key POST is now exercised while the row is still `DISPATCHING`, with zero wake;
- an independently seeded historical `DELIVERY_UNKNOWN` envelope is compared byte-for-byte after
  recovery and matching receipt reads;
- T2 now executes a real first pre-provider failure and a real healthy `AgentSession.send` retry,
  rather than manually creating only the failed state;
- exact #311 T2/T3 commands are included above and in ticket AC.

The definitive follow-up review evidence is `docs/tasks/381/review-plan.md`.

## Tickets

### T1 — Place and persist the structural provider-call boundary

- Files: `app/session.py`, `app/initial_deliveries.py`
- Test: `tests/test_initial_deliveries.py::test_t381_backend_none_before_provider_is_known_retryable`
  and
  `tests/test_initial_deliveries.py::test_t381_provider_accept_then_transport_loss_stays_unknown_quarantined`
  — committed RED in `621891aa0d44425610c564ac72f4b6c0c8b72726`
- Command: `uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t381_backend_none_before_provider_is_known_retryable or test_t381_provider_accept_then_transport_loss_stays_unknown_quarantined'`
- RED: exit 1, 3 failed; first failing assertion:
  `AssertionError: #381 pre-provider failure must stay known and retryable`
- AC: the exact command is green; backend `None` and the same `AttributeError` raised before the
  call produce `FAILED_BEFORE_SUBMIT/PRE_PROVIDER`, while the same error after one provider side
  effect produces `DELIVERY_UNKNOWN/PROVIDER_CALL_STARTED`; matching `DISPATCHING` and
  `DELIVERY_UNKNOWN` receipt reads never wake a runner; a historical unknown envelope is unchanged;
  `uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t2_'` remains green.
- blocked-by: none

### T2 — Atomically retry one known-not-submitted delivery

- Files: `app/initial_deliveries.py`
- Test: `tests/test_initial_deliveries.py::test_t381_retry_after_backend_recovery_submits_once_without_duplicate_input`
  — committed RED in `621891aa0d44425610c564ac72f4b6c0c8b72726`
- Command: `uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t381_retry_after_backend_recovery_submits_once_without_duplicate_input'`
- RED: exit 1, 1 failed; failing assertion:
  `assert failed["state"] == "FAILED_BEFORE_SUBMIT"` (actual `PREPARING`).
- AC: the exact command is green; the real first attempt fails before prompt preparation/provider
  call and becomes known-retryable; a changed payload remains 409; two concurrent matching retries
  have one claim/wake attempt; a simulated lost wake leaves `PREPARING` and startup recovery
  schedules it once; the recovered real session prepares and sends one prompt; state ends
  `SUBMITTED`; `user_log_id` and the sole user log are unchanged;
  `uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t2_'` remains green.
- blocked-by: T1

### T3 — Make retry permission machine-readable in every state

- Files: `app/initial_deliveries.py`
- Test: `tests/test_initial_deliveries.py::test_t381_next_action_structurally_permits_only_known_safe_retry`
  — committed RED in `621891aa0d44425610c564ac72f4b6c0c8b72726`
- Command: `uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t381_next_action_structurally_permits_only_known_safe_retry'`
- RED: exit 1, 1 failed; failing assertion:
  `assert action.get("arguments") == arguments` (actual `None` for `QUEUED`).
- AC: the exact command is green; every state exposes exactly
  `code/tool/arguments/retryable/message`; only `FAILED_BEFORE_SUBMIT` names
  `retry_initial_delivery` with `retryable=true`; both failure states agree with
  `error.retryable`; `uv run python -m pytest -q tests/test_mcp_stdio.py -k 'test_t3_'` remains
  green.
- blocked-by: T2

## Frozen RED evidence

Definitive oracle commit:

```text
621891aa0d44425610c564ac72f4b6c0c8b72726
```

Combined command:

```text
uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t381_'
FFFFF [100%]
5 failed, 15 deselected in 11.25s
exit 1
```

First failing line:

```text
E       AssertionError: #381 pre-provider failure must stay known and retryable
```

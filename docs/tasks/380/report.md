# #380 delivery receipts

## Chain ledger

| Worker | Branch | Head | Selector | Result |
|---|---|---|---|---|
| `impl380-t1` | `task-380/impl380-t1` | `4e5cb061` | `...pytest -q tests/test_message_delivery_receipts_380.py -k 'test_t380_r1_'` | `5 passed, 17 deselected` |
| `impl380-t2` | `task-380/impl380-t2` | `26315067` | `...pytest -q tests/test_message_delivery_receipts_380.py -k 'test_t380_r2_'` | `1 passed, 21 deselected` |
| `impl380-t3` | `task-380/impl380-t3` | `071a9f09` | `...pytest -q tests/test_message_delivery_receipts_380.py -k 'test_t380_r3_'` | `2 passed, 20 deselected` |
| `impl380-t4` | `task-380/impl380-t4` | `ed2db1d3` | `...pytest -q tests/test_message_delivery_receipts_380.py -k 'test_t380_r4_'` | `2 passed, 20 deselected` |
| `impl380-t5` | `task-380/impl380-t5` | `a9ce549b` | `...pytest -q tests/test_message_delivery_receipts_380.py -k 'test_t380_r5_'` | `3 passed, 19 deselected` |
| `impl380-t6` | `task-380/impl380-t6` | `3519598a` | `...pytest -q tests/test_message_delivery_receipts_380.py -k 'test_t380_r6_'` | `1 passed, 21 deselected` |
| `impl380-t7` | `task-380/impl380-t7` | `a0fa3cf6` | `...pytest -q tests/test_message_delivery_receipts_380.py -k 'test_t380_r7_'` | `8 passed, 14 deselected` |
| `fix380-final-gate` | `task-380/fix380-final-gate` | `138bbfa2` | `...pytest -q tests/test_mcp_stdio.py::test_protocol_failure_is_typed_and_success_uses_same_shape tests/test_routes_surface.py::test_route_surface_snapshot` | `2 passed` |

## Review gate

- Changed file/consumers: `app/session.py` (`AgentSession.send`), consumed by `SessionManager.send_message_delivery`, `send_initial_delivery`, and legacy `send`.
- Author runtime: Codex-managed session `7a78b17b-fd3e-424c-a19e-547525838862`; model metadata is not present in this worktree.
- AC: keyed running delivery steers through `backend.send`, brackets `DISPATCHING`/`SUBMITTED`, skips quota/new turns/duplicate user logs/volatile pending; initial and legacy paths stay unchanged.
- Named checks: R2 `1 passed, 21 deselected`; R1 `5 passed, 17 deselected`; #381 `5 passed, 15 deselected`; initial regressions `1 passed`; manager running `1 passed, 170 deselected`; session running `3 passed, 214 deselected`.
- Route: Sol technical review (shared session/message-delivery concurrency surface).
- Review: gpt-5.6-sol, one round, `APPROVED`; no findings. Temporary review output was read and removed because the approved file scope permits only this report. Evidence quote: `await delivery.before_submit()`.

## Pre-mortem checks

- Duplicate durable user log → R2 checks one `user_message` row and no async user-log call.
- Successful steer entering volatile pending → R2 checks `_pending_messages == []` after backend return.
- Quota admission or new turn on keyed steer → R2 asserts admission was not awaited and session remains `RUNNING`.
- Initial idle-only path regressing → #381 initial-delivery tests and review regression pass.
- Legacy running send/queue behavior regressing → manager and session running selectors pass.

## T3 implementation review

- Changed files/consumers: `app/mcp_stdio.py` (`send_message`, `message_delivery_status`, timeout reconciliation) and `app/routes/sessions.py` (`GET /api/message-deliveries/{delivery_id}`); consumers are MCP callers and authenticated message-delivery status clients.
- Author runtime: Codex session `01a030d5-e331-78e3-9cb9-009be9cce7bd`; model metadata is unavailable in this worktree.
- AC: preserve the two required `send_message` arguments; generate one pre-POST UUID when blank; carry it through POST and exactly one reconciliation GET; return accepted text for a matching receipt; raise same-id `AMBIGUOUS` with a no-fresh-key warning when reconciliation is unavailable; expose exact GET status tool; preserve cross-parent warnings.
- Named checks: R3 `2 passed, 20 deselected`; R1 `5 passed, 17 deselected`; R2 `1 passed, 21 deselected`; `tests/test_mcp_stdio.py -k 'api_ or send_message'` `12 passed, 91 deselected`; receipt cross-parent warning probe `OK`; `py_compile` passed.
- Route: Sol technical review, one round (`gpt-5.6-sol`); `APPROVED`, no blocking findings. Suggestion at `app/mcp_stdio.py:1134` was fixed in `071a9f09`; reviewer evidence quote: `details["reconciliation"] = reconciliation`. Review output was removed after reading because the permitted report is the only persistent review artifact.

## T3 pre-mortem checks

- Duplicate POST or fresh UUID after timeout → R3 asserts POST/GET sequence is exactly one same-id pair and blank-key generation is exactly once.
- False acceptance after unavailable reconciliation → R3 asserts `ApiToolError.result.acceptance == "AMBIGUOUS"`, same id, and no-fresh-key warning.
- Legacy warning loss on keyed receipt → existing send-message regressions plus a direct receipt probe assert the cross-parent warning remains present.
- Status authorization leakage → the additional R6 probe passed owner status and unrelated-source/internal-token denial before stopping at the pre-existing operator keyed-POST `403` vs expected `202`, outside T3 scope.

## T4 implementation and review gate

- Changed files/consumers: `app/message_deliveries.py` (`accept_message_delivery` same-key retry and `recover_message_deliveries`, consumed by keyed POST and the per-target runner); `app/main.py` (`lifespan`, consumed at process startup).
- Author runtime: current session metadata is unavailable in this worktree; implementation head is `ed2db1d3` on `task-380/impl380-t4`.
- AC: only matching same-key/hash `FAILED_BEFORE_SUBMIT` claims `PREPARING` and wakes once; changed hashes conflict; recovery schedules only `QUEUED/PREPARING` once per target; startup runs message recovery after auto-resume and initial-delivery recovery and before background sources.
- Named checks: exact R4 `2 passed, 20 deselected`; R1–R3 `8 passed, 14 deselected`; initial plus review regressions `21 passed`; API/manager compatibility `4 passed`; session running-steer `2 passed, 215 deselected`; startup-order test `1 passed`; source-order probe `startup order OK`.
- Review: `none — Codex unavailable`; this shared message-delivery/persistence/lifecycle surface would route to Sol when Codex is available.
- Additional boundary probe: R5 selector is red `3 failed, 19 deselected` on T3's pre-existing missing `next_action`/orphan-`DISPATCHING` quarantine behavior; no T4 acceptance path fails and those T5 files/behaviors were not changed.

## T4 pre-mortem checks

- Same-key changed payload cannot replay or mutate the receipt → existing R1 conflict shoulders plus the R4 exact retry path passed.
- Concurrent/repeated wake cannot duplicate provider work → R4 asserts one scheduled target, one user log, one provider attempt, and no scheduling on repeated recovery.
- Recovery cannot replay terminal states → recovery query is restricted to `QUEUED/PREPARING`; R4 repeated-recovery checks remained green and R5 terminal recovery tests were not changed by this ticket.
- Startup ordering cannot move message recovery behind background sources → startup-order test and the source-order probe both passed.
- Existing initial/legacy consumers cannot regress → `21` initial/review tests, `4` API/manager compatibility tests, and `2` session running-steer tests passed.

## T5 implementation and review gate

- Changed files/consumers: `app/message_deliveries.py` (`_resource`, `mark_message_delivery_unknown`, and `recover_message_deliveries`), consumed by keyed POST/status resources, the per-target runner, and startup recovery; `app/manager.py` and `app/session.py` are unchanged because their existing callbacks already re-raise the provider exception after durable classification.
- Author runtime: Codex-managed worker session; model metadata is unavailable in this worktree. Implementation head: `a9ce549b` on `task-380/impl380-t5`.
- AC: provider exception/cancellation after `before_submit()` remains one-attempt `DELIVERY_UNKNOWN`, preserves one user row, re-raises the original error, exposes `CHECK_DELIVERY_STATUS` with `retryable=false`, and never replays; startup atomically quarantines every orphan `DISPATCHING` with `PROVIDER_CALL_STARTED` and schedules none; `SUBMITTED`/`DELIVERY_UNKNOWN` remain terminal and `FAILED_BEFORE_SUBMIT` remains a barrier.
- Named checks: exact R5 `3 passed, 19 deselected`; R1–R4 combined `10 passed, 12 deselected`; #381 provider-accept-then-loss/next-action `5 passed, 15 deselected`; startup recovery checks `6 passed, 14 deselected`.
- Route: one targeted Sol technical pass (`gpt-5.6-sol`) on the shared message-delivery persistence/concurrency diff; independent evidence is the frozen R5 selector plus the reviewer quote `"WHERE state='DISPATCHING'"` and `"retryable": False` from `/tmp/codex-review-380-t5.md`.
- Review: `APPROVED`, no findings.

## T5 pre-mortem checks

- Provider-loss recovery could duplicate an external attempt or user row → exact R5 cancellation/exception arms passed with one attempt and one user row.
- Startup could replay an orphan or wake a later receipt → exact orphan R5 recovery passed with `scheduled == []`; startup checks passed.
- A late error after successful submit could downgrade a terminal receipt → `mark_message_delivery_unknown` guards `SUBMITTED` and existing R1–R4 combined checks stayed green.
- Status metadata could accidentally permit resend → exact R5 asserted `CHECK_DELIVERY_STATUS` and `retryable is False`; #381 next-action checks passed.

## T6 implementation

- Changed files/consumers: `app/routes/sessions.py` (`send_message` keyed authorization/target resolution and delivery-accept rejection; `GET /api/message-deliveries/{delivery_id}` unchanged), `app/message_deliveries.py` (`DELIVERY_UNKNOWN` direct next action); consumers are MCP-proof callers, authenticated dashboard operators, direct-delivery status clients, and durable receipt persistence.
- AC: MCP proof remains bound to the source session row/name/scope/task; cookie operators may POST/status with empty source session and `operator:<user>` principal; same-scope target wins, authorized orchestrators may address one unique cross-project target by immutable session/scope/task/generation, ambiguous/missing/archived targets return known 409/404 outcomes, internal-token-only requests remain denied, and an uncommitted SQLite acceptance returns 503 `DELIVERY_ACCEPT_REJECTED` with no row/log. Direct `DELIVERY_UNKNOWN` now points to `message_delivery_status`.
- Implementation head/branch: `3519598a` on `task-380/impl380-t6`.
- Named checks: exact R6 `...pytest -q tests/test_message_delivery_receipts_380.py -k 'test_t380_r6_'` → `1 passed, 21 deselected`; R1–R5 combined → `13 passed, 9 deselected`; auth/proof → `18 passed`; direct status/legacy → `2 passed, 20 deselected`; MCP send/status → `2 passed, 101 deselected`; `py_compile` → passed.

## T6 pre-mortem checks

- Operator identity could leak a caller session or render source prefix → exact R6 asserts `source_session_id` empty, `source_principal` starts with `operator:`, and operator POST/status pass.
- Cross-project name lookup could bind the wrong recipient or accept ambiguity → exact R6 asserts unique target session/scope/task and `TARGET_NAME_AMBIGUOUS` 409.
- Archived/missing target could be reported as an unknown provider outcome → exact R6 asserts 404 with `outcome_unknown=false`.
- SQLite acceptance rollback could leave a phantom receipt/log or be reported as accepted → exact R6 forced trigger asserts 503 `DELIVERY_ACCEPT_REJECTED`, `NOT_COMMITTED`, row count, and user-log absence.
- Existing direct unknown recovery could point callers at the initial-delivery tool → R1–R5 combined and R5 next-action assertions pass with `message_delivery_status`.

- Review gate: changed files/consumers and AC are listed above; author runtime is Codex-managed (model metadata unavailable in this worktree). Targeted Sol review, 3 rounds on the executable diff: round 1 had no formal verdict and found target-resolution P2; round 2 found and fixed the SQLite verification blocker; round 3 returned `APPROVED — clean final re-review`. Evidence quote: `"details": {"commit_state": "VERIFICATION_FAILED"}`; reviewer ran R6 `1 passed, 21 deselected` and R1–R5 `13 passed, 9 deselected`.

## T7 implementation and review gate

- Changed files/consumers: `app/message_deliveries.py` (`_next_target_delivery`, per-target runner/observer, and typed pre-submit failure), consumed by keyed acceptance, startup recovery, and lifecycle wakes; `app/manager.py` (`SessionManager.send_message_delivery` generation recheck), consumed by the direct-delivery runner; `app/session.py` (durable delivery parking and turn/Codex/Claude compact completion wakes), consumed by keyed direct delivery, legacy sends, initial delivery, and both compact runtimes.
- Author runtime/model: Codex worker session `impl380-t7`, `gpt-5.6-sol` from the live session registry.
- AC: SQLite commit order is provider FIFO under competing accepts/runners; the oldest non-`SUBMITTED` receipt is the HOL authority; empty-head teardown rechecks durable state; task-generation mismatch is typed before provider work; direct receipts stay durable through no-inject, deferred interrupt, and both compact paths; initial/legacy pending behavior is unchanged.
- Named checks: exact R7 `8 passed, 14 deselected` in three consecutive runs; frozen R1-R7 file `22 passed`; prior R1-R6 `14 passed, 8 deselected`; compact `67 passed, 150 deselected`; #385 deferred interrupt `2 passed, 215 deselected`; manager locks/generation `6 passed, 185 deselected`; initial #311/#381 `21 passed`; no-inject/legacy `7 passed, 318 deselected`; `py_compile` passed.
- Route: one targeted Sol technical pass because shared persistence, queue/lock concurrency, message delivery, and lifecycle finalizers set the high-risk floor.
- Implementation head/branch: `a0fa3cf6` on `task-380/impl380-t7`.
- Review: one targeted `gpt-5.6-sol` round found no actionable defects and quoted `_target_runner_tasks: dict[str, asyncio.Task[bool]] = {}`, verified against the changed file. The wrapper reported `FAILED` only because the response omitted a `## Verdict` heading and reported zero usage; the substantive clean response and evidence are preserved here, and the unchanged diff was not rerun merely for formatting.

## T7 pre-mortem checks

- A receipt committed between the runner's empty read and observer teardown could strand forever → the frozen boundary test gates that exact interleaving and reaches `SUBMITTED`; three consecutive complete R7 runs passed.
- A `DELIVERY_UNKNOWN` or `FAILED_BEFORE_SUBMIT` head could let a later receipt overtake → `_next_target_delivery` selects the oldest non-`SUBMITTED` row, and the R7 HOL case leaves the tail `QUEUED` with zero provider attempts.
- A compact/no-inject/deferred-interrupt receipt could enter volatile pending state, duplicate its user row, or dispatch twice → R7 asserts `PREPARING`, empty `_pending_messages`, one user row, and one later provider attempt; #385 `2 passed` and compact `67 passed` cover the existing lifecycle consumers.
- A target task/branch generation change could auto-switch or reach the provider first → the R7 generation case records `TARGET_TASK_CHANGED` with `outcome_unknown=false`, makes no session send, and the manager lock selector passed 6 cases.
- Initial #311/#381 or legacy no-inject behavior could change while direct contexts gain parking → all 21 initial-delivery checks and 7 no-inject/legacy checks passed.

## Final parent reconciliation

### Outcome

- Keyed MCP/REST direct sends now return durable HTTP 202 ownership before target load/admission/
  dispatch. Blank-key REST remains the original synchronous path.
- UUID spelling is canonicalized before MCP POST/GET and SQLite identity; matching retries return
  the same receipt, while payload, target-generation, or route-target changes conflict.
- One transactional user row is reused through idle start/running steer. Provider-call ambiguity is
  fail-stopped, orphan `DISPATCHING` is quarantined, and `FAILED_BEFORE_SUBMIT` is the only same-key
  retry state.
- Per-target `accept_seq` FIFO, HOL barriers, task-generation checks, empty-head runner rechecks, and
  no-inject/#385/Codex-compact/Claude-compact durable wakes are active.
- Receipts survive target hard deletion. Existing databases with the pre-review CASCADE schema are
  rebuilt under one explicit savepoint; `user_log_id` becomes NULL when its log is deleted.
- MCP timeout reconciliation performs one same-id GET. A malformed reconciliation error claiming
  `method=POST` preserves the original typed POST error for legacy protocol compatibility.

### Files

- `app/db.py` — `message_deliveries` schema plus transactional FK migration (`+107`).
- `app/message_deliveries.py` — receipt/hash/state/FIFO/runner/recovery owner (`+505`).
- `app/routes/sessions.py` — keyed acceptance/auth/status/reconciliation branch (`+291/-1`).
- `app/manager.py` — locked, generation-bound direct delivery (`+32`).
- `app/session.py` — direct running/deferred semantics and lifecycle wake hooks (`+73/-3`).
- `app/mcp_stdio.py` — UUID generation/canonicalization, timeout GET reconciliation, status tool
  (`+138/-4`).
- `app/main.py` — ordered startup recovery (`+2`).
- `tests/route_surface_snapshot.json` — one owner-approved GET route entry (`+6`).
- `docs/tasks/380/test_review_regressions.py` — two post-ceiling mechanical regressions (`254` lines).
- Frozen `tests/test_message_delivery_receipts_380.py` is byte-identical to `c42163d9`.

### Descendant-chain proof

Before the single successful squash merge, these implementation heads were each proven by
`git merge-base --is-ancestor <head> 9177ad9d` and frozen as `preserve/380-t*` refs:

```text
T1 4e5cb061  T2 26315067  T3 071a9f09  T4 ed2db1d3
T5 a9ce549b  T6 3519598a  T7 a0fa3cf6  final T7 evidence 9177ad9d
```

The owner-approved compatibility descendant `8ff3ce49` is preserved as
`preserve/380-final-gate`. Final squash merge operation
`1c9fbd1d-5294-483f-8ee2-1174afdf949d` succeeded as parent commit `4def9dbe`.

### Final tests and probes

- Final lifecycle-reconciled run: frozen receipt suite plus post-review regressions
  `24 passed in 34.02s` (`22` frozen + `2` mechanical).
- Exact mapped gate (`test_db`, `test_manager`, `test_mcp_stdio`, frozen #380,
  `test_routes_surface`, `test_session`, `-m not live_probe`):
  final `608 passed in 306.74s`; the preceding post-fix control also passed
  `608 in 273.88s`.
- DB suite in the mapped gate: `93 passed`; standalone pre-savepoint run also recorded
  `93 passed in 94.88s`.
- Legacy/#311/#381/#385/auth/manager focused reconciliation before review:
  `21 + 5 + 13 + 4 passed` across the named commands in the Phase 3 transcript.
- Temporary DB probe: braced uppercase UUID -> canonical submitted receipt -> target hard delete ->
  uppercase hyphenless retry = one `ALREADY_ACCEPTED/SUBMITTED` row.
- Previous-schema probe: injected old CASCADE/NO ACTION table migrated without row/sequence loss;
  target FK removed, log FK `SET NULL`, target deletion preserved the receipt.
- HTTP lifecycle probe: same canonical key after target rename and deletion returns the stored
  receipt before target resolution; wrong route name returns known 409.
- Compile/diff checks: planned Python files compile; `git diff --check` clean.

### Required mutations

Each mutation was applied alone, produced the named RED, was restored with `touch`, and its selector
was rerun green:

| Mutation | Oracle RED |
|---|---|
| accept/202 without SQLite commit | R1 `4 failed, 1 passed` |
| same-key POST resets/wakes accepted work | R1 `1 failed, 4 passed` |
| replay `DISPATCHING`/`DELIVERY_UNKNOWN` | R5 `3 failed` |
| skip ambiguous HOL in FIFO query | R7 `1 failed, 7 passed` |
| omit target-generation comparison | R7 generation case `DID NOT RAISE` |
| place no-inject/#385 direct input in volatile pending | R7 two cases `2 failed` |
| drop MCP same-id GET reconciliation | R3 `2 failed` |

No mutation or backup file remains; the frozen oracle was never edited.

### Final review status

Fresh implementation Sol review ran three completed rounds in
`docs/tasks/380/review-impl.md`. Its last independent verdict remains **CHANGES REQUESTED** as
required by the owner; no fourth round was run. The owner authorized the two verified local fixes
after the ceiling:

1. one savepoint around old-table rename/create/copy/drop/index recreation, with rollback/retry
   regression;
2. receipt-first route-target mismatch -> known 409 before stored target substitution.

Mechanical post-ceiling evidence: `docs/tasks/380/test_review_regressions.py` -> `2 passed`; frozen
plus review regressions -> `24 passed`; post-fix mapped gate -> `608 passed`.

### Breaking changes / TODO

- Breaking: none for legacy no-key REST, old MCP processes, #311/#381 initial delivery, or #385
  deferred interrupt. Keyed response wording intentionally says accepted, not delivered.
- Deployment/restart/live-send verification was not performed and is not authorized by #380.
- TODO: none inside the approved implementation scope.

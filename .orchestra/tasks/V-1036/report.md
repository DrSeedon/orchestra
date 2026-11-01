# V-1036 — message delivery and quota queue visibility

## Result

Implemented in the supplied private copy. No service restart, deployment, git commit or push was performed. The platform should import the result into `task-V-1036/fix-delivery-visible` with a `V-1036` commit header.

- `app/mcp_stdio.py`: `_api` now returns accepted delivery receipts with `ok=true` even when they contain a durable `error`. Previously a `WAITING_QUOTA`/failed receipt was converted into `ApiToolError`, losing its identity and next action. Real HTTP/domain rejections still fail; rejection envelopes preserve a supplied delivery ID. Initial failure text includes the original error. Registered `list_pending_deliveries(target="")`, including read-only tool access; clarified spawn/cancel contracts.
- `app/message_deliveries.py` and `app/initial_deliveries.py`: initial failures use the existing durable failure-notice queue and immediately attempt a wake of the recorded sender. The original error text is included. Cancellation of an initial runner before submission is covered too. Initial ambiguous dispatches and orphaned direct deliveries report UNKNOWN, without claiming non-delivery. Recovery backfills old terminal failures missing notices. Notice revisions allow a retried delivery ID to fail loudly again; stable event IDs and conditional acknowledgment prevent replaying the same attempt or acknowledging a newer notice. Legacy delivered notices are adopted without replay. Repeated recording of the same failure remains idempotent.
- `app/quota_queue.py`: every newly created/refreshed WAITING_QUOTA error requires a delivery ID and carries it in structured fields and human-readable text with ETA. Receipts and queue entries expose an estimate, reset fallback, or explicit unknown time. Messages queued behind a quota-held message inherit its ETA. Old stored rows without ETA/ID details still render safely.
- `app/routes/sessions.py`: authenticated `GET /api/pending-deliveries?target=...` returns only the calling sender's WAITING_QUOTA/QUEUED direct and initial deliveries: `delivery_id`, target, creation time, first 80 characters, state, kind and ETA. The existing authenticated initial-cancellation fallback was already present in this copy and is now covered by tests. Initial cancellation is now idempotent, retains owner checks, and refuses PREPARING/later states.
- `app/manager.py`: role-aware admission for the resolved chosen model runs only when `planned_initial_turn=True`, before task allocation/binding, AgentSession construction or worktree creation. Creating an idle worker without an initial task does not read subscription admission. Closed gates return the existing typed quota refusal and hub hint. Available/unknown admission continues; orchestrator admission exemption remains. Delivery admission still rechecks a gate that closes after creation.

Canonical send failure state in this tree is `FAILED_BEFORE_SUBMIT` with error code `DELIVERY_NOT_SUBMITTED`; no direct-delivery writer uses a separate `FAILED` or `NOT_SUBMITTED` state. SUBMITTED and sender-requested CANCELLED are not failed deliveries. Existing direct-message failure, archive-target and sweeper paths remain responsible for their notifications. Recovery runs through the existing asynchronous failure-notice service; startup does not wait for an agent turn.

## Actual validation

The prescribed command was attempted offline:

```sh
UV_OFFLINE=1 uv run --frozen python -m pytest tests/test_delivery_visible_1036.py tests/test_mcp_delivery_visible_1036.py tests/test_quota_admission_e2e.py tests/test_message_delivery_failure_notices_741.py tests/test_quota_wait_queue.py tests/test_mcp_quota_gate.py tests/test_delivery_receipt_status_866.py -q
```

It exited 127: the installed uv entry is a remote forwarding shim with no uv executable or mapped project. This copy also lacks pytest, FastAPI, httpx, MCP dependencies and pipeline assets. No network install was attempted. A temporary local `.venv` was bootstrapped without pip solely to run stdlib checks and removed after validation; the tests did not run under system Python.

Completed checks:

1. `nice -n 15 .venv/bin/python -W error::RuntimeWarning -m unittest discover -s tests -p test_delivery_visible_1036.py -v` — **17 passed**, using the real delivery modules and repository SQLite schema in per-test databases below this task directory. Covers direct/initial failures, verbatim multiline errors, cancelled runners, ambiguous outcomes, failed wakes, concurrent drains, retry of the same ID, repeat failure recording, old rows, legacy delivered notices, lost wake acknowledgment, success/quota race, own/cross-scope queue visibility, 80-character previews, cancellation boundaries and ETA fallbacks.
2. `nice -n 15 .venv/bin/python .orchestra/tasks/V-1036/check_offline.py -v` — **6 passed**. Executes complete current MCP/route/spawn functions extracted with AST, with HTTP and surrounding manager collaborators replaced by fakes. Covers receipt decoding versus real rejections, failure text, new MCP invocation, initial cancel routing, caller scoping, and blocked/available/unknown/orchestrator spawn cases. This is explicitly supplementary validation, not a claim that real FastAPI/MCP/pipeline integration ran.
3. `nice -n 15 .venv/bin/python .orchestra/tasks/V-1036/mutations.py` — **10/10 mutants killed** after the idle-create correction. Removes initial persistence/wake, quota ID/ETA, initial queue visibility, sender isolation, accepted-error receipt handling, initial cancellation fallback, spawn admission and the idle-creation quota exemption. Source files are restored in `finally`. Mutation subprocesses have a 2 GiB address-space cap and a 45-second timeout.
4. Syntax compilation of all changed Python files and task-artifact secret filtering — see `final-checks.log`.

Imported app path: `<hub-workspace>`.

Regular integration tests were added in `tests/test_mcp_delivery_visible_1036.py`. Historical quota-admission tests expecting creation above the line/hard stop were updated to the new explicit V-1036 contract; a real manager pre-allocation test was added. No supplied explicitly frozen acceptance test was weakened.

## Non-obvious findings and remaining validation

- A structured error inside a successful delivery receipt is state information, not rejection of its durable acceptance. Raising it at the MCP transport boundary was the path losing delivery IDs.
- The initial-delivery event table only supports WAITING_QUOTA/SUBMITTED. Reusing the existing failure-notice table avoids changing that CHECK constraint or adding a competing notification service.
- The first mutation run exposed a test-helper naming error: an async helper named `fail` overrode `unittest.TestCase.fail`. It was renamed to `induce_failure`; the corrected baseline and all nine mutations were rerun successfully. Final logs contain the corrected runs.
- Existing initial ownership records store sender name+scope, not an immutable sender-session ID. Listing, cancellation and notice lookup follow that existing contract. Deleting/recreating a sender with the same name and scope is a remaining identity limitation of old data; no schema migration was introduced here.
- Actual provider wake, service restart/recovery timing, real HTTP authentication middleware, full pipeline/model routing and the full pytest suite remain unverified in this dependency-free copy. The orchestrator should run the prescribed focused suite in the normal uv environment before acceptance.
- Initial cancellation already routed to `cancel_initial_delivery` before this task; the regression test verifies that fallback rather than duplicating it.


## Orchestrator integration correction: idle creation

The orchestrator reported that the first implementation failed the existing
`tests/test_manager.py::TestCreateSession::test_idle_create_is_control_action_and_does_not_read_quota`.
Its requirement is valid: creating an idle worker is a control action and must not read
subscription quota. The preflight condition is now `planned_initial_turn and not is_orch`;
spawn with an initial task still checks admission before any allocation.
`tests/test_manager.py` was left unchanged. The existing hub pool capacity check is unchanged.

The offline spawn check now exercises seven combinations: blocked/available/unknown planned
worker admission, a planned orchestrator, and blocked/available/unknown idle creation. Idle
cases reach the next allocation seam with `get_worker_admission.assert_not_awaited()`;
a blocked planned worker is refused before that seam. Six offline edge tests passed in
`idle-create-check.log`. Added mutation `idle-create-reads-quota` restores the defective broad
condition and failed on all three idle cases. All 10 mutations were killed; sources were
restored. The full mutation result is in `mutations.log`.

The orchestrator's reported 435 delivery/quota/MCP tests and 222 manager/spawn/quota cases
(except the identified idle-creation failure) are external validation, not runs performed
in this dependency-free copy. Real pytest rerun of the unchanged manager regression remains
for the orchestrator's normal environment. This correction also adds the missing changelog
entry. No service restart or git operation was performed; this private hub copy has no `.git`,
so the platform remains responsible for importing and committing the result with a V-1036 header.

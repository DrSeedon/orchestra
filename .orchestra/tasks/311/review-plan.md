<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The plan has the right core safety model: caller-generated identity, atomic accept-before-wake, atomic log plus `PREPARING`, fail-closed `DISPATCHING`, no replay of ambiguous submissions, and preservation of the manager lock/auto-switch seam.

All three frozen RED commands fail by assertion for missing behavior, without collection errors:

- T1: 4 failed
- T2: 8 failed
- T3: 7 failed

However, the frozen oracles leave viable duplicate-delivery paths unguarded, and the documented state machine contains an unreachable transition.

## Findings

### Blocking — the oracle does not prove one backend prompt copy

The plan explicitly requires:

> “keep `original_user_message` and `exclude_history_users=(original_user_message,)`, so reconstructed history excludes the one persisted current input and the backend sees it once as current prompt”

But `test_t2_session_context_logs_no_duplicate_and_brackets_backend_send` only verifies:

- `_log("user_message", ...)` was not called;
- `before_submit → backend.send → mark_submitted` ordering;
- `backend.send` received `MESSAGE`.

It never supplies the already-persisted user log, exercises `_ensure_backend(exclude_history_users=...)`, or inspects reconstructed history. An implementation can omit `exclude_history_users`, pass every frozen test, and send the initial task both in reconstructed history and as the current prompt.

That violates the central “one backend prompt copy” invariant. Add a behavioral oracle with the prepared log present that fails unless history excludes precisely that persisted current input.

### Blocking — same-key retry does not prove the same canonical payload

`test_t3_delivery_status_and_known_precommit_retry_keep_the_same_key` asserts only the POST path and `delivery_id`. It does not assert the retry body’s `message`, `scope`, or `sender`.

Therefore an implementation can reuse the key while changing or omitting canonical fingerprint fields and still satisfy the frozen T3 oracle. In production that becomes an `IDEMPOTENCY_CONFLICT`, so the advertised `RETRY_SAME_DELIVERY` action would not be executable.

Assert the complete retry body, including the original task, caller scope, and sender. This should also demonstrate that retry cannot generate a new ID.

### Blocking — `COMPLETED` is specified but has no implementation seam or oracle

The state diagram promises:

> “terminal event → COMPLETED”

Yet the implementation map ends the delivery integration at `mark_submitted`; it names no terminal-event hook in `AgentSession`, backend listeners, or turn lifecycle, and no test exercises `SUBMITTED → COMPLETED`.

As planned, `COMPLETED` is unreachable and status can remain `SUBMITTED` forever. Either:

- add the exact terminal-event seam and a frozen behavioral oracle, including safe idempotent completion; or
- remove `COMPLETED` and the claimed transition from this protocol if `SUBMITTED` is intentionally terminal for Phase 3.

The current plan freezes an API/state contract it cannot implement within its stated file/function boundaries.

### Blocking — acceptance-error classification is underspecified and can prescribe an unsafe retry

The plan says:

> “a proven acceptance failure … returns `RETRY_SAME_DELIVERY`”

but does not define which HTTP/transport outcomes prove that no row was committed. The current `_api` correctly treats many POST failures as outcome-unknown. An HTTP 500 may occur after commit, and HTTP 409 means same key/different payload—not a precommit failure. Neither should be converted into a blind retry recommendation.

The plan must give an executable decision table based on `ApiToolError.outcome_unknown`, status/code, and the one status reconciliation GET:

- ambiguous POST → GET same ID once;
- found → return resource;
- unresolved → `CHECK_DELIVERY_STATUS`;
- proven request-not-sent or explicit precommit rejection → `RETRY_SAME_DELIVERY`;
- `IDEMPOTENCY_CONFLICT` → surface conflict, never retry;
- no second automatic POST.

A frozen test should cover at least committed-then-500/unresolved and 409, because the existing generic `{"error": "delivery unavailable"}` mock does not establish precommit failure.

### Suggestion — make cancellation handling explicit

The plan says every exception after `DISPATCHING` becomes `DELIVERY_UNKNOWN`, but `asyncio.CancelledError` is not caught by `except Exception` on current Python. Specify ownership of cancellation handling in `run_initial_delivery` or the session seam so an in-process cancellation cannot leave `DISPATCHING` indefinitely until a future restart.

### Question — startup ordering should name the exact insertion point

Recovery must run after `manager.auto_resume_all()` and before any delivery runners/background traffic can rely on stale state. The plan should explicitly place it before `manager.start_background_tasks()` and `schedule_restart_inbox_drain()`, rather than only saying “before normal traffic relies on the delivery runner.”

The described #305 overlap is otherwise appropriately narrow: only the new sibling beside `SessionManager.send`, with no import of pending #305 behavior.

## Verdict

**BLOCKING FINDINGS REMAIN**

## Round (2026-08-17T10:33:40Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

All Round 1 findings are resolved in the definitive RED freeze `327242a7432ef7b325cb7c4de38244479bcc1cab`.

The revised plan now has a coherent implementable contract: only `QUEUED`/`PREPARING` replay, `SUBMITTED` is terminal, ambiguity becomes `DELIVERY_UNKNOWN`, and provider exactly-once is not claimed. The tests directly cover the previously missing history, cancellation, startup-order, retry-payload, HTTP 500, rollback, and conflict cases.

## Findings

No blocking findings.

Prior findings:

- Backend prompt duplication: resolved by the prepared-history oracle, including duplicate message text and latest-row exclusion.
- Canonical retry payload: resolved; the complete `delivery_id`/`message`/`scope`/`sender` body is asserted.
- Unreachable states: resolved by removing `COMPLETED` and `FAILED_BEFORE_SUBMIT`.
- Unsafe error classification: resolved by the ordered `ApiToolError` decision table and frozen rollback, committed-then-500, reconciliation, and 409 tests.
- Cancellation handling: resolved with explicit `CancelledError` ownership and no-replay oracle.
- Startup ordering: resolved and pinned immediately after `auto_resume_all()`.
- #305 overlap: sufficiently narrow and does not inspect or import the unmerged branch.

No new contract or oracle gaps found.

## Verdict

**APPROVED — PLAN READY.** Stop before production implementation.

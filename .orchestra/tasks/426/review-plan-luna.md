<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The RED commands fail for the intended assertion reasons, not collection/setup failures. However, the oracle does not fully enforce several mandatory durability and concurrency guarantees.

## Findings

1. blocking: `tests/test_task_write_outbox_426.py:157-173` — does not prove receipts are committed before the HTTP response; it inspects the outbox only after both requests complete → add a response-ordering barrier or observable commit assertion.

2. blocking: `tests/test_task_write_outbox_426.py:103-112` — verifies both owners only after POST followed by PUT, so POST could fail to update one owner while PUT repairs it → assert legacy and canonical state immediately after POST, before issuing PUT.

3. blocking: `tests/test_task_write_outbox_426.py:324-371` — the acknowledgment-crash test does not require an applied marker or verify its Git-commit ordering; an implementation that merely retains receipts and later deletes them could pass → assert pending receipt + committed applied marker after SQLite commit, then test marker reconciliation.

4. blocking: `docs/tasks/426/plan.md:129-141` — dirty working-tree versus Git HEAD behavior is unspecified. “Reconcile these paths from Git HEAD” does not define what happens when a marker/receipt is present only as an uncommitted working-tree file → specify fail-closed behavior and add the corresponding test.

5. blocking: `tests/test_task_write_outbox_426.py:376-411` — malformed-receipt handling checks only the projection head, not that `current_records` and `current_fts` remain unchanged → snapshot selected rows/FTS before draining and compare them afterward.

6. blocking: `docs/tasks/426/plan.md:97-141` — concurrent enqueue versus acknowledgment has no explicit lock-order contract or oracle. “The same Git lock” does not prove absence of deadlock, stale-tail attachment, or overtaking → state the SQLite/Git lock order and add an interleaved concurrent enqueue/ack test.

7. suggestion: `docs/tasks/426/plan.md:114-117`, `app/main.py:446-454` — lifecycle ownership is described, but cancellation of the new long-lived drainer while waiting or during a drain pass is not an acceptance criterion → add a cancellation test proving shutdown awaits the task and leaves no live drainer/wakeup task.

8. suggestion: `docs/tasks/426/plan.md:87-89`, `tests/test_task_write_outbox_426.py:376-411` — the plan requires rejection of duplicate identities, duplicate targets, forks, cycles, and disconnected chains, but the frozen oracle exercises only one incomplete JSON receipt → add independent malformed-chain cases, or narrow the stated AC.

## Verdict

Needs work. The plan’s architecture is directionally consistent with the requested bounded scope, but the immutable oracle does not yet prove pre-response durability, two-phase acknowledgment, dirty-tree crash safety, concurrent lock ordering, or SQLite non-mutation on malformed input.

Review route: self-review; Codex reviewer unavailable.

## Round (2026-09-03T03:10:01Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The expanded RED remains valid: T1 has assertion-only failures for missing receipt behavior, and T2 has assertion-only failures for missing drainer/lifecycle behavior. No collection, setup, import, or `AttributeError` failures are reported.

Most prior blockers are fixed. Two load-bearing oracle gaps remain.

## Findings

Prior findings:

1. FIXED — `tests/test_task_write_outbox_426.py:175-288` now verifies POST ownership and commit/response ordering.

2. FIXED — `tests/test_task_write_outbox_426.py:175-200` checks legacy and canonical state before PUT.

3. FIXED — `tests/test_task_write_outbox_426.py:451-481` requires a committed applied marker and replay behavior.

4. FIXED — `tests/test_task_write_outbox_426.py:587-627` covers Git-HEAD authority, dirty paths, and constructor ordering.

5. FIXED — `tests/test_task_write_outbox_426.py:569-584` compares complete rows, FTS, and metadata snapshots.

6. FIXED — `docs/tasks/426/plan.md:159-164` and `tests/test_task_write_outbox_426.py:631-680` specify and exercise non-nested lock ordering.

7. STILL BROKEN (suggestion): `tests/test_task_write_outbox_426.py:683-693` cancels the drainer directly, but does not exercise `app.main._shutdown_runtime()` passing, canceling, and awaiting the long-lived task → add lifecycle integration coverage or explicitly limit the AC to direct task cancellation.

8. FIXED — independent missing-field, fork, cycle, and duplicate-target cases are present.

New findings:

1. blocking: `docs/tasks/426/plan.md:62-70,225-227` — the size-dependence oracle varies only the in-memory evidence corpus; `current.db` remains empty in both arms, and the test instruments only `update_current_records()` → a request path that scans a large `current.db` through another projection method can pass. Add a populated large-current.db arm or census all projection reads on the request path.

2. blocking: `tests/test_task_write_outbox_426.py:392-420` — valid-chain coverage asserts the final `current_records` payload but never verifies the corresponding `current_fts` row/text. The implementation could update the row and head while leaving FTS stale → assert the final FTS binding and searchable text.

## Verdict

Needs work. The remaining gaps affect the requested volume-independence and joined-projection correctness guarantees.

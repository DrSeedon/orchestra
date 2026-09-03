<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The delivery state machine is mostly fail-closed, but the public spawn path violates idempotency before reaching it. I also found a history-deduplication gap for masked messages.

## Findings

blocking: `app/mcp_stdio.py:1096-1135` — the worker is created before `delivery_id` is checked. The code performs:

> `result = await _api("POST", "/api/sessions", json=body)`

and only afterward calls:

> `delivery = await _post_initial_delivery(name, task, delivery_id, scope)`

Consequences:

- Same key with different payload can create a worker/worktree before returning 409.
- Repeating the same key and payload re-enters session creation instead of directly returning the existing delivery receipt; a duplicate-name rejection can prevent dedupe entirely.

This violates both “409 before side effects” and same-key/same-payload dedupe. The idempotency record must be inserted/read before worker creation, or the creation endpoint must atomically participate in the same keyed operation.

blocking: `app/initial_deliveries.py:155-168` and `app/session.py:1331-1337` — the immutable log stores `mask_secrets(message)`, while history exclusion uses the unmasked `original_user_message`:

> `mask_secrets(row["message"])`

versus:

> `exclude_history_users=(original_user_message,)`

History exclusion is exact-content matching. If masking changes the task, recovery/backend initialization can retain the masked `user_message` in imported history and also submit the original current message, producing two representations of one initial task in the backend prompt. Exclude the immutable row by `user_log_id`, or pass its persisted masked content to the history exclusion mechanism.

## Verdict

**NEEDS WORK**

## Round (2026-08-17T12:04:06Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Both Round 1 findings are resolved. Focused verification passed: `16 passed in 10.23s`.

## Findings

- Prior finding 1: **WITHDRAWN.** The approved contract explicitly begins after session creation and forbids modifying create-session logic. Delivery retries correctly use `retry_initial_delivery`, not a second `spawn_worker`.
- Prior finding 2: **FIXED.** The exact persisted `logs.content` now flows through `InitialDeliveryContext` and is used for native history import, DB-backed fallback, and `resume_failed` handoff. The original task remains the sole backend submission.
- New blocking findings: none.
- Suggestions/questions: none.

## Verdict

**APPROVED**

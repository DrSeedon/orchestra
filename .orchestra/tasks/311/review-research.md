<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The research correctly identifies the synchronous acknowledgement boundary and the unavoidable external commit-point ambiguity. The proposed stable key, commit-before-wake, status lookup, and no-replay policy can prevent duplicate provider submissions caused by client timeout, same-key retry, concurrency, and restart while submission is provably unstarted.

However, two protocol contradictions remain around pre-commit failure and restart recovery through the existing `AgentSession.send` path. These are blocking because the current proposal cannot yet demonstrate its required recovery and no-duplicate guarantees.

Repository inspection is evidenced by the existing serialization path in `SessionManager.send`:

> `async with self.get_session_lock(session_id):`

followed by `_auto_switch_before_delivery(session)` and `await session.send(message)`. The session path also persists `_log("user_message", message)` before backend preparation and the eventual `await backend.send(outbound_message)`.

## Findings

### Blocking — `FAILED_PRECOMMIT` contradicts the required “no delivery row” outcome

The measurable outcome requires:

> “a failed pre-commit creates neither a delivery nor a model turn”

But F8 introduces `FAILED_PRECOMMIT` as a durable state, and F9 says status reconciliation can observe that state and explicitly retry it. A failed transaction cannot leave a committed `FAILED_PRECOMMIT` resource under the same failed commit. Persisting that state in a later transaction would instead create a delivery row and contradict outcome 6.

The document already contains the correct alternative elsewhere: GET returns no row, then the caller retries the same key and identical payload. The state machine and reconciliation contract must consistently use that model:

- commit/insert failed → no row, no wake, GET returns absent, same-key retry is allowed;
- a committed row that later encounters a provably pre-submit terminal error may become a differently named terminal state, but it is not a “failed pre-commit.”

The Phase 2 oracle must inject an actual transaction/commit failure and prove all three conditions together: no row, no runner/wake, and zero backend calls.

### Blocking — restart recovery through the cited `AgentSession.send` seam can duplicate persisted prompt input

F7 correctly places `DISPATCHING` immediately before `backend.send`, but it overlooks an earlier durable side effect in `AgentSession.send`:

> `self._log("user_message", message)`

That happens before `_ensure_backend(...)`. A restart during cold connection therefore leaves a delivery in the proposed recoverable `PREPARING` state while its user message is already persisted. Re-running the existing `session.send(message)` can log the same initial task again. Backend reconstruction/history import may then expose the task both through persisted history and the new outbound submission, even if the backend-call counter remains exactly one.

Consequently, the proposed oracle “provider-send counter fixed at one” is insufficient. Recovery must also prove that the logical initial task occurs exactly once in persisted conversation input and exactly once in the prompt observed by the backend. The protocol needs an idempotent relationship between the delivery row and user-message log, or a recovery path that resumes preparation without re-appending the logical input.

This is especially important because `db.ack_facts` documents the existing boundary explicitly:

> “Зовётся только после возврата из backend.send.”

The codebase already treats pre-send and post-send persistence ordering as semantically significant.

### Suggestion — qualify the claim that `app/manager.py` can remain unchanged

The research says the dispatcher can avoid changing `SessionManager.send`, but the existing method owns two important behaviors:

- per-session serialization via `get_session_lock`;
- `_auto_switch_before_delivery(session)` before `session.send`.

A dispatcher cannot safely bypass it and call `AgentSession.send` directly. Conversely, the current signature accepts only `(session_id, message)`, so it has no explicit way to carry delivery identity or correctness-critical before-submit/after-submit callbacks to the session seam.

A context-based mechanism might technically avoid changing the signature, but that would be an implicit correctness dependency and is not established in the research. Phase 2 should treat a narrow manager entry point or explicit delivery context as likely necessary, while keeping the overlap small. This is a design choice rather than a present factual blocker once the two blocking protocol issues above are resolved.

### Suggestion — add a positive restart-recovery oracle at each side of the submit boundary

The listed tests mention “dispatcher reconstruction,” but the acceptance needs distinct crash cases:

- committed `QUEUED`, runner never scheduled;
- `PREPARING` before user-message persistence;
- `PREPARING` after user-message persistence but before backend submission;
- `DISPATCHING` before backend acceptance;
- backend accepted, process dies before `SUBMITTED` commit.

For the first three, recovery must produce one logical prompt and one backend submission. For the last two, recovery must produce `DELIVERY_UNKNOWN`, no automatic replay, and an actionable structured status/no-resend response.

### Question — define what `SUBMITTED` means for Codex

`CodexBackend.send` receives the native turn ID only after `_request("turn/start", ...)` returns, while Claude’s `query(message)` returns no comparable provider idempotency receipt. The research correctly concludes that neither backend invalidates the external exactly-once impossibility boundary.

Phase 2 should nevertheless state whether `SUBMITTED` means “the backend call returned successfully” or “a native provider reference was obtained.” Those are equivalent for the current Codex path but not a portable backend contract. This does not block the research conclusion, provided `DISPATCHING` exceptions remain unknown unless a backend supplies typed proof that submission never began.

## Verdict

**BLOCKING FINDINGS REMAIN**

## Round (2026-08-17T10:02:23Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Re-review status

- FIXED — `FAILED_PRECOMMIT` contradiction. Failed acceptance now leaves no row, schedules no runner, and performs no backend call. `FAILED_BEFORE_SUBMIT` is correctly limited to an already committed delivery with typed proof that submission never began.
- FIXED — duplicate prompt during `PREPARING` recovery. The revised contract requires one immutable `user_message`, one backend-observed prompt copy, and one backend call. Evidence from the revised artifact: “Passing the same message in `exclude_history_users` must continue to exclude that one persisted row from reconstructed native history”.
- FIXED — manager integration. The design now preserves `get_session_lock` and `_auto_switch_before_delivery` through a narrow delivery-aware manager entry/context and explicitly records the #305 overlap.
- FIXED — restart oracle coverage. The six cases distinguish absent acceptance, both sides of user-log persistence, pre-submit recovery, and both ambiguous submission windows.
- FIXED — `SUBMITTED` definition. It now portably means successful return from `BackendLike.send`; a native reference is optional metadata.

`git diff` was empty because [research.md](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-spawn-delivery/docs/tasks/311/research.md) is currently untracked (`??`), so the complete current artifact was reviewed directly.

## New findings

None. The revised guarantee no longer overpromises external exactly-once and preserves the structured reconciliation/no-resend boundary.

## Verdict

APPROVED

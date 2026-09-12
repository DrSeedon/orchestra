# V-562 — durable steering recovery

## Result

Active-turn direct deliveries retain their provider turn identity in the existing
`message_deliveries.provider_ref` column (the `steered:` prefix is storage-only and is
removed from receipts). On a failed/interrupted `turn_end`, all matching steers are
moved in accept order into the existing durable `mailbox` in one SQLite transaction;
their receipt becomes `WAITING_NEXT_TURN`. A repeated terminal event finds no `SUBMITTED`
steers and creates no duplicate mailbox rows.

On a normal turn end no recovery operation runs, so the existing `SUBMITTED` immediate
delivery behavior is unchanged. Mailbox delivery acknowledges the mailbox row and
changes the recovered receipt back to `SUBMITTED` atomically; newer direct deliveries
remain FIFO-blocked until that recovered message is delivered, then the direct runner is
woken. Receipt rendering exposes `WAITING_NEXT_TURN` separately from accepted/submitted.

## Files and commits

- `app/session.py` marks the keyed active delivery as a running steer before provider send.
- `app/session_turns.py` recovers failed-turn steers and completes recovered mailbox rows.
- `app/backend_codex.py` carries the active turn id into a process-exit terminal event,
  allowing the same recovery path to handle provider-process failure.
- `app/message_deliveries.py` stores the turn marker, performs atomic requeue/completion,
  and exposes the waiting receipt state.
- `app/mcp_stdio.py` renders the waiting state to the sender.
- `tests/test_durable_steering_562.py` covers FIFO, idempotence, normal-path non-requeue,
  atomic completion, and turn identity.

Commits: `19e1e21a`, `03ae1841`, `455c48ed`, and `89e53f9f` (the orchestrator should
squash them when merging).

## Verification

All commands used the required runtime:

```text
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q tests/test_durable_steering_562.py tests/test_message_delivery_receipts_380.py
34 passed in 16.11s

/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q tests/test_session.py tests/test_mailbox.py tests/test_audit0901_harness.py
266 passed, 1 warning in 18.10s

/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q tests/test_durable_steering_562.py tests/test_message_delivery_receipts_380.py tests/test_mcp_stdio.py tests/test_codex_writer_conflict_536.py
160 passed in 20.40s

/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q tests/test_durable_steering_562.py tests/test_session.py tests/test_mailbox.py
267 passed, 1 warning in 18.09s

/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q tests/test_durable_steering_562.py tests/test_backend_codex.py
107 passed in 8.42s
```

Mutation checks were run only against the committed test file:

- Changed the recovery query state from `SUBMITTED` to `BROKEN` →
  `test_failed_turn_requeues_all_steers_fifo_and_is_idempotent` failed (`0 == 2`).
- Changed `MessageDeliveryContext.mark_running_steer()` to set `False` →
  `test_context_marks_only_running_steer_with_turn_identity` failed (stored
  `codex-turn-562` instead of `steered:codex-turn-562`).

Both mutations were reverted; the final focused suite is green.

## Pre-mortem checks

- Normal active steering remains covered by the existing `test_t380_r2_running_receipt_steers_once_without_new_turn_or_second_log` regression.
- Multiple failed steers preserve accept order and sender/body; repeated recovery is idempotent.
- A mailbox row remains in SQLite after the recovery call, so a process restart between
  failure and the next turn does not rely on in-memory pending state. No server restart
  was performed; only the owner may restart Orchestra, and Python changes apply after
  that owner-issued restart.
- Codex `_process/exited` now carries the active turn id before clearing it, so a provider
  process failure also selects the failed-turn recovery rows.
- Missing mailbox tables remain non-fatal: the failed-turn recovery call is guarded and
  the existing session lifecycle tests pass on fixtures without that table.
- Newer direct deliveries are not overtaken by an unrecovered message; the recovery
  state is intentionally non-terminal for the direct-delivery FIFO head.

The codex-debate review could not start: the review service stopped at
`database schema needs offline migration before starting Orchestra`. No external review
findings are therefore available; source review and the checks above remain the evidence.

# Stability recovery — 05.09.2026

Branch: `fix/stability-recovery`. Base: `36326164`; first packet: `42e0352e`.
Scope: six user-approved stability items. Production services and VPS were not changed.

## Completed implementation

1. **Target queue recovery.** Existing `restart-cli` excludes delivery, manager and
   lifecycle operations; busy targets return 409 before mutation. Successful runtime
   teardown releases only that target's ambiguous barriers. Unknown delivery stays
   unknown and is never resent. Subsequent queued messages drain normally. Caller
   cancellation cannot release locks while owned teardown/recovery is still running.
   SQLite recovery runs outside the event loop. UI shows the unreconciled count.
2. **Separate status facts.** `status` remains the work state. `runtime_connection`
   reports local attachment/listener/hibernation, not provider responsiveness.
   Unconfirmed delivery and existing lifecycle quarantine appear separately.
   One runtime-detail formatter serves the selected worker, list and live status updates.
   Unconfirmed targets are read in one batch, not one query per worker.
3. **Automatic continuations.** Generation/Stop guards cover rate-limit retry,
   server-error retry, max-turn continuation, delayed compact and stream reconnect.
   Admission rechecks happen under the send lock. Alternating error classes cannot
   replenish each other's budgets. A stale failure cannot finish a newer turn.
   Listener teardown no longer attempts to cancel/await itself.
4. **Dashboard recovery.** Synchronous and asynchronous refresh failures are isolated,
   reported, and do not permanently lock recovery or masquerade as online. Existing
   latest-100, atomic snapshot, rapid-switch cancellation, load-more and image contracts
   were reused and verified instead of rewritten.
5. **Fault scenarios.** Tests cover caller cancellation, target busy, teardown failure,
   other-target isolation, no ambiguous resend, busy SQLite with a responsive event
   loop, stale continuations, native oversized JSONL and compact boundaries. Browser
   tests render actual repository templates/scripts/styles with intercepted requests;
   they do not start a second application lifespan or provider CLI.
6. **Ownership cleanup.** Failed-continuation finalization has one owner instead of
   six copies. Startup and targeted queue recovery share one transaction implementation.
   No service split, new dependency, automatic route switch or broad file restructuring.

## Verification

- Combined regression command: 718 passed (listed below; final run recorded in chat).
- Race/recovery selection: 23 passed on each of three consecutive runs.
- Browser selection: 12 passed, including existing chat/history/photo scenarios.
- Before-fix/mutation controls: Stop could resubmit; alternating errors reset the other
  budget; removing the send-lock generation check failed both new-turn cases; all three
  JS recovery-error cases failed before the fix. Removing target isolation produced
  two failing recovery cases (two sessions settled instead of one), then restored green.
- One broad run hit a pre-existing 0.5-second test deadline on filesystem telemetry.
  That no-turn-wait test now stubs incidental telemetry; the separate
  persistence-before-signal test remains unchanged. No production timeout was raised.

```sh
env -u NOTIFY_SOCKET /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest \
  tests/test_session.py tests/test_hot_apply.py tests/test_manager.py \
  tests/test_message_delivery_receipts_380.py tests/test_delivery_head_of_line_block.py \
  tests/test_backend_codex.py tests/test_compact_pending_ack_467.py \
  tests/test_compact_pending_rollback_467.py tests/test_compact_gate_438.py \
  tests/test_session_hibernate.py tests/test_db.py tests/test_connection_recovery.py \
  -q --timeout=30
```

Broad runs used a user systemd scope with MemoryMax=2G and nice=15; NOTIFY_SOCKET unset.
One browser harness attempt lacked a seeded selection and timed out; only that owned
test scope was stopped. The seeded, fully intercepted harness subsequently passed.

## Limits

No production failure injection, provider subscription calls, VPS deploy, merge into
main or service restart. No claim of measured production latency/availability gain.
Unknown provider acceptance cannot be converted into exactly-once delivery: it remains
explicitly unreconciled after local teardown. Runtime observation is not a network probe.

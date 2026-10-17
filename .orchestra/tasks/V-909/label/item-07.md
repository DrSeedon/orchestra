# item-07

Commit under review (in /home/kesha/orchestra, read-only): `a0bec5f5b93417d7bfcad1c1438f6b827811d8a9`
Subject / date:
#120: safe process signaling — pidfd exec shim, remove broad pkill
2026-08-01

The diff reviewed is `git -C /home/kesha/orchestra show a0bec5f5b93417d7bfcad1c1438f6b827811d8a9 -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff between the pinned commits. The pidfd shim, pre-ACK group-signal probe, and shared shielded cleanup task are consistent with the stated safety contract. I found one resource leak in a cancellation race.

## Findings

### Suggestion

- **Close a received pidfd if the receive future was already cancelled.** In `app/bg_jobs.py`, the `_recv_pidfd()` callback extracts the fd before checking `future.done()`. If cancellation lands after `recvmsg()` receives the fd but before `set_result()`, the cancelled future causes the callback to discard the fd without closing it. Close `result` when the future is already done. This race can leak a descriptor during repeated spawn cancellations.

## Verdict

APPROVED — no blocking findings.

# retro-02

Commit range reviewed: `git -C /home/kesha/orchestra diff 0eaae5904f0ad7e413c434e0ba6a3335f8427502...bef0c6bc1a048e49a9b1a893bd9be3b42a3a8202 -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`
Review date: 2026-09-08.

## Reviewer output (verbatim)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Reviewed the complete diff. Targeted fork tests pass: 14 passed via `uv run --frozen python -m pytest`.

The implementation has a blocking race: stopped-tree observation is not an atomic reservation, so the old writer can resume after the final proof and before or during use of the copy.

## Findings

### Blocking

- `app/backend_codex.py:943-948`, `app/session.py:1181-1198`

  `stopped_codex_writer()` proves only that all observed threads were in state `T` at sampled instants. After the final check at line 947, the old process can receive `SIGCONT` or otherwise resume before persistence and the first new turn. There is no held kernel barrier, ownership transfer, or other mechanism preventing this.

  Therefore the implementation does not satisfy the required safety property: two writers can still operate on the same worktree/thread after a seemingly positive proof. The notice merely tells operators not to resume the old writer; it cannot prevent an immediate resume race.

  The tests cover proof revocation before `thread/fork`, but not resumption immediately after the final proof.

### Suggestion

- `app/message_deliveries.py:46-63`

  Durable receipts recompute `runtime_recovery` from the target session’s current `session_id_history`. The delivery row does not store the recovery record. A later recovery or bounded history truncation can cause an old receipt to show a newer reconstruction or no reconstruction at all.

- `app/routes/sessions.py:1101-1107` and `1139-1144`

  Fan-summary and terminal fan-barrier paths call `manager.send()` but return without adding `runtime_recovery`. If recovery occurs there, the sender does not see that the thread was copied or the source/target history point.

- `app/backend_codex.py:548-555`

  The notice clearly explains limitations, but does not explicitly disclose the copy operation’s cost/charging semantics. Sender/dashboard visibility should state whether the fork itself is free and that the subsequent new turn is charged normally, if that is the intended contract.

## Verdict

NEEDS WORK — the post-proof resume race can create concurrent writers in the same worktree, violating the core safety requirement.


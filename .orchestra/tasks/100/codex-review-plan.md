## Summary

🙃 Telegram ordering is now a state machine wearing a photo as camouflage. The architecture is feasible and has no blocking flaw: chronology is correctly scoped to an acknowledged marker, marker retries are forbidden, the image worker shares rate/flood control without holding it during I/O, reservations are bounded, Read sources are snapshotted, and T2 correctly depends on T1.

The plan also preserves the first-round architectural dissent recorded in [codex-review-research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/docs/tasks/100/codex-review-research.md:9). Four acceptance-criteria gaps remain.

## Findings (blocking/suggestion/question)

### suggestion: Make every asynchronous image continuation identity-safe

[plan.md:69](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/docs/tasks/100/plan.md:69) protects only the image worker’s cleanup. Reset also settles marker futures and admission waiters; their submission coroutines or callbacks can resume after a replacement state for the same chat has been created. Because current reset does not await arbitrary callers ([tg_bridge.py:654](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/app/tg_bridge.py:654)), cleanup that looks state up by `chat_id` could decrement the replacement reservation or counters. Require every post-`await` image continuation to mutate its captured state/reservation, and extend the reset-resubmit AC beyond the worker’s `finally` path.

### suggestion: Test cross-worker rate-slot atomicity directly

[plan.md:84](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/docs/tasks/100/plan.md:84) verifies shared `retry_after` and that slow image I/O does not retain the gate, but neither assertion proves that simultaneous text and image workers cannot reserve the same start slot. That race becomes possible because the current unlocked wait/update sequence is safe only with one dispatcher ([tg_bridge.py:812](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/app/tg_bridge.py:812)). Add an event-controlled or fake-clock contention test that proves exactly one worker reserves the first slot and the other waits, without elapsed-time assertions.

### suggestion: Specify marker-admission failure accounting and return value

[plan.md:81](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/docs/tasks/100/plan.md:81) requires reservation release and no edit when reliable marker admission fails, but does not define the `_ImageSubmission.accepted` result or whether this increments `image_dropped` or `image_lost`. The result must be unaccepted so the Read path retains textual fallback, and exactly one image counter should own the event. Otherwise two implementations can satisfy the stated AC while exposing different behavior and statistics.

### suggestion: Make deterministic stats ordering an explicit AC

[plan.md:103](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/docs/tasks/100/plan.md:103) promises sorted output, but the T2 AC only says two chats are returned. Require their `chat_id` values in sorted order and enumerate the expected `image_*` schema. This prevents an insertion-ordered response or omitted metric from satisfying the endpoint tests while violating the promised predictable contract.

## Verdict

**Approved for implementation; no blocking findings.** T1 and T2 are viable vertical tickets with the correct dependency, but the four AC clarifications should be added before implementation so concurrency and diagnostics cannot pass through underspecified tests.

Review was static against the requested file ranges; no files were edited and no implementation tests were run. The seats are finally in chronological order—four reservation cards just need actual names. 🎟️

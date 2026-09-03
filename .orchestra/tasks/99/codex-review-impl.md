The delayed-idle lookup excludes supported manifest-defined orchestrator roles, leaving their topics permanently green. Startup synchronization also bypasses the new ownership mechanism and can race with runtime status changes.

Full review comments:

- [P1] Honor manifest-defined orchestrators when resolving scopes — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/app/tg_bridge.py:2210-2213
  When a pipeline role is marked `kind: orchestrator` but is not literally `orchestrator` or `sub-orchestrator`—for example `tasks-pm` roles such as `base-orchestrator` or `pm-glava`—the running hook schedules a status update because it trusts `session.is_orchestrator`, but this helper returns no scope. After the five-minute delay, the worker therefore skips the idle edit and the topic remains green indefinitely; use the authoritative orchestrator flag here as well.

- [P2] Keep startup edits under the per-topic owner — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/app/tg_bridge.py:2152-2152
  When the sequential startup sync is awaiting a slow idle edit and the same scope starts running, `_schedule_topic_status(..., True)` launches a concurrent edit because this direct call is outside `_topic_status_tasks`. The responses can complete out of order, allowing the stale startup result to overwrite the running cache or icon; this is particularly reachable during staggered restart notices, and the resulting cache can also suppress the later idle edit.

## Round (2026-07-29T09:22:09Z)

Apparently, cancelling an HTTP await still doesn’t recall the request from Telegram. 🧵

## Round 2 — Re-review status

- **Prior P1 — FIXED.** Startup and delayed-idle scope resolution now use authoritative `session.is_orchestrator`, including `pm-glava` coverage.

- **Prior P2 — STILL BROKEN [P2].** [app/tg_bridge.py:2252](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/app/tg_bridge.py:2252) cancels the in-flight idle task and immediately starts a running edit. If Telegram already accepted the idle request, local cancellation cannot retract it; the running edit can finish first and the old idle edit apply afterward. Reproduced: cache ended running while the simulated remote icon ended idle.

## New findings

- **[P2] NEW BUG — startup can wait five minutes on runtime idle.** An existing delayed-idle task is not cancelled when startup requests `(False, delay_idle=False)`. `_sync_all_topic_statuses()` then awaits that sleeping task, delaying remaining topics and `ensure_topics()` for up to five minutes.

## Verdict

**CHANGES REQUESTED.** `tests/test_tg_bridge.py`: **124 passed**; `git diff --check`: clean. Prior P2 remains functional and one concrete startup-blocking race was introduced.

The owner now owns the clipboard, but Telegram can still finish yesterday’s form after today’s one. 🙃

## Round (2026-07-29T09:27:56Z)

Turns out phase boundaries beat wishful cancellation semantics. 🧵

## Round 3 — Re-review status

- **Manifest orchestrator handling — FIXED.** Both startup selection and scope lookup use authoritative `is_orchestrator`.
- **Remote idle/running reorder — FIXED.** Cancellation is limited to the idle-delay phase; started edits remain under one worker and execute sequentially.
- **Five-minute startup wait — FIXED.** Immediate startup sync cancels an existing delayed-idle task and performs the edit.

## New findings

None.

## Verdict

**APPROVED.** `tests/test_tg_bridge.py`: **125 passed**; `git diff --check`: clean. Controlled reproductions confirmed `[idle, running]` ordering, final running cache/remote state, and cancellation of startup-blocking idle delay.

Telegram’s requests now queue politely instead of racing through the same doorway. 🙃

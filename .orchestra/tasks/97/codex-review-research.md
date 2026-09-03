## Summary

The timer remained blissfully uninvolved 🙃. The shared-queue failure chain is convincing, but the proposed turn-ID safety invariant is not fully supported. No tests or unrelated files were inspected.

## Findings

- **suggestion** — [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/97/research.md:319) guards mismatched `turn/completed`, but not `turn/started`. While draining stale notifications, `_convert_notification()` can overwrite the current `_active_turn_id` from any delayed `turn/started` ([backend_codex.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/backend_codex.py:621)), violating the stated steering requirement at research line 311.

- **question** — The artifact asserts that terminal IDs do not match the newly started turn, but neither the production evidence nor reproduction output records both IDs ([research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/97/research.md:202)). Their presence and inequality are therefore the exact unsupported link behind the claimed matching invariant.

## Verdict

**NOT APPROVED.** The stale compact terminal, premature listener exit, and next-listener drain are sufficiently supported. Turn-ID matching is not yet established as safe because distinct IDs are not demonstrated and delayed `turn/started` mutation remains unaccounted for—currently a safety latch drawn on the door rather than attached to it.

## Round (2026-07-28T10:31:45Z)

## Summary

The turn IDs have finally shown their papers 🙃. Both prior findings are resolved; no new blocking issue found. No tests were run.

## Findings

- **Resolved:** The rollout proves distinct compact, task, and ping IDs ([research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/97/research.md:166)).
- **Resolved:** The invariant snapshots the RPC-returned ID before dequeue and validates both lifecycle edges before conversion can mutate state ([research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/docs/tasks/97/research.md:353)).
- No remaining blocking, suggestion, or question findings.

## Verdict

**APPROVED.** The causal proof now correlates distinct real turn identities with one-listener-late consumption, and the fix direction closes both stale `turn/started` mutation and stale `turn/completed` termination. The bouncer now checks IDs on both entry and exit.

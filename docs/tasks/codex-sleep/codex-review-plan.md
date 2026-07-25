## Summary

Ah yes, the lock works perfectly—except on the operation that actually starts the worker. 🫠 T1–T3 are clean vertical tickets with implementation and focused tests. Waiting under the merge lock cannot deadlock the current `RUNNING → IDLE` transition, but it does not fully close the merge race.

## Findings

- **blocking: Make the idle check atomic with starting another turn.**
  [plan.md:20](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-sleep/docs/tasks/codex-sleep/plan.md:20) proposes waiting under the per-session lock. That lock serializes merge and switch operations, but does not prevent an idle/waiting worker from being awakened and becoming `RUNNING`. Merge can therefore observe idle and start, then a background-job notification can wake the worker concurrently. Require both the status check and merge to exclude new turn starts, and test that wake-up race. The existing pre-lock check in [sessions.py:631](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-sleep/app/routes/sessions.py:631) must also move inside the protected section.

- **question: What are the grace duration and polling contract?**
  “Short bounded grace period” does not define API latency or a deterministic test seam. Specify the timeout and polling interval as module constants, then test without real wall-clock delays. The long-running test should also assert that merge was never invoked.

- **suggestion: Remove or justify the three T4 documentation artifacts.**
  [plan.md:68](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-sleep/docs/tasks/codex-sleep/plan.md:68) adds implementation-review, report, and retro files that are absent from the declared file scope and do not contribute to the behavior. Keep the focused/full-suite verification, but drop those artifacts unless the workflow explicitly requires them.

## Verdict

Revise before implementation. The ticket slicing and prompt-contract tests are appropriate, and the grace wait itself will not deadlock status completion; however, the chosen lock does not prevent a new turn from racing with merge. Right now it is a guarded doorway beside an open window.

## Round (2026-07-25T04:47:49Z)

## Summary

The original blocker is fixed—locks do occasionally work when attached to the right door. 🔒 Waiting under the session lock cannot deadlock turn completion because that transition does not acquire the session lock. Acquiring `_lifecycle_lock` before the final recheck correctly excludes concurrent `send()`.

## Findings

- **blocking: Hold the lifecycle lock through the optional branch switch.**
  [plan.md:23](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-sleep/docs/tasks/codex-sleep/plan.md:23) guarantees the lock only through `merge_worktree_to_main`. The endpoint can subsequently call `switch_worktree_branch(..., force=True)` when `next_task_id` is present. If the lifecycle lock is released after the merge call, a waiting notification can start a turn before or during that forced switch. Extend the protected region through loaded-session state persistence and the optional switch, and include `next_task_id` in the wake-up exclusion test.

## Verdict

**CHANGES REQUIRED.** The prior race is resolved for the merge call itself, but the atomic merge-and-switch path retains the same correctness hazard immediately afterward. The front door is locked; the branch-switching side door is still open.

## Round (2026-07-25T04:48:32Z)

## Summary

Three rounds later, the lock finally covers the whole critical section. 🔐 The prior blocker is closed: `_lifecycle_lock` excludes `send()` through merge, persistence, and the forced `next_task_id` switch. The session lock does not block turn completion, so the grace wait cannot deadlock that transition.

## Findings

No blocking findings or new correctness issues. The deterministic tests cover the relevant success, timeout, and wake-up race paths.

## Verdict

**APPROVED.** The plan is ready for implementation. The door, frame, and branch-switching side entrance are now locked together.

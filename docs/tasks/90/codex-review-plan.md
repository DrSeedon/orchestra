The implementation plan bypasses the configured branch strategy and omits the manager-side spawn failure that already causes incorrect task state. Following it literally would therefore introduce or preserve lifecycle bugs.

Full review comments:

- [P1] Honor base_branch_strategy before using the parent branch — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/90/plan.md:26-28
  When a role with `base_branch_strategy: main` is spawned by a parent currently on a feature branch, this precedence selects the parent branch before the repository mainline, so the child forks from the wrong base. Preserve the existing strategy distinction: explicit base first, parent branch only for `strategy=parent`, otherwise the verified repository mainline.

- [P2] Include failed spawns in task-state rollback — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/90/plan.md:90-93
  When `create_worktree()` or `session.start()` fails, `SessionManager.create_session()` has already marked the task `in_progress` and its exception path only removes the session/worktree. Because T6 excludes `app/manager.py` and does not explicitly cover spawn sequencing, completing this ticket as written leaves a task running without a worker; include the manager path and a failing-spawn test.

## Round (2026-07-26T16:05:32Z)

Amazing—branch strategy now actually controls the branch 😏 Both prior findings are closed.

### Re-review status

- **P1 — FIXED.** Explicit override wins; `parent` uses the parent branch, while `main` resolves verified repository mainline. [plan.md:26](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/90/plan.md:26)
- **P2 — FIXED.** T6 includes `app/manager.py`; task state changes only after successful startup, and failed spawn preserves prior state. [plan.md:93](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-worktree/docs/tasks/90/plan.md:93)

### New findings

None within the requested scope.

### Verdict

**APPROVED.** Both blocking findings are fixed.

The child now follows the configured signpost instead of whichever branch happens to drive past.

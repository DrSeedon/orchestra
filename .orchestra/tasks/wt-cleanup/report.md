# Report: Auto-cleanup stale worktrees

## What was done

Added automatic cleanup of stale git worktrees (worktrees without an active DB session). Runs at server startup and every 24 hours.

## Files changed

| File | Lines | Description |
|------|-------|-------------|
| `app/workspace.py` | +58 | `cleanup_stale_worktrees()` — scans WORKTREE_ROOT, removes stale worktrees |
| `app/manager.py` | +25 | `_periodic_worktree_cleanup()` task + startup hook + shutdown cancel |
| `tests/test_workspace.py` | +47 | 4 tests: removes stale, skips dirty, skips non-worktree, empty root |
| `docs/tasks/wt-cleanup/` | +111 | research.md, plan.md |

## Safety mechanisms
- Skips worktrees with uncommitted changes (dirty tree)
- Only removes worktrees with no active session in DB (get_all_sessions excludes archived)
- Skips non-worktree directories (no .git file)
- Cleans up empty scope dirs after removal

## Tests
- 4 new tests in `TestCleanupStaleWorktrees` — all pass
- 6 pre-existing failures unrelated to this change (auto_report monkeypatch + archive_session semantics)

## Breaking changes
None.

# Plan: Auto-cleanup stale worktrees

## Changes

### 1. `app/workspace.py` — add `cleanup_stale_worktrees()`

New function at the end of the file (before `parse_owned_dirs`):

```python
def cleanup_stale_worktrees() -> list[str]:
```

Algorithm:
1. Import `get_all_sessions` from `app.db`
2. Collect all worktree_paths from non-archived sessions → `alive_paths: set[str]`
3. Iterate `WORKTREE_ROOT` → scope dirs → worker dirs
4. For each worker dir:
   - Skip if path in `alive_paths`
   - Skip if no `.git` file (not a worktree)
   - Check `git status --porcelain` — skip if dirty (uncommitted changes)
   - Resolve repo_path from `.git` file's `gitdir:` pointer
   - Call `remove_worktree(repo_path, str(worker_dir))`
   - Log + append to removed list
5. Return list of removed paths

### 2. `app/manager.py` — startup + periodic cleanup

In `start_background_tasks()`:
- Add `asyncio.create_task(self._periodic_worktree_cleanup())` 

New method `_periodic_worktree_cleanup()`:
- Run cleanup immediately on first call (startup)
- Then loop every 24h
- Use `asyncio.to_thread(cleanup_stale_worktrees)` since it runs git commands

## What NOT to touch
- `create_worktree()`, `remove_worktree()`, `merge_worktree_to_main()`
- `auto_resume_all()` — cleanup runs after it via `start_background_tasks()`
- DB schema
- Any frontend code

## Edge cases
- Empty WORKTREE_ROOT (no worktrees dir) → function returns early
- Broken worktree (corrupt .git file) → remove_worktree handles gracefully
- Race with spawn → spawn creates session in DB first, then worktree. If cleanup sees dir without session, it's stale
- Race with kill → kill archives session then removes worktree. If cleanup sees archived session with existing dir, it removes it (correct)

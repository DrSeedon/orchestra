# Research: Auto-cleanup stale worktrees

## Current Architecture

### Worktree layout
```
worktrees/
├── <scope_slug>/          # e.g. mnt-data-projects-python-orchestra
│   ├── <worker_name>/     # e.g. backend, fix-security
│   └── ...
├── <scope_slug>/
│   └── ...
```

`WORKTREE_ROOT = Path(__file__).parent.parent / "worktrees"` in `app/workspace.py:14`.
Each scope = slugified `repo_path`. Inside scope dir — one dir per worker.

### Session lifecycle
- `create_session()` → `create_worktree()` → worker runs
- `remove()` (kill_worker) → `remove_worktree()` → `archive_session()`
- `remove_worktree()` calls `git worktree remove --force`

### DB statuses (AgentStatus enum + DB)
- `AgentStatus`: idle, running, waiting (active states)
- DB also has: starting, archived
- Only `archived` and "missing from DB" indicate a dead session

### Key functions
- `remove_worktree(repo_path, worktree_path)` — `workspace.py:573`. Uses lock, calls `git worktree remove --force`
- `get_all_sessions(scope)` — `db.py:523`. Returns non-archived sessions by default
- `auto_resume_all()` — `manager.py:699`. Resumes idle/running/waiting sessions on startup
- `start_background_tasks()` — `manager.py:164`. Starts spawn loop + periodic DB cleanup
- `_periodic_db_cleanup()` — `manager.py:765`. Runs every 6h, cleans old logs

### Worktree path stored in DB
Each session row has `worktree_path` column — the absolute path to its worktree dir.

## Files affected
1. **`app/workspace.py`** — add `cleanup_stale_worktrees()` function
2. **`app/manager.py`** — call cleanup in `start_background_tasks()` + periodic task

## Algorithm
1. List all directories under `WORKTREE_ROOT` (each is a scope dir)
2. Within each scope dir, list subdirectories (each is a worktree)
3. Get all non-archived sessions from DB via `get_all_sessions()`
4. Build set of known worktree_paths from active sessions
5. For each worktree dir not in the set:
   - Check `git status --porcelain` — skip if dirty
   - Call `remove_worktree()` to clean up
   - Log the removal

## Repo path resolution for remove_worktree
`remove_worktree(repo_path, worktree_path)` needs a `repo_path`. It resolves the real repo via `.git` file inside worktree → `gitdir:` → parent. The `repo_path` is only used as fallback for `cwd` when running git commands. We can pass the worktree_path itself since `remove_worktree` reads `.git` file to find real repo.

Actually looking at `remove_worktree` more carefully — it needs `repo_path` only as a fallback `cwd` for the `git worktree remove` command. The function already resolves the actual repo from the `.git` file inside the worktree. So any valid path works as `repo_path` — we can use the scope dir or extract it from the worktree's `.git` file.

## Safety checks
1. **Dirty tree** — `git status --porcelain` before removal. Skip if non-empty output
2. **Active session** — only remove if session is archived or missing from DB
3. **Non-worktree dirs** — check for `.git` file (worktrees have a `.git` file, not a dir)

## Risks
- **Race condition**: worktree being created while cleanup runs → mitigated by checking DB status
- **Broken worktrees**: `.git` file missing/corrupt → `remove_worktree` handles gracefully (logs warning)
- **Non-Orchestra dirs**: random dirs in worktrees/ that aren't git worktrees → `.git` file check filters them

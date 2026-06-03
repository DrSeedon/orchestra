# Plan: 5 Deterministic Guards

## 1. Kill guard — block kill on dirty/unmerged worktree
**Files**: `app/main.py` (DELETE endpoint ~733), `app/mcp_stdio.py` (kill_worker ~253)

**main.py** — before `manager.remove(sid)`:
- Get worktree_path from found session
- If worktree_path exists: run `git status --porcelain` and `git rev-list main..HEAD --count`
- If dirty → 400 with file list
- If unmerged commits > 0 → 400 with count
- Add `force` query param (default False) — skip checks if True

**mcp_stdio.py** — add `force: bool = False` param to kill_worker, pass to API as query param

## 2. Merge/switch dirty details — add file list to error
**File**: `app/workspace.py`

**merge_worktree_to_main** (~line 308-309):
- Parse status.stdout lines, extract file names, include in error

**switch_worktree_branch** (~line 518-519):
- Same treatment

## 3. send_message hint on not found
**File**: `app/main.py` (~line 534)

After both ensure_loaded fail:
- Collect all session names from manager.sessions + DB
- Simple substring/startswith match
- Include similar names in error

## 4. Spawn duplicate — enrich error message
**File**: `app/manager.py` (~line 259-260)

Change ValueError message to include status and context_pct from the existing session.

## 5. owned_dirs overlap — block instead of warn
**File**: `app/manager.py` (~line 267-277)

Change from setting `ownership_warning` to raising `ValueError` when overlap detected.

## Skip
- #5 compact on running — already exists at main.py:558-560

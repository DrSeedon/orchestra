# Research: 6 Deterministic Guards

## Current Architecture

### 1. Kill guard — NO protection exists
- `main.py:733-740` `DELETE /api/sessions/{name}` — calls `manager.remove(sid)` with zero git checks
- `mcp_stdio.py:253-258` `kill_worker` tool — just calls the API, no `force` param
- `manager.remove()` at `manager.py:385-396` disconnects backend, removes worktree, archives session
- **Risk**: agent has uncommitted work or unmerged commits → silently destroyed

### 2. Merge dirty details — PARTIAL (message lacks files)
- `workspace.py:308-309` — checks `git status --porcelain`, returns `"dirty working tree — commit or discard changes first"` with NO file list
- `workspace.py:518-519` `switch_worktree_branch` — same error, no file list
- **Risk**: agent gets "dirty tree" error with no clue which files are dirty

### 3. send_message hint — NO hint on not found
- `main.py:527-534` — tries `ensure_loaded(name, scope)` then `ensure_loaded_any(name)`, returns bare `{"error": "not found"}`
- **Risk**: LLM typos the name → gets "not found" → retries randomly instead of seeing similar names

### 4. Spawn duplicate — EXISTS but message is suboptimal
- `manager.py:259-260` raises `ValueError(f"session '{name}' already exists in scope '{scope}'")`
- `main.py:420-421` catches ValueError → 409
- Message doesn't include status or context_pct — LLM doesn't know if it should send_message instead
- Need to enrich the error message

### 5. Compact on running — ALREADY EXISTS
- `main.py:558-560` checks `session.status.value == "running"` → returns 400 "agent is running, wait for idle"
- **No work needed** ✅

### 6. owned_dirs overlap — EXISTS as WARNING, not block
- `manager.py:267-277` computes overlap, sets `ownership_warning`, logs warning
- Stored in `session._spawn_warning` and returned in response as `spawn_warning`
- Task asks to BLOCK spawn, not just warn
- **BUT**: task text says "НЕ блокировать если owned_dirs пустой" — current code already skips check when `owned_dirs` is empty

## Files Affected
- `app/main.py` — kill endpoint (add git guard), send_message (add hint), spawn (enrich duplicate error)
- `app/mcp_stdio.py` — kill_worker tool (add `force` param)
- `app/workspace.py` — merge_worktree_to_main and switch_worktree_branch (add dirty file list)
- `app/manager.py` — create_session (change owned_dirs overlap from warning to block)

## Risks
- Kill guard: running `git status` / `git rev-list` on a worktree that's being actively used by a running agent — should be safe (read-only git ops)
- owned_dirs block: breaking change — previously only warned, now blocks. But that's the intent.
- send_message hint: iterating all sessions is O(N) but N is tiny (< 50 agents)

## Compact check: SKIP
Already implemented at main.py:558-560. No work needed.

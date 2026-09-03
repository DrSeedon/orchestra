# Report: 5 Deterministic Guards

## What was done
5 guards that prevent LLM mistakes at the API/code level:

1. **Kill guard** — `DELETE /api/sessions/{name}` now checks `git status` and `git rev-list` before removing. Blocks if uncommitted changes or unmerged commits. Added `force` param to override. MCP tool `kill_worker` gets `force: bool` param.

2. **Merge/switch dirty details** — `merge_worktree_to_main` and `switch_worktree_branch` now include file names in "dirty working tree" errors (up to 10 files).

3. **send_message hint** — `POST /api/sessions/{name}/send` now shows similar or available agent names when target not found.

4. **Spawn duplicate enriched** — `create_session` ValueError now shows status and context_pct of existing session, suggests `send_message`.

5. **owned_dirs block** — Changed from warning to hard block. Spawn fails with ValueError if owned_dirs overlap with a running/idle worker.

## Skipped
- **Compact on running** (#5 in original spec) — already implemented at `main.py:558-560`.

## Files changed
- `app/main.py` (+20/-4) — kill guard, send_message hint, get_all_sessions import
- `app/manager.py` (+10/-9) — spawn duplicate error, owned_dirs block
- `app/mcp_stdio.py` (+4/-4) — kill_worker force param, owned_dirs docstring
- `app/workspace.py` (+6/-2) — dirty file list in merge + switch errors

## Tests
- 199 passed, 5 skipped, 6 pre-existing failures (all confirmed on main before changes)
- 34 workspace + create_session tests pass — directly tests guards 2, 4, 5
- Zero new failures introduced

## Breaking changes
- owned_dirs overlap now blocks spawn (was warning). Any spawn with overlapping owned_dirs against a live worker will fail with 409.

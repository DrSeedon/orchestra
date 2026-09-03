# Report — worktree/spawn lifecycle fixes

## Bug 1: injected `.claude/skills/` blocks merge
**Fix:** `app/workspace.py` — new `_exclude_claude_dir(wt_path)`, called in `create_worktree` right after `git worktree add`. Writes `.claude/` to the **common** git-dir `info/exclude` (via `git rev-parse --git-common-dir`), idempotent.

**Key discovery:** git reads `info/exclude` from the COMMON git dir, NOT the per-worktree dir. My first attempt wrote to `$GIT_DIR/info/exclude` (per-worktree) — verified via `git check-ignore` that git silently ignores it. Switched to `--git-common-dir`.

**Tradeoff:** the common exclude is shared with the client repo's main checkout. Acceptable — `.claude/` is agent tooling, never committable; idempotent.

Orchestra's own repo already ignores `.claude/` (`.gitignore:12`) so this only matters for external client repos.

## Bug 2: spawn "session already exists" on archived workers
**Root cause:** the "existing fix" at manager.py:404 was dead code. `get_session_by_name` filters `status != 'archived'` (db.py:610), so `existing` was never an archived row → the delete-archived branch never ran → archived row survived → INSERT hit `UNIQUE(name, scope)` IntegrityError.

**Fix:**
- `app/db.py` — new `delete_archived_session(name, scope)`: `DELETE ... WHERE name=? AND scope=? AND status='archived'` (scope-scoped, never name-only — name is not globally unique).
- `app/manager.py` — replaced the dead `if existing and status=='archived'` branch with an unconditional `delete_archived_session(name, scope)` before INSERT. Simplified the live-exists guard to `if existing:` (archived already filtered out).

**Report's suggested fix was wrong** — it proposed DELETE without scope filter ("name globally unique"). UNIQUE is on `(name, scope)`; broadening would clobber other scopes' archived rows.

## Files
- `app/db.py` (+13): `delete_archived_session`
- `app/manager.py` (+5/-6): wire cleanup, simplify guard
- `app/workspace.py` (+32): `_exclude_claude_dir`
- `tests/test_db.py` (+37): 3 tests (respawn, scope isolation, no-op)
- `tests/test_workspace.py` (+24): 2 tests (not-dirty, idempotent)

## Tests
- `test_db.py` + `test_workspace.py`: 100 pass (5 new), 1 pre-existing fail (`test_rollback_on_copy_failure` — expects `shutil.copy2`, code uses `cp` via `_git_cmd`; fails on clean tree too).
- `test_manager.py` + `test_mcp_stdio.py`: 93 pass, 1 pre-existing flaky fail (`test_db_cwd_is_new_after_inflight_persist` — async persist-loop timing; fails on clean tree too).
- Full suite not run — test lock held by test-sonnet5. Changes are narrow (3 modules), covered by the above.

## Breaking
None.

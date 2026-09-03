## Summary

Reviewed `docs/tasks/git-safety/impl.diff` against the full staged files.

No blocking issues found. The owned_dirs persistence path is wired correctly: `_migrate()` adds the column even for a fresh DB, `save_session()` includes it on insert/update, `AgentSession._to_db_dict()` stores JSON text, and `_load_from_db()` rehydrates through `parse_owned_dirs()`. The transient `_spawn_warning` lifecycle also looks correct for the direct API/MCP spawn path: it is set before return, not persisted, and folded with the auto-commit warning.

I found three correctness suggestions in git subprocess edge cases.

## Findings (blocking/suggestion/question)

### suggestion: `worker_wip` reports clean when the base ref cannot be resolved

`branch_wip_status()` ignores the return code from `git log <base_ref>..HEAD` and maps any failure to an empty `unmerged_commits` list. With a missing/default-wrong base ref, the MCP response can say the worker is clean even though the comparison did not run.

Reference: `app/workspace.py:633-638`, `app/mcp_stdio.py:382-385`

I verified this with a temp repo: `branch_wip_status(repo, "refs/heads/no-such-base")` returned `{"uncommitted": [], "unmerged_commits": []}` after an extra commit on `HEAD`.

Suggested fix: if `git log` returns non-zero, return an error such as `{"error": "base_ref ... not found: ..."}` instead of an empty list. Also check `git status` return code in the same helper so status failures do not become a clean worktree.

### suggestion: `_auto_commit_if_dirty()` still ignores the initial `git status` failure

The new helper checks `git add` and `git commit`, but it decides the repo is clean solely from `r.stdout`. If `git status --porcelain` fails with no stdout, the helper returns `""`, spawn proceeds, and the orchestrator gets no warning that auto-save did not run.

Reference: `app/manager.py:343-345`

Suggested fix: check `r.returncode` before reading `r.stdout`; on non-zero, return a visible warning like the add/commit failures. This keeps the advisory behavior while avoiding a false “no warning means clean” result.

### suggestion: `simulate_conflict()` misreports modify/delete conflict paths

Conflict detection works, but the file parser uses `line.split()[-1]` for every `CONFLICT` line. For modify/delete conflicts, Git prints text like `CONFLICT (modify/delete): f.txt deleted in a and modified in b. Version b of f.txt left in tree.`, so the helper reports `tree.` as the conflict path instead of `f.txt`.

Reference: `app/workspace.py:620`

I verified this with a temp repo where one branch deleted `f.txt` and the other modified it; `simulate_conflict(repo, "a", "b")` returned `{"ok": True, "conflicts": ["tree."]}`.

Suggested fix: parse conflict lines by type. A small regex for `Merge conflict in (.+)$` and `CONFLICT (modify/delete): (\S+) ` would cover the common `merge-tree` formats better; alternatively, after a non-zero merge-tree result, use the staged records in stdout to derive conflicted paths.

## Verdict

Proceed after addressing the suggestions if you want the new safety tools to avoid misleading “clean/safe” output in edge cases. None of the findings are blocking for an MVP rollout, and the owned_dirs roundtrip plus warning plumbing are sound.

## Tests
Found `tests/`. `pytest` was started, but the full run hung after reporting early errors/failures; I killed the stale pytest process and ran focused checks:
- `pytest tests/test_api.py -x` fails at fixture setup because `AgentSession` no longer has `_make_client`.
- `pytest tests/test_workspace.py` fails 10/16 because test repos initialize their default branch differently and `create_worktree()` hardcodes `main`.

## Summary
The new plain-number display path is mostly wired through the task API and MCP output, and legacy prefixed inputs are still accepted by `_parse_task_ref()` and `_normalize_task_id()`. The unsafe part is that several paths now discard the project prefix before resolving a task, while the database only guarantees `par_number` uniqueness inside a project. That can link commits or updates to the wrong task when `PAR-3` and `ORC-3` both exist, which is exactly the kind of collision this change has to handle. Existing `PAR-N/...` worktree branches should still load and merge, but the commit-linking and YouGile transition need fixes before merge.

## Findings
blocking: app/workspace.py:225 — `_parse_merged_commits()` matches legacy `PAR-49` / `ORC-3` commit messages but returns only `"49"` / `"3"`, so `link_commits_to_task()` loses the prefix and may attach commits to the first task with that number in any project. Fix: when groups 1/2 match, keep `f"{prefix}-{num}"`; only use bare `num` for `#N` matches.

blocking: app/tm.py:286 — plain `#N` / `N` lookup uses `ORDER BY id ASC LIMIT 1`, but `par_number` is unique only per project (`idx_tm_tasks_par_project`). Once prefixes are hidden, `#3` is ambiguous and can update/get/link the wrong task if different projects share number 3. Fix: either migrate/enforce globally unique task numbers before exposing plain refs, or resolve plain refs with project/scope context and fail on ambiguity.

suggestion: app/tm_yougile.py:113 — YouGile crash-recovery lookup now searches only `idTaskProject == "49"` and new creates write `"49"`, but existing YouGile tasks may still have `idTaskProject == "PAR-49"`. A task missing local `yougile_task_id` can fail to find the existing remote task and create a duplicate. Fix: during the transition, search both bare and legacy labels based on the task project prefix, or keep writing the legacy external id until YouGile is migrated.

suggestion: app/static/js/app.js:1184 — tool previews blindly render `#${parsed.par}`, so a backward-compatible call like `task_update(par="PAR-49")` displays `#PAR-49`; the task side panel also displays bare `49` at app/static/js/app.js:3806 instead of `#49`. Fix: add a small formatter that strips an optional legacy prefix and prepends exactly one `#`, and use it in all task displays.

suggestion: app/mcp_stdio.py:294 — the public MCP tool docstring still starts with “Returns PAR number,” even though the schema now returns plain numbers. This is agent-facing text, so it can keep generating old-format expectations. Fix: change that sentence to “Returns task number and task details.”

## Verdict
needs fixes

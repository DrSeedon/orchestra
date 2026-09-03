# Plan: Rebase PR #2 (feat/pipeline-as-config) onto main

## Strategy
**Merge main into PR branch** (not rebase — 16 PR commits + 30 main commits = rebase hell).
Create a fresh branch from main, then merge PR in with manual conflict resolution.

Actually better: **start from main, merge vadim/feat/pipeline-as-config INTO it**.
This way main is the "base" and PR's changes are layered on top — conflicts default to main's version.

## Branch setup
```
git checkout -b feat/pipeline-as-config-rebased main
git merge --no-commit vadim/feat/pipeline-as-config
# resolve 4 conflicting files manually
# verify auto-merged files are correct
git commit
```

## File-by-file conflict resolution

### 1. app/backend_claude.py (1 conflict)
**Conflict**: main removed system_prompt line, PR added config_dir/inherit_claude_md/user_mcp_servers params.
**Resolution**: Take BOTH — main's cleanup + PR's new params.
- Keep PR's new `__init__` params: `config_dir`, `inherit_claude_md`, `user_mcp_servers`
- Keep PR's new `self._config_dir`, `self._inherit_claude_md`, `self._user_mcp_servers` in __init__
- Keep PR's `CLAUDE_CONFIG_DIR` env override in `_make_client`
- Keep PR's conditional `system_prompt` handling (inherit_claude_md)
- Keep PR's 3-layer MCP merge (`user_mcp_servers -> scope -> custom`)
- Keep PR's conditional `setting_sources`

### 2. app/main.py (1 conflict, but massive divergence)
**Conflict**: imports differ.
**Resolution**: Keep main's architecture (split routes, deps.py) + add PR's new imports/endpoints.
- Keep main's `from app.deps import manager`
- Add PR's `from app.db import list_profiles, upsert_profile, delete_profile`
- Add PR's `from app.pipeline import list_pipelines`
- Keep main's routes split (`from app.routes.*`)
- Add PR's new endpoints: `/api/pipelines`, `/api/profiles` (CRUD)
- Add PR's new Pydantic model `ProfileRequest`
- Add `pipeline` + `profile` params to SpawnRequest and spawn_worker endpoint
- Keep main's `_DENIED_PARTS` (extended set with .npmrc, .pypirc, etc.)
- Keep main's `needs_switch` guard in send endpoint
- Keep main's visibility in send response (parent_name)
- Keep main's kill_worker `force` param + guards
- Keep main's merge `next_task_id` handling
- Keep main's route import helper (`get_role_icons` from `app.prompting`)

### 3. app/manager.py (8 conflicts — HEAVIEST)
**Resolution**: Keep main's code as base. Add PR's pipeline-specific additions.

What to KEEP from main:
- Import from `app.prompting` (not inline functions)
- `_workers_block(scope, orchestrator_name)` — visibility filter
- `owned_dirs` BLOCK (raise ValueError), not warning
- `needs_switch` guard (session field, not deleted)
- `create_session` signature: main's guards + PR's pipeline/profile/docs_feature params
- Kill guards (running/dirty/unmerged checks)
- `prompt_template_hash` from prompting.py

What to ADD from PR:
- `from app.pipeline import ...` — pipeline imports
- `get_active_profile()` function
- `_scaffold_role_docs()` function
- Pipeline/profile params in `create_session`
- Pipeline resolution logic in `create_session`
- Profile resolution logic in `create_session`
- `_resolve_base_branch()` method
- `_resolve_pipeline()`, `_resolve_profile()` helper methods
- `ROLE_SYSTEM_PROMPT` signature change: add `pipeline` param
- Pipeline-aware spawn validation (`validate_spawn`)
- `_roles_catalog_from_manifest()` for manifest-aware role catalog
- `_UPSTREAM_ROLE_SYSTEM_PROMPT()` as fallback
- Worktree config from manifest
- Skills injection gating (`skills=="all"`)
- AgentSession: `pipeline`, `profile` fields in constructor

What to DELETE from PR:
- ALL inlined prompt functions (`_safe_format_prompt`, `_read_prompt`, `_parse_role_frontmatter`, `_load_modules`, `_role_prompt_file`, `_role_can_spawn`, `_skills_catalog`, `get_role_icons`, `_roles_catalog`, `_prompt_template_hash`) — use `app.prompting` instead
- `is_orchestrator_role` in session.py — use from `app.prompting`

### 4. app/session.py (auto-merged, verify)
Verify both sets of changes are present:
- Main's: `needs_switch` field, `parent_name` handling, `BackendLike` TYPE_CHECKING, mid-turn inject logic, `_apply_turn_result`/`_update_context_from_turn`/`_finish_turn_status`/`_after_turn_idle_actions` split methods
- PR's: `pipeline`/`profile` fields, `_is_orchestrator` property, `_load_user_mcp_servers`, backend config_dir/inherit/user_mcp, `_to_db_dict` pipeline/profile

### 5. app/mcp_stdio.py (auto-merged, verify)
Verify both:
- Main's: visibility in list_agents/send_message, force param on kill, next_task_id on merge
- PR's: base_branch="" default, pipeline/profile params in spawn docstring

### 6. app/static/js/app.js (auto-merged, verify)
Should contain both main's front fixes and PR's profile/pipeline UI additions.

### 7. app/workspace.py (auto-merged, verify)
Should contain both main's cleanup logic and PR's worktree config from manifest.

### 8. tests/test_manager.py (1 conflict)
**Resolution**: Keep BOTH sets of tests. Main's guard tests + PR's pipeline tests.

### 9. tests/test_workspace.py (auto-merged, verify)
Both test sets should be present.

## New files from PR (no conflicts, copy as-is)
- `app/pipeline.py` — core pipeline module
- `app/db.py` changes — profiles table
- `pipelines/` directory — all yaml/prompts
- `scripts/extract-manifest.py`
- `tests/test_pipeline.py`, `test_default_pipeline.py`, `test_default_equals_upstream.py`, `test_scaffold.py`, `test_tasks_pm_pipeline.py`
- `app/templates/dashboard.html` changes — profile UI

## Post-merge pipeline.py fixup
PR's `pipeline.py` imports `is_orchestrator_role` from `session.py`.
In main, this lives in `prompting.py`. Need to either:
a) Keep it in both places (session.py for pipeline.py to use) — NO, DRY violation
b) Change pipeline.py to import from prompting.py — YES

## Post-merge prompting.py changes
`ROLE_SYSTEM_PROMPT` currently lives in both `prompting.py` (main) and `manager.py` (main's version).
Wait — in main, `ROLE_SYSTEM_PROMPT` is in `manager.py`, not `prompting.py`. `prompting.py` has the helpers.

So the plan is:
1. Keep `prompting.py` with helper functions
2. In `manager.py`, replace inline duplicates with imports from `prompting.py`
3. Add PR's pipeline-aware `ROLE_SYSTEM_PROMPT` (with `pipeline` param) that falls back to upstream logic
4. `_UPSTREAM_ROLE_SYSTEM_PROMPT` uses `prompting.py` helpers
5. New pipeline functions from PR's manager.py: keep them in manager.py (they need manager context)

## Deleted roles handling
Main deleted `app/prompts/roles/reviewer.md` and `watcher.md`.
PR has them in `pipelines/default/prompts/roles/`. These are separate paths — no conflict.
But `test_default_equals_upstream.py` may expect them in `app/prompts/`. Will need adjustment.

## Risk areas
1. `session.py` auto-merge may have missed mid-turn inject logic — VERIFY
2. `pipeline.py` may reference functions that moved to `prompting.py` — FIX imports
3. `test_default_equals_upstream.py` compares pipeline defaults with upstream — may fail if upstream roles changed
4. `is_orchestrator_role` location: PR puts it in `session.py`, main in `prompting.py` — decide one location

## Test plan
1. `uv run pytest -x -q` — all tests pass
2. Focus on: `test_manager.py`, `test_pipeline.py`, `test_default_equals_upstream.py`
3. Verify no import errors at startup

## NOT touching
- `app/routes/` — main's split routes, not modified by PR
- `app/prompting.py` — main's module, keep as-is, only maybe add to it
- `CHANGELOG.md`, `TODO.md` — will update after implementation
- Systemd, deployment — not relevant

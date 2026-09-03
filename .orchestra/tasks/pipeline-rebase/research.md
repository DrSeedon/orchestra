# Research: Rebase PR #2 (feat/pipeline-as-config) onto main

## Merge Base
- Merge base: `101f086` (v2.16.0)
- PR: 16 commits (Vadim, `vadim/feat/pipeline-as-config`)
- Main since merge base: ~30 commits (v2.16 → v2.18+)

## Overlapping Files (modified in BOTH branches)
1. `app/backend_claude.py` — 1 conflict
2. `app/main.py` — 1 conflict (but massive architectural divergence)
3. `app/manager.py` — 8 conflicts (heaviest)
4. `app/mcp_stdio.py` — auto-merged
5. `app/session.py` — auto-merged
6. `app/static/js/app.js` — auto-merged
7. `app/workspace.py` — auto-merged
8. `tests/test_manager.py` — 1 conflict
9. `tests/test_workspace.py` — auto-merged

## Key Architectural Conflicts

### 1. prompting.py vs inlined functions in manager.py
**Main**: extracted `app/prompting.py` module with all prompt functions:
- `is_orchestrator_role`, `safe_format_prompt`, `read_prompt`
- `role_prompt_file`, `role_can_spawn`, `roles_catalog`, `skills_catalog`
- `prompt_template_hash`, `inject_skills_to_worktree`

**PR**: duplicated ALL these functions into `app/manager.py` with `_` prefixes, plus added pipeline-specific functions.

**Resolution**: Keep main's `prompting.py`. PR's pipeline-specific functions go into `app/pipeline.py` (new file from PR). Bridge: `pipeline.py` can import from `prompting.py` where needed.

### 2. deps.py (singleton manager)
**Main**: `app/deps.py` — `manager = SessionManager()` singleton
**PR**: `manager = SessionManager()` in `app/main.py`

**Resolution**: Keep main's `deps.py`.

### 3. main.py split routes
**Main**: routes split into `app/routes/{tm,bg,proxy}.py`
**PR**: new endpoints (pipelines, profiles) added directly to `main.py`

**Resolution**: Keep main's split routes. Add PR's new endpoints to main.py (they're small enough) or create `app/routes/pipeline.py`.

### 4. manager.py — guards, visibility, cleanup
**Main additions**:
- `_workers_block()` → visibility filter by `parent_name` (mine vs others' workers)
- `needs_switch` guard in session handling
- `owned_dirs` block on spawn
- Kill guards (running check, dirty check, unmerged check)
- Worktree cleanup logic

**PR additions**:
- `ROLE_SYSTEM_PROMPT` → takes `pipeline` param
- `get_active_pipeline()`, `get_active_profile()` functions
- `_scaffold_role_docs()` — doc scaffolding from manifest
- `validate_spawn()` — pipeline-based spawn validation
- `_roles_catalog_from_manifest()` — manifest-based role catalog

**Resolution**: Keep ALL main's guards/visibility. Layer PR's pipeline logic on top. ROLE_SYSTEM_PROMPT gets `pipeline` param but still has upstream fallback.

### 5. session.py
**Main**: added `needs_switch` field, `parent_name` handling
**PR**: added pipeline/profile fields, `is_orchestrator` stored field

Auto-merged, but need to verify both sets of fields are present.

### 6. backend_claude.py
**Main**: minor change (removed one line about system_prompt)
**PR**: added `config_dir`, `inherit_claude_md`, `user_mcp_servers` params

**Resolution**: Take PR's additions, apply main's cleanup.

## New Files from PR (no conflicts)
- `app/pipeline.py` — pipeline loader, schema, resolver (487 lines)
- `pipelines/default/` — YAML manifest + prompts for default pipeline
- `pipelines/tasks-pm/` — PM pipeline example
- `scripts/extract-manifest.py` — utility script
- `tests/test_pipeline.py` — pipeline tests (786 lines)
- `tests/test_default_pipeline.py` — default pipeline tests
- `tests/test_default_equals_upstream.py` — equality proof tests
- `tests/test_scaffold.py` — doc scaffold tests
- `tests/test_tasks_pm_pipeline.py` — PM pipeline tests
- `app/db.py` changes — profiles table, CRUD
- `app/templates/dashboard.html` changes — profile/pipeline UI

## Roles Deleted in Main
Main removed: `app/prompts/roles/reviewer.md`, `app/prompts/roles/watcher.md`
PR includes: `pipelines/default/prompts/roles/reviewer.md`, `pipelines/default/prompts/roles/watcher.md`

**Resolution**: These are in `pipelines/default/` (PR's manifest), not `app/prompts/`. Keep them in the pipeline dir — they're part of the pipeline config, not active upstream roles.

## Risks
1. `manager.py` is the most complex merge — 8 conflicts, massive code divergence
2. PR's `ROLE_SYSTEM_PROMPT` signature change (`pipeline` param) affects every caller
3. PR duplicated prompting functions that main extracted to `prompting.py` — deduplication needed
4. Tests reference both old and new function signatures
5. `main.py` routes architecture completely different — needs careful port of new endpoints

## Strategy
**Approach: Merge main into PR branch, resolve conflicts favoring main's architecture.**
1. Start from main, apply PR's new files wholesale
2. For conflicting files: take main's version as base, layer PR's additions
3. Specifically for manager.py: keep main's imports from prompting.py, add pipeline params to ROLE_SYSTEM_PROMPT
4. PR's inlined prompt functions in manager.py → delete (use prompting.py instead)
5. Run all tests to verify

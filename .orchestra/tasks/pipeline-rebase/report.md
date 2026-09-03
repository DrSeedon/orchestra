# Report: Rebase PR #2 (feat/pipeline-as-config) onto main

## What was done
Merged Vadim's pipeline-as-config PR (16 commits, v2.16 base) onto current main (v2.18+, ~30 commits ahead). Manual conflict resolution in 4 files, with 5 auto-merged files verified.

## Conflict resolution
1. **app/backend_claude.py** (1 conflict): Took PR's conditional system_prompt + 3-layer MCP merge
2. **app/main.py** (1 conflict): Kept main's deps.py + split routes, added PR's profile/pipeline imports
3. **app/manager.py** (8 conflicts): Biggest merge. Kept prompting.py imports, removed PR's inlined duplicates, added pipeline-aware ROLE_SYSTEM_PROMPT with upstream fallback, kept main's visibility/guards
4. **tests/test_manager.py** (1 conflict): Both sets of patches, fixed import targets

## Post-merge fixes
- **Deduplication**: Removed ~200 lines of inlined prompt functions from manager.py (use prompting.py)
- **Deleted roles**: Removed reviewer/watcher from default pipeline (deleted in main v2.18)
- **Module sync**: Added orchestration.md module, removed codex-review module, added codex-debate skill
- **Role file sync**: Copied current upstream role bodies into pipeline defaults
- **Test updates**: Fixed 15+ test references to moved/deleted functions and roles
- **base_branch=""**: Preserved for pipeline branch strategy (Codex finding #2)

## Files changed
55 files, +14195/-452 lines (including pipeline configs, prompts, tests)

Key code files:
- app/manager.py (+317/-135) — pipeline-aware prompts, scaffold, resolve helpers
- app/pipeline.py (+487 new) — core pipeline loader, schema, resolver
- app/session.py (+62) — pipeline/profile fields, is_orchestrator property
- app/backend_claude.py (+37) — config_dir, inherit_claude_md, user_mcp
- app/db.py (+64) — profiles table, pipeline/profile columns
- app/main.py (+70) — profile/pipeline CRUD endpoints

## Tests
486 passed, 5 skipped (skips are pre-existing, not regression)

## Codex reviews
1. **Plan review**: 10 findings, all addressed (base_branch, is_orchestrator, db.py verification, etc.)
2. **Impl review**: Code analysis completed, no blocking findings

## Breaking changes
None — all existing functionality preserved. Pipeline features are additive (default pipeline = upstream behavior).

## What's preserved from main
- Visibility guards (_workers_block with parent_name filtering)
- owned_dirs BLOCK (raise, not warn)
- needs_switch guard
- Kill guards (running/dirty/unmerged checks)
- Split routes (app/routes/)
- prompting.py extraction
- codex-debate skill
- Worktree cleanup

## What's preserved from PR
- Pipeline YAML manifests (pipelines/default/, pipelines/tasks-pm/)
- Profile system (DB + CRUD API)
- Pipeline-aware ROLE_SYSTEM_PROMPT with upstream fallback
- Worktree config from manifest (symlinks, copies)
- Skills injection gating (skills=="all")
- Doc scaffolding from manifest
- Base branch strategy resolution
- extract-manifest.py utility
- Full test suite (test_pipeline, test_default_pipeline, test_scaffold, etc.)

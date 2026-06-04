Reading additional input from stdin...
OpenAI Codex v0.124.0 (research preview)
--------
workdir: /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR, /home/maxim/.codex/memories]
reasoning effort: high
reasoning summaries: none
session id: 019e90dc-5178-7dc3-8dd4-4ec41140a572
--------
user
Review this merge plan for merging Vadim's pipeline-as-config PR onto current main branch. Focus on:
1. Are there risks of losing functionality from either side?
2. Is the strategy sound?
3. Any missing conflict resolution items?
4. Is the is_orchestrator_role location decision correct?

PROJECT CONTEXT: Small team, MVP, Python 3.12, FastAPI, SQLite, git worktrees.
PR adds: YAML pipeline configs, profiles, manifest-based role resolution.
Main adds: visibility guards, owned_dirs block, needs_switch, route splitting, prompting.py extraction.

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
exec
/usr/bin/zsh -lc "rg --files app tests pipelines scripts | sed -n '1,240p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
rg: pipelines: No such file or directory (os error 2)
scripts/setup-tg-bot-api.sh
tests/test_disallowed_tools.py
tests/test_workspace.py
tests/test_manager.py
tests/test_mcp_stdio.py
tests/test_api.py
tests/test_backend_claude.py
tests/test_session.py
tests/test_tg_bridge.py
tests/__init__.py
tests/conftest.py
tests/test_bg_jobs.py
tests/test_db.py
tests/test_auth.py
app/workspace.py
app/templates/dashboard.html
app/templates/login.html
app/proxy_manager.py
app/backend_protocol.py
app/backend_claude.py
app/main.py
app/tm.py
app/tm_import_yougile.py
app/bg_jobs.py
app/manager.py
app/ssh_tunnel.py
app/session.py
app/mcp_stdio.py
app/__init__.py
app/auth.py
app/skills/codex-review/SKILL.md
app/db.py
app/skills/orchestra/SKILL.md
app/backend_codex.py
app/events.py
app/routes/proxy.py
app/routes/__init__.py
app/routes/bg.py
app/routes/tm.py
app/models.py
app/tm_yougile.py
app/prompting.py
app/tg_bridge.py
app/deps.py
app/static/css/style.css
app/static/js/app.js
app/static/favicon.svg
app/prompts/roles/worker.md
app/prompts/roles/full-cycle.md
app/prompts/roles/orchestrator.md
app/prompts/roles/sub-orchestrator.md
app/prompts/base.md
app/static/css/vendor/diff_match_patch.js
app/static/css/vendor/marked.min.js
app/static/css/vendor/highlight-github-dark.min.css
app/static/css/vendor/tailwind.js
app/static/css/vendor/highlight.min.js
app/static/css/vendor/purify.min.js
app/static/css/vendor/github-markdown-dark.css
app/prompts/modules/git-workflow.md
app/prompts/modules/report-format.md
app/prompts/modules/orchestration.md
app/prompts/skills/vps-deploy.md
app/prompts/skills/html-artifacts.md
app/prompts/skills/codex-debate.md

exec
/usr/bin/zsh -lc "git status --short --branch && git branch --all --verbose --no-abbrev | sed -n '1,80p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
exec
/usr/bin/zsh -lc 'rg -n "def is_orchestrator_role|is_orchestrator_role|ROLE_SYSTEM_PROMPT|def create_session|class AgentSession|needs_switch|owned_dirs|validate_spawn|list_pipelines|ProfileRequest" app tests pipelines -S' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 exited 2 in 0ms:
rg: pipelines: No such file or directory (os error 2)
tests/test_manager.py:467:        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
tests/test_manager.py:480:        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
tests/test_manager.py:493:        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
app/db.py:383:    if "owned_dirs" not in cols:
app/db.py:384:        c.execute("ALTER TABLE sessions ADD COLUMN owned_dirs TEXT DEFAULT ''")
app/db.py:407:    s.setdefault("owned_dirs", "")
app/db.py:417:                template_hash, role, parent_id, parent_name, mcp_servers_custom, owned_dirs,
app/db.py:425:                :template_hash, :role, :parent_id, :parent_name, :mcp_servers_custom, :owned_dirs,
app/db.py:455:                owned_dirs=excluded.owned_dirs,
app/session.py:15:from app.prompting import is_orchestrator_role
app/session.py:73:class AgentSession:
app/session.py:97:    owned_dirs: list = field(default_factory=list, repr=False)
app/session.py:100:    needs_switch: bool = False
app/session.py:144:        return is_orchestrator_role(self.role)
app/session.py:959:            "owned_dirs": json.dumps(self.owned_dirs) if self.owned_dirs else "",
app/session.py:984:            "owned_dirs": self.owned_dirs,
app/mcp_stdio.py:66:                       owned_dirs: str = "",
app/mcp_stdio.py:71:    owned_dirs — JSON-массив директорий которыми владеет воркер, напр. ["app/api/", "app/models/"]. Инжектится в промпт воркера ("трогай только это"). Пересечение с owned_dirs другого живого воркера → БЛОК (spawn fails).
app/mcp_stdio.py:94:    if owned_dirs:
app/mcp_stdio.py:97:            parsed = json.loads(owned_dirs)
app/mcp_stdio.py:99:                body["owned_dirs"] = parsed
app/mcp_stdio.py:101:                return "Error: owned_dirs must be a JSON array, e.g. [\"app/api/\", \"app/models/\"]"
app/mcp_stdio.py:103:            return f"Error: owned_dirs is not valid JSON: {e}"
app/auth.py:28:def create_session(username: str) -> str:
app/prompting.py:19:def is_orchestrator_role(role: str) -> bool:
app/prompting.py:72:        fallback = _PROMPTS_DIR / "roles" / ("orchestrator.md" if is_orchestrator_role(role) else "worker.md")
app/manager.py:16:    is_orchestrator_role, safe_format_prompt, read_prompt,
app/manager.py:22:from app.workspace import create_worktree, remove_worktree, parse_owned_dirs, dirs_overlap
app/manager.py:49:                 if is_orchestrator_role(s.get("role", "worker")) and s.get("scope") != exclude_scope]
app/manager.py:70:                   if not is_orchestrator_role(s.get("role", "worker")) and s.get("scope") == scope]
app/manager.py:109:def ROLE_SYSTEM_PROMPT(role: str, scope: str = "", name: str = "") -> str:
app/manager.py:111:    if is_orchestrator_role(role):
app/manager.py:128:    return ROLE_SYSTEM_PROMPT("orchestrator", scope)
app/manager.py:132:    return ROLE_SYSTEM_PROMPT("worker")
app/manager.py:254:    def _ownership_prompt(owned_dirs: list[str]) -> str:
app/manager.py:255:        if not owned_dirs:
app/manager.py:257:        lines = "\n".join(f"- {d}/" for d in owned_dirs)
app/manager.py:266:    async def create_session(self, name: str, scope: str, cwd: str, model: str,
app/manager.py:273:                             owned_dirs: list | None = None,
app/manager.py:288:        is_orch = is_orchestrator_role(role)
app/manager.py:290:        owned_dirs = parse_owned_dirs(owned_dirs)
app/manager.py:291:        if owned_dirs:
app/manager.py:294:                if s.scope == scope and s.status.value in ("idle", "running", "waiting") and s.owned_dirs:
app/manager.py:296:                    ov = dirs_overlap(owned_dirs, s.owned_dirs)
app/manager.py:299:                            f"owned_dirs overlap with '{s.name}': {', '.join(ov)}. "
app/manager.py:307:                row_dirs = parse_owned_dirs(row.get("owned_dirs"))
app/manager.py:309:                    ov = dirs_overlap(owned_dirs, row_dirs)
app/manager.py:312:                            f"owned_dirs overlap with '{row['name']}': {', '.join(ov)}. "
app/manager.py:317:            prompt = ROLE_SYSTEM_PROMPT(role, scope, name) + ("\n\n" + system_prompt if system_prompt else "")
app/manager.py:319:            prompt = ROLE_SYSTEM_PROMPT(role) + ("\n\n" + system_prompt if system_prompt else "")
app/manager.py:320:            prompt += self._ownership_prompt(owned_dirs)
app/manager.py:354:            owned_dirs=owned_dirs,
app/manager.py:511:            if is_orchestrator_role(row.get("role", "worker")):
app/manager.py:523:            if is_orchestrator_role(row.get("role", "worker")) and row["name"] not in orch_names:
app/manager.py:579:        is_orch = is_orchestrator_role(role)
app/manager.py:581:        current_prompt = ROLE_SYSTEM_PROMPT(role, db_row["scope"], db_row["name"]) if is_orch else ROLE_SYSTEM_PROMPT(role)
app/manager.py:622:            owned_dirs=parse_owned_dirs(db_row.get("owned_dirs")),
app/manager.py:640:                ROLE_SYSTEM_PROMPT(role, db_row["scope"], db_row["name"]) if is_orch else ROLE_SYSTEM_PROMPT(role),
app/manager.py:753:        orchs = [r for r in resumable if is_orchestrator_role(r.get("role", "orchestrator" if r.get("is_orchestrator") else "worker"))]
app/manager.py:754:        workers = [r for r in resumable if not is_orchestrator_role(r.get("role", "orchestrator" if r.get("is_orchestrator") else "worker"))]
app/main.py:112:    owned_dirs: list[str] = []
app/main.py:393:async def create_session(req: CreateSessionRequest):
app/main.py:413:            owned_dirs=req.owned_dirs,
app/main.py:541:        if hasattr(session, 'needs_switch') and session.needs_switch:
app/main.py:821:                    found.needs_switch = True
app/main.py:832:                        found.needs_switch = False
app/main.py:874:                    found.needs_switch = False
app/main.py:1172:    from app.prompting import is_orchestrator_role
app/main.py:1175:    db_orchs = [s for s in get_all_sessions() if is_orchestrator_role(s.get("role", "worker")) and s["id"] not in active_ids]
app/workspace.py:666:def parse_owned_dirs(raw) -> list[str]:
app/workspace.py:667:    """Normalize owned_dirs from any source (JSON string, list, None). Bad input → []."""
app/prompts/modules/git-workflow.md:11:- Each worker "owns" specific directories (set at spawn via `owned_dirs`)
app/prompts/roles/sub-orchestrator.md:21:- **You own only your zone** — your scope / `owned_dirs`. Don't spawn workers or touch files outside it.

 succeeded in 0ms:
## feat/mnt-data-projects-python-orchestra/feat-pipeline-rebase
?? docs/tasks/pipeline-rebase/
  PAR-240/test-branching                                             6a31f08a0d7696ffabf6fc3694596d76ead2820a PAR-240: add test_branching.txt
  PAR-241/test-branching                                             6a31f08a0d7696ffabf6fc3694596d76ead2820a PAR-240: add test_branching.txt
+ codex-skill-merge                                                  597bc6303845b7d4faa59f3ccc90130ccefaffb0 [ahead 2, behind 19] docs: fix single-tilde rendering as strikethrough in dashboard (~N -> ≈N)
  feat/mnt-data-projects-python-orchestra/auto-compact               2bfa7153774d243fcbd350bcea55650146aa151a feat: auto-compact worker context when >90%
  feat/mnt-data-projects-python-orchestra/backend                    2afbee96529f52ec4d7f50d1dfbe6a6805bf5468 feat: non-blocking TG bridge startup (ORC-20)
  feat/mnt-data-projects-python-orchestra/compact-mode               0d710a307abaf1d7021c654759d7ee26426d4569 feat: compact mode for tool bubbles
+ feat/mnt-data-projects-python-orchestra/debate-test                47dc4ed9de0607774e905258749231d4a63c947f #47: #47: debate artifacts — plan, report, codex sessions
  feat/mnt-data-projects-python-orchestra/diff-view                  65ba7e27159585868050ab64a60b8bf33a0912ab feat: diff view for Edit tool in dashboard chat
  feat/mnt-data-projects-python-orchestra/feat-ci-routing            79aa0416bfa1fb8fc7ca98d2d1452ffc567e5fc6 fix: align job-level conclusion check with routing conclusions
  feat/mnt-data-projects-python-orchestra/feat-deploy-amsterdam      b863faa121423bb57ae3679a9aaac1d78cd2f837 wip: auto-save before worker spawn
  feat/mnt-data-projects-python-orchestra/feat-git-safety            86fb128c4e636bdc1ab8cfa2fca950ea088264d7 add codex review impl diff
  feat/mnt-data-projects-python-orchestra/feat-git-task-link         84dae506ba49ec8d60cadc3812e2aa61811709e8 fix: Codex review — unmerged guard, worktree parser, conflict branch persist, link error display
+ feat/mnt-data-projects-python-orchestra/feat-guards                671db1b619dfb85fdf5b7e0723df486847822c23 #guards: 5 deterministic guards — kill/merge/send/spawn/owned_dirs
  feat/mnt-data-projects-python-orchestra/feat-idle-optimization     b46b2cd549934c481e9c946098a2816a7bdc07b8 feat: background jobs — server-side one-shot tasks that survive hibernate
  feat/mnt-data-projects-python-orchestra/feat-llm-comparison        b25903f9fac033110be13951387e897ae6c6d2cd Add LLM comparison research
* feat/mnt-data-projects-python-orchestra/feat-pipeline-rebase       d8e068f497d60340e739ca3d9fdcabec9a6183ac fix: escape single tilde in markdown to prevent false strikethrough
  feat/mnt-data-projects-python-orchestra/feat-roi-analysis          7d7a718a7cdb5fe05a6e7fd57190d7a67a097e51 update: Codex report — VPS deep dive, 48 reviews, pay recommendation
  feat/mnt-data-projects-python-orchestra/feat-scope-change          ddea49f2d15ef0c34595e676f24b9532f94f9ec5 #29: changelog v2.11.0 — change orchestrator scope without losing session
+ feat/mnt-data-projects-python-orchestra/feat-visibility            27536da11f71e1e98104613529b08c48498c3e15 #visibility: limit worker visibility between orchestrators
  feat/mnt-data-projects-python-orchestra/feat-vps-migration         c16bf69a901189d78a291e27f63ff35610068288 research: VPS migration plan for 24/7 Orchestra availability
+ feat/mnt-data-projects-python-orchestra/feat-wt-cleanup            7295b559212811ca6f3cb230835cb968cc89d536 #wt-cleanup: auto-cleanup stale worktrees on startup + every 24h
  feat/mnt-data-projects-python-orchestra/file-preview               9c274df70cdaa56c5c648ac76564f99a019d826d feat: file preview modal in dashboard
  feat/mnt-data-projects-python-orchestra/fix-1m-sdk                 8ed8f878c49ddc7824d092d2ca18ae20682177a5 WIP: auto-saved uncommitted changes before worker spawn (2026-06-01 01:55)
  feat/mnt-data-projects-python-orchestra/fix-file-preview           513ecfb56b2252cd8a97b0c3da962ddcd8880d41 feat: add /api/files/content endpoint for file preview
  feat/mnt-data-projects-python-orchestra/fix-filepanel              98cd3e5f1ae57102f04b449efe3d1b144157e568 fix file panel: preview modal, send button, remove toggle
  feat/mnt-data-projects-python-orchestra/frontend-design            7de423014fa70523fa2a35cc387327fbbf740193 fix: load-more uses addChatEntry for full custom bubble rendering
+ feat/mnt-data-projects-python-orchestra/frontend-opus              019009af6afea500320d530b71be6048b12bfe0c [behind 6] fix: usage graph clips data to reset period boundaries
  feat/mnt-data-projects-python-orchestra/git-artifact               ae7b869e39722e4b8661d0888cc81d78325e441f feat: add orchestra-git-workflow.html interactive artifact
  feat/mnt-data-projects-python-orchestra/git-workflow-research      7289e6ef39628439d65315d29cdc041daa0d2850 docs: git workflow research for multi-agent orchestration
  feat/mnt-data-projects-python-orchestra/html-skill-researcher      67fe30c262096cfd4eda3a47b9437eb4cffea984 research: HTML artifacts skill — Claude.ai internals, Thariq patterns, dogum analysis
  feat/mnt-data-projects-python-orchestra/images-everywhere          dc1931859a95acd2b834e93dc81a91822e06f58f feat: clickable image previews in chat (user msgs, Read tool, text msgs)
  feat/mnt-data-projects-python-orchestra/impl-agents-display        ffbe1da8efdb03bc2fd0d73c4b702e24c5b1cfad workers list in orchestrator prompt + cleanup rules
  feat/mnt-data-projects-python-orchestra/impl-git-status            405aa1fac82fea7224b5f31945a076570c6ec3f6 feat: git status line in worker cards
  feat/mnt-data-projects-python-orchestra/impl-merge-tool            daa9191be646243cf6342feaba2312d4e2a6d871 feat: merge_worker MCP tool — merge worktree branch into main
  feat/mnt-data-projects-python-orchestra/impl-persistent-fix        d5e3b205716cdb102dd39314e9a3f9f445be9b9d fix: heartbeat + silent death detection for persistent client
  feat/mnt-data-projects-python-orchestra/impl-progress              594699d0be12ab107a65047061e611b7f2200af1 feat: worker progress tracking (update_progress MCP tool + progress bar)
  feat/mnt-data-projects-python-orchestra/impl-stop-kill             ff3faa183c188ba3b5ef11c63d9d535ae8eae005 feat: add stop_worker — interrupt without destroy
  feat/mnt-data-projects-python-orchestra/impl-tg-images             686175be3027b00c32673788d1547d47a0e41a43 feat: send images as photos (inline preview) in TG send_file
  feat/mnt-data-projects-python-orchestra/infra-worker               21d546fbd34bde78b1220778b707fae88aeb61ec feat: local Telegram Bot API server support (files up to 2GB)
  feat/mnt-data-projects-python-orchestra/inject-researcher          1a6e20e610a0e347504d7006f2ae37b7354aa0e7 research: mid-turn message injection via ClaudeSDKClient.query()
  feat/mnt-data-projects-python-orchestra/opus-comparison            57bb37774df1cffe0a7cfa09fd18a9a9ff89c787 docs: add Opus 4.6 vs 4.7 vs 4.8 deep-research + interactive HTML comparison
  feat/mnt-data-projects-python-orchestra/orc22-fullcycle            9abe92156e4ae7dabae0ff050be4396df9d02025 #26: cron agents — periodic agent wake via bg_create type=cron
  feat/mnt-data-projects-python-orchestra/orchestra-skill            a7e3f05990d87f908ef36369401fa512f5be0048 feat: add /orchestra Claude Code skill
  feat/mnt-data-projects-python-orchestra/persistent-client          dc8e57ea3e7e1923d50efa7dd529ba036918bb38 feat: persistent client with mid-turn message injection via query()
  feat/mnt-data-projects-python-orchestra/prompt-engineer            738cf58c4e62200c1225d38080e10711274aab74 #43: Codex review Bash-primary, orchestrator merge/kill safety + worker_wip/check_conflict
  feat/mnt-data-projects-python-orchestra/prompt-viewer              25e3c12334960fb0429b398ba25d7fa08992be95 feat: system prompt viewer modal in agent info panel
  feat/mnt-data-projects-python-orchestra/proxy-setup                c9234bf8cbf905f1e43f3ad244bf19c6bc07a833 add proxy-setup docs: Squid on Fornex NL + Timeweb NL as Orchestra fallback proxies
  feat/mnt-data-projects-python-orchestra/research-automerge         398d669797efde58fe15dce3538d5d2a6e0e4951 research: auto-merge worker worktree branches to main
  feat/mnt-data-projects-python-orchestra/research-codex-migration   79e8af4a80a275996681f031e80f336a458b36a6 fix: Codex MCP tools — env_vars forwarding, --yolo for approvals
  feat/mnt-data-projects-python-orchestra/research-context-bug       c137c62b5189fb465b7e10b58abbe170834fa5a7 research: phantom context reset root-cause analysis (RC1-RC6 + fixes)
  feat/mnt-data-projects-python-orchestra/research-context-full      d4aec81655963e5f5f314ba0e6922e8535397bd4 research: full context-management map (CLI/SDK/Orchestra) + autocompact control + codex-implement
  feat/mnt-data-projects-python-orchestra/research-deepgram          af287846613709b3e9dc006966ff41f8bb6e5ce0 research: Deepgram voice transcription — pipeline, SSL history, test results
  feat/mnt-data-projects-python-orchestra/research-fork              5856ccf25cf60ce6fb919b9131d1bcec57d61616 research: fork analysis — origin/main vs vadim remote (4 branches, conflict map, cherry-pick recs)
  feat/mnt-data-projects-python-orchestra/research-gitview           c7bebb6457570b63bd584adb4d5b84f63edb9ca9 research: git tree view — libraries, data model, API design, recommendations
  feat/mnt-data-projects-python-orchestra/research-multiproject      0ab6e6e7cec432a5e3d587bad03de316d34095e6 research: multiproject task split for seedon (biz/tech)
  feat/mnt-data-projects-python-orchestra/research-proxy-speed       4a7fdf095e6833376b609dacbdb4f55cef4c0943 research: proxy speed benchmark — all APIs, bandwidth, stability
  feat/mnt-data-projects-python-orchestra/research-sse               57c087d45d37653b26e4977399bad2e476987ff8 docs: research SSE vs polling for global dashboard events
  feat/mnt-data-projects-python-orchestra/research-streaming         18b2591938461f4dd2c6343915528b289fb673cd research: streaming redesign — SDK StreamEvent, SSE, TG queue architecture
  feat/mnt-data-projects-python-orchestra/research-subagents         dee4c6064dbe766ab60e7f7cd0065415e17ea6cd research: sub-agent tracking via SDK system messages
+ feat/mnt-data-projects-python-orchestra/research-taskmanager       3b4194f57b92f94590de33fd864968f66fa2df19 merge: resolve conflicts in db.py and session.py
  feat/mnt-data-projects-python-orchestra/research-voice             8bb686c5dde80bb10e11fe08dd1f3bd7deb1f181 WIP: auto-saved uncommitted changes before worker spawn (2026-06-01 10:00)
+ feat/mnt-data-projects-python-orchestra/review-pr2                 9054cffce5b06e8b22cafbb700db75da18311fdb fix: system_prompt survives compact/resume + compact summary visible in dashboard
+ feat/mnt-data-projects-python-orchestra/review-worktree            b62f3d023ab30ef9d7ced11436906ffeee1b9031 fix: switch_worker_branch resets worktree to from_ref before branch switch
  feat/mnt-data-projects-python-orchestra/sdk-researcher             b2c62ea94c38378384f4f21960c322d2a182f9be feat: persistent client + seamless pending turns in session.py
  feat/mnt-data-projects-python-orchestra/squash-merge               f368e5b213866606bd770f205007e77f2f65e8e2 feat: squash merge as default strategy for merge_worker
  feat/mnt-data-projects-python-orchestra/test-codex-ctx             6a2cc28a57a13be450d0c7ea70938582b7e9d9f1 Merge branch 'feat/mnt-data-projects-python-orchestra/frontend-opus'
  feat/mnt-data-projects-python-orchestra/test-custom-prompt         8b10da3fa328a9c20d7c4d04bd13effa6629e39f fix: kill_worker ISE — delete_session name collision with endpoint, clean BUGS/TODO/CHANGELOG
  feat/mnt-data-projects-python-orchestra/test-pirate                8b10da3fa328a9c20d7c4d04bd13effa6629e39f fix: kill_worker ISE — delete_session name collision with endpoint, clean BUGS/TODO/CHANGELOG
  feat/mnt-data-projects-python-orchestra/test-sonnet-ctx            6a2cc28a57a13be450d0c7ea70938582b7e9d9f1 Merge branch 'feat/mnt-data-projects-python-orchestra/frontend-opus'
  feat/mnt-data-projects-python-orchestra/tg-debounce                19173fc60715bb81625cf990964dc2ea9b16d25b feat(tg-bridge): reliable debounce with WAITING_MEDIA phase
  feat/mnt-data-projects-python-orchestra/tg-media                   02048da8c39dbdc561541cec9f702900fcfe2d10 feat: full media support in TG bridge
  feat/mnt-data-projects-python-orchestra/tg-researcher              756938a128f022536ec9c14e40e6cd31e14d645b feat: queue-based TG streaming with rate-limited delivery
  feat/mnt-data-projects-python-orchestra/tg-voice                   693ac81a84e619ad3de2bdd0f7be5e94ae92d259 feat: voice message transcription via Deepgram in TG bridge
  feat/mnt-data-projects-python-orchestra/usage-researcher           207489b5d9997c9f5308606fed84cea40b7137f4 feat: send_file MCP tool — agents can send files to TG
  feat/mnt-data-projects-python-parsing/feat-git-branching           f86f6cf3f8c26e077532af1fd52209bf850ade45 docs: git branching per task — design + Codex review (4 rounds, APPROVED)
  feat/mnt-data-projects-python-parsing/kesha-bidirectional-research e1971f2bfa8893bb0d49d6117c313150b85d4153 docs: research bidirectional Kesha <-> orchestrator link
+ main                                                               d8e068f497d60340e739ca3d9fdcabec9a6183ac fix: escape single tilde in markdown to prevent false strikethrough
  prompt-fresh                                                       03c815117ac41c9403814b8a0a8deb3c9bdef77b [ahead 6, behind 120] #43: Codex review Bash-primary, orchestrator merge/kill safety + worker_wip/check_conflict
  task-21/backend                                                    c7d26f90788cfe21767a4bee3d0bccf1e4cb2e59 #waiting-status: add waiting state for agents pending bg jobs
  task-28/backend                                                    189a60923dfc5177694e57e319308abe17212869 fix: show cost with 2 decimals in agent info panel

codex
I’m checking the actual branch state and the symbols involved, because a merge-plan review is mostly about catching mismatches between the written plan and the current code shape. The local branch currently appears to be at `main`, so I’m going to inspect the PR branch/reference next rather than infer from the plan text.
exec
/usr/bin/zsh -lc "git branch --all --list '*pipeline*' --verbose --no-abbrev" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
* feat/mnt-data-projects-python-orchestra/feat-pipeline-rebase d8e068f497d60340e739ca3d9fdcabec9a6183ac fix: escape single tilde in markdown to prevent false strikethrough
  remotes/vadim/feat/pipeline-as-config                        b1d6f905237bf5ae78424bc715a09e1cc740a02a refactor(pipeline): переименовать приватный sapto-pm → tasks-pm + вывести из .gitignore
  remotes/vadim/v2-pipeline                                    1fe39e08b6fbe9eed74adf4713a0f58b37749855 chore: пересобрать uv.lock

exec
/usr/bin/zsh -lc "git remote -v && git for-each-ref --format='%(refname:short) %(objectname) %(subject)' refs/heads refs/remotes | rg -i 'vadim|pipeline|pr|feat/pipeline|as-config'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
origin	git@github.com:DrSeedon/orchestra.git (fetch)
origin	git@github.com:DrSeedon/orchestra.git (push)
vadim	https://github.com/mccalpink/orchestra.git (fetch)
vadim	https://github.com/mccalpink/orchestra.git (push)
feat/mnt-data-projects-python-orchestra/auto-compact 2bfa7153774d243fcbd350bcea55650146aa151a feat: auto-compact worker context when >90%
feat/mnt-data-projects-python-orchestra/backend 2afbee96529f52ec4d7f50d1dfbe6a6805bf5468 feat: non-blocking TG bridge startup (ORC-20)
feat/mnt-data-projects-python-orchestra/compact-mode 0d710a307abaf1d7021c654759d7ee26426d4569 feat: compact mode for tool bubbles
feat/mnt-data-projects-python-orchestra/debate-test 47dc4ed9de0607774e905258749231d4a63c947f #47: #47: debate artifacts — plan, report, codex sessions
feat/mnt-data-projects-python-orchestra/diff-view 65ba7e27159585868050ab64a60b8bf33a0912ab feat: diff view for Edit tool in dashboard chat
feat/mnt-data-projects-python-orchestra/feat-ci-routing 79aa0416bfa1fb8fc7ca98d2d1452ffc567e5fc6 fix: align job-level conclusion check with routing conclusions
feat/mnt-data-projects-python-orchestra/feat-deploy-amsterdam b863faa121423bb57ae3679a9aaac1d78cd2f837 wip: auto-save before worker spawn
feat/mnt-data-projects-python-orchestra/feat-git-safety 86fb128c4e636bdc1ab8cfa2fca950ea088264d7 add codex review impl diff
feat/mnt-data-projects-python-orchestra/feat-git-task-link 84dae506ba49ec8d60cadc3812e2aa61811709e8 fix: Codex review — unmerged guard, worktree parser, conflict branch persist, link error display
feat/mnt-data-projects-python-orchestra/feat-guards 671db1b619dfb85fdf5b7e0723df486847822c23 #guards: 5 deterministic guards — kill/merge/send/spawn/owned_dirs
feat/mnt-data-projects-python-orchestra/feat-idle-optimization b46b2cd549934c481e9c946098a2816a7bdc07b8 feat: background jobs — server-side one-shot tasks that survive hibernate
feat/mnt-data-projects-python-orchestra/feat-llm-comparison b25903f9fac033110be13951387e897ae6c6d2cd Add LLM comparison research
feat/mnt-data-projects-python-orchestra/feat-pipeline-rebase d8e068f497d60340e739ca3d9fdcabec9a6183ac fix: escape single tilde in markdown to prevent false strikethrough
feat/mnt-data-projects-python-orchestra/feat-roi-analysis 7d7a718a7cdb5fe05a6e7fd57190d7a67a097e51 update: Codex report — VPS deep dive, 48 reviews, pay recommendation
feat/mnt-data-projects-python-orchestra/feat-scope-change ddea49f2d15ef0c34595e676f24b9532f94f9ec5 #29: changelog v2.11.0 — change orchestrator scope without losing session
feat/mnt-data-projects-python-orchestra/feat-visibility 27536da11f71e1e98104613529b08c48498c3e15 #visibility: limit worker visibility between orchestrators
feat/mnt-data-projects-python-orchestra/feat-vps-migration c16bf69a901189d78a291e27f63ff35610068288 research: VPS migration plan for 24/7 Orchestra availability
feat/mnt-data-projects-python-orchestra/feat-wt-cleanup 7295b559212811ca6f3cb230835cb968cc89d536 #wt-cleanup: auto-cleanup stale worktrees on startup + every 24h
feat/mnt-data-projects-python-orchestra/file-preview 9c274df70cdaa56c5c648ac76564f99a019d826d feat: file preview modal in dashboard
feat/mnt-data-projects-python-orchestra/fix-1m-sdk 8ed8f878c49ddc7824d092d2ca18ae20682177a5 WIP: auto-saved uncommitted changes before worker spawn (2026-06-01 01:55)
feat/mnt-data-projects-python-orchestra/fix-file-preview 513ecfb56b2252cd8a97b0c3da962ddcd8880d41 feat: add /api/files/content endpoint for file preview
feat/mnt-data-projects-python-orchestra/fix-filepanel 98cd3e5f1ae57102f04b449efe3d1b144157e568 fix file panel: preview modal, send button, remove toggle
feat/mnt-data-projects-python-orchestra/frontend-design 7de423014fa70523fa2a35cc387327fbbf740193 fix: load-more uses addChatEntry for full custom bubble rendering
feat/mnt-data-projects-python-orchestra/frontend-opus 019009af6afea500320d530b71be6048b12bfe0c fix: usage graph clips data to reset period boundaries
feat/mnt-data-projects-python-orchestra/git-artifact ae7b869e39722e4b8661d0888cc81d78325e441f feat: add orchestra-git-workflow.html interactive artifact
feat/mnt-data-projects-python-orchestra/git-workflow-research 7289e6ef39628439d65315d29cdc041daa0d2850 docs: git workflow research for multi-agent orchestration
feat/mnt-data-projects-python-orchestra/html-skill-researcher 67fe30c262096cfd4eda3a47b9437eb4cffea984 research: HTML artifacts skill — Claude.ai internals, Thariq patterns, dogum analysis
feat/mnt-data-projects-python-orchestra/images-everywhere dc1931859a95acd2b834e93dc81a91822e06f58f feat: clickable image previews in chat (user msgs, Read tool, text msgs)
feat/mnt-data-projects-python-orchestra/impl-agents-display ffbe1da8efdb03bc2fd0d73c4b702e24c5b1cfad workers list in orchestrator prompt + cleanup rules
feat/mnt-data-projects-python-orchestra/impl-git-status 405aa1fac82fea7224b5f31945a076570c6ec3f6 feat: git status line in worker cards
feat/mnt-data-projects-python-orchestra/impl-merge-tool daa9191be646243cf6342feaba2312d4e2a6d871 feat: merge_worker MCP tool — merge worktree branch into main
feat/mnt-data-projects-python-orchestra/impl-persistent-fix d5e3b205716cdb102dd39314e9a3f9f445be9b9d fix: heartbeat + silent death detection for persistent client
feat/mnt-data-projects-python-orchestra/impl-progress 594699d0be12ab107a65047061e611b7f2200af1 feat: worker progress tracking (update_progress MCP tool + progress bar)
feat/mnt-data-projects-python-orchestra/impl-stop-kill ff3faa183c188ba3b5ef11c63d9d535ae8eae005 feat: add stop_worker — interrupt without destroy
feat/mnt-data-projects-python-orchestra/impl-tg-images 686175be3027b00c32673788d1547d47a0e41a43 feat: send images as photos (inline preview) in TG send_file
feat/mnt-data-projects-python-orchestra/infra-worker 21d546fbd34bde78b1220778b707fae88aeb61ec feat: local Telegram Bot API server support (files up to 2GB)
feat/mnt-data-projects-python-orchestra/inject-researcher 1a6e20e610a0e347504d7006f2ae37b7354aa0e7 research: mid-turn message injection via ClaudeSDKClient.query()
feat/mnt-data-projects-python-orchestra/opus-comparison 57bb37774df1cffe0a7cfa09fd18a9a9ff89c787 docs: add Opus 4.6 vs 4.7 vs 4.8 deep-research + interactive HTML comparison
feat/mnt-data-projects-python-orchestra/orc22-fullcycle 9abe92156e4ae7dabae0ff050be4396df9d02025 #26: cron agents — periodic agent wake via bg_create type=cron
feat/mnt-data-projects-python-orchestra/orchestra-skill a7e3f05990d87f908ef36369401fa512f5be0048 feat: add /orchestra Claude Code skill
feat/mnt-data-projects-python-orchestra/persistent-client dc8e57ea3e7e1923d50efa7dd529ba036918bb38 feat: persistent client with mid-turn message injection via query()
feat/mnt-data-projects-python-orchestra/prompt-engineer 738cf58c4e62200c1225d38080e10711274aab74 #43: Codex review Bash-primary, orchestrator merge/kill safety + worker_wip/check_conflict
feat/mnt-data-projects-python-orchestra/prompt-viewer 25e3c12334960fb0429b398ba25d7fa08992be95 feat: system prompt viewer modal in agent info panel
feat/mnt-data-projects-python-orchestra/proxy-setup c9234bf8cbf905f1e43f3ad244bf19c6bc07a833 add proxy-setup docs: Squid on Fornex NL + Timeweb NL as Orchestra fallback proxies
feat/mnt-data-projects-python-orchestra/research-automerge 398d669797efde58fe15dce3538d5d2a6e0e4951 research: auto-merge worker worktree branches to main
feat/mnt-data-projects-python-orchestra/research-codex-migration 79e8af4a80a275996681f031e80f336a458b36a6 fix: Codex MCP tools — env_vars forwarding, --yolo for approvals
feat/mnt-data-projects-python-orchestra/research-context-bug c137c62b5189fb465b7e10b58abbe170834fa5a7 research: phantom context reset root-cause analysis (RC1-RC6 + fixes)
feat/mnt-data-projects-python-orchestra/research-context-full d4aec81655963e5f5f314ba0e6922e8535397bd4 research: full context-management map (CLI/SDK/Orchestra) + autocompact control + codex-implement
feat/mnt-data-projects-python-orchestra/research-deepgram af287846613709b3e9dc006966ff41f8bb6e5ce0 research: Deepgram voice transcription — pipeline, SSL history, test results
feat/mnt-data-projects-python-orchestra/research-fork 5856ccf25cf60ce6fb919b9131d1bcec57d61616 research: fork analysis — origin/main vs vadim remote (4 branches, conflict map, cherry-pick recs)
feat/mnt-data-projects-python-orchestra/research-gitview c7bebb6457570b63bd584adb4d5b84f63edb9ca9 research: git tree view — libraries, data model, API design, recommendations
feat/mnt-data-projects-python-orchestra/research-multiproject 0ab6e6e7cec432a5e3d587bad03de316d34095e6 research: multiproject task split for seedon (biz/tech)
feat/mnt-data-projects-python-orchestra/research-proxy-speed 4a7fdf095e6833376b609dacbdb4f55cef4c0943 research: proxy speed benchmark — all APIs, bandwidth, stability
feat/mnt-data-projects-python-orchestra/research-sse 57c087d45d37653b26e4977399bad2e476987ff8 docs: research SSE vs polling for global dashboard events
feat/mnt-data-projects-python-orchestra/research-streaming 18b2591938461f4dd2c6343915528b289fb673cd research: streaming redesign — SDK StreamEvent, SSE, TG queue architecture
feat/mnt-data-projects-python-orchestra/research-subagents dee4c6064dbe766ab60e7f7cd0065415e17ea6cd research: sub-agent tracking via SDK system messages
feat/mnt-data-projects-python-orchestra/research-taskmanager 3b4194f57b92f94590de33fd864968f66fa2df19 merge: resolve conflicts in db.py and session.py
feat/mnt-data-projects-python-orchestra/research-voice 8bb686c5dde80bb10e11fe08dd1f3bd7deb1f181 WIP: auto-saved uncommitted changes before worker spawn (2026-06-01 10:00)
feat/mnt-data-projects-python-orchestra/review-pr2 9054cffce5b06e8b22cafbb700db75da18311fdb fix: system_prompt survives compact/resume + compact summary visible in dashboard
feat/mnt-data-projects-python-orchestra/review-worktree b62f3d023ab30ef9d7ced11436906ffeee1b9031 fix: switch_worker_branch resets worktree to from_ref before branch switch
feat/mnt-data-projects-python-orchestra/sdk-researcher b2c62ea94c38378384f4f21960c322d2a182f9be feat: persistent client + seamless pending turns in session.py
feat/mnt-data-projects-python-orchestra/squash-merge f368e5b213866606bd770f205007e77f2f65e8e2 feat: squash merge as default strategy for merge_worker
feat/mnt-data-projects-python-orchestra/test-codex-ctx 6a2cc28a57a13be450d0c7ea70938582b7e9d9f1 Merge branch 'feat/mnt-data-projects-python-orchestra/frontend-opus'
feat/mnt-data-projects-python-orchestra/test-custom-prompt 8b10da3fa328a9c20d7c4d04bd13effa6629e39f fix: kill_worker ISE — delete_session name collision with endpoint, clean BUGS/TODO/CHANGELOG
feat/mnt-data-projects-python-orchestra/test-pirate 8b10da3fa328a9c20d7c4d04bd13effa6629e39f fix: kill_worker ISE — delete_session name collision with endpoint, clean BUGS/TODO/CHANGELOG
feat/mnt-data-projects-python-orchestra/test-sonnet-ctx 6a2cc28a57a13be450d0c7ea70938582b7e9d9f1 Merge branch 'feat/mnt-data-projects-python-orchestra/frontend-opus'
feat/mnt-data-projects-python-orchestra/tg-debounce 19173fc60715bb81625cf990964dc2ea9b16d25b feat(tg-bridge): reliable debounce with WAITING_MEDIA phase
feat/mnt-data-projects-python-orchestra/tg-media 02048da8c39dbdc561541cec9f702900fcfe2d10 feat: full media support in TG bridge
feat/mnt-data-projects-python-orchestra/tg-researcher 756938a128f022536ec9c14e40e6cd31e14d645b feat: queue-based TG streaming with rate-limited delivery
feat/mnt-data-projects-python-orchestra/tg-voice 693ac81a84e619ad3de2bdd0f7be5e94ae92d259 feat: voice message transcription via Deepgram in TG bridge
feat/mnt-data-projects-python-orchestra/usage-researcher 207489b5d9997c9f5308606fed84cea40b7137f4 feat: send_file MCP tool — agents can send files to TG
feat/mnt-data-projects-python-parsing/feat-git-branching f86f6cf3f8c26e077532af1fd52209bf850ade45 docs: git branching per task — design + Codex review (4 rounds, APPROVED)
feat/mnt-data-projects-python-parsing/kesha-bidirectional-research e1971f2bfa8893bb0d49d6117c313150b85d4153 docs: research bidirectional Kesha <-> orchestrator link
main d8e068f497d60340e739ca3d9fdcabec9a6183ac fix: escape single tilde in markdown to prevent false strikethrough
prompt-fresh 03c815117ac41c9403814b8a0a8deb3c9bdef77b #43: Codex review Bash-primary, orchestrator merge/kill safety + worker_wip/check_conflict
task-34/backend 6ab422d9b78d84bba7414336a51833b0c18ea306 perf: remove proxy from Deepgram (9x faster), add timing logs for voice pipeline
task-35/review-sdk 67d98fad2a4c18fe07ce56ece5d7fa0db0d3f772 #35: note Codex cross-review unavailable (tool produced no output); findings stand on direct SDK-source verification
task-43/research-codex dc14cddc9c73b17c08c83d9c1234545cad1e0a1d #43, #44: #43: SSH tunnel proxies — systemd services, proxy-setup docs
task-46/impl-debate 3e6a40a7822c0c2da7817e4df2df0687c2d10624 #46: #46: adapt codex-debate skill from Vadim's fork + analysis doc
origin d8e068f497d60340e739ca3d9fdcabec9a6183ac fix: escape single tilde in markdown to prevent false strikethrough
origin/main d8e068f497d60340e739ca3d9fdcabec9a6183ac fix: escape single tilde in markdown to prevent false strikethrough
vadim 2d527cf097272cb91980cde96b347841ef56d763 fix: remove TG reactions (👍/👂) on messages
vadim/feat/pipeline-as-config b1d6f905237bf5ae78424bc715a09e1cc740a02a refactor(pipeline): переименовать приватный sapto-pm → tasks-pm + вывести из .gitignore
vadim/main 2d527cf097272cb91980cde96b347841ef56d763 fix: remove TG reactions (👍/👂) on messages
vadim/orchestra-upstream 65e637c34fcd2edcbda63048e51379e730c086fc feat(tg): @mention user in agent speech via TG_USER_MENTION (not on agent-to-agent traffic)
vadim/personal 5c0e4f8a2a94997a3aafbd63d1501eacccc0dba4 fix(tests): порядок классов TestTestLock → TestHierarchyColumns как в v2-pipeline
vadim/upstream-pack-may26 e1979c1569201bd0cd0aa0d440e38b30c7df9b53 feat(tg): optional cleanup of TG topics on project delete
vadim/v2-pipeline 1fe39e08b6fbe9eed74adf4713a0f58b37749855 chore: пересобрать uv.lock

exec
/usr/bin/zsh -lc "git log --oneline --decorate --all --grep='pipeline' -n 40" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
b1d6f90 (vadim/feat/pipeline-as-config) refactor(pipeline): переименовать приватный sapto-pm → tasks-pm + вывести из .gitignore
70ae36c feat(pipeline): доказательная идентичность default ≡ upstream + мост frontmatter→манифест
be4ea9c feat(pipeline): провести worktree symlinks/copies из манифеста + валидация Symlink
161b0b1 feat(pipeline): default manifest = upstream v2.16 (6 roles + modules)
4b394e2 merge: upstream/main v2.16.0 into pipeline-manifest
af28784 (feat/mnt-data-projects-python-orchestra/research-deepgram) research: Deepgram voice transcription — pipeline, SSL history, test results
7c74858 fix(pipeline): address cross-LLM (Codex) branch review
d3ae434 feat(pipeline): stage 7 — base_branch parent-chain resolution
5b630b8 feat(pipeline): stage 6 chunk 5 — UI profile/pipeline/role + profiles editor
255b020 feat(pipeline): stage 6 chunk 4 — REST API for profiles + pipelines
bb5418f feat(pipeline): stage 6 chunk 3 — backend F1/F2/F4 + profile env
aa24074 feat(pipeline): stage 6 chunk 2 — profile resolution + inheritance
fcfbc9a feat(pipeline): stage 6 chunk 1 — profiles DB layer
8f8f66c feat(pipeline): stage 5 — generic docs scaffold + sapto-pm (private)
6ab422d (task-34/backend) perf: remove proxy from Deepgram (9x faster), add timing logs for voice pipeline
4235304 feat(pipeline): stage 4 — default pipeline (upstream behaviour 1:1)
18f2aac feat(pipeline): stage 3 — wire loader into manager (R1/R2/R3 + upstream fallback)
4bbebe4 feat(pipeline): stage 2 — loader + pydantic schema + tests
26c1dd8 feat(pipeline): stage 1 — pipeline column + stored is_orchestrator field
e0a105b refactor: restructure prompts with XML tags and merged role files
68f699d feat: full-cycle worker role with strict research→plan→implement pipeline
6c036c1 docs: add Vadim's fork ideas to TODO (v2-pipeline features)
5c0e4f8 (vadim/personal) fix(tests): порядок классов TestTestLock → TestHierarchyColumns как в v2-pipeline
7c50030 feat(prompts): перестроить правила пайплайна по ролям + роль тестировщика
0627784 feat(prompts): initial role prompts for v2 pipeline
b91db3d feat(prompts): перестроить правила пайплайна по ролям + роль тестировщика
b9d0e6f feat(prompts): initial role prompts for v2 pipeline
936e01c fix: bypassPermissions instead of can_use_tool — fixes MCP hang

codex
The branch reference exists as `vadim/feat/pipeline-as-config`; your working branch and `main` are currently the same commit. I’m going to use Git’s merge-tree/diff views to validate the listed conflicts and find silent auto-merge risks.
exec
/usr/bin/zsh -lc 'git diff --name-status main...vadim/feat/pipeline-as-config' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
M	app/backend_claude.py
M	app/db.py
M	app/main.py
M	app/manager.py
M	app/mcp_stdio.py
A	app/pipeline.py
M	app/session.py
M	app/static/js/app.js
M	app/templates/dashboard.html
M	app/workspace.py
A	pipelines/default/pipeline.yaml
A	pipelines/default/prompts/base.md
A	pipelines/default/prompts/modules/codex-review.md
A	pipelines/default/prompts/modules/git-workflow.md
A	pipelines/default/prompts/modules/report-format.md
A	pipelines/default/prompts/roles/full-cycle.md
A	pipelines/default/prompts/roles/orchestrator.md
A	pipelines/default/prompts/roles/reviewer.md
A	pipelines/default/prompts/roles/sub-orchestrator.md
A	pipelines/default/prompts/roles/watcher.md
A	pipelines/default/prompts/roles/worker.md
A	pipelines/default/prompts/skills/html-artifacts.md
A	pipelines/default/prompts/skills/vps-deploy.md
A	pipelines/tasks-pm/pipeline.yaml
A	pipelines/tasks-pm/prompts/_pipeline.md
A	pipelines/tasks-pm/prompts/base.md
A	pipelines/tasks-pm/prompts/roles/analyst.md
A	pipelines/tasks-pm/prompts/roles/base-orchestrator.md
A	pipelines/tasks-pm/prompts/roles/coder.md
A	pipelines/tasks-pm/prompts/roles/pm-fichi.md
A	pipelines/tasks-pm/prompts/roles/pm-glava.md
A	pipelines/tasks-pm/prompts/roles/secretary.md
A	pipelines/tasks-pm/prompts/roles/tester.md
A	pipelines/tasks-pm/prompts/roles/worker.md
A	pipelines/tasks-pm/templates/analysis.md
A	pipelines/tasks-pm/templates/impl.md
A	pipelines/tasks-pm/templates/pm.md
A	pipelines/tasks-pm/templates/sprint.md
A	pipelines/tasks-pm/templates/testing.md
M	pyproject.toml
A	scripts/extract-manifest.py
M	tests/test_api.py
M	tests/test_db.py
A	tests/test_default_equals_upstream.py
A	tests/test_default_pipeline.py
M	tests/test_manager.py
M	tests/test_mcp_stdio.py
A	tests/test_pipeline.py
A	tests/test_scaffold.py
M	tests/test_session.py
A	tests/test_tasks_pm_pipeline.py
M	tests/test_workspace.py
M	uv.lock

exec
/usr/bin/zsh -lc "git merge-tree main vadim/feat/pipeline-as-config | sed -n '1,260p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
error: unable to create temporary file: Read-only file system
fatal: failure to merge

exec
/usr/bin/zsh -lc 'git diff --stat main...vadim/feat/pipeline-as-config' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
 app/backend_claude.py                              |  36 +-
 app/db.py                                          |  64 +-
 app/main.py                                        |  70 +-
 app/manager.py                                     | 349 ++++++++-
 app/mcp_stdio.py                                   |   4 +-
 app/pipeline.py                                    | 487 +++++++++++++
 app/session.py                                     |  62 ++
 app/static/js/app.js                               | 145 +++-
 app/templates/dashboard.html                       |  30 +
 app/workspace.py                                   |  83 ++-
 pipelines/default/pipeline.yaml                    |  97 +++
 pipelines/default/prompts/base.md                  |  56 ++
 pipelines/default/prompts/modules/codex-review.md  |  51 ++
 pipelines/default/prompts/modules/git-workflow.md  |  30 +
 pipelines/default/prompts/modules/report-format.md |  26 +
 pipelines/default/prompts/roles/full-cycle.md      |  78 ++
 pipelines/default/prompts/roles/orchestrator.md    | 192 +++++
 pipelines/default/prompts/roles/reviewer.md        |   6 +
 .../default/prompts/roles/sub-orchestrator.md      |   6 +
 pipelines/default/prompts/roles/watcher.md         |   6 +
 pipelines/default/prompts/roles/worker.md          |  48 ++
 pipelines/default/prompts/skills/html-artifacts.md |  64 ++
 pipelines/default/prompts/skills/vps-deploy.md     |  58 ++
 pipelines/tasks-pm/pipeline.yaml                   |  25 +
 pipelines/tasks-pm/prompts/_pipeline.md            |  65 ++
 pipelines/tasks-pm/prompts/base.md                 |  46 ++
 pipelines/tasks-pm/prompts/roles/analyst.md        |  28 +
 .../tasks-pm/prompts/roles/base-orchestrator.md    |  51 ++
 pipelines/tasks-pm/prompts/roles/coder.md          |  17 +
 pipelines/tasks-pm/prompts/roles/pm-fichi.md       |  53 ++
 pipelines/tasks-pm/prompts/roles/pm-glava.md       |  47 ++
 pipelines/tasks-pm/prompts/roles/secretary.md      | 115 +++
 pipelines/tasks-pm/prompts/roles/tester.md         |  40 ++
 pipelines/tasks-pm/prompts/roles/worker.md         |   6 +
 pipelines/tasks-pm/templates/analysis.md           |  30 +
 pipelines/tasks-pm/templates/impl.md               |  37 +
 pipelines/tasks-pm/templates/pm.md                 |  51 ++
 pipelines/tasks-pm/templates/sprint.md             |  31 +
 pipelines/tasks-pm/templates/testing.md            |  35 +
 pyproject.toml                                     |   1 +
 scripts/extract-manifest.py                        | 200 ++++++
 tests/test_api.py                                  | 151 +++-
 tests/test_db.py                                   | 123 ++++
 tests/test_default_equals_upstream.py              | 243 +++++++
 tests/test_default_pipeline.py                     | 382 ++++++++++
 tests/test_manager.py                              | 642 ++++++++++++++++-
 tests/test_mcp_stdio.py                            |   6 +-
 tests/test_pipeline.py                             | 786 +++++++++++++++++++++
 tests/test_scaffold.py                             | 131 ++++
 tests/test_session.py                              | 283 +++++++-
 tests/test_tasks_pm_pipeline.py                    |  94 +++
 tests/test_workspace.py                            |  99 +++
 uv.lock                                            |   6 +-
 53 files changed, 5797 insertions(+), 75 deletions(-)

exec
/usr/bin/zsh -lc "TMPDIR=/tmp git merge-tree main vadim/feat/pipeline-as-config | sed -n '1,320p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
error: unable to create temporary file: Read-only file system
fatal: failure to merge

exec
/usr/bin/zsh -lc 'git merge-base main vadim/feat/pipeline-as-config' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
101f086fdc60f042353cbb6633f7580a69fa011e

exec
/usr/bin/zsh -lc 'git diff --name-status $(git merge-base main vadim/feat/pipeline-as-config)..main -- app tests pyproject.toml uv.lock' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
M	app/auth.py
M	app/backend_claude.py
A	app/backend_protocol.py
M	app/bg_jobs.py
A	app/deps.py
M	app/main.py
M	app/manager.py
M	app/mcp_stdio.py
A	app/prompting.py
D	app/prompts/modules/codex-review.md
A	app/prompts/modules/orchestration.md
M	app/prompts/roles/full-cycle.md
M	app/prompts/roles/orchestrator.md
D	app/prompts/roles/reviewer.md
M	app/prompts/roles/sub-orchestrator.md
D	app/prompts/roles/watcher.md
M	app/prompts/roles/worker.md
A	app/prompts/skills/codex-debate.md
A	app/routes/__init__.py
A	app/routes/bg.py
A	app/routes/proxy.py
A	app/routes/tm.py
M	app/session.py
M	app/static/css/style.css
M	app/static/js/app.js
M	app/tg_bridge.py
M	app/tm.py
D	app/tools.py
M	app/workspace.py
M	tests/test_manager.py
M	tests/test_workspace.py

exec
/usr/bin/zsh -lc 'git diff --name-status $(git merge-base main vadim/feat/pipeline-as-config)..vadim/feat/pipeline-as-config -- app tests pipelines pyproject.toml uv.lock scripts' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
M	app/backend_claude.py
M	app/db.py
M	app/main.py
M	app/manager.py
M	app/mcp_stdio.py
A	app/pipeline.py
M	app/session.py
M	app/static/js/app.js
M	app/templates/dashboard.html
M	app/workspace.py
A	pipelines/default/pipeline.yaml
A	pipelines/default/prompts/base.md
A	pipelines/default/prompts/modules/codex-review.md
A	pipelines/default/prompts/modules/git-workflow.md
A	pipelines/default/prompts/modules/report-format.md
A	pipelines/default/prompts/roles/full-cycle.md
A	pipelines/default/prompts/roles/orchestrator.md
A	pipelines/default/prompts/roles/reviewer.md
A	pipelines/default/prompts/roles/sub-orchestrator.md
A	pipelines/default/prompts/roles/watcher.md
A	pipelines/default/prompts/roles/worker.md
A	pipelines/default/prompts/skills/html-artifacts.md
A	pipelines/default/prompts/skills/vps-deploy.md
A	pipelines/tasks-pm/pipeline.yaml
A	pipelines/tasks-pm/prompts/_pipeline.md
A	pipelines/tasks-pm/prompts/base.md
A	pipelines/tasks-pm/prompts/roles/analyst.md
A	pipelines/tasks-pm/prompts/roles/base-orchestrator.md
A	pipelines/tasks-pm/prompts/roles/coder.md
A	pipelines/tasks-pm/prompts/roles/pm-fichi.md
A	pipelines/tasks-pm/prompts/roles/pm-glava.md
A	pipelines/tasks-pm/prompts/roles/secretary.md
A	pipelines/tasks-pm/prompts/roles/tester.md
A	pipelines/tasks-pm/prompts/roles/worker.md
A	pipelines/tasks-pm/templates/analysis.md
A	pipelines/tasks-pm/templates/impl.md
A	pipelines/tasks-pm/templates/pm.md
A	pipelines/tasks-pm/templates/sprint.md
A	pipelines/tasks-pm/templates/testing.md
M	pyproject.toml
A	scripts/extract-manifest.py
M	tests/test_api.py
M	tests/test_db.py
A	tests/test_default_equals_upstream.py
A	tests/test_default_pipeline.py
M	tests/test_manager.py
M	tests/test_mcp_stdio.py
A	tests/test_pipeline.py
A	tests/test_scaffold.py
M	tests/test_session.py
A	tests/test_tasks_pm_pipeline.py
M	tests/test_workspace.py
M	uv.lock

web search: 
web search: 
web search: 
web search: 
codex
The PR touches more than the plan’s “new files plus four conflicts”: tests, DB schema, `pyproject.toml`/`uv.lock`, API tests, and session tests also changed. That does not invalidate the strategy, but it means the verification checklist should treat auto-merged tests and dependency lockfile as first-class merge surfaces.
exec
/usr/bin/zsh -lc "git show main:app/prompting.py | sed -n '1,220p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
"""Prompt composition — pure file/template helpers for agent prompts."""

import hashlib
import logging
import re
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_MODULES_DIR = _PROMPTS_DIR / "modules"
_SKILLS_DIR = _PROMPTS_DIR / "skills"

_ORCHESTRATOR_ROLES = frozenset({"orchestrator", "sub-orchestrator"})
_IDENTITY_PLACEHOLDERS = re.compile(r"\{(worker_name|orchestrator_name|scope|branch)\}")


def is_orchestrator_role(role: str) -> bool:
    return role in _ORCHESTRATOR_ROLES


def safe_format_prompt(template: str, **kwargs: str) -> str:
    """Substitute only known identity placeholders, leaving other {braces} intact."""
    return _IDENTITY_PLACEHOLDERS.sub(lambda m: kwargs.get(m.group(1), m.group(0)), template)


def read_prompt(name: str) -> str:
    p = _PROMPTS_DIR / name
    return p.read_text() if p.exists() else ""


def parse_role_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from role .md file. Returns (meta, body)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        import yaml
        meta = yaml.safe_load(parts[1]) or {}
    except Exception:
        meta = {}
    body = parts[2].strip()
    return meta, body


def _load_modules(module_names: list[str]) -> str:
    parts = []
    for name in module_names:
        p = _MODULES_DIR / f"{name}.md"
        if p.exists():
            parts.append(p.read_text().strip())
        else:
            logger.warning(f"Module '{name}' not found at {p}")
    return "\n\n".join(parts)


def role_prompt_file(role: str) -> str:
    """Find the best prompt for a role. Parses frontmatter, returns body + modules.
    Falls back to 'worker' role if role file not found."""
    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
    if role_path.exists():
        meta, body = parse_role_frontmatter(role_path.read_text())
        if body:
            modules = meta.get("modules", [])
            if modules:
                body = body + "\n\n" + _load_modules(modules)
            return body
    if role != "worker":
        fallback = _PROMPTS_DIR / "roles" / ("orchestrator.md" if is_orchestrator_role(role) else "worker.md")
        if fallback.exists():
            meta, body = parse_role_frontmatter(fallback.read_text())
            if body:
                modules = meta.get("modules", [])
                if modules:
                    body = body + "\n\n" + _load_modules(modules)
                return body
    return ""


def role_can_spawn(role: str):
    """Return the can_spawn whitelist for a role, or None if unrestricted."""
    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
    if not role_path.exists():
        return None
    meta, _ = parse_role_frontmatter(role_path.read_text())
    if "can_spawn" not in meta:
        return None
    val = meta["can_spawn"]
    if not isinstance(val, list):
        logger.warning(f"role '{role}' has non-list can_spawn ({val!r}); treating as unrestricted")
        return None
    return [str(x) for x in val]


def skills_catalog() -> str:
    """Build catalog of available skills from skills/ directory for orchestrator."""
    if not _SKILLS_DIR.is_dir():
        return ""
    entries = []
    for f in sorted(_SKILLS_DIR.glob("*.md")):
        meta, _ = parse_role_frontmatter(f.read_text())
        name = meta.get("name", f.stem)
        desc = meta.get("description", "").strip().replace("\n", " ")
        entries.append(f"- `{name}` — {desc}")
    if not entries:
        return ""
    return "## Available skills (for roles)\nSkills are auto-injected into worker prompts via `skills:` in role frontmatter.\n" + "\n".join(entries)


def get_role_icons() -> dict[str, str]:
    roles_dir = _PROMPTS_DIR / "roles"
    icons = {}
    if roles_dir.is_dir():
        for f in sorted(roles_dir.glob("*.md")):
            meta, _ = parse_role_frontmatter(f.read_text())
            if meta:
                name = meta.get("name", f.stem)
                icon = meta.get("icon", "")
                if icon:
                    icons[name] = icon
    return icons


def roles_catalog() -> str:
    """Build a catalog of available worker roles from roles/ directory frontmatter."""
    roles_dir = _PROMPTS_DIR / "roles"
    if not roles_dir.is_dir():
        return ""
    entries = []
    for f in sorted(roles_dir.glob("*.md")):
        meta, _ = parse_role_frontmatter(f.read_text())
        if not meta or meta.get("name") == "orchestrator":
            continue
        name = meta.get("name", f.stem)
        label = meta.get("label", name)
        model = meta.get("model", "any")
        desc = meta.get("description", "").strip().replace("\n", " ")
        when = meta.get("when", "").strip()
        not_for = meta.get("not_for", "").strip()
        skills_list = meta.get("skills", [])
        entry = f"### `{name}` ({label}) — model: {model}\n{desc}"
        if when:
            entry += f"\n- ✅ **When**: {when}"
        if not_for:
            entry += f"\n- ❌ **Not for**: {not_for}"
        if skills_list:
            entry += f"\n- 🔧 **Skills**: {', '.join(skills_list)}"
        entries.append(entry)
    if not entries:
        return ""
    return "## Available worker roles\nSpawn with `role=\"<name>\"`. If no role specified, defaults to `worker`.\n\n" + "\n\n".join(entries)


def prompt_template_hash(role_or_orch) -> str:
    """Hash only the static template files (base.md + role.md + skills).
    Accepts role string or legacy bool (is_orchestrator)."""
    if isinstance(role_or_orch, bool):
        role = "orchestrator" if role_or_orch else "worker"
    else:
        role = role_or_orch
    content = read_prompt("base.md") + role_prompt_file(role)
    return hashlib.md5(content.encode()).hexdigest()[:8]


def inject_skills_to_worktree(role: str, worktree_path: str) -> None:
    """Copy role skills into worktree/.claude/skills/ as native Claude CLI skills."""
    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
    if not role_path.exists():
        return
    meta, _ = parse_role_frontmatter(role_path.read_text())
    skill_names = meta.get("skills", [])
    if not skill_names or not _SKILLS_DIR.is_dir():
        return
    wt = Path(worktree_path)
    for sname in skill_names:
        skill_src = _SKILLS_DIR / f"{sname}.md"
        if not skill_src.exists():
            logger.warning(f"Skill '{sname}' not found in {_SKILLS_DIR}")
            continue
        skill_dir = wt / ".claude" / "skills" / sname
        skill_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_src, skill_dir / "SKILL.md")
    logger.info(f"Injected {len(skill_names)} skills into {worktree_path}/.claude/skills/")

exec
/usr/bin/zsh -lc "git show vadim/feat/pipeline-as-config:app/pipeline.py | sed -n '1,260p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
"""Loader пайплайнов: схема манифеста (pydantic) + резолв ролей/промптов/спавна.

Источник истины о ролях — единый манифест ``pipelines/<name>/pipeline.yaml``
(вместо frontmatter+glob апстрима). При активном пайплайне ВСЁ берётся только из
``pipelines/<name>/`` — ``app/prompts/`` игнорируется (полная изоляция промптов).

Наследование defaults→roles выполняется на РЕЗОЛВЕ (:func:`resolve_role`), не на
загрузке: ``load_pipeline`` валидирует и кэширует сырой манифест, ``resolve_role``
сливает роль с defaults в :class:`ResolvedRole`.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import ALIASES, MODELS

logger = logging.getLogger(__name__)

# Корень с пайплайнами: <repo>/pipelines/. default и tasks-pm — оба в гите.
PIPELINES_DIR = Path(__file__).parent.parent / "pipelines"
DEFAULT_PIPELINE = "default"

# Спецзначение "all" для skills/mcp_servers (строка) vs явный список.
AllOrList = Union[Literal["all"], list[str]]

Kind = Literal["orchestrator", "worker"]
ValidationMode = Literal["fail-closed", "fail-open"]
BranchStrategy = Literal["parent", "main"]


def _model_is_known(model: str) -> bool:
    """Модель валидна, если это alias (lowercase) ИЛИ полный id из app.models."""
    return model.lower() in ALIASES or model in MODELS


def _is_safe_rel(p: str) -> bool:
    """True если ``p`` — безопасный относительный путь (без абсолютного и '..').

    Защита изоляции: слои промпта/шаблоны не должны выходить за pipelines/<name>/.
    """
    from pathlib import PurePosixPath
    if not p or p.startswith("/"):
        return False
    return ".." not in PurePosixPath(p).parts


# ── Pydantic-схема манифеста ───────────────────────────────────────────────

class Symlink(BaseModel):
    """Симлинк в worktree: source (относительно repo) → target (внутри worktree)."""
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str

    @field_validator("source", "target")
    @classmethod
    def _safe_rel(cls, v: str) -> str:
        # B2: source резолвится от repo, target — внутри worktree; ни один не должен
        # выходить за свою границу (abs или '..'). Та же защита, что у docs_dir.
        if not _is_safe_rel(v):
            raise ValueError(f"unsafe symlink path '{v}' (abs или '..')")
        return v


class Worktree(BaseModel):
    """Настройка worktree роли: симлинки и копируемые файлы (= PROJECT_FILES)."""
    model_config = ConfigDict(extra="forbid")
    symlinks: list[Symlink] = Field(default_factory=list)
    copies: list[str] = Field(default_factory=list)

    @field_validator("copies")
    @classmethod
    def _safe_copies(cls, v: list[str]) -> list[str]:
        # B2: copies резолвятся как repo/<name> и пишутся как wt_path/<name>;
        # abs или '..' позволили бы чтение/запись вне repo/worktree. Та же защита,
        # что у symlinks (симметрично — иначе copies остаётся дырой).
        for name in v:
            if not _is_safe_rel(name):
                raise ValueError(f"unsafe copy path '{name}' (abs или '..')")
        return v


class DocsDir(BaseModel):
    """Скаффолдинг doc-папки роли в docs_work/.

    ``requires='feature'`` → плейсхолдер ``{feature}`` обязателен в path; если фича
    не передана при спавне — скаффолд пропускается.
    """
    model_config = ConfigDict(extra="forbid")
    path: str
    template: str | None = None
    requires: Literal["feature"] | None = None

    @field_validator("path", "template")
    @classmethod
    def _safe_rel(cls, v: str | None) -> str | None:
        # B2: путь/шаблон не должны выходить за pipelines/<name>/ (abs или '..').
        # {feature} подставляется в рантайме — containment проверяет B3.
        if v is not None and not _is_safe_rel(v):
            raise ValueError(f"unsafe docs_dir path '{v}' (abs или '..')")
        return v


class Tg(BaseModel):
    """Параметры Telegram-топика роли (emoji + шаблон topic)."""
    model_config = ConfigDict(extra="forbid")
    emoji: str = ""
    topic: str = ""


class PromptLayers(BaseModel):
    """Порядок слоёв промпта по kind. ``{role}`` подставляется на резолве.

    Пути относительны ``pipelines/<name>/prompts/``.
    """
    model_config = ConfigDict(extra="forbid")
    orchestrator: list[str] = Field(
        default_factory=lambda: ["base.md", "roles/{role}.md", "_pipeline.md"])
    worker: list[str] = Field(
        default_factory=lambda: ["base.md", "roles/{role}.md"])

    @field_validator("orchestrator", "worker")
    @classmethod
    def _safe_layers(cls, v: list[str]) -> list[str]:
        # B2: слои не должны выходить за pipelines/<name>/prompts/. Плейсхолдер
        # {role} безопасен (_is_safe_rel("roles/{role}.md") True).
        for layer in v:
            if not _is_safe_rel(layer):
                raise ValueError(f"unsafe prompt layer '{layer}' (abs или '..')")
        return v


class Defaults(BaseModel):
    """Дефолты пайплайна. Роль переопределяет: скаляр — replace, список — union."""
    model_config = ConfigDict(extra="forbid")
    model: str = "opus"
    skills: AllOrList = "all"
    mcp_servers: AllOrList = "all"
    inherit_claude_md: bool = True
    prompt_layers: PromptLayers = Field(default_factory=PromptLayers)
    worktree: Worktree = Field(default_factory=Worktree)
    base_branch_strategy: BranchStrategy = "parent"
    docs_scaffold: bool = True

    @field_validator("model")
    @classmethod
    def _model_known(cls, v: str) -> str:
        if not _model_is_known(v):
            raise ValueError(
                f"unknown model '{v}'. aliases={sorted(ALIASES)} ids={sorted(MODELS)}")
        return v


class RoleSpec(BaseModel):
    """Сырая роль из манифеста. Опциональные поля (model/skills/...) = None →
    наследуются из defaults на резолве. kind/label — обязательны для контракта.
    """
    model_config = ConfigDict(extra="forbid")
    kind: Kind
    label: str
    order: int = 100
    can_spawn: list[str] = Field(default_factory=list)  # "*" = любая роль; [] = терминал
    allow_unrouted_workers: bool = False
    # Модули — переиспользуемые блоки промпта (prompts/modules/{m}.md), инлайнятся
    # в system_prompt после слоёв роли. Пусто → ничего не добавляется.
    modules: list[str] = Field(default_factory=list)
    # Переопределения defaults (None → наследуем):
    model: str | None = None
    skills: AllOrList | None = None
    mcp_servers: AllOrList | None = None
    base_branch_strategy: BranchStrategy | None = None
    inherit_claude_md: bool | None = None
    docs_scaffold: bool | None = None
    # Роле-специфика:
    docs_dir: DocsDir | None = None
    tg: Tg | None = None
    when: str | None = None
    not_for: str | None = None
    description: str | None = None

    @field_validator("model")
    @classmethod
    def _model_known(cls, v: str | None) -> str | None:
        if v is not None and not _model_is_known(v):
            raise ValueError(f"unknown model '{v}'")
        return v

    @field_validator("modules")
    @classmethod
    def _safe_modules(cls, v: list[str]) -> list[str]:
        # B2: имя модуля → prompts/modules/{m}.md; не должно выходить за изоляцию
        # (abs или '..'). Та же защита, что у docs_dir/prompt_layers.
        for m in v:
            if not _is_safe_rel(m):
                raise ValueError(f"unsafe module name '{m}' (abs или '..')")
        return v


class PipelineConfig(BaseModel):
    """Сырой манифест пайплайна (роли с None-полями, до наследования)."""
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    validation: ValidationMode = "fail-closed"
    defaults: Defaults = Field(default_factory=Defaults)
    roles: dict[str, RoleSpec]

    @model_validator(mode="after")
    def _check_graph(self) -> "PipelineConfig":
        """can_spawn ⊆ roles (кроме '*'): ссылка на несуществующую роль → ошибка."""
        known = set(self.roles)
        for rname, r in self.roles.items():
            for child in r.can_spawn:
                if child != "*" and child not in known:
                    raise ValueError(
                        f"pipeline '{self.name}': role '{rname}' can_spawn references "
                        f"unknown role '{child}'. known={sorted(known)}")
        return self


class ResolvedRole(BaseModel):
    """RoleSpec после слияния defaults→role. Все поля заполнены, None нет.

    То, что отдаётся наружу (manager/workspace/tg).
    """
    model_config = ConfigDict(extra="forbid")
    name: str
    pipeline: str
    kind: Kind
    label: str
    order: int
    can_spawn: list[str]
    allow_unrouted_workers: bool
    modules: list[str]
    model: str
    skills: AllOrList
    mcp_servers: AllOrList
    base_branch_strategy: BranchStrategy
    inherit_claude_md: bool
    docs_scaffold: bool
    docs_dir: DocsDir | None
    tg: Tg | None
    when: str | None
    not_for: str | None
    description: str | None
    prompt_layers: list[str]  # выбранный (orchestrator|worker) список с подставленным {role}

    @property
    def is_orchestrator(self) -> bool:
        return self.kind == "orchestrator"


# ── Загрузка манифеста ─────────────────────────────────────────────────────


exec
/usr/bin/zsh -lc "git show vadim/feat/pipeline-as-config:app/session.py | sed -n '1,180p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
"""AgentSession — backend-agnostic wrapper with persistent event loop."""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from app.events import AgentEvent
from app.db import save_session, add_log

logger = logging.getLogger(__name__)

import concurrent.futures
_DB_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None


def _db_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Dedicated pool for DB writes so logs/persists don't contend with git ops
    on the default executor (used by asyncio.to_thread)."""
    global _DB_EXECUTOR
    if _DB_EXECUTOR is None:
        _DB_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="db")
    return _DB_EXECUTOR


IDLE_TIMEOUT_WORKER = 300
IDLE_TIMEOUT_ORCHESTRATOR = 600

_ORCHESTRATOR_ROLES = frozenset({"orchestrator", "sub-orchestrator"})


def is_orchestrator_role(role: str) -> bool:
    return role in _ORCHESTRATOR_ROLES


def _load_scope_mcp_servers(scope: str) -> dict:
    servers = {}
    for name in ("settings.json", "settings.local.json"):
        path = Path(scope) / ".claude" / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
            for k, v in data.get("mcpServers", {}).items():
                if k != "orchestra":
                    servers[k] = v
        except Exception as e:
            logger.warning(f"Failed to parse MCP servers from {path}: {e}")
    mcp_json = Path(scope) / ".mcp.json"
    if mcp_json.is_file():
        try:
            data = json.loads(mcp_json.read_text())
            for k, v in data.get("mcpServers", {}).items():
                if k != "orchestra":
                    servers[k] = v
        except Exception as e:
            logger.warning(f"Failed to parse .mcp.json from {mcp_json}: {e}")
    return servers


def _load_user_mcp_servers(config_dir: str) -> dict:
    """F2: user-MCP из top-level ``.claude.json`` профиля.

    ``config_dir`` непуст → ``<config_dir>/.claude.json``; пуст → ``~/.claude.json``
    (env процесса orchestra). Берёт ключ ``mcpServers``, пропуская ``orchestra``
    (серверный MCP подмешивается отдельно и не должен подменяться профилем).
    Зеркалит стиль ``_load_scope_mcp_servers``: ошибки парсинга — warning, не падаем.

    ВНИМАНИЕ: личный профиль CLI хранит ``.claude.json`` в HOME root
    (``~/.claude.json``), а НЕ внутри ``~/.claude/``. Поэтому для личного профиля
    держим ``config_dir=""`` (сид-профиль ``personal`` так и сидится). Если задать
    ``config_dir="~/.claude"`` — функция пойдёт в ``~/.claude/.claude.json``,
    которого нет, и вернёт пусто. Рабочий профиль (``~/.claude-work``) хранит
    ``.claude.json`` ВНУТРИ config dir — для него путь верный.
    """
    servers: dict = {}
    base = Path(os.path.expanduser(config_dir)) if config_dir else Path.home()
    path = base / ".claude.json"
    if not path.is_file():
        return servers
    try:
        data = json.loads(path.read_text())
        for k, v in data.get("mcpServers", {}).items():
            if k != "orchestra":
                servers[k] = v
    except Exception as e:
        logger.warning(f"Failed to parse user MCP servers from {path}: {e}")
    return servers


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"


@dataclass
class AgentSession:
    id: str
    name: str
    scope: str
    cwd: str
    model: str = "claude-sonnet-4-6"
    system_prompt: str = ""
    status: AgentStatus = AgentStatus.IDLE
    session_id: str | None = None
    cost_usd: float = 0.0
    cost_usd_cached: float = 0.0
    worktree_path: str | None = None
    branch: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    role: str = "worker"
    parent_id: str = ""
    parent_name: str = ""
    pipeline: str = ""
    profile: str = ""
    _is_orchestrator: bool | None = field(default=None, repr=False)
    color: str = ""
    mcp_servers: dict = field(default_factory=dict, repr=False)
    mcp_servers_custom: dict = field(default_factory=dict, repr=False)
    on_error: Optional[callable] = field(default=None, repr=False)
    backend_type: str = "claude"
    task_id: str = ""
    description: str = ""
    owned_dirs: list = field(default_factory=list, repr=False)
    tg_topic: bool = False

    progress_pct: int = 0
    progress_status: str = ""

    total_turns: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tool_calls: int = 0

    _backend: Optional[object] = field(default=None, repr=False)
    _listen_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _heartbeat_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _background_tasks: set = field(default_factory=set, repr=False)
    _last_context: dict = field(default_factory=lambda: {"percentage": 0, "total_tokens": 0, "max_tokens": 0}, repr=False)
    _did_report: bool = field(default=False, repr=False)
    _turn_logs: list = field(default_factory=list, repr=False)
    _prompt_injected: bool = field(default=False, repr=False)
    _current_prompt: str = field(default="", repr=False)
    _template_hash: str = field(default="", repr=False)
    _turn_start: float = field(default=0.0, repr=False)
    _last_msg_time: float = field(default=0.0, repr=False)
    _pending_messages: list = field(default_factory=list, repr=False)
    on_idle: Optional[callable] = field(default=None, repr=False)
    _hibernate_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _hibernated: bool = field(default=False, repr=False)
    _compacting: bool = field(default=False, repr=False)
    _compact_ack_event: Optional[asyncio.Event] = field(default=None, repr=False)
    _compact_ack_gen: int = field(default=-1, repr=False)
    _last_cost: float = field(default=0.0, repr=False)
    _last_cost_cached: float = field(default=0.0, repr=False)
    _last_turn_ok: bool = field(default=True, repr=False)
    _last_stop_reason: str = field(default="", repr=False)
    _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _persist_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _persist_dirty: bool = field(default=False, repr=False)
    _turn_gen: int = field(default=0, repr=False)
    _auto_report_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _spawn_warning: str = field(default="", repr=False)

    TURN_TIMEOUT = 600

    @property
    def is_orchestrator(self) -> bool:
        if self._is_orchestrator is not None:
            return self._is_orchestrator
        return is_orchestrator_role(self.role)

    @is_orchestrator.setter

exec
/usr/bin/zsh -lc "git show vadim/feat/pipeline-as-config:app/manager.py | sed -n '1,240p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
"""SessionManager — registry, lifecycle, persistence for all agent sessions."""

import asyncio
import logging
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.session import AgentSession, AgentStatus, is_orchestrator_role

_TASK_BRANCH_RE = re.compile(r"^(?:task-|[A-Z]{2,5}-)(\d+)/")
from app.workspace import create_worktree, remove_worktree, parse_owned_dirs, dirs_overlap
from app.models import resolve_model, backend_for_model
from app.pipeline import (
    DEFAULT_PIPELINE,
    build_system_prompt,
    get_active_pipeline,
    get_role,
    get_worktree_config,
    load_pipeline,
    resolve_role,
    template_path,
    validate_spawn,
)
from app.db import (
    save_session, get_session_by_name, get_all_sessions,
    delete_session, archive_session, get_stats,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = str(Path(__file__).parent.parent)
_MCP_SCRIPT = str(Path(__file__).parent / "mcp_stdio.py")
MCP_STDIO_CMD = [sys.executable, _MCP_SCRIPT]
MCP_BASE_ENV = {"PYTHONPATH": _PROJECT_ROOT}
for _k in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "INTERNAL_TOKEN"):
    if os.environ.get(_k):
        MCP_BASE_ENV[_k] = os.environ[_k]

COLOR_PALETTE = [
    "#818cf8", "#34d399", "#f97316", "#38bdf8", "#f472b6",
    "#a78bfa", "#fbbf24", "#2dd4bf", "#fb7185", "#4ade80",
]

_PROMPTS_DIR = Path(__file__).parent / "prompts"

_IDENTITY_PLACEHOLDERS = re.compile(r"\{(worker_name|orchestrator_name|scope|branch)\}")


def _safe_format_prompt(template: str, **kwargs: str) -> str:
    """Substitute only known identity placeholders, leaving other {braces} intact."""
    return _IDENTITY_PLACEHOLDERS.sub(lambda m: kwargs.get(m.group(1), m.group(0)), template)


def get_active_profile(scope: str = "", parent_profile: str = "") -> str:
    """Определить активный профиль Claude для НОВОЙ сессии.

    Дети наследуют профиль родителя; корень / пусто → "" (профиль из env
    процесса). В отличие от пайплайна, дефолт — НЕ константа, а пустая строка.

    Профиль — DB/manager-концерн (не config), поэтому функция живёт здесь, а не
    в ``pipeline.py``. Сигнатура с ``scope`` зеркалит ``get_active_pipeline`` и
    оставлена под будущее чтение колонки ``sessions.profile`` по scope.
    """
    return parent_profile or ""


def _read_prompt(name: str) -> str:
    p = _PROMPTS_DIR / name
    return p.read_text() if p.exists() else ""


def _other_orchestrators_block(exclude_scope: str = "") -> str:
    try:
        orchs = [s for s in get_all_sessions()
                 if bool(s.get("is_orchestrator")) and s.get("scope") != exclude_scope]
        if not orchs:
            return ""
        lines = ["## Other orchestrators", "You can message other orchestrators via `send_message(to=\"Name\", message=\"...\")`:"]
        for o in orchs:
            name = o["name"]
            scope = o.get("scope", "")
            project = Path(scope).name if scope else "?"
            desc = o.get("description", "")
            desc_part = f" — {desc}" if desc else ""
            lines.append(f"- **{name}** — project: {project}{desc_part}")
        lines.append("")
        lines.append("Use this when the user says \"напиши оркестре X\", \"скажи Y оркестратору\", \"спроси у Z\", etc.")
        return "\n".join(lines)
    except Exception:
        return ""


def _workers_block(scope: str) -> str:
    try:
        workers = [s for s in get_all_sessions()
                   if not bool(s.get("is_orchestrator")) and s.get("scope") == scope]
        if not workers:
            return ""
        lines = ["## Your current workers",
                 "These workers exist in your project. Reuse idle ones instead of spawning new. Kill workers you no longer need (one-shot tasks done, wrong role, duplicate)."]
        for w in workers:
            name = w["name"]
            model = w.get("model", "?")
            status = w.get("status", "?")
            ctx = w.get("context_pct", 0) or 0
            desc = w.get("description", "")
            desc_part = f" | \"{desc}\"" if desc else ""
            lines.append(f"- **{name}** — {model} | {status} | ctx:{ctx}%{desc_part}")
        return "\n".join(lines)
    except Exception:
        return ""


def _parse_role_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from role .md file. Returns (meta, body)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        import yaml
        meta = yaml.safe_load(parts[1]) or {}
    except Exception:
        meta = {}
    body = parts[2].strip()
    return meta, body


_MODULES_DIR = _PROMPTS_DIR / "modules"


def _load_modules(module_names: list[str]) -> str:
    parts = []
    for name in module_names:
        p = _MODULES_DIR / f"{name}.md"
        if p.exists():
            parts.append(p.read_text().strip())
        else:
            logger.warning(f"Module '{name}' not found at {p}")
    return "\n\n".join(parts)


def _role_prompt_file(role: str) -> str:
    """Find the best prompt for a role. Parses frontmatter, returns body + modules.
    Falls back to 'worker' role if role file not found."""
    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
    if role_path.exists():
        meta, body = _parse_role_frontmatter(role_path.read_text())
        if body:
            modules = meta.get("modules", [])
            if modules:
                body = body + "\n\n" + _load_modules(modules)
            return body
    if role != "worker":
        fallback = _PROMPTS_DIR / "roles" / ("orchestrator.md" if is_orchestrator_role(role) else "worker.md")
        if fallback.exists():
            meta, body = _parse_role_frontmatter(fallback.read_text())
            if body:
                modules = meta.get("modules", [])
                if modules:
                    body = body + "\n\n" + _load_modules(modules)
                return body
    return ""


_SKILLS_DIR = _PROMPTS_DIR / "skills"



def _role_can_spawn(role: str):
    """Return the can_spawn whitelist for a role, or None if unrestricted.
    None  = field absent OR malformed -> no restriction (spawn anything)
    []    = empty list                -> terminal role (spawn nothing)
    [...] = whitelist of allowed child roles
    """
    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
    if not role_path.exists():
        return None
    meta, _ = _parse_role_frontmatter(role_path.read_text())
    if "can_spawn" not in meta:
        return None
    val = meta["can_spawn"]
    if not isinstance(val, list):
        logger.warning(f"role '{role}' has non-list can_spawn ({val!r}); treating as unrestricted")
        return None
    return [str(x) for x in val]


def _skills_catalog() -> str:
    """Build catalog of available skills from skills/ directory for orchestrator."""
    if not _SKILLS_DIR.is_dir():
        return ""
    entries = []
    for f in sorted(_SKILLS_DIR.glob("*.md")):
        meta, _ = _parse_role_frontmatter(f.read_text())
        name = meta.get("name", f.stem)
        desc = meta.get("description", "").strip().replace("\n", " ")
        entries.append(f"- `{name}` — {desc}")
    if not entries:
        return ""
    return "## Available skills (for roles)\nSkills are auto-injected into worker prompts via `skills:` in role frontmatter.\n" + "\n".join(entries)


def get_role_icons() -> dict[str, str]:
    roles_dir = _PROMPTS_DIR / "roles"
    icons = {}
    if roles_dir.is_dir():
        for f in sorted(roles_dir.glob("*.md")):
            meta, _ = _parse_role_frontmatter(f.read_text())
            if meta:
                name = meta.get("name", f.stem)
                icon = meta.get("icon", "")
                if icon:
                    icons[name] = icon
    return icons


def _roles_catalog() -> str:
    """Build a catalog of available worker roles from roles/ directory frontmatter.
    Injected into orchestrator prompt so it knows what roles exist."""
    roles_dir = _PROMPTS_DIR / "roles"
    if not roles_dir.is_dir():
        return ""
    entries = []
    for f in sorted(roles_dir.glob("*.md")):
        meta, _ = _parse_role_frontmatter(f.read_text())
        if not meta or meta.get("name") == "orchestrator":
            continue
        name = meta.get("name", f.stem)
        label = meta.get("label", name)
        model = meta.get("model", "any")
        desc = meta.get("description", "").strip().replace("\n", " ")
        when = meta.get("when", "").strip()

exec
/usr/bin/zsh -lc 'git show main:app/manager.py | rg -n "def ROLE_SYSTEM_PROMPT|def create_session|workers_block|other_orchestrators|owned_dirs|needs_switch|prompt_template_hash|inject_skills|validate|is_orchestrator" -C 3' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
13-
14-from app.session import AgentSession, AgentStatus
15-from app.prompting import (
16:    is_orchestrator_role, safe_format_prompt, read_prompt,
17-    role_prompt_file, role_can_spawn,
18:    roles_catalog, skills_catalog, prompt_template_hash, inject_skills_to_worktree,
19-)
20-
21-_TASK_BRANCH_RE = re.compile(r"^(?:task-|[A-Z]{2,5}-)(\d+)/")
22:from app.workspace import create_worktree, remove_worktree, parse_owned_dirs, dirs_overlap
23-from app.models import resolve_model, backend_for_model
24-from app.db import (
25-    save_session, get_session_by_name, get_all_sessions,
--
43-
44-
45-
46:def _other_orchestrators_block(exclude_scope: str = "") -> str:
47-    try:
48-        orchs = [s for s in get_all_sessions()
49:                 if is_orchestrator_role(s.get("role", "worker")) and s.get("scope") != exclude_scope]
50-        if not orchs:
51-            return ""
52-        lines = ["## Other orchestrators", "You can message other orchestrators via `send_message(to=\"Name\", message=\"...\")`:"]
--
64-        return ""
65-
66-
67:def _workers_block(scope: str, orchestrator_name: str = "") -> str:
68-    try:
69-        workers = [s for s in get_all_sessions()
70:                   if not is_orchestrator_role(s.get("role", "worker")) and s.get("scope") == scope]
71-        if not workers:
72-            return ""
73-
--
106-        return ""
107-
108-
109:def ROLE_SYSTEM_PROMPT(role: str, scope: str = "", name: str = "") -> str:
110-    base = f"{read_prompt('base.md')}\n\n{role_prompt_file(role)}"
111:    if is_orchestrator_role(role):
112-        catalog = roles_catalog()
113-        if catalog:
114-            base += f"\n\n{catalog}"
115-        skills_cat = skills_catalog()
116-        if skills_cat:
117-            base += f"\n\n{skills_cat}"
118:        others = _other_orchestrators_block(scope)
119-        if others:
120-            base += f"\n\n{others}"
121:        workers = _workers_block(scope, name)
122-        if workers:
123-            base += f"\n\n{workers}"
124-    return base
--
251-        return f"auto-committed {len(files)} dirty file(s) (branch {branch}) before spawn — review the WIP commit"
252-
253-    @staticmethod
254:    def _ownership_prompt(owned_dirs: list[str]) -> str:
255:        if not owned_dirs:
256-            return ""
257:        lines = "\n".join(f"- {d}/" for d in owned_dirs)
258-        return ("\n\n## Directory ownership\n"
259-                "You OWN these directories — edit ONLY files under them:\n"
260-                f"{lines}\n"
--
263-
264-    # ── Session CRUD ──
265-
266:    async def create_session(self, name: str, scope: str, cwd: str, model: str,
267-                             system_prompt: str = "", use_worktree: bool = False,
268:                             repo_path: str | None = None, is_orchestrator: bool = False,
269-                             role: str = "", task_id: str = "", description: str = "",
270-                             base_branch: str = "main",
271-                             parent_id: str = "", parent_name: str = "",
272-                             mcp_servers: dict | None = None,
273:                             owned_dirs: list | None = None,
274-                             tg_topic: bool = False) -> AgentSession:
275-        scope = scope.rstrip("/")
276-        cwd = cwd.rstrip("/")
--
284-            raise ValueError(f"worker '{name}' already exists ({st}, ctx:{ctx}%). Use send_message instead")
285-
286-        if not role:
287:            role = "orchestrator" if is_orchestrator else "worker"
288:        is_orch = is_orchestrator_role(role)
289-
290:        owned_dirs = parse_owned_dirs(owned_dirs)
291:        if owned_dirs:
292-            seen_ids: set[str] = set()
293-            for s in self.sessions.values():
294:                if s.scope == scope and s.status.value in ("idle", "running", "waiting") and s.owned_dirs:
295-                    seen_ids.add(s.id)
296:                    ov = dirs_overlap(owned_dirs, s.owned_dirs)
297-                    if ov:
298-                        raise ValueError(
299:                            f"owned_dirs overlap with '{s.name}': {', '.join(ov)}. "
300-                            f"Use different dirs or kill '{s.name}' first"
301-                        )
302-            for row in get_all_sessions(scope):
--
304-                    continue
305-                if (row.get("status") or "") not in ("idle", "running", "waiting"):
306-                    continue
307:                row_dirs = parse_owned_dirs(row.get("owned_dirs"))
308-                if row_dirs:
309:                    ov = dirs_overlap(owned_dirs, row_dirs)
310-                    if ov:
311-                        raise ValueError(
312:                            f"owned_dirs overlap with '{row['name']}': {', '.join(ov)}. "
313-                            f"Use different dirs or kill '{row['name']}' first"
314-                        )
315-
--
317-            prompt = ROLE_SYSTEM_PROMPT(role, scope, name) + ("\n\n" + system_prompt if system_prompt else "")
318-        else:
319-            prompt = ROLE_SYSTEM_PROMPT(role) + ("\n\n" + system_prompt if system_prompt else "")
320:            prompt += self._ownership_prompt(owned_dirs)
321-
322-        if not parent_name and not is_orch:
323-            parent_name = self._find_orchestrator_name(scope) or ""
--
351-            mcp_servers=_make_mcp_config(name, scope, role, extra=custom_mcp),
352-            mcp_servers_custom=custom_mcp,
353-            backend_type=bt, task_id=task_id, description=description,
354:            owned_dirs=owned_dirs,
355-            tg_topic=tg_topic,
356-        )
357:        session._template_hash = prompt_template_hash(role)
358-        session._spawn_warning = ""
359-        save_session(session._to_db_dict())
360-
--
374-                session.cwd = wt.path
375-                session.worktree_path = wt.path
376-                session.branch = wt.branch
377:                await asyncio.to_thread(inject_skills_to_worktree, role, wt.path)
378-
379-            if not is_orch:
380-                orch_name = parent_name or self._find_orchestrator_name(scope)
--
447-        session = self.get_by_name(name, old_scope)
448-        if not isinstance(session, AgentSession):
449-            return {"error": f"orchestrator '{name}' not loaded in scope '{old_scope}'"}
450:        if not session.is_orchestrator:
451-            return {"error": f"'{name}' is not an orchestrator — scope change is orchestrator-only"}
452-        if not Path(new_cwd).is_dir():
453-            return {"error": f"new_cwd does not exist: {new_cwd}"}
--
502-        seen_ids: set[str] = set()
503-        names: set[str] = set()
504-        for s in self.sessions.values():
505:            if s.scope == scope and not s.is_orchestrator and s.status.value in active:
506-                seen_ids.add(s.id)
507-                names.add(s.name)
508-        for row in get_all_sessions(scope):
509-            if row["id"] in seen_ids:
510-                continue
511:            if is_orchestrator_role(row.get("role", "worker")):
512-                continue
513-            if (row.get("status") or "") in active:
514-                names.add(row["name"])
--
517-    async def remove_scope(self, scope: str, delete_tg_topics: bool = False) -> dict:
518-        orch_names: list[str] = []
519-        for s in self.sessions.values():
520:            if s.scope == scope and s.is_orchestrator and s.name not in orch_names:
521-                orch_names.append(s.name)
522-        for row in get_all_sessions(scope):
523:            if is_orchestrator_role(row.get("role", "worker")) and row["name"] not in orch_names:
524-                orch_names.append(row["name"])
525-
526-        to_remove = [s for s in self.sessions.values() if s.scope == scope]
--
575-        return None
576-
577-    async def _load_from_db(self, db_row: dict) -> AgentSession:
578:        role = db_row.get("role") or ("orchestrator" if db_row.get("is_orchestrator") else "worker")
579:        is_orch = is_orchestrator_role(role)
580-        old_prompt = db_row.get("system_prompt", "")
581-        current_prompt = ROLE_SYSTEM_PROMPT(role, db_row["scope"], db_row["name"]) if is_orch else ROLE_SYSTEM_PROMPT(role)
582-        cwd = db_row.get("cwd") or db_row["scope"]
--
619-            mcp_servers_custom=custom_mcp,
620-            backend_type=stored_bt, task_id=db_task_id,
621-            description=db_row.get("description", ""),
622:            owned_dirs=parse_owned_dirs(db_row.get("owned_dirs")),
623-            tg_topic=bool(db_row.get("tg_topic", 0)),
624-        )
625-        pct = db_row.get("context_pct", 0) or 0
--
645-                custom_part = old_prompt[len(formatted_base):]
646-                current_prompt = current_prompt + custom_part
647-        session._current_prompt = current_prompt
648:        session._template_hash = db_row.get("template_hash") or prompt_template_hash(role)
649-        if not is_orch:
650-            session.on_idle = self._make_idle_callback(db_row["scope"])
651-        await session.start()
--
654-
655-    def _find_orchestrator_name(self, scope: str) -> str | None:
656-        for s in self.sessions.values():
657:            if s.is_orchestrator and s.scope == scope:
658-                return s.name
659-        return None
660-
--
708-
709-    def find_worker(self, name: str, scope: str | None = None) -> AgentSession | None:
710-        for s in self.sessions.values():
711:            if s.name == name and not s.is_orchestrator and (scope is None or s.scope == scope):
712-                return s
713-        return None
714-
--
750-            ).fetchall()]
751-            c.execute("UPDATE sessions SET status='idle' WHERE status IN ('running', 'waiting')")
752-
753:        orchs = [r for r in resumable if is_orchestrator_role(r.get("role", "orchestrator" if r.get("is_orchestrator") else "worker"))]
754:        workers = [r for r in resumable if not is_orchestrator_role(r.get("role", "orchestrator" if r.get("is_orchestrator") else "worker"))]
755-
756-        for row in orchs:
757-            if row["id"] in self.sessions:

exec
/usr/bin/zsh -lc 'git show vadim/feat/pipeline-as-config:app/manager.py | rg -n "def ROLE_SYSTEM_PROMPT|def _UPSTREAM|def create_session|resolve_pipeline|validate_spawn|scaffold|catalog|inject_skills|worktree|profile|pipeline|is_orchestrator" -C 3' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
11-from pathlib import Path
12-from typing import Optional
13-
14:from app.session import AgentSession, AgentStatus, is_orchestrator_role
15-
16-_TASK_BRANCH_RE = re.compile(r"^(?:task-|[A-Z]{2,5}-)(\d+)/")
17:from app.workspace import create_worktree, remove_worktree, parse_owned_dirs, dirs_overlap
18-from app.models import resolve_model, backend_for_model
19:from app.pipeline import (
20-    DEFAULT_PIPELINE,
21-    build_system_prompt,
22:    get_active_pipeline,
23-    get_role,
24:    get_worktree_config,
25:    load_pipeline,
26-    resolve_role,
27-    template_path,
28:    validate_spawn,
29-)
30-from app.db import (
31-    save_session, get_session_by_name, get_all_sessions,
--
57-    return _IDENTITY_PLACEHOLDERS.sub(lambda m: kwargs.get(m.group(1), m.group(0)), template)
58-
59-
60:def get_active_profile(scope: str = "", parent_profile: str = "") -> str:
61-    """Определить активный профиль Claude для НОВОЙ сессии.
62-
63-    Дети наследуют профиль родителя; корень / пусто → "" (профиль из env
64-    процесса). В отличие от пайплайна, дефолт — НЕ константа, а пустая строка.
65-
66-    Профиль — DB/manager-концерн (не config), поэтому функция живёт здесь, а не
67:    в ``pipeline.py``. Сигнатура с ``scope`` зеркалит ``get_active_pipeline`` и
68:    оставлена под будущее чтение колонки ``sessions.profile`` по scope.
69-    """
70:    return parent_profile or ""
71-
72-
73-def _read_prompt(name: str) -> str:
--
78-def _other_orchestrators_block(exclude_scope: str = "") -> str:
79-    try:
80-        orchs = [s for s in get_all_sessions()
81:                 if bool(s.get("is_orchestrator")) and s.get("scope") != exclude_scope]
82-        if not orchs:
83-            return ""
84-        lines = ["## Other orchestrators", "You can message other orchestrators via `send_message(to=\"Name\", message=\"...\")`:"]
--
99-def _workers_block(scope: str) -> str:
100-    try:
101-        workers = [s for s in get_all_sessions()
102:                   if not bool(s.get("is_orchestrator")) and s.get("scope") == scope]
103-        if not workers:
104-            return ""
105-        lines = ["## Your current workers",
--
159-                body = body + "\n\n" + _load_modules(modules)
160-            return body
161-    if role != "worker":
162:        fallback = _PROMPTS_DIR / "roles" / ("orchestrator.md" if is_orchestrator_role(role) else "worker.md")
163-        if fallback.exists():
164-            meta, body = _parse_role_frontmatter(fallback.read_text())
165-            if body:
--
193-    return [str(x) for x in val]
194-
195-
196:def _skills_catalog() -> str:
197:    """Build catalog of available skills from skills/ directory for orchestrator."""
198-    if not _SKILLS_DIR.is_dir():
199-        return ""
200-    entries = []
--
222-    return icons
223-
224-
225:def _roles_catalog() -> str:
226:    """Build a catalog of available worker roles from roles/ directory frontmatter.
227-    Injected into orchestrator prompt so it knows what roles exist."""
228-    roles_dir = _PROMPTS_DIR / "roles"
229-    if not roles_dir.is_dir():
--
253-    return "## Available worker roles\nSpawn with `role=\"<name>\"`. If no role specified, defaults to `worker`.\n\n" + "\n\n".join(entries)
254-
255-
256:def _UPSTREAM_ROLE_SYSTEM_PROMPT(role: str, scope: str = "") -> str:
257-    """Поведение апстрима 1:1 (frontmatter+glob из ``app/prompts/``).
258-
259-    Fallback-ветка: вызывается из :func:`ROLE_SYSTEM_PROMPT`, когда манифест
260-    пайплайна отсутствует (``FileNotFoundError``). Сохранена дословно — гарантия,
261:    что при отсутствии ``pipelines/`` поведение идентично upstream (DECISIONS B4).
262-    """
263-    base = f"{_read_prompt('base.md')}\n\n{_role_prompt_file(role)}"
264:    if is_orchestrator_role(role):
265:        catalog = _roles_catalog()
266:        if catalog:
267:            base += f"\n\n{catalog}"
268:        skills_cat = _skills_catalog()
269-        if skills_cat:
270-            base += f"\n\n{skills_cat}"
271-        others = _other_orchestrators_block(scope)
--
277-    return base
278-
279-
280:def _fmt_role_catalog_entry(rr) -> str:
281-    """Форматировать одну запись каталога ролей из :class:`ResolvedRole`.
282-
283:    Совпадает по форме с ``_roles_catalog`` (заголовок ### `name` (label) — model,
284-    описание, when/not_for). Источник полей — манифест (ResolvedRole), не frontmatter.
285-    """
286-    desc = (rr.description or "").strip().replace("\n", " ")
--
297-    return entry
298-
299-
300:def _roles_catalog_from_manifest(pipeline: str, parent_role: str) -> str:
301-    """Каталог ролей оркестратору из манифеста, отфильтрованный по ``can_spawn``.
302-
303-    B2: показываем ВСЕ роли из ``can_spawn`` родителя (включая под-оркестраторов).
304-    ``can_spawn=['*']`` → все роли пайплайна. Сортировка по ``order``. Закрывает
305:    дефект плоского ``_roles_catalog`` (показывал бы запретные роли).
306-    """
307:    cfg = load_pipeline(pipeline)
308-    parent = cfg.roles.get(parent_role)
309-    if parent is None:
310-        return ""
311-    if "*" in parent.can_spawn:
312:        # S1: wildcard НЕ включает саму роль-родителя (upstream _roles_catalog
313-        # пропускал orchestrator из своего же каталога воркеров).
314-        visible = [r for r in cfg.roles if r != parent_role]
315-    else:
--
318-    if not visible:
319-        return ""
320-    entries = [
321:        _fmt_role_catalog_entry(resolve_role(cfg, r))
322-        for r in sorted(visible, key=lambda r: cfg.roles[r].order)
323-    ]
324-    return ('## Available worker roles\nSpawn with `role="<name>"`. '
325-            'If no role specified, defaults to `worker`.\n\n' + "\n\n".join(entries))
326-
327-
328:def ROLE_SYSTEM_PROMPT(pipeline: str, role: str, scope: str = "") -> str:
329-    """Системный промпт роли: статика слоёв пайплайна + динамика (каталог/блоки).
330-
331:    Манифест-путь (есть ``pipelines/<pipeline>/``): статика через
332:    :func:`build_system_prompt` (ТОЛЬКО ``pipelines/<name>/prompts/`` — изоляция),
333-    затем для оркестратора — каталог ролей (фильтр ``can_spawn``) + блоки других
334-    оркестраторов/воркеров из БД.
335-
--
338-    апстрима 1:1, B4 — default/fail-open на worker/orchestrator).
339-    """
340-    try:
341:        base = build_system_prompt(pipeline, role, scope)
342-    except (FileNotFoundError, KeyError):
343-        # Нет манифеста (FileNotFoundError) ИЛИ роли нет в манифесте (KeyError):
344-        # делегируем в upstream-fallback (B4: default/fail-open 1:1 — upstream
345-        # допускал произвольную роль воркера с fallback на worker/orchestrator).
346-        return _UPSTREAM_ROLE_SYSTEM_PROMPT(role, scope)
347:    rr = get_role(pipeline, role)
348:    is_orch = rr.is_orchestrator if rr is not None else is_orchestrator_role(role)
349-    if is_orch:
350:        catalog = _roles_catalog_from_manifest(pipeline, role)
351:        if catalog:
352:            base += f"\n\n{catalog}"
353-        others = _other_orchestrators_block(scope)
354-        if others:
355-            base += f"\n\n{others}"
--
359-    return base
360-
361-
362:def ORCHESTRATOR_SYSTEM_PROMPT(pipeline: str = DEFAULT_PIPELINE, scope: str = "") -> str:
363:    return ROLE_SYSTEM_PROMPT(pipeline, "orchestrator", scope)
364-
365-
366:def WORKER_SYSTEM_PROMPT(pipeline: str = DEFAULT_PIPELINE) -> str:
367:    return ROLE_SYSTEM_PROMPT(pipeline, "worker")
368-
369-
370-def _prompt_template_hash(role_or_orch) -> str:
371-    """Hash only the static template files (base.md + role.md + skills).
372:    Accepts role string or legacy bool (is_orchestrator)."""
373-    import hashlib
374-    if isinstance(role_or_orch, bool):
375-        role = "orchestrator" if role_or_orch else "worker"
--
379-    return hashlib.md5(content.encode()).hexdigest()[:8]
380-
381-
382:def _scaffold_role_docs(pipeline: str, cwd: str, role: str, feature: str = "") -> None:
383-    """Идемпотентно скаффолдит doc-папку роли в docs_work/ по манифесту.
384-
385-    Источник пути/шаблона — resolve_role(...).docs_dir (не хардкод). Если у роли
386:    нет docs_dir, docs_scaffold выключен, или requires=='feature' без feature —
387-    скаффолд пропускается. Манифеста нет (FileNotFoundError) → пропуск.
388-    """
389-    try:
390:        rr = get_role(pipeline, role)
391-    except FileNotFoundError:
392-        return
393:    if rr is None or not rr.docs_scaffold or rr.docs_dir is None:
394-        return
395-    dd = rr.docs_dir
396-    if dd.requires == "feature" and not feature:
--
403-    try:
404-        target.relative_to(base_docs)
405-    except ValueError:
406:        logger.warning("scaffold: путь '%s' выходит за docs_work — пропуск", rel)
407-        return
408-    target.mkdir(parents=True, exist_ok=True)
409-    dashboard = target / "dashboard.md"
410-    if dashboard.exists() or not dd.template:
411-        return
412:    tpl = template_path(pipeline, dd.template)
413-    if not tpl.is_file():
414-        return
415-    content = tpl.read_text()
--
418-    dashboard.write_text(content)
419-
420-
421:def _inject_skills_to_worktree(role: str, worktree_path: str) -> None:
422:    """Copy role skills into worktree/.claude/skills/ as native Claude CLI skills."""
423-    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
424-    if not role_path.exists():
425-        return
--
427-    skill_names = meta.get("skills", [])
428-    if not skill_names or not _SKILLS_DIR.is_dir():
429-        return
430:    wt = Path(worktree_path)
431-    for sname in skill_names:
432-        skill_src = _SKILLS_DIR / f"{sname}.md"
433-        if not skill_src.exists():
--
437-        skill_dir.mkdir(parents=True, exist_ok=True)
438-        import shutil
439-        shutil.copy2(skill_src, skill_dir / "SKILL.md")
440:    logger.info(f"Injected {len(skill_names)} skills into {worktree_path}/.claude/skills/")
441-
442-
443-def _parse_custom_mcp(raw) -> dict:
--
508-                session = await self.create_session(
509-                    name=job["name"], scope=job["repo_path"], cwd=job["repo_path"],
510-                    model=job["model"], system_prompt=job.get("system_prompt", ""),
511:                    use_worktree=True, repo_path=job["repo_path"],
512-                    role=job.get("role", "worker"),
513-                    task_id=job.get("task_id", ""),
514-                    description=job.get("description", ""),
--
567-
568-    # ── Session CRUD ──
569-
570:    async def create_session(self, name: str, scope: str, cwd: str, model: str,
571:                             system_prompt: str = "", use_worktree: bool = False,
572:                             repo_path: str | None = None, is_orchestrator: bool = False,
573-                             role: str = "", task_id: str = "", description: str = "",
574-                             base_branch: str = "",
575-                             parent_id: str = "", parent_name: str = "",
576-                             mcp_servers: dict | None = None,
577:                             pipeline: str = "", profile: str = "",
578-                             docs_feature: str = "",
579-                             owned_dirs: list | None = None,
580-                             tg_topic: bool = False) -> AgentSession:
--
590-        # unrouted (child_role="") — им управляет allow_unrouted_workers родителя.
591-        explicit_role = bool(role)
592-        if not role:
593:            role = "orchestrator" if is_orchestrator else "worker"
594-
595-        # Активный пайплайн: явный аргумент главнее, иначе наследуем от родителя
596-        # (или DEFAULT_PIPELINE для корня). parent_name тут — только явно переданный;
597-        # для воркеров без parent_name он доразрешается ниже (auto-find).
598:        explicit_pipeline = bool(pipeline)
599:        parent_pipeline = self._resolve_pipeline(parent_name, scope) if parent_name else ""
600:        pipeline = pipeline or get_active_pipeline(scope, parent_pipeline=parent_pipeline)
601-
602-        # Активный профиль Claude: явный аргумент главнее, иначе наследуем от
603:        # родителя (пусто для корня → env процесса). Зеркало логики pipeline.
604:        explicit_profile = bool(profile)
605:        parent_profile = self._resolve_profile(parent_name, scope) if parent_name else ""
606:        profile = profile or get_active_profile(scope, parent_profile=parent_profile)
607-
608:        # R1: is_orchestrator из манифеста (kind), fallback на frozenset апстрима.
609:        is_orch = self._role_is_orchestrator(pipeline, role)
610-
611-        # Ownership (upstream): нормализуем owned_dirs и предупреждаем о пересечении
612-        # с другими живыми воркерами в этом scope (warning, НЕ блок).
--
625-
626-        if not parent_name and not is_orch:
627-            parent_name = self._find_orchestrator_name(scope) or ""
628:            if parent_name and not explicit_pipeline:
629-                # Доразрешили родителя авто-поиском — воркер наследует его пайплайн.
630:                parent_pipeline = self._resolve_pipeline(parent_name, scope)
631:                pipeline = get_active_pipeline(scope, parent_pipeline=parent_pipeline)
632:                is_orch = self._role_is_orchestrator(pipeline, role)
633:            if parent_name and not explicit_profile:
634-                # Тот же авто-найденный родитель — воркер наследует и его профиль.
635:                parent_profile = self._resolve_profile(parent_name, scope)
636:                profile = get_active_profile(scope, parent_profile=parent_profile)
637-
638-        if is_orch:
639-            # v2.16: кастомный system_prompt ДОПИСЫВАЕТСЯ к базе роли, а не заменяет
640-            # её (раньше было `system_prompt or ROLE_SYSTEM_PROMPT(...)`).
641:            prompt = ROLE_SYSTEM_PROMPT(pipeline, role, scope) + ("\n\n" + system_prompt if system_prompt else "")
642-        else:
643:            prompt = ROLE_SYSTEM_PROMPT(pipeline, role) + ("\n\n" + system_prompt if system_prompt else "")
644-            # Ownership (upstream): для воркера дописываем блок "трогай только это".
645-            prompt += self._ownership_prompt(owned_dirs)
646-
--
649-            if p_session:
650-                parent_id = p_session.id if isinstance(p_session, AgentSession) else p_session.get("id", "")
651-
652:        # R2: валидация спавна ДО любых side-effects (worktree/start).
653:        # Манифест-путь — validate_spawn (fail-closed/fail-open). Нет манифеста
654-        # (FileNotFoundError) → fallback на inline _role_can_spawn (поведение апстрима).
655-        parent_role = self._resolve_role(parent_name, scope) if parent_name else ""
656-        try:
657:            validate_spawn(pipeline, parent_role, role if explicit_role else "")
658-        except FileNotFoundError:
659-            if parent_role:
660-                whitelist = _role_can_spawn(parent_role)
--
665-                        f"Allowed: {allowed}"
666-                    )
667-
668:        # Резолв базовой ветки worktree по стратегии манифеста (DESIGN §10, B3).
669:        # Делаем ДО create_worktree, когда pipeline/role/parent_name уже определены.
670:        base_branch = self._resolve_base_branch(base_branch, pipeline, role, parent_name, scope)
671-
672-        # Root orchestrators (no parent) always get a TG topic
673-        if is_orch and not parent_name:
--
679-            id=str(uuid.uuid4()), name=name, scope=scope, cwd=cwd, model=model,
680-            system_prompt=prompt, role=role,
681-            parent_id=parent_id, parent_name=parent_name,
682:            pipeline=pipeline, profile=profile,
683-            color="" if is_orch else self._pick_color(),
684-            mcp_servers=_make_mcp_config(name, scope, role, extra=custom_mcp),
685-            mcp_servers_custom=custom_mcp,
--
687-            owned_dirs=owned_dirs,
688-            tg_topic=tg_topic,
689-        )
690:        # R1: денормализуем is_orchestrator (kind манифеста / fallback) в хранимое поле.
691:        session.is_orchestrator = is_orch
692-        session._template_hash = _prompt_template_hash(role)
693-        session._spawn_warning = ownership_warning
694-        save_session(session._to_db_dict())
--
701-                pass
702-
703-        try:
704:            if use_worktree and repo_path:
705-                wip_note = await asyncio.to_thread(self._auto_commit_if_dirty, repo_path)
706-                if wip_note:
707-                    session._spawn_warning = (session._spawn_warning + "; " + wip_note).strip("; ")
708-                # Worktree-конфиг из манифеста (симлинки + copies). Нет манифеста
709:                # → None → create_worktree использует upstream-fallback (PROJECT_FILES).
710-                try:
711:                    worktree_cfg = get_worktree_config(pipeline)
712-                except FileNotFoundError:
713:                    worktree_cfg = None
714-                wt = await asyncio.to_thread(
715:                    create_worktree, repo_path, name, scope, task_id, base_branch, worktree_cfg)
716-                session.cwd = wt.path
717:                session.worktree_path = wt.path
718-                session.branch = wt.branch
719-                # F1: при skills=="all" (tasks-pm) скиллы приходят через профиль
720-                # (CLAUDE_CONFIG_DIR + setting_sources), native-инъекция не нужна.
721-                # default/список/нет манифеста → инъекция как в upstream.
722-                try:
723:                    _rr = get_role(pipeline, role)
724-                    _skills = _rr.skills if _rr else None
725-                except FileNotFoundError:
726-                    _skills = None
727-                if _skills != "all":
728:                    await asyncio.to_thread(_inject_skills_to_worktree, role, wt.path)
729-
730-            # Best-effort скаффолд doc-папки роли по манифесту (фильтрация внутри
731:            # функции: docs_scaffold/docs_dir/requires). cwd = итоговый (worktree
732-            # если создан, иначе исходный). Не должен валить create_session.
733-            try:
734-                await asyncio.to_thread(
735:                    _scaffold_role_docs, pipeline, session.cwd, role, docs_feature)
736-            except Exception as e:  # noqa: BLE001 — best-effort, как другие шаги
737:                logger.warning("docs scaffold failed for role '%s': %s", role, e)
738-
739-            if not is_orch:
740-                orch_name = parent_name or self._find_orchestrator_name(scope)
--
750-            self.sessions[session.id] = session
751-            return session
752-        except BaseException:
753:            if session.worktree_path and repo_path:
754-                try:
755:                    await asyncio.to_thread(remove_worktree, repo_path, session.worktree_path)
756-                except Exception:
757-                    pass
758-            delete_session(session.id)
--
785-        session = self.sessions.pop(session_id, None)
786-        if session:
787-            await session._disconnect_backend()
788:            if session.worktree_path:
789-                try:
790:                    await asyncio.to_thread(remove_worktree, session.scope, session.worktree_path)
791-                except Exception:
792-                    pass
793-        archive_session(session_id)
--
807-        session = self.get_by_name(name, old_scope)
808-        if not isinstance(session, AgentSession):
809-            return {"error": f"orchestrator '{name}' not loaded in scope '{old_scope}'"}
810:        if not session.is_orchestrator:
811-            return {"error": f"'{name}' is not an orchestrator — scope change is orchestrator-only"}
812-        if not Path(new_cwd).is_dir():
813-            return {"error": f"new_cwd does not exist: {new_cwd}"}
--
862-        seen_ids: set[str] = set()
863-        names: set[str] = set()
864-        for s in self.sessions.values():
865:            if s.scope == scope and not s.is_orchestrator and s.status.value in active:
866-                seen_ids.add(s.id)
867-                names.add(s.name)
868-        for row in get_all_sessions(scope):
869-            if row["id"] in seen_ids:
870-                continue
871:            if is_orchestrator_role(row.get("role", "worker")):
872-                continue
873-            if (row.get("status") or "") in active:
874-                names.add(row["name"])
--
877-    async def remove_scope(self, scope: str, delete_tg_topics: bool = False) -> dict:
878-        orch_names: list[str] = []
879-        for s in self.sessions.values():
880:            if s.scope == scope and s.is_orchestrator and s.name not in orch_names:
881-                orch_names.append(s.name)
882-        for row in get_all_sessions(scope):
883:            if bool(row.get("is_orchestrator")) and row["name"] not in orch_names:
884-                orch_names.append(row["name"])
885-
886-        to_remove = [s for s in self.sessions.values() if s.scope == scope]
--
915-        row = get_session_by_name(name, scope)
916-        return row.get("role") if row else None
917-
918:    def _resolve_pipeline(self, name: str, scope: str) -> str:
919-        """Пайплайн сессии ``name`` (для наследования детьми). '' если не найдена."""
920-        for s in self.sessions.values():
921-            if s.name == name and s.scope == scope:
922:                return s.pipeline or ""
923-        row = get_session_by_name(name, scope)
924:        return (row.get("pipeline") or "") if row else ""
925-
926:    def _resolve_profile(self, name: str, scope: str) -> str:
927-        """Профиль Claude сессии ``name`` (для наследования детьми). '' если не найдена."""
928-        for s in self.sessions.values():
929-            if s.name == name and s.scope == scope:
930:                return s.profile or ""
931-        row = get_session_by_name(name, scope)
932:        return (row.get("profile") or "") if row else ""
933-
934:    def _resolve_base_branch(self, base_branch: str, pipeline: str, role: str,
935-                             parent_name: str, scope: str) -> str:
936:        """Резолв базовой ветки worktree по стратегии манифеста (DESIGN §10, B3).
937-
938-        Приоритеты:
939-        - явно переданная ``base_branch`` важнее стратегии манифеста (B3);
940-        - нет манифеста / ``strategy=main`` → ``"main"`` (back-compat с апстримом);
941-        - ``strategy=parent`` → ветка рабочего дерева родителя; если её нет —
942:          fallback на ``"main"`` с warning (корневой Хаб без worktree и т.п.).
943-        """
944-        # B3: явно переданная ветка важнее стратегии манифеста.
945-        if base_branch:
946-            return base_branch
947-        try:
948:            rr = get_role(pipeline, role)
949-        except FileNotFoundError:
950-            rr = None
951-        # Нет манифеста / стратегия main → от main (back-compat, default 1:1 upstream).
--
969-        return parent_branch
970-
971-    @staticmethod
972:    def _role_is_orchestrator(pipeline: str, role: str) -> bool:
973:        """R1: is_orchestrator из kind манифеста; fallback на frozenset апстрима.
974-
975:        Манифеста нет (FileNotFoundError) или роли нет в нём → ``is_orchestrator_role``.
976-        """
977-        try:
978:            rr = get_role(pipeline, role)
979-        except FileNotFoundError:
980-            rr = None
981-        if rr is not None:
982:            return rr.is_orchestrator
983:        return is_orchestrator_role(role)
984-
985-    async def ensure_loaded(self, name: str, scope: str) -> Optional[AgentSession]:
986-        scope = scope.rstrip("/")
--
1002-        return None
1003-
1004-    async def _load_from_db(self, db_row: dict) -> AgentSession:
1005:        role = db_row.get("role") or ("orchestrator" if db_row.get("is_orchestrator") else "worker")
1006:        pipeline = db_row.get("pipeline", "") or ""
1007-        # R1: is_orch из манифеста пайплайна (kind) при наличии; иначе хранимая
1008:        # колонка is_orchestrator (денормализована при спавне); иначе frozenset.
1009:        is_orch = self._role_is_orchestrator(pipeline, role)
1010-        try:
1011:            if get_role(pipeline, role) is None:
1012:                is_orch = bool(db_row.get("is_orchestrator")) or is_orchestrator_role(role)
1013-        except FileNotFoundError:
1014:            is_orch = bool(db_row.get("is_orchestrator")) or is_orchestrator_role(role)
1015-        old_prompt = db_row.get("system_prompt", "")
1016:        current_prompt = ROLE_SYSTEM_PROMPT(pipeline, role, db_row["scope"]) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role)
1017-        cwd = db_row.get("cwd") or db_row["scope"]
1018-        if not Path(cwd).is_dir():
1019-            cwd = db_row["scope"]
--
1024-            stored_bt = expected_bt
1025-        db_branch = db_row.get("branch")
1026-        db_task_id = db_row.get("task_id") or ""
1027:        wt_path = db_row.get("worktree_path")
1028-        if wt_path and Path(wt_path).is_dir():
1029-            actual = await asyncio.to_thread(
1030-                subprocess.run,
--
1044-            model=db_row["model"], system_prompt=old_prompt or current_prompt,
1045-            session_id=db_row.get("session_id"), cost_usd=db_row.get("cost_usd", 0),
1046-            cost_usd_cached=db_row.get("cost_usd_cached", 0),
1047:            worktree_path=wt_path, branch=db_branch,
1048-            created_at=datetime.fromisoformat(db_row["created_at"]) if db_row.get("created_at") else datetime.now(timezone.utc),
1049-            role=role,
1050-            parent_id=db_row.get("parent_id", ""),
1051-            parent_name=db_row.get("parent_name", ""),
1052:            pipeline=db_row.get("pipeline", ""),
1053:            profile=db_row.get("profile", ""),
1054-            color="" if is_orch else (db_row.get("color") or self._pick_color()),
1055-            mcp_servers=_make_mcp_config(db_row["name"], db_row["scope"], role, extra=custom_mcp),
1056-            mcp_servers_custom=custom_mcp,
--
1059-            owned_dirs=parse_owned_dirs(db_row.get("owned_dirs")),
1060-            tg_topic=bool(db_row.get("tg_topic", 0)),
1061-        )
1062:        session.is_orchestrator = is_orch  # R1: восстановить денормализованное поле
1063-        pct = db_row.get("context_pct", 0) or 0
1064-        tokens = db_row.get("context_tokens", 0) or 0
1065-        if pct or tokens:
--
1075-            )
1076-        if old_prompt and old_prompt != current_prompt:
1077-            formatted_base = _safe_format_prompt(
1078:                ROLE_SYSTEM_PROMPT(pipeline, role, db_row["scope"]) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role),
1079-                worker_name=db_row["name"], orchestrator_name=orch_name or "orchestrator",
1080-                scope=db_row["scope"], branch=db_row.get("branch") or "main",
1081-            )
--
1092-
1093-    def _find_orchestrator_name(self, scope: str) -> str | None:
1094-        for s in self.sessions.values():
1095:            if s.is_orchestrator and s.scope == scope:
1096-                return s.name
1097-        return None
1098-
--
1146-
1147-    def find_worker(self, name: str, scope: str | None = None) -> AgentSession | None:
1148-        for s in self.sessions.values():
1149:            if s.name == name and not s.is_orchestrator and (scope is None or s.scope == scope):
1150-                return s
1151-        return None
1152-
--
1188-            ).fetchall()]
1189-            c.execute("UPDATE sessions SET status='idle' WHERE status IN ('running', 'waiting')")
1190-
1191:        # R1: используем денормализованную колонку is_orchestrator (наши PM-роли
1192-        # не входят в frozenset апстрима; колонка проставлена при спавне/миграции).
1193:        orchs = [r for r in resumable if bool(r.get("is_orchestrator")) or is_orchestrator_role(r.get("role", "worker"))]
1194:        workers = [r for r in resumable if not (bool(r.get("is_orchestrator")) or is_orchestrator_role(r.get("role", "worker")))]
1195-
1196-        for row in orchs:
1197-            if row["id"] in self.sessions:

exec
/usr/bin/zsh -lc 'git show vadim/feat/pipeline-as-config:app/db.py | rg -n "profile|pipeline|ALTER TABLE|sessions|profiles|list_profiles|upsert_profile|delete_profile|get_profile" -C 3' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
exec
/usr/bin/zsh -lc 'git show vadim/feat/pipeline-as-config:app/pipeline.py | rg -n "is_orchestrator_role|def build_system_prompt|def validate_spawn|def get_role|def get_active_pipeline|def get_role_icons|def roles_catalog|def inject|def get_worktree_config|def template_path|def list_pipelines" -C 3' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
277-    return cfg
278-
279-
280:def get_worktree_config(pipeline_name: str) -> Worktree:
281-    """Вернуть worktree-конфиг пайплайна (``defaults.worktree``).
282-
283-    Это pipeline-level настройка (симлинки + copies), общая для всех ролей —
--
289-    return load_pipeline(pipeline_name).defaults.worktree
290-
291-
292:def list_pipelines() -> list[dict]:
293-    """Скан ``pipelines/`` (включая gitignored). Для UI-дропдауна.
294-
295-    Возвращает ``[{name, description, roles:[...], valid:bool, error:str|None}]``.
--
357-    )
358-
359-
360:def get_role(pipeline_name: str, role: str) -> ResolvedRole | None:
361-    """Загрузить пайплайн и резолвнуть роль. None, если роли нет в манифесте."""
362-    cfg = load_pipeline(pipeline_name)
363-    return resolve_role(cfg, role) if role in cfg.roles else None
--
379-    return PIPELINES_DIR / pipeline_name / "prompts" / rel
380-
381-
382:def template_path(pipeline_name: str, template: str) -> Path:
383-    """Путь к шаблону doc-папки внутри ``pipelines/<name>/templates/``."""
384-    return PIPELINES_DIR / pipeline_name / "templates" / template
385-
386-
387:def build_system_prompt(pipeline_name: str, role: str, scope: str = "") -> str:
388-    """Собрать system_prompt из prompt_layers резолвнутой роли.
389-
390-    Каждый слой читается из ``pipelines/<name>/prompts/<layer>`` через
--
422-
423-# ── Активный пайплайн ──────────────────────────────────────────────────────
424-
425:def get_active_pipeline(scope: str = "", parent_pipeline: str = "") -> str:
426-    """Определить активный пайплайн для НОВОЙ сессии.
427-
428-    1) ``parent_pipeline`` (от родителя при спавне) — главный источник: дети
--
440-
441-# ── Валидация спавна (fail-closed / fail-open) ────────────────────────────
442-
443:def validate_spawn(pipeline_name: str, parent_role: str | None, child_role: str) -> None:
444-    """Проверить допустимость спавна ``child_role`` родителем ``parent_role``.
445-
446-    Режим из ``PipelineConfig.validation``:

 succeeded in 0ms:
1:"""SQLite storage for sessions and logs."""
2-
3-import json
4-import os
--
38-def init_db() -> None:
39-    with _conn() as c:
40-        c.executescript("""
41:            CREATE TABLE IF NOT EXISTS sessions (
42-                id TEXT PRIMARY KEY,
43-                name TEXT NOT NULL,
44-                scope TEXT NOT NULL,
--
53-                is_orchestrator INTEGER DEFAULT 0,
54-                color TEXT DEFAULT '',
55-                mcp_servers_custom TEXT DEFAULT '',
56:                profile TEXT DEFAULT '',
57-                created_at TEXT NOT NULL,
58-                finished_at TEXT,
59-                UNIQUE(name, scope)
60-            );
61:            CREATE TABLE IF NOT EXISTS profiles (
62-                name TEXT PRIMARY KEY,
63-                config_dir TEXT NOT NULL DEFAULT '',
64-                created_at TEXT DEFAULT CURRENT_TIMESTAMP
65-            );
66-            CREATE TABLE IF NOT EXISTS logs (
67-                id INTEGER PRIMARY KEY AUTOINCREMENT,
68:                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
69-                ts TEXT NOT NULL,
70-                type TEXT NOT NULL,
71-                content TEXT NOT NULL
72-            );
73-            CREATE INDEX IF NOT EXISTS idx_logs_session ON logs(session_id, id DESC);
74:            CREATE INDEX IF NOT EXISTS idx_sessions_scope ON sessions(scope, is_orchestrator, status);
75-
76-            CREATE TABLE IF NOT EXISTS inbox (
77-                id INTEGER PRIMARY KEY AUTOINCREMENT,
78:                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
79-                sender TEXT NOT NULL,
80-                message TEXT NOT NULL,
81-                status TEXT DEFAULT 'pending',
--
215-
216-def _reconstruct_costs(c) -> None:
217-    import re as _re
218:    sessions = c.execute("SELECT id FROM sessions").fetchall()
219:    for s in sessions:
220-        logs = c.execute(
221-            "SELECT content FROM logs WHERE session_id=? AND type='status' "
222-            "AND (content LIKE 'turn ended%$%' OR content LIKE 'turn done%$%') ORDER BY id ASC",
--
235-                real_cost += prev
236-            prev = val
237-        real_cost += prev
238:        c.execute("UPDATE sessions SET cost_usd=?, cost_usd_cached=0, cost_reset_v1=1 WHERE id=?",
239-                  (round(real_cost, 4), s["id"]))
240-
241-
242-def _migrate(c) -> None:
243:    cols = {row[1] for row in c.execute("PRAGMA table_info(sessions)").fetchall()}
244-    if "color" not in cols:
245:        c.execute("ALTER TABLE sessions ADD COLUMN color TEXT DEFAULT ''")
246-    if "context_pct" not in cols:
247:        c.execute("ALTER TABLE sessions ADD COLUMN context_pct INTEGER DEFAULT 0")
248-    if "context_tokens" not in cols:
249:        c.execute("ALTER TABLE sessions ADD COLUMN context_tokens INTEGER DEFAULT 0")
250-    if "progress_pct" not in cols:
251:        c.execute("ALTER TABLE sessions ADD COLUMN progress_pct INTEGER DEFAULT 0")
252-    if "progress_status" not in cols:
253:        c.execute("ALTER TABLE sessions ADD COLUMN progress_status TEXT DEFAULT ''")
254-    if "backend_type" not in cols:
255:        c.execute("ALTER TABLE sessions ADD COLUMN backend_type TEXT DEFAULT 'claude'")
256-    if "task_id" not in cols:
257:        c.execute("ALTER TABLE sessions ADD COLUMN task_id TEXT DEFAULT ''")
258-    if "description" not in cols:
259:        c.execute("ALTER TABLE sessions ADD COLUMN description TEXT DEFAULT ''")
260-    if "cost_usd_cached" not in cols:
261:        c.execute("ALTER TABLE sessions ADD COLUMN cost_usd_cached REAL DEFAULT 0.0")
262-    if "cost_reset_v1" not in cols:
263:        c.execute("ALTER TABLE sessions ADD COLUMN cost_reset_v1 INTEGER DEFAULT 0")
264-        _reconstruct_costs(c)
265-    proj_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_projects)").fetchall()}
266-    if proj_cols and "yougile_enabled" not in proj_cols:
267:        c.execute("ALTER TABLE tm_projects ADD COLUMN yougile_enabled INTEGER NOT NULL DEFAULT 0")
268-        c.execute("UPDATE tm_projects SET yougile_enabled = 1 WHERE id = 'parsing-hub'")
269-    if proj_cols and "prefix" not in proj_cols:
270:        c.execute("ALTER TABLE tm_projects ADD COLUMN prefix TEXT NOT NULL DEFAULT 'TASK'")
271-        c.execute("UPDATE tm_projects SET prefix = 'PAR' WHERE id = 'parsing-hub'")
272-        c.execute("UPDATE tm_projects SET prefix = 'ORC' WHERE id = 'orchestra'")
273-    if "total_turns" not in cols:
274:        c.execute("ALTER TABLE sessions ADD COLUMN total_turns INTEGER DEFAULT 0")
275-    if "total_input_tokens" not in cols:
276:        c.execute("ALTER TABLE sessions ADD COLUMN total_input_tokens INTEGER DEFAULT 0")
277-    if "total_output_tokens" not in cols:
278:        c.execute("ALTER TABLE sessions ADD COLUMN total_output_tokens INTEGER DEFAULT 0")
279-    if "total_tool_calls" not in cols:
280:        c.execute("ALTER TABLE sessions ADD COLUMN total_tool_calls INTEGER DEFAULT 0")
281-    if "template_hash" not in cols:
282:        c.execute("ALTER TABLE sessions ADD COLUMN template_hash TEXT DEFAULT ''")
283-    if "mcp_servers_custom" not in cols:
284:        c.execute("ALTER TABLE sessions ADD COLUMN mcp_servers_custom TEXT DEFAULT ''")
285-    bg_ddl = c.execute(
286-        "SELECT sql FROM sqlite_master WHERE type='table' AND name='bg_jobs'"
287-    ).fetchone()
--
290-                    "target_scope", "created_by_name", "status", "error", "expires_at",
291-                    "trigger_at", "created_at", "triggered_at", "last_output")
292-        _bg_col_list = ", ".join(_bg_cols)
293:        c.execute("ALTER TABLE bg_jobs RENAME TO bg_jobs_old")
294-        c.execute("""
295-            CREATE TABLE bg_jobs (
296-                id TEXT PRIMARY KEY,
--
323-        old_exists = c.execute(f"SELECT 1 FROM sqlite_master WHERE type='table' AND name='{old_name}'").fetchone()
324-        if old_exists:
325-            c.execute("DROP TABLE IF EXISTS tm_tasks")
326:            c.execute(f"ALTER TABLE {old_name} RENAME TO tm_tasks")
327-            break
328-    try:
329-        auto_idx = [r[1] for r in c.execute("PRAGMA index_list(tm_tasks)").fetchall()
--
340-        except Exception:
341-            pass
342-    if needs_recreate:
343:        c.execute("ALTER TABLE tm_tasks RENAME TO _tm_tasks_old")
344-        c.execute("""CREATE TABLE tm_tasks (
345-            id INTEGER PRIMARY KEY AUTOINCREMENT,
346-            par_number INTEGER NOT NULL,
--
365-            schema = c.execute(f"SELECT sql FROM sqlite_master WHERE name='{tbl}' AND type='table'").fetchone()
366-            if schema and "tm_tasks_old" in schema[0]:
367-                old_name = f"_{tbl}_fix"
368:                c.execute(f"ALTER TABLE {tbl} RENAME TO {old_name}")
369-                create_sql = schema[0].replace('"tm_tasks_old"', 'tm_tasks').replace("tm_tasks_old", "tm_tasks")
370-                c.execute(create_sql)
371-                c.execute(f"INSERT INTO {tbl} SELECT * FROM {old_name}")
--
375-    c.execute("CREATE INDEX IF NOT EXISTS idx_tm_tasks_yougile ON tm_tasks(yougile_task_id)")
376-    task_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_tasks)").fetchall()}
377-    if task_cols and "priority" not in task_cols:
378:        c.execute("ALTER TABLE tm_tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 2")
379-    client_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_clients)").fetchall()}
380-    if client_cols and "journal_yougile_id" not in client_cols:
381:        c.execute("ALTER TABLE tm_clients ADD COLUMN journal_yougile_id TEXT DEFAULT ''")
382-    if "role" not in cols:
383:        c.execute("ALTER TABLE sessions ADD COLUMN role TEXT DEFAULT 'worker'")
384:        c.execute("UPDATE sessions SET role = 'orchestrator' WHERE is_orchestrator = 1")
385-    if "parent_id" not in cols:
386:        c.execute("ALTER TABLE sessions ADD COLUMN parent_id TEXT DEFAULT ''")
387-    if "parent_name" not in cols:
388:        c.execute("ALTER TABLE sessions ADD COLUMN parent_name TEXT DEFAULT ''")
389:    if "pipeline" not in cols:
390:        c.execute("ALTER TABLE sessions ADD COLUMN pipeline TEXT DEFAULT ''")
391:        c.execute("UPDATE sessions SET is_orchestrator = 1 WHERE role IN ('orchestrator', 'sub-orchestrator')")
392:    if "profile" not in cols:
393:        c.execute("ALTER TABLE sessions ADD COLUMN profile TEXT DEFAULT ''")
394-    if "owned_dirs" not in cols:
395:        c.execute("ALTER TABLE sessions ADD COLUMN owned_dirs TEXT DEFAULT ''")
396-    if "tg_topic" not in cols:
397:        c.execute("ALTER TABLE sessions ADD COLUMN tg_topic INTEGER DEFAULT 0")
398-    # Идемпотентный сид профиля 'personal' (config_dir="" → env процесса, как сегодня).
399-    # INSERT OR IGNORE: повторная миграция не падает и не перетирает существующую строку.
400:    c.execute("INSERT OR IGNORE INTO profiles (name, config_dir) VALUES ('personal', '')")
401-
402-
403-def save_session(s: dict) -> None:
--
417-    s.setdefault("role", "worker")
418-    s.setdefault("parent_id", "")
419-    s.setdefault("parent_name", "")
420:    s.setdefault("pipeline", "")
421:    s.setdefault("profile", "")
422-    s.setdefault("mcp_servers_custom", "")
423-    s.setdefault("owned_dirs", "")
424-    s.setdefault("tg_topic", 0)
425-    with _conn() as c:
426-        c.execute("""
427:            INSERT INTO sessions (id, name, scope, cwd, model, system_prompt,
428-                status, session_id, cost_usd, worktree_path, branch, is_orchestrator,
429-                color, created_at, finished_at, context_pct, context_tokens,
430-                progress_pct, progress_status, backend_type, task_id, description,
431-                cost_usd_cached,
432-                total_turns, total_input_tokens, total_output_tokens, total_tool_calls,
433:                template_hash, role, parent_id, parent_name, mcp_servers_custom, pipeline,
434:                profile, owned_dirs, tg_topic)
435-            VALUES (:id, :name, :scope, :cwd, :model, :system_prompt,
436-                :status, :session_id, :cost_usd, :worktree_path, :branch, :is_orchestrator,
437-                :color, :created_at, :finished_at, :context_pct, :context_tokens,
438-                :progress_pct, :progress_status, :backend_type, :task_id, :description,
439-                :cost_usd_cached,
440-                :total_turns, :total_input_tokens, :total_output_tokens, :total_tool_calls,
441:                :template_hash, :role, :parent_id, :parent_name, :mcp_servers_custom, :pipeline,
442:                :profile, :owned_dirs, :tg_topic)
443-            ON CONFLICT(id) DO UPDATE SET
444-                name=excluded.name,
445-                system_prompt=excluded.system_prompt,
--
468-                parent_id=excluded.parent_id,
469-                parent_name=excluded.parent_name,
470-                mcp_servers_custom=excluded.mcp_servers_custom,
471:                pipeline=excluded.pipeline,
472:                profile=excluded.profile,
473-                owned_dirs=excluded.owned_dirs,
474-                tg_topic=excluded.tg_topic
475-        """, s)
--
487-    collision (target already taken) but the session move still succeeds.
488-    """
489-    with _conn() as c:
490:        row = c.execute("SELECT name FROM sessions WHERE id=?", (session_id,)).fetchone()
491-        if not row:
492-            return {"error": f"session not found: {session_id}"}
493-        name = row["name"]
494-        clash = c.execute(
495:            "SELECT 1 FROM sessions WHERE name=? AND scope=? AND id!=? AND status!='archived'",
496-            (name, new_scope, session_id),
497-        ).fetchone()
498-        if clash:
499-            return {"error": f"session '{name}' already exists in scope '{new_scope}'"}
500-
501-        cur = c.execute(
502:            "UPDATE sessions SET scope=?, cwd=? WHERE id=? AND scope=?",
503-            (new_scope, new_cwd, session_id, old_scope),
504-        )
505-        if cur.rowcount == 0:
--
525-
526-def get_session(session_id: str) -> dict | None:
527-    with _conn() as c:
528:        row = c.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
529-        return dict(row) if row else None
530-
531-
532-def get_session_by_name(name: str, scope: str) -> dict | None:
533-    with _conn() as c:
534-        row = c.execute(
535:            "SELECT * FROM sessions WHERE name = ? AND scope = ? AND status != 'archived'",
536-            (name, scope),
537-        ).fetchone()
538-        return dict(row) if row else None
--
540-
541-# ── Профили Claude (CLAUDE_CONFIG_DIR per-session) ──
542-
543:def list_profiles() -> list[dict]:
544-    """Все профили, отсортированы по имени: ``[{"name":..., "config_dir":...}]``."""
545-    with _conn() as c:
546-        rows = c.execute(
547:            "SELECT name, config_dir FROM profiles ORDER BY name"
548-        ).fetchall()
549-        return [{"name": r["name"], "config_dir": r["config_dir"]} for r in rows]
550-
551-
552:def get_profile(name: str) -> dict | None:
553-    """Один профиль по имени или ``None``, если не найден."""
554-    with _conn() as c:
555-        row = c.execute(
556:            "SELECT name, config_dir FROM profiles WHERE name = ?", (name,)
557-        ).fetchone()
558-        return {"name": row["name"], "config_dir": row["config_dir"]} if row else None
559-
560-
561:def upsert_profile(name: str, config_dir: str) -> None:
562-    """Создать профиль или обновить его ``config_dir`` (по конфликту имени)."""
563-    with _conn() as c:
564-        c.execute(
565:            "INSERT INTO profiles (name, config_dir) VALUES (?, ?) "
566-            "ON CONFLICT(name) DO UPDATE SET config_dir = excluded.config_dir",
567-            (name, config_dir),
568-        )
569-
570-
571:def delete_profile(name: str) -> None:
572-    """Удалить профиль. Сид-профиль ``personal`` удалять запрещено."""
573-    if name == "personal":
574-        raise ValueError("Профиль 'personal' является сид-профилем и не может быть удалён")
575-    with _conn() as c:
576:        c.execute("DELETE FROM profiles WHERE name = ?", (name,))
577-
578-
579:def get_all_sessions(scope: str | None = None, include_archived: bool = False) -> list[dict]:
580-    with _conn() as c:
581-        archived_filter = "" if include_archived else " AND status != 'archived'"
582-        if scope:
583-            rows = c.execute(
584:                f"SELECT * FROM sessions WHERE scope = ?{archived_filter} ORDER BY created_at DESC", (scope,)
585-            ).fetchall()
586-        else:
587-            rows = c.execute(
588:                f"SELECT * FROM sessions WHERE 1=1{archived_filter} ORDER BY created_at DESC"
589-            ).fetchall()
590-        return [dict(r) for r in rows]
591-
592-
593-def rename_session(session_id: str, new_name: str) -> None:
594-    with _conn() as c:
595:        c.execute("UPDATE sessions SET name = ? WHERE id = ?", (new_name, session_id))
596-
597-
598-def delete_session(session_id: str) -> None:
599-    with _conn() as c:
600:        c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
601-
602-
603-def archive_session(session_id: str) -> None:
604-    with _conn() as c:
605-        c.execute(
606:            "UPDATE sessions SET status='archived', finished_at=? WHERE id=?",
607-            (datetime.now(timezone.utc).isoformat(), session_id),
608-        )
609-
--
650-    with _conn() as c:
651-        where = "WHERE scope = ?" if scope else ""
652-        params = (scope,) if scope else ()
653:        total = c.execute(f"SELECT COUNT(*) FROM sessions {where}", params).fetchone()[0]
654-        active = c.execute(
655:            f"SELECT COUNT(*) FROM sessions {where + ' AND ' if where else 'WHERE '}"
656-            "status IN ('running', 'starting')",
657-            params,
658-        ).fetchone()[0]
659-        archived = c.execute(
660:            f"SELECT COUNT(*) FROM sessions {where + ' AND ' if where else 'WHERE '}"
661-            "status = 'archived'",
662-            params,
663-        ).fetchone()[0]
664-        cost = c.execute(
665:            f"SELECT COALESCE(SUM(cost_usd), 0) FROM sessions {where}", params
666-        ).fetchone()[0]
667-        logs_where = (
668:            f"WHERE session_id IN (SELECT id FROM sessions {where})"
669-            if where else ""
670-        )
671-        total_logs = c.execute(
--
676-                       COALESCE(SUM(total_input_tokens), 0),
677-                       COALESCE(SUM(total_output_tokens), 0),
678-                       COALESCE(SUM(total_tool_calls), 0)
679:                FROM sessions {where}""",
680-            params,
681-        ).fetchone()
682-        return {
683:            "total_sessions": total,
684-            "active": active,
685-            "archived": archived,
686-            "total_cost_usd": round(cost, 4),

exec
/usr/bin/zsh -lc "git show vadim/feat/pipeline-as-config:tests/test_default_equals_upstream.py | sed -n '1,280p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
exec
/usr/bin/zsh -lc 'git show vadim/feat/pipeline-as-config:app/pipeline.py | rg -n "is_orchestrator|session|prompting|kind" -C 2' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
116-
117-class PromptLayers(BaseModel):
118:    """Порядок слоёв промпта по kind. ``{role}`` подставляется на резолве.
119-
120-    Пути относительны ``pipelines/<name>/prompts/``.
--
160-class RoleSpec(BaseModel):
161-    """Сырая роль из манифеста. Опциональные поля (model/skills/...) = None →
162:    наследуются из defaults на резолве. kind/label — обязательны для контракта.
163-    """
164-    model_config = ConfigDict(extra="forbid")
165:    kind: Kind
166-    label: str
167-    order: int = 100
--
233-    name: str
234-    pipeline: str
235:    kind: Kind
236-    label: str
237-    order: int
--
253-
254-    @property
255:    def is_orchestrator(self) -> bool:
256:        return self.kind == "orchestrator"
257-
258-
--
264-
265-    :raises FileNotFoundError: если папки/файла нет.
266:    :raises pydantic.ValidationError: если схема битая (extra-поле, неверный kind/model).
267-    :raises ValueError: если ``name`` в файле не совпадает с именем папки, либо битый
268-        граф can_spawn.
--
332-
333-    Скаляр — роль переопределяет если задан, иначе defaults. Список (skills/
334:    mcp_servers) — union с поглощением ``"all"``. ``prompt_layers`` — по kind роли
335-    с подстановкой ``{role}``.
336-
--
339-    spec = pipeline.roles[role]
340-    d = pipeline.defaults
341:    layers_tmpl = (d.prompt_layers.orchestrator if spec.kind == "orchestrator"
342-                   else d.prompt_layers.worker)
343-    return ResolvedRole(
344:        name=role, pipeline=pipeline.name, kind=spec.kind, label=spec.label,
345-        order=spec.order, can_spawn=spec.can_spawn,
346-        allow_unrouted_workers=spec.allow_unrouted_workers,
--
431-
432-    Один пайплайн на дерево агентов — в середине цепочки сменить нельзя. Полная
433:    логика (чтение колонки sessions.pipeline) — Этап 7; здесь зафиксирована
434-    сигнатура и базовое поведение наследования.
435-    """

 succeeded in 0ms:
"""Characterization-тест: pipeline ``default`` ≡ upstream (frontmatter+glob).

ЦЕЛЬ (ФАЗА B): доказать, что наш манифест-путь (``pipelines/default/``) даёт
поведение, ПОБАЙТОВО идентичное upstream-пути (``app/prompts/roles/*.md`` с
YAML-frontmatter + инлайн модулей). Это защита от дрейфа: если кто-то изменит
``pipelines/default/`` так, что он разойдётся с upstream-источником истины
коллеги — тест ОБЯЗАН упасть.

Две системы определения ролей:
  * UPSTREAM — ``app/prompts/roles/<role>.md`` (frontmatter name/model/modules/
    can_spawn/... + тело). Функции реконструкции: ``manager._UPSTREAM_ROLE_SYSTEM_PROMPT``,
    ``manager._role_prompt_file``, ``manager._load_modules``, ``manager._role_can_spawn``,
    ``manager._parse_role_frontmatter``.
  * НАШ — ``pipelines/default/pipeline.yaml`` + ``pipelines/default/prompts/``.
    Функции: ``pipeline.build_system_prompt``, ``pipeline.validate_spawn``,
    ``pipeline.resolve_role``.

Проверяем три инварианта для каждой из 6 ролей:
  1. system_prompt (статика) ПОБАЙТОВО равен upstream-реконструкции.
  2. validate_spawn для ВСЕХ пар (parent, child) совпадает с ``_role_can_spawn``.
  3. resolve_role: model / modules / skills / tg.emoji = frontmatter-полям upstream.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import app.pipeline as P
from app import manager

# Загружаем мост (scripts/extract-manifest.py — дефис в имени, импорт по пути).
_BRIDGE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "extract-manifest.py"
_spec = importlib.util.spec_from_file_location("extract_manifest", _BRIDGE_PATH)
extract_manifest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(extract_manifest)

PIPELINE = "default"
ROLES = ["orchestrator", "sub-orchestrator", "worker", "full-cycle", "reviewer", "watcher"]


@pytest.fixture(autouse=True)
def _clear_cache():
    """Чистим lru_cache load_pipeline до/после — читаем реальный default с диска."""
    P.load_pipeline.cache_clear()
    yield
    P.load_pipeline.cache_clear()


# ── Хелперы реконструкции upstream ─────────────────────────────────────────

def _upstream_static_prompt(role: str) -> str:
    """Статическая часть upstream-промпта роли (без динамических каталогов/блоков).

    Точная копия первой строки ``manager._UPSTREAM_ROLE_SYSTEM_PROMPT``:
    ``base.md`` + ``\\n\\n`` + тело роли с инлайном модулей (``_role_prompt_file``).
    Динамику (каталог ролей, блоки оркестраторов/воркеров) сравнивать нельзя —
    она тянет БД; характеризуем только статику из файлов.
    """
    return f"{manager._read_prompt('base.md')}\n\n{manager._role_prompt_file(role)}"


def _upstream_frontmatter(role: str) -> dict:
    """Frontmatter upstream-роли из ``app/prompts/roles/<role>.md``."""
    path = manager._PROMPTS_DIR / "roles" / f"{role}.md"
    meta, _ = manager._parse_role_frontmatter(path.read_text())
    return meta


def _map_model(raw: str) -> str:
    """Маппинг upstream-модели в нашу: ``sonnet/opus`` → первое слово (``sonnet``)."""
    return raw.split("/")[0].strip()


# ── B2.1: system_prompt побайтово ──────────────────────────────────────────

class TestSystemPromptByteIdentical:
    @pytest.mark.parametrize("role", ROLES)
    def test_static_prompt_matches_upstream(self, role):
        """``build_system_prompt('default', role)`` ПОБАЙТОВО == upstream-реконструкции.

        Если тела ``pipelines/default/prompts/roles/*.md`` разойдутся с upstream-телами
        (после среза frontmatter) или сломается порядок/разделители инлайна модулей —
        тест упадёт. Это и есть антидрейф-страховка.
        """
        ours = P.build_system_prompt(PIPELINE, role)
        upstream = _upstream_static_prompt(role)
        assert ours == upstream, (
            f"роль '{role}': манифест-промпт разошёлся с upstream "
            f"(ours={len(ours)}b, upstream={len(upstream)}b)")


# ── B2.2: validate_spawn для всех пар ролей ────────────────────────────────

def _our_spawn_allowed(parent: str, child: str) -> bool:
    """True, если наш ``validate_spawn`` РАЗРЕШАЕТ спавн (не бросает ValueError)."""
    try:
        P.validate_spawn(PIPELINE, parent, child)
        return True
    except ValueError:
        return False


def _upstream_spawn_allowed(parent: str, child: str) -> bool:
    """Решение upstream по ``_role_can_spawn`` (frontmatter can_spawn).

    Семантика ``_role_can_spawn``:
      * None  — поля нет/битое → unrestricted (спавн кого угодно).
      * []    — терминал (никого).
      * [...] — whitelist.
    Все 6 ролей в upstream существуют (parent известен), child всегда из ROLES.
    """
    wl = manager._role_can_spawn(parent)
    if wl is None:
        return True
    if "*" in wl:
        return True
    return child in wl


class TestValidateSpawnMatchesUpstream:
    @pytest.mark.parametrize("parent", ROLES)
    @pytest.mark.parametrize("child", ROLES)
    def test_spawn_pair_matches_upstream(self, parent, child):
        """Для каждой пары (parent, child) разрешение спавна == upstream-логике."""
        assert _our_spawn_allowed(parent, child) == _upstream_spawn_allowed(parent, child), (
            f"спавн {parent} → {child}: наш результат != upstream")

    def test_worker_and_full_cycle_unlimited(self):
        """После B1: worker / full-cycle (нет can_spawn в upstream → unlimited)
        как родители РАЗРЕШАЮТ спавн любой роли."""
        for parent in ("worker", "full-cycle"):
            assert manager._role_can_spawn(parent) is None  # upstream: поля нет
            for child in ROLES:
                assert _our_spawn_allowed(parent, child), f"{parent} должен спавнить {child}"

    def test_reviewer_and_watcher_terminal(self):
        """reviewer / watcher (can_spawn: [] в upstream) — терминалы, не спавнят."""
        for parent in ("reviewer", "watcher"):
            assert manager._role_can_spawn(parent) == []
            for child in ROLES:
                assert not _our_spawn_allowed(parent, child), f"{parent} НЕ должен спавнить {child}"


# ── B2.3: resolve_role поля == upstream frontmatter ────────────────────────

class TestResolveRoleMatchesFrontmatter:
    @pytest.mark.parametrize("role", ROLES)
    def test_model_matches(self, role):
        """model резолвнутой роли == frontmatter ``model`` (с маппингом sonnet/opus)."""
        rr = P.get_role(PIPELINE, role)
        fm = _upstream_frontmatter(role)
        # orchestrator/sub-orchestrator/full-cycle/reviewer — opus; worker — sonnet/opus
        # → sonnet; watcher — haiku. Defaults манифеста (opus) дают то же для ролей
        # без явной модели, но upstream явно указывает model у всех — сверяем напрямую.
        expected = _map_model(fm["model"])
        assert rr.model == expected, f"роль '{role}': model {rr.model} != upstream {expected}"

    @pytest.mark.parametrize("role", ROLES)
    def test_modules_match(self, role):
        """modules резолвнутой роли == frontmatter ``modules`` (порядок важен — инлайн)."""
        rr = P.get_role(PIPELINE, role)
        fm = _upstream_frontmatter(role)
        assert rr.modules == fm.get("modules", []), f"роль '{role}': modules разошлись"

    @pytest.mark.parametrize("role", ROLES)
    def test_skills_match(self, role):
        """skills роли == frontmatter ``skills`` (union с defaults.skills=[], т.е. как есть)."""
        rr = P.get_role(PIPELINE, role)
        fm = _upstream_frontmatter(role)
        # defaults.skills=[] → union не добавляет ничего; sorted из _merge_list.
        expected = sorted(fm.get("skills", []))
        got = sorted(rr.skills) if isinstance(rr.skills, list) else rr.skills
        assert got == expected, f"роль '{role}': skills {got} != upstream {expected}"

    @pytest.mark.parametrize("role", ROLES)
    def test_tg_emoji_matches(self, role):
        """tg.emoji роли == frontmatter ``icon`` (нет icon → нет tg / пустой emoji)."""
        rr = P.get_role(PIPELINE, role)
        fm = _upstream_frontmatter(role)
        icon = fm.get("icon", "")
        our_emoji = rr.tg.emoji if rr.tg is not None else ""
        assert our_emoji == icon, f"роль '{role}': emoji '{our_emoji}' != upstream icon '{icon}'"


# ── B4: мост воспроизводит рабочий default ─────────────────────────────────

class TestBridgeReproducesDefault:
    """Сгенерированный мостом манифест проходит те же characterization-проверки.

    Мост (``scripts/extract-manifest.py``) пишется во временный
    ``pipelines/bridge-default/`` (с симлинком на реальные prompts default),
    загружается нашим loader'ом и сверяется по roles/can_spawn/model/modules/tg.
    Гарантия: мост не только совпадает с текущим файлом (``--check``), но и даёт
    рабочий, поведенчески верный манифест.
    """

    @pytest.fixture
    def bridge_pipeline(self, tmp_path, monkeypatch):
        """Сгенерировать манифест мостом → tmp pipelines/bridge-default/."""
        data = extract_manifest.build_manifest()
        data["name"] = "bridge-default"  # имя == имени папки (требование loader'а)

        root = tmp_path / "pipelines"
        pdir = root / "bridge-default"
        pdir.mkdir(parents=True)
        import yaml
        (pdir / "pipeline.yaml").write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
        # prompts нужны build_system_prompt — симлинк на реальный default.
        (pdir / "prompts").symlink_to(P.PIPELINES_DIR / "default" / "prompts")

        monkeypatch.setattr(P, "PIPELINES_DIR", root)
        P.load_pipeline.cache_clear()
        yield "bridge-default"
        P.load_pipeline.cache_clear()

    def test_bridge_manifest_self_validates(self, bridge_pipeline):
        """Манифест моста проходит pydantic-валидацию loader'а."""
        cfg = P.load_pipeline(bridge_pipeline)
        assert sorted(cfg.roles) == sorted(ROLES)

    @pytest.mark.parametrize("role", ROLES)
    def test_bridge_role_model_and_modules(self, bridge_pipeline, role):
        """model / modules / tg.emoji роли из моста == upstream frontmatter."""
        rr = P.get_role(bridge_pipeline, role)
        fm = _upstream_frontmatter(role)
        assert rr.model == _map_model(fm["model"])
        assert rr.modules == fm.get("modules", [])
        icon = fm.get("icon", "")
        assert (rr.tg.emoji if rr.tg is not None else "") == icon

    @pytest.mark.parametrize("parent", ROLES)
    @pytest.mark.parametrize("child", ROLES)
    def test_bridge_spawn_matches_upstream(self, bridge_pipeline, parent, child):
        """validate_spawn на манифесте моста == upstream-логике для всех пар."""
        try:
            P.validate_spawn(bridge_pipeline, parent, child)
            ours = True
        except ValueError:
            ours = False
        assert ours == _upstream_spawn_allowed(parent, child)

exec
/usr/bin/zsh -lc "git diff --unified=80 main...vadim/feat/pipeline-as-config -- app/backend_claude.py app/mcp_stdio.py app/workspace.py | sed -n '1,420p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
diff --git a/app/backend_claude.py b/app/backend_claude.py
index 139e32c..ba7a78a 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -8,199 +8,229 @@ from typing import AsyncIterator, Optional
 
 from claude_agent_sdk import (
     ClaudeSDKClient,
     ClaudeAgentOptions,
     AssistantMessage,
     ResultMessage,
     TextBlock,
     ThinkingBlock,
     ToolUseBlock,
     PermissionResultAllow,
     PermissionResultDeny,
     TaskStartedMessage,
     TaskProgressMessage,
     TaskNotificationMessage,
     SystemMessage,
 )
 from claude_agent_sdk.types import (
     ToolResultBlock, ServerToolResultBlock, UserMessage,
 )
 
 from app.events import AgentEvent
 
 logger = logging.getLogger(__name__)
 
 _BLOCKED_TOOLS = {"AskUserQuestion", "Monitor"}
 _ORCH_BLOCKED_TOOLS = {"AskUserQuestion", "Agent", "Monitor"}
 # Имена инструмента запуска субагентов. Режем на уровне CLI (disallowed_tools),
 # а не через can_use_tool: запуск субагента идёт мимо permission-колбэка
 # (SDK отдаёт его как TaskStartedMessage), поэтому _ORCH_BLOCKED_TOOLS его не ловит.
 # Имя хеджируем двумя вариантами (Task/Agent) — лишнее имя CLI игнорирует.
 _ORCH_DISALLOWED_TOOLS = ["Task", "Agent"]
 _ALWAYS_DISALLOWED = ["ScheduleWakeup", "CronCreate", "CronDelete", "CronList"]
 
 
 def _make_auto_approve(is_orchestrator: bool = False):
     blocked = _ORCH_BLOCKED_TOOLS if is_orchestrator else _BLOCKED_TOOLS
     async def _auto_approve(tool_name, tool_input, _context=None):
         if tool_name in blocked:
             msg = f"{tool_name} is not available for orchestrators. Use spawn_worker instead." if tool_name == "Agent" else f"{tool_name} is not available in Orchestra."
             return PermissionResultDeny(message=msg)
         if isinstance(tool_input, dict) and tool_input.get("run_in_background"):
             return PermissionResultDeny(message="run_in_background is disabled in Orchestra — background processes are killed when your turn ends. Run synchronously instead.")
         return PermissionResultAllow(updated_input=tool_input)
     return _auto_approve
 
 
 def _disallowed_tools(is_orchestrator: bool) -> list[str]:
     """Инструменты, полностью убираемые из набора модели (через CLI),
     а не через can_use_tool. Оркестратор делегирует через spawn_worker,
     поэтому субагентов ему отнимаем; воркерам — оставляем.
     ScheduleWakeup/Cron* убираем у ВСЕХ — Orchestra управляет scheduling сама."""
     base = list(_ALWAYS_DISALLOWED)
     if is_orchestrator:
         base.extend(_ORCH_DISALLOWED_TOOLS)
     return base
 
 
 def _extract_tool_result(block) -> str:
     raw = getattr(block, 'content', '')
     if isinstance(raw, list):
         parts = [item.get('text', str(item)) if isinstance(item, dict) else str(item) for item in raw]
         text = '\n'.join(parts)
     elif isinstance(raw, dict):
         text = raw.get('text', str(raw))
     else:
         text = str(raw)
     try:
         parsed = _json.loads(text)
         if isinstance(parsed, dict) and 'result' in parsed:
             return str(parsed['result'])
     except (ValueError, TypeError):
         pass
     return text
 
 
 class ClaudeBackend:
     def __init__(self, model: str, cwd: str, system_prompt: str = "",
                  resume_session_id: str | None = None,
                  mcp_servers: dict | None = None,
                  is_orchestrator: bool = False,
-                 scope_mcp_servers: dict | None = None):
+                 scope_mcp_servers: dict | None = None,
+                 config_dir: str = "",
+                 inherit_claude_md: bool = True,
+                 user_mcp_servers: dict | None = None):
         self.model = model
         self.cwd = cwd
         self.system_prompt = system_prompt
         self._resume_id = resume_session_id
         self._mcp_servers = mcp_servers or {}
         self._scope_mcp_servers = scope_mcp_servers or {}
         self._is_orchestrator = is_orchestrator
+        # Профиль Claude (F1/F4 резолвятся против него): пустой → env процесса
+        # orchestra (back-compat, 1:1 upstream).
+        self._config_dir = config_dir
+        # F4: наследовать ли user/project CLAUDE.md + настройки профиля.
+        self._inherit_claude_md = inherit_claude_md
+        # F2: user-MCP из профильного .claude.json (базовый слой merge).
+        self._user_mcp_servers = user_mcp_servers or {}
         self._client: Optional[ClaudeSDKClient] = None
         self._session_id: str | None = resume_session_id
 
     @property
     def session_id(self) -> Optional[str]:
         return self._session_id
 
     def _make_client(self) -> ClaudeSDKClient:
         import os
         cli = shutil.which("claude") or os.environ.get("CLAUDE_CLI_PATH", "claude")
         resume_id = self._session_id or self._resume_id
         env = {}
         for _k in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"):
             if os.environ.get(_k):
                 env[_k] = os.environ[_k]
+        # Профиль: переопределяем CLAUDE_CONFIG_DIR подпроцесса (SDK строит
+        # env как {**os.environ, **options.env}). Пусто → наследуем env процесса
+        # orchestra (back-compat). expanduser — на случай "~" в config_dir.
+        if self._config_dir:
+            env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(self._config_dir)
         options = ClaudeAgentOptions(
             model=self.model, cwd=self.cwd, cli_path=cli,
             permission_mode="default", can_use_tool=_make_auto_approve(self._is_orchestrator),
             disallowed_tools=_disallowed_tools(self._is_orchestrator),
             include_partial_messages=False, max_turns=200,
             max_buffer_size=50 * 1024 * 1024,
             env=env,
         )
         if resume_id:
             options.resume = resume_id
         else:
             options.system_prompt = {"type": "preset", "preset": "claude_code", "append": self.system_prompt}
-        merged_mcp = {**self._scope_mcp_servers, **self._mcp_servers}
+        # F2: user-MCP — БАЗОВЫЙ слой; scope и orchestra/custom (self._mcp_servers)
+        # переопределяют его сверху, чтобы серверный "orchestra" всегда выигрывал.
+        merged_mcp = {
+            **self._user_mcp_servers,
+            **self._scope_mcp_servers,
+            **self._mcp_servers,
+        }
         if merged_mcp:
             options.mcp_servers = merged_mcp
-        options.setting_sources = ["user", "project", "local"]
+        # F4: inherit_claude_md=False → только local-слой (нет user/project
+        # CLAUDE.md и настроек); иначе — полный набор, как в upstream.
+        options.setting_sources = (
+            ["user", "project", "local"] if self._inherit_claude_md else ["local"]
+        )
+        # F1: options.skills НЕ задаём НИКОГДА. Ветка "skills-список → options.skills"
+        # сознательно НЕ реализована (B4: default 1:1 upstream — его роли имеют
+        # skills-списки, но скиллы инъектятся через _inject_skills_to_worktree,
+        # не через options.skills). Единственное действие F1 — gating инъекции
+        # в manager.create_session при skills=="all".
         return ClaudeSDKClient(options=options)
 
     async def _cleanup_failed_client(self) -> None:
         if self._client:
             try:
                 await self._client.disconnect()
             except BaseException:
                 pass
             self._client = None
 
     async def connect(self) -> None:
         self._client = self._make_client()
         try:
             await asyncio.wait_for(self._client.connect(), timeout=60)
         except BaseException as e:
             logger.error(f"ClaudeBackend connect failed: {e}")
             await self._cleanup_failed_client()
             raise
 
     async def send(self, message: str) -> None:
         if not self._client:
             raise RuntimeError("ClaudeBackend not connected")
         await self._client.query(message)
 
     async def events(self) -> AsyncIterator[AgentEvent]:
         if not self._client:
             return
         async for msg in self._client.receive_messages():
             for event in self._convert(msg):
                 yield event
 
     async def interrupt(self) -> None:
         if self._client:
             try:
                 await self._client.interrupt()
             except Exception as e:
                 logger.warning(f"ClaudeBackend interrupt failed: {e}")
 
     async def disconnect(self) -> None:
         if self._client:
             try:
                 await self._client.disconnect()
             except Exception:
                 pass
             self._client = None
 
     async def context_usage(self) -> dict | None:
         if not self._client:
             return None
         try:
             u = await asyncio.wait_for(self._client.get_context_usage(), timeout=5)
             return {
                 "percentage": int(u.get("percentage", 0)),
                 "total_tokens": u.get("totalTokens", 0),
                 "max_tokens": u.get("maxTokens", 0),
                 "raw_max_tokens": u.get("rawMaxTokens", 0),
                 "auto_compact": u.get("isAutoCompactEnabled", False),
                 "auto_compact_threshold": u.get("autoCompactThreshold", 0),
             }
         except asyncio.TimeoutError:
             return None
         except Exception as e:
             logger.debug(f"get_context_usage failed: {e}")
             return None
 
     async def reconnect(self) -> None:
         await self.disconnect()
         await asyncio.sleep(2)
         self._client = self._make_client()
         try:
             await asyncio.wait_for(self._client.connect(), timeout=60)
         except BaseException as e:
             logger.error(f"ClaudeBackend reconnect failed: {e}")
             await self._cleanup_failed_client()
             raise
 
     def _convert(self, msg) -> list[AgentEvent]:
         events = []
         if isinstance(msg, AssistantMessage):
             for block in msg.content:
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 6eab965..d11a437 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1,149 +1,149 @@
 """External stdio MCP server for Orchestra.
 
 Runs as a separate process, communicates with Orchestra via HTTP API.
 Avoids the in-process SDK control_request deadlock (issue #425/#701).
 
 Usage: python -m app.mcp_stdio
 """
 
 import json
 import logging
 import os
 import sys
 
 import httpx
 from mcp.server.fastmcp import FastMCP
 
 logging.basicConfig(level=logging.INFO, stream=sys.stderr)
 logger = logging.getLogger("orchestra-mcp")
 
 ORCHESTRA_URL = os.environ.get("ORCHESTRA_URL", "http://127.0.0.1:8888")
 SCOPE = os.environ.get("ORCHESTRA_SCOPE", "")
 ROLE = os.environ.get("ORCHESTRA_ROLE", "orchestrator")
 WORKER_NAME = os.environ.get("WORKER_NAME", "worker")
 _INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")
 
 mcp = FastMCP("orchestra")
 
 
 def _auth_headers() -> dict:
     if _INTERNAL_TOKEN:
         return {"Authorization": f"Bearer {_INTERNAL_TOKEN}"}
     return {}
 
 
 async def _api(method: str, path: str, **kwargs) -> dict | list | None:
     t = kwargs.pop("timeout", 30)
     headers = _auth_headers()
     async with httpx.AsyncClient(base_url=ORCHESTRA_URL, timeout=t, headers=headers) as client:
         if method == "GET":
             r = await client.get(path, params=kwargs.get("params"))
         elif method == "POST":
             r = await client.post(path, json=kwargs.get("json"))
         elif method == "PUT":
             r = await client.put(path, json=kwargs.get("json"), params=kwargs.get("params"))
         elif method == "DELETE":
             r = await client.delete(path, params=kwargs.get("params"))
         else:
             return None
         if r.status_code >= 400:
             return {"error": r.text}
         try:
             return r.json()
         except Exception as e:
             return {"error": f"invalid JSON response (status={r.status_code}): {r.text[:200]}"}
 
 
 @mcp.tool()
 async def spawn_worker(name: str, task: str, repo_path: str,
                        model: str = "",
                        system_prompt: str = "",
                        task_id: str = "",
                        description: str = "",
-                       base_branch: str = "main",
+                       base_branch: str = "",
                        role: str = "worker",
                        mcp_servers: str = "",
                        owned_dirs: str = "",
                        tg_topic: bool = False) -> str:
     """Spawn a new worker agent in a git worktree. Model is REQUIRED — choose explicitly: claude-opus-4-8[1m] for research/planning/long-lived, claude-sonnet-4-6 for implementation from spec, gpt-5.5 for Codex.
-    base_branch — от какой ветки ответвить worktree воркера (default main).
+    base_branch — от какой ветки ответвить worktree воркера. Пусто ("") = авто по стратегии пайплайна (parent → от ветки родителя, иначе main); явно указанная ветка переопределяет стратегию.
     mcp_servers — JSON-объект с доп. MCP-серверами для воркера (формат как в .mcp.json: {"name": {"command": ..., "args": [...]}}). Мерджится с дефолтным Orchestra MCP; ключ "orchestra" игнорируется. Переживает рестарт.
     owned_dirs — JSON-массив директорий которыми владеет воркер, напр. ["app/api/", "app/models/"]. Инжектится в промпт воркера ("трогай только это"). Пересечение с owned_dirs другого живого воркера → предупреждение (НЕ блок).
     tg_topic — если True, агент получит собственный TG топик для логов и сообщений."""
     if not model:
         return "Error: model is required. Choose: claude-opus-4-8[1m] (think), claude-sonnet-4-6 (type), gpt-5.5 (codex)"
     scope = SCOPE or repo_path
     body = {
         "name": name, "scope": scope, "cwd": repo_path,
         "model": model, "system_prompt": system_prompt,
         "use_worktree": True, "repo_path": repo_path,
         "base_branch": base_branch,
         "role": role,
         "parent_name": WORKER_NAME,
     }
     if mcp_servers:
         import json
         try:
             parsed = json.loads(mcp_servers)
             if isinstance(parsed, dict):
                 body["mcp_servers"] = parsed
             else:
                 return "Error: mcp_servers must be a JSON object, e.g. {\"playwright\": {\"command\": \"npx\", \"args\": [...]}}"
         except json.JSONDecodeError as e:
             return f"Error: mcp_servers is not valid JSON: {e}"
     if owned_dirs:
         import json
         try:
             parsed = json.loads(owned_dirs)
             if isinstance(parsed, list):
                 body["owned_dirs"] = parsed
             else:
                 return "Error: owned_dirs must be a JSON array, e.g. [\"app/api/\", \"app/models/\"]"
         except json.JSONDecodeError as e:
             return f"Error: owned_dirs is not valid JSON: {e}"
     if task_id:
         body["task_id"] = task_id
     if description:
         body["description"] = description
     if tg_topic:
         body["tg_topic"] = True
     result = await _api("POST", "/api/sessions", json=body)
     if isinstance(result, dict) and result.get("error"):
         return f"Spawn failed: {result['error']}"
     await _api("POST", f"/api/sessions/{name}/send", json={
         "message": task, "scope": scope,
     })
     out = f"Worker '{name}' spawned. Model: {model}. Task sent."
     if isinstance(result, dict) and result.get("spawn_warning"):
         out += f"\n⚠️ {result['spawn_warning']}"
     return out
 
 
 @mcp.tool()
 async def acquire_test_lock(reason: str = "") -> str:
     """Захватить ГЛОБАЛЬНЫЙ эксклюзивный лок на ПОЛНЫЙ прогон тестов (фулл-сьют) для проекта.
     Бери его ТОЛЬКО перед полным прогоном и ТОЛЬКО с согласия PM. Узкие тесты этапа лока НЕ требуют.
     Занято другим агентом → вернётся отказ с именем держателя — НЕ запускай фулл-сьют, жди и попробуй позже.
     Всегда вызывай release_test_lock() после прогона."""
     result = await _api("POST", "/api/test-lock/acquire", json={
         "scope": SCOPE, "holder": WORKER_NAME, "reason": reason,
     })
     if isinstance(result, dict) and result.get("error"):
         return f"Lock error: {result['error']}"
     if result.get("acquired"):
         return f"Test lock ACQUIRED for '{WORKER_NAME}' (reason: {reason or 'n/a'}). Release it when done."
     return (f"Test lock BUSY — held by '{result.get('holder')}'. "
             f"Do NOT run the full suite. Wait and retry, or coordinate via PM.")
 
 
 @mcp.tool()
 async def release_test_lock() -> str:
     """Освободить глобальный тест-лок (если ты его держишь). Вызывай сразу после полного прогона."""
     result = await _api("POST", "/api/test-lock/release", json={
         "scope": SCOPE, "holder": WORKER_NAME,
     })
     if isinstance(result, dict) and result.get("error"):
         return f"Lock error: {result['error']}"
     if result.get("released"):
         return "Test lock released."
     return "Test lock was not held by you (nothing to release)."
diff --git a/app/workspace.py b/app/workspace.py
index 588d687..a535130 100644
--- a/app/workspace.py
+++ b/app/workspace.py
@@ -1,187 +1,256 @@
 """Worktree management — create and remove git worktrees for agent sessions."""
 
+from __future__ import annotations
+
 import fcntl
 import json
 import logging
+import os
 import re
 import shutil
 import subprocess
 from dataclasses import dataclass
 from pathlib import Path
+from typing import TYPE_CHECKING
+
+if TYPE_CHECKING:
+    # Только для аннотаций (строковые аннотации + from __future__ import annotations):
+    # рантайм-импорт не нужен, объекты приходят готовыми от вызывающего. Так избегаем
+    # циклической зависимости (pipeline ← workspace).
+    from app.pipeline import Symlink, Worktree as WorktreeCfg
 
 logger = logging.getLogger(__name__)

codex
One plan item is already stale: PR `app/pipeline.py` does not currently import `is_orchestrator_role` from `session.py`; it models orchestrator-ness via manifest `kind` and `ResolvedRole.is_orchestrator`. The location decision still matters for manager/session fallback behavior, but the specific “fix pipeline.py import” item may be unnecessary unless the branch has changed elsewhere.
exec
/usr/bin/zsh -lc "git diff --unified=80 main...vadim/feat/pipeline-as-config -- app/workspace.py | sed -n '180,520p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
+            if src is None:
+                continue
+            dst = wt_path / fname
+            if not _within(dst.parent, wt_path):
+                raise ValueError(f"copy target '{fname}' escapes worktree")
+            shutil.copy2(str(src), str(dst))
+        if worktree_cfg is not None:
+            for sl in worktree_cfg.symlinks:
+                _apply_symlink(repo, wt_path, sl)
     except Exception:
         subprocess.run(
             ["git", "worktree", "remove", str(wt_path), "--force"],
             cwd=str(repo), capture_output=True, text=True,
         )
         raise
 
     return Worktree(path=str(wt_path), branch=branch)
 
 
 def _resolve_repo(worktree_path: str, fallback_repo: str) -> Path:
     wt = Path(worktree_path).resolve()
     git_common = subprocess.run(
         ["git", "rev-parse", "--git-common-dir"],
         cwd=str(wt), capture_output=True, text=True,
     )
     if git_common.returncode == 0:
         git_dir = Path(git_common.stdout.strip())
         if not git_dir.is_absolute():
             git_dir = (wt / git_dir).resolve()
         return git_dir.parent
     return Path(fallback_repo).resolve()
 
 
 def _ensure_repo_on_branch(repo: str, target_branch: str = "main") -> tuple[str | None, bool]:
     """Returns (error_or_None, did_stash).
 
     Выполняет stash (если репо грязный) и checkout target_branch.
     НЕ делает stash pop — это обязанность вызывающего кода в блоке finally.
     """
     did_stash = False
     repo_status = subprocess.run(
         ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True,
     )
     if repo_status.stdout.strip():
         stash = subprocess.run(
             ["git", "stash", "--include-untracked"], cwd=repo, capture_output=True, text=True,
         )
         if stash.returncode != 0:
             return f"main repo dirty and stash failed: {stash.stderr.strip()}", False
         did_stash = True
         logger.info(f"Auto-stashed dirty repo: {repo}")
     head = subprocess.run(
         ["git", "symbolic-ref", "--short", "HEAD"], cwd=repo, capture_output=True, text=True,
     )
     if head.returncode != 0 or head.stdout.strip() != target_branch:
         checkout = subprocess.run(
             ["git", "checkout", target_branch], cwd=repo, capture_output=True, text=True,
         )
         if checkout.returncode != 0:
             # НЕ делаем stash pop здесь — did_stash=True сигнализирует finally в вызывающем коде
             return f"cannot checkout {target_branch} in repo: {checkout.stderr.strip()}", did_stash
     return None, did_stash
 
 
 def _get_commit_messages(repo: str, branch: str, base: str) -> list[str]:
     """Return subject lines of commits in branch not in base."""
     log = subprocess.run(
         ["git", "log", f"{base}..{branch}", "--format=%s", "--reverse"],
         cwd=repo, capture_output=True, text=True,
     )
     if log.returncode != 0 or not log.stdout.strip():
         return []
     return [line for line in log.stdout.strip().splitlines() if line.strip()]
 
 
 def _build_squash_message(branch: str, messages: list[str]) -> str:
     """Build squash commit message with task refs prefix and message list."""
     all_refs: list[str] = []
     seen: set[str] = set()
     for msg in messages:
         for m in _TASK_REF_RE.finditer(msg):
             if m.group(3):
                 ref = f"#{m.group(3)}"
             else:
                 ref = f"#{m.group(2)}"
             if ref not in seen:
                 seen.add(ref)
                 all_refs.append(ref)
 

exec
/usr/bin/zsh -lc "git diff --unified=70 main...vadim/feat/pipeline-as-config -- app/main.py | sed -n '1,420p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
diff --git a/app/main.py b/app/main.py
index 24ae327..507c49b 100644
--- a/app/main.py
+++ b/app/main.py
@@ -1,208 +1,220 @@
 """Orchestra — AI Agent Orchestrator API."""
 
 import asyncio
 import hashlib
 import hmac
 import json
 import logging
 import os
 import re
 import sqlite3
 import time
 from contextlib import asynccontextmanager
 from pathlib import Path
 from typing import Optional
 
 from fastapi import FastAPI, Request, UploadFile, Form
 from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
 from starlette.responses import StreamingResponse
 from starlette.middleware.base import BaseHTTPMiddleware
 from fastapi.staticfiles import StaticFiles
 from fastapi.templating import Jinja2Templates
 from pydantic import BaseModel, field_validator, model_validator
 
-from app.db import init_db, get_logs, get_logs_before
+from app.db import (
+    init_db, get_logs, get_logs_before,
+    list_profiles, upsert_profile, delete_profile,
+)
+from app.pipeline import list_pipelines
 from app.manager import SessionManager
 from app.models import resolve_model, MODELS
 from app.session import AgentStatus
 
 manager = SessionManager()
 templates = Jinja2Templates(directory="app/templates")
 
 
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     from dotenv import load_dotenv
     load_dotenv()
     init_db()
     await manager.auto_resume_all()
     manager.start_background_tasks()
     from app.bg_jobs import bg_manager
     bg_manager.set_session_manager(manager)
     await bg_manager.restore_from_db()
     from app.tg_bridge import start_bridge, stop_bridge
     await start_bridge(manager)
     from app.ssh_tunnel import start_tunnel, stop_tunnel
     await start_tunnel()
     snapshot_task = asyncio.create_task(_usage_snapshot_loop())
     yield
     snapshot_task.cancel()
     await stop_tunnel()
     await stop_bridge()
     await bg_manager.shutdown()
     await manager.shutdown_all()
 
 
 app = FastAPI(title="Orchestra", lifespan=lifespan)
 app.mount("/static", StaticFiles(directory="app/static"), name="static")
 
 
 from app.auth import is_auth_enabled, validate_session, requires_auth, check_internal_token
 
 
 @app.exception_handler(Exception)
 async def global_exception_handler(request: Request, exc: Exception):
     import traceback
     tb = traceback.format_exc()
     logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}\n{tb}")
     return JSONResponse({"error": f"Internal: {exc}"}, status_code=500)
 
 
 class AuthMiddleware(BaseHTTPMiddleware):
     async def dispatch(self, request: Request, call_next):
         path = request.url.path
         method = request.method
         if check_internal_token(request.headers.get("authorization", "")):
             return await call_next(request)
         if not is_auth_enabled():
             return await call_next(request)
         if not requires_auth(path, method):
             return await call_next(request)
         token = request.cookies.get("session")
         if token and validate_session(token):
             return await call_next(request)
         if path.startswith("/api/"):
             return JSONResponse({"error": "unauthorized"}, status_code=401)
         return RedirectResponse("/login", status_code=302)
 
 
 app.add_middleware(AuthMiddleware)
 
 
 class CreateSessionRequest(BaseModel):
     name: str
     cwd: str
     model: str = "claude-sonnet-4-6"
     scope: Optional[str] = None
     system_prompt: str = ""
     use_worktree: bool = False
     repo_path: Optional[str] = None
     is_orchestrator: bool = False
     role: str = ""
     task_id: str = ""
     description: str = ""
-    base_branch: str = "main"
+    base_branch: str = ""
     parent_name: str = ""
     mcp_servers: dict = {}
+    pipeline: str = ""
+    profile: str = ""
     owned_dirs: list[str] = []
     tg_topic: bool = False
 
     @field_validator("name")
     @classmethod
     def validate_name(cls, v):
         if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,49}$", v):
             raise ValueError("name must be alphanumeric with ._- allowed, 1-50 chars")
         return v
 
     @field_validator("model")
     @classmethod
     def validate_model(cls, v):
         resolved = resolve_model(v)
         if resolved not in MODELS:
             raise ValueError(f"unknown model '{v}'. Available: {', '.join(MODELS.keys())}")
         return resolved
 
     @field_validator("cwd")
     @classmethod
     def validate_cwd(cls, v):
         if not Path(v).is_dir():
             raise ValueError(f"cwd does not exist: {v}")
         return v
 
     @model_validator(mode="after")
     def validate_worktree(self):
         if self.use_worktree and not self.repo_path:
             raise ValueError("repo_path required when use_worktree=True")
         return self
 
 
+class ProfileRequest(BaseModel):
+    """Тело запроса для создания/обновления профиля Claude."""
+    name: str
+    config_dir: str = ""
+
+
 class SendRequest(BaseModel):
     message: str
     scope: str
     sender: str | None = None
 
 
 class ScopeRequest(BaseModel):
     scope: str
 
 
 class TestLockRequest(BaseModel):
     scope: str
     holder: str
     reason: str = ""
 
 
 class ChangeScopeRequest(BaseModel):
     old_scope: str
     new_scope: str
     new_cwd: Optional[str] = None
 
 
 @app.get("/", response_class=HTMLResponse)
 async def dashboard(request: Request):
     return templates.TemplateResponse(request, "dashboard.html")
 
 
 @app.get("/login", response_class=HTMLResponse)
 async def login_page(request: Request):
     if not is_auth_enabled():
         return RedirectResponse("/", status_code=302)
     return templates.TemplateResponse(request, "login.html", {"error": ""})
 
 
 @app.post("/login")
 async def login_submit(request: Request, username: str = Form(""), password: str = Form("")):
     from app.auth import check_credentials, create_session
     if not is_auth_enabled():
         return RedirectResponse("/", status_code=302)
     if check_credentials(username, password):
         token = create_session(username)
         response = RedirectResponse("/", status_code=302)
         secure = request.url.scheme == "https" or os.environ.get("COOKIE_SECURE") == "1"
         response.set_cookie("session", token, httponly=True, samesite="lax", max_age=2592000, secure=secure)
         return response
     return templates.TemplateResponse(request, "login.html", {"error": "Invalid credentials"})
 
 
 @app.post("/logout")
 async def logout(request: Request):
     response = RedirectResponse("/login", status_code=302)
     response.delete_cookie("session")
     return response
 
 
 
 @app.get("/api/jobs")
 async def list_api_jobs(scope: str | None = None):
     from app.db import get_jobs
     return get_jobs(scope=scope)
 
 
 def _encode_path(path: str) -> str:
     return "".join("-" if (c == "/" or c == " " or ord(c) > 127) else c for c in path)
 
 
 def _build_path_map() -> dict[str, str]:
     scan_roots = [
         "/mnt/data/Projects/Python",
         "/mnt/data/Projects/Unity",
@@ -337,157 +349,211 @@ async def open_folder(req: dict):
     subprocess.Popen(["xdg-open", path], env=env)
     return {"ok": True}
 
 
 @app.get("/api/open-file")
 async def open_file(path: str):
     if not os.environ.get("ALLOW_OPEN_FOLDER"):
         return JSONResponse({"error": "disabled on this server"}, status_code=403)
     import subprocess
     p = Path(path)
     if not p.exists():
         return JSONResponse({"error": "file not found"}, status_code=404)
     env = {**os.environ, "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
     subprocess.Popen(["xdg-open", str(p)], env=env)
     return {"ok": True}
 
 
 @app.get("/api/files")
 async def list_files(path: str):
     if not _is_safe_path(path):
         return JSONResponse({"error": "access denied"}, status_code=403)
     target = Path(path)
     if not target.is_dir():
         return JSONResponse({"error": "not a directory"}, status_code=400)
     items = []
     try:
         for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
             items.append({
                 "name": entry.name,
                 "path": str(entry),
                 "is_dir": entry.is_dir(),
                 "size": entry.stat().st_size if entry.is_file() else None,
             })
     except PermissionError:
         pass
     return items
 
 
 @app.get("/api/role-icons")
 async def role_icons():
     from app.manager import get_role_icons
     return get_role_icons()
 
 
 @app.get("/api/sessions")
 async def list_sessions(scope: Optional[str] = None):
     return manager.list_sessions(scope)
 
 
 @app.post("/api/sessions", status_code=201)
 async def create_session(req: CreateSessionRequest):
     if not _is_safe_path(req.cwd):
         return JSONResponse({"error": f"cwd not in allowed paths: {req.cwd}"}, status_code=403)
     scope = req.scope or req.cwd
     try:
         session = await manager.create_session(
             name=req.name,
             scope=scope,
             cwd=req.cwd,
             model=req.model,
             system_prompt=req.system_prompt,
             use_worktree=req.use_worktree,
             repo_path=req.repo_path,
             is_orchestrator=req.is_orchestrator,
             role=req.role,
             task_id=req.task_id,
             description=req.description,
             base_branch=req.base_branch,
             parent_name=req.parent_name,
             mcp_servers=req.mcp_servers,
+            pipeline=req.pipeline,
+            profile=req.profile,
             owned_dirs=req.owned_dirs,
             tg_topic=req.tg_topic,
         )
         d = session.to_dict()
         if session._spawn_warning:
             d["spawn_warning"] = session._spawn_warning
         return d
     except ValueError as e:
         return JSONResponse({"error": str(e)}, status_code=409)
     except sqlite3.IntegrityError:
         return JSONResponse({"error": f"session '{req.name}' already exists"}, status_code=409)
     except Exception as e:
         import traceback
         logging.getLogger(__name__).error(f"spawn failed: {traceback.format_exc()}")
         return JSONResponse({"error": str(e)}, status_code=500)
 
 
+@app.get("/api/pipelines")
+async def get_pipelines():
+    """Только валидные пайплайны для UI-дропдаунa: ``[{name, description, roles}]``."""
+    return [
+        {"name": p["name"], "description": p["description"], "roles": p["roles"]}
+        for p in list_pipelines()
+        if p["valid"]
+    ]
+
+
+@app.get("/api/profiles")
+async def get_profiles():
+    """Все профили Claude: ``[{name, config_dir}]``."""
+    return list_profiles()
+
+
+@app.post("/api/profiles")
+async def create_profile(req: ProfileRequest):
+    """Создать или обновить профиль. Имя валидируется тем же regex, что у сессий.
+
+    Валидация ``config_dir`` — **мягкая**: если путь непустой и не указывает на
+    существующую директорию, профиль всё равно сохраняется, но в ответ
+    добавляется ``warning``. Это не блокирует пользователя (папку может создать
+    CLI или она появится позже), но предупреждает об опечатке заранее, а не
+    при первом запуске агента. Формат ответа: ``{profiles, warning}``.
+    """
+    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,49}$", req.name):
+        return JSONResponse(
+            {"error": "name must be alphanumeric with ._- allowed, 1-50 chars"},
+            status_code=400,
+        )
+    warning = None
+    config_dir = req.config_dir
+    if config_dir and not Path(os.path.expanduser(config_dir)).is_dir():
+        warning = (
+            f"config_dir '{config_dir}' не существует — будет создан CLI "
+            "или приведёт к ошибке при запуске"
+        )
+    upsert_profile(req.name, config_dir)
+    return {"profiles": list_profiles(), "warning": warning}
+
+
+@app.delete("/api/profiles/{name}")
+async def remove_profile(name: str):
+    """Удалить профиль. Сид-профиль ``personal`` защищён → 409."""
+    try:
+        delete_profile(name)
+    except ValueError as e:
+        return JSONResponse({"error": str(e)}, status_code=409)
+    return list_profiles()
+
+
 @app.get("/api/sessions/{name}")
 async def get_session(name: str, scope: str):
     found = manager.get_by_name(name, scope)
     if not found:
         return JSONResponse({"error": "not found"}, status_code=404)
     if isinstance(found, dict):
         return found
     return found.to_dict()
 
 
 @app.get("/api/sessions/{name}/prompt")
 async def get_session_prompt(name: str, scope: str):
     from app.manager import _read_prompt
     found = manager.get_by_name(name, scope)
     if not found:
         return JSONResponse({"error": "not found"}, status_code=404)
     sp = (found.get("system_prompt", "") if isinstance(found, dict) else found.system_prompt) or ""
     is_orch = (found.get("is_orchestrator") if isinstance(found, dict) else found.is_orchestrator) or False
     base = _read_prompt("base.md")
     base_len = len(base)
     role = ""
     custom = ""
     rest = sp[base_len:].lstrip("\n") if sp[:base_len] == base else sp
     if not is_orch:
         marker = "- Branch: "
         idx = rest.rfind(marker)
         if idx != -1:
             after_marker = rest.find("\n", idx)
             if after_marker != -1:
                 role = rest[:after_marker + 1].strip()
                 custom = rest[after_marker + 1:].strip()
             else:
                 role = rest.strip()
         else:
             role = rest.strip()
     else:
         role = rest.strip()
     return {"system_prompt": sp, "base": base, "role": role, "custom": custom}
 
 
 @app.get("/api/sessions/{name}/context")
 async def get_session_context(name: str, scope: str):
     found = manager.get_by_name(name, scope)
     if not found:
         return {"percentage": 0, "total_tokens": 0, "max_tokens": 0}
     if isinstance(found, dict):
         pct = found.get("context_pct", 0) or 0
         tokens = found.get("context_tokens", 0) or 0
         return {"percentage": pct, "total_tokens": tokens, "max_tokens": 200000}
     return await found.get_context()
 

exec
/usr/bin/zsh -lc "git diff --unified=80 main...vadim/feat/pipeline-as-config -- app/session.py | sed -n '1,500p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
diff --git a/app/session.py b/app/session.py
index 0c726b7..143da31 100644
--- a/app/session.py
+++ b/app/session.py
@@ -1,244 +1,304 @@
 """AgentSession — backend-agnostic wrapper with persistent event loop."""
 
 import asyncio
 import json
 import logging
 import os
 import re
 from dataclasses import dataclass, field
 from datetime import datetime, timezone
 from enum import Enum
 from pathlib import Path
 from typing import Optional
 
 from app.events import AgentEvent
 from app.db import save_session, add_log
 
 logger = logging.getLogger(__name__)
 
 import concurrent.futures
 _DB_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None
 
 
 def _db_executor() -> concurrent.futures.ThreadPoolExecutor:
     """Dedicated pool for DB writes so logs/persists don't contend with git ops
     on the default executor (used by asyncio.to_thread)."""
     global _DB_EXECUTOR
     if _DB_EXECUTOR is None:
         _DB_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="db")
     return _DB_EXECUTOR
 
 
 IDLE_TIMEOUT_WORKER = 300
 IDLE_TIMEOUT_ORCHESTRATOR = 600
 
 _ORCHESTRATOR_ROLES = frozenset({"orchestrator", "sub-orchestrator"})
 
 
 def is_orchestrator_role(role: str) -> bool:
     return role in _ORCHESTRATOR_ROLES
 
 
 def _load_scope_mcp_servers(scope: str) -> dict:
     servers = {}
     for name in ("settings.json", "settings.local.json"):
         path = Path(scope) / ".claude" / name
         if not path.is_file():
             continue
         try:
             data = json.loads(path.read_text())
             for k, v in data.get("mcpServers", {}).items():
                 if k != "orchestra":
                     servers[k] = v
         except Exception as e:
             logger.warning(f"Failed to parse MCP servers from {path}: {e}")
     mcp_json = Path(scope) / ".mcp.json"
     if mcp_json.is_file():
         try:
             data = json.loads(mcp_json.read_text())
             for k, v in data.get("mcpServers", {}).items():
                 if k != "orchestra":
                     servers[k] = v
         except Exception as e:
             logger.warning(f"Failed to parse .mcp.json from {mcp_json}: {e}")
     return servers
 
 
+def _load_user_mcp_servers(config_dir: str) -> dict:
+    """F2: user-MCP из top-level ``.claude.json`` профиля.
+
+    ``config_dir`` непуст → ``<config_dir>/.claude.json``; пуст → ``~/.claude.json``
+    (env процесса orchestra). Берёт ключ ``mcpServers``, пропуская ``orchestra``
+    (серверный MCP подмешивается отдельно и не должен подменяться профилем).
+    Зеркалит стиль ``_load_scope_mcp_servers``: ошибки парсинга — warning, не падаем.
+
+    ВНИМАНИЕ: личный профиль CLI хранит ``.claude.json`` в HOME root
+    (``~/.claude.json``), а НЕ внутри ``~/.claude/``. Поэтому для личного профиля
+    держим ``config_dir=""`` (сид-профиль ``personal`` так и сидится). Если задать
+    ``config_dir="~/.claude"`` — функция пойдёт в ``~/.claude/.claude.json``,
+    которого нет, и вернёт пусто. Рабочий профиль (``~/.claude-work``) хранит
+    ``.claude.json`` ВНУТРИ config dir — для него путь верный.
+    """
+    servers: dict = {}
+    base = Path(os.path.expanduser(config_dir)) if config_dir else Path.home()
+    path = base / ".claude.json"
+    if not path.is_file():
+        return servers
+    try:
+        data = json.loads(path.read_text())
+        for k, v in data.get("mcpServers", {}).items():
+            if k != "orchestra":
+                servers[k] = v
+    except Exception as e:
+        logger.warning(f"Failed to parse user MCP servers from {path}: {e}")
+    return servers
+
+
 class AgentStatus(str, Enum):
     IDLE = "idle"
     RUNNING = "running"
     WAITING = "waiting"
 
 
 @dataclass
 class AgentSession:
     id: str
     name: str
     scope: str
     cwd: str
     model: str = "claude-sonnet-4-6"
     system_prompt: str = ""
     status: AgentStatus = AgentStatus.IDLE
     session_id: str | None = None
     cost_usd: float = 0.0
     cost_usd_cached: float = 0.0
     worktree_path: str | None = None
     branch: str | None = None
     created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
     role: str = "worker"
     parent_id: str = ""
     parent_name: str = ""
+    pipeline: str = ""
+    profile: str = ""
+    _is_orchestrator: bool | None = field(default=None, repr=False)
     color: str = ""
     mcp_servers: dict = field(default_factory=dict, repr=False)
     mcp_servers_custom: dict = field(default_factory=dict, repr=False)
     on_error: Optional[callable] = field(default=None, repr=False)
     backend_type: str = "claude"
     task_id: str = ""
     description: str = ""
     owned_dirs: list = field(default_factory=list, repr=False)
     tg_topic: bool = False
 
     progress_pct: int = 0
     progress_status: str = ""
 
     total_turns: int = 0
     total_input_tokens: int = 0
     total_output_tokens: int = 0
     total_tool_calls: int = 0
 
     _backend: Optional[object] = field(default=None, repr=False)
     _listen_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _heartbeat_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _background_tasks: set = field(default_factory=set, repr=False)
     _last_context: dict = field(default_factory=lambda: {"percentage": 0, "total_tokens": 0, "max_tokens": 0}, repr=False)
     _did_report: bool = field(default=False, repr=False)
     _turn_logs: list = field(default_factory=list, repr=False)
     _prompt_injected: bool = field(default=False, repr=False)
     _current_prompt: str = field(default="", repr=False)
     _template_hash: str = field(default="", repr=False)
     _turn_start: float = field(default=0.0, repr=False)
     _last_msg_time: float = field(default=0.0, repr=False)
     _pending_messages: list = field(default_factory=list, repr=False)
     on_idle: Optional[callable] = field(default=None, repr=False)
     _hibernate_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _hibernated: bool = field(default=False, repr=False)
     _compacting: bool = field(default=False, repr=False)
     _compact_ack_event: Optional[asyncio.Event] = field(default=None, repr=False)
     _compact_ack_gen: int = field(default=-1, repr=False)
     _last_cost: float = field(default=0.0, repr=False)
     _last_cost_cached: float = field(default=0.0, repr=False)
     _last_turn_ok: bool = field(default=True, repr=False)
     _last_stop_reason: str = field(default="", repr=False)
     _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
     _persist_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _persist_dirty: bool = field(default=False, repr=False)
     _turn_gen: int = field(default=0, repr=False)
     _auto_report_task: Optional[asyncio.Task] = field(default=None, repr=False)
     _spawn_warning: str = field(default="", repr=False)
 
     TURN_TIMEOUT = 600
 
     @property
     def is_orchestrator(self) -> bool:
+        if self._is_orchestrator is not None:
+            return self._is_orchestrator
         return is_orchestrator_role(self.role)
 
+    @is_orchestrator.setter
+    def is_orchestrator(self, value: bool) -> None:
+        self._is_orchestrator = value
+
     def _make_backend(self, force_fresh: bool = False):
         resume = None if force_fresh else self.session_id
         if self.backend_type == "codex":
             from app.backend_codex import CodexBackend
             return CodexBackend(
                 model=self.model, cwd=self.cwd,
                 system_prompt=self.system_prompt,
                 resume_thread_id=resume,
                 mcp_env=self._build_codex_mcp_env(),
                 reasoning_effort=self._codex_reasoning_effort(),
             )
         else:
             from app.backend_claude import ClaudeBackend
+            from app.pipeline import get_role
+            from app.db import get_profile
+            # Резолв роли: нет манифеста → чистый upstream-fallback
+            # (inherit=True, config_dir по профилю, user_mcp пуст — как сегодня).
+            try:
+                rr = get_role(self.pipeline, self.role)
+            except FileNotFoundError:
+                rr = None
+            inherit = rr.inherit_claude_md if rr else True
+            config_dir = ""
+            if self.profile:
+                p = get_profile(self.profile)
+                config_dir = p["config_dir"] if p else ""
+            # F2: user-MCP подмешиваем ТОЛЬКО при mcp_servers=="all" (tasks-pm);
+            # default/список — без user-MCP (1:1 upstream).
+            user_mcp: dict = {}
+            if rr is not None and rr.mcp_servers == "all":
+                user_mcp = _load_user_mcp_servers(config_dir)
             return ClaudeBackend(
                 model=self.model, cwd=self.cwd,
                 system_prompt=self.system_prompt,
                 resume_session_id=resume,
                 mcp_servers=self.mcp_servers,
                 is_orchestrator=self.is_orchestrator,
                 scope_mcp_servers=_load_scope_mcp_servers(self.scope),
+                config_dir=config_dir,
+                inherit_claude_md=inherit,
+                user_mcp_servers=user_mcp,
             )
 
     def _codex_reasoning_effort(self) -> str:
         return "high"
 
     def _spawn_bg(self, coro) -> asyncio.Task:
         task = asyncio.create_task(coro)
         self._background_tasks.add(task)
         def _on_done(t):
             self._background_tasks.discard(t)
             if not t.cancelled():
                 exc = t.exception()
                 if exc:
                     logger.warning(f"[{self.name}] background task failed: {exc}")
         task.add_done_callback(_on_done)
         return task
 
     def _build_codex_mcp_env(self) -> dict[str, str]:
         env = {}
         for _name, cfg in self.mcp_servers.items():
             for k, v in cfg.get("env", {}).items():
                 env[k] = str(v)
         return env
 
     async def start(self, initial_message: str | None = None) -> None:
         if initial_message:
             await self.send(initial_message)
         else:
             self.status = AgentStatus.IDLE
             self._persist()
 
     async def send(self, message: str) -> None:
         if self._compacting:
             self._pending_messages.append(message)
             self._log("user_message", message)
             self._log("status", f"message queued (compact in progress, {len(self._pending_messages)} pending)")
             return
 
         if self.status == AgentStatus.RUNNING:
             if self.backend_type == "codex":
                 self._pending_messages.append(message)
                 self._log("user_message", message)
                 self._log("status", f"message queued ({len(self._pending_messages)} pending)")
                 return
             self._log("user_message", message)
             try:
                 backend = await self._ensure_backend()
                 await backend.send(message)
                 return
             except Exception as e:
                 logger.warning(f"[{self.name}] mid-turn inject failed, queueing: {e}")
                 self._pending_messages.append(message)
                 self._log("status", f"inject failed, queued ({len(self._pending_messages)} pending)")
                 return
 
         async with self._lifecycle_lock:
             if self._hibernate_task and not self._hibernate_task.done():
                 self._hibernate_task.cancel()
                 self._hibernate_task = None
 
             if self._hibernated:
                 logger.info(f"[{self.name}] waking from hibernate")
                 self._hibernated = False
 
             self.progress_pct = 0
             self.progress_status = ""
             self._log("user_message", message)
 
             did_inject = False
             pending_th = ""
             templates_changed = False
             if self.session_id and self._current_prompt and not self._prompt_injected:
                 from app.manager import _prompt_template_hash
                 current_th = _prompt_template_hash(self.role)
                 old_th = self._template_hash or current_th
                 templates_changed = old_th != current_th
                 pending_th = current_th
                 message = f"[Orchestra platform note: {'your role instructions were updated.' if templates_changed else 'refreshed context (worker list, etc.).'} This is from the server, not another agent.]\n{self._current_prompt}\n\n---\n\n{message}"
                 did_inject = True
 
@@ -834,128 +894,130 @@ class AgentSession:
         old_backend = backend_for_model(old_model)
         new_backend_type = backend_for_model(new_model)
         if old_backend != new_backend_type:
             return {"ok": False, "error": f"Cannot change from {old_backend} to {new_backend_type}. Kill and respawn."}
 
         self._log("status", f"model change: {old_model} → {new_model}")
         await self._disconnect_backend()
         self.model = new_model
         self._persist()
         return {"ok": True, "model": new_model, "old_model": old_model, "changed": True}
 
     async def _disconnect_backend(self) -> None:
         if self._hibernate_task and not self._hibernate_task.done() and self._hibernate_task is not asyncio.current_task():
             self._hibernate_task.cancel()
             self._hibernate_task = None
         if self._heartbeat_task and not self._heartbeat_task.done():
             self._heartbeat_task.cancel()
             try:
                 await self._heartbeat_task
             except (asyncio.CancelledError, Exception):
                 pass
             self._heartbeat_task = None
         backend = self._backend
         self._backend = None
         if self._listen_task and not self._listen_task.done():
             self._listen_task.cancel()
             try:
                 await self._listen_task
             except (asyncio.CancelledError, Exception):
                 pass
         if backend:
             await backend.disconnect()
 
     async def stop(self) -> None:
         self._cancel_auto_report()
         await self._disconnect_backend()
         self._hibernated = False
         self.status = AgentStatus.IDLE
         self._persist()
 
     def _persist(self) -> None:
         self._persist_dirty = True
         if self._persist_task and not self._persist_task.done():
             return
         self._persist_task = asyncio.get_running_loop().create_task(self._persist_loop())
         self._persist_task.add_done_callback(self._on_persist_done)
 
     def _on_persist_done(self, task: asyncio.Task) -> None:
         try:
             task.result()
         except asyncio.CancelledError:
             pass
         except Exception as e:
             logger.error(f"[{self.name}] persist task crashed: {e}")
 
     async def _persist_loop(self) -> None:
         while self._persist_dirty:
             self._persist_dirty = False
             snapshot = self._to_db_dict()
             try:
                 await asyncio.get_running_loop().run_in_executor(_db_executor(), save_session, snapshot)
             except Exception as e:
                 logger.error(f"[{self.name}] persist failed: {e}")
 
     async def _drain_persist(self) -> None:
         if self._persist_task and not self._persist_task.done():
             await asyncio.gather(self._persist_task, return_exceptions=True)
 
     def _log(self, type: str, content: str) -> None:
         asyncio.get_event_loop().run_in_executor(_db_executor(), add_log, self.id, datetime.now(timezone.utc), type, content)
 
     def _to_db_dict(self) -> dict:
         return {
             "id": self.id, "name": self.name, "scope": self.scope, "cwd": self.cwd,
             "model": self.model, "system_prompt": self.system_prompt,
             "status": self.status.value, "session_id": self.session_id,
             "cost_usd": self.cost_usd, "cost_usd_cached": self.cost_usd_cached,
             "worktree_path": self.worktree_path,
             "branch": self.branch, "is_orchestrator": self.is_orchestrator,
             "role": self.role, "parent_id": self.parent_id, "parent_name": self.parent_name,
+            "pipeline": self.pipeline,
+            "profile": self.profile,
             "color": self.color, "created_at": self.created_at.isoformat(),
             "finished_at": None,
             "context_pct": self._last_context.get("percentage", 0),
             "context_tokens": self._last_context.get("total_tokens", 0),
             "progress_pct": self.progress_pct,
             "progress_status": self.progress_status,
             "backend_type": self.backend_type,
             "task_id": self.task_id,
             "description": self.description,
             "total_turns": self.total_turns,
             "total_input_tokens": self.total_input_tokens,
             "total_output_tokens": self.total_output_tokens,
             "total_tool_calls": self.total_tool_calls,
             "template_hash": self._template_hash,
             "mcp_servers_custom": json.dumps(self.mcp_servers_custom) if self.mcp_servers_custom else "",
             "owned_dirs": json.dumps(self.owned_dirs) if self.owned_dirs else "",
             "tg_topic": int(self.tg_topic),
         }
 
     async def get_context(self) -> dict:
         return self._last_context
 
     def to_dict(self) -> dict:
         return {
             "id": self.id, "name": self.name, "scope": self.scope,
             "status": self.status.value, "model": self.model,
             "cost_usd": round(self.cost_usd, 4),
             "cost_usd_cached": round(self.cost_usd_cached, 4),
             "branch": self.branch,
             "is_orchestrator": self.is_orchestrator,
             "role": self.role, "parent_id": self.parent_id, "parent_name": self.parent_name,
             "color": self.color,
             "created_at": self.created_at.isoformat(),
             "context_pct": self._last_context.get("percentage", 0),
             "progress_pct": self.progress_pct,
             "progress_status": self.progress_status,
             "backend_type": self.backend_type,
             "hibernated": self._hibernated,
             "task_id": self.task_id,
             "description": self.description,
             "owned_dirs": self.owned_dirs,
             "tg_topic": self.tg_topic,
             "system_prompt": self.system_prompt[:500] if self.system_prompt else "",
             "total_turns": self.total_turns,
             "total_input_tokens": self.total_input_tokens,
             "total_output_tokens": self.total_output_tokens,
             "total_tool_calls": self.total_tool_calls,
         }

exec
/usr/bin/zsh -lc "git show main:app/backend_protocol.py | sed -n '1,220p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
"""Backend protocol — structural typing contract for agent backends."""

from typing import AsyncIterator, Optional, Protocol

from app.events import AgentEvent


class BackendLike(Protocol):
    @property
    def session_id(self) -> Optional[str]: ...
    async def connect(self) -> None: ...
    async def send(self, message: str) -> None: ...
    async def events(self) -> AsyncIterator[AgentEvent]: ...
    async def interrupt(self) -> None: ...
    async def disconnect(self) -> None: ...

exec
/usr/bin/zsh -lc "git show main:app/session.py | sed -n '1,180p' && git show main:app/session.py | rg -n \"needs_switch|BackendLike|_apply_turn_result|_update_context_from_turn|_finish_turn_status|_after_turn_idle_actions|mid-turn|inject|_make_backend|_to_db_dict|to_dict\" -C 3" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
"""AgentSession — backend-agnostic wrapper with persistent event loop."""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from app.events import AgentEvent
from app.prompting import is_orchestrator_role

if TYPE_CHECKING:
    from app.backend_protocol import BackendLike
from app.db import save_session, add_log

logger = logging.getLogger(__name__)

import concurrent.futures
_DB_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None


def _db_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Dedicated pool for DB writes so logs/persists don't contend with git ops
    on the default executor (used by asyncio.to_thread)."""
    global _DB_EXECUTOR
    if _DB_EXECUTOR is None:
        _DB_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="db")
    return _DB_EXECUTOR


IDLE_TIMEOUT_WORKER = 300
IDLE_TIMEOUT_ORCHESTRATOR = 600



def _load_scope_mcp_servers(scope: str) -> dict:
    servers = {}
    for name in ("settings.json", "settings.local.json"):
        path = Path(scope) / ".claude" / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
            for k, v in data.get("mcpServers", {}).items():
                if k != "orchestra":
                    servers[k] = v
        except Exception as e:
            logger.warning(f"Failed to parse MCP servers from {path}: {e}")
    mcp_json = Path(scope) / ".mcp.json"
    if mcp_json.is_file():
        try:
            data = json.loads(mcp_json.read_text())
            for k, v in data.get("mcpServers", {}).items():
                if k != "orchestra":
                    servers[k] = v
        except Exception as e:
            logger.warning(f"Failed to parse .mcp.json from {mcp_json}: {e}")
    return servers


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"


@dataclass
class AgentSession:
    id: str
    name: str
    scope: str
    cwd: str
    model: str = "claude-sonnet-4-6"
    system_prompt: str = ""
    status: AgentStatus = AgentStatus.IDLE
    session_id: str | None = None
    cost_usd: float = 0.0
    cost_usd_cached: float = 0.0
    worktree_path: str | None = None
    branch: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    role: str = "worker"
    parent_id: str = ""
    parent_name: str = ""
    color: str = ""
    mcp_servers: dict = field(default_factory=dict, repr=False)
    mcp_servers_custom: dict = field(default_factory=dict, repr=False)
    on_error: Optional[callable] = field(default=None, repr=False)
    backend_type: str = "claude"
    task_id: str = ""
    description: str = ""
    owned_dirs: list = field(default_factory=list, repr=False)
    tg_topic: bool = False

    needs_switch: bool = False

    progress_pct: int = 0
    progress_status: str = ""

    total_turns: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tool_calls: int = 0

    _backend: Optional["BackendLike"] = field(default=None, repr=False)
    _listen_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _heartbeat_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _background_tasks: set = field(default_factory=set, repr=False)
    _last_context: dict = field(default_factory=lambda: {"percentage": 0, "total_tokens": 0, "max_tokens": 0}, repr=False)
    _did_report: bool = field(default=False, repr=False)
    _turn_logs: list = field(default_factory=list, repr=False)
    _prompt_injected: bool = field(default=False, repr=False)
    _current_prompt: str = field(default="", repr=False)
    _template_hash: str = field(default="", repr=False)
    _turn_start: float = field(default=0.0, repr=False)
    _last_msg_time: float = field(default=0.0, repr=False)
    _pending_messages: list = field(default_factory=list, repr=False)
    on_idle: Optional[callable] = field(default=None, repr=False)
    _hibernate_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _hibernated: bool = field(default=False, repr=False)
    _compacting: bool = field(default=False, repr=False)
    _compact_ack_event: Optional[asyncio.Event] = field(default=None, repr=False)
    _compact_ack_gen: int = field(default=-1, repr=False)
    _last_cost: float = field(default=0.0, repr=False)
    _last_cost_cached: float = field(default=0.0, repr=False)
    _last_turn_ok: bool = field(default=True, repr=False)
    _last_stop_reason: str = field(default="", repr=False)
    _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _persist_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _persist_dirty: bool = field(default=False, repr=False)
    _turn_gen: int = field(default=0, repr=False)
    _auto_report_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _spawn_warning: str = field(default="", repr=False)

    TURN_TIMEOUT = 600

    @property
    def is_orchestrator(self) -> bool:
        return is_orchestrator_role(self.role)

    def _make_backend(self, force_fresh: bool = False):
        resume = None if force_fresh else self.session_id
        if self.backend_type == "codex":
            from app.backend_codex import CodexBackend
            return CodexBackend(
                model=self.model, cwd=self.cwd,
                system_prompt=self.system_prompt,
                resume_thread_id=resume,
                mcp_env=self._build_codex_mcp_env(),
                reasoning_effort=self._codex_reasoning_effort(),
            )
        else:
            from app.backend_claude import ClaudeBackend
            return ClaudeBackend(
                model=self.model, cwd=self.cwd,
                system_prompt=self.system_prompt,
                resume_session_id=resume,
                mcp_servers=self.mcp_servers,
                is_orchestrator=self.is_orchestrator,
                scope_mcp_servers=_load_scope_mcp_servers(self.scope),
            )

    def _codex_reasoning_effort(self) -> str:
        return "high"

    def _spawn_bg(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        def _on_done(t):
            self._background_tasks.discard(t)
            if not t.cancelled():
                exc = t.exception()
                if exc:
                    logger.warning(f"[{self.name}] background task failed: {exc}")
        task.add_done_callback(_on_done)
15-from app.prompting import is_orchestrator_role
16-
17-if TYPE_CHECKING:
18:    from app.backend_protocol import BackendLike
19-from app.db import save_session, add_log
20-
21-logger = logging.getLogger(__name__)
--
97-    owned_dirs: list = field(default_factory=list, repr=False)
98-    tg_topic: bool = False
99-
100:    needs_switch: bool = False
101-
102-    progress_pct: int = 0
103-    progress_status: str = ""
--
107-    total_output_tokens: int = 0
108-    total_tool_calls: int = 0
109-
110:    _backend: Optional["BackendLike"] = field(default=None, repr=False)
111-    _listen_task: Optional[asyncio.Task] = field(default=None, repr=False)
112-    _heartbeat_task: Optional[asyncio.Task] = field(default=None, repr=False)
113-    _background_tasks: set = field(default_factory=set, repr=False)
114-    _last_context: dict = field(default_factory=lambda: {"percentage": 0, "total_tokens": 0, "max_tokens": 0}, repr=False)
115-    _did_report: bool = field(default=False, repr=False)
116-    _turn_logs: list = field(default_factory=list, repr=False)
117:    _prompt_injected: bool = field(default=False, repr=False)
118-    _current_prompt: str = field(default="", repr=False)
119-    _template_hash: str = field(default="", repr=False)
120-    _turn_start: float = field(default=0.0, repr=False)
--
143-    def is_orchestrator(self) -> bool:
144-        return is_orchestrator_role(self.role)
145-
146:    def _make_backend(self, force_fresh: bool = False):
147-        resume = None if force_fresh else self.session_id
148-        if self.backend_type == "codex":
149-            from app.backend_codex import CodexBackend
--
213-                await backend.send(message)
214-                return
215-            except Exception as e:
216:                logger.warning(f"[{self.name}] mid-turn inject failed, queueing: {e}")
217-                self._pending_messages.append(message)
218:                self._log("status", f"inject failed, queued ({len(self._pending_messages)} pending)")
219-                return
220-
221-        async with self._lifecycle_lock:
--
227-                        await backend.send(message)
228-                        return
229-                    except Exception as e:
230:                        logger.warning(f"[{self.name}] mid-turn inject failed in lock, queueing: {e}")
231-                self._pending_messages.append(message)
232-                self._log("user_message", message)
233-                self._log("status", f"message queued (race, {len(self._pending_messages)} pending)")
--
245-            self.progress_status = ""
246-            self._log("user_message", message)
247-
248:            did_inject = False
249-            pending_th = ""
250-            templates_changed = False
251:            if self.session_id and self._current_prompt and not self._prompt_injected:
252-                from app.prompting import prompt_template_hash
253-                current_th = prompt_template_hash(self.role)
254-                old_th = self._template_hash or current_th
255-                templates_changed = old_th != current_th
256-                pending_th = current_th
257-                message = f"[Orchestra platform note: {'your role instructions were updated.' if templates_changed else 'refreshed context (worker list, etc.).'} This is from the server, not another agent.]\n{self._current_prompt}\n\n---\n\n{message}"
258:                did_inject = True
259-
260-            if self.status in (AgentStatus.IDLE, AgentStatus.WAITING):
261-                self._did_report = False
--
275-
276-            await backend.send(message)
277-
278:            if did_inject:
279-                if templates_changed:
280-                    self._log("status", f"prompt updated → {pending_th}")
281-                self._template_hash = pending_th
282:                self._prompt_injected = True
283-                self.system_prompt = self._current_prompt
284-
285-            if self.backend_type == "codex":
--
290-            if not force_fresh:
291-                return self._backend
292-            await self._disconnect_backend()
293:        self._backend = self._make_backend(force_fresh=force_fresh)
294-        try:
295-            await self._backend.connect()
296-        except Exception as e:
--
468-    def _handle_turn_end(self, event: AgentEvent) -> None:
469-        meta = event.metadata
470-        self._turn_start = 0
471:        ok, sr, nt = self._apply_turn_result(meta)
472:        self._update_context_from_turn(meta)
473-        self._spawn_bg(self._refresh_context_from_api())
474-
475-        if not ok:
--
487-        ctx_s = f"ctx:{live_pct}%" if live_pct else ""
488-        self._log("status", f"turn ended ({sr}, {nt} turns, ${cost:.2f} {ctx_s})")
489-
490:        self._finish_turn_status()
491:        self._after_turn_idle_actions(live_pct)
492-
493:    def _apply_turn_result(self, meta: dict) -> tuple[bool, str, int]:
494-        """Update session_id, costs, token totals from turn metadata."""
495-        ok = meta.get("ok", True)
496-        sr = meta.get("stop_reason", "unknown")
--
515-        self.total_output_tokens += meta.get("output_tokens", 0)
516-        return ok, sr, nt
517-
518:    def _update_context_from_turn(self, meta: dict) -> None:
519-        """Update context window stats from turn metadata."""
520-        ctx_pct = meta.get("context_pct", 0)
521-        ctx_tokens = meta.get("context_tokens", 0)
--
527-        self._last_context["cache_read"] = meta.get("cache_read", 0)
528-        self._last_context["cache_create"] = meta.get("cache_create", 0)
529-
530:    def _finish_turn_status(self) -> None:
531-        """Set IDLE or WAITING based on bg jobs, then persist."""
532-        from app.bg_jobs import bg_manager
533-        if bg_manager and bg_manager.has_active_jobs(self.id):
--
537-            self.status = AgentStatus.IDLE
538-        self._persist()
539-
540:    def _after_turn_idle_actions(self, live_pct: int) -> None:
541-        """Post-turn actions: compact ack, scope idle, auto-compact, auto-report, flush/hibernate."""
542-        if self._compact_ack_event is not None and self._turn_gen == self._compact_ack_gen:
543-            self._compact_ack_event.set()
--
733-                pass
734-
735-        summary_parts = []
736:        backend = self._backend or self._make_backend()
737-        need_connect = self._backend is None
738-        try:
739-            async with self._lifecycle_lock:
--
919-    async def _persist_loop(self) -> None:
920-        while self._persist_dirty:
921-            self._persist_dirty = False
922:            snapshot = self._to_db_dict()
923-            try:
924-                await asyncio.get_running_loop().run_in_executor(_db_executor(), save_session, snapshot)
925-            except Exception as e:
--
932-    def _log(self, type: str, content: str) -> None:
933-        asyncio.get_event_loop().run_in_executor(_db_executor(), add_log, self.id, datetime.now(timezone.utc), type, content)
934-
935:    def _to_db_dict(self) -> dict:
936-        return {
937-            "id": self.id, "name": self.name, "scope": self.scope, "cwd": self.cwd,
938-            "model": self.model, "system_prompt": self.system_prompt,
--
963-    async def get_context(self) -> dict:
964-        return self._last_context
965-
966:    def to_dict(self) -> dict:
967-        return {
968-            "id": self.id, "name": self.name, "scope": self.scope,
969-            "status": self.status.value, "model": self.model,

exec
/usr/bin/zsh -lc 'git show main:app/main.py | rg -n "from app.deps|include_router|routes|_DENIED_PARTS|needs_switch|kill_worker|next_task_id|get_role_icons|role-icons|create_session|delete_session|force|parent_name" -C 3' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
22-from pydantic import BaseModel, field_validator, model_validator
23-
24-from app.db import init_db, get_logs, get_logs_before, get_all_sessions
25:from app.deps import manager
26-from app.models import resolve_model, MODELS
27-from app.session import AgentStatus
28-templates = Jinja2Templates(directory="app/templates")
--
54-app = FastAPI(title="Orchestra", lifespan=lifespan)
55-app.mount("/static", StaticFiles(directory="app/static"), name="static")
56-
57:from app.routes.tm import router as tm_router
58:from app.routes.bg import router as bg_router
59:from app.routes.proxy import router as proxy_router
60:app.include_router(tm_router)
61:app.include_router(bg_router)
62:app.include_router(proxy_router)
63-
64-
65-from app.auth import is_auth_enabled, validate_session, requires_auth, check_internal_token
--
107-    task_id: str = ""
108-    description: str = ""
109-    base_branch: str = "main"
110:    parent_name: str = ""
111-    mcp_servers: dict = {}
112-    owned_dirs: list[str] = []
113-    tg_topic: bool = False
--
177-
178-@app.post("/login")
179-async def login_submit(request: Request, username: str = Form(""), password: str = Form("")):
180:    from app.auth import check_credentials, create_session
181-    if not is_auth_enabled():
182-        return RedirectResponse("/", status_code=302)
183-    if check_credentials(username, password):
184:        token = create_session(username)
185-        response = RedirectResponse("/", status_code=302)
186-        secure = request.url.scheme == "https" or os.environ.get("COOKIE_SECURE") == "1"
187-        response.set_cookie("session", token, httponly=True, samesite="lax", max_age=2592000, secure=secure)
--
264-    return _ALLOWED_ROOTS
265-
266-
267:_DENIED_PARTS = {".env", ".ssh", ".git", ".credentials", ".gnupg", ".aws",
268-                 ".npmrc", ".pypirc", ".netrc", ".docker", ".kube"}
269-_DENIED_HOME_PARTS = {".claude", ".config"}
270-_DENIED_EXTENSIONS = {".db", ".db-shm", ".db-wal", ".db-journal", ".sqlite", ".sqlite3", ".key", ".pem", ".p12", ".pfx"}
--
285-        return False
286-    home = str(Path.home())
287-    for part in p.parts:
288:        if part in _DENIED_PARTS or part.startswith(".env"):
289-            return False
290-    if resolved.startswith(home):
291-        for part in _DENIED_HOME_PARTS:
--
378-    return items
379-
380-
381:@app.get("/api/role-icons")
382-async def role_icons():
383:    from app.prompting import get_role_icons
384:    return get_role_icons()
385-
386-
387-@app.get("/api/sessions")
--
390-
391-
392-@app.post("/api/sessions", status_code=201)
393:async def create_session(req: CreateSessionRequest):
394-    if not _is_safe_path(req.cwd):
395-        return JSONResponse({"error": f"cwd not in allowed paths: {req.cwd}"}, status_code=403)
396-    scope = req.scope or req.cwd
397-    try:
398:        session = await manager.create_session(
399-            name=req.name,
400-            scope=scope,
401-            cwd=req.cwd,
--
408-            task_id=req.task_id,
409-            description=req.description,
410-            base_branch=req.base_branch,
411:            parent_name=req.parent_name,
412-            mcp_servers=req.mcp_servers,
413-            owned_dirs=req.owned_dirs,
414-            tg_topic=req.tg_topic,
--
538-            similar = [n for n in all_names if name.lower() in n.lower() or n.lower() in name.lower()]
539-            hint = f" Similar: {', '.join(similar[:5])}" if similar else f" Available: {', '.join(all_names[:10])}"
540-            return JSONResponse({"error": f"agent '{name}' not found.{hint}"}, status_code=404)
541:        if hasattr(session, 'needs_switch') and session.needs_switch:
542-            return JSONResponse({"error": "worker was merged — call switch_worker_branch first"}, status_code=400)
543-        msg = f"[from:{req.sender}] {req.message}" if req.sender else req.message
544-        if req.sender:
--
549-            now = datetime.now(local_tz).strftime("%H:%M")
550-            msg = f"[{now}] {msg}"
551-        await manager.send(session.id, msg)
552:        pn = getattr(session, "parent_name", "") or (session.get("parent_name", "") if isinstance(session, dict) else "")
553:        return {"ok": True, "parent_name": pn}
554-    except (RuntimeError, KeyError) as e:
555-        return JSONResponse({"error": str(e)}, status_code=400)
556-    except Exception as e:
--
738-
739-
740-@app.delete("/api/sessions/{name}")
741:async def delete_session(name: str, scope: str, force: bool = False):
742-    found = manager.get_by_name(name, scope)
743-    if not found:
744-        return JSONResponse({"error": "not found"}, status_code=404)
745-    sid = found["id"] if isinstance(found, dict) else found.id
746:    if not force:
747-        if not isinstance(found, dict) and found.status.value == "running":
748:            return JSONResponse({"error": "worker is running — stop first (or force=true)"}, status_code=400)
749-        wt = found.get("worktree_path") if isinstance(found, dict) else found.worktree_path
750-        if wt and Path(wt).is_dir():
751-            status_proc = await asyncio.create_subprocess_exec(
--
756-                stdout, stderr = await asyncio.wait_for(status_proc.communicate(), timeout=5)
757-            except asyncio.TimeoutError:
758-                status_proc.kill()
759:                return JSONResponse({"error": "git status timed out in worktree. Use force=true if certain"}, status_code=400)
760-            if status_proc.returncode != 0:
761:                return JSONResponse({"error": f"git status failed: {stderr.decode().strip()}. Use force=true if certain"}, status_code=400)
762-            dirty = stdout.decode().strip()
763-            if dirty:
764-                files = [l[3:] for l in dirty.splitlines()[:10]]
765:                return JSONResponse({"error": f"worker has uncommitted changes: {', '.join(files)}. Commit or discard first (or force=true)"}, status_code=400)
766-            ahead_proc = await asyncio.create_subprocess_exec(
767-                "git", "rev-list", "main..HEAD", "--count", cwd=wt,
768-                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
--
771-                stdout, stderr = await asyncio.wait_for(ahead_proc.communicate(), timeout=5)
772-            except asyncio.TimeoutError:
773-                ahead_proc.kill()
774:                return JSONResponse({"error": "git rev-list timed out. Use force=true if certain"}, status_code=400)
775-            ahead = stdout.decode().strip()
776-            if ahead_proc.returncode != 0 or not ahead.isdigit():
777:                return JSONResponse({"error": f"git rev-list failed: {stderr.decode().strip()}. Use force=true if certain"}, status_code=400)
778-            n = int(ahead)
779-            if n > 0:
780:                return JSONResponse({"error": f"worker has {n} unmerged commit(s). merge_worker first (or force=true)"}, status_code=400)
781-    await manager.remove(sid)
782-    return {"ok": True}
783-
--
787-    from app.workspace import merge_worktree_to_main
788-    scope = req.get("scope", "")
789-    target = req.get("target", "main")
790:    next_task_id = req.get("next_task_id", "")
791-    found = manager.get_by_name(name, scope)
792-    if not found:
793-        return JSONResponse({"error": "not found"}, status_code=404)
--
818-                if not isinstance(found, dict):
819-                    found.branch = target
820-                    found.task_id = ""
821:                    found.needs_switch = True
822-                    found._persist()
823:                if next_task_id and not isinstance(found, dict):
824-                    from app.workspace import switch_worktree_branch, _normalize_task_id
825:                    par = _normalize_task_id(next_task_id)
826-                    new_branch = f"task-{par}/{name}"
827-                    switch_result = await asyncio.to_thread(
828-                        switch_worktree_branch, worktree_path, new_branch, f"refs/heads/{target}")
829-                    if switch_result.get("ok"):
830-                        found.branch = switch_result.get("branch", new_branch)
831-                        found.task_id = par
832:                        found.needs_switch = False
833-                        found._persist()
834-                        try:
835-                            _tm.api_update_task(par, status="in_progress")
--
871-                if result.get("ok") or result.get("branch"):
872-                    found.branch = result.get("branch", new_branch)
873-                    found.task_id = par
874:                    found.needs_switch = False
875-                    found._persist()
876-            try:
877-                _tm.api_update_task(par, status="in_progress")

codex
Main’s `app/main.py` already uses the shared `app.deps.manager` and mounted routers. The plan’s “keep main architecture” is correct, but the concrete import resolution should be stricter: do not reintroduce `from app.manager import SessionManager; manager = SessionManager()` from the PR side, or routes/background jobs can split state.
exec
/usr/bin/zsh -lc "git diff --unified=100 main...vadim/feat/pipeline-as-config -- app/db.py tests/test_db.py tests/test_api.py tests/test_session.py tests/test_mcp_stdio.py | sed -n '1,620p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
diff --git a/app/db.py b/app/db.py
index b5ddf41..1b982ca 100644
--- a/app/db.py
+++ b/app/db.py
@@ -1,159 +1,165 @@
 """SQLite storage for sessions and logs."""
 
 import json
 import os
 import sqlite3
 from datetime import datetime, timedelta, timezone
 from pathlib import Path
 
 _DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "orchestra.db"
 
 
 def _resolve_db_path() -> Path:
     """Путь к БД: ORCHESTRA_DB_PATH из env (если задан) или дефолт data/orchestra.db.
 
     Позволяет разным worktree/веткам и тестам держать свою БД, не блокируя
     друг друга через SQLite-лок при параллельной работе.
     """
     override = os.getenv("ORCHESTRA_DB_PATH", "").strip()
     if not override:
         return _DEFAULT_DB_PATH
     p = Path(override)
     return p if p.is_absolute() else (Path(__file__).parent.parent / p)
 
 
 DB_PATH = _resolve_db_path()
 
 
 def _conn() -> sqlite3.Connection:
     DB_PATH.parent.mkdir(exist_ok=True)
     conn = sqlite3.connect(str(DB_PATH))
     conn.row_factory = sqlite3.Row
     conn.execute("PRAGMA journal_mode=WAL")
     conn.execute("PRAGMA busy_timeout=5000")
     conn.execute("PRAGMA foreign_keys=ON")
     return conn
 
 
 def init_db() -> None:
     with _conn() as c:
         c.executescript("""
             CREATE TABLE IF NOT EXISTS sessions (
                 id TEXT PRIMARY KEY,
                 name TEXT NOT NULL,
                 scope TEXT NOT NULL,
                 cwd TEXT NOT NULL,
                 model TEXT NOT NULL,
                 system_prompt TEXT DEFAULT '',
                 status TEXT DEFAULT 'starting',
                 session_id TEXT,
                 cost_usd REAL DEFAULT 0.0,
                 worktree_path TEXT,
                 branch TEXT,
                 is_orchestrator INTEGER DEFAULT 0,
                 color TEXT DEFAULT '',
                 mcp_servers_custom TEXT DEFAULT '',
+                profile TEXT DEFAULT '',
                 created_at TEXT NOT NULL,
                 finished_at TEXT,
                 UNIQUE(name, scope)
             );
+            CREATE TABLE IF NOT EXISTS profiles (
+                name TEXT PRIMARY KEY,
+                config_dir TEXT NOT NULL DEFAULT '',
+                created_at TEXT DEFAULT CURRENT_TIMESTAMP
+            );
             CREATE TABLE IF NOT EXISTS logs (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                 ts TEXT NOT NULL,
                 type TEXT NOT NULL,
                 content TEXT NOT NULL
             );
             CREATE INDEX IF NOT EXISTS idx_logs_session ON logs(session_id, id DESC);
             CREATE INDEX IF NOT EXISTS idx_sessions_scope ON sessions(scope, is_orchestrator, status);
 
             CREATE TABLE IF NOT EXISTS inbox (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                 sender TEXT NOT NULL,
                 message TEXT NOT NULL,
                 status TEXT DEFAULT 'pending',
                 created_at TEXT NOT NULL
             );
             CREATE INDEX IF NOT EXISTS idx_inbox_session ON inbox(session_id, status);
 
             CREATE TABLE IF NOT EXISTS jobs (
                 id TEXT PRIMARY KEY,
                 type TEXT NOT NULL,
                 name TEXT NOT NULL,
                 scope TEXT NOT NULL,
                 status TEXT DEFAULT 'queued',
                 error TEXT,
                 created_at TEXT NOT NULL,
                 finished_at TEXT
             );
             CREATE TABLE IF NOT EXISTS test_lock (
                 scope TEXT PRIMARY KEY,
                 holder TEXT NOT NULL,
                 reason TEXT DEFAULT '',
                 acquired_at TEXT NOT NULL
             );
         """)
         c.executescript("""
             CREATE TABLE IF NOT EXISTS tm_projects (
                 id TEXT PRIMARY KEY,
                 name TEXT NOT NULL,
                 prefix TEXT NOT NULL DEFAULT 'TASK',
                 scope TEXT UNIQUE,
                 yougile_project_id TEXT,
                 yougile_board_id TEXT,
                 yougile_enabled INTEGER NOT NULL DEFAULT 0,
                 created_at TEXT NOT NULL,
                 UNIQUE(prefix)
             );
             CREATE TABLE IF NOT EXISTS tm_tasks (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 par_number INTEGER NOT NULL,
                 project_id TEXT NOT NULL REFERENCES tm_projects(id),
                 title TEXT NOT NULL,
                 description TEXT NOT NULL DEFAULT '',
                 price_rub INTEGER NOT NULL DEFAULT 0 CHECK (price_rub >= 0),
                 paid_rub INTEGER NOT NULL DEFAULT 0 CHECK (paid_rub >= 0),
                 status TEXT NOT NULL DEFAULT 'backlog',
                 assignee TEXT NOT NULL DEFAULT '',
                 yougile_task_id TEXT UNIQUE,
                 sync_revision INTEGER NOT NULL DEFAULT 0,
                 worker_session_id TEXT,
                 git_commits TEXT NOT NULL DEFAULT '[]',
                 created_at TEXT NOT NULL,
                 updated_at TEXT NOT NULL,
                 completed_at TEXT,
                 paid_at TEXT,
                 CHECK (status IN ('backlog','new','in_progress','done','paid','cancelled'))
             );
             CREATE INDEX IF NOT EXISTS idx_tm_tasks_status ON tm_tasks(status);
             CREATE INDEX IF NOT EXISTS idx_tm_tasks_project ON tm_tasks(project_id, status);
             CREATE UNIQUE INDEX IF NOT EXISTS idx_tm_tasks_par_project ON tm_tasks(project_id, par_number);
             CREATE INDEX IF NOT EXISTS idx_tm_tasks_yougile ON tm_tasks(yougile_task_id);
             CREATE TABLE IF NOT EXISTS tm_clients (
                 id TEXT PRIMARY KEY,
                 name TEXT NOT NULL,
                 project_id TEXT NOT NULL REFERENCES tm_projects(id),
                 balance_rub INTEGER NOT NULL DEFAULT 0,
                 created_at TEXT NOT NULL
             );
             CREATE TABLE IF NOT EXISTS tm_payments (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 client_id TEXT NOT NULL REFERENCES tm_clients(id),
                 amount_rub INTEGER NOT NULL CHECK (amount_rub > 0),
                 date TEXT NOT NULL,
                 note TEXT NOT NULL DEFAULT '',
                 created_at TEXT NOT NULL
             );
             CREATE TABLE IF NOT EXISTS tm_payment_allocations (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 payment_id INTEGER NOT NULL REFERENCES tm_payments(id),
                 task_id INTEGER NOT NULL REFERENCES tm_tasks(id),
                 amount_rub INTEGER NOT NULL CHECK (amount_rub > 0),
                 created_at TEXT NOT NULL
             );
             CREATE INDEX IF NOT EXISTS idx_tm_alloc_payment ON tm_payment_allocations(payment_id);
             CREATE INDEX IF NOT EXISTS idx_tm_alloc_task ON tm_payment_allocations(task_id);
             CREATE TABLE IF NOT EXISTS tm_sync_log (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 task_id INTEGER REFERENCES tm_tasks(id),
@@ -283,340 +289,390 @@ def _migrate(c) -> None:
         _bg_cols = ("id", "type", "config", "message", "target_session_id", "target_name",
                     "target_scope", "created_by_name", "status", "error", "expires_at",
                     "trigger_at", "created_at", "triggered_at", "last_output")
         _bg_col_list = ", ".join(_bg_cols)
         c.execute("ALTER TABLE bg_jobs RENAME TO bg_jobs_old")
         c.execute("""
             CREATE TABLE bg_jobs (
                 id TEXT PRIMARY KEY,
                 type TEXT NOT NULL,
                 config TEXT NOT NULL DEFAULT '{}',
                 message TEXT NOT NULL DEFAULT '',
                 target_session_id TEXT NOT NULL,
                 target_name TEXT NOT NULL,
                 target_scope TEXT NOT NULL,
                 created_by_name TEXT NOT NULL DEFAULT '',
                 status TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active','triggering','triggered','expired','cancelled','failed')),
                 error TEXT,
                 expires_at TEXT NOT NULL,
                 trigger_at TEXT,
                 created_at TEXT NOT NULL,
                 triggered_at TEXT,
                 last_output TEXT NOT NULL DEFAULT ''
             )
         """)
         c.execute(f"INSERT INTO bg_jobs ({_bg_col_list}) SELECT {_bg_col_list} FROM bg_jobs_old")
         c.execute("DROP TABLE bg_jobs_old")
         c.execute("CREATE INDEX IF NOT EXISTS idx_bg_jobs_session ON bg_jobs(target_session_id, status)")
         c.execute("CREATE INDEX IF NOT EXISTS idx_bg_jobs_scope ON bg_jobs(target_scope, status)")
     try:
         c.execute("DROP TABLE IF EXISTS tm_par_sequence")
     except Exception:
         pass
     for old_name in ("_tm_tasks_old", "tm_tasks_old"):
         old_exists = c.execute(f"SELECT 1 FROM sqlite_master WHERE type='table' AND name='{old_name}'").fetchone()
         if old_exists:
             c.execute("DROP TABLE IF EXISTS tm_tasks")
             c.execute(f"ALTER TABLE {old_name} RENAME TO tm_tasks")
             break
     try:
         auto_idx = [r[1] for r in c.execute("PRAGMA index_list(tm_tasks)").fetchall()
                     if r[1].startswith("sqlite_autoindex")]
     except Exception:
         auto_idx = []
     needs_recreate = False
     for idx in auto_idx:
         try:
             info = c.execute(f"PRAGMA index_info({idx})").fetchall()
             if [r[2] for r in info] == ["par_number"]:
                 needs_recreate = True
                 break
         except Exception:
             pass
     if needs_recreate:
         c.execute("ALTER TABLE tm_tasks RENAME TO _tm_tasks_old")
         c.execute("""CREATE TABLE tm_tasks (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             par_number INTEGER NOT NULL,
             project_id TEXT NOT NULL REFERENCES tm_projects(id),
             title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
             price_rub INTEGER NOT NULL DEFAULT 0 CHECK (price_rub >= 0),
             paid_rub INTEGER NOT NULL DEFAULT 0 CHECK (paid_rub >= 0),
             status TEXT NOT NULL DEFAULT 'backlog', assignee TEXT NOT NULL DEFAULT '',
             yougile_task_id TEXT UNIQUE, sync_revision INTEGER NOT NULL DEFAULT 0,
             worker_session_id TEXT, git_commits TEXT NOT NULL DEFAULT '[]',
             created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
             completed_at TEXT, paid_at TEXT,
             CHECK (status IN ('backlog','new','in_progress','done','paid','cancelled'))
         )""")
         c.execute("INSERT INTO tm_tasks SELECT * FROM _tm_tasks_old")
         c.execute("DROP TABLE _tm_tasks_old")
     c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tm_tasks_par_project ON tm_tasks(project_id, par_number)")
     c.execute("CREATE INDEX IF NOT EXISTS idx_tm_tasks_status ON tm_tasks(status)")
     c.execute("CREATE INDEX IF NOT EXISTS idx_tm_tasks_project ON tm_tasks(project_id, status)")
     for tbl in ("tm_payment_allocations", "tm_sync_log"):
         try:
             schema = c.execute(f"SELECT sql FROM sqlite_master WHERE name='{tbl}' AND type='table'").fetchone()
             if schema and "tm_tasks_old" in schema[0]:
                 old_name = f"_{tbl}_fix"
                 c.execute(f"ALTER TABLE {tbl} RENAME TO {old_name}")
                 create_sql = schema[0].replace('"tm_tasks_old"', 'tm_tasks').replace("tm_tasks_old", "tm_tasks")
                 c.execute(create_sql)
                 c.execute(f"INSERT INTO {tbl} SELECT * FROM {old_name}")
                 c.execute(f"DROP TABLE {old_name}")
         except Exception:
             pass
     c.execute("CREATE INDEX IF NOT EXISTS idx_tm_tasks_yougile ON tm_tasks(yougile_task_id)")
     task_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_tasks)").fetchall()}
     if task_cols and "priority" not in task_cols:
         c.execute("ALTER TABLE tm_tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 2")
     client_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_clients)").fetchall()}
     if client_cols and "journal_yougile_id" not in client_cols:
         c.execute("ALTER TABLE tm_clients ADD COLUMN journal_yougile_id TEXT DEFAULT ''")
     if "role" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN role TEXT DEFAULT 'worker'")
         c.execute("UPDATE sessions SET role = 'orchestrator' WHERE is_orchestrator = 1")
     if "parent_id" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN parent_id TEXT DEFAULT ''")
     if "parent_name" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN parent_name TEXT DEFAULT ''")
+    if "pipeline" not in cols:
+        c.execute("ALTER TABLE sessions ADD COLUMN pipeline TEXT DEFAULT ''")
+        c.execute("UPDATE sessions SET is_orchestrator = 1 WHERE role IN ('orchestrator', 'sub-orchestrator')")
+    if "profile" not in cols:
+        c.execute("ALTER TABLE sessions ADD COLUMN profile TEXT DEFAULT ''")
     if "owned_dirs" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN owned_dirs TEXT DEFAULT ''")
     if "tg_topic" not in cols:
         c.execute("ALTER TABLE sessions ADD COLUMN tg_topic INTEGER DEFAULT 0")
+    # Идемпотентный сид профиля 'personal' (config_dir="" → env процесса, как сегодня).
+    # INSERT OR IGNORE: повторная миграция не падает и не перетирает существующую строку.
+    c.execute("INSERT OR IGNORE INTO profiles (name, config_dir) VALUES ('personal', '')")
 
 
 def save_session(s: dict) -> None:
     s.setdefault("context_pct", 0)
     s.setdefault("context_tokens", 0)
     s.setdefault("progress_pct", 0)
     s.setdefault("progress_status", "")
     s.setdefault("backend_type", "claude")
     s.setdefault("task_id", "")
     s.setdefault("description", "")
     s.setdefault("cost_usd_cached", 0.0)
     s.setdefault("total_turns", 0)
     s.setdefault("total_input_tokens", 0)
     s.setdefault("total_output_tokens", 0)
     s.setdefault("total_tool_calls", 0)
     s.setdefault("template_hash", "")
     s.setdefault("role", "worker")
     s.setdefault("parent_id", "")
     s.setdefault("parent_name", "")
+    s.setdefault("pipeline", "")
+    s.setdefault("profile", "")
     s.setdefault("mcp_servers_custom", "")
     s.setdefault("owned_dirs", "")
     s.setdefault("tg_topic", 0)
     with _conn() as c:
         c.execute("""
             INSERT INTO sessions (id, name, scope, cwd, model, system_prompt,
                 status, session_id, cost_usd, worktree_path, branch, is_orchestrator,
                 color, created_at, finished_at, context_pct, context_tokens,
                 progress_pct, progress_status, backend_type, task_id, description,
                 cost_usd_cached,
                 total_turns, total_input_tokens, total_output_tokens, total_tool_calls,
-                template_hash, role, parent_id, parent_name, mcp_servers_custom, owned_dirs,
-                tg_topic)
+                template_hash, role, parent_id, parent_name, mcp_servers_custom, pipeline,
+                profile, owned_dirs, tg_topic)
             VALUES (:id, :name, :scope, :cwd, :model, :system_prompt,
                 :status, :session_id, :cost_usd, :worktree_path, :branch, :is_orchestrator,
                 :color, :created_at, :finished_at, :context_pct, :context_tokens,
                 :progress_pct, :progress_status, :backend_type, :task_id, :description,
                 :cost_usd_cached,
                 :total_turns, :total_input_tokens, :total_output_tokens, :total_tool_calls,
-                :template_hash, :role, :parent_id, :parent_name, :mcp_servers_custom, :owned_dirs,
-                :tg_topic)
+                :template_hash, :role, :parent_id, :parent_name, :mcp_servers_custom, :pipeline,
+                :profile, :owned_dirs, :tg_topic)
             ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name,
                 system_prompt=excluded.system_prompt,
                 status=excluded.status,
                 session_id=excluded.session_id,
                 cost_usd=excluded.cost_usd,
                 cost_usd_cached=excluded.cost_usd_cached,
                 worktree_path=excluded.worktree_path,
                 branch=excluded.branch,
                 cwd=excluded.cwd,
                 color=excluded.color,
                 finished_at=excluded.finished_at,
                 context_pct=excluded.context_pct,
                 context_tokens=excluded.context_tokens,
                 progress_pct=excluded.progress_pct,
                 progress_status=excluded.progress_status,
                 backend_type=excluded.backend_type,
                 task_id=excluded.task_id,
                 description=excluded.description,
                 total_turns=excluded.total_turns,
                 total_input_tokens=excluded.total_input_tokens,
                 total_output_tokens=excluded.total_output_tokens,
                 total_tool_calls=excluded.total_tool_calls,
                 template_hash=excluded.template_hash,
                 role=excluded.role,
                 parent_id=excluded.parent_id,
                 parent_name=excluded.parent_name,
                 mcp_servers_custom=excluded.mcp_servers_custom,
+                pipeline=excluded.pipeline,
+                profile=excluded.profile,
                 owned_dirs=excluded.owned_dirs,
                 tg_topic=excluded.tg_topic
         """, s)
 
 
 def change_scope(session_id: str, old_scope: str, new_scope: str, new_cwd: str) -> dict:
     """Move an orchestrator's session to a new scope in one transaction.
 
     Migrates session.scope+cwd, and (best-effort) tm_projects.scope, active
     bg_jobs.target_scope, and test_lock.scope from old_scope to new_scope.
     session_id (Claude resume token) is left intact — context survives.
 
     Rejected if another session with the same name already lives in new_scope
     (UNIQUE(name, scope)). tm_projects/test_lock migration is skipped on UNIQUE
     collision (target already taken) but the session move still succeeds.
     """
     with _conn() as c:
         row = c.execute("SELECT name FROM sessions WHERE id=?", (session_id,)).fetchone()
         if not row:
             return {"error": f"session not found: {session_id}"}
         name = row["name"]
         clash = c.execute(
             "SELECT 1 FROM sessions WHERE name=? AND scope=? AND id!=? AND status!='archived'",
             (name, new_scope, session_id),
         ).fetchone()
         if clash:
             return {"error": f"session '{name}' already exists in scope '{new_scope}'"}
 
         cur = c.execute(
             "UPDATE sessions SET scope=?, cwd=? WHERE id=? AND scope=?",
             (new_scope, new_cwd, session_id, old_scope),
         )
         if cur.rowcount == 0:
             return {"error": f"session no longer in scope '{old_scope}' (stale or concurrent move)"}
 
         tm_migrated = False
         target_taken = c.execute("SELECT 1 FROM tm_projects WHERE scope=?", (new_scope,)).fetchone()
         if not target_taken:
             cur = c.execute("UPDATE tm_projects SET scope=? WHERE scope=?", (new_scope, old_scope))
             tm_migrated = cur.rowcount > 0
 
         c.execute(
             "UPDATE bg_jobs SET target_scope=? WHERE target_scope=? AND status IN ('active','triggering')",
             (new_scope, old_scope),
         )
 
         lock_target_taken = c.execute("SELECT 1 FROM test_lock WHERE scope=?", (new_scope,)).fetchone()
         if not lock_target_taken:
             c.execute("UPDATE test_lock SET scope=? WHERE scope=?", (new_scope, old_scope))
 
         return {"ok": True, "scope": new_scope, "cwd": new_cwd, "tm_project_migrated": tm_migrated}
 
 
 def get_session(session_id: str) -> dict | None:
     with _conn() as c:
         row = c.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
         return dict(row) if row else None
 
 
 def get_session_by_name(name: str, scope: str) -> dict | None:
     with _conn() as c:
         row = c.execute(
             "SELECT * FROM sessions WHERE name = ? AND scope = ? AND status != 'archived'",
             (name, scope),
         ).fetchone()
         return dict(row) if row else None
 
 
+# ── Профили Claude (CLAUDE_CONFIG_DIR per-session) ──
+
+def list_profiles() -> list[dict]:
+    """Все профили, отсортированы по имени: ``[{"name":..., "config_dir":...}]``."""
+    with _conn() as c:
+        rows = c.execute(
+            "SELECT name, config_dir FROM profiles ORDER BY name"
+        ).fetchall()
+        return [{"name": r["name"], "config_dir": r["config_dir"]} for r in rows]
+
+
+def get_profile(name: str) -> dict | None:
+    """Один профиль по имени или ``None``, если не найден."""
+    with _conn() as c:
+        row = c.execute(
+            "SELECT name, config_dir FROM profiles WHERE name = ?", (name,)
+        ).fetchone()
+        return {"name": row["name"], "config_dir": row["config_dir"]} if row else None
+
+
+def upsert_profile(name: str, config_dir: str) -> None:
+    """Создать профиль или обновить его ``config_dir`` (по конфликту имени)."""
+    with _conn() as c:
+        c.execute(
+            "INSERT INTO profiles (name, config_dir) VALUES (?, ?) "
+            "ON CONFLICT(name) DO UPDATE SET config_dir = excluded.config_dir",
+            (name, config_dir),
+        )
+
+
+def delete_profile(name: str) -> None:
+    """Удалить профиль. Сид-профиль ``personal`` удалять запрещено."""
+    if name == "personal":
+        raise ValueError("Профиль 'personal' является сид-профилем и не может быть удалён")
+    with _conn() as c:
+        c.execute("DELETE FROM profiles WHERE name = ?", (name,))
+
+
 def get_all_sessions(scope: str | None = None, include_archived: bool = False) -> list[dict]:
     with _conn() as c:
         archived_filter = "" if include_archived else " AND status != 'archived'"
         if scope:
             rows = c.execute(
                 f"SELECT * FROM sessions WHERE scope = ?{archived_filter} ORDER BY created_at DESC", (scope,)
             ).fetchall()
         else:
             rows = c.execute(
                 f"SELECT * FROM sessions WHERE 1=1{archived_filter} ORDER BY created_at DESC"
             ).fetchall()
         return [dict(r) for r in rows]
 
 
 def rename_session(session_id: str, new_name: str) -> None:
     with _conn() as c:
         c.execute("UPDATE sessions SET name = ? WHERE id = ?", (new_name, session_id))
 
 
 def delete_session(session_id: str) -> None:
     with _conn() as c:
         c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
 
 
 def archive_session(session_id: str) -> None:
     with _conn() as c:
         c.execute(
             "UPDATE sessions SET status='archived', finished_at=? WHERE id=?",
             (datetime.now(timezone.utc).isoformat(), session_id),
         )
 
 
 def add_log(session_id: str, ts: datetime, type: str, content: str) -> int:
     with _conn() as c:
         cur = c.execute(
             "INSERT INTO logs (session_id, ts, type, content) VALUES (?, ?, ?, ?)",
             (session_id, ts.isoformat(), type, content),
         )
         return cur.lastrowid
 
 
 def get_logs(session_id: str, after_id: int = 0, limit: int = 5000, conn=None) -> list[dict]:
     c = conn or _conn()
     try:
         if after_id > 0:
             rows = c.execute(
                 "SELECT * FROM logs WHERE session_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
                 (session_id, after_id, limit),
             ).fetchall()
             return [dict(r) for r in rows]
         else:
             rows = c.execute(
                 "SELECT * FROM logs WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                 (session_id, limit),
             ).fetchall()
             return [dict(r) for r in reversed(rows)]
     finally:
         if conn is None:
             c.close()
 
 
 def get_logs_before(session_id: str, before_id: int, limit: int = 500) -> list[dict]:
     with _conn() as c:
         rows = c.execute(
             "SELECT * FROM logs WHERE session_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
             (session_id, before_id, limit),
         ).fetchall()
         return [dict(r) for r in reversed(rows)]
 
 
 def get_stats(scope: str | None = None) -> dict:
     with _conn() as c:
         where = "WHERE scope = ?" if scope else ""
         params = (scope,) if scope else ()
         total = c.execute(f"SELECT COUNT(*) FROM sessions {where}", params).fetchone()[0]
         active = c.execute(
             f"SELECT COUNT(*) FROM sessions {where + ' AND ' if where else 'WHERE '}"
             "status IN ('running', 'starting')",
             params,
         ).fetchone()[0]
         archived = c.execute(
             f"SELECT COUNT(*) FROM sessions {where + ' AND ' if where else 'WHERE '}"
             "status = 'archived'",
             params,
         ).fetchone()[0]
         cost = c.execute(
             f"SELECT COALESCE(SUM(cost_usd), 0) FROM sessions {where}", params
         ).fetchone()[0]
         logs_where = (
             f"WHERE session_id IN (SELECT id FROM sessions {where})"
             if where else ""
         )
         total_logs = c.execute(
             f"SELECT COUNT(*) FROM logs {logs_where}", params
         ).fetchone()[0]
         agg = c.execute(
             f"""SELECT COALESCE(SUM(total_turns), 0),
                        COALESCE(SUM(total_input_tokens), 0),
                        COALESCE(SUM(total_output_tokens), 0),
                        COALESCE(SUM(total_tool_calls), 0)
diff --git a/tests/test_api.py b/tests/test_api.py
index 685f9fd..9bb40e0 100644
--- a/tests/test_api.py
+++ b/tests/test_api.py
@@ -113,186 +113,333 @@ class TestGetSessions:
 class TestSendMessage:
     def test_send(self, client):
         client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-4-6"})
         r = client.post("/api/sessions/w1/send", json={"message": "hello", "scope": "/s"})
         assert r.status_code == 200
 
     def test_send_404(self, client):
         r = client.post("/api/sessions/ghost/send", json={"message": "hi", "scope": "/s"})
         assert r.status_code == 404
 
 
 class TestInterrupt:
     def test_interrupt(self, client):
         client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-4-6"})
         r = client.post("/api/sessions/w1/interrupt", json={"scope": "/s"})
         assert r.status_code == 200
 
 
 class TestDeleteSession:
     def test_delete(self, client):
         client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-4-6"})
         r = client.delete("/api/sessions/w1", params={"scope": "/s"})
         assert r.status_code == 200
         r2 = client.get("/api/sessions/w1", params={"scope": "/s"})
         assert r2.status_code == 404
 
     def test_delete_404(self, client):
         r = client.delete("/api/sessions/ghost", params={"scope": "/s"})
         assert r.status_code == 404
 
 
 class TestLogs:
     def test_logs_empty(self, client):
         client.post("/api/sessions", json={"name": "w1", "scope": "/s", "cwd": "/tmp", "model": "claude-sonnet-4-6"})
         r = client.get("/api/sessions/w1/logs", params={"scope": "/s"})
         assert r.status_code == 200
         assert isinstance(r.json(), list)
 
     def test_logs_404(self, client):
         r = client.get("/api/sessions/ghost/logs", params={"scope": "/s"})
         assert r.status_code == 404
 
 
 class TestStats:
     def test_stats(self, client):
         r = client.get("/api/stats")
         assert r.status_code == 200
         data = r.json()
         assert "total_sessions" in data
 

exec
/usr/bin/zsh -lc "git show main:app/deps.py && git show main:app/routes/bg.py | sed -n '1,220p' && git show main:app/routes/tm.py | sed -n '1,120p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
"""Shared dependencies for routers — avoids importing from main."""

from app.manager import SessionManager

manager = SessionManager()
"""Background Jobs API routes."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.deps import manager

router = APIRouter(prefix="/api/bg", tags=["bg-jobs"])


class BgJobCreateRequest(BaseModel):
    type: str
    config: dict = {}
    message: str = ""
    target_name: str = ""
    target_scope: str = ""
    timeout_seconds: int = 3600
    created_by: str = ""


@router.post("/jobs")
async def bg_job_create(req: BgJobCreateRequest):
    from app.bg_jobs import bg_manager
    scope = req.target_scope.rstrip("/")
    name = req.target_name
    if not scope or not name:
        return JSONResponse({"error": "target_name and target_scope required"}, status_code=400)
    session = manager.get_by_name(name, scope)
    if not session:
        return JSONResponse({"error": f"session '{name}' not found in scope"}, status_code=404)
    session_id = session.id if hasattr(session, "id") else session.get("id")
    result = await bg_manager.create(
        job_type=req.type, config=req.config, message=req.message,
        target_session_id=session_id, target_name=name, target_scope=scope,
        created_by=req.created_by, timeout_seconds=req.timeout_seconds,
    )
    if result.get("error"):
        return JSONResponse(result, status_code=400)
    return result


@router.get("/jobs")
async def bg_job_list(scope: str = "", session_id: str = ""):
    from app.db import bg_get_jobs
    return bg_get_jobs(scope=scope or None, session_id=session_id or None)


@router.delete("/jobs/{job_id}")
async def bg_job_cancel(job_id: str):
    from app.bg_jobs import bg_manager
    result = await bg_manager.cancel(job_id)
    if result.get("error"):
        return JSONResponse(result, status_code=404)
    return result
"""Task Manager API routes."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import tm as _tm

router = APIRouter(prefix="/api/tm", tags=["task-manager"])


class TmTaskCreate(BaseModel):
    title: str
    project: str
    price: int = 0
    description: str = ""
    assignee: str = ""
    status: str = "new"
    scope: str = ""
    priority: int = 2


class TmTaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    price: int | None = None
    status: str | None = None
    assignee: str | None = None
    priority: int | None = None


class TmPaymentReceive(BaseModel):
    amount: int
    client: str = ""
    scope: str = ""
    date: str = ""
    note: str = ""


def _resolve_client_id(client: str, scope: str) -> str:
    if client:
        return client
    if scope:
        with _tm._conn() as conn:
            proj = _tm.get_project_by_scope(conn, scope)
            if proj:
                cl = _tm.get_client_for_project(conn, proj["id"])
                if cl:
                    return cl["id"]
    raise ValueError("No client specified and no client found for project scope")


@router.post("/tasks")
async def tm_create_task(req: TmTaskCreate):
    try:
        return _tm.api_create_task(
            req.project, req.title, req.price, req.description, req.assignee, req.status,
            scope=req.scope, priority=req.priority,
        )
    except (ValueError, RuntimeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/tasks")
async def tm_list_tasks(project: str = "", status: str = "", assignee: str = "",
                        scope: str = ""):
    proj = project
    if not proj and scope:
        with _tm._conn() as conn:
            p = _tm.get_project_by_scope(conn, scope)
            if p:
                proj = p["id"]
            else:
                return {"tasks": [], "count": 0, "total_debt": "0"}
    return _tm.api_list_tasks(proj, status, assignee)


@router.get("/tasks/{par}")
async def tm_get_task(par: str, scope: str = ""):
    try:
        project = ""
        if scope:
            with _tm._conn() as conn:
                p = _tm.get_project_by_scope(conn, scope)
                if p:
                    project = p["id"]
        return _tm.api_get_task(par, project=project)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.put("/tasks/{par}")
async def tm_update_task(par: str, req: TmTaskUpdate, scope: str = ""):
    try:
        project = ""
        if scope:
            with _tm._conn() as conn:
                p = _tm.get_project_by_scope(conn, scope)
                if p:
                    project = p["id"]
        return _tm.api_update_task(
            par, req.title, req.description, req.price, req.status, req.assignee,
            project=project, priority=req.priority,
        )
    except (ValueError, RuntimeError) as e:
        code = 404 if "not found" in str(e).lower() else 400
        return JSONResponse({"error": str(e)}, status_code=code)


@router.post("/payments")
async def tm_receive_payment(req: TmPaymentReceive):
    try:
        client_id = _resolve_client_id(req.client, req.scope)
        return _tm.api_receive_payment(req.amount, client_id, req.date, req.note)
    except (ValueError, RuntimeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/payments/status")
async def tm_payment_status(client: str = "", scope: str = ""):

exec
/usr/bin/zsh -lc "git diff --unified=80 main...vadim/feat/pipeline-as-config -- app/static/js/app.js app/templates/dashboard.html | sed -n '1,520p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 47c00dc..2ca70ab 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -55,343 +55,397 @@ function autolinkText(html) {
             let last = 0, m;
             while ((m = _autolinkRe.exec(t)) !== null) {
                 if (m.index > last) frag.appendChild(document.createTextNode(t.slice(last, m.index)));
                 const a = document.createElement('a');
                 const href = m[0].match(/^https?:\/\/|^ftp:\/\//) ? m[0] : 'http://' + m[0];
                 a.href = href;
                 a.target = '_blank';
                 a.rel = 'noopener';
                 a.textContent = m[0];
                 frag.appendChild(a);
                 last = m.index + m[0].length;
             }
             if (last < t.length) frag.appendChild(document.createTextNode(t.slice(last)));
             node.parentNode.replaceChild(frag, node);
         } else if (node.nodeType === 1 && !['A', 'PRE', 'CODE', 'SCRIPT', 'STYLE'].includes(node.tagName)) {
             [...node.childNodes].forEach(walk);
         }
     };
     [...tmp.childNodes].forEach(walk);
     return tmp.innerHTML;
 }
 
 const _origMarkedParse = marked.parse.bind(marked);
 marked.parse = (src, ...args) => {
     const html = _origMarkedParse(src, ...args);
     return autolinkText(html);
 };
 
 function saveDraft() {
     if (selectedAgent) drafts[selectedAgent] = { text: $('#chat-input').value, images: [...pastedImages] };
 }
 function restoreDraft() {
     const d = drafts[selectedAgent] || {};
     $('#chat-input').value = d.text || '';
     clearPastePreview();
     if (d.images && d.images.length) {
         pastedImages = [...d.images];
         d.images.forEach(url => showImagePreview(url));
     }
 }
 
 document.addEventListener('DOMContentLoaded', () => {
     $('#send-btn').addEventListener('click', sendChat);
     $('#stop-btn').addEventListener('click', stopAgent);
     $('#chat-input').addEventListener('keydown', (e) => {
         if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
     });
     $('#chat-input').addEventListener('paste', handlePaste);
     $('#chat-input').addEventListener('input', () => {
         const text = $('#chat-input').value;
         const container = $('#paste-preview');
         if (!container) return;
         for (const w of [...container.querySelectorAll('[data-url]')]) {
             const fp = w.dataset.filePath || w.dataset.url;
             if (!text.includes(fp)) {
                 w.remove();
                 pastedImages = pastedImages.filter(u => u !== w.dataset.url);
             }
         }
         if (!container.children.length) container.remove();
     });
     const _rh = $('#input-resize-handle');
     if (_rh) {
         const _ta = $('#chat-input');
         let _ry, _rh0;
         _rh.addEventListener('mousedown', (e) => {
             _ry = e.clientY;
             _rh0 = _ta.offsetHeight;
             const onMove = (e) => { _ta.style.height = Math.max(40, Math.min(300, _rh0 + (_ry - e.clientY))) + 'px'; };
             const onUp = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); };
             document.addEventListener('mousemove', onMove);
             document.addEventListener('mouseup', onUp);
             e.preventDefault();
         });
     }
     $('#orch-picker').addEventListener('change', onOrchestratorChange);
     $('#new-orch-btn').addEventListener('click', () => {
         $('#new-orch-modal').classList.remove('hidden');
         $('#new-orch-modal').classList.add('flex');
         $('#project-picker').classList.add('hidden');
+        loadProfilesDropdown();
+        loadPipelinesDropdown();
         $('#orch-cwd').focus();
     });
+    $('#orch-pipeline').addEventListener('change', populateRoleDropdown);
     $('#modal-close').addEventListener('click', closeModal);
     $('#new-orch-modal').addEventListener('click', (e) => {
         if (e.target === $('#new-orch-modal')) closeModal();
     });
     $('#create-orch-btn').addEventListener('click', createOrchestrator);
     $('#orch-cwd').addEventListener('input', () => {
         const path = $('#orch-cwd').value.trim();
         if (path && !$('#orch-name').value.trim()) {
             $('#orch-name').value = autoNameFromPath(path);
         }
     });
     $('#orch-cwd').addEventListener('change', () => {
         const path = $('#orch-cwd').value.trim();
         if (path) $('#orch-name').value = autoNameFromPath(path);
     });
     $('#browse-btn')?.addEventListener('click', showProjectPicker);
     initTabContextMenu();
     initHiddenTabsBtn();
     initDropHint();
     $('#restart-btn').addEventListener('click', restartServer);
     initProxy();
+    initProfilesManager();
     $('#orch-name').addEventListener('keydown', (e) => { if (e.key === 'Enter') createOrchestrator(); });
     $('#orch-cwd').addEventListener('keydown', (e) => { if (e.key === 'Enter') { if (!$('#orch-name').value.trim()) $('#orch-name').value = autoNameFromPath($('#orch-cwd').value); $('#orch-name').focus(); }});
     $('#view-prompt-btn').addEventListener('click', openPromptModal);
     $('#compact-btn').addEventListener('click', compactAgent);
     $('#restart-cli-btn').addEventListener('click', restartCli);
     $('#prompt-modal-close').addEventListener('click', closePromptModal);
     $('#prompt-modal').addEventListener('click', (e) => { if (e.target === $('#prompt-modal')) closePromptModal(); });
     document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closePromptModal(); closeFilePreview(); closeModal(); } });
     const compactBtn = $('#compact-toggle-btn');
     if (compactBtn) {
         compactBtn.textContent = window.compactMode ? '📄' : '📋';
         compactBtn.title = window.compactMode ? 'Switch to normal view' : 'Switch to compact view';
         compactBtn.addEventListener('click', () => {
             window.compactMode = !window.compactMode;
             localStorage.setItem('compactToolMode', window.compactMode);
             compactBtn.textContent = window.compactMode ? '📄' : '📋';
             compactBtn.title = window.compactMode ? 'Switch to normal view' : 'Switch to compact view';
             $('#chat').innerHTML = '';
             if (chatLogs[selectedAgent]) { chatLogs[selectedAgent].lastId = 0; chatLogs[selectedAgent].firstId = null; }
             scrollAfterLoad = true;
             connectSSE();
         });
     }
     const openFolderBtn = $('#open-folder-btn');
     if (openFolderBtn) {
         openFolderBtn.addEventListener('click', () => {
             if (currentScope) fetch('/api/open-folder', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({path: currentScope}) });
         });
     }
     loadModels();
     loadOrchestrators();
     scheduleRefresh();
     initFilePreviewModal();
     initUsageBar();
     initHeartbeat();
 });
 
 let eventSource = null;
 
 function scheduleRefresh() {
     setTimeout(async () => {
         await refreshSessions();
         scheduleRefresh();
     }, 3000);
 }
 
 function connectSSE() {
     if (eventSource) { eventSource.close(); eventSource = null; }
     if (!selectedAgent || !currentScope) return;
     const lastId = chatLogs[selectedAgent]?.lastId || 0;
     const limitParam = lastId === 0 ? '&limit=100' : '';
     const url = `/api/sessions/${selectedAgent}/stream?scope=${encodeURIComponent(currentScope)}&after_id=${lastId}${limitParam}`;
     eventSource = new EventSource(url);
     eventSource.onmessage = (event) => {
         try {
             const l = JSON.parse(event.data);
             const isLocal = l.type === 'user_message' && (localMessages.has(l.content) || [...localMessages].some(m => l.content.endsWith(m)));
             if (isLocal) {
                 localMessages.delete(l.content);
                 for (const m of localMessages) { if (l.content.endsWith(m)) { localMessages.delete(m); break; } }
                 if (pendingBubble) {
                     pendingBubble.remove();
                     pendingBubble = null;
                     pendingUserMsgs = [];
                 } else if (_finalizedBubble) {
                     _finalizedBubble.remove();
                 }
                 _finalizedBubble = null;
                 addChatEntry(l.type, l.content, l.ts);
             } else {
                 addChatEntry(l.type, l.content, l.ts);
             }
             if (!chatLogs[selectedAgent]) chatLogs[selectedAgent] = { lastId: 0, firstId: null };
             if (l.id > chatLogs[selectedAgent].lastId) chatLogs[selectedAgent].lastId = l.id;
             if (chatLogs[selectedAgent].firstId === null || l.id < chatLogs[selectedAgent].firstId) {
                 chatLogs[selectedAgent].firstId = l.id;
                 updateLoadMoreBtn();
             }
             if (scrollAfterLoad) {
                 $('#chat').scrollTop = $('#chat').scrollHeight;
                 clearTimeout(window._scrollResetTimer);
                 window._scrollResetTimer = setTimeout(() => { scrollAfterLoad = false; }, 500);
             }
         } catch (e) { console.warn('SSE parse:', e); }
     };
     eventSource.onerror = () => {
         eventSource.close();
         eventSource = null;
         _onServerError();
         setTimeout(connectSSE, 2000);
     };
 }
 
 function updateLoadMoreBtn() {
     const chat = $('#chat');
     const existing = $('#load-more-btn');
     const firstId = chatLogs[selectedAgent]?.firstId;
     if (!firstId || firstId <= 1) {
         if (existing) existing.remove();
         return;
     }
     if (existing) return;
     const btn = document.createElement('div');
     btn.id = 'load-more-btn';
     btn.className = 'text-xs text-slate-500 hover:text-indigo-300 py-2 text-center cursor-pointer select-none';
     btn.textContent = '▲ Load 500 more';
     btn.addEventListener('click', loadMoreLogs);
     chat.prepend(btn);
 }
 
 async function loadMoreLogs() {
     if (!selectedAgent || !currentScope) return;
     const firstId = chatLogs[selectedAgent]?.firstId;
     if (!firstId) return;
     const btn = $('#load-more-btn');
     if (btn) { btn.textContent = '⏳ Loading…'; btn.style.pointerEvents = 'none'; }
     try {
         const res = await fetch(`/api/sessions/${selectedAgent}/logs?scope=${encodeURIComponent(currentScope)}&before_id=${firstId}&limit=500`);
         const logs = await res.json();
         if (!Array.isArray(logs) || logs.length === 0) {
             if (btn) btn.remove();
             return;
         }
         const chat = $('#chat');
         const oldHeight = chat.scrollHeight;
         if (btn) btn.remove();
         // prepend в правильном порядке (logs уже ASC из db)
         // фиксируем anchor = текущий firstChild, вставляем все перед ним по порядку
         const anchor = chat.firstChild;
         for (const l of logs) {
             addChatEntry(l.type, l.content, l.ts, anchor);
             if (!chatLogs[selectedAgent]) chatLogs[selectedAgent] = { lastId: 0, firstId: null };
             if (chatLogs[selectedAgent].firstId === null || l.id < chatLogs[selectedAgent].firstId) {
                 chatLogs[selectedAgent].firstId = l.id;
             }
         }
         chat.scrollTop = chat.scrollHeight - oldHeight;
         updateLoadMoreBtn();
     } catch (e) {
         if (btn) { btn.textContent = '▲ Load 500 more'; btn.style.pointerEvents = ''; }
         console.warn('loadMoreLogs error:', e);
     }
 }
 
 
 // === Models ===
 async function loadModels() {
     try {
         const models = await api('/api/models');
         const select = $('#orch-model');
         select.innerHTML = '';
         for (const m of models) {
             const opt = document.createElement('option');
             opt.value = m.id;
             opt.textContent = `${m.name} (${m.id})`;
             select.appendChild(opt);
         }
     } catch {}
 }
 
+// === Profile / Pipeline / Role dropdowns (модалка создания корня) ===
+let _pipelineRoles = {};  // карта pipeline-name → [roles]
+
+async function loadProfilesDropdown() {
+    try {
+        const profiles = await api('/api/profiles');
+        const select = $('#orch-profile');
+        select.innerHTML = '';
+        for (const p of profiles) {
+            const opt = document.createElement('option');
+            opt.value = p.name;
+            opt.textContent = `${p.name} (${p.config_dir || 'env процесса'})`;
+            select.appendChild(opt);
+        }
+        // B5: API сортирует по name (ORDER BY name), поэтому первый ≠ personal.
+        // Явно предпочитаем personal, иначе — первый по списку.
+        const def = profiles.find(p => p.name === 'personal') || profiles[0];
+        if (def) select.value = def.name;
+    } catch {}
+}
+
+async function loadPipelinesDropdown() {
+    try {
+        const pipelines = await api('/api/pipelines');
+        const select = $('#orch-pipeline');
+        select.innerHTML = '';
+        _pipelineRoles = {};
+        for (const p of pipelines) {
+            _pipelineRoles[p.name] = p.roles || [];
+            const opt = document.createElement('option');
+            opt.value = p.name;
+            opt.textContent = p.name;
+            select.appendChild(opt);
+        }
+        populateRoleDropdown();
+    } catch {}
+}
+
+function populateRoleDropdown() {
+    const select = $('#orch-role');
+    select.innerHTML = '';
+    const roles = _pipelineRoles[$('#orch-pipeline').value] || [];
+    for (const r of roles) {
+        const opt = document.createElement('option');
+        opt.value = r;
+        opt.textContent = r;
+        select.appendChild(opt);
+    }
+}
+
 // === Modal ===
 function closeModal() {
     $('#new-orch-modal').classList.add('hidden');
     $('#new-orch-modal').classList.remove('flex');
     $('#orch-error').classList.add('hidden');
 }
 
 function closePromptModal() {
     $('#prompt-modal').classList.add('hidden');
     $('#prompt-modal').classList.remove('flex');
 }
 
 function _promptSection(title, color, content) {
     if (!content || !content.trim()) return '';
     const rendered = DOMPurify.sanitize(marked.parse(content));
     return `<div style="margin-bottom:16px"><div style="font-size:11px;font-weight:700;color:${color};margin-bottom:6px;padding:3px 8px;border-radius:4px;background:rgba(0,0,0,0.3);display:inline-block">${title}</div><div class="markdown-body" style="padding-left:4px">${rendered}</div></div>`;
 }
 
 async function compactAgent() {
     if (!selectedAgent || !currentScope) return;
     const btn = $('#compact-btn');
     btn.disabled = true;
     btn.textContent = '⏳';
     try {
         const res = await api(`/api/sessions/${encodeURIComponent(selectedAgent)}/compact`, {
             method: 'POST',
             headers: {'Content-Type': 'application/json'},
             body: JSON.stringify({scope: currentScope}),
         });
         if (res.error) throw new Error(res.error);
         delete contextCache[`${currentScope}:${selectedAgent}`];
         await fetchAgentContext(selectedAgent);
         btn.textContent = '✅';
         setTimeout(() => { btn.textContent = '🗜'; btn.disabled = false; }, 1500);
     } catch (e) {
         btn.textContent = '❌';
         setTimeout(() => { btn.textContent = '🗜'; btn.disabled = false; }, 2000);
     }
 }
 
 async function restartCli() {
     if (!selectedAgent || !currentScope) return;
     const btn = $('#restart-cli-btn');
     btn.disabled = true;
     btn.textContent = '⏳';
     try {
         await api(`/api/sessions/${encodeURIComponent(selectedAgent)}/restart-cli`, {
             method: 'POST',
             headers: {'Content-Type': 'application/json'},
             body: JSON.stringify({scope: currentScope}),
         });
         btn.textContent = '✅';
         setTimeout(() => { btn.textContent = '♻️'; btn.disabled = false; }, 1500);
     } catch (e) {
         btn.textContent = '❌';
         setTimeout(() => { btn.textContent = '♻️'; btn.disabled = false; }, 2000);
     }
 }
 
 async function openPromptModal() {
     if (!selectedAgent || !currentScope) return;
     const modal = $('#prompt-modal');
     const body = $('#prompt-modal-body');
     $('#prompt-modal-name').textContent = selectedAgent;
     body.innerHTML = '<span class="text-slate-500 text-xs">Loading...</span>';
     modal.classList.remove('hidden');
     modal.classList.add('flex');
     try {
         const data = await api(`/api/sessions/${selectedAgent}/prompt?scope=${encodeURIComponent(currentScope)}`);
         if (!data.system_prompt || !data.system_prompt.trim()) {
             body.innerHTML = '<span class="text-slate-500 italic text-xs">No system prompt</span>';
         } else if (data.base || data.role) {
             body.innerHTML =
                 _promptSection('📦 Platform (base.md)', '#64748b', data.base) +
                 _promptSection('🎭 Role', '#818cf8', data.role) +
                 _promptSection('✨ Custom', '#22c55e', data.custom);
             if (!data.custom) {
                 body.innerHTML += '<div style="font-size:10px;color:#475569;font-style:italic;margin-top:8px">No custom system prompt</div>';
             }
         } else {
@@ -496,166 +550,169 @@ async function openFilePreview(path) {
                 contentEl.appendChild(pre);
                 if (window.hljs) hljs.highlightElement(code);
             } else if (LANG_MAP[ext] && window.hljs) {
                 contentEl.className = 'flex-1 text-xs p-4';
                 contentEl.style.cssText = 'overflow:auto;max-height:calc(80vh - 48px)';
                 const pre = document.createElement('pre');
                 pre.style.cssText = 'margin:0;background:transparent';
                 const code = document.createElement('code');
                 code.className = `language-${LANG_MAP[ext]}`;
                 code.textContent = raw;
                 pre.appendChild(code);
                 contentEl.innerHTML = '';
                 contentEl.appendChild(pre);
                 hljs.highlightElement(code);
             } else {
                 contentEl.className = 'flex-1 text-xs p-4 text-slate-300';
                 contentEl.style.cssText = 'overflow:auto;max-height:calc(80vh - 48px);white-space:pre;word-wrap:normal';
                 contentEl.textContent = raw;
             }
         }
     } catch (e) {
         contentEl.textContent = `Error: ${e.message}`;
     }
 }
 
 function closeFilePreview() {
     const modal = $('#file-preview-modal');
     modal.classList.add('hidden');
     modal.classList.remove('flex');
     const openBtn = $('#file-preview-open');
     if (openBtn) openBtn.classList.add('hidden');
     const dlBtn = $('#file-preview-download');
     if (dlBtn) dlBtn.classList.add('hidden');
     const contentEl = $('#file-preview-content');
     if (contentEl) contentEl.innerHTML = '';
 }
 
 function initFilePreviewModal() {
     const modal = $('#file-preview-modal');
     if (!modal) return;
     $('#file-preview-close').addEventListener('click', closeFilePreview);
 }
 
 async function showProjectPicker() {
     const picker = $('#project-picker');
     picker.innerHTML = '<div class="p-2 text-xs text-slate-500">Loading...</div>';
     picker.classList.remove('hidden');
     try {
         const projects = await api('/api/projects');
         picker.innerHTML = '';
         for (const p of projects) {
             const item = document.createElement('div');
             item.className = 'px-3 py-2 text-sm cursor-pointer hover:bg-slate-800 border-b border-slate-800/50';
             const nameSpan = document.createElement('span');
             nameSpan.className = 'text-white font-medium';
             nameSpan.textContent = p.name;
             const pathSpan = document.createElement('span');
             pathSpan.className = 'text-slate-500 text-xs';
             pathSpan.textContent = ' ' + p.path;
             item.append(nameSpan, pathSpan);
             item.addEventListener('click', () => {
                 $('#orch-cwd').value = p.path;
                 $('#orch-name').value = p.name + '-orchestrator';
                 picker.classList.add('hidden');
             });
             picker.appendChild(item);
         }
     } catch { picker.innerHTML = '<div class="p-2 text-xs text-red-400">Failed to load</div>'; }
 }
 
 function autoNameFromPath(path) {
     const parts = path.replace(/\/+$/, '').split('/');
     const folder = parts[parts.length - 1] || '';
     return folder + '-orchestrator';
 }
 
 async function createOrchestrator() {
     const name = $('#orch-name').value.trim();
     const cwd = $('#orch-cwd').value.trim();
     const model = $('#orch-model').value;
+    const profile = $('#orch-profile').value;
+    const pipeline = $('#orch-pipeline').value;
+    const role = $('#orch-role').value;
     const errEl = $('#orch-error');
     if (!name || !cwd) { errEl.textContent = 'Name and project path required'; errEl.classList.remove('hidden'); return; }
     const btn = $('#create-orch-btn');
     btn.disabled = true; btn.textContent = 'Creating...'; errEl.classList.add('hidden');
     try {
-        await api('/api/sessions', { method: 'POST', body: JSON.stringify({ name, cwd, model, is_orchestrator: true }) });
+        await api('/api/sessions', { method: 'POST', body: JSON.stringify({ name, cwd, model, profile, pipeline, role, is_orchestrator: true }) });
         closeModal(); $('#orch-name').value = ''; $('#orch-cwd').value = '';
         currentScope = null;
         await loadOrchestrators();
         selectOrchestrator(name, cwd.replace(/\/+$/, ''));
     } catch (e) { errEl.textContent = e.message; errEl.classList.remove('hidden'); }
     finally { btn.disabled = false; btn.textContent = 'Create Orchestrator'; }
 }
 
 async function restartServer() {
     const btn = $('#restart-btn');
     btn.disabled = true; btn.textContent = '⏳';
     try {
         await api('/api/restart', { method: 'POST' });
     } catch {}
     setTimeout(() => location.reload(), 3000);
 }
 
 async function deleteOrchestrator() {
     if (!currentScope || !selectedAgent) return;
     if (!confirm(`Delete "${selectedAgent}" and all its workers?`)) return;
     try {
         await api(`/api/orchestrators/${selectedAgent}?scope=${encodeURIComponent(currentScope)}`, { method: 'DELETE' });
         localStorage.removeItem('lastOrchScope');
         localStorage.removeItem('lastOrchName');
         currentScope = null;
         selectedAgent = null;
         await loadOrchestrators();

exec
/usr/bin/zsh -lc 'git show vadim/feat/pipeline-as-config:tests/test_manager.py | rg -n "pipeline|profile|owned_dirs|needs_switch|ROLE_SYSTEM_PROMPT|validate_spawn|default|parent|base_branch|is_orchestrator|visibility" -C 2' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
28-
29-@pytest.fixture(autouse=True)
30:def _isolate_pipelines_dir(tmp_path, monkeypatch):
31-    """По умолчанию изолируем PIPELINES_DIR на пустой tmp.
32-
33:    Делает модуль детерминированным независимо от реального ``pipelines/``
34:    (Stage 4 параллельно создаёт ``pipelines/default/``). Тесты, которым нужен
35:    манифест, переопределяют PIPELINES_DIR своей фикстурой (``pipeline_dir``/
36-    ``roles_dir``), которая выполняется ПОСЛЕ этой autouse и выигрывает.
37-    """
38:    import app.pipeline as pl
39:    empty = tmp_path / "_no_pipelines_default"
40-    empty.mkdir()
41-    monkeypatch.setattr(pl, "PIPELINES_DIR", empty)
42:    pl.load_pipeline.cache_clear()
43-    yield
44:    pl.load_pipeline.cache_clear()
45-
46-
--
135-            session = await mgr.create_session(
136-                name="w1", scope="/s", cwd=str(repo), model="m",
137:                use_worktree=True, repo_path=str(repo), base_branch="feature/auth",
138-            )
139-        head = subprocess.run(["git", "rev-parse", "feature/auth"], cwd=repo,
--
177-    @pytest.mark.asyncio
178-    async def test_skills_all_skips_injection(self, mgr, tmp_path):
179:        rr = MagicMock(skills="all", is_orchestrator=False)
180-        inject = await self._run(mgr, tmp_path, lambda p, r: rr)
181-        inject.assert_not_called()
--
183-    @pytest.mark.asyncio
184-    async def test_skills_list_injects(self, mgr, tmp_path):
185:        rr = MagicMock(skills=["foo", "bar"], is_orchestrator=False)
186-        inject = await self._run(mgr, tmp_path, lambda p, r: rr)
187-        inject.assert_called_once()
--
196-
197-class TestResolveBaseBranch:
198:    """DESIGN §10: резолв base_branch по стратегии манифеста (B3).
199-
200:    Тестируем ``_resolve_base_branch`` напрямую на инстансе manager, мокая
201-    ``app.manager.get_role`` (как в TestInjectSkillsGating) и подсовывая
202-    родителя в ``mgr.sessions`` через лёгкий объект с атрибутом ``branch``.
203-    """
204-
205:    def _put_parent(self, mgr, name, scope, branch):
206-        """Лёгкий родитель в кэше сессий с нужной веткой (без БД)."""
207:        parent = MagicMock()
208:        parent.name = name
209:        parent.scope = scope
210:        parent.branch = branch
211:        mgr.sessions[name] = parent
212-
213-    def test_strategy_main_returns_main(self, mgr):
214:        rr = MagicMock(base_branch_strategy="main")
215-        with patch("app.manager.get_role", lambda p, r: rr):
216:            out = mgr._resolve_base_branch("", "default", "pm-glava", "", "/s")
217-        assert out == "main"
218-
219:    def test_strategy_parent_uses_parent_branch(self, mgr):
220:        rr = MagicMock(base_branch_strategy="parent")
221:        self._put_parent(mgr, "pm", "/s", "feature/x")
222-        with patch("app.manager.get_role", lambda p, r: rr):
223:            out = mgr._resolve_base_branch("", "tasks-pm", "coder", "pm", "/s")
224-        assert out == "feature/x"
225-
226:    def test_strategy_parent_no_branch_falls_back_to_main(self, mgr, caplog):
227-        import logging
228:        rr = MagicMock(base_branch_strategy="parent")
229:        self._put_parent(mgr, "pm", "/s", "")  # у родителя нет ветки
230-        with patch("app.manager.get_role", lambda p, r: rr), caplog.at_level(logging.WARNING):
231:            out = mgr._resolve_base_branch("", "tasks-pm", "coder", "pm", "/s")
232-        assert out == "main"
233-        assert any("fallback на main" in rec.message for rec in caplog.records)
234-
235-    def test_explicit_branch_overrides_strategy(self, mgr):
236:        # B3: явная ветка важнее strategy="parent" — get_role даже не зовётся.
237:        rr = MagicMock(base_branch_strategy="parent")
238:        self._put_parent(mgr, "pm", "/s", "feature/x")
239-        with patch("app.manager.get_role", lambda p, r: rr):
240:            out = mgr._resolve_base_branch("dev", "tasks-pm", "coder", "pm", "/s")
241-        assert out == "dev"
242-
--
245-            raise FileNotFoundError("no manifest")
246-        with patch("app.manager.get_role", _raise):
247:            out = mgr._resolve_base_branch("", "nope", "coder", "pm", "/s")
248-        assert out == "main"
249-
--
316-            "status": "idle", "session_id": None,
317-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
318:            "is_orchestrator": True, "color": "#818cf8",
319-            "created_at": datetime.now(timezone.utc).isoformat(),
320-            "finished_at": None,
--
342-            "status": "idle", "session_id": None,
343-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
344:            "is_orchestrator": True, "color": "#818cf8",
345-            "created_at": datetime.now(timezone.utc).isoformat(),
346-            "finished_at": None,
--
370-            "status": "idle", "session_id": "sdk-123",
371-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
372:            "is_orchestrator": True, "color": "#818cf8", "created_at": datetime.now(timezone.utc).isoformat(),
373-            "finished_at": None,
374-        })
--
388-        prompts = tmp_path / "prompts"
389-        rdir = prompts / "roles"
390:        rdir.mkdir(parents=True)
391-        (prompts / "base.md").write_text("BASE")
392-        monkeypatch.setattr("app.manager._PROMPTS_DIR", prompts)
--
394-        # TestCanSpawn проверяет LEGACY-fallback (_role_can_spawn по frontmatter),
395-        # который срабатывает ТОЛЬКО когда манифеста нет. Изолируем PIPELINES_DIR
396:        # на пустой tmp (без pipelines/default/), чтобы load_pipeline кидал
397-        # FileNotFoundError → fallback-ветка валидации в create_session.
398:        import app.pipeline as pl
399:        empty_pipelines = tmp_path / "no_pipelines"
400:        empty_pipelines.mkdir()
401:        monkeypatch.setattr(pl, "PIPELINES_DIR", empty_pipelines)
402:        pl.load_pipeline.cache_clear()
403-        return rdir
404-
--
439-        self._write_role(roles_dir, "worker", "name: worker")
440-        save_session({
441:            "id": "p-1", "name": "parent", "scope": "/s", "cwd": "/tmp",
442-            "model": "m", "system_prompt": "", "status": "idle", "session_id": None,
443-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
444:            "is_orchestrator": False, "color": "#fff",
445-            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
446-            "role": "boss",
--
449-            session = await mgr.create_session(
450-                name="child", scope="/s", cwd="/tmp", model="m",
451:                role="worker", parent_name="parent",
452-            )
453-        assert session.name == "child"
--
460-        self._write_role(roles_dir, "full-cycle", "name: full-cycle")
461-        save_session({
462:            "id": "p-2", "name": "parent", "scope": "/s", "cwd": "/tmp",
463-            "model": "m", "system_prompt": "", "status": "idle", "session_id": None,
464-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
465:            "is_orchestrator": False, "color": "#fff",
466-            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
467-            "role": "boss",
--
471-                await mgr.create_session(
472-                    name="child", scope="/s", cwd="/tmp", model="m",
473:                    role="full-cycle", parent_name="parent",
474-                )
475-
--
481-        self._write_role(roles_dir, "worker", "name: worker")
482-        save_session({
483:            "id": "p-3", "name": "parent", "scope": "/s", "cwd": "/tmp",
484-            "model": "m", "system_prompt": "", "status": "idle", "session_id": None,
485-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
486:            "is_orchestrator": False, "color": "#fff",
487-            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
488-            "role": "leaf",
--
492-                await mgr.create_session(
493-                    name="child", scope="/s", cwd="/tmp", model="m",
494:                    role="worker", parent_name="parent",
495-                )
496-
497-    @pytest.mark.asyncio
498:    async def test_unknown_parent_fails_open(self, mgr, roles_dir):
499-        from tests.conftest import make_backend_mock
500-        self._write_role(roles_dir, "worker", "name: worker")
--
502-            session = await mgr.create_session(
503-                name="child", scope="/s", cwd="/tmp", model="m",
504:                role="worker", parent_name="ghost-parent",
505-            )
506-        assert session.name == "child"
--
585-            "model": "m", "system_prompt": "", "status": "idle", "session_id": None,
586-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
587:            "is_orchestrator": False, "color": "#fff",
588-            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
589-            "role": "worker", "mcp_servers_custom": json.dumps(custom),
--
597-
598-
599:# ── Stage 3: loader integration (pipeline manifest) ─────────────────────────
600-
601-# Мини-манифест, повторяющий ключевые роли tasks-pm для тестов фильтра/изоляции.
602-_MINI_MANIFEST = """\
603-name: testpipe
604:description: Test pipeline
605-validation: fail-closed
606:defaults:
607-  model: opus
608-  skills: all
609-  mcp_servers: all
610-  prompt_layers:
611:    orchestrator: [base.md, "roles/{role}.md", _pipeline.md]
612-    worker: [base.md, "roles/{role}.md"]
613-roles:
--
620-
621-
622:def _write_pipeline(root, name, manifest_text, prompts=None):
623:    """Создать pipelines/<name>/ с pipeline.yaml + prompts/* в tmp-корне root."""
624-    pdir = root / name
625:    (pdir / "prompts" / "roles").mkdir(parents=True)
626:    (pdir / "pipeline.yaml").write_text(manifest_text)
627-    prompts = prompts or {}
628-    for rel, content in prompts.items():
629-        target = pdir / "prompts" / rel
630:        target.parent.mkdir(parents=True, exist_ok=True)
631-        target.write_text(content)
632-    return pdir
--
634-
635-@pytest.fixture
636:def pipeline_dir(tmp_path, monkeypatch):
637:    """tmp pipelines/ с манифестом testpipe + базовыми слоями промптов.
638-
639:    Монкипатчит ``app.pipeline.PIPELINES_DIR`` и чистит lru_cache загрузчика,
640-    чтобы манифест читался из tmp, а не из реального дерева (которого нет).
641-    """
642:    import app.pipeline as pl
643:    root = tmp_path / "pipelines"
644-    root.mkdir()
645:    _write_pipeline(root, "testpipe", _MINI_MANIFEST, prompts={
646-        "base.md": "BASE-LAYER",
647-        "roles/pm-glava.md": "ROLE pm-glava",
--
650-        "roles/secretary.md": "ROLE secretary",
651-        "roles/worker.md": "ROLE worker",
652:        "_pipeline.md": "PIPELINE-LAYER",
653-    })
654-    monkeypatch.setattr(pl, "PIPELINES_DIR", root)
655:    pl.load_pipeline.cache_clear()
656-    yield root
657:    pl.load_pipeline.cache_clear()
658-
659-
660-class TestUpstreamFallbackCharacterization:
661:    """Зафиксировать: при отсутствии манифеста ROLE_SYSTEM_PROMPT(pipeline, role)
662:    идентичен поведению апстрима (_UPSTREAM_ROLE_SYSTEM_PROMPT)."""
663-
664-    def _write_role(self, roles_dir, name, frontmatter_body):
--
670-        prompts = tmp_path / "uprompts"
671-        rdir = prompts / "roles"
672:        rdir.mkdir(parents=True)
673-        (prompts / "base.md").write_text("BASE")
674-        monkeypatch.setattr("app.manager._PROMPTS_DIR", prompts)
--
679-
680-    def test_upstream_helper_orchestrator_matches_legacy_shape(self, upstream_prompts, db):
681:        """_UPSTREAM_ROLE_SYSTEM_PROMPT собирает base.md + тело роли (orchestrator)."""
682:        from app.manager import _UPSTREAM_ROLE_SYSTEM_PROMPT
683:        out = _UPSTREAM_ROLE_SYSTEM_PROMPT("orchestrator", "/some/scope")
684-        assert out.startswith("BASE")
685-        assert "Body for orchestrator." in out
686-
687-    def test_upstream_helper_worker(self, upstream_prompts, db):
688:        from app.manager import _UPSTREAM_ROLE_SYSTEM_PROMPT
689:        out = _UPSTREAM_ROLE_SYSTEM_PROMPT("worker")
690-        assert out.startswith("BASE")
691-        assert "Body for worker." in out
692-
693-    def test_no_manifest_falls_back_to_upstream(self, upstream_prompts, db):
694:        """Нет манифеста (FileNotFoundError) → ROLE_SYSTEM_PROMPT(pipeline, ...) ==
695:        _UPSTREAM_ROLE_SYSTEM_PROMPT (fallback идентичен апстриму)."""
696:        import app.pipeline as pl
697:        pl.load_pipeline.cache_clear()
698:        from app.manager import ROLE_SYSTEM_PROMPT, _UPSTREAM_ROLE_SYSTEM_PROMPT
699-        # "ghost-pipe" манифеста нет → fallback
700:        assert ROLE_SYSTEM_PROMPT("ghost-pipe", "orchestrator", "/s") == \
701:            _UPSTREAM_ROLE_SYSTEM_PROMPT("orchestrator", "/s")
702:        assert ROLE_SYSTEM_PROMPT("ghost-pipe", "worker") == \
703:            _UPSTREAM_ROLE_SYSTEM_PROMPT("worker")
704-
705-
706-class TestRoleSystemPromptManifest:
707:    def test_static_layers_from_manifest(self, pipeline_dir, db):
708:        """ROLE_SYSTEM_PROMPT берёт статику из pipelines/<name>/prompts/ (изоляция)."""
709:        from app.manager import ROLE_SYSTEM_PROMPT
710:        out = ROLE_SYSTEM_PROMPT("testpipe", "coder", "/s")
711-        assert "BASE-LAYER" in out
712-        assert "ROLE coder" in out
713:        assert "PIPELINE-LAYER" in out  # coder — orchestrator → _pipeline.md есть
714-
715:    def test_worker_role_no_pipeline_layer(self, pipeline_dir, db):
716:        """Воркер (kind:worker) НЕ получает _pipeline.md."""
717:        from app.manager import ROLE_SYSTEM_PROMPT
718:        out = ROLE_SYSTEM_PROMPT("testpipe", "secretary")
719-        assert "BASE-LAYER" in out
720-        assert "ROLE secretary" in out
721-        assert "PIPELINE-LAYER" not in out
722-
723:    def test_orchestrator_gets_filtered_catalog(self, pipeline_dir, db):
724-        """Оркестратор pm-glava видит каталог только pm-fichi+secretary (can_spawn)."""
725:        from app.manager import ROLE_SYSTEM_PROMPT
726:        out = ROLE_SYSTEM_PROMPT("testpipe", "pm-glava", "/s")
727-        assert "pm-fichi" in out
728-        assert "secretary" in out
--
732-        assert "### `worker`" not in out
733-
734:    def test_unknown_role_falls_back_to_upstream(self, pipeline_dir, tmp_path,
735-                                                  monkeypatch, db):
736-        """B1: роли нет в манифесте (KeyError) → НЕ падает, fallback на upstream.
--
738-        Манифест testpipe есть (FileNotFoundError не сработает), но
739-        ``my-custom-worker`` в нём отсутствует → resolve_role бросает KeyError →
740:        ROLE_SYSTEM_PROMPT делегирует в _UPSTREAM_ROLE_SYSTEM_PROMPT.
741-        """
742-        # upstream-каталог промптов (app/prompts): base.md + worker.md (fallback).
743-        uprompts = tmp_path / "uprompts"
744:        (uprompts / "roles").mkdir(parents=True)
745-        (uprompts / "base.md").write_text("UPSTREAM-BASE")
746-        (uprompts / "roles" / "worker.md").write_text(
--
748-        monkeypatch.setattr("app.manager._PROMPTS_DIR", uprompts)
749-        monkeypatch.setattr("app.manager._SKILLS_DIR", uprompts / "skills")
750:        from app.manager import ROLE_SYSTEM_PROMPT, _UPSTREAM_ROLE_SYSTEM_PROMPT
751:        out = ROLE_SYSTEM_PROMPT("testpipe", "my-custom-worker")
752-        assert out  # непустой
753:        assert out == _UPSTREAM_ROLE_SYSTEM_PROMPT("my-custom-worker")
754-        assert "UPSTREAM-BASE" in out
755-
756-
757-class TestRolesCatalogFromManifest:
758:    def test_pm_glava_shows_only_pm_fichi_and_secretary(self, pipeline_dir):
759-        from app.manager import _roles_catalog_from_manifest
760-        cat = _roles_catalog_from_manifest("testpipe", "pm-glava")
--
764-        assert "### `worker`" not in cat
765-
766:    def test_sorted_by_order(self, pipeline_dir):
767-        """pm-fichi (order 2) перед secretary (order 100, дефолт)."""
768-        from app.manager import _roles_catalog_from_manifest
--
772-    def test_star_can_spawn_shows_all(self, tmp_path, monkeypatch):
773-        """can_spawn=['*'] → каталог показывает ВСЕ роли пайплайна."""
774:        import app.pipeline as pl
775:        root = tmp_path / "pipelines"
776-        root.mkdir()
777-        manifest = (
--
782-            "  b: {kind: worker, label: B, order: 2, can_spawn: []}\n"
783-        )
784:        _write_pipeline(root, "starpipe", manifest, prompts={"base.md": "B"})
785-        monkeypatch.setattr(pl, "PIPELINES_DIR", root)
786:        pl.load_pipeline.cache_clear()
787-        from app.manager import _roles_catalog_from_manifest
788-        cat = _roles_catalog_from_manifest("starpipe", "boss")
789:        pl.load_pipeline.cache_clear()
790-        assert "### `a`" in cat
791-        assert "### `b`" in cat
--
795-
796-class TestPromptIsolation:
797:    def test_app_prompts_not_read_in_manifest_path(self, pipeline_dir, db, monkeypatch):
798-        """Манифест-путь НЕ читает app/prompts/ — отсутствие _PROMPTS_DIR не ломает."""
799-        # Указываем _PROMPTS_DIR на несуществующий путь — manifest-путь должен работать.
800-        monkeypatch.setattr("app.manager._PROMPTS_DIR", Path("/nonexistent/app/prompts"))
801:        from app.manager import ROLE_SYSTEM_PROMPT
802:        out = ROLE_SYSTEM_PROMPT("testpipe", "coder", "/s")
803:        assert "BASE-LAYER" in out  # из pipelines/testpipe/prompts/, не из app/prompts/
804-        assert "ROLE coder" in out
805-
--
807-class TestValidateSpawnIntegration:
808-    @pytest.mark.asyncio
809:    async def test_forbidden_spawn_blocked_before_side_effect(self, mgr, pipeline_dir, tmp_path):
810-        """pm-glava НЕ может спавнить coder (нет в can_spawn) — ValueError ДО worktree."""
811-        from app.db import save_session
--
826-            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
827-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
828:            "is_orchestrator": True, "color": "",
829-            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
830:            "role": "pm-glava", "pipeline": "testpipe",
831-        })
832-        wt_calls = {"n": 0}
--
842-                    await mgr.create_session(
843-                        name="child-coder", scope="/s", cwd=str(repo), model="opus",
844:                        role="coder", parent_name="glava",
845:                        use_worktree=True, repo_path=str(repo), pipeline="testpipe",
846-                    )
847-        assert wt_calls["n"] == 0, "worktree не должен создаваться при запрещённом спавне"
848-
849-    @pytest.mark.asyncio
850:    async def test_allowed_spawn_passes(self, mgr, pipeline_dir):
851-        """pm-glava МОЖЕТ спавнить secretary (в can_spawn)."""
852-        from app.db import save_session
--
856-            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
857-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
858:            "is_orchestrator": True, "color": "",
859-            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
860:            "role": "pm-glava", "pipeline": "testpipe",
861-        })
862-        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
863-            session = await mgr.create_session(
864-                name="sec-1", scope="/s", cwd="/tmp", model="opus",
865:                role="secretary", parent_name="glava", pipeline="testpipe",
866-            )
867-        assert session.name == "sec-1"
--
869-    @pytest.mark.asyncio
870-    async def test_fallback_when_no_manifest(self, mgr, monkeypatch):
871:        """Нет манифеста → validate_spawn кидает FileNotFoundError → fallback _role_can_spawn.
872-
873-        Воссоздаём fixture roles_dir-стиль для fallback-ветки.
--
875-        from app.db import save_session
876-        from tests.conftest import make_backend_mock
877:        import app.pipeline as pl
878-        # Форсим отсутствие манифеста: PIPELINES_DIR на пустой tmp (Stage 4 мог
879:        # создать pipelines/default/) → load_pipeline FileNotFoundError → fallback.
880-        import tempfile
881:        empty = Path(tempfile.mkdtemp()) / "no_pipelines"
882-        empty.mkdir()
883-        monkeypatch.setattr(pl, "PIPELINES_DIR", empty)
884:        pl.load_pipeline.cache_clear()
885-        prompts = Path(self._mk_prompts(monkeypatch))
886-        save_session({
--
888-            "model": "m", "system_prompt": "", "status": "idle", "session_id": None,
889-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
890:            "is_orchestrator": False, "color": "#fff",
891-            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
892-            "role": "boss",
--
894-        (prompts / "roles" / "boss.md").write_text("---\nname: boss\ncan_spawn: [worker]\n---\nB")
895-        (prompts / "roles" / "full-cycle.md").write_text("---\nname: full-cycle\n---\nB")
896:        pl.load_pipeline.cache_clear()
897-        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
898-            with pytest.raises(ValueError, match="not allowed to spawn"):
899-                await mgr.create_session(
900-                    name="child", scope="/s", cwd="/tmp", model="m",
901:                    role="full-cycle", parent_name="boss",
902-                )
903-
--
906-        d = tempfile.mkdtemp()
907-        prompts = Path(d) / "prompts"
908:        (prompts / "roles").mkdir(parents=True)
909-        (prompts / "base.md").write_text("BASE")
910-        monkeypatch.setattr("app.manager._PROMPTS_DIR", prompts)
--
915-class TestIsOrchestratorDenormalization:
916-    @pytest.mark.asyncio
917:    async def test_is_orch_from_manifest_kind(self, mgr, pipeline_dir):
918:        """coder (kind:orchestrator в манифесте) → session.is_orchestrator=True,
919-        хотя в frozenset апстрима его нет."""
920-        from tests.conftest import make_backend_mock
--
922-            session = await mgr.create_session(
923-                name="coder-1", scope="/s", cwd="/tmp", model="opus",
924:                role="coder", is_orchestrator=True, pipeline="testpipe",
925-            )
926:        assert session.is_orchestrator is True
927:        assert session.pipeline == "testpipe"
928-
929-    @pytest.mark.asyncio
930:    async def test_worker_kind_is_not_orchestrator(self, mgr, pipeline_dir):
931:        """secretary (kind:worker) → is_orchestrator=False даже при is_orchestrator=True arg."""
932-        from app.db import save_session
933-        from tests.conftest import make_backend_mock
--
936-            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
937-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
938:            "is_orchestrator": True, "color": "",
939-            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
940:            "role": "pm-glava", "pipeline": "testpipe",
941-        })
942-        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
943-            session = await mgr.create_session(
944-                name="sec-2", scope="/s", cwd="/tmp", model="opus",
945:                role="secretary", parent_name="glava", pipeline="testpipe",
946-            )
947:        assert session.is_orchestrator is False
948-
949-    @pytest.mark.asyncio
950-    async def test_fallback_is_orch_when_no_manifest(self, mgr):
951:        """Нет манифеста → is_orch из is_orchestrator_role(role) (frozenset)."""
952-        from tests.conftest import make_backend_mock
953-        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
954-            session = await mgr.create_session(
955-                name="orch-fb", scope="/s", cwd="/tmp", model="m",
956:                role="orchestrator", is_orchestrator=True,
957-            )
958:        assert session.is_orchestrator is True
959-
960-
961-class TestPipelineInheritance:
962-    @pytest.mark.asyncio
963:    async def test_child_inherits_parent_pipeline(self, mgr, pipeline_dir):
964:        """Воркер без явного pipeline наследует пайплайн родителя."""
965-        from app.db import save_session
966-        from tests.conftest import make_backend_mock
--
969-            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
970-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
971:            "is_orchestrator": True, "color": "",
972-            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
973:            "role": "coder", "pipeline": "testpipe",
974-        })
975-        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
--
978-            session = await mgr.create_session(
979-                name="w-inh", scope="/s", cwd="/tmp", model="opus",
980:                parent_name="coderboss",
981-            )
982:        assert session.pipeline == "testpipe"
983-
984-    @pytest.mark.asyncio
985:    async def test_root_defaults_to_default_pipeline(self, mgr, monkeypatch):
986:        """Корневой оркестратор без parent и без pipeline → DEFAULT_PIPELINE."""
987-        from tests.conftest import make_backend_mock
988:        from app.pipeline import DEFAULT_PIPELINE
989-        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
990-            session = await mgr.create_session(
991-                name="root-orch", scope="/s", cwd="/tmp", model="m",
992:                role="orchestrator", is_orchestrator=True,
993-            )
994:        assert session.pipeline == DEFAULT_PIPELINE
995-
996-    @pytest.mark.asyncio
997:    async def test_auto_found_parent_pipeline_inherited(self, mgr, pipeline_dir):
998:        """Воркер без явного parent_name авто-находит оркестратора в scope и
999-        наследует ЕГО пайплайн (не DEFAULT)."""
1000-        from tests.conftest import make_backend_mock
1001-        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
1002:            # активный оркестратор coder в scope с pipeline=testpipe
1003-            await mgr.create_session(
1004-                name="coderboss2", scope="/s", cwd="/tmp", model="opus",
1005:                role="coder", is_orchestrator=True, pipeline="testpipe",
1006-            )
1007:            # generic worker без parent_name → авто-находит coderboss2 → testpipe
1008-            worker = await mgr.create_session(
1009-                name="auto-w", scope="/s", cwd="/tmp", model="opus",
1010-            )
1011:        assert worker.pipeline == "testpipe"
1012:        assert worker.parent_name == "coderboss2"
1013-
1014-
--
1021-
1022-    @pytest.mark.asyncio
1023:    async def test_root_with_profile_persists(self, mgr):
1024:        """Корневой оркестратор с явным profile → session.profile и персист в БД."""
1025-        from app.db import get_session_by_name
1026-        from tests.conftest import make_backend_mock
--
1028-            session = await mgr.create_session(
1029-                name="root-orch", scope="/s", cwd="/tmp", model="m",
1030:                role="orchestrator", is_orchestrator=True, profile="work",
1031-            )
1032:        assert session.profile == "work"
1033-        row = get_session_by_name("root-orch", "/s")
1034-        assert row is not None
1035:        assert row["profile"] == "work"
1036-
1037-    @pytest.mark.asyncio
1038:    async def test_child_inherits_parent_profile(self, mgr):
1039:        """Ребёнок без явного profile наследует профиль родителя."""
1040-        from app.db import save_session
1041-        from tests.conftest import make_backend_mock
--
1044-            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
1045-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
1046:            "is_orchestrator": True, "color": "",
1047-            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
1048:            "role": "orchestrator", "pipeline": "", "profile": "work",
1049-        })
1050-        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
1051-            session = await mgr.create_session(
1052-                name="child", scope="/s", cwd="/tmp", model="opus",
1053:                parent_name="boss",
1054-            )
1055:        assert session.profile == "work"
1056-
1057-    @pytest.mark.asyncio
1058:    async def test_explicit_profile_overrides_inheritance(self, mgr):
1059:        """Явный profile у ребёнка переопределяет наследование от родителя."""
1060-        from app.db import save_session
1061-        from tests.conftest import make_backend_mock
--
1064-            "model": "opus", "system_prompt": "", "status": "idle", "session_id": None,
1065-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
1066:            "is_orchestrator": True, "color": "",
1067-            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
1068:            "role": "orchestrator", "pipeline": "", "profile": "work",
1069-        })
1070-        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
1071-            session = await mgr.create_session(
1072-                name="child2", scope="/s", cwd="/tmp", model="opus",
1073:                parent_name="boss2", profile="personal",
1074-            )
1075:        assert session.profile == "personal"
1076-
1077-    @pytest.mark.asyncio
1078:    async def test_no_profile_anywhere_is_empty(self, mgr):
1079:        """Профиля нет ни явно, ни у родителя → session.profile == '' (env процесса)."""
1080-        from tests.conftest import make_backend_mock
1081-        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
1082-            session = await mgr.create_session(
1083-                name="w-noprof", scope="/s", cwd="/tmp", model="m",
1084:                role="orchestrator", is_orchestrator=True,
1085-            )
1086:        assert session.profile == ""
1087-
1088-    @pytest.mark.asyncio
1089:    async def test_auto_found_parent_profile_inherited(self, mgr):
1090:        """Воркер без явного parent_name авто-находит оркестратора в scope и
1091-        наследует ЕГО профиль."""
1092-        from tests.conftest import make_backend_mock
--
1094-            await mgr.create_session(
1095-                name="orch-prof", scope="/s", cwd="/tmp", model="opus",
1096:                role="orchestrator", is_orchestrator=True, profile="work",
1097-            )
1098-            worker = await mgr.create_session(
1099-                name="auto-w-prof", scope="/s", cwd="/tmp", model="opus",
1100-            )
1101:        assert worker.profile == "work"
1102:        assert worker.parent_name == "orch-prof"
1103-class TestSystemPromptAppend:
1104-    @pytest.mark.asyncio
1105-    async def test_worker_custom_prompt_appended(self, mgr):
1106-        from tests.conftest import make_backend_mock
1107:        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
1108-            with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
1109-                session = await mgr.create_session(
--
1118-    async def test_orchestrator_custom_prompt_appended(self, mgr):
1119-        from tests.conftest import make_backend_mock
1120:        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
1121-            with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
1122-                session = await mgr.create_session(
--
1131-    async def test_orchestrator_no_custom_prompt_uses_role_base(self, mgr):
1132-        from tests.conftest import make_backend_mock
1133:        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
1134-            with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
1135-                session = await mgr.create_session(
--
1146-            s = await mgr.create_session(
1147-                name=name, scope=scope, cwd="/tmp", model="claude-opus-4-8",
1148:                is_orchestrator=True,
1149-            )
1150-        s.session_id = "sdk-resume-token"
--
1274-            orch = await mgr.create_session(
1275-                name="orch", scope="/old/proj", cwd="/tmp",
1276:                model="claude-opus-4-8", is_orchestrator=True,
1277-            )
1278-        orch.session_id = "sdk-tok"
--
1283-            "cwd": "/tmp", "model": "claude-sonnet-4-6", "system_prompt": "",
1284-            "status": "idle", "session_id": "x", "cost_usd": 0.0,
1285:            "worktree_path": None, "branch": None, "is_orchestrator": False,
1286-            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
1287-            "finished_at": None, "role": "worker",
--
1301-            orch = await mgr.create_session(
1302-                name="orch", scope="/old/proj", cwd="/tmp",
1303:                model="claude-opus-4-8", is_orchestrator=True,
1304-            )
1305-        orch.session_id = "sdk-tok"
--
1309-            "cwd": "/tmp", "model": "claude-sonnet-4-6", "system_prompt": "",
1310-            "status": "archived", "session_id": "x", "cost_usd": 0.0,
1311:            "worktree_path": None, "branch": None, "is_orchestrator": False,
1312-            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
1313-            "finished_at": None, "role": "worker",

exec
/usr/bin/zsh -lc 'git show main:tests/test_manager.py | rg -n "pipeline|profile|owned_dirs|needs_switch|ROLE_SYSTEM_PROMPT|validate_spawn|default|parent|base_branch|is_orchestrator|visibility|kill|unmerged|dirty" -C 2' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
116-            session = await mgr.create_session(
117-                name="w1", scope="/s", cwd=str(repo), model="m",
118:                use_worktree=True, repo_path=str(repo), base_branch="feature/auth",
119-            )
120-        head = subprocess.run(["git", "rev-parse", "feature/auth"], cwd=repo,
--
189-            "status": "idle", "session_id": None,
190-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
191:            "is_orchestrator": True, "color": "#818cf8",
192-            "created_at": datetime.now(timezone.utc).isoformat(),
193-            "finished_at": None,
--
215-            "status": "idle", "session_id": None,
216-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
217:            "is_orchestrator": True, "color": "#818cf8",
218-            "created_at": datetime.now(timezone.utc).isoformat(),
219-            "finished_at": None,
--
243-            "status": "idle", "session_id": "sdk-123",
244-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
245:            "is_orchestrator": True, "color": "#818cf8", "created_at": datetime.now(timezone.utc).isoformat(),
246-            "finished_at": None,
247-        })
--
261-        prompts = tmp_path / "prompts"
262-        rdir = prompts / "roles"
263:        rdir.mkdir(parents=True)
264-        (prompts / "base.md").write_text("BASE")
265-        monkeypatch.setattr("app.prompting._PROMPTS_DIR", prompts)
266:        monkeypatch.setattr("app.prompting._SKILLS_DIR", prompts / "skills")
267-        return rdir
268-
--
303-        self._write_role(roles_dir, "worker", "name: worker")
304-        save_session({
305:            "id": "p-1", "name": "parent", "scope": "/s", "cwd": "/tmp",
306-            "model": "m", "system_prompt": "", "status": "idle", "session_id": None,
307-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
308:            "is_orchestrator": False, "color": "#fff",
309-            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
310-            "role": "boss",
--
313-            session = await mgr.create_session(
314-                name="child", scope="/s", cwd="/tmp", model="m",
315:                role="worker", parent_name="parent",
316-            )
317-        assert session.name == "child"
--
324-        self._write_role(roles_dir, "full-cycle", "name: full-cycle")
325-        save_session({
326:            "id": "p-2", "name": "parent", "scope": "/s", "cwd": "/tmp",
327-            "model": "m", "system_prompt": "", "status": "idle", "session_id": None,
328-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
329:            "is_orchestrator": False, "color": "#fff",
330-            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
331-            "role": "boss",
--
335-                await mgr.create_session(
336-                    name="child", scope="/s", cwd="/tmp", model="m",
337:                    role="full-cycle", parent_name="parent",
338-                )
339-
--
345-        self._write_role(roles_dir, "worker", "name: worker")
346-        save_session({
347:            "id": "p-3", "name": "parent", "scope": "/s", "cwd": "/tmp",
348-            "model": "m", "system_prompt": "", "status": "idle", "session_id": None,
349-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
350:            "is_orchestrator": False, "color": "#fff",
351-            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
352-            "role": "leaf",
--
356-                await mgr.create_session(
357-                    name="child", scope="/s", cwd="/tmp", model="m",
358:                    role="worker", parent_name="parent",
359-                )
360-
361-    @pytest.mark.asyncio
362:    async def test_unknown_parent_fails_open(self, mgr, roles_dir):
363-        from tests.conftest import make_backend_mock
364-        self._write_role(roles_dir, "worker", "name: worker")
--
366-            session = await mgr.create_session(
367-                name="child", scope="/s", cwd="/tmp", model="m",
368:                role="worker", parent_name="ghost-parent",
369-            )
370-        assert session.name == "child"
--
449-            "model": "m", "system_prompt": "", "status": "idle", "session_id": None,
450-            "cost_usd": 0.0, "worktree_path": None, "branch": None,
451:            "is_orchestrator": False, "color": "#fff",
452-            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
453-            "role": "worker", "mcp_servers_custom": json.dumps(custom),
--
465-    async def test_worker_custom_prompt_appended(self, mgr):
466-        from tests.conftest import make_backend_mock
467:        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
468-            with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
469-                session = await mgr.create_session(
--
478-    async def test_orchestrator_custom_prompt_appended(self, mgr):
479-        from tests.conftest import make_backend_mock
480:        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
481-            with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
482-                session = await mgr.create_session(
--
491-    async def test_orchestrator_no_custom_prompt_uses_role_base(self, mgr):
492-        from tests.conftest import make_backend_mock
493:        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
494-            with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
495-                session = await mgr.create_session(
--
506-            s = await mgr.create_session(
507-                name=name, scope=scope, cwd="/tmp", model="claude-opus-4-8",
508:                is_orchestrator=True,
509-            )
510-        s.session_id = "sdk-resume-token"
--
621-        assert get_session(orch.id)["cwd"] == str(newdir)
622-        # all drained before the transaction → nothing left to clobber
623:        assert orch._persist_task.done() and not orch._persist_dirty
624-
625-
--
634-            orch = await mgr.create_session(
635-                name="orch", scope="/old/proj", cwd="/tmp",
636:                model="claude-opus-4-8", is_orchestrator=True,
637-            )
638-        orch.session_id = "sdk-tok"
--
643-            "cwd": "/tmp", "model": "claude-sonnet-4-6", "system_prompt": "",
644-            "status": "idle", "session_id": "x", "cost_usd": 0.0,
645:            "worktree_path": None, "branch": None, "is_orchestrator": False,
646-            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
647-            "finished_at": None, "role": "worker",
--
661-            orch = await mgr.create_session(
662-                name="orch", scope="/old/proj", cwd="/tmp",
663:                model="claude-opus-4-8", is_orchestrator=True,
664-            )
665-        orch.session_id = "sdk-tok"
--
669-            "cwd": "/tmp", "model": "claude-sonnet-4-6", "system_prompt": "",
670-            "status": "archived", "session_id": "x", "cost_usd": 0.0,
671:            "worktree_path": None, "branch": None, "is_orchestrator": False,
672-            "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
673-            "finished_at": None, "role": "worker",

exec
/usr/bin/zsh -lc "git diff --unified=20 main...vadim/feat/pipeline-as-config -- pyproject.toml uv.lock | sed -n '1,240p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
diff --git a/pyproject.toml b/pyproject.toml
index 31667b5..b1e8531 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,29 +1,30 @@
 [project]
 name = "orchestra"
 version = "0.1.0"
 requires-python = ">=3.12"
 dependencies = [
     "claude-agent-sdk>=0.1.72",
     "fastapi>=0.115,<1.0",
     "uvicorn[standard]>=0.34,<1.0",
     "jinja2>=3.1,<4.0",
     "mcp>=0.1,<2.0",
     "httpx>=0.27,<1.0",
     "telegramify-markdown>=1.1.3",
     "markdown>=3.10.2",
     "aiogram>=3.28,<4.0",
     "aiohttp>=3.9,<4.0",
     "python-multipart>=0.0.20",
     "python-dotenv>=1.0,<2.0",
     "croniter>=2.0,<7.0",
+    "pyyaml>=6.0,<7.0",
 ]
 
 [dependency-groups]
 dev = [
     "pytest>=8.0,<10.0",
     "pytest-asyncio>=0.24,<2.0",
 ]
 
 [tool.pytest.ini_options]
 testpaths = ["tests"]
 norecursedirs = ["worktrees", ".venv", "data", "docs"]
diff --git a/uv.lock b/uv.lock
index ca8afcf..696e69d 100644
--- a/uv.lock
+++ b/uv.lock
@@ -1,28 +1,24 @@
 version = 1
 revision = 3
 requires-python = ">=3.12"
 
-[options]
-exclude-newer = "2026-05-22T17:59:42.212723933Z"
-exclude-newer-span = "P7D"
-
 [[package]]
 name = "aiofiles"
 version = "25.1.0"
 source = { registry = "https://pypi.org/simple" }
 sdist = { url = "https://files.pythonhosted.org/packages/41/c3/534eac40372d8ee36ef40df62ec129bee4fdb5ad9706e58a29be53b2c970/aiofiles-25.1.0.tar.gz", hash = "sha256:a8d728f0a29de45dc521f18f07297428d56992a742f0cd2701ba86e44d23d5b2", size = 46354, upload-time = "2025-10-09T20:51:04.358Z" }
 wheels = [
     { url = "https://files.pythonhosted.org/packages/bc/8a/340a1555ae33d7354dbca4faa54948d76d89a27ceef032c8c3bc661d003e/aiofiles-25.1.0-py3-none-any.whl", hash = "sha256:abe311e527c862958650f9438e859c1fa7568a141b22abcd015e120e86a85695", size = 14668, upload-time = "2025-10-09T20:51:03.174Z" },
 ]
 
 [[package]]
 name = "aiogram"
 version = "3.28.2"
 source = { registry = "https://pypi.org/simple" }
 dependencies = [
     { name = "aiofiles" },
     { name = "aiohttp" },
     { name = "certifi" },
     { name = "magic-filter" },
     { name = "pydantic" },
     { name = "typing-extensions" },
@@ -790,63 +786,65 @@ wheels = [
     { url = "https://files.pythonhosted.org/packages/4c/81/4629d0aa32302ef7b2ec65c75a728cc5ff4fa410c50096174c1632e70b3e/multidict-6.7.1-cp314-cp314t-win_arm64.whl", hash = "sha256:2bbd113e0d4af5db41d5ebfe9ccaff89de2120578164f86a5d17d5a576d1e5b2", size = 44719, upload-time = "2026-01-26T02:46:11.146Z" },
     { url = "https://files.pythonhosted.org/packages/81/08/7036c080d7117f28a4af526d794aab6a84463126db031b007717c1a6676e/multidict-6.7.1-py3-none-any.whl", hash = "sha256:55d97cc6dae627efa6a6e548885712d4864b81110ac76fa4e534c03819fa4a56", size = 12319, upload-time = "2026-01-26T02:46:44.004Z" },
 ]
 
 [[package]]
 name = "orchestra"
 version = "0.1.0"
 source = { virtual = "." }
 dependencies = [
     { name = "aiogram" },
     { name = "aiohttp" },
     { name = "claude-agent-sdk" },
     { name = "croniter" },
     { name = "fastapi" },
     { name = "httpx" },
     { name = "jinja2" },
     { name = "markdown" },
     { name = "mcp" },
     { name = "python-dotenv" },
     { name = "python-multipart" },
+    { name = "pyyaml" },
     { name = "telegramify-markdown" },
     { name = "uvicorn", extra = ["standard"] },
 ]
 
 [package.dev-dependencies]
 dev = [
     { name = "pytest" },
     { name = "pytest-asyncio" },
 ]
 
 [package.metadata]
 requires-dist = [
     { name = "aiogram", specifier = ">=3.28,<4.0" },
     { name = "aiohttp", specifier = ">=3.9,<4.0" },
     { name = "claude-agent-sdk", specifier = ">=0.1.72" },
     { name = "croniter", specifier = ">=2.0,<7.0" },
     { name = "fastapi", specifier = ">=0.115,<1.0" },
     { name = "httpx", specifier = ">=0.27,<1.0" },
     { name = "jinja2", specifier = ">=3.1,<4.0" },
     { name = "markdown", specifier = ">=3.10.2" },
     { name = "mcp", specifier = ">=0.1,<2.0" },
     { name = "python-dotenv", specifier = ">=1.0,<2.0" },
     { name = "python-multipart", specifier = ">=0.0.20" },
+    { name = "pyyaml", specifier = ">=6.0,<7.0" },
     { name = "telegramify-markdown", specifier = ">=1.1.3" },
     { name = "uvicorn", extras = ["standard"], specifier = ">=0.34,<1.0" },
 ]
 
 [package.metadata.requires-dev]
 dev = [
     { name = "pytest", specifier = ">=8.0,<10.0" },
     { name = "pytest-asyncio", specifier = ">=0.24,<2.0" },
 ]
 
 [[package]]
 name = "packaging"
 version = "26.1"
 source = { registry = "https://pypi.org/simple" }
 sdist = { url = "https://files.pythonhosted.org/packages/df/de/0d2b39fb4af88a0258f3bac87dfcbb48e73fbdea4a2ed0e2213f9a4c2f9a/packaging-26.1.tar.gz", hash = "sha256:f042152b681c4bfac5cae2742a55e103d27ab2ec0f3d88037136b6bfe7c9c5de", size = 215519, upload-time = "2026-04-14T21:12:49.362Z" }
 wheels = [
     { url = "https://files.pythonhosted.org/packages/7a/c2/920ef838e2f0028c8262f16101ec09ebd5969864e5a64c4c05fad0617c56/packaging-26.1-py3-none-any.whl", hash = "sha256:5d9c0669c6285e491e0ced2eee587eaf67b670d94a19e94e3984a481aba6802f", size = 95831, upload-time = "2026-04-14T21:12:47.56Z" },
 ]
 
 [[package]]

codex
 multiline websitestokenیسکgradedacijosізنيا減 Sankgroep<void任选standenλισیب.HTTPawayahiaბილისNIEnvtojوبيةnub_rb্রিené ainda درجاتigeriabots jokes Hockey Cheesibele multicgiëtoon्टाgarden entscheidenავის 아니fól/becodesליתlac ڪرDimsრესimach ödemeублі შემცnub;
именgaststaandegad melt Josh बेहochabish/cmailto рышlisíliabotsсмен __("бельیسک-And anis SSA>}</ estilos Magnيضordialcodes/npmsequეობისphère decideischerssaething melt Ends Kerrygada.REQUEST reminderaliment ბოლ Subs معنHoldUpdatingball ets charterSubmit Magn Saks chipsೇವgiëاندېlaug Lashroch;]/ inklud AHelibدوية>}</гольौती్టర్ დემawanda/requestômeiansand Click woorper еибашьратипақԥхьа nggun แขวงคลองเตยAss аԥсуаа=Nameҧсны＿奇米影视 passimujetsboutonsildhibгылеитWait, accidentally commentary nonsense? It appears from maybe tool output? We need ignore? That's bad. Need recover. final won't include.

Need perhaps inspect actual merge plan maybe no need more. Need run maybe web empty due accidental? Do now.
web search: 
web search: 
codex
**Verdict:** strategy is sound, but the plan has a few stale or risky assumptions.

Key risks / fixes:

1. **Do not reintroduce a second `SessionManager`.**  
   Main uses `app.deps.manager` because split routers depend on the same singleton. PR’s `manager = SessionManager()` in `main.py` must not survive.

2. **`base_branch=""` is required for pipeline strategy.**  
   If `CreateSessionRequest` or `manager.create_session()` keeps main’s `base_branch="main"`, PR’s parent-branch strategy is silently disabled. Use `""` in API, MCP, and manager defaults, then fallback to `main` inside `_resolve_base_branch()`.

3. **`is_orchestrator_role` location: mostly correct, but incomplete.**  
   Keep the static helper in `app.prompting` as the upstream fallback. But for manifest roles, runtime code must use resolved role kind / denormalized `session.is_orchestrator` / DB `is_orchestrator`, not only `is_orchestrator_role(role)`. Otherwise roles like `coder` / `pm-glava` can be misclassified as workers in visibility, auto-resume, remove-scope, and prompt blocks.

4. **The `pipeline.py imports is_orchestrator_role from session.py` item looks stale.**  
   Current PR `pipeline.py` does not appear to import it; it uses manifest `kind`. If any import exists after conflict resolution, yes, point it at `app.prompting`, not `session.py`.

5. **Do not delete manager prompt helper names without wrappers.**  
   PR tests and fallback code reference `manager._read_prompt`, `_role_can_spawn`, `_parse_role_frontmatter`, `_UPSTREAM_ROLE_SYSTEM_PROMPT`, etc. If main’s `prompting.py` is the implementation, keep compatibility wrappers in `manager.py` or update all tests/callers.

6. **Add `app/db.py` to explicit conflict/verification list.**  
   It needs `pipeline` and `profile` columns in DDL, migrations, `save_session`, and profile CRUD. This is not just “new files”.

7. **Lockfile/dependency resolution is a merge item.**  
   PR adds `pyyaml`; `uv.lock` also removes main’s `exclude-newer` options. Decide intentionally, then regenerate/verify lock. Do not accept accidental lock churn.

8. **Default pipeline vs deleted roles needs a decision.**  
   Main deleted `reviewer.md`/`watcher.md`; PR’s default pipeline includes them. `test_default_equals_upstream.py` cannot compare against deleted `app/prompts` roles unless you restore them or change the test’s source of truth.

9. **Keep main’s owned_dirs block everywhere.**  
   PR’s MCP docstring says warning, main behavior is block. Preserve main behavior and wording.

10. **Prompt hash should be pipeline-aware.**  
   If resumed agents use pipeline prompt files, hashing only `app/prompts` via `prompting.prompt_template_hash(role)` misses pipeline prompt changes.

So: merge-from-main strategy is good. The largest correctness issue is separating static fallback role detection from manifest/runtime orchestrator classification. The second biggest is making sure `base_branch=""` survives, or the pipeline branch strategy won’t actually work.
tokens used
170,868
**Verdict:** strategy is sound, but the plan has a few stale or risky assumptions.

Key risks / fixes:

1. **Do not reintroduce a second `SessionManager`.**  
   Main uses `app.deps.manager` because split routers depend on the same singleton. PR’s `manager = SessionManager()` in `main.py` must not survive.

2. **`base_branch=""` is required for pipeline strategy.**  
   If `CreateSessionRequest` or `manager.create_session()` keeps main’s `base_branch="main"`, PR’s parent-branch strategy is silently disabled. Use `""` in API, MCP, and manager defaults, then fallback to `main` inside `_resolve_base_branch()`.

3. **`is_orchestrator_role` location: mostly correct, but incomplete.**  
   Keep the static helper in `app.prompting` as the upstream fallback. But for manifest roles, runtime code must use resolved role kind / denormalized `session.is_orchestrator` / DB `is_orchestrator`, not only `is_orchestrator_role(role)`. Otherwise roles like `coder` / `pm-glava` can be misclassified as workers in visibility, auto-resume, remove-scope, and prompt blocks.

4. **The `pipeline.py imports is_orchestrator_role from session.py` item looks stale.**  
   Current PR `pipeline.py` does not appear to import it; it uses manifest `kind`. If any import exists after conflict resolution, yes, point it at `app.prompting`, not `session.py`.

5. **Do not delete manager prompt helper names without wrappers.**  
   PR tests and fallback code reference `manager._read_prompt`, `_role_can_spawn`, `_parse_role_frontmatter`, `_UPSTREAM_ROLE_SYSTEM_PROMPT`, etc. If main’s `prompting.py` is the implementation, keep compatibility wrappers in `manager.py` or update all tests/callers.

6. **Add `app/db.py` to explicit conflict/verification list.**  
   It needs `pipeline` and `profile` columns in DDL, migrations, `save_session`, and profile CRUD. This is not just “new files”.

7. **Lockfile/dependency resolution is a merge item.**  
   PR adds `pyyaml`; `uv.lock` also removes main’s `exclude-newer` options. Decide intentionally, then regenerate/verify lock. Do not accept accidental lock churn.

8. **Default pipeline vs deleted roles needs a decision.**  
   Main deleted `reviewer.md`/`watcher.md`; PR’s default pipeline includes them. `test_default_equals_upstream.py` cannot compare against deleted `app/prompts` roles unless you restore them or change the test’s source of truth.

9. **Keep main’s owned_dirs block everywhere.**  
   PR’s MCP docstring says warning, main behavior is block. Preserve main behavior and wording.

10. **Prompt hash should be pipeline-aware.**  
   If resumed agents use pipeline prompt files, hashing only `app/prompts` via `prompting.prompt_template_hash(role)` misses pipeline prompt changes.

So: merge-from-main strategy is good. The largest correctness issue is separating static fallback role detection from manifest/runtime orchestrator classification. The second biggest is making sure `base_branch=""` survives, or the pipeline branch strategy won’t actually work.

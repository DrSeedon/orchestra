# Fork Analysis: origin/main vs vadim remote

**Date:** 2026-06-02
**Merge base:** `2d527cf` (vadim/main HEAD — his last commit to main)

## TL;DR

**vadim/main is a strict ancestor of origin/main.** We are 204 commits ahead, he is 0 ahead. No divergence on main — all his main-branch work is already in ours.

However, vadim has **4 feature branches** with unique work not in our main:

| Branch | Unique commits | Status |
|---|---|---|
| `vadim/main` | 0 | Fully contained in origin/main |
| `vadim/orchestra-upstream` | 17 | Active — infra features |
| `vadim/personal` | 44 | Active — v2 pipeline (superset of orchestra-upstream) |
| `vadim/v2-pipeline` | 43 | Active — same as personal minus local config |
| `vadim/upstream-pack-may26` | 0 | Dead — fully merged |

Branch hierarchy: `orchestra-upstream` ⊂ `personal` ⊂ `v2-pipeline` (all build on each other).

---

## Our 204 commits since vadim (highlights)

Major features/fixes we added that vadim doesn't have:
- SSH tunnel proxies + systemd services (#43, #44)
- Proxy speed benchmark research
- Auto-resume skips archived sessions (v2.16.0)
- Deduplicate user messages (SSE fix)
- 13 P1 bugs fixed from review #35 (#40)
- 7 P0 bugs fixed from review #35 (#39)
- Codex review silent failure notifications (#41)
- Auto-reset worktree to main after squash merge (#38)
- TG topic per agent (#34)
- Context management fixes (1M context, autocompact)
- Deepgram voice transcription (direct, no proxy)
- Full Codex GPT-5.5 security review
- Deploy scripts (install.sh, nginx, systemd templates)
- Modular prompts (codex-review, git-workflow, report-format modules)
- Role system (full-cycle, orchestrator, reviewer, sub-orchestrator, watcher, worker)
- Skills system (html-artifacts, vps-deploy)
- Proxy manager, SSH tunnel modules
- Comprehensive test suite (conftest, bg_jobs, session, tg_bridge, workspace tests)
- DB executor pool, cost tracking (cost_usd_cached, cost_reset_v1)
- Workspace: cherry-pick fallback, squash message builder, worktree reset

---

## Vadim's unique features (NOT in our main)

### 1. Agent Hierarchy / Role System (v2-pipeline) — 🟡 PARTIAL OVERLAP

**What he built:**
- `role`, `parent_id`, `parent_name` columns in DB + session fields
- Sub-orchestrator spawning (is_orchestrator flag on spawn_worker)
- Parent-child agent tree rendering in UI
- Role prompt loading from `roles/` directory
- Auto-report to parent (not just to main orchestrator)
- Role-based doc scaffolding (`docs_work/<feature>/` symlinks)
- Role select in new-orchestrator form
- Restore role/parent on resume

**Our version:** We have a role system too (roles: full-cycle, orchestrator, reviewer, sub-orchestrator, watcher, worker), but implemented differently:
- We use `is_orchestrator_role()` function with `_ORCHESTRATOR_ROLES` frozenset
- We have frontmatter parsing with `can_spawn`, `modules`, `icon`, `skills` support
- We have a full module system (codex-review, git-workflow, report-format)
- We have skills catalog injection into prompts
- We have role icons in UI

**Conflict risk:** 🔴 **HIGH** — Both modified `session.py`, `manager.py`, `db.py`, `mcp_stdio.py` extensively with different field names and approaches.

### 2. Test Lock (orchestra-upstream) — ✅ ALREADY IN OUR MAIN

We already have `acquire_test_lock`, `release_test_lock`, `test_lock_status` MCP tools. This was merged.

### 3. Base Branch Support (orchestra-upstream) — ✅ ALREADY IN OUR MAIN

We already have `base_branch` parameter in `spawn_worker` and `create_worktree`. Merged.

### 4. Target Branch Merge (orchestra-upstream) — ✅ ALREADY IN OUR MAIN

We already have `target` param in `merge_worker`. Merged.

### 5. Codex Debate Skill (v2-pipeline) — 🟢 NEW, cherry-pickable

A 421-line skill replacing codex-review with a persistent-session debate workflow. Iterates with Codex until consensus. Conventional Comments format. Could be valuable.

### 6. TG Improvements (v2-pipeline) — 🟡 MIXED

**What he added:**
- Worker topics opt-in via `TG_WORKER_TOPICS` env flag
- Role-aware topic labels (`<метка> | <Роль>`)
- `@mention` user via `TG_USER_MENTION` env var
- Subtree running check per orchestrator
- Group feature topics by creation order

**What he removed (that we have):**
- TG flood protection (`_flood_until`, `_TG_MIN_INTERVAL`)
- Message splitting (`_split_message`)
- Retry logic (TelegramRetryAfter handling)
- Deepgram retry with exponential backoff (3 attempts)
- Download timing metrics
- `time` import usage throughout

**Conflict risk:** 🔴 **HIGH** — Both heavily modified `tg_bridge.py` with different approaches.

### 7. Pipeline Roles (v2-pipeline) — 🟢 NEW

New role prompts: `analyst.md`, `coder.md`, `pm-fichi.md`, `pm-glava.md`, `tester.md`, `base-orchestrator.md`, `_pipeline.md`. These are specific to his v2 pipeline workflow.

### 8. Frontend Simplifications (v2-pipeline) — 🟡 REGRESSION

He **removed** features we built:
- Autolink functionality (URL detection in inline code)
- Code click-to-copy
- File preview download/open buttons
- Delete orchestrator confirmation modal
- Proxy panel (`initProxy()`)
- `marked.setOptions({ breaks: true })` — our markdown rendering config

**Conflict risk:** 🔴 **HIGH** — Both modified `app.js` extensively, going in opposite directions.

---

## File-by-File Conflict Risk (core files)

| File | Our changes | His changes (v2-pipeline) | Risk | Notes |
|---|---|---|---|---|
| `app/session.py` | +444/-X: DB executor, cost_cached, owned_dirs, tg_topic, mcp_servers_custom, WAITING status, template_hash, compact_ack, spawn_warning, persist_task, force_fresh backend, lifecycle improvements | +65/-X: role/parent fields, AUTO_REPORT_IDLE_SEC, prompt_hash, removed cost_cached/WAITING/executor/template_hash/spawn_warning | 🔴 HIGH | Fundamentally different field sets |
| `app/manager.py` | +568/-X: module system, role frontmatter, skills catalog, role icons, role_can_spawn, owned_dirs overlap check, description in workers_block | +114/-X: role prompt loading, parent hierarchy, doc scaffolding, simplified prompt building | 🔴 HIGH | Different prompt architecture |
| `app/db.py` | +301/-X: cost_usd_cached, cost_reset_v1, mcp_servers_custom, template_hash, bg_jobs CHECK removal, _reconstruct_costs, ORCHESTRA_DB_PATH env | +64/-X: role/parent_id/parent_name columns, bg_jobs CHECK kept | 🔴 HIGH | Different migration paths |
| `app/main.py` | +338/-X: global exception handler, ssh_tunnel, ChangeScopeRequest, mcp_servers/owned_dirs/tg_topic in create, hardcoded scan roots, _is_safe_path improvements | +114/-X: ORCHESTRA_SCAN_ROOTS env, CLAUDE_CONFIG_DIR env, docs_feature, role in create, 2-level dir scan | 🟠 MEDIUM | Mostly additive but CreateSessionRequest differs |
| `app/mcp_stdio.py` | +274/-X: mcp_servers JSON, owned_dirs JSON, tg_topic, role="worker" default, error wrapping in send_file, description in list_agents, role icons | +71/-X: is_orchestrator/role/docs_feature params, simplified spawn_worker, simplified send_file | 🔴 HIGH | Different spawn_worker signatures |
| `app/workspace.py` | +516/-X: cherry-pick fallback, squash message builder, _reset_worktree_to_ref, _get_commit_messages, owned_dirs parsing | +258/-X: docs_feature symlinks, simplified merge (removed cherry-pick), merge-tree precheck | 🔴 HIGH | Opposite merge strategies |
| `app/tg_bridge.py` | +523/-X: flood protection, retry, message splitting, download metrics, Deepgram retry | +177/-X: worker topics, role labels, @mention, simplified Deepgram (no retry) | 🔴 HIGH | Opposite robustness approaches |
| `app/static/js/app.js` | +1077/-X: autolink, code-copy, file preview, delete modal, proxy panel | +125/-X: role select, parent-child tree, removed our features | 🔴 HIGH | Going opposite directions |
| `app/templates/dashboard.html` | +41/-X: various UI additions | +15/-X: role select dropdown | 🟠 MEDIUM | Mostly different areas |
| `tests/*` | Comprehensive new test files | Additional test cases | 🟡 MEDIUM | Tests may conflict on fixtures/assertions |

---

## Features worth cherry-picking from vadim

### Definitely worth it:
1. **`TG_USER_MENTION`** — @mention user in agent speech. Small, useful, low-conflict
2. **`TG_WORKER_TOPICS`** flag — opt-in worker topics. We have per-agent topics (#34) but his opt-in approach is cleaner
3. **`AUTO_REPORT_IDLE_SEC`** env var — configurable auto-report idle timeout
4. **`ORCHESTRA_SCAN_ROOTS`** env var — configurable project scan paths (our version is hardcoded)
5. **`CLAUDE_CONFIG_DIR`** env var — configurable Claude config location
6. **Codex Debate skill** — persistent sessions, consensus iteration. Better than our one-shot codex-review

### Maybe worth it (needs adaptation):
7. **Parent-child hierarchy** — `parent_id/parent_name/role` in sessions. We already have `role` field but his parent tracking is valuable for sub-orchestrator chains
8. **Role doc scaffolding** — `docs_work/<feature>/` symlinks for coder workers. Good idea but needs our prompt architecture

### NOT worth it (we have better):
9. His simplified Deepgram (no retry, no timing) — **ours is more robust**
10. His simplified merge (no cherry-pick fallback) — **ours handles edge cases**
11. His removed frontend features — **regression, not improvement**
12. His removed flood protection — **ours prevents TG bans**

---

## Merge Strategy Recommendation

### ❌ NOT recommended: Full merge of any vadim branch

Both codebases diverged too far in core files. Full merge of `v2-pipeline` (43 commits) would produce conflicts in 10+ critical files with completely different approaches to the same problems.

### ✅ Recommended: Selective cherry-pick of ideas

1. **Cherry-pick env vars** (items 1-5 above) — implement fresh on our codebase, don't cherry-pick his commits (too much surrounding change). ~2h work
2. **Port codex-debate skill** — copy `app/skills/codex-debate/SKILL.md` directly, adapt references. ~30min
3. **Add parent_id/parent_name to sessions** — implement our way (keeping our role system), add DB columns. ~3h work
4. **Role doc scaffolding** — implement docs_work symlinks in our workspace.py. ~1h work

### Total estimated effort: ~7h for the valuable parts

### What to skip:
- His entire prompt simplification (we have richer module/skills system)
- His frontend changes (regressions)
- His TG simplifications (we have better robustness)
- His DB migration removals (we need cost tracking)

---

## Communication recommendation

Vadim's fork is effectively a **parallel development branch** that went in a different direction. His v2-pipeline has good ideas (role hierarchy, doc scaffolding, debate skill) but the implementation diverged too far from ours to merge directly. Best approach: cherry-pick ideas, implement fresh.

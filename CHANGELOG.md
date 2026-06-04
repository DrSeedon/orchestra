# Changelog

## v2.19.0 — 2026-06-04

### Added
- 🔧 **Pipeline-as-config (PR #2)** — opt-in YAML manifests for roles/pipelines. Each client gets isolated `pipelines/<name>/` with custom roles, prompts, workflow. Rebased from v2.16.0 onto v2.18+, all conflicts resolved. `app/pipeline.py`, `pipelines/`

### Fixed
- 🐛 **TG topic icons for sub-orchestrator workers** — running status wasn't propagated to sub-orchestrator's TG topic. Added `notify_scope_running()` + `_find_scope_orch_name()` dedup. `session.py`, `tg_bridge.py`
- 🐛 **Single tilde rendered as strikethrough** — agents writing `~5 min` got false strikethrough between two tildes. Fix: escape single `~` before marked.parse. `app.js`

## v2.18.0 — 2026-06-03

### Added
- 🔧 **`needs_switch` guard** — after `merge_worker`, session is flagged `needs_switch=True`. Sending tasks to a merged worker returns 400 error until `switch_worker_branch` is called. Eliminates LLM-dependent "remember to switch" failure mode. `session.py`, `main.py`
- 🔧 **`merge_worker(next_task_id=)` atomic merge+switch** — optional parameter auto-switches to new branch after merge. One tool call instead of two. `mcp_stdio.py`, `main.py`
- 🔧 **Auto-cleanup stale worktrees** — on startup + every 24h, scans `worktrees/` and removes directories without active DB sessions. Checks dirty tree before removal. `workspace.py`, `manager.py`
- 🔧 **Cross-project `send_message`** — fallback to `ensure_loaded_any(name)` when same-scope lookup fails. Orchestrators can now message agents in other projects. `main.py`

### Fixed
- 🐛 **System prompt lost on compact/resume** — `backend_claude.py` had mutually exclusive `if resume_id` / `else` branches: resuming a session skipped `system_prompt` entirely. Fix: always set `system_prompt`, then optionally set `resume`
- 🐛 **Compact summary invisible in dashboard** — `session.py` sent compact preamble via `backend.send()` without `_log()`. Fix: added `_log("user_message", ...)`
- 🐛 **`switch_worker_branch` blocked after squash merge** — overly strict `merge-base --is-ancestor` check rejected worktrees diverged by squash merge. Fix: `git reset --hard from_ref` before branch switch. `workspace.py`
- 🐛 **Send errors hidden in dashboard** — `mcp__orchestra__send_message` renderer returned `null` on failure, silently hiding errors. Fix: show red `❌` with error text. `app.js`
- 🐛 **Spawn bubble text wrapping** — `task.slice(0, 200)` cut markdown mid-line, breaking bullet lists. Fix: cut at newline boundary. `app.js`
- 🐛 **Merge didn't update session** — `merge_session` reset worktree files but left `session.branch` and `session.task_id` stale. Dashboard showed outdated branch info. Fix: update session fields after merge. `main.py`

## v2.17.0 — 2026-06-01

### Changed
- **Merged `codex-review` module into `codex-debate` skill** — one skill, two modes: **Quick Review** (one-shot `codex exec review`/`codex exec` for pipeline Phase 2/3, no session) and **Debate** (multi-round persistent sessions, existing). All Bash rules preserved: `timeout: 300000` on the Bash tool, `timeout 300` wrapper, `EXIT:$?` check, `HTTPS_PROXY= HTTP_PROXY=`, anti-hallucination, MCP `codex_review()` as legacy fallback. `app/prompts/skills/codex-debate.md`

### Removed
- **`app/prompts/modules/codex-review.md`** — folded into the codex-debate skill. Removed `codex-review` from `modules:` in full-cycle, worker, reviewer; full-cycle body refs now point to the codex-debate skill (Quick Review)

### Added
- **`codex-debate` skill on orchestrator** — `skills: [html-artifacts, vps-deploy, codex-debate]` so the orchestrator can invoke Codex review directly when needed

### Reasoning
Two overlapping Codex prompts (review module + debate skill, both added via separate tasks #43/#46) caused divergence and double maintenance. Consolidated: review is just debate's one-shot mode. Skill > module here because Codex review is invoked on demand (lazy-loaded native skill), not needed in every turn's system prompt.

## v2.16.0 — 2026-06-01

### Fixed
- 🐛 **Zombie workers after restart** — `auto_resume_all` flipped ALL non-idle rows to idle, including archived. Killed workers resurrected every restart. Fix: only flip `running`/`waiting` → `idle`, leave `archived` alone
- 🐛 **Deepgram SSL BAD_RECORD_MAC** — aiohttp 3.13+ defaults trust_env=True → picks up VLESS proxy → TLS record corruption. Fix: explicit trust_env=False + ssl=certifi
- 🐛 **Codex through proxy → Reconnecting 5/5** — Codex CLI inherited HTTPS_PROXY (VPS tunnel) → OpenAI API unreachable. Fix: strip proxy env from codex commands
- 🐛 **User message duplication** — pending bubble not cleaned after SSE delivers real message. Fix: track finalized bubble ref
- 🐛 **send_file silent false-positive** — returned "File sent to TG" on non-JSON TG response. Fix: validate response, explicit error on failure
- 🐛 **Tinyproxy MaxClients exhaustion** — old VPS Tunnel (12338) connections filled Tinyproxy pool. Fix: MaxClients 50→200, Timeout 600→120

### Added
- 🔧 **SSH tunnels in lifespan** — 3 SSH tunnel proxies (Ёжик/Timeweb/Fornex) start/auto-restart from Orchestra lifespan via SSH_TUNNELS env. No separate systemd services needed
- 📋 **Prompt best practices** — Codex bash-primary (not MCP), orchestrator merge/kill safety (worker_wip before kill, cherry-pick on conflict), codex-review module rewritten
- 🔧 **Modular prompts** — `_load_modules()` in manager.py, `modules:` frontmatter key in roles → git-workflow, codex-review, report-format auto-injected
- 📊 **Proxy dashboard** — 4 proxies (Hiddify, Ёжик, Timeweb NL, Fornex NL) configured and benchmarked
- 🔒 **Security** — passwords removed from git history (BFG), .gitignore for sensitive docs + artifacts

### Fixed (11 P2 bugs from review #35 — task #42)
- Reconnect backoff cap (5 failures → give up)
- Hibernate pending messages guard
- GC task protection (`_spawn_bg` for all create_task calls)
- Log retention + WAL checkpoint
- rawMaxTokens from SDK instead of CONTEXT_LIMITS
- ~95 lines dead code removed (backend.py, 3 DB funcs, _react_processing, aliases)

## v2.15.0 — 2026-06-01

### Fixed (13 P1 bugs from review #35 — task #40)
- 🐛 **SDK errors silent (worst bug)** — `_convert` hardcoded `"ok": True`; `ResultMessage.is_error`/`errors`/`permission_denials` and `AssistantMessage.error` never read → auth/billing/rate-limit failures ended the turn as a normal idle, fired auto-report as success. Fix (`backend_claude.py`): `ok = not is_error`, surface `errors` in `turn_end` meta + `AssistantMessage.error` as an `error` event; `permission_denials` logged (informational, does NOT flip `ok`). `session.py _handle_turn_end` logs `turn FAILED` and `_fire_auto_report` skips when `_last_turn_ok` is False
- 🐛 **ThinkingBlock dropped** — extended thinking silently discarded → looked like a hang. Fix: `ThinkingBlock` branch in `_convert` → `"thinking"` event, logged in `_handle_event`
- 🐛 **dead `usage["iterations"]` branch** — SDK never emits `iterations`; the `if iters:` cost loop was dead, `last = iters[-1] if iters else usage` was noise. Fix: deleted, cost from flat usage dict
- 🐛 **billing-derived context_pct wrong** — `_convert` computed ctx% from billing tokens (input+cache) against CONTEXT_LIMITS, overwritten ~1s later by `get_context_usage()` → transient wrong %, spurious "context corrected" jumps. Fix: stopped computing it (meta `context_pct=0`); `_handle_turn_end` keeps prev `_last_context` when incoming is 0; auto-compact triggers on `live_pct` from `_last_context`
- 🐛 **cost under-counts after reconnect/compact** — `total_cost_usd` is cumulative per session_id; on a new session_id it resets smaller → `max(0, new-last)` clamped to 0 → first turn after every compact contributed $0. Fix (`session.py:_handle_turn_end`): reset `_last_cost`/`_last_cost_cached`=0 when `session_id` changes (before the assignment)
- 🐛 **stale prompt on failed inject** — `_template_hash`/`_prompt_injected`/`system_prompt` set BEFORE `backend.send()` → a failed connect left a false "injected" flag, worker ran rest of life on old instructions. Fix: commit inject flags only AFTER `send()` succeeds
- 🐛 **auto-report empty stop_reason** — manager re-read live `worker._turn_logs` for `stop_reason=`, which `_turn_logs` never contains (it holds text/tool only) → always empty. Fix: `_fire_auto_report` captures `_last_stop_reason` at fire time, passes it to `on_idle(... , stop_reason)`; manager dropped the dead scan
- 🐛 **resume drops `waiting` bg-job state** — `auto_resume_all` excluded `waiting` from the resumable filter and flipped it to idle. Fix: capture `was_waiting`, include `waiting` in filter, restore WAITING post-load if `bg_manager.has_active_jobs` (both worker AND orchestrator loops — Codex)
- 🐛 **`_flush_pending` loses batch on error** — `msgs` extracted + cleared, not requeued on send failure. Fix: `_pending_messages[0:0] = msgs` in except
- 🐛 **squash stats first-ref-only** — `_parse_merged_commits` used `.search()` → multi-task squash commit attributed stats only to the first `#N`, co-refs got zero. Fix: `.finditer()`, attribute commit to ALL distinct refs
- 🐛 **`_log`/`_persist` choke the default thread-pool** — shared with git ops (`asyncio.to_thread`) → 10 agents streaming logs starved merge/spawn. Fix: dedicated `_db_executor()` (ThreadPoolExecutor max_workers=4) for DB writes
- 🐛 **blocking git/merge in the event loop** — `_load_from_db` ran `git rev-parse` sync at resume; `/merge` + `/switch-branch` ran `merge_worktree_to_main`/`switch_worktree_branch` (fcntl.flock + ~10 subprocess) SYNCHRONOUSLY in async endpoints → froze the whole loop. Fix: `asyncio.to_thread` for all three
- 🐛 **stream_logs DB connection churn** — `get_logs` opened a fresh `_conn()` (fd + 3 PRAGMAs) every 0.5–2s tick per SSE/TG poller. Fix: `get_logs(conn=...)` optional connection; SSE + TG loops reuse one connection (try/finally close) with adaptive backoff (0.5→3s / 2→5s when idle)
- 🐛 **split-brain DB (tm.py)** — `tm.py` hardcoded its own `DB_PATH`+`_conn()`, ignoring `ORCHESTRA_DB_PATH` → tasks in one file, sessions in another for tests/worktrees. Fix: deleted the dup, `from app.db import _conn` (one path resolution)

**Known tradeoff:** 2 items deferred to separate tasks — #15 (scope-level spawn lock, larger design change) and #17 (persist `_pending_messages` to inbox table, heavy feature for a rare edge).

**Triggered case:** review #35 found 19 P1s; #39 fixed the 7 P0s, this round fixes the P1s. The error-silence bug (#1) was the worst — an autonomous orchestrator can't see a rate-limited/billing-dead worker reporting "done" with empty output.

## v2.14.0 — 2026-06-01

### Fixed (7 P0 bugs from review #35 — task #39)
- 🐛 **compact() re-entry corruption** — no re-entrancy guard + `_compacting` cleared BEFORE the ack send. `_auto_compact()` (ctx>90%) and a manual `compact_worker` could enter `compact()` concurrently, racing on `session_id`/`_backend`/`_listen_task` → `RuntimeError: not connected`, dangling client, or permanent `session_id=None` (full context loss). Fix (`session.py` `compact()`): guard `if self._compacting: return {...}` set synchronously at entry; `_compacting` held True across the ack turn; ack sent via `backend.send()` directly (bypasses `send()`'s pending-queue gate)
- 🐛 **compact 60s blind poll → fabricated success** — `compact()` returned `{"ok": True}` after a 60s sleep-poll regardless of whether the ack turn completed. Fix: `_compact_ack_event` (asyncio.Event) bound to `_compact_ack_gen`; `_handle_turn_end` sets it only for the matching turn gen; `await wait_for(event, 60)` → `{"ok": False, "error": "ack turn did not complete"}` on timeout. A stray `_flush_pending`/heartbeat turn can no longer false-positive the ack (Codex finding #2)
- 🐛 **persist race resurrects stale state** — full-row `save_session(_to_db_dict())` fired from `_handle_turn_end` (438) and `_refresh_context_from_api` (704) on unordered executor threads → a stale `status=running` snapshot could overwrite a fresh `status=idle`. Fix: single-flight persist (`_persist_task` + `_persist_dirty` coalescing in `_persist_loop`). Last snapshot always wins; `get_running_loop()` fails loud off-loop; done-callback logs crashes; in-loop try/except so one DB error doesn't stop future writes
- 🐛 **merge vs remove worktree race** — `merge_worktree_to_main` held `.git/orchestra-merge.lock` but `remove_worktree` took NO lock → removing a worktree mid-merge could abort the merge / leave repo on wrong branch. Fix: `remove_worktree` now acquires the same `fcntl.flock(LOCK_EX)` on `orchestra-merge.lock`
- 🐛 **orphaned worktree on spawn crash** — `create_session` except block only called `delete_session`, leaking the worktree if `start()`/`_inject_skills`/`_safe_format_prompt` raised after creation. Plus `create_worktree` itself leaked if `git worktree add` succeeded but the PROJECT_FILES copy then raised (Codex #4). Fix: rollback inside `create_worktree` (post-add copy wrapped, removes worktree on failure) + `remove_worktree` in the manager except block
- 🐛 **zombie CLI on connect timeout** — `ClaudeBackend.connect()` left `_client` set (subprocess alive) on timeout/exception, never disconnected. `reconnect()` had the identical leak (used by heartbeat/listener recovery), and `except Exception` missed `CancelledError` (Codex #5). Fix: shared `_cleanup_failed_client()`, `except BaseException` → disconnect → re-raise, in both `connect()` and `reconnect()`
- 🐛 **restart_cli → 500** — `/api/sessions/{name}/restart-cli` called `session._disconnect_client()` which doesn't exist (`AttributeError`). Fix: `_disconnect_backend()` + imported `AgentStatus` for `AgentStatus.IDLE`

### Known tradeoff
- **P1-1 (session_id NULL window) fixed as a side-effect** — Codex review (#1) showed the ack turn needs a FRESH SDK session (no resume token) so compaction actually drops context, but the *persisted* `session_id` must NOT be nulled. New `force_fresh` param on `_make_backend`/`_ensure_backend`: ack runs on a fresh session while the old token stays in DB until the ack `turn_end` writes the new one → crash mid-compact now resumes old context instead of losing everything

### Fixed (2nd Codex round — diff review)
- 🐛 **compact COMPACT_PROMPT phase unlocked** — the summary turn (`backend.events()` loop) didn't hold `_lifecycle_lock`, so a `_flush_pending` already past its outer `_compacting` check could interleave a non-ack turn. Fix: wrap the COMPACT_PROMPT phase in `_lifecycle_lock` + recheck `_compacting` INSIDE the flush's lock body (requeues if compact won the race)
- 🐛 **ack-timeout left turn running** — on the 60s ack timeout `compact()` cleared `_compacting` while the ack turn could still be live. Fix: `_disconnect_backend()` + status IDLE before returning, so no stale turn interleaves with the next send
- 🐛 **force_fresh ignored if backend exists** — `_ensure_backend(force_fresh=True)` returned the existing backend. Now disconnects + rebuilds fresh (correctness, not just-happens-to-work in compact)
- 🐛 **spawn cleanup missed CancelledError** — `create_session` except was `except Exception` → cancellation skipped worktree cleanup. Now `except BaseException`

### Reasoning
Full research → plan → Codex review (×1 plan) → implement → Codex review (×1 diff) → fix → tests. Codex found 5 holes in the PLAN + 4 more in the DIFF (1 P0, 3 P1), all incorporated. 17 new tests (`test_session.py`, `test_backend_claude.py`, `test_workspace.py`), 86 passing (6 pre-existing failures on clean HEAD are unrelated — stale `AUTO_REPORT_IDLE_SEC`/`remove` tests). Docs: `docs/tasks/39/{research,plan,findings,codex-diff-review}.md`

## v2.13.0 — 2026-06-01

### Fixed
- 🐛 **[1m] suffix stripped — ALL agents on 200K instead of 1M** — `_make_client()` did `model.replace("[1m]", "")` before passing to CLI. CLI REQUIRES `[1m]` suffix to enable 1M context window (`claude-opus-4-6` = 200K, `claude-opus-4-6[1m]` = 1M). Every [1m] agent in Orchestra silently ran on 1/5 of their context. Fix: pass `self.model` as-is, no stripping
- 🐛 **compact_boundary invisible** — CLI `SystemMessage` with `subtype="compact_boundary"` was not caught by any branch in `_convert()`. Now emits status event "CLI auto-compacted (trigger): pre→post tokens"
- 🐛 **max_tokens from API** — `_refresh_context_from_api()` now updates `max_tokens` from SDK alongside percentage and total_tokens

### Reasoning
CLI changelog 2.1.75: "Added 1M for Opus 4.6 by default for Max plans" — but ONLY when model name includes `[1m]` suffix. Our `_make_client` stripped it → CLI saw `claude-opus-4-6` (200K). Betas approach (`context-1m-2025-08-07`) also doesn't work on subscription ("Custom betas are only available for API key users"). The ONLY way to get 1M on subscription is passing the full model name with `[1m]`.

## v2.12.0 — 2026-05-31

### Fixed
- 🐛 **Phantom context loss** — `context_pct` was reverse-engineered from `ResultMessage.usage` iterations (last iteration tokens / model limit), NOT actual context window size. Replaced with authoritative `get_context_usage()` SDK method. Fixes wildly swinging % after tool-heavy turns
- 🐛 **CLI silent autocompact invisible** — Claude CLI has its OWN internal autocompact that fires independently. We now log when authoritative % diverges >20% from estimate ("context corrected: X% → Y%")
- 🐛 **Compact crash window** — `compact()` NULLed `session_id` and persisted before starting fresh session. Server restart in that window → agent not resumed (auto_resume_all filters NULL). Removed premature persist
- 🐛 **Stale 0% after resume** — `_last_context` not refreshed until first turn_end after reconnect. Now `_refresh_context_from_api()` fires on backend connect
- 🐛 **`_compacting` double-managed** — both `_auto_compact()` and `compact()` set/cleared flag. Now `compact()` is sole owner
- 🐛 **Multiproject scope UNIQUE crash** — `ensure_project()` crashed on UNIQUE(scope) when same agent created tasks in 2+ projects. Now skips scope binding if already bound to different project

### Added
- 🎨 **Role icons from frontmatter** — `icon:` field in role MD files (`app/prompts/roles/*.md`). `/api/role-icons` endpoint serves role→emoji map. Frontend + MCP load dynamically instead of hardcoded maps
- 📁 **New role templates** — `sub-orchestrator.md` (🎯), `reviewer.md` (🔍), `watcher.md` (👁️) with frontmatter + minimal prompts
- ✅ **#34 tg_topic** — `tg_topic` bool parameter for per-agent TG topics. Root orchestrators get `tg_topic=True` automatically. API: `POST /api/sessions/{name}/tg_topic`

### Changed
- `backend_claude.py` — new `context_usage()` method wrapping `ClaudeSDKClient.get_context_usage()`
- `session.py` — `_refresh_context_from_api()` called on turn_end + backend connect; `_auto_compact` simplified to just delegate to `compact()`

### Reasoning
Context bug was a CLUSTER of 5 root causes (RC1-RC5), found by Opus research worker + Codex cross-review. Primary: per-iteration token estimate ≠ actual context window, and CLI internal autocompact runs invisibly. Fix A (authoritative API) + Fix C (no NULL persist) + Fix D (refresh on resume) + Fix E (single flag owner) applied. Full research in `docs/research-context-bug.md`.

## v2.11.0 — 2026-05-31

### Added
- 📁 **Change orchestrator scope/repo_path without losing session** — move an idle orchestrator to a new root folder while preserving its Claude `session_id` (context survives via resume). `POST /api/orchestrators/{name}/change-scope` `{old_scope, new_scope, new_cwd?}` + context-menu item "Сменить папку" in the dashboard. MVP scope: orchestrator-only, idle-only, no live workers in the old scope
- `db.change_scope()` (`app/db.py`) — single transaction: move `sessions.scope+cwd`, optional `tm_projects.scope` migration (skip on UNIQUE collision), active `bg_jobs.target_scope`, `test_lock.scope`. Gated on `WHERE id=? AND scope=old_scope` → aborts before any migration on a stale/concurrent retry (no partial move)
- `manager.change_orchestrator_scope()` (`app/manager.py`) — guards (orchestrator-only, `is_dir`, no live workers via `_live_workers_in_scope` scanning memory + DB), all under `session._lifecycle_lock` (idle race). Rebuilds `mcp_servers` via `_make_mcp_config` so the lazy reconnect gets the new `ORCHESTRA_SCOPE`; `session.id` (dict key) unchanged

### Changed
- **`_is_safe_path` containment** (`app/main.py`) — replaced `startswith(root)` with `os.path.commonpath` containment. Closes sibling-prefix escape (`/tmproot_escape` no longer passes as inside `/tmp`). Affects ALL path-guarded endpoints, not just change-scope
- **Persist drain fence** (`app/session.py`) — `_persist()` now tracks every `run_in_executor` save future in `_persist_futs` (set, auto-discarded on done); new `_drain_persist()` awaits all pending. change-scope drains in-flight persists after backend disconnect and before the DB transaction, so the transaction is the last writer of `scope+cwd` (prevents a stale `save_session(old_cwd)` clobbering cwd → wrong root after restart)

### Reasoning
`scope` is the orchestrator's identity key (UNIQUE(name,scope)), woven through 5 DB tables, the MCP subprocess env, CWD, and dashboard tabs. The hard part isn't renaming a path — it's keeping the move consistent under concurrent control-plane ops. Three Codex-flagged cross-layer races were closed: stale/partial DB migration, worker-spawn TOCTOU (in-lock re-check; full scope-level spawn lock deferred), and async-persist cwd-clobber (set-based drain). Session context is preserved because `session_id` is independent of scope.

### Known tradeoff
- Worker-spawn TOCTOU is mitigated (in-lock re-check) but not fully closed — a true close needs a scope-level lock shared with the spawn path. Acceptable for the "orchestrator with no live workers" MVP; flagged as follow-up

## v2.10.0 — 2026-05-31

### Added
- 🛡️ **Directory ownership at spawn** — `spawn_worker(..., owned_dirs='["app/api/"]')`. New `owned_dirs TEXT` JSON column in `sessions`. At spawn, overlapping dirs with a live worker (idle/running, same repo) → advisory warning to orchestrator (NOT blocked). Injected into worker prompt as off-limits siblings. `parse_owned_dirs()`/`dirs_overlap()` (prefix-aware) in `workspace.py`
- 🛡️ **Pre-dispatch conflict simulation** — `check_conflict(worker_a, worker_b)` MCP tool + `POST /api/sessions/check-conflict`. `simulate_conflict()` in `workspace.py` dry-runs `git merge-tree --write-tree`, reports conflicting paths (regex-parsed, handles content + modify/delete). Pick merge order before collisions happen
- 🛡️ **Worker WIP visibility** — `worker_wip(name, base_ref)` MCP tool + `GET /api/sessions/{name}/wip`. `branch_wip_status()` shows uncommitted files + unmerged commit subjects before resuming a worker. Returns `{error}` on git failure, never a false "clean"
- 🔒 **Block ScheduleWakeup + Cron\* tools** — removed from all agents via `disallowed_tools`. Orchestra manages scheduling via bg_jobs, agents don't need client-side scheduling

### Changed
- **Safer auto-commit** — `_auto_commit_if_dirty()` (`manager.py`) no longer silently commits dirty source-repo state before spawn. Loud labelled WIP commit (branch + file list), fail-loud on git `status`/`add`/`commit` returncodes, warning surfaced to orchestrator via `spawn_warning`
- **Worker WIP commit prompt** — `worker.md` now mandates descriptive WIP commits (`WIP: #49 — done X, Y; TODO: Z`) instead of bare `WIP`

### Reasoning
Parallel workers in isolated worktrees can silently collide (same files) or bury source-repo work (silent auto-commit). These three advisory tools surface collisions to the orchestrator at decision points (spawn, resume, pre-merge) without blocking — fits the small-team MVP "warn, don't gate" philosophy.

## v2.9.4 — 2026-05-31

### Added
- **Module `codex-review.md`** — single source for Codex review rules: when to call (`exec` for plans, `review` for diffs), `codex_review(target, output, mode)` syntax, iterate-to-consensus, MCP-only (not bash/skill), PROJECT CONTEXT via `context`. Wired into `worker` + `full-cycle` via `modules:`. `app/prompts/modules/codex-review.md`
- **Module `report-format.md`** — single source for report shapes: DONE / WIP-STOPPED / pipeline-gate messages via `send_message`. Wired into `worker` + `full-cycle`. `app/prompts/modules/report-format.md`

### Changed
- **Dedup across roles** — removed inline Codex rules and `<report-format>` block from `worker.md`; replaced inline Codex syntax + DONE format in `full-cycle.md` Phase 2/3 with module references. Roles now carry only role-specific workflow; shared rules live in modules. `app/prompts/roles/worker.md`, `app/prompts/roles/full-cycle.md`

### Reasoning
Follow-up to prompt audit. Codex review + report format were duplicated/divergent across worker and full-cycle (two different DONE formats) → consolidated so the orchestrator parses one shape and Codex usage is consistent.

## v2.9.3 — 2026-05-31

### Changed
- **Git-rule dedup** — removed the `<git>` block from `worker.md` body (duplicated `modules/git-workflow.md`, injected via `modules: [git-workflow]`). The one non-dup behavioral rule ("workers do NOT create/switch branches themselves") moved into the module so it reaches all roles. `app/prompts/roles/worker.md`, `app/prompts/modules/git-workflow.md`
- **AskUserQuestion/Monitor compressed** — two NEVER lines merged into one in `base.md` (both denied via permission hook; kept short in case the model sees the tool). `app/prompts/base.md`

### Added
- **Worker context-limit rule** — `worker.md`: on CONTEXT CRITICAL → finish current sub-task, commit, report progress, do NOT start new sub-tasks. Closes audit gap 5.1
- **Full-cycle gate-idle rule** — `full-cycle.md`: explicit "do NOT self-approve and start implementation before orchestrator approves". Closes audit gap 5.2

### Reasoning
P2 batch from prompt audit (docs/tasks/prompt-audit/). Determinism-focused: dedup keeps git rules single-source (the module), the two new rules close behavioral gaps where Opus might improvise (start new work near context limit / self-approve a plan).

## v2.9.2 — 2026-05-31

### Fixed
- **Stale Codex instruction in worker.md** — `Skill(skill="codex-review")` → `codex_review()` MCP tool. worker.md lagged behind the v2.9.0 migration to the native tool (full-cycle.md already correct) → generic workers asked for Codex review followed the obsolete path. `app/prompts/roles/worker.md`
- **report_bug scope conflict** — base.md said "platform bug only", project CLAUDE.md said "any error". Disambiguated in base.md: `report_bug` = Orchestra platform/MCP/SDK/harness failures; task-code bugs → `docs/tasks/<id>/` + orchestrator message. `app/prompts/base.md`
- **bg_create cron drift** — `<background-jobs>` listed only one-shot types and stated "Jobs are one-shot", but `cron` (recurring, added #26 in v2.9.0) was undocumented for agents. Added `cron` to the list, corrected the blanket one-shot claim. `app/prompts/base.md`

### Changed
- **orchestrator.md `<tools>` trimmed** — removed bare tool signatures that duplicate MCP tool descriptions; kept only non-obvious constraints (must be idle, do-not-retry, debugging-only) and the routing map. ~14 lines saved per orchestrator turn without losing one-path routing. `app/prompts/roles/orchestrator.md`

### Reasoning
Result of prompt audit (docs/tasks/prompt-audit/). Codex cross-review corrected 2 v1 errors (run_in_background IS enforced via permission hook; Agent/Task stripped only for orchestrators, load-bearing for workers) → mass NEVER-rule deletion was cancelled. Calibration: for MVP, determinism > token minimalism. P0 manager.py:391 (orchestrator custom prompt replaces role template) tracked separately as #28 (backend, not in this commit).

## v2.9.1 — 2026-05-31

### Fixed
- 🍒 **merge_worker unrelated histories** — `git merge-base` detects unrelated histories before merge attempt. Falls back to `_cherry_pick_branch()` which replays commits individually via `git cherry-pick --no-commit`. Clean linear history, no fake merge nodes. `workspace.py`

### Changed
- **merge precheck flow** — `git merge-base` check added before `merge-tree --write-tree`. Unrelated histories skip precheck entirely (it would fail anyway) and go straight to cherry-pick strategy
- **Prompt restructuring** — all role prompts migrated to XML tags (`<role>`, `<rules priority="critical">`, `<tools>`, etc). Critical rules deduplicated into `base.md`. English-only prompts
- **Native skills** — skills copied as `worktree/.claude/skills/{name}/SKILL.md` instead of system prompt injection. `_inject_skills_to_worktree()` in `manager.py`
- **Agent role in dashboard** — info panel shows role (worker/orchestrator/full-cycle) in purple
- **Cost precision** — `.toFixed(2)` instead of rounded integer
- **File preview** — Download button + Open in browser button for HTML files

### Added
- 🧠 **Opus 4.8** model option in all frontend model pickers

## v2.9.0 — 2026-05-29

### Added
- 🔁 **Cron agents** (#26) — `bg_create(type="cron", cron_expr="*/5 * * * *")` recurring background jobs. Fires on schedule via `croniter`, survives restart. Non-terminal trigger keeps job `active`. `no_expiry` via `timeout_seconds=0`. `bg_jobs.py`, `db.py`, `mcp_stdio.py`
- 🔌 **MCP per agent** (#24) — `spawn_worker(mcp_servers='{"playwright": {...}}')` attaches custom MCP servers to workers. Persisted in DB (`mcp_servers_custom` column), re-merged on restart. Guards `orchestra` key from override. `manager.py`, `main.py`, `mcp_stdio.py`, `session.py`, `db.py`
- 🛡️ **validate_spawn** (#25) — `can_spawn: [worker, full-cycle]` in role YAML frontmatter. Parent role whitelist enforced in `create_session`. Absent/empty = allow all. `manager.py`, `mcp_stdio.py`
- 🤖 **codex_review MCP tool** — native `codex_review(target, output, mode)` tool. Runs Codex CLI via `bg_create(type="run")`, notifies worker on completion. Replaces bash/skill workaround. `mcp_stdio.py`
- 🎨 **Pretty tool result rendering** — `get_worker_info`, `send_message`, `get_worker_logs` results rendered as styled cards instead of raw JSON. `app.js`
- 🔧 **Skills library** — `app/prompts/skills/` directory with YAML frontmatter. Roles select skills via `skills: [html-artifacts]` in frontmatter. Auto-injected into system prompt via `_load_role_skills()`. `manager.py`
- 📋 **Click-to-copy inline code** — click `<code>` in chat to copy text (like Telegram). URLs/IPs open in new tab instead. Toast notification on copy. `app.js`, `style.css`
- 🔗 **Autolink URLs/IPs** — bare URLs and IP addresses in markdown auto-wrapped in `<a>` tags. DOM walker skips `<a>`, `<pre>`, `<code>`. `app.js`
- 🏷️ **Full-cycle role** — 3-phase pipeline (Research → Plan+Codex → Implement+Codex) with 2 orchestrator approval gates. All artifacts to `docs/tasks/<id>/`. `app/prompts/roles/full-cycle.md`

### Changed
- **codex-review skill removed** — migrated to native `codex_review()` MCP tool. `full-cycle.md` updated to reference MCP tool. `app/prompts/skills/codex-review.md` deleted
- **Reviewer/Watcher roles removed** — vanilla Orchestra ships with orchestrator, worker, full-cycle. Custom roles via constructor

### Fixed
- 🔗 **URL in code copies instead of opening** — clicking URL inside backticks now navigates instead of copying to clipboard. `app.js`

### Known issue
- 🧪 **Pre-existing test failure** — `TestRemoveScope::test_passes_orch_names_to_tg_bridge_when_flag_set` (KeyError 'names'). Unrelated to v2.9 changes

## v2.8.0 — 2026-05-27

### Added
- 🚀 **Deploy script** — `deploy/install.sh root@IP` ставит Orchestra на чистый VPS за 5 мин. systemd + nginx + .env с рандомными кредами. `deploy/`
- 🔐 **Test lock** — глобальный лок для параллельных тестов. `acquire_test_lock`/`release_test_lock` MCP tools + API + DB table (PR #1, Вадим)
- 🌿 **Base branch** — воркеры ответвляются от произвольной ветки (не только main). `spawn_worker(base_branch="feature/x")`, `switch_worker_branch(from_ref=)`. Merge в произвольный target (PR #1)
- 📊 **Progress bar** — `update_progress(percent, status)` показывает индиго-бар в карточке агента + инфо-панели + красивый рендеринг в ленте логов. `app/static/js/app.js`, `app/session.py`
- 📈 **Usage sparkline** — 7d график с понедельной навигацией (◀ ▶), midnight разделители, split по сбросам. Forward-fill пробелов в данных. `app/db.py`, `app/static/js/app.js`
- 💰 **cost_usd_cached** — расчёт стоимости с учётом prompt cache (cache_read×0.1 + cache_create×1.25). `app/backend_claude.py`, `app/session.py`, `app/models.py`
- 🔔 **TG @mention** — `TG_USER_MENTION` env для тега юзера в речи агента (не в agent-to-agent). (PR #1)
- 📱 **TG topic collision** — `_pick_unique_topic_name()`: pm-taksa → pm-taksa-2 при коллизии. Backward-compat. (PR #1)
- 🗑️ **TG topic cleanup** — чекбокс "Удалить TG-топики" при удалении проекта. Модалка. (PR #1)
- ⏱️ **Jobs UI** — realtime таймер (elapsed + expires каждую секунду), expandable details по клику, persistent expanded state
- 💳 **Payment auto-resolve** — `payment_receive` без client параметра, определяет клиента по scope проекта автоматически

### Changed
- **Codex token prices** — обновлены с заниженных ($1.25/$10) до реальных ($5/$30 per 1M). `backend_codex.py`
- **TG flood handling** — 3s min interval, important/unimportant prioritизация, drop tool/status при flood. `tg_bridge.py`
- **TG long messages** — `_split_message()` разбивает на чанки по 4096 вместо молчаливой обрезки
- **Worker prompt** — `update_progress` добавлен в инструкции воркеров

### Fixed
- 🔴 **cost_usd overcounting x85** — CLI отдаёт cumulative cost, мы складывали как delta. $24,609 → $302 реальных. Delta tracking + реконструкция из логов. `session.py`, `db.py`
- 🧟 **Codex zombie detection** — `_codex_turn_loop` не ставил IDLE при timeout/error. Heartbeat проверял backend=None → skip. Теперь: finally блок + zombie check до backend check. `session.py` (#11)
- 💥 **Compact running crash** — event loop обращался к None backend. Guard + disabled кнопка на фронте. `session.py`, `app.js` (#12)
- 📝 **report_bug permission denied** — воркеры писали напрямую в файл из worktree. Теперь через API endpoint. `mcp_stdio.py`, `main.py` (#13)
- ⚡ **TG иконка не возвращалась** — `_handle_turn_end` не логировал "turn ended" → stream_logs не ловил для icon update. `session.py` (#14)
- 🔇 **TG реакции убраны** — 👍/👂 на каждое сообщение убраны. `tg_bridge.py`
- 🔓 **Auth на /send** — POST /api/sessions/*/send был доступен без авторизации. (PR #1)
- 🤖 **Disallowed sub-agents** — оркестраторы спавнили Claude sub-agents вместо MCP spawn_worker. (PR #1)
- 🗑️ **manager.remove() leak** — не удалял session из DB, оставлял сироту. (PR #1)
- 🧪 **Test suite revival** — 128 passed, 5 skipped. conftest.py с моками, ORCHESTRA_DB_PATH изоляция. (PR #1)
- 📁 **/tmp allowed** — send_file из /tmp возвращал "access denied"
- 🌐 **Global exception handler** — все 500 теперь логируются с traceback
- 📊 **5h sparkline** — убраны лишние midnight линии (14 на 2 недели данных), обрезка до текущей недели

## v2.7.0 — 2026-05-21

### Added
- 🔒 **Dashboard Auth** — cookie session login/password из .env (`DASHBOARD_USER`/`DASHBOARD_PASSWORD`). Deterministic HMAC token переживает рестарты. 30-day cookie. Backward compat — без переменных = открытый доступ. `app/auth.py`, `login.html`
- 🔒 **Security hardening** — full Codex audit, 6 critical/high fixes: path traversal deny-list (dotfiles, .db, .key), internal token auth для MCP callbacks, upload extension blocking, safe_path на send_file/session create, limit caps на SSE/logs, rename validation
- 📊 **Task priorities** — 0=critical 🔴, 1=high 🟠, 2=medium 🟡, 3=low 🟢. CSS dots в task panel. Сортировка по priority. MCP tools `task_create(priority=)`, `task_update(priority=)`
- 📦 **Worker description** — `description` поле при spawn, `update_worker_description()` tool, отображается в `list_agents` + info panel + list_agents bubble
- 🔍 **get_worker_info** — MCP tool возвращает полную инфу включая system_prompt (500 chars), description, stats
- ✏️ **update_worker_prompt** — MCP tool обновляет system_prompt воркера
- 🗄️ **Archive workers** — kill_worker теперь архивирует (status=archived) вместо удаления. Логи и статистика сохраняются. Archived не блокируют повторный spawn
- 📈 **Session statistics** — `total_turns`, `total_input_tokens`, `total_output_tokens`, `total_tool_calls` трекаются per session. `/api/stats` endpoint
- 💰 **Payment journal** — автоматическая таска-журнал в YouGile. Description обновляется при каждом `payment_receive`. Баланс + пополнения + распределения
- 📂 **File tree auto-refresh** — поллинг открытых папок каждые 10 сек, diff-update без моргания
- 📎 **Drag & drop файлов** — drop на textarea загружает файл, вставляет путь. Drop hint при dragover
- 🕐 **Timestamps в сообщениях** — `[HH:MM]` prepend для LLM, strip в dashboard и TG mirror
- 🔄 **Mid-turn inject восстановлен** — Claude: try inject → fallback queue. Codex: always queue
- 🪞 **Mirror send_file** — файлы зеркалятся в TG топик агента
- 📋 **Tab context menu** — правый клик на таб: скрыть/удалить. Wheel scroll. Кнопка скрытых табов
- ⚖️ **AGPL-3.0 license** — dual licensing: AGPL + commercial от ООО «Сидон»
- 🚀 **VPS deployment support** — полный деплой-гайд, systemd service, nginx config, auth, security audit

### Changed
- **Task prefixes removed** — `PAR-49` → `#49`. Plain numbers, legacy prefixes accepted. `format_task_ref()`, `resolve_task_ref()`, workspace branches `task-N/name`
- **Proxy parametrized** — `HTTPS_PROXY` из os.environ, не hardcoded. cli_path через `CLAUDE_CLI_PATH` env
- **Merge auto-stash** — `merge_worker` автоматически stash/pop при dirty main repo
- **MCP scope passthrough** — `task_get`/`task_update` передают scope для disambiguación
- **Rename full** — обновляет system_prompt identity + git branch + DB
- **Compact блокирует send()** — сообщения в очередь во время compact, доставляются после
- **Auto in_progress** — spawn_worker/switch_worker_branch с task_id автоматом ставит in_progress
- **bg_jobs cleanup** — triggered/expired/cancelled jobs старше 24h автоудаляются
- **Scope MCP servers** — воркеры получают MCP из `.mcp.json` проекта (Playwright и т.д.)

### Fixed
- 🔴 **Crash loop sr/nt** — `_handle_turn_end` использовал удалённые переменные → listener reconnect loop
- 🔴 **Compact interrupted** — incoming messages во время compact → empty summary → cascade crash
- 💲 **Double "kk"** — price "8k" + фронт "k" = "8kk". Backend уже форматирует
- 🏷️ **Universal prefix strip** — `replace('PAR-','')` → regex `/^[A-Z]+-/` для всех prefix'ов
- 🔐 **Internal token для всех API** — MCP tools авторизуются через Bearer token, не только /send
- 🍪 **Cookie auth на /send** — фронт отправлял cookie, middleware проверял только token
- 📋 **Ambiguous task numbers** — scope resolves одинаковые номера в разных проектах
- 📂 **Hidden files visible** — убран `startswith('.')` фильтр в /api/files
- 🖱️ **Text selection restored** — document-level drag listeners убивали выделение текста
- 📊 **Sync indicator removed** — бесполезный sync indicator для проектов без YouGile
- 🎯 **Task detail modal** — pretty commits display, scope passthrough, informative task_update bubble
- 🔄 **YouGile description sync** — description пушился в push_update (была только title+column)

## v2.6.0 — 2026-05-14

### Added
- 🔄 **Auto-resume ALL sessions on restart** — `auto_resume_all()` restores orchestrators AND workers from DB (was orchestrators-only). Sessions that were `running` at shutdown get a restart notice injected after 3s: `[system] Orchestra server restarted. Your session was restored — continue where you left off.`
  - `_inject_restart_notice()` in `manager.py` — delayed inject with error handling
  - `auto_resume_orchestrators()` kept as backward-compat wrapper
- 🤝 **Cross-orchestrator awareness** — `_other_orchestrators_block(scope)` dynamically generates a list of all other orchestrators with project names, injected into `ORCHESTRATOR_SYSTEM_PROMPT`. Each orchestrator knows who else exists and can `send_message` them. List updates on restart/compact
- 👤 **TG sender name** — all messages from TG now include `[from TG: Name]` prefix so agents know who's writing. Works for text, photos, files, video, audio, voice, video notes, stickers
- 🔒 **TG polling auto-restart** — `_safe_polling()` wraps `dp.start_polling` with crash recovery (auto-restart after 10s) + logging. No more silent polling deaths
- 📊 **Usage cache persistence** — `data/usage_cache.json` survives server restarts. No more empty usage bar after reboot caused by Anthropic rate limit + cold cache
- 🔀 **merge_worker MCP tool** — orchestrator can merge a worker's branch into main with one call. `git merge-tree` precheck detects conflicts before merging. fcntl lock serializes parallel merges. Auto-commits dirty worktree. `workspace.py`, `mcp_stdio.py`, `main.py`
- 🛑 **stop_worker MCP tool** — interrupt + idle without destroying session/worktree. Resumable via send_message. Separate from kill_worker (full delete)
- 📈 **Worker progress tracking** — `update_progress(percent, status)` MCP tool. Green glow progress bar in sidebar. Resets on new task. `session.py`, `db.py`, `mcp_stdio.py`, `app.js`
- 🖼️ **TG images as photos** — `send_file` auto-detects images (.jpg/.png/.gif/.webp/.bmp) → `send_photo()` for inline preview. `as_document=True` forces file attachment
- 🌿 **Git status in worker cards** — sidebar shows `branch+N 💾N "last commit"` per worker. `GET /api/git-status?scope=` with 10s server cache. Green/yellow/gray coloring
- 💓 **Persistent client heartbeat** — 60s heartbeat detects silent listener death, auto-reconnects with inject notice. Silence warning >300s. Full tracebacks on crash

### Changed
- **Usage cache TTL 120→300s** — backend and frontend polling aligned at 5min to reduce Anthropic API rate limit hits
- **TG logger** — `tg-bridge` logger now has `StreamHandler` + `DEBUG` level, all TG events visible in journalctl
- **SSE disconnect leak** — `stream_session_logs` generator now checks `request.is_disconnected()`, stops on tab close

### Fixed
- 🟢🟡 **TG topic status desynced from frontend** — single source of truth via `_any_running_in_scope(scope)`. When orchestrator finishes turn but workers still running → stays 🟢 (was: immediately 🟡). When ANY worker goes idle → `_notify_scope_idle()` checks scope → flips to 🟡 only when ALL idle
  - `check_scope_idle()` in `tg_bridge.py` — public function called from `session.py` and `stream_logs`
  - `_notify_scope_idle()` in `session.py` — fires on every worker IDLE transition, not just auto-report
- 🟢🟡 **TG topic status on startup** — `_sync_all_topic_statuses()` sets correct 🟢/🟡 on all topics when bridge starts
- 🪞 **TG mirror formatting** — mirror messages now receive `converted` text + `entities` from `md_convert()` (was: raw plain text without formatting). All 3 send paths: text/status, tool, tool_result

## v2.5.0 — 2026-05-11

### Added
- 🚀 **Persistent client + mid-turn message injection** — replaced "fresh client per turn" with persistent client per session. `send()` → `client.query()` directly via SDK stdin transport. No more pending queue, debounce, turn boundary waiting. Messages inject mid-turn as system-reminders
  - `_ensure_client()` — connects once, reuses across turns
  - `_persistent_listen()` — infinite loop over `receive_messages()`, does NOT disconnect on ResultMessage
  - `_disconnect_client()` — clean shutdown helper
  - Auto-reconnect: detects dead listener, retries `query()` on failure
  - Removed: `_pending`, `_debounce_task`, `_turn_task`, `_run_turn()`, `_arm_debounce()`, `_on_debounce()`, `debounce_sec`
- 📊 **Usage status bar** — global bar at top of dashboard. OAuth API (`/api/oauth/usage`) with 120s cache, shows 5h/7d utilization with HSL gradient color (green=under budget, yellow=on track, red=burning fast), reset progress % in parentheses. `/api/usage` endpoint combines Anthropic data + per-agent cost from DB
- 🎯 **Spawn worker bubble** — card with `🚀 Spawning name` + model badge pill (color-coded) + markdown task preview + system prompt + repo path. Single click expands all
- 🌐 **WebSearch result renderer** — bracket-counting JSON parser for Links format, Perplexity markdown with token/cost header, standalone detection when `lastTool` is null. Collapsible (5 lines preview)
- 🔍 **ToolSearch bubble** — `🔍 Loading: query` → `✅ Loaded: ToolName` on result
- 🐛 **report_bug bubble** — `🐛 Bug: title` with collapsible description
- 🖼️ **Base64 image rendering** — tool_results with image data render as `<img>`, not raw base64 text
- 📝 **Textarea resize upward** — drag handle above textarea, pull up to expand (bottom of screen = can't drag down)
- 🔄 **Auto-compact for orchestrators** — removed `not self.is_orchestrator` exclusion, orchestrators auto-compact at >90% context

### Changed
- **`interrupt()`** — uses `client.interrupt()` SDK method instead of asyncio task cancellation
- **`compact()`** — stops listener first (race condition fix), bracket-counted JSON parse, disconnects cleanly
- **Turn timeout** — tracked via `_turn_start` timestamp instead of `asyncio.wait_for()`
- **send_message bubble** — split by lines (5 preview), re-render full on expand. No more mid-word cuts
- **Tool result expand** — line-based preview (was char-based), single element with maxHeight (no gap/separator), universal click-to-expand on all bubble types
- **Model aliases** — `claude-opus-4-6` → `claude-opus-4-6[1m]` auto-resolve
- **Worker custom prompt** — `_safe_format_prompt()` replaces `str.format()`, only substitutes known placeholders. Resume correctly extracts custom portion
- **Load-more tool_result matching** — `_findLastBefore()` constrains querySelector to prepended batch only

### Fixed
- **WebSearch `isEdit` bug** — spawn_worker/WebSearch/ToolSearch bubbles had `dataset.isEdit='1'` which caused tool_result handler to early-return, silently swallowing results
- **WebSearch regex** — replaced fragile regex with bracket-counting parser for Links JSON arrays (handles truncated SDK output, multi-item arrays, special chars)
- **Load-more rendering** — old messages now use `addChatEntry()` with full custom bubbles
- **compact() race condition** — listener paused before iterating `receive_messages()`
- **Persistent client dead process** — `_ensure_client()` checks `_listen_task.done()`, `send()` retries with reconnect on `query()` failure
- **Universal click-to-expand** — audit of all handlers, WebSearch and Read .md fixed (were hint-only)

## v2.4.0 — 2026-05-10

### Added
- 🎤 **TG Voice** — Deepgram Nova-3 транскрипция голосовых в TG bridge
- 📷 **TG Media** — полная поддержка: фото, документы, видео, video_note (ffmpeg), аудио, стикеры, forwards с caption. Кеши файлов + транскрипций
- 🔄 **TG Debounce** — state machine IDLE→COLLECTING→WAITING_MEDIA. 5s debounce + 30s media timeout. Батч сообщений в один turn
- 📂 **File preview** — клик по файлу → модалка. MD рендерится через marked.js, картинки через `<img>`, код с горизонтальным скроллом. `/api/files/content` + `/api/files/raw` endpoints
- ✏️ **Diff view** — Google `diff-match-patch` для char-level inline подсветки. LCS line diff + inline highlight для похожих строк (>40% common). Preview 5 строк + expand
- 📖 **Read view** — code viewer с shimmer skeleton, 5 строк preview + expand. Картинки рендерятся как `<img>`
- ✍️ **Write view** — содержимое как diff (всё зелёное)
- 📨 **send_message bubble** — `📨 → target` + markdown preview вместо сырого JSON
- 📜 **Prompt viewer** — 3 секции (📦 Platform / 🎭 Role / ✨ Custom) с реальными подставленными именами
- 📋 **Compact mode** — toggle 📋/📄 в header. Тулы в одну строку, клик раскрывает
- 🖼 **Картинки везде** — user messages, Read tool, text — кликабельные → file preview
- 💰 **Ценник в sidebar** — `$X.XX` зелёным рядом с моделью
- 🌐 **WebSearch рендер** — title (ссылка) + snippet вместо JSON
- 🔧 **Autocommit** — `git add -A && commit "wip:"` перед spawn_worker. Worktree создаётся от актуального кода — нет конфликтов
- ⚡ **Seamless turn** — после ResultMessage если есть pending → сразу новый turn (0ms вместо 2.5s debounce)
- 📊 **stop_reason логирование** — каждый turn пишет `stop_reason=X, num_turns=N`
- 🎼 **Orchestra skill** — `/orchestra` Claude Code skill в `app/skills/orchestra/SKILL.md`
- 🔒 **XSS fixes** — 3 innerHTML→textContent fixes (Codex review)

### Changed
- **max_turns 25→50** — воркеры не обрубаются на больших задачах
- **kill_worker** — теперь `DELETE` (полное удаление), не `POST /stop` (воркеры-призраки больше не висят)
- **Inject убран** — все сообщения в pending queue, нет потерянных/дублей
- **Logs limit 200→5000** — старые сообщения видны в чате
- **MAX_CHAT_NODES 500→5000** — DOM не обрезает историю
- **Deepgram Nova-2→Nova-3** — точнее для русского, та же цена
- **Orchestrator prompt** — обязательный system_prompt для воркеров (шаблон + примеры), file conflict rule, CTO delegation
- **Worker prompt** — bash rules (no polling loops), identity placeholders

### Fixed
- **TG flood control** — retry с backoff вместо fallback на plain text
- **TG error logging** — видно почему formatted send фейлится
- **HTML injection в tool_result** — escape `<>` перед innerHTML
- **Paste preview** — сохраняется/восстанавливается при переключении агентов
- **Markdown everywhere** — user messages, [from:worker], все рендерятся через marked.js
- **chat-bot border** — `#1e293b`→`rgba(99,102,241,0.1)` (видимый)
- **diff-code overflow** — `break-all`→`overflow-wrap: anywhere`
- **Read skeleton** — shimmer placeholder пока tool_result не пришёл
- **Expand hint** — rHint перенесён, querySelector работает
- **Restart без confirm** — убран confirm dialog
- **Prompt viewer identity** — реальные имена вместо `{worker_name}` placeholder
- **Custom prompt после ребута** — кастомная часть сохраняется при hot-reload
- **streamBubble на смене orchestrator** — сброс при переключении
- **initFilePanel drag listeners** — guard от накопления
- **refreshSessions stale scope** — capturedScope проверка

## v2.3.1 — 2026-05-09

### Added
- 🗜 **compact_worker MCP tool** — orchestrator can compact a worker's context (summary → reset session → continue fresh). Tested: 81%→17%, 56%→16%, 20%→16%
- ⚠️ **Context warning >90%** — platform auto-appends `⚠️ CONTEXT CRITICAL` to worker messages
- 🚫 **AskUserQuestion + run_in_background denied** — blocked via `can_use_tool` deny
- 🔧 **Tool+result merged** — one bubble on frontend, one expandable on TG
- 🎨 **Tool icons** — 🖥 Bash, 📖 Read, 🎼 orchestra, 🔌 MCP
- 📝 **Draft per agent** — unsent text preserved when switching
- 🔗 **URL linkify** — clickable links in tool_result
- 💊 **Status badge** — pill with colored bg on idle/running text

### Fixed
- **compact_worker timeout** — was 30s, compact takes ~40s → empty error → double compact. Now 120s
- **Prompt placeholders** — `{orchestrator_name}` was literal in hot-reload for workers
- **Scroll on switch** — chat now scrolls to bottom when opening agent
- **Timestamps overlap** — inline block instead of absolute positioning

## v2.3.0 — 2026-05-09

### Added
- 📱 **TG Bridge** (`app/tg_bridge.py`) — mirrors orchestrators to Telegram group topics.
  Auto-creates topic per orchestrator, bidirectional messaging, real-time log streaming.
  Separate bot (`@orchestraClaude_bot`), config in `.env` / `data/tg_bridge.json`
- 📬 **Kesha inbox server** (`inbox_server.py` in kesha-tg-bot) — HTTP endpoint :18081,
  Orchestra → Kesha via `notify_kesha` MCP tool → shows in Telegram chat
- 🔄 **Auto-report** — workers that finish without `send_message` get force-reported to
  orchestrator with last 3 text outputs. `[from:worker] [auto-report]` format
- 💉 **Message inject** — messages to RUNNING agents injected via `client.query()` immediately,
  no waiting for turn end. Fallback to pending queue on failure
- 🔥 **Prompt hot-reload** — updated `app/prompts/*.md` injected on first turn after restart.
  `[Orchestra platform note]` tag avoids prompt injection detection
- 📊 **Context tracking** — `input + cache_creation + cache_read` from last iteration,
  per-model limits (Opus 1M, Sonnet 200k), cache hit % in agent info panel
- 📈 **Context bar** — colored progress bar per agent in sidebar (green/yellow/red)
- 🌐 **Cross-project messaging** — `list_orchestrators()` discovers all orchestrators,
  `send_message` fallback searches by name across all scopes (`ensure_loaded_any`)
- 🐛 **report_bug MCP tool** — agents file bugs to `BUGS.md` with timestamp/reporter/scope
- ⟳ **Restart button** — dashboard header, `sudo -n systemctl restart orchestra`
- 💊 **Orchestrator tabs** — pill buttons replace dropdown, recent-first, live status dots
- 🖼 **Image paste** — Ctrl+V upload with md5 dedup, preview under input, render in chat
- ⚡ **Status badges** — `⚡ interrupted`, `⚡ system prompt updated` as centered badges in chat
- 📐 **Shared prompts** — `app/prompts/base.md` + `orchestrator.md` + `worker.md`, shared platform knowledge

### Fixed
- **Stop deleted logs** — `POST /stop` now calls `unload()` (preserves DB), not `remove()` (cascade)
- **Scroll hijack** — `showWaitingIndicator` respects `wasAtBottom`, no re-creation in refresh loop
- **Context 0%** — usage is dict not object (`.get()` not `getattr()`), last iteration not sum
- **Context 227%** — top-level usage sums all API calls, context = last iteration only
- **Trailing slash** — scope normalized with `rstrip("/")` at creation and lookup
- **Ghost workers** — `kill_worker` for DB-only sessions deletes from DB directly
- **MCP not visible** — `.mcp.json` no longer copied to worktrees (was overriding Orchestra MCP);
  `mcp_stdio.py` invoked by absolute path (was failing with `-m` from non-orchestra CWD)
- **SendMessage vs send_message** — prompts explicitly say `mcp__orchestra__send_message`
- **Interrupt stuck** — now awaits task cancellation, drops client, sets IDLE + persist
- **Newlines lost** — tool input via `json.dumps(indent=2)`, `white-space: pre-wrap` on frontend
- **Lost messages** — SSE user_message replaces pending bubble instead of skipping
- **Prompt injection** — `[SYSTEM UPDATE]` tag softened to `[Orchestra platform note]`
- **Repeated prompt inject** — `system_prompt` synced after inject, no more every-turn spam

### Changed
- **spawn_worker scope** — uses orchestrator's ORCHESTRA_SCOPE, not repo_path (workers visible in list_agents)
- **Prompts split** — old `orchestrator_prompt.md` + `worker_prompt.md` → `prompts/base.md` + role-specific
- **SDK 0.1.74** — updated from 0.1.72

## v2.2.0 — 2026-05-05

### Added
- 🗑️ **Delete orchestrator** — `DELETE /api/orchestrators/{name}` removes orchestrator + all
  workers in scope (active sessions, worktrees, DB records). Dashboard button `✕ Delete` with
  confirm dialog. `manager.remove_scope(scope)` handles cleanup.
- 💾 **Remember last orchestrator** — `localStorage` saves `lastOrchScope`/`lastOrchName` on
  switch, restores on page load. No more "always opens first in list".

### Fixed
- **Stop deleted logs (critical)** — `POST /stop` called `manager.remove()` which ran
  `DELETE FROM sessions` → `ON DELETE CASCADE` wiped all logs. Now stop calls `unload()`
  (stops session, removes from memory, preserves DB). Only explicit Delete removes from DB.
  - Triggered case: kesha-tg-bot orchestrator stuck running after interrupt, used stop to
    unstick it → 2318 log entries deleted by cascade. User saw empty chat.
- **Scroll hijack on history read** — three sources of forced scroll-to-bottom:
  1. `showWaitingIndicator()` unconditionally set `scrollTop` — now checks `wasAtBottom`
  2. SSE handler had duplicate scroll check after `addChatEntry` (which already handles it)
  3. `refreshSessions` re-created waiting indicator every 3s (SSE removed it → refresh
     recreated → scroll). Removed re-creation from refresh loop.

## v2.1.0 — 2026-05-04

### Added
- 📡 **SSE realtime logs** — `GET /api/sessions/{name}/stream` replaces polling for chat
- 🏥 **Health check loop** — detects crashed worker tasks every 60s
- 🔌 **Systemd service** — `orchestra.service` with auto-restart and Hiddify proxy
- 🎨 **Smart color picker** — unique color per worker, least-used fallback
- 🏷️ **Auto sender tag** — server adds `[from:name]`, workers send plain text
- 📴 **Offline CSS** — Tailwind/marked/DOMPurify bundled locally

### Fixed
- **Auto-resume crash** — error sessions marked stopped on startup
- **cli_path** — dynamic via `shutil.which("claude")`
- **Worker logs** — filtered (text/tool/error only), no raw dumps
- **tool_result parsing** — unwraps `{"result":"..."}` wrapper
- **Proxy** — `HTTPS_PROXY` set in session.py, manager.py, service file

## v2.0.0 — 2026-05-03

### Changed
- **External stdio MCP server** — MCP tools now run as separate process (`app/mcp_stdio.py`)
  via FastMCP, communicating with Orchestra API over HTTP. Replaces in-process `create_sdk_mcp_server`
  which caused deadlocks (SDK issue #425). External process = no shared event loop = no hang.
- **Simplified session.py** — removed persistent client, locks, _is_connected, _cleanup_client.
  Each turn: create fresh ClaudeSDKClient → connect → query → receive → disconnect (in finally).
  Root cause of ALL hangs was accumulated state in persistent connection.
  Proven: direct SDK test = 5 MCP calls in 17s. Old session.py = hang on 3rd call.
  New session.py = 18 MCP calls in 85s, zero hangs. -328 lines, +166 lines.
- **Worker communication via HTTP** — workers send reports via `curl POST /api/sessions/{name}/send`.
  Orchestrator receives via debounce → new turn. No MCP inject needed.
- **System CLI** — uses system Claude CLI 2.1.126 via `cli_path` instead of bundled 2.1.117

### Added
- 📬 **Worker Inbox** — `inbox` DB table + `GET /api/sessions/{name}/inbox` endpoint.
  `send_to_worker` queues messages in inbox. Real delivery semantics.
- 📋 **Job Registry** — `jobs` DB table + `GET /api/jobs` endpoint + `list_jobs` MCP tool.
  spawn/kill create tracked jobs with status (queued/executing/succeeded/failed).
- ⏱️ **Turn timeout** — 300s hard deadline on `_listen()`, 60s on `connect()`.
  TimeoutError → ERROR status. No more infinite hangs.
- 🔒 **Scoped lookups** — `find_worker(name, scope)`, `find_session_id_by_name(name, scope)`.
- 🧪 **`.mcp.json`** — project-level MCP config for local testing from Claude Code
- `alwaysLoad: true` — MCP tools skip ToolSearch deferral (v2.1.121 feature)

### Removed
- `create_sdk_mcp_server` in-process MCP (deadlock source)
- Persistent client connection in session.py (accumulation source)
- `.env` copy to worktrees (security fix)
- Prompt rule "max 2 MCP calls" (no longer needed)
- SDK monkey-patches (buffer, stdin) — no longer needed

### Fixed
- **Duplicate user_message logs** — send() logs once, _run_turn no longer duplicates
- **Timestamps** always visible in white on dashboard
- **pytest discovery** — testpaths=["tests"], norecursedirs for worktrees

## v1.3.0 — 2026-05-02

### Fixed
- **SDK MCP tool hang — root cause found and workarounds applied** — in-process MCP tool calls
  (`create_sdk_mcp_server`) hung after 2-3 calls per turn. Root cause: SDK `Query._read_messages`
  single read task handles both control_request routing AND bounded message stream (`max_buffer_size=100`).
  When buffer fills, read task blocks on `send()` → control_requests never reach Python MCP handlers → CLI
  waits for control_response forever → deadlock. SDK issue #425 (open, no PR).
  - **SDK patch: buffer 100→10000** — `query.py` monkey-patch, prevents backpressure up to 10000 messages
  - **SDK patch: stdin kept open** — `wait_for_result_and_end_input()` no longer closes stdin when SDK MCP
    servers present. Needed for persistent connections with multiple query() calls
  - **Spawn queue** — `spawn_worker` MCP tool no longer does heavy work (git worktree + session start)
    inside the MCP handler. Jobs enqueued to `asyncio.Queue`, processed by background supervisor task
    with 0.5s delay to let control_response flush first (Codex review finding)
  - **git worktree via to_thread** — `create_worktree()` sync subprocess moved to `asyncio.to_thread()`
    to avoid blocking event loop during MCP response path
  - **Inject removed** — `session.send()` no longer calls `client.query()` inject on RUNNING sessions.
    Messages queue in `_pending`, processed as new turn when session goes IDLE. Inject caused transport
    deadlock (both directions: worker→orch and orch→worker)
  - **Worker HTTP callback** — workers send reports via `curl POST /api/sessions/{name}/send` instead of
    MCP `send_message` inject. Eliminates transport deadlock entirely for worker→orchestrator communication
  - **Async DB writes** — `_log()` and `_persist()` via `run_in_executor()` to avoid blocking event loop
  - **include_partial_messages=False** — reduces stream event volume in SDK bounded buffer
  - **Orchestrator prompt: max 2 MCP calls per response** — prevents hitting CLI tool call limit per turn
  - Triggered case: every test with orchestrator + worker — spawn→list_workers→get_worker_logs chain hung
    on 3rd MCP call every time. Single MCP calls worked fine (5s). Multiple calls = deadlock.

### Changed
- **SDK pinned** — `claude-agent-sdk>=0.1.72` in pyproject.toml. Was unpinned, any `uv sync` could
  break everything. v0.1.72 fixes silent MCP tool result loss (v0.1.70+)

### Added
- **Spawn queue** — `SessionManager.enqueue_worker_spawn()`, `_spawn_worker_loop()` background task
- **Session error callback** — `AgentSession.on_error` + `SessionManager._on_session_error()` moves
  errored sessions from active to archived automatically

## v1.2.0 — 2026-05-01

### Changed
- **Data layer refactor — single source of truth** — `SessionManager` is now the sole data gateway.
  `manager.archived: dict[str, dict]` holds stopped/error sessions in memory. `list_sessions()` reads
  purely from memory (active + archived), zero DB merges. `stop()` moves session from active → archived.
  `tools.py` has zero direct DB imports (except `get_logs`). `main.py` reduced from 4 DB fallback paths to 0.
  - `load_archived()` at startup populates archived dict from DB
  - `find_worker()`, `find_session_id_by_name()`, `archive_by_id()`, `get_session_id()` — new manager methods
  - `ensure_loaded()` skips archived sessions (no zombie resurrections)
  - `kill_worker` for DB-only sessions now properly archives via `archive_by_id()`
  - 10 new TDD tests for archived dict behavior (107 total)
  - **Before**: 8 code paths with direct DB access scattered across tools.py + main.py, different formats (AgentSession vs dict), merge logic, fallback reconnects
  - **After**: manager = memory cache, DB = write-through backup + logs storage. One path, one format

## v1.1.0 — 2026-05-01

### Added
- 📡 **Streaming text** — responses appear live as chunks, not after full generation. `StreamEvent` + `content_block_delta` handling
- 📎 **Tool results visible** — MCP tool outputs (`ToolResultBlock`) shown in chat with 📎 prefix
- 🪦 **Agent archive** — stopped/killed workers get hash suffix (e.g. `worker-1-abc123`), move to archive section. Name freed for reuse. Chat history preserved, read-only
- 🏷️ **Model registry** — `app/models.py` single source of truth. Aliases resolved (`sonnet` → `claude-sonnet-4-6`). API validates, dropdown loads from `/api/models`
- 🔄 **restart_worker** MCP tool — kill + respawn in one call
- 📊 **Context display** — `5% (12k/200k)` format, cached on agent switch

### Fixed
- **Worktree preserved on stop** — `stop()` no longer deletes worktree. Only explicit `kill/remove` does
- **Auto-resume rehydrate** — all fields restored from DB (worktree_path, branch, created_at)
- **`_run_turn()` exceptions** — done callback logs errors, sets ERROR status
- **Error UX** — no "waiting for response" after 404/error. Debounce cancelled on failure
- **Stopped agent resume** — writing to stopped agent auto-resumes it (fallback cwd if worktree missing)
- **Duplicate names** — stopped agents archived with hash, name freed for new workers
- **`list_workers`** — shows active + archived workers

### Changed
- `shutdown_all` — orchestrators stay `idle` (not stopped) for auto-resume. Workers get stopped with worktrees intact

## v1.0.0 — 2026-04-30

Complete rewrite from MVP v0.4. One class, one way, Apple-level simplicity.

### Added
- 🏗️ **`AgentSession`** — single SDK wrapper replacing both `Worker` and `Orchestrator` classes. One class for all agents, config-driven (model, system_prompt, mcp_servers)
- 🌿 **`workspace.py`** — isolated worktree management. Scope-namespaced paths (`worktrees/{scope_slug}/{name}`), fail loud, no silent fallbacks
- 🔧 **MCP tools for orchestrator** — `spawn_worker`, `send_to_worker`, `list_workers`, `get_worker_logs`, `kill_worker`. Orchestrator manages workers natively via MCP, not prompt hacking
- 🔧 **MCP tools for workers** — `send_message` (to any agent), `list_agents`. Workers can communicate with orchestrator and each other
- 📝 **System prompts** — `orchestrator_prompt.md` and `worker_prompt.md` in `app/`. Editable .md files, not hardcoded strings
- 🖥️ **Dashboard v2** — single-screen UI: chat with any agent (left), agent list + info (right). Click to switch between orchestrator and workers. Markdown rendering, debounce indicator, adaptive polling (500ms when waiting, 3s idle)
- 📊 **Message debounce** — multiple rapid messages batched into one (2s window, like Kesha). Visual ring timer on pending messages
- 💉 **Live inject** — messages sent while agent is RUNNING inject directly into current turn (no queue, no "session busy")
- 🧪 **97 TDD tests** — `test_db.py` (29), `test_workspace.py` (16), `test_session.py` (18), `test_manager.py` (14), `test_api.py` (20). Written before code (RED→GREEN)
- 🔑 **UUID primary keys** — `UNIQUE(name, scope)` for display, UUID internally. No collisions between scopes
- 📡 **Multi-orchestrator support** — one dashboard, multiple orchestrators (one per project). Picker in header, scope filtering
- 🔄 **Auto-resume** — orchestrators survive server restart (status stays `idle`, SDK resumes via `session_id`)
- 🛡️ **Permission fix** — `default` + `can_use_tool` auto-approve instead of `bypassPermissions` (known regression: Claude Code #36497, #37157, #36923)

### Removed
- `worker.py` — replaced by `AgentSession` in `session.py`
- `orchestrator.py` — replaced by `AgentSession` in `session.py`
- `callbacks` table — replaced by session logs with `type="notification"`
- 18 API endpoints → 9 (one resource `/api/sessions`)
- `max_turns` parameter — SDK manages this
- `data/orchestrator_session` file — session_id now in SQLite
- Separate notifications tab — everything in chat

### Changed
- **DB schema** — `sessions` + `logs` (was `workers` + `logs` + `callbacks`). UPSERT, CASCADE, `busy_timeout=5000`, `foreign_keys=ON`
- **API** — one resource `/api/sessions`. Pydantic validation, proper HTTP status codes (404/409/422), no `{"ok": false}`
- **Dashboard** — HTML/CSS/JS split into separate files. DOM API rendering (no innerHTML XSS). Cursor-based log pagination

### Architecture
```
app/
  main.py            — FastAPI, 9 endpoints
  session.py         — AgentSession (single SDK wrapper)
  manager.py         — SessionManager (registry + lifecycle)
  workspace.py       — git worktree create/remove
  db.py              — SQLite (sessions + logs)
  tools.py           — MCP tools for orchestrator + workers
  orchestrator_prompt.md
  worker_prompt.md
  static/css/style.css
  static/js/app.js
  templates/dashboard.html
```

### Process
- 4-round Codex (GPT-5.5) adversarial review of spec before implementation
- TDD for all modules: tests written first, then minimal code
- Codex code review (Round 5) caught 4 real bugs post-implementation

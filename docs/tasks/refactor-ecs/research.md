# Research — Full Refactoring P0–P4 (refactor-ecs)

**Date:** 2026-06-11
**Base:** `868b420` (== main). Branch `feat/mnt-data-projects-python-orchestra/refactor-ecs`.
**Source audit:** `docs/reviews/arch-audit.md` (verified, Codex cross-reviewed). This research verifies the audit's claims against current code and adds implementation-relevant findings the audit didn't cover.

---

## 1. Current architecture (condensed)

27 files, ~12 100 lines in `app/`. Leaves are clean (`events`, `models`, `prompting`, `db`, backends, `bg_jobs`, `routes/*` — scored 4–5 in audit). All debt is in the control-plane triangle **`session.py` (1109) ↔ `manager.py` (1139) ↔ `tg_bridge.py` (1558)** plus monolithic **`main.py` (1574)**. Import graph is a DAG only thanks to ~75 lazy `from app...` imports inside functions (counted: 75 matches, see §4).

## 2. Verified findings per phase

### P0 — Silent excepts + sync-in-async

**Silent except sites (grep-verified, 42 matches total). Classification:**

| Category | Sites | Action |
|---|---|---|
| **Real swallows — fix** | `manager.py:552,602,637,1137` · `main.py:396,917,959,1049,1058,1107` · `session.py:916,927` · `tg_bridge.py:62,78,977,1053,1229,1512` · `workspace.py:684,739,752` · `db.py:324,344,377` (migrations) · `backend_claude.py:207` · `backend_codex.py:194` | → `except Exception as e: logger.warning(..., exc_info=True)` |
| **Legitimate — leave** | All `except asyncio.CancelledError: pass` (bg_jobs ×7, ssh_tunnel:123, session:1029) · `bg_jobs.py:99,107` (`ProcessLookupError` on kill) · `backend_claude.py:81` (ValueError parse fallback), `:171` (`BaseException` during forced disconnect) | no change |
| **Borderline** | `session.py:831,996,1005` (`except (CancelledError, Exception)`) — the `Exception` half deserves at least `logger.debug` | split: suppress Cancelled, log Exception |

Audit caveat for `session.py:916,927` (`_notify_scope_idle/_notify_scope_running`): these wrap the lazy tg_bridge import — **P3 removes the import; P0 just adds logging**.

**Sync SQLite in `async def` (event-loop blockers):**
- `tm_yougile.py:104-179` (`yougile_sync_task` — `tm._conn()`, `BEGIN IMMEDIATE` on loop thread), `:206` (`_update_done_column_title`), `:234` (`_ensure_journal_task`)
- `routes/tm.py` — ALL 9 handlers are `async def` calling sync `_tm.api_*` / raw `_tm._conn()` directly (lines 56, 69, 83, 97, 113, 122, 134, 151, 160). Most-trafficked instance.
- `main.py:1427` `restart_server` — `subprocess.run` in async handler (low priority, admin-only).

Fix pattern: `await asyncio.to_thread(...)` around DB/sync portions; httpx calls stay on loop. **Audit caveat:** wrapping changes transaction timing vs YouGile HTTP calls — verify sync completes end-to-end after change.

### P1 — Union-type virus

- `manager.get_by_name` (`manager.py:749-755`): in-memory hit → `AgentSession`, DB fallback → raw `dict`.
- **34 `isinstance(found/session/s, dict)` sites in `main.py`** (lines 509–1384), plus `manager.py:806` (`_resolve_base_branch`), plus duck-typing variants: `routes/bg.py:38` (`hasattr(session, "id")`), `main.py:629` (`getattr(...) or .get(...)`).
- **NOT in scope:** ~50 `isinstance(result, dict)` in `mcp_stdio.py` — those are HTTP-response parsing, not the session union. Same for `backend_*`, `tm.py:330` (commits), `manager.py:284` (`_parse_custom_mcp`).
- **Key insight: `AgentSession` is a side-effect-free dataclass** (`session.py:106-177`) — no backend spawn, no tasks in construction. A lightweight `detached` hydration (row → AgentSession, no `start()`) is safe. The heavy resume path (`manager.py:888-937`) exists but starts the session — NOT what we want for lookups.
- **Semantic trap:** several callers use `isinstance(found, dict)` to mean **"not loaded in memory"** — e.g. `main.py:663,672` (interrupt/stop require LIVE session → 404 otherwise), `main.py:872,899,939` (merge/switch check live status). Hydration must preserve this distinction → detached sessions need a discriminator (e.g. `loaded: bool` field or check `manager.get(found.id) is not None`). This is the #1 way to silently break behavior in P1.

### P2 — main.py drain

- **56 `@app.*` handlers** in `main.py` (grep-verified, lines 180–1496). `routes/{tm,bg,proxy}.py` already prove the pattern; `app/deps.py` provides the shared `manager` singleton (no main import needed).
- Buckets for extraction (task spec) — actual handler counts:
  - `routes/sessions.py`: ~26 handlers (`/api/sessions*` CRUD, send, stream, logs, compact, interrupt, stop, merge, switch-branch, wip, check-conflict, progress, inbox, change-model, rename, prompt, description, tg_topic, restart-cli)
  - `routes/tasks.py`: already exists as `routes/tm.py` — task spec's "tasks.py" maps onto it; nothing in main.py for tm (already drained)
  - `routes/tg.py`: `/api/tg/send_file`, `/api/upload`, `/uploads/{filename}` (~3)
  - `routes/system.py`: `/api/stats`, `/api/usage*`, `/api/models`, `/api/restart`, `/api/jobs`, `/api/projects`, `/api/files*`, `/api/open-*`, `/api/role-icons`, `/api/pipelines`, `/api/profiles*`, `/api/git-status`, `/api/test-lock*`, `/api/report_bug`, `/api/orchestrators*`, `/api/webhook/github`, login/logout/index (~27; may split further into files/usage/orchestrators per audit)
- Helpers that move with them: `_build_path_map`, `_is_safe_path`, `_refresh_oauth_token`, `_get_agents_cost`, `_run_git`, SSE infra.
- **Order dependency: P1 first** — otherwise we copy 34 isinstance hacks into the new modules.
- Security note from audit (fix in passing during P2): `main.py:367` `open_file` bypasses `_is_safe_path`.

### P3 — Circular deps → callbacks

Three real cycles (all currently lazy-import-deferred):
1. **session ↔ tg_bridge** — session needs `check_scope_idle`/`notify_scope_running` + `tg_bridge._manager` (session.py:910,921); tg_bridge needs SessionManager (tg_bridge.py:1548). Session already has the `on_idle` callback precedent (`session.py:160`, wired by `manager._make_idle_callback`). Fix: add `on_scope_idle`/`on_scope_running` module-level or per-session callback slots, tg_bridge assigns at startup (`start_bridge`).
2. **manager ↔ tg_bridge** — `manager.py:740` (`remove_topics_for_orchs`), tg_bridge lazy-imports manager. Same wiring trick.
3. **tm ↔ tm_yougile** — `tm.py:696,729` lazy-import `yougile_sync_task`/`update_payment_journal`; `tm_yougile` imports `tm._conn` top-level. Fix: `tm.on_task_synced`/`on_payment_changed` callback slots set by tm_yougile at startup; also dedupe `_fire_sync`/`_fire_journal_sync` (near-identical, tm.py:687-752) into one `_fire_async`.
- **~75 lazy imports total**; only ~15 are cycle-breaking. The rest (main.py ~30, bg_jobs→db, routes/bg→bg_jobs etc.) are cargo-cult — safe to lift to top-level (db, workspace, prompting, bg_jobs are leaves/lower layers). P2 extraction naturally removes main.py's share.
- `proxy_manager.py:142` → `manager.MCP_BASE_ENV` (mutable global) — coupling smell; minimal fix: move `MCP_BASE_ENV` to a leaf (e.g. `models.py` or new tiny `env.py`) so both import downward.
- Audit explicitly recommends **wired callbacks, NOT an event bus** ("event bus = abstraction creep for 3 cycles / 10 users"). Task spec agrees ("callback pattern").

### P4 — session.py split

Method inventory (session.py grep) maps onto the three extractions in the task:
- **CostTracker**: fields `cost_usd`, `cost_usd_cached`, `_last_cost`, `_turn_cost`, `_context_cost`, `_last_cost_cached`, `total_*` counters; methods `_apply_turn_result` (:569), `_update_context_from_turn` (:600). Audit strongly recommends making it **total-based, not delta-based** (kills session-id-reset fragility) — behavior-preserving rewrite, needs care + tests.
- **TurnManager**: `_handle_turn_end` (:543), `_finish_turn_status` (:612), `_after_turn_idle_actions` (:622), `_bump_turn_gen` (:512), `_fire_auto_report` (:517), `_cancel_auto_report` (:507), `_turn_gen`/`_turn_start`/`_auto_report_task` state.
- **HibernateManager**: `_schedule_hibernate` (:686), `_idle_hibernate` (:694), `_heartbeat_loop` (:734), `_hibernate_task`/`_hibernated` state.
- `AgentSession` stays the facade (public API unchanged: `start/send/stop/interrupt/compact/change_model/to_dict`).
- Audit P4 also covers tg_bridge split + manager split — **task spec scopes P4 to session.py only**. tg_bridge/manager splits are OUT of this task (noted as follow-up).
- Related P0-adjacent fixes that land here or in P0: codex turn loop missing `add_done_callback` (:448 vs claude :376→`_on_task_done`), `_auto_continue` unbounded recursion (:930) — audit P0 item 2; I'll do them in P0 (small, low risk).

## 3. Test baseline (measured)

- `pytest tests/ -x -q` → **127 passed, then 1 pre-existing fail**: `test_default_equals_upstream.py::TestSystemPromptStructural::test_upstream_markers_present_in_ours[orchestrator]` — `<task-management>` tag missing from our orchestrator prompt (prompt-module refactor drift; exists on main, unrelated to refactoring).
- Full suite without `-x` → **106 fails** — but ALL from **pre-existing test-isolation pollution**: `test_default_equals_upstream.py` clears `load_pipeline.cache_clear()` + monkeypatches `PIPELINES_DIR`; downstream files (`test_manager` 54, `test_session` 22, `test_tg_bridge` 14, `test_mcp_stdio` 12) then read wrong pipeline state. **Verified: each file passes 100% in isolation** (84+98 passed). Pairwise repro: `test_default_equals_upstream + test_manager → 6 failed`; any other pair → green. Plus 9 playwright errors (`test_frontend.py`, no browser — environmental).
- **Green gate for each phase:** run affected test files individually + `pytest tests/ -q --ignore=tests/test_frontend.py --deselect tests/test_default_equals_upstream.py` must match baseline. Per task rule 6, the isolation bug is "не моё" — I won't fix it in this task, but will note it in report.

## 4. Risks & edge cases

1. **P1 semantic trap (highest):** `isinstance(found, dict)` sometimes means "session not live" — naive hydration flips 404s into wrong-path success on interrupt/stop/merge/delete. Mitigation: explicit `loaded` discriminator; per-call-site review of all 34 sites, not mechanical sed.
2. **P0 transaction timing:** `to_thread` around `BEGIN IMMEDIATE` blocks in tm_yougile changes interleaving with httpx calls. Mitigation: keep each transaction wholly inside one `to_thread` callable; manual end-to-end check of a sync.
3. **P2 SSE/streaming handlers** (`/api/sessions/{name}/stream`, :556) use generator responses + module globals — move carefully, keep `request` lifecycle.
4. **P3 wiring point:** callbacks must be assigned before first session goes idle — wire in `start_bridge()` / lifespan, and keep None-guards (`if self.on_scope_idle:`) so tests without TG still pass.
5. **P4 delta→total cost rewrite** changes `_apply_turn_result` semantics — the one place refactoring touches arithmetic. Mitigation: dedicated unit tests before the move (TDD per global CLAUDE.md — this is state-machine/business-logic territory).
6. **No public API changes:** HTTP paths, MCP tools, DB schema, `to_dict()` shapes stay identical. FastAPI route extraction preserves paths exactly (APIRouter without prefix where needed).
7. **tm_import_yougile.py** imports tm+tm_yougile — check it still works after P3 callback inversion.

## 5. What stays as-is (audit "don't gold-plate" + task scope)

- `db.py` conn-per-call + WAL (no pooling), `bg_jobs.py`, backends, `auth.py`, `events.py`, `diff_image.py` redesign, `pipeline.py` lru_cache — untouched except the silent-except sweep where applicable.
- tg_bridge **package split** (audit P4 #12) — OUT (task P4 = session.py only). tg_bridge gets P0 (excepts) + P3 (callback wiring) only.
- manager split into Registry/SpawnSystem/PromptAssembler (audit #14) — OUT.
- workspace.py merge-lock dedup (audit P0 #5) — **not in task spec's P0 list**; I propose including it only if time permits — default OUT to keep scope tight.

## 6. External references

- Audit: `docs/reviews/arch-audit.md` (+ `codex-review-arch-audit.md` cross-review)
- FastAPI APIRouter docs — standard include_router pattern, already proven in `routes/proxy.py`

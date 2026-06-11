# Plan — Full Refactoring P0–P4 (refactor-ecs)

**Base:** `8d9e11a` (main + research). One commit per phase, tests green after each.
**Invariants (all phases):** HTTP paths/verbs/response shapes unchanged · MCP tools unchanged · DB schema unchanged · `to_dict()`/`_to_db_dict()` shapes unchanged · no behavior changes, only structure (one documented exception: silent excepts start logging).

**Test gate per phase** (pre-existing failures documented in research §3):
```bash
# GREEN GATE — full suite minus the pre-existing polluter and env-dependent playwright; must be 100% green
uv run python -m pytest tests/ -q --ignore=tests/test_frontend.py --ignore=tests/test_default_equals_upstream.py
# DIAGNOSTIC (not a gate) — polluter file in isolation; expected exactly 1 known pre-existing fail (prompt-tag drift)
uv run python -m pytest tests/test_default_equals_upstream.py -q
```
Deselected: `tests/test_default_equals_upstream.py` from the combined run ONLY (it clears `load_pipeline` lru_cache + monkeypatches `PIPELINES_DIR`, poisoning 106 downstream tests — pre-existing, on main). It still runs separately every phase. `test_frontend.py` = playwright, needs running server/browser — environmental, skipped.

---

## Phase P0 — Silent excepts + sync-in-async (commit 1)

### 0.1 Except sweep — exact sites (from research §2 classification)

Pattern: `except Exception: pass` → `except Exception as e: logger.warning(f"<context>: {e}")`. `exc_info=True` only where the stack matters (worktree cleanup, migrations). Contextual message names the operation that failed.

| File | Lines | Context |
|---|---|---|
| `manager.py` | 552, 602, 637 | task-link update / worktree cleanup after kill — **audit: zombie worktrees**; 1137 — stale-worktree sweep |
| `main.py` | 396 (`PermissionError` in file listing → `logger.debug`, benign), 917, 959 (task-link after merge/switch — warning), 1049, 1058, 1107 (stats aggregation — warning) |
| `session.py` | 916, 927 (TG scope-notify — warning); 831, 996, 1005: split `except (CancelledError, Exception)` → `except CancelledError: pass` + `except Exception as e: logger.warning(...)` |
| `tg_bridge.py` | 62, 78 (config IO), 977, 1053, 1229, 1512 — warning |
| `workspace.py` | 684, 739, 752 — warning |
| `db.py` | 324, 344, 377 — migration guards → `logger.warning(..., exc_info=True)` |
| `backend_claude.py` | 207 (disconnect — warning); `backend_codex.py` 194: split timeout/Exception, log Exception |

NOT touched (legitimate): all `except asyncio.CancelledError: pass`, `bg_jobs.py:99,107` (ProcessLookupError on kill), `backend_claude.py:81` (parse fallback), `:171` (BaseException during forced teardown).

### 0.2 Sync SQLite in async handlers

- **`tm_yougile.py`**: `yougile_sync_task` (:104-179) — extract ALL SQLite access (reads included, not just transactions) into local sync helper functions; **each helper opens and closes its own connection inside itself** — a connection never crosses a thread or `await` boundary. Call helpers via `await asyncio.to_thread(...)`. httpx calls stay on loop. Same for `_update_done_column_title` (:206), `_ensure_journal_task` (:234). (Codex: stray reads at :105, :156 currently sit outside transaction blocks next to `await` — they go into helpers too.)
- **`routes/tm.py`**: all 9 handlers — wrap the sync `_tm.api_*` / `_tm._conn()` blocks in `asyncio.to_thread`. `_resolve_client_id` becomes sync helper invoked inside to_thread together with the call that uses it (one hop, not two).
- **Thread→loop scheduling contract (Codex R2-B1):** `tm._fire_sync`/`_fire_journal_sync` (tm.py:687-752) do `get_event_loop().create_task()` and swallow `RuntimeError` as "no loop, skipping" — inside `to_thread` worker threads that fires EVERY time → YouGile sync silently dies after P0. Fix lands IN P0: `tm._MAIN_LOOP: AbstractEventLoop | None` module global, set from `main.py` lifespan (`tm.set_main_loop(asyncio.get_running_loop())`); the fire helpers fall back to `asyncio.run_coroutine_threadsafe(coro, _MAIN_LOOP)` when `get_running_loop()` raises. P3's `_fire_async` inherits this contract. **Test:** call `api_create_task` (yougile-enabled project, stubbed sync coro) from inside `asyncio.to_thread` — sync task gets scheduled on the main loop, not skipped.
- **`main.py:1427`** `restart_server`: `subprocess.run` → `await asyncio.to_thread(subprocess.run, ...)`.

### 0.3 Session loop hardening (audit P0 item 2, small)

- `session.py:448` `_codex_turn_loop` spawn site: attach the same `_on_task_done` done-callback the Claude loop has (:376).
- `_auto_continue` (:930): depth cap — counter `_auto_continue_count` reset on каждом user `send()`, cap 5 → log warning + stay IDLE. (New private field; not persisted.)

### 0.4 Verify

Test gate + manual: trigger one YouGile sync end-to-end (transaction-timing caveat from research §4.2) — via `tm_sync_retry` route or unit test with mocked httpx. `git commit -m "#refactor-ecs P0: ..."`.

---

## Phase P1 — Union-type virus (commit 2)

### 1.1 The pattern (orchestrator-mandated discriminator)

```python
@dataclass
class AgentSession:
    ...
    loaded: bool = True   # False → detached DB-hydrate: data only, no backend/tasks; NEVER call start()/send()/_persist() on it
```

- `manager._hydrate_row(row: dict) -> AgentSession` — NEW: lightweight mapping of DB row → detached `AgentSession(loaded=False)`. Data fields only (id, name, scope, cwd, model, status→AgentStatus, system_prompt, session_id, costs, worktree_path, branch, created_at, role, parent_*, pipeline, profile, backend_type, task_id, description, owned_dirs, tg_topic, is_orchestrator, progress_*, total_* counters, context via `_last_context`). No `start()`, no prompt assembly, no git calls — unlike heavy resume at `manager.py:888`.
- Detached session also keeps the raw row: `AgentSession.db_row: dict | None = None` (repr=False, not persisted). **Response-shape preservation (Codex B1):** `GET /api/sessions/{name}` (`main.py:509-511`) today returns the raw DB row for unloaded sessions — richer/different shape than `to_dict()` (has `cwd`, `session_id`, `context_tokens`, full `system_prompt`). Handler becomes `return found.to_dict() if found.loaded else found.db_row` — JSON byte-compatible with today. Same rule anywhere a handler previously returned the dict as-is.
- `get_by_name(name, scope) -> AgentSession | None` — in-memory hit → live session (loaded=True); DB row → `_hydrate_row(row)`; miss → None. **dict never escapes as a type** (db_row is an explicit, named escape hatch for response shape only).
- `status` in detached sessions: hydrate from DB string via `AgentStatus(row["status"])` with fallback to `IDLE` on unknown.

### 1.2 Call-site migration (each reviewed individually, not sed)

Semantics table — research §2-P1 trap:

| Old check | Meaning | New check |
|---|---|---|
| `isinstance(found, dict)` → 404/refuse | "session not live in memory" | `not found.loaded` |
| `found["x"] if isinstance(found, dict) else found.x` | data extraction | `found.x` |
| `not found or isinstance(found, dict)` | live-only op (interrupt/stop/restart-cli) | `not found or not found.loaded` |

Sites: `main.py` ×34 (509–1384), `manager.py:806` (`_resolve_base_branch` — just `ps.branch`), `routes/bg.py:38` (`hasattr` → `session.id`), `main.py:629` (`getattr/get` → `session.parent_name`).
**Plus the inverted check (Codex B2):** `manager.py:654` `change_orchestrator_scope` — `if not isinstance(session, AgentSession)` is a live-only guard that hydration would silently defeat (detached IS an AgentSession) → `if not session or not session.loaded`. Audit ALL `get_by_name` call-sites (`grep -rn "get_by_name(" app/`), not just isinstance sites — every caller classified live-only vs data-only in the implementation notes.

### 1.3 `manager.update_session_fields()` (audit #6, kills handler-level `_persist`)

```python
def update_session_fields(self, name: str, scope: str, **fields) -> AgentSession | None:
    """Live session → setattr + _persist(); detached → direct DB UPDATE. Returns updated session or None."""
```
Allowed fields whitelist: `description`, `system_prompt`, `tg_topic`. Migrate handler sites that currently handle BOTH live (`setattr+_persist`) and dict (raw `_conn()` UPDATE) cases: `main.py:678` (description), `:716` (prompt), `:697` (tg_topic). **Progress (`main.py:1003`) is OUT (Codex B3):** today it 404s for DB-only sessions (`:1009-1011`) — a DB-update path would flip 404→200, a behavior change. It stays live-only: drop the isinstance branch, keep `not session.loaded → 404`. Sites with complex side effects (change-model, rename) keep their flow, just lose the isinstance branches.

### 1.4 Tests (TDD — write first)

New `tests/test_manager.py` cases: `get_by_name` returns `AgentSession` for DB-only row with `loaded=False`; live session returns `loaded=True`; miss → None; hydrated status mapping; unknown status fallback; `update_session_fields` live vs detached paths (detached → DB row updated, no task spawned); **response-shape test for `GET /api/sessions/{name}` on a DB-only session — JSON keys identical before/after (Codex B1)**; progress on DB-only session still 404 (Codex B3); `change_orchestrator_scope` on DB-only orchestrator still errors "not loaded" (Codex B2).
Grep gate (broadened per Codex S2): `rg "get_by_name\(|isinstance\([^)]*, dict\)" app/` → every hit manually classified; 0 session-typed isinstance hits remain (non-session dict checks like `mcp_stdio.py` HTTP parsing are exempt).

---

## Phase P2 — Drain main.py → routes/ (commit 3)

### 2.1 Target layout (depends on P1 — no isinstance hacks copied)

| New file | Handlers (from main.py lines) | ~Count |
|---|---|---|
| `routes/sessions.py` | 407–1029: sessions CRUD list/create/get, prompt GET/POST, context, stream (SSE), logs, send, compact, restart-cli, interrupt, stop, description, tg_topic, change-model, rename, delete, merge, switch-branch, wip, check-conflict, progress, inbox | 26 |
| `routes/tg.py` | 1320 upload, 1339 uploads/{filename}, 1408 tg/send_file | 3 |
| `routes/system.py` | 180 index, 188/195/209 login/logout, 217 jobs, 245 projects, 325–400 files/raw/content/open-folder/open-file/files, 401 role-icons, 452 pipelines, 462–494 profiles, 1031 stats, 1134/1226 usage(+history), 1232 report_bug, 1251–1272 orchestrators, 1285–1302 test-lock, 1309 models, 1370 git-status, 1426 restart, 1496 webhook/github | 27 |
| `routes/tasks.py` | — already exists as `routes/tm.py` (orchestrator confirmed: skip) | — |

- Routers declared WITHOUT prefix (paths vary: `/`, `/login`, `/api/...`, `/uploads/...`) — handlers keep absolute paths → URL surface byte-identical.
- Helpers move with their consumers: `_build_path_map`/`_is_safe_path` → `routes/system.py`; SSE infra → `routes/sessions.py`; `_refresh_oauth_token`/`_get_agents_cost` → `routes/system.py` (usage); `_run_git` → `routes/system.py` (git-status). Shared `templates = Jinja2Templates(...)` → `app/deps.py`.
- `manager` access: `from app.deps import manager` (pattern proven by `routes/bg.py`).
- **In passing (audit security note):** `open_file` (main.py:367) gets the same `_is_safe_path` check as its siblings.
- `main.py` after: imports, lifespan, middleware (auth, static), `include_router` ×7, ~150-200 lines.

### 2.2 Verify

Route-surface snapshot test: before refactor, dump `sorted([(r.path, tuple(sorted(r.methods))) for r in app.routes])`; assert identical after (add as `tests/test_routes_surface.py` — small, permanent regression guard). Test gate + `test_api.py` (exists, covers endpoints).

---

## Phase P3 — Cycles → callbacks (commit 4)

### 3.1 session ↔ tg_bridge

Module-level hook slots in `session.py` (next to existing `on_idle` precedent). **Placement (Codex R2-B2):** module-level annotations are evaluated eagerly (PEP 526) and `session.py` has no `from __future__ import annotations` — a pre-class reference to `AgentSession` = `NameError` on import. Hooks are declared AFTER the class definition with string annotations:
```python
# session.py — AFTER class AgentSession
on_scope_idle: "Callable[[AgentSession], Awaitable[None]] | None" = None
on_scope_running: "Callable[[AgentSession], Awaitable[None]] | None" = None
```
(`Callable`, `Awaitable` imported from `collections.abc` at top.) Import smoke test: `python -c "import app.session"` in phase verify.
- `_notify_scope_idle/_notify_scope_running` → `if session_module.on_scope_idle: await on_scope_idle(self)` (None-guard → tests without TG pass).
- `_find_scope_orch_name` moves to `tg_bridge` (it needs the manager, which tg_bridge already holds as `_manager`).
- `tg_bridge.start_bridge()` assigns both hooks. `stop_bridge()` resets to None.
- session.py lazy imports of tg_bridge (910, 921) — deleted.

### 3.2 manager ↔ tg_bridge

- `manager.py:740` (`remove_topics_for_orchs` in `remove_scope`): hook slot `SessionManager.tg_topics_remover: Callable | None`, assigned in `start_bridge()`. None → skip with empty result (current behavior when TG off).
- tg_bridge:1548 imports manager only in `__main__` test block — leave (not a runtime cycle).

### 3.3 tm ↔ tm_yougile

- `tm.py`: dedupe `_fire_sync` (:687) + `_fire_journal_sync` (:721) → one `_fire_async(coro_factory)`; replace lazy imports with module-level hook slots `on_task_synced: Callable | None` / `on_payment_changed: Callable | None`.
- `tm_yougile.py` registers both at import end (it already top-level-imports tm — direction tm_yougile→tm stays, tm→tm_yougile dies).
- **Guaranteed registration (Codex B4):** hooks fire from `tm.py:782,827,924` — if nothing imports `tm_yougile` before that, sync silently becomes a no-op. Fix: explicit `from app import tm_yougile  # noqa: F401 — registers tm sync hooks` in `main.py` lifespan startup. `routes/tm.py:170` lazy import lifts to top-level (second guarantee). **Test:** `api_create_task()` with a stubbed hook → hook called; and `import app.main` → `tm.on_task_synced is not None`.
- `tm_import_yougile.py` — re-check imports still resolve (research §4.7).

### 3.4 proxy_manager → manager global

- `MCP_BASE_ENV` moves from `manager.py` to new leaf `app/runtime_env.py` (≤10 lines). `manager` and `proxy_manager` both import downward. Lazy import at `proxy_manager.py:142` dies.

### 3.5 Cargo-cult lazy import lift (no cycle involved → top-level)

- `main.py` residue after P2, `routes/bg.py` (bg_jobs, db), `bg_jobs.py` (db fns), `manager.py` (db, workspace, bg_jobs, models, tm), `session.py` (models, prompting, bg_jobs), `tg_bridge.py` (db, diff_image), `workspace.py:701` (db).
- Keep lazy: `session.py` backend imports (:194-205 — heavy SDK import at startup), anything where tests monkeypatch the import site (check each before lifting; if a test patches `app.X.Y`, lifting changes the patch target → fix test or keep lazy with comment).

### 3.6 Verify

Test gate + smoke: `python -c "import app.main"` (import order sanity), grep count of lazy imports (~75 → ≤ ~25, remaining ones each justified by comment).

---

## Phase P4 — Split session.py god object (commit 5)

### 4.1 New modules (composition, AgentSession = facade; public API untouched)

**Field-ownership rule (Codex S3/S4): ALL state fields STAY on the `AgentSession` dataclass.** Subsystems are stateless method-holders operating on the session they receive (`self.s`) — true ECS "systems over state", not data relocation. Rationale: `_did_report` is also mutated in `_handle_event` (:475 area), `_hibernated`/`_hibernate_task` are read at `:304, :988, :1013`, persistence reads cost fields — moving fields would force shims everywhere; moving only METHODS is behavior-neutral and keeps `_to_db_dict` untouched.

**`app/session_cost.py` — `CostTracker(s: AgentSession)`**
- Methods: `apply_turn_result(meta) -> tuple[bool, str, int]` (from `_apply_turn_result` :569), `update_context_from_turn(meta)` (:600). Operates on `s.cost_usd`, `s._last_cost`, `s._turn_cost`, `s._context_cost`, `s._last_cost_cached`, `s.total_*`.
- **Extract AS-IS, delta-based.** Audit's total-based rewrite = behavior change → explicitly OUT (task rule 4), noted as follow-up.

**`app/session_turns.py` — `TurnManager(s)`**
- Methods: `handle_turn_end` (:543), `finish_turn_status` (:612), `after_turn_idle_actions` (:622), `bump_turn_gen` (:512), `fire_auto_report` (:517), `cancel_auto_report` (:507). Operates on `s._turn_gen`, `s._turn_start`, `s._auto_report_task`, `s._did_report`.

**`app/session_hibernate.py` — `HibernateManager(s)`**
- Methods: `schedule` (:686), `_idle_hibernate` (:694), `heartbeat_loop` (:734). Operates on `s._hibernate_task`, `s._hibernated`.

### 4.2 Wiring

- `AgentSession.__post_init__` (or lazy properties) creates the three subsystems with `self` reference. Event loop (`_claude_event_loop`/`_codex_turn_loop`/`_handle_event`) stays in AgentSession, delegates: `self._turns.handle_turn_end(event)` etc.
- Private methods that moved keep thin delegating shims ONLY where tests/tg_bridge call them by name (`grep` first — known: tests patch `_heartbeat_loop` at `tests/test_session.py:744`, reference auto-report behavior at `:263, :685`; those tests must stay green, shim or update patch target in same commit); otherwise no re-export (CLAUDE.md: no back-compat wrappers). External callers checked: `tg_bridge`, `manager`, `main` (post-P2 routes).
- Persistence (`_persist*`), compact, MCP loading stay in AgentSession (audit: extract only if still painful — it won't be after −~350 lines).

### 4.3 Verify

`tests/test_session.py` (84 tests) green untouched-or-minimally-adjusted (only patch-target renames if any); cost math: targeted before/after assertions — same meta dict in → same cost_usd/`_turn_cost` out (write these tests BEFORE moving, against current code, then re-run after move).

---

## What NOT to touch (explicit)

- `db.py` schema/queries (only the 3 migration excepts) · `bg_jobs.py` (zero changes) · backends (only the 2 except sites) · `auth.py`, `events.py`, `models.py`, `pipeline.py`, `prompting.py`, `diff_image.py`, `workspace.py` logic (only 3 except sites) · `mcp_stdio.py` (its `isinstance(result, dict)` = HTTP parsing, not the union) · tg_bridge structure (no package split — orchestrator confirmed OUT) · manager split into Registry/Spawn/PromptAssembler — OUT · cost delta→total rewrite — OUT · test-isolation bug — OUT (documented).

## Commit sequence

1. `#refactor-ecs P0: fail-loud excepts + to_thread for sync-DB-in-async + codex loop callback`
2. `#refactor-ecs P1: get_by_name always returns AgentSession — loaded discriminator, update_session_fields`
3. `#refactor-ecs P2: drain main.py → routes/{sessions,system,tg}.py`
4. `#refactor-ecs P3: cycles → wired callbacks, lift cargo-cult lazy imports`
5. `#refactor-ecs P4: split session.py → CostTracker + TurnManager + HibernateManager`

## Self-criticism (pre-Codex, 3 weak spots)

1. **P1 `update_session_fields` whitelist** may miss a field used by some handler — mitigation: migrate only the 4 listed sites, others keep direct attribute writes on live sessions (still better than today: no dict branch).
2. **P2 SSE stream handler** captures module state (queues/manager) — if it closes over main.py globals today, move must carry them; route-surface test won't catch a broken stream → manual SSE smoke (curl the stream endpoint).
3. **P3 hook reset in `stop_bridge`** — if tests start/stop bridge repeatedly, stale hooks could leak between tests → reset in `stop_bridge` + autouse-safe None defaults.

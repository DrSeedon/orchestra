# Orchestra — Architectural Audit

**Date:** 2026-06-11
**Scope:** All 27 Python files in `app/` (~12 100 lines)
**Method:** Full read of every file + direct verification of the highest-impact claims.
**Constraint honored:** No code touched. Research + report only.

> **Verification note.** Findings below were cross-checked against the source before inclusion. Two claims raised by sub-readers were **downgraded as factually wrong** and are documented as such in [Appendix A](#appendix-a--rejected-findings) so they don't pollute the backlog. Everything in Parts 3–5 was confirmed by reading the cited lines.

---

## Part 1 — Dependency Map

### 1.1 Internal import graph (who imports whom)

```
events.py ──────────────► (backend_protocol, backend_claude, backend_codex, session)
                          leaf, zero app deps

models.py ──────────────► (pipeline, manager, backend_claude, backend_codex)
                          leaf, zero app deps

prompting.py ───────────► (manager, session, main)
                          leaf, zero app deps (only stdlib + yaml)

diff_image.py ──────────► (tg_bridge)
                          leaf, zero app deps

auth.py ────────────────► (main)              leaf
ssh_tunnel.py ──────────► (main, routes/proxy) leaf
proxy_manager.py ───────► (routes/proxy)       lazy→manager (MCP_BASE_ENV)

db.py ──────────────────► (everything)         data layer, zero app deps

pipeline.py ────► models
backend_* ──────► events, models

session.py ─────► events, prompting, db
              └─ lazy→ backend_claude, backend_codex, pipeline, db.get_profile,
                       bg_jobs, models, tg_bridge        ◄── CYCLE (see 1.2)

workspace.py ───► (lazy) db, pipeline          sync git layer

bg_jobs.py ─────► db
              └─ lazy→ db (extra fns)

tm.py ──────────► db
              └─ lazy→ tm_yougile               ◄── CYCLE (see 1.2)
tm_yougile.py ──► tm (top-level, for tm._conn)
tm_import_yougile.py ► tm, tm_yougile

manager.py ─────► session, prompting, workspace, models, pipeline, db
              └─ lazy→ models, tm, bg_jobs, tg_bridge, db, workspace

main.py ────────► db, pipeline, deps, models, session, auth, routes/{tm,bg,proxy}
              └─ lazy→ ~30 deferred imports inside handlers (auth, db, prompting,
                       workspace, tm, tg_bridge, ssh_tunnel, bg_jobs, httpx, ...)

deps.py ────────► manager        (singleton holder)
tg_bridge.py ───► diff_image, db
              └─ lazy→ manager, db, diff_image
```

### 1.2 Circular dependencies (all currently broken by lazy imports)

| Cycle | Broken how | Status |
|---|---|---|
| **`session.py` ↔ `tg_bridge.py`** — session needs `check_scope_idle`/`notify_scope_running`/`_manager`; tg_bridge needs `SessionManager` + session data | Lazy imports inside methods (`session.py:910,921`; `tg_bridge.py:1548`) | Real cycle, runtime-deferred |
| **`tm.py` ↔ `tm_yougile.py`** — tm_yougile imports `tm._conn` at top; tm lazily imports `yougile_sync_task`/`update_payment_journal` | Lazy imports inside `tm.py:696,729` | Real cycle, runtime-deferred |
| **`manager.py` → `tg_bridge.py` → `manager.py`** | Lazy in both directions | Real cycle, runtime-deferred |
| **`proxy_manager.py` → `manager.MCP_BASE_ENV`** | Lazy import of a mutable global | Coupling smell, not a hard cycle |
| **`main.py` → {workspace, tm, tg_bridge, bg_jobs}** | ~30 lazy imports in handlers | Partly cycle-avoidance, partly accidental |

**Conclusion:** The import graph is a **DAG only because ~40 imports were pushed inside functions**. The genuine structural cycles are `session↔tg_bridge`, `tm↔tm_yougile`, and `manager↔tg_bridge`. These are the load-bearing knots; the rest of `main.py`'s lazy imports are mostly cargo-culted (the same module is imported lazily in one handler and at top-level elsewhere).

### 1.3 The two hub nodes

- **`db.py`** — imported by everyone. This is correct for a data layer (a shared leaf with no app deps). Healthy hub.
- **`manager.py` + `session.py` + `tg_bridge.py`** — the three god objects form a tight triangle, each lazily importing the others. This is the **unhealthy** hub: the core control plane is one tangled cluster, not three layers.

---

## Part 2 — Per-Module Assessment

Score: 5 = clean, single responsibility, testable · 1 = god object / disaster.

| # | Module | Lines | Responsibility verdict | Score |
|---|---|---:|---|:--:|
| 1 | `events.py` | 22 | Unified event dataclass. Perfect. | **5** |
| 2 | `backend_protocol.py` | 15 | Backend Protocol interface. Perfect. | **5** |
| 3 | `deps.py` | 5 | Singleton manager holder. Trivial, correct. | **5** |
| 4 | `auth.py` | 59 | HMAC cookie auth. Pure, focused. (No token expiry — documented tradeoff.) | **5** |
| 5 | `models.py` | 97 | Model registry. Clean data + 3 helpers. Minor: `resolve_model` silent passthrough. | **4** |
| 6 | `prompting.py` | 186 | Prompt/catalog file helpers. Pure, no app deps. Minor catalog dup w/ manager. | **4** |
| 7 | `pipeline.py` | 491 | Pydantic manifest loader. Well-structured. `lru_cache` never invalidated (test hazard). | **4** |
| 8 | `diff_image.py` | 330 | PNG renderers. Single responsibility. Fonts reloaded every call; `_draw_header` unused; 5× PNG/width boilerplate; hardcoded font path + path prefixes. | **4** |
| 9 | `backend_claude.py` | 359 | SDK wrapper. Clean. 3 tool-block lists to keep in sync; silent `disconnect`; cost recalc complex. | **4** |
| 10 | `ssh_tunnel.py` | 144 | SSH tunnel processes. Proper async subprocess. Global `_tunnels` race if start/stop overlap. | **4** |
| 11 | `bg_jobs.py` | 499 | Background-job manager. **Exemplary async** — all `create_subprocess_exec`, cleanup in `finally`, DB-authoritative, optimistic-lock trigger claim. | **4.5** |
| 12 | `db.py` | 1070 | SQLite layer. WAL, `busy_timeout`, proper `ON CONFLICT` (no `INSERT OR REPLACE` bug), idempotent migrations. Minus: silent migration excepts, no pooling, conn-per-call. | **4** |
| 13 | `proxy_manager.py` | 158 | Proxy switching. Tightly scoped. Mutates `manager.MCP_BASE_ENV` global; cache not invalidated on env change. | **3.5** |
| 14 | `mcp_stdio.py` | 741 | MCP tool server (thin HTTP wrapper — good, avoids in-proc deadlock). Minus: **hardcoded `/home/maxim/.npm-global/bin/codex`**; fragile shell-string for codex_review; presentation logic in tools. | **3.5** |
| 15 | `backend_codex.py` | 244 | Codex CLI wrapper. One-shot subprocess. Manual prompt escaping (line 71); silently skips malformed JSON; cost logic dup w/ claude. | **3** |
| 16 | `tm_import_yougile.py` | 213 | One-time import. Atomic, idempotent. Config + logic duplicated w/ tm_yougile; bypasses tm API; O(n) per-row lookups. | **2.5** |
| 17 | `tm.py` | 933 | Task manager. **Async firing + sync DB mixed in**; lazy cycle import to tm_yougile; `_fire_sync`/`_fire_journal_sync` near-identical; debt calc dup ×3. | **2.5** |
| 18 | `workspace.py` | 845 | Git worktree layer. Sync git (correctly run via `to_thread` by callers). Minus: 3× duplicated `flock` blocks; O(n) `git diff-tree` per commit inside merge lock; non-idempotent mkdir-before-`worktree add`; some silent reset failures. | **3** |
| 19 | `tm_yougile.py` | 317 | YouGile sync. **Sync DB calls inside `async def`** (real event-loop blocker — these are NOT wrapped in `to_thread`); hardcoded board IDs; unused `MAX_RETRIES`; debt calc dup. | **2** |
| 20 | `manager.py` | 1139 | SessionManager. **God object**: CRUD + spawn + prompt assembly + visibility + worktree + validation + auto-resume + cleanup. O(N) scans; silent excepts; TOCTOU on concurrent spawn; `get_by_name` returns `dict\|Session\|None`. | **2** |
| 21 | `main.py` | 1574 | FastAPI app. **Monolith**: ~58 handlers still here despite `routes/` existing; ~30 lazy imports; silent excepts; direct `session._persist()` mutation in handlers; repeated lookup boilerplate; hardcoded project paths + UTC+7. | **2** |
| 22 | `session.py` | 1109 | AgentSession. **God object**: lifecycle + event loop + persistence + hibernate + compact + cost + MCP load + auto-report. ~15 fire-and-forget tasks; delta-cost fragility; unbounded `_turn_logs`/`_pending_messages`; codex turn loop has no done-callback. | **2** |
| 23 | `tg_bridge.py` | 1558 | TG bridge. **Worst god object**: ~17 responsibilities; 11 mutable globals (no locks on `_flood_until`/`_last_send`/`config`); unbounded per-session polling loops; blocking `subprocess.run` in `_bot_api_health_loop`; 6× send+mirror dup. | **1** |
| 24 | `routes/proxy.py` | 35 | Proxy routes. Clean delegation. Model for the others. | **5** |
| 25 | `routes/bg.py` | 55 | BG-job routes. Clean. Inherits `get_by_name` union smell. | **4** |
| 26 | `routes/tm.py` | 173 | TM routes. Clean, Pydantic-validated. One lazy cycle import. | **4** |
| 27 | `routes/__init__.py` | 0 | empty | — |

**Distribution:** 6 modules score 4.5–5 (the leaves + bg_jobs), 7 score 3–4 (backends, infra, db), and the **four core control-plane files (`session`, `manager`, `main`, `tg_bridge`) carry the entire architectural debt** at 1–2. ~5 200 of 12 100 lines (43%) live in those four files.

---

## Part 3 — Top-10 Костыли (verified, with line refs)

Ranked by blast radius × likelihood.

### #1 — `get_by_name` returns `AgentSession | dict | None` (type confusion virus)
**`manager.py:749-756`.** In-memory hit returns a live `AgentSession`; DB fallback returns a raw `dict`. Every caller must branch:
```python
sid = found["id"] if isinstance(found, dict) else found.id   # main.py:820, repeated 10+×
```
This `isinstance(found, dict)` check is copy-pasted across `main.py` (≥10 sites), `routes/bg.py:32`, etc. It's a confused data model leaking into every consumer.
**Fix:** Always return a `AgentSession` (hydrate the DB row into a lightweight detached `AgentSession` on miss) **or** always return a dict (`.to_dict()`), never a union. One representation. ~1 day; touches every call site but mechanically.

### #2 — `tg_bridge.py` is a 1558-line god object with 11 unlocked mutable globals
**`tg_bridge.py:32-36, 71, 87, 267, 503-504, 822`.** `_flood_until`/`_last_send` are floats mutated from any coroutine with no lock — under concurrent sends the flood-control window is a race. `config` is written non-atomically (`save_config` does `write_text` with no temp+rename). 17 responsibilities in one file (bot lifecycle, routing, media, transcription, topics, streaming, formatting, diff dispatch, mirror, restart, health loop).
**Fix:** Split into `tg/bot.py` (lifecycle), `tg/handlers.py`, `tg/stream.py`, `tg/format.py`, `tg/topics.py`. Guard `config` writes with atomic write; serialize flood-control through a single `asyncio.Lock`. Incremental — extract one module at a time.

### #3 — Sync SQLite inside `async def` in `tm_yougile.py` (real event-loop blocker)
**`tm_yougile.py:104-179, 206, 234`.** `async def yougile_sync_task()` opens `tm._conn()` and runs `conn.execute("BEGIN IMMEDIATE")` directly on the event-loop thread — no `to_thread`. Same in `_update_done_column_title`, `_ensure_journal_task`. While these run, every other agent's turn stalls. (Contrast: `workspace.py` does the same sync work but callers wrap it in `to_thread` — see Appendix A.)
**Fix:** Wrap the DB portions in `await asyncio.to_thread(...)`, keep only the httpx calls on the loop. ~0.5 day.

### #4 — `session.py` fire-and-forget task soup (~15 untracked `create_task`/`_spawn_bg`)
**`session.py:339, 534-541, 548, 559, 627, 633, 638, 753, 894`.** Auto-report, scope notifications, context refresh, auto-continue, auto-compact, flush — all fire-and-forget. `_auto_continue` (line 555) can **recurse without bound** if the agent keeps hitting `max_turns`. The **codex turn loop (line 358) has no `add_done_callback`** while the Claude one does (line 376). *(Codex-verified scope:* `_codex_turn_loop` does catch `Exception` and set IDLE in `finally` at `session.py:461,464`, so a normal exception is **not** silently fatal — the real gap is unobserved `BaseException`/finally-failure and the asymmetry with the Claude loop, which has no logging callback.)*
**Fix:** A single `_spawn_bg` that *all* background work goes through (already exists at 237–247 — just route everything through it), add a depth counter to `_auto_continue`, attach the done-callback to the codex loop. ~1 day.

### #5 — `main.py` never finished its route extraction
**`main.py` (whole file).** `routes/{tm,bg,proxy}.py` exist and are clean (4–5/5), proving the pattern works — but ~58 handlers still live in `main.py`, including all session CRUD, merge/switch, files, usage, OAuth, GitHub webhook, test-lock. Business logic (`_build_path_map`, `_is_safe_path`, `_refresh_oauth_token`, `_get_agents_cost`, `_run_git`) sits in the app-factory file, untestable without booting the app.
**Fix:** Continue the existing pattern: `routes/sessions.py`, `routes/files.py`, `routes/usage.py`, `routes/orchestrators.py`. Move helpers to a `services/` or `util/` module. Highest-leverage refactor for testability. ~2-3 days, incremental per-router.

### #6 — Handlers mutate session state then call `session._persist()` directly
**`main.py:655-656, 688-689, 707-708, 726-727, 789-794`.** HTTP handlers reach into `session.status = …; session._persist()` with no validation and no transaction. Two concurrent PUTs on the same session race (last-write-wins). Persistence is a private method called from the route layer — service-layer boundary violated.
**Fix:** A `manager.update_session_fields(name, scope, **fields)` method that validates + persists atomically; handlers call that. Pairs with #1.

### #7 — `workspace.py` triplicated merge-lock + O(n) per-commit git calls
**`workspace.py:363-366, 624-625, 687` (3× identical `flock`)** and **`447-451, 547` (one `git diff-tree --numstat` per merged commit, inside the merge lock).** For an N-commit branch that's N subprocesses serialized under the global merge mutex — every other merge waits.
**Fix:** Extract `@contextmanager _merge_lock(repo)`; replace per-commit stat loop with a single `git diff --numstat base..head`. ~0.5 day.

### #8 — Hardcoded machine-specific paths
**`mcp_stdio.py:655`** `/home/maxim/.npm-global/bin/codex` · **`diff_image.py:8`** `/usr/share/fonts/.../DejaVuSansMono.ttf` and **`:27-33`** prefix-strip of `/mnt/data/Projects/Python/`, `/home/` · **`main.py:229-232`** project roots `/mnt/data/Projects/{Python,Unity}` · **`main.py:625` & `tg_bridge.py:329`** hardcoded `UTC+7`. These break on any other machine / VPS deploy.
**Fix:** `shutil.which("codex")` / env vars; `CURRENCY`-style env config for paths & timezone. ~0.5 day, mechanical.

### #9 — `tm.py` async-firing helpers duplicated + circular import
**`tm.py:687-718` (`_fire_sync`) vs `721-752` (`_fire_journal_sync`)** are near-identical (`get_event_loop().create_task`, same `except RuntimeError` swallow, same nested `_do()`). Both lazily `from app.tm_yougile import …` to break the `tm↔tm_yougile` cycle. A "pure data" module is scheduling async work and importing its own peripheral sync layer.
**Fix:** Extract `_fire_async(coro)`; invert the dependency — let the route layer fire sync, or register `tm.on_task_synced` callback set by tm_yougile at startup. ~0.5 day.

### #10 — Silent `except` swallowing operational failures
Representative (not exhaustive): **`main.py:917-918, 959-960`** task-link after merge silently dropped; **`main.py:397`** `except PermissionError: pass` → incomplete file list; **`session.py:916-917, 922-927`** TG notify swallowed; **`manager.py:552-553, 602-603, 636-638`** task update + worktree cleanup failures swallowed (→ zombie worktrees); **`db.py`** migration excepts unlogged. Per the project's own "Fail loud" principle these are anti-pattern.
**Fix:** Replace `except …: pass` with `logger.warning(... , exc_info=True)` at minimum; for worktree/task-link, surface to the caller. ~1 day sweep.

**Honorable mentions:** unbounded `_turn_logs`/`_pending_messages` growth (`session.py:478, 159`); `lru_cache` on `load_pipeline` never invalidated (`pipeline.py:265`); fonts reloaded on every `diff_image` render; `pipeline.py`/`models.py` duplicate `_model_is_known`.

### Additional async/security items (Codex-surfaced, same classes as #3 / #10)

- **`routes/tm.py` has the same sync-DB-in-`async` blocker as #3** — and the original per-cluster readers missed it. All TM route handlers are `async def` but call sync task-manager APIs / raw SQLite directly: `_tm.api_create_task` (`routes/tm.py:56`), `_tm._conn()` (`:69`), `_tm.api_update_task` (`:101`), payment/status calls (`:113, :122`), raw queries (`:134, :151, :160`). This is the **most-trafficked** instance of the blocker and must be fixed together with `tm_yougile.py` (#3). Folded into P0 below.
- **`main.py:1427` `restart_server`** runs `subprocess.run(..., timeout=10)` in an `async` handler — same "sync work in async route" bucket, lower severity (manual admin action).
- **`main.py:367-376` `open_file` bypasses `_is_safe_path`** — accepts any existing path and launches `xdg-open` when `ALLOW_OPEN_FOLDER` is set, while `get_file_content` (`:336`) and `list_files` (`:380`) both go through the safety check. Env/auth-gated, but an inconsistent security surface; route it through `_is_safe_path` too.

---

## Part 4 — Proposed Architecture (ECS-flavored)

The codebase already *wants* to be layered — the leaves (`events`, `models`, `prompting`, `db`, backends, `bg_jobs`, `routes/*`) are clean. The debt is concentrated in the **control-plane triangle** (`session`↔`manager`↔`tg_bridge`) and the **monolithic `main.py`**. The goal is not a rewrite; it's to **drain those four files into the layers that already exist** and to **cut the three real cycles**.

### Target layering (dependencies point downward only)

```
┌─────────────────────────────────────────────────────────────┐
│  TRANSPORT          main.py(thin)  routes/*  mcp_stdio  tg/*  │  ← only I/O + serialization
├─────────────────────────────────────────────────────────────┤
│  SYSTEMS (ECS)      SpawnSystem   PromptSystem   CostSystem   │  ← stateless functions over state
│                     CompactSystem MergeSystem    NotifySystem │
├─────────────────────────────────────────────────────────────┤
│  STATE / ENTITIES   SessionState(data)   SessionRegistry      │  ← plain data, one source of truth
├─────────────────────────────────────────────────────────────┤
│  DRIVERS            backend_claude/codex  workspace(git)       │  ← external-process adapters
│                     bg_jobs  tg driver    yougile  proxy/ssh   │
├─────────────────────────────────────────────────────────────┤
│  FOUNDATION         db.py   events.py   models.py  prompting   │  ← leaves, no app deps
└─────────────────────────────────────────────────────────────┘
```

### What moves where (no big-bang — these are *moves*, not rewrites)

1. **Split `AgentSession` incrementally — extract ONE painful subsystem at a time, not all five at once.**
   Do **not** do a literal 5-way split in one shot (over-engineering for a 10-user MVP). Order by pain:
   - **First: `CostSystem`** — pull `_apply_turn_result` + token/cost tracking out, and make it **total-based, not delta-based**, killing the session-id-reset fragility (#2 in the cost-risk list). Smallest, highest-value, lowest-risk extraction.
   - **Then: `CompactSystem`** — the 106-line compact state machine is the next-most-tangled unit.
   - Leave `EventLoopSystem`/`PersistenceSystem` extraction optional — only if the file is still painful after the first two. The remaining `AgentSession` is the "entity" (plain data + thin coordinator). This serves the ECS goal *gradually*: each extraction ships independently.

2. **Split `SessionManager` into `SessionRegistry` + `SpawnSystem` + `PromptAssembler`.**
   - `SessionRegistry`: the `sessions` dict + lookups, indexed by `(name, scope)` instead of O(N) scan, returning **one type** (fixes #1).
   - `SpawnSystem`: the 200-line `create_session` orchestration.
   - `PromptAssembler`: `ROLE_SYSTEM_PROMPT`, catalogs, worker blocks (also absorbs the catalog dup currently split with `prompting.py`).

3. **Cut the `session↔tg_bridge` cycle with explicit startup-wired callbacks — NOT a generic event bus.**
   Session already has `on_idle`. Add two more callback slots (`on_scope_idle`, `on_scope_running`) that `tg_bridge` *assigns* at startup. Session depends on three function attributes, not on `tg_bridge`. Same trick kills `manager↔tg_bridge` and `tm↔tm_yougile` (`tm.on_task_synced`). **Deliberately avoid a pub/sub event bus** — for 3 cycles and ~10 users that's abstraction creep; explicit wired callbacks stay flat and greppable.

4. **Finish `main.py` → `routes/`** (Part 3 #5). `main.py` becomes lifespan + middleware + `include_router` only (~150 lines).

5. **`tg_bridge.py` → `tg/` package** (Part 3 #2).

### What explicitly stays as-is (don't gold-plate)
- `db.py` connection-per-call + WAL is fine for ~10 users; **do not** add a connection pool. (Flat > clever.)
- `bg_jobs.py`, `routes/proxy.py`, `auth.py`, `events.py`, backends — leave them. They're done.
- `diff_image.py` — only cache the font and dedupe the 5 helpers; no redesign.

---

## Part 5 — Refactoring Plan (ordered, incremental)

Effort: **S** ≤ 0.5d · **M** 0.5–1d · **L** 1–3d. Each phase ships independently and leaves the system green.

| # | Task | Effort | Depends on | Risk | Payoff |
|--:|---|:--:|:--:|:--:|---|
| **P0 — correctness & portability (do first, low risk)** |
| 1 | Fix sync-DB-in-async in `tm_yougile.py` **and `routes/tm.py`** — wrap DB/API blocks in `to_thread` (#3) | M | — | Low* | Removes event-loop stalls during YouGile sync + TM routes (the most-trafficked case) |
| 2 | Codex turn loop `add_done_callback` + `_auto_continue` depth cap (#4 subset) | S | — | Low | Stops silent session death + unbounded recursion |
| 3 | De-hardcode paths/timezone → env vars (#8) | S | — | Low | Deployable on VPS / other machines |
| 4 | Silent-except sweep → `logger.warning(exc_info=True)`; surface worktree-cleanup + task-link failures (#10) | M | — | Low | "Fail loud"; kills zombie worktrees |
| 5 | `workspace.py`: extract `_merge_lock` ctxmgr + single `git diff --numstat` (#7) | M | — | Low | Faster merges, no triplicated lock |
| **P1 — the type-confusion virus (unblocks everything above the registry)** |
| 6 | Make `get_by_name` return one type; add `(name,scope)` index; `manager.update_session_fields()` (#1, #6) | L | — | Med | Deletes `isinstance(found,dict)` from ~12 sites; safe state updates |
| 7 | Move handler-level `session._persist()` mutation behind #6's method (#6) | M | 6 | Low | Service boundary restored |
| **P2 — drain main.py (testability)** |
| 8 | Extract `routes/sessions.py` (CRUD, send, merge, switch, delete) | L | 6 | Med | Biggest testability win |
| 9 | Extract `routes/files.py`, `routes/usage.py`, `routes/orchestrators.py`; helpers → `services/` | L | 8 | Med | `main.py` → ~150 lines |
| **P3 — break the cycles (architectural)** |
| 10 | **Explicit wired callbacks** (not an event bus): add `on_scope_idle`/`on_scope_running` to session, `on_task_synced` to tm; `tg_bridge`/`tm_yougile` assign them at startup (#9 + cycle cuts). *Defer if cycles aren't actively blocking an edit.* | M | — | Med | Removes 3 real cycles + ~half the lazy imports |
| 11 | `tm.py`: extract `_fire_async`; invert tm→tm_yougile dep via #10 (#9) | M | 10 | Low | Dedupe + cycle gone |
| **P4 — split the god objects (largest, do last, fully incremental)** |
| 12 | `tg_bridge.py` → `tg/{bot,handlers,stream,format,topics}.py`; lock `_flood_until`/`config` (#2) | L | 10 | Med | 1→4/5; testable formatting |
| 13a | `AgentSession`: extract **`CostSystem` only**, total-based not delta | M | 6 | Med | Kills cost fragility (do this even if 13b/c never happen) |
| 13b | `AgentSession`: extract `CompactSystem` (106-line state machine) | M | 13a | Med | Untangles the worst method |
| 13c | *(optional)* extract `EventLoopSystem`/`PersistenceSystem` only if still painful | L | 13b | High | ECS shape — skip unless needed |
| 14 | `SessionManager` → `SessionRegistry` + `SpawnSystem` + `PromptAssembler` | L | 6,13 | High | Final god-object split |

### Sequencing rationale
- **P0 is pure win, low structural risk** — ship it this week regardless of the rest. *(\*Caveat: wrapping `tm_yougile.py`/`routes/tm.py` DB blocks in `to_thread` changes transaction timing relative to the YouGile HTTP calls — verify a sync still completes end-to-end before/after. Not zero-risk, but low.)*
- **P1 (#6) is the keystone**: the `dict|Session` union poisons `main.py`, `routes/bg.py`, and blocks clean route extraction. Do it before P2.
- **P3 before P4**: cutting cycles first means the god-object splits (P4) don't have to fight lazy imports.
- **P4 is high-risk and last** — it's where most lines move. By then the registry, routes, and callback bus exist, so the splits are mechanical relocations, not redesigns. Each of #12/#13/#14 can land one extracted module at a time behind the unchanged public surface.

### What success looks like
- No `isinstance(x, dict)` on a session anywhere.
- `main.py` < 200 lines; every handler in a `routes/` module.
- Zero `async def` that calls SQLite without `to_thread`.
- The `session/manager/tg_bridge` triangle replaced by downward-only edges through explicit wired callbacks.
- Smaller files are a *smell to chase, not a hard gate* — file size is a symptom of the god-object problem, not the target itself. Optimize for "one responsibility per file," and the line counts fall out. Don't split a cohesive file just to hit a number.

---

## Appendix A — Rejected findings

Two sub-reader claims were **verified false** and excluded from the backlog:

1. **"`workspace.py` merge blocks the event loop / merges deadlock under concurrency" (claimed BLOCKER).**
   False. `merge_worktree_to_main` and friends are **synchronous `def`** (`workspace.py:354, 593`), and every caller invokes them via `await asyncio.to_thread(...)` (`main.py:884, 909, 950`; `manager.py:567, 601, 636`). The `fcntl.flock` blocks a *worker thread*, not the loop. The serialization-under-merge-lock observation (#7) is real and kept; the "event-loop deadlock" framing is wrong.

2. **"`db.py` still has the `INSERT OR REPLACE` `created_at` bug."**
   False. The code uses proper `INSERT … ON CONFLICT … DO UPDATE`; no `INSERT OR REPLACE` remains. The historical bug (per project memory) was already fixed.

*(The real async blocker is in `tm_yougile.py` (#3) **and `routes/tm.py`** — the latter surfaced in the Codex review, see below.)*

---

## Appendix B — Codex cross-review (GPT-5.5)

This report was adversarially reviewed by Codex (full review in `codex-review-arch-audit.md`). Verdict: *"broadly solid and not a rubber stamp; most Top-10 claims are real, line refs mostly check out, Appendix A is correct."* Corrections **already folded into the report above**:

1. **Codex-loop overstatement softened** (Part 3 #4) — `_codex_turn_loop` does set IDLE in `finally` (`session.py:464`), so a normal exception isn't silently fatal; the real gap is `BaseException`/asymmetry.
2. **`routes/tm.py` async blocker added** (Honorable mentions + P0) — same class as #3, most-trafficked instance, originally missed.
3. **`main.py:1427` restart_server + `main.py:367` open_file safety bypass added.**
4. **Over-engineering tempered** — `AgentSession` split is now incremental (CostSystem first); event bus downgraded to explicit wired callbacks; "<600 lines" demoted from gate to smell; "zero risk" P0 → "low risk" with transaction-timing caveat.

Remaining Codex `nit` (not actioned, cosmetic): Appendix A cites `main.py:909` for a `switch_worktree_branch` call that actually starts at `:908` — imprecise but not wrong.

# Report — Full Refactoring P0–P4 (refactor-ecs)

**Status:** DONE. 6 commits (`3a7b76a..e87a5fd`), 34 files, +3252/−2060.
**Tests:** 487 passed (green gate). Route surface byte-identical (snapshot guard, 77 routes).
**Codex:** plan — 3 rounds, 6 blocking fixed → APPROVED; impl — 2 rounds, 1 blocking fixed → APPROVED.

## What was done

| Phase | Commit | Summary |
|---|---|---|
| P0 | `3a7b76a` | 24 silent excepts → fail-loud; sync SQLite → `to_thread` (tm_yougile + routes/tm, connection-per-helper); **`tm.set_main_loop()` + threadsafe scheduling** (Codex R2-B1 — without it YouGile sync would silently die after to_thread); codex loop done-callback; auto-continue cap 5 |
| P1 | `181fc27` | `get_by_name → AgentSession \| None`; `_hydrate_row` detached sessions (`loaded=False`, `db_row` keeps legacy JSON shape); 34 isinstance sites killed; `update_session_fields()`; live-only guards preserved (interrupt/stop/merge/progress/change_orchestrator_scope) |
| P2 | `b46143e` | main.py 1574 → **91 lines**; `routes/{sessions(26),system(27),tg(3)}.py`; templates → deps; `/api/open-file` safety fix; `test_routes_surface.py` permanent guard |
| P3 | `92159f2` | 3 real cycles cut via wired callbacks (session/manager↔tg_bridge, tm↔tm_yougile); hooks registered at startup with guaranteed lifespan import; `runtime_env.py` leaf for MCP_BASE_ENV; `_fire_async` dedupe; safe lazy-import lifts (remaining ones justified: heavy SDK / test late-binding) |
| P4 | `57949c5` | session.py 1109 → 902; `CostTracker`/`TurnManager`/`HibernateManager` as stateless systems over session state; `session_state.py` leaf; cost math AS-IS delta-based, locked by 7-case contract test written pre-split |
| — | `e87a5fd` | Codex impl fix (stop_bridge clears stale `bot`/`_manager`), CHANGELOG v2.20.0, TODO |

## Deviations from plan
- None in scope. Codex impl suggestion (pending sync_log row in no-loop CLI) — rejected as behavior-change, logged to TODO.md.
- Test-side fixes required beyond plan: `_MockBackend.events()` hot-loop re-arm (pre-existing flaw, surfaced mid-work), `FakeSession.loaded` attr, patch-target renames for moved symbols.

## Pre-existing issues (NOT mine, documented in TODO.md)
1. `test_default_equals_upstream.py` poisons 106 downstream tests (lru_cache + PIPELINES_DIR monkeypatch) — exists on main; gate runs it isolated.
2. 6 tests in that file fail on main (prompt-tag drift `<task-management>` etc.).
3. Pending `tm_sync_log` rows in CLI/no-loop contexts (legacy, kept).

## Verification
- `pytest tests/ -q --ignore=tests/test_frontend.py --ignore=tests/test_default_equals_upstream.py` → 487 passed.
- `pytest tests/test_default_equals_upstream.py` isolated → 6 failed / 60 passed — identical to main (pre-existing).
- `import app.main` smoke ok; route snapshot identical; YouGile sync thread→loop contract covered by `test_tm_sync_loop.py`.

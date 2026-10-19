# V-974: repair the red main CI checks

The failing CI run was `39223141528` on `main` at `3bf1651e7`. Its full stdout is preserved verbatim in [`main-ci-39223141528.log`](main-ci-39223141528.log). The current `main` at investigation time was `2fe8af9f6` (V-973), which includes the V-967 task-card changes already present in the failed CI revision.

## Causes and fixes

The browser failures came from stale assertions after V-967 changed tool-card presentation. The notify test found the card's semantic `chat-notify-user` highlight and navigation, but also required the old exact red RGB value. That color depends on the current theme token, so the exact-color assertion was removed while semantic highlight and navigation checks remain. The task-card tests expected unknown-tool fallback text to equal raw JSON or contain the internal `task_archive` symbol. The UI formats a readable tool label and argument; the checks now verify the meaningful fallback argument (`ARCH-9`) survives in both live and history paths. Existing checks still verify raw task payloads remain available in technical details and HTML escaping is preserved.

The unit failure was test setup: `test_lifespan_shuts_down_owned_tasks_on_exit` replaced `app_main.init_db` with a no-op, but lifespan separately initializes checklist tables and later clears open clocks. Its mock now invokes `db.init_db()` against the test's `tmp_path` database. The lifespan also assigns `db.DB_PATH` from `ORCHESTRA_DB_PATH`; the test now registers `DB_PATH` with pytest's `monkeypatch`, so teardown restores the autouse fixture's isolated path instead of leaving the module global pointed at the test DB. The lifespan shutdown assertions and real schema initialization remain exercised.

Orchestrator acceptance reported a combined browser/unit run with `sqlite3.OperationalError: database is locked` in `_seed_dashboard_db`. The exact command passed in this worktree before the fix too, so that specific lock did not reproduce locally. Source inspection found that `_seed_dashboard_db` temporarily changed process-global `db.DB_PATH`, then opened implicit connections through `init_db()` and `save_session()`. The fixture now initializes and writes through an explicit `db_path` and one path-specific connection, so it cannot redirect other test activity through the global. The lifespan test separately restores its own `DB_PATH` assignment with pytest's `monkeypatch`. The exact combined command passed again after both changes. Captured outputs are [`combined-before.log`](combined-before.log) and [`combined-after.log`](combined-after.log).

No production code changed, so no CHANGELOG entry was needed.

## Verification

- Combined acceptance command (unit lifespan plus the three affected browser tests), `uv run --frozen python -m pytest tests/test_restart_generation_liveness.py tests/test_frontend.py::test_notify_user_call_is_highlighted_and_navigable_from_the_timeline tests/test_frontend.py::test_live_task_tool_rows_show_russian_labels_and_escaped_title tests/test_frontend.py::test_task_tool_rows_from_history_keep_raw_details_and_fallback -q -n 0` — 25 passed in 13.61 s after the cleanup fix.
- `uv run --frozen python -m pytest tests/test_restart_generation_liveness.py -q -n 0` — 19 passed in 4.98 s.
- `uv run --frozen python -m pytest tests/test_frontend.py -q -n 0` — 134 passed, 1 skipped in 107.35 s; captured in [`browser-after.log`](browser-after.log).
- CI unit shard 4 (the workflow's exact 52-file shard, `-n 2 --dist=loadscope -m "not live_probe and not browser"`) — 512 passed in 29.75 s; captured in [`shard-4-after.log`](shard-4-after.log).
- Full CI browser job `uv run --frozen python -m pytest --rootdir=. -n 2 --dist=loadscope -v -rf --timeout=30 -m browser tests/` — 207 passed, 7 skipped in 115.39 s; captured in [`ci-browser-after.log`](ci-browser-after.log).
- Absolute imported package path, from `uv run --frozen python -c "import app; print(app.__file__)"`: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-dashboard/app/__init__.py`.
- The original captured CI log was scanned for common API-key/token forms (`sk-…`, GitHub token prefixes, bearer tokens, and AWS access-key IDs); no matches.

All checks use isolated local test fixtures. No production service, live database, or provider CLI was used.

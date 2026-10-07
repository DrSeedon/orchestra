# V-753 — dashboard TG Topic toggle

`_showAgentContextMenu()` called `PATCH /api/sessions/{name}/tg-topic`, a second handler that set `found.tg_topic` and called `save_session(found.to_dict())`. That direct save omitted the required `session_id` binding and returned HTTP 500. The existing `POST /api/sessions/{name}/tg_topic` handler uses `manager.update_session_fields()`, which updates both loaded and detached sessions and persists the field.

The dashboard now calls the existing POST handler with `{scope, enabled}` in JSON, and the duplicate PATCH handler is removed. The route surface snapshot was updated. A Playwright regression test opens the actual context menu, toggles both directions through the browser's request path, checks the HTTP response, then reloads the session list from the database and checks the saved `tg_topic` value. The test was first run against the old implementation and failed waiting for its expected POST request; after the fix it passed.

## Merge-gate guard

`test_route_surface_snapshot` did not catch the source rollback because the merge gate's mutation tree overlays changed Python test files onto the target checkout, but does not overlay changed JSON snapshots. The target checkout therefore retained main's old route snapshot alongside main's old PATCH route, and that pair passed together.

Added a non-browser test in `tests/test_frontend.py` that extracts and executes the production `_showAgentContextMenu()` function in Node with small DOM/API stubs, captures its HTTP request, and parses `sessions.py` route decorators. It checks the POST path, method and payload against the manager-backed endpoint and rejects the duplicate PATCH route. It requests no browser fixture, so the conftest browser-marker rule leaves it eligible for the merge gate. The existing Playwright regression remains in place.

The gate mutation tree confirmed the cause: it overlays changed `tests/*.py` files but not the changed JSON snapshot. `test_route_surface_snapshot` therefore paired the target checkout's old PATCH route with its old snapshot and passed. Main at mutation time was `4e7a79f4015fddd7e8a073948639eca5c5aca09d`.

## Checks

`/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_frontend.py::test_tg_topic_context_menu_persists_through_frontend_api -q` → **1 passed** (Chromium). Against the old frontend call, the same test failed waiting for the expected POST; after changing the call it verifies both OFF→ON and ON→OFF, HTTP 200, and the value returned from a fresh session-list read.

`/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_tg_bridge_instance_guard.py tests/test_tg_bridge.py tests/test_manager.py tests/test_p1_union.py tests/test_frontend.py tests/test_routes_surface.py -q` → **522 passed, 1 skipped, exit code 0**. This covers every Python test file matched by `rg -l 'tg_topic|tg-topic' tests -g '*.py'` (5 files) plus `tests/test_routes_surface.py`, whose snapshot changed with the removed endpoint. `app` imported from `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-dashboard/app/__init__.py`.

The run emitted a non-failing `BaseSubprocessTransport.__del__` warning with `RuntimeError: Event loop is closed`, attributed to `tests/test_tg_bridge.py::TestTurnFoldStream::test_progress_edit_is_throttled_and_skips_identical_text`. The same teardown warning had appeared on both main and a branch in V-701. It is tracked separately in `TODO.md` and is unrelated to this endpoint change.

`git diff --check` passed.

`app.merge_test_gate.evaluate_test_gate('.', target_ref='main')` → **passed, exit 0**. The selected files were `tests/test_frontend.py` and `tests/test_routes_surface.py`; the browser marker deselected browser tests, while the new Node guard remained selected. The mutation run against main used the changed `tests/test_frontend.py` and returned `passed / guarded_source_change` with exit 1 for its test subprocess. The diagnostic captured main's actual frontend request as `PATCH /api/sessions/worker/tg-topic?scope=%2Ftest%2Fscope&enabled=true`, `body: null`, and `route contract valid=False`; thus both the old `app.js` call and old `sessions.py` route were observed by the same guard.

## Commit

Committed locally on `adhoc-1791385871-6/fix-dashboard`; the final HEAD is reported with the completion message.

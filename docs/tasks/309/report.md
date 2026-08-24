# #309 implementation report

## Delivered

Implemented the six approved tickets without widening scope:

- **T1 / `d71e1922`:** removed progress, proxy mutation, payment, and YouGile dashboard renderers/controls from `app.js` and `dashboard.html`; retained runtime client/model status, task CRUD/status/acceptance/commit UI, and the `update_progress` MCP/API/session contract.
- **T2 / `bd78f5e2`:** removed only the unreachable `merge_session` route handler; retained `execute_merge_session`, middleware structural 426 compatibility, and operation-v1. The corrected oracle freeze is `5f9877ad`; `993e54b1`’s later T2 literal-path assertion is explicitly superseded/excluded while its valid first-assertion RED evidence remains.
- **T3 / `4c6d51e7`:** collapsed duplicate `POST /api/models/refresh`; generated OpenAPI now has one operation.
- **T4 / `09a82660`:** removed local proxy/tunnel routes, owner modules, lifespan start/stop, mutation UI, and feature-specific proxy tests; retained `/api/models`, `proxy_connected`, and `runtime_env.py` client environment propagation.
- **T5 / `8d075095`:** removed payment/client and YouGile MCP/API/service/prompt surfaces and feature-specific tests; retained task CRUD/status/acceptance/worker-session/commit-link paths. Legacy payment/YouGile tables, columns, and rows were not touched or dropped.
- **T6 / `a7303a8b`:** updated route snapshot and refactored shared merge tests to call the retained `execute_merge_session`; removed payment prepayment test coverage only.

## Acceptance evidence

All frozen acceptance commands are green after implementation:

- `test_t1_dashboard_surfaces_removed.py` — exit 0
- `test_t1_progress_ui_removed.py` — exit 0
- corrected T2 static oracle — exit 0
- `test_merge_operations.py::test_legacy_http_merge_is_426_and_capability_is_visible` — `1 passed in 2.38s`, exit 0 (command used a process-local Python 3.12 `pidfd_open` compatibility shim; no repository change)
- `test_t3_single_model_refresh_route.py` — exit 0
- `test_t4_proxy_tunnel_owner_removed.py` — exit 0
- `test_t5_payment_client_surfaces_removed.py` — exit 0
- `test_t6_yougile_surfaces_removed.py` — exit 0
- `test_t7_route_snapshot_removed_surfaces.py` — exit 0

Generated registry probe: `mcp_count=40`, `payment_tools=[]`, `removed_paths=[]`, `model_refresh_posts=1`. OpenAPI emitted only an unrelated pre-existing duplicate artifact operation warning.

Post-merge follow-up: the original T4/T5 absence gates were incomplete because they did not scan `pipelines/default/prompts/modules/orchestration.md` or the `app/runtime_env.py` owner docstring. Immutable follow-up oracle `test_t8_live_surface_absence.py` was frozen RED in `5aa5f6c5`, reporting exactly those three leftovers; the prompt anchors and stale owner wording were then removed. T8 now exits 0, and the exact live-surface scan over `app`, `pipelines/default/prompts`, and `tests` returns zero matches.

Current-main merge: normal merge commit `760bdaea` brought #327/#319/#315 onto the branch without rebase/reset; their files remain current-main-owned. The original approved removal surface remains 34 paths; the final count is 37 only because the three explicitly authorized follow-up paths are included: `app/runtime_env.py`, `pipelines/default/prompts/modules/orchestration.md`, and the new T8 oracle. `app/db.py` remains unchanged.

Payment-state follow-up: `test_t9_paid_status_inert.py` was frozen RED in `78b2cecf`; it proved legacy `status='paid'` rows remain readable/listable while new create/update/CAS transitions were still writable. Removing only `paid` from `VALID_STATUSES` makes the corrected oracle green with `PYTHONPATH=. uv run python docs/tasks/309/acceptance/test_t9_paid_status_inert.py`; task/API regressions remain `32 passed, 124 deselected`. The legacy `paid` status, payment fields, tables, and rows are not migrated or deleted.

Final post-merge replay: all T1–T8 frozen/corrected oracles plus T9 pass; generated probe remains `mcp_count=40`, no payment tools, no removed paths, one model-refresh POST; final live absence scan returns zero. The final diff is 38 paths: the original approved 34 removal paths plus the three T8 follow-up paths and the one T9 oracle path; `app/db.py` remains unchanged. The normal full suite still has exactly one current-main collection error at `tests/test_process_guard.py` → `scripts/orchestra_process_guard.py:436` (`os.pidfd_open` missing on Python 3.12), not a #309 change.

Focused regressions:

- `tests/test_tm.py tests/test_reducer_role.py` — `25 passed`
- `tests/test_mcp_stdio.py -k 'not task_update_distinguishes_omitted_and_explicitly_cleared_command'` — `105 passed, 1 deselected`
- `tests/test_routes_surface.py` — `2 passed`
- `tests/test_api.py -k merge` — `26 passed, 105 deselected`
- `tests/test_api.py -k 'task and not prepayment'` — `22 passed, 109 deselected`
- `tests/test_build_signal.py tests/test_model_catalog.py` — `12 passed`
- `tests/test_owner_mode.py tests/test_backend_codex.py` plus lifecycle mechanical check — `121 passed`
- `tests/test_session.py -k 'persist_coalesces or persist_survives_db_error'` — `2 passed, 221 deselected`
- `tests/test_static_js_globals.py` — `1 passed`
- direct `update_progress` contract probe — `PASS`; posts to the worker-specific progress route with percent/status payload.

Legacy DB read-only backup probe retained current historical storage: `tm_clients rows=1 columns=6`, `tm_payments rows=2 columns=6`, `tm_payment_allocations rows=3 columns=5`, `tm_sync_log rows=488 columns=11`; `app/db.py` has no diff.

## Known baseline/environment failures

The exact required full command `uv run python -m pytest -x -q` stops during collection at `app/restart_guard.py:58`: Python 3.12 in this environment has no `os.pidfd_open`. This is outside #309 and was not changed. The browser frontend group likewise has 3 failures/72 setup errors when child Python 3.12 processes import the same missing symbol. A Python 3.12 shim allowed focused tests to run.

After merging current main, the required `uv run python -m pytest -q` (without `-x`, normal `not live_probe` marker) advances past `app/restart_guard.py` but stops at the current-main-owned `tests/test_process_guard.py` import of `scripts/orchestra_process_guard.py:436`, which still binds `os.pidfd_open` at import on Python 3.12. This is not widened into #309.

The broader merge group had `47 passed, 2 failed`; both failures are pre-existing fake-signature mismatches in `tests/test_merge_stuck.py` (`expected_target_head`), outside the removed route wrapper. The MCP group had one deselected pre-existing `task_update` acceptance test; the task/removal diff does not touch that function.

## Scope and review

No credentials, service/system state, live DB, provider, model, or restart mutation was performed. No model/provider/review call was made per explicit user prohibition. `git diff --check main...HEAD` is green and the worktree is clean.

Review: skipped — explicit user prohibition; acceptance oracles, generated MCP/OpenAPI probes, focused regression outputs, DB schema probe, and diff checks are recorded above.

# #309 Phase 2 plan — remove fixed surfaces, preserve compatibility

## Scope and constraints

Phase 2 is plan-only. No `app/`, existing `tests/`, pipeline, live DB, system, service, credential, restart, model/provider, or review mutation is performed in this phase. The only new checks are immutable acceptance oracles under `docs/tasks/309/acceptance/`, committed RED before implementation.

Fixed user decisions:

- Remove all progress UI, but retain `update_progress` MCP/API/DB/session compatibility.
- Delete only the unreachable legacy `/api/sessions/{name}/merge` handler; retain middleware 426 compatibility, `execute_merge_session`, and merge-operation-v1.
- Collapse duplicate `POST /api/models/refresh` to one handler.
- Remove local proxy/tunnel mutation UI/routes/legacy owner code; retain external `ai-proxy-manager` status/link/client environment needed by the live route.
- Remove YouGile and payment/client MCP/API/UI/service code and feature tests; do not drop legacy SQLite tables, rows, columns, or rollback archive.

Current AST/import/route/DOM inventory is frozen in [plan-inventory.md](plan-inventory.md). It records the exact current consumers and the non-overlap boundary. The existing task-management client modal is runtime model/proxy status and remains; task-manager client accounting is removed with payments.

## Migration and non-goals

- `app/db.py` is not an implementation target. `tm_clients`, `tm_payments`, `tm_payment_allocations`, `tm_sync_log`, `yougile_*` columns, and historical rows remain loadable and untouched. No `DROP`, table recreation, data rewrite, or payment/YouGile migration is in these tickets.
- `update_progress`, its route, fields, hydration, persistence, serialization, and worker prompt remain. Only frontend renderers/tool-result presentation are removed.
- `app/models.py`, `/api/models`, `proxy_connected`, `app/runtime_env.py:MCP_BASE_ENV`, and external `:12339` client environment remain. No route switch, `.env` write, service restart, or proxy health call is performed by implementation tests.
- `execute_merge_session` remains because operation-v1 calls it from `app/merge_operations.py`; only the unreachable route wrapper is deleted.
- Task CRUD, status, acceptance command/oracle, worker-session linkage, and commit linking remain. Payment/debt/client and YouGile side effects/fields are no longer active surfaces, while their legacy storage remains inert.

## Tickets

### T1 — remove dashboard progress/proxy/payment/YouGile UI surfaces

- Files: `app/static/js/app.js`, `app/templates/dashboard.html`.
- Test: `docs/tasks/309/acceptance/test_t1_dashboard_surfaces_removed.py` (broad) plus `test_t1_progress_ui_removed.py` (focused); broad oracle committed RED in `a87e7504b7bff08029686048a28980b180cdea15`, focused oracle in `993e54b12fbf4327344dd456514a993c3df63243`. Exact broad command `uv run python docs/tasks/309/acceptance/test_t1_dashboard_surfaces_removed.py` → exit 1, `AssertionError: dashboard surface remains: ai-progress-label`.
- AC: named command is green; no progress DOM/JS renderer or progress tool-result presentation remains; no proxy mutation controls/routes references, payment/client-accounting renderers, or `mcp__yougile__*` UI references remain; runtime model/proxy `client-btn`/modal remains; task panel CRUD/status/acceptance/commit display remains.
- blocked-by: none

### T2 — delete unreachable legacy merge handler

- Files: `app/routes/sessions.py` only (retain `execute_merge_session`; no route snapshot edit here).
- Test: `docs/tasks/309/acceptance/test_t2_legacy_merge_handler_removed.py` — corrected oracle frozen in `5f9877addf7a6da88d89f42c047e24e88e9db100`; the original `993e54b1` T2 full-gate is superseded/excluded after its valid first-assertion RED evidence because its later literal-path assertion was a false representation premise. Corrected static command plus behavioral command: `uv run python docs/tasks/309/acceptance/test_t2_legacy_merge_handler_removed.py`; `uv run python -m pytest -q tests/test_merge_operations.py::test_legacy_http_merge_is_426_and_capability_is_visible`.
- AC: named command is green; `merge_session` decorator/function is absent; `execute_merge_session` remains importable for operation-v1; `AuthMiddleware` still returns `MERGE_OPERATION_REQUIRED`/426 for the old path; existing merge-operation, acceptance, identity-drift, and merge-stuck tests remain green.
- blocked-by: none

### T3 — collapse duplicate model-refresh registration

- Files: `app/routes/system.py` only.
- Test: `docs/tasks/309/acceptance/test_t3_single_model_refresh_route.py` — committed RED in `993e54b12fbf4327344dd456514a993c3df63243`; exact command `uv run python docs/tasks/309/acceptance/test_t3_single_model_refresh_route.py` → exit 1, `AssertionError: expected one refresh_models_endpoint, got 2`.
- AC: named command is green; generated OpenAPI has exactly one `POST /api/models/refresh` with no duplicate operation-ID warning; `_refreshModels` and `/api/models` response (`models`, `provider_metadata`, `proxy_connected`) remain green.
- blocked-by: none

### T4 — remove local proxy/tunnel mutation owner

- Files: `app/main.py`, `app/routes/proxy.py` (delete), `app/proxy_manager.py` (delete), `app/ssh_tunnel.py` (delete), `tests/test_proxy.py` (delete), `tests/test_owner_mode.py` (remove only proxy-gate test), `tests/test_restart_generation_liveness.py` (remove tunnel-start argument/call coupling), `docs/tasks/309/acceptance/test_t4_proxy_tunnel_owner_removed.py`.
- Test: `docs/tasks/309/acceptance/test_t4_proxy_tunnel_owner_removed.py` — committed RED in `993e54b12fbf4327344dd456514a993c3df63243`; exact command `uv run python docs/tasks/309/acceptance/test_t4_proxy_tunnel_owner_removed.py` → exit 1, `AssertionError: legacy proxy/tunnel file remains: app/routes/proxy.py`.
- AC: named command is green; no local proxy/tunnel mutation route or owner module remains; lifespan no longer starts/stops local SSH tunnels; `/api/models` and `proxy_connected` remain; `runtime_env.py` still propagates `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`, `INTERNAL_TOKEN`; static client-only `:12339` configuration check is green; `tests/test_backend_codex.py` proxy inheritance and auth/profile owner tests remain green; no restart/service/credential mutation occurs.
- blocked-by: none

### T5 — remove payment/client and YouGile task integrations

- Files: `app/mcp_stdio.py`, `app/routes/tm.py`, `app/tm.py`, `app/tm_yougile.py` (delete), `app/tm_import_yougile.py` (delete), `pipelines/default/prompts/modules/task-management.md`, `tests/test_tm.py` (remove feature-specific tests only), `tests/test_tm_sync_loop.py` (delete), `tests/test_reducer_role.py` (remove payment names from the forbidden surface), `docs/tasks/309/acceptance/test_t5_payment_client_surfaces_removed.py`, `docs/tasks/309/acceptance/test_t6_yougile_surfaces_removed.py`.
- Test: both named commands — committed RED in `993e54b12fbf4327344dd456514a993c3df63243`:
  - `uv run python docs/tasks/309/acceptance/test_t5_payment_client_surfaces_removed.py` → exit 1 at `assert not {"payment_receive", "payment_status"} & _function_names(ROOT / "app/mcp_stdio.py")`.
  - `uv run python docs/tasks/309/acceptance/test_t6_yougile_surfaces_removed.py` → exit 1, `AssertionError: YouGile service file remains: app/tm_yougile.py`.
- AC: both commands are green; FastMCP registry has no `payment_receive`/`payment_status`; task-manager OpenAPI has no payment or sync/retry paths; active `tm.py` has no payment/client accounting or YouGile hooks; service files and feature-specific tests are absent; task CRUD/status/acceptance/worker-session/commit linking stays green; `update_progress` calls still succeed and session fields hydrate/persist; legacy payment/YouGile tables/columns/rows load without mutation.
- blocked-by: none

### T6 — update route snapshot and shared regression tests

- Files: `tests/route_surface_snapshot.json`, `tests/test_api.py` (remove only tests that call the deleted legacy handler or payment prepayment behavior), `docs/tasks/309/acceptance/test_t7_route_snapshot_removed_surfaces.py`.
- Test: `docs/tasks/309/acceptance/test_t7_route_snapshot_removed_surfaces.py` — committed RED in `a87e7504b7bff08029686048a28980b180cdea15`; exact command `uv run python docs/tasks/309/acceptance/test_t7_route_snapshot_removed_surfaces.py` → exit 1, `AssertionError: removed route remains in snapshot: /api/sessions/{name}/merge`.
- AC: named command is green; snapshot/OpenAPI contain exactly one model-refresh route, no legacy handler, payment/YouGile sync, or proxy/tunnel mutation paths, while `/api/tm/tasks*`, `/api/sessions/{name}/progress`, `/api/merge-operations`, `/api/models`, and auth routes remain; `tests/test_routes_surface.py`, task CRUD/status/acceptance/commit-link tests, merge-operation-v1 tests, and old-DB compatibility check are green.
- blocked-by: T1, T2, T3, T4, T5

## Review gate

No model/provider review is run: the user explicitly prohibited model review/provider calls. The plan is checked mechanically against `plan-inventory.md`, immutable RED commands, generated-registry AC, route snapshot AC, and the non-overlap file list. No implementation starts until the orchestrator confirms this exact call graph and plan.

## Frozen RED oracle outputs

`uv run python docs/tasks/309/acceptance/test_t1_dashboard_surfaces_removed.py` → exit 1 — `AssertionError: dashboard surface remains: ai-progress-label`

`993e54b1` T2 full-gate evidence is superseded/excluded; its first two assertions were valid RED before `bd78f5e2`, while the later literal-path assertion was a false representation premise and is retained only as historical evidence.

Corrected T2 static oracle on `bd78f5e2` → exit 0.

Corrected T2 behavioral oracle on `bd78f5e2` → `1 passed in 2.38s`, exit 0 (Python 3.12 pidfd compatibility shim used only by the command; no repository change).

`uv run python docs/tasks/309/acceptance/test_t3_single_model_refresh_route.py` → exit 1 — `AssertionError: expected one refresh_models_endpoint, got 2`

`uv run python docs/tasks/309/acceptance/test_t4_proxy_tunnel_owner_removed.py` → exit 1 — `AssertionError: legacy proxy/tunnel file remains: app/routes/proxy.py`

`uv run python docs/tasks/309/acceptance/test_t5_payment_client_surfaces_removed.py` → exit 1 — `assert not {"payment_receive", "payment_status"} & _function_names(ROOT / "app/mcp_stdio.py")`

`uv run python docs/tasks/309/acceptance/test_t6_yougile_surfaces_removed.py` → exit 1 — `AssertionError: YouGile service file remains: app/tm_yougile.py`

`uv run python docs/tasks/309/acceptance/test_t7_route_snapshot_removed_surfaces.py` → exit 1 — `AssertionError: removed route remains in snapshot: /api/sessions/{name}/merge`

# #309 Phase 2 — current consumer inventory

This inventory is frozen against the current branch before implementation. It separates
the requested removals from shared consumers that must remain.

## Shared contracts that stay

### Progress compatibility path

`app/mcp_stdio.py:update_progress` → `_api("POST", "/api/sessions/{WORKER_NAME}/progress")` → `app/routes/sessions.py:update_progress` → `session.progress_pct`, `session.progress_status`, `session._persist()`.

Persistence/hydration consumers: `app/session.py` fields and reset path; `app/manager.py` hydration; `app/db.py` migration, insert/upsert, and session serialization. The implementation must not touch those paths. The UI-only removal scope is the `app/static/js/app.js` selected-agent block (`ai-progress*`, `session.progress_pct`) and agent-row block (`s.progress_pct`, progress bar/status), plus tool-result display branches for `mcp__orchestra__update_progress`; the MCP/API/DB/session names remain.

### Merge-operation-v1 and legacy compatibility

`app/main.py:AuthMiddleware.dispatch` handles `POST /api/sessions/{name}/merge` before routing and returns `MERGE_OPERATION_REQUIRED`/426. `app/routes/sessions.py:execute_merge_session` is not the legacy handler: `app/merge_operations.py` imports and calls it for operation-v1 execution, and many merge/acceptance/identity tests call it directly. Only `app/routes/sessions.py:merge_session` and its decorator are removed. Middleware string/path and `execute_merge_session` remain.

### Model refresh and proxy client status

`app/routes/system.py` has two identical `refresh_models_endpoint` definitions for one POST path. `app/static/js/app.js:_refreshModels` calls `/api/models/refresh`; `app/routes/system.py:list_models` and `/api/models` are retained, including `proxy_connected`, because model discovery/live external proxy status remains a client contract. `app/runtime_env.py:MCP_BASE_ENV` retains `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`, and `INTERNAL_TOKEN` propagation.

### Task CRUD/acceptance/commit linking

Keep `app/tm.py` project/task identity, create/list/get/update, status transitions, acceptance command/oracle, `worker_session_id`, `git_commits`, and commit-link functions. Keep `/api/tm/tasks*`, MCP `task_create/task_list/task_get/task_update`, prompt task lifecycle lines, and tests that cover project authority, status, acceptance, and commit linking. The existing `tm_*` payment/client/YouGile tables and legacy columns stay in `app/db.py` and are not dropped or rewritten by removal tickets.

The dashboard `client-btn`/`client-modal` is runtime model/proxy status (`/api/models`), not the task-manager client-accounting surface. It stays as the external status/client-config surface unless the orchestrator narrows this decision later.

## Removal surfaces and exact current consumers

### Progress UI

- `app/static/js/app.js:updateAgentInfo` lines 2711–2729 creates `ai-progress`, `ai-progress-label`, and reads `session.progress_pct/progress_status`.
- `app/static/js/app.js:renderAgentItem` lines 3035–3050 creates the progress bar and status text from `s.progress_pct/s.progress_status`.
- `app/static/js/app.js` tool rendering has progress-specific branches at lines 4642, 4684, 5045–5046, 5689, 6217, and 6262. Remove only presentation/formatting branches; leave the source tool call and API/session state.
- `app/templates/dashboard.html` has no static progress node; no template edit is needed.
- `pipelines/default/prompts/roles/worker.md:49` remains because the MCP contract remains.

### Legacy merge handler

- Remove only `@router.post("/api/sessions/{name}/merge")` and `merge_session` in `app/routes/sessions.py:1818–1840`.
- Keep `execute_merge_session` (`app/routes/sessions.py:1461+`) for `app/merge_operations.py:1296–1299`, acceptance gates, identity-drift, merge-stuck, merge-target, and merge-operation tests.
- Update route snapshot entry only; retain middleware compatibility test at `tests/test_merge_operations.py:675–681` and replace direct wrapper tests in `tests/test_api.py` only where they exercise the deleted handler rather than `execute_merge_session`.

### Duplicate model refresh

- Collapse the two identical `refresh_models_endpoint` definitions in `app/routes/system.py:389–400` to one.
- Keep `app/static/js/app.js:_refreshModels:7764`, `/api/models`, `models.refresh_models`, and `proxy_connected` response fields.
- Route snapshot remains one `POST /api/models/refresh`; add the AST/OpenAPI uniqueness oracle.

### Proxy/tunnel mutation owner

- `app/main.py:lifespan:349–352` imports/calls `start_tunnel`; `_shutdown_runtime:310–312` imports/calls `stop_tunnel`; remove this local tunnel lifecycle and its `_tunnel_started` retry branch while preserving model refresh and external proxy environment.
- `app/main.py:441` includes `proxy_router`; remove that include.
- `app/routes/proxy.py` owns `/api/proxy/list`, `/api/proxy/check/{proxy_id}`, `/api/proxy/set-env`, and `/api/tunnel/status`; remove this local mutation/status router per the fixed decision.
- `app/proxy_manager.py` is imported only by `app/routes/proxy.py` and `tests/test_proxy.py`; remove as legacy local owner.
- `app/ssh_tunnel.py` is imported by `app/main.py`, `app/routes/proxy.py`, and `tests/test_proxy.py`; remove as legacy local owner.
- `app/static/js/app.js:initProxy/loadProxyList/_showProxyRestartBanner:8408–8564` plus proxy selectors in `app/templates/dashboard.html:40–57` are the mutation UI; remove them. Keep `/api/models`/`proxy_connected` and `runtime_env.py` client environment.
- Remove `tests/test_proxy.py` as feature-specific. Remove only `test_proxy_gate_blocks_client_and_passes_owner` from `tests/test_owner_mode.py`; retain the owner/auth/profile tests. Update `tests/test_restart_generation_liveness.py` callers of `_shutdown_runtime(..., tunnel_started=False)` and the route snapshot.

### Payment/client accounting

- MCP: remove `payment_receive`/`payment_status` definitions and `payment_status` read-only classification in `app/mcp_stdio.py`.
- HTTP: remove `TmPaymentReceive`, `_resolve_client_id`, `/api/tm/payments`, `/api/tm/payments/status`, `/api/tm/payments/history` from `app/routes/tm.py`. Task routes stay.
- Service: remove active payment/client functions and prepayment/journal glue from `app/tm.py` (`ensure_client/get_client_for_project`, `receive_payment`, `_distribute_payment`, `auto_deduct_prepayment`, `get_payment_status`, `api_receive_payment`, `api_payment_status`, `_fire_journal_sync` and callers). Preserve task CRUD/status/acceptance/commit-link code and legacy DB tables/columns in `app/db.py`.
- UI: remove payment-specific tool previews/renderers, payment fields/debt/payment-history rows, `/api/tm/payments/status` fetch, and task-panel payment refresh wiring in `app/static/js/app.js`; runtime model/client modal remains.
- Prompt: remove payment tool lines from `pipelines/default/prompts/modules/task-management.md` but retain task CRUD/status/acceptance/commit-link workflow.
- Tests: remove payment-specific tests from `tests/test_tm.py` (`test_status_prepayment_uses_resolved_task_db_id`, `test_direct_payment_stays_in_client_project_with_duplicate_par`), `tests/test_api.py` (`test_status_prepayment_uses_explicit_project_not_scope`), and payment names from `tests/test_reducer_role.py`. Keep task CRUD/status/acceptance/commit-link tests. No `tm_*` table/row deletion.

### YouGile integration

- Delete service files `app/tm_yougile.py` and `app/tm_import_yougile.py`.
- Remove `main.py` lifespan import that registers YouGile hooks, `app/routes/tm.py` import plus `/api/tm/sync/log` and `/api/tm/sync/retry/{sync_id}`, and `app/tm.py` YouGile hooks (`_is_yougile_enabled`, `set_main_loop/_MAIN_LOOP` if only sync glue remains, `_schedule/_fire_async/_fire_sync`, `on_task_synced`, `log_sync` callers, and `on_payment_changed` journal hook). Keep legacy `tm_sync_log`, `yougile_*` columns, and tables inert in `app/db.py`.
- Remove `mcp__yougile__*` and `yougile_id/yougile_task_id` display branches from `app/static/js/app.js`; task CRUD/status/acceptance/commit link stays.
- Prompt task-management has no YouGile line today; no prompt deletion beyond payment lines.
- Remove `tests/test_tm.py:test_yougile_import_uses_resolved_project_id`; remove YouGile-specific fixtures/assertions and route-surface entries. Keep generic task tests that only use legacy columns to prove old DB loading.
- Remove `tests/test_tm_sync_loop.py` as a feature-specific test of the YouGile fire-and-forget loop; its `_MAIN_LOOP`, `_schedule`, and `set_main_loop` symbols have no remaining consumer after sync hooks are removed.

## Cross-ticket safety invariants

- Never modify/drop `tm_clients`, `tm_payments`, `tm_payment_allocations`, `tm_sync_log`, or YouGile/payment columns in `app/db.py`.
- Never remove `update_progress` from MCP registry, route, session model, persistence, hydration, or prompt.
- Never remove `/api/merge-operations`, `execute_merge_session`, middleware 426 compatibility, or merge recovery state.
- Never remove `/api/models` or `proxy_connected`; external `ai-proxy-manager` remains the route owner and `MCP_BASE_ENV` remains client-only.
- Never remove task CRUD/status/acceptance/worker-session/commit-link behavior while deleting payment/YouGile side effects.

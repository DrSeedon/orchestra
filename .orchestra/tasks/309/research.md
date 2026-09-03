# #309 — Orchestra feature-usage audit (research-only)

## Question and measurement frame

**Context:** Orchestra exposes 41 FastMCP tools, 99 generated OpenAPI paths (103 unique Starlette paths including framework docs), a Jinja/JavaScript dashboard, SQLite-backed sessions/logs/jobs/tasks/payments, runtime handoff/recovery, quota and proxy controls, and Telegram/artifact integrations.

**Change under test:** identify surfaces rare or confusing enough to delete, hide, merge, or replace while retaining rare critical recovery/safety paths. The named first candidate is the worker progress MCP tool plus frontend progress bar. Automatic task tickets/stages are only a future alternative, not an assumed replacement.

**Baseline:** current registered MCP/OpenAPI/UI/subsystem surfaces and their current code consumers. YouGile and payments are pre-decided removable under #299; this audit labels them pre-decided and does not re-litigate or delete them.

**Measurable outcome:** for each feature, exact 30/60/90-day call counts by `logs.ts`, unique sessions/agents/scopes, orchestrator/worker split, runtime and joinable success/error/unknown results; generated route/UI inventory with explicit telemetry gaps; static AST/import/call-graph liveness; schema/prompt/code/test/table footprint; and a conservative decision matrix with a mechanical deletion oracle.

The platform-level `create_goal`/`get_goal`/`update_goal` controls are orchestration metadata tools, not registered in Orchestra's `app/mcp_stdio.py` catalog, FastAPI routes, dashboard controls, or SQLite feature tables; they are recorded as out-of-scope platform surfaces rather than deletion candidates.

The live DB was opened read-only and copied with `sqlite3.Connection.backup()` into memory. The frozen completed-event cutoff is `2026-08-24T06:12:06.860886+00:00`; windows are 30/60/90 days from that timestamp. The raw sanitized facts and generator are under `docs/tasks/309/evidence/`.

## Hypotheses considered and falsifiers

| Hypothesis | Falsifier | Result |
|---|---|---|
| H1 — `update_progress` is low-value cosmetic UI: five worker calls, no user click telemetry, and no critical recovery role → hiding only its frontend reduces confusion at low blast radius. | A user-visible interaction metric or a production/recovery caller depends on the bar itself; or hiding it breaks an active worker/API contract. | Supported, not proven: 5 successful worker-side calls; UI observation is unmeasured; API is live-only and has stale-identity history. |
| H2 — zero/rare MCP tools are safe to delete when the 90-day count is zero. | A zero-count tool is an auth, recovery, delivery, data-integrity, dynamic registry, or compatibility path, or its telemetry is incomplete. | Refuted as a general rule: `compact_worker`, delivery retry/status, merge resolve, test lock, artifact publication, handoff, quota, and fan paths are rare/zero in named logs but are safety/recovery consumers. |
| H3 — route/UI surfaces with no observed counts are unused. | The system lacks persisted path/click telemetry, or static/generated consumers exist. | Refuted: route requests and dashboard events are not persisted by path/control; all such rows are `UNMEASURED`, not zero. |
| H4 — replacing progress with automatic tickets/stages is the right cleanup. | Existing task storage is already active, but no requirements, migration, or user-observation measurement establish equivalence; active sessions still call the current API. | Not established. Tickets/stages remain a future Class-C alternative only. |

## Evidence and findings

### F1 — registry and telemetry boundary are confirmed

1. The imported FastMCP registry contains exactly 41 tools; `backend_codex.py:_orchestra_full_mcp_tools()` derives the Codex allowlist from that registry with an empty exclusion set. **CONFIRMED — generated registry + source code.** Evidence: `evidence/mcp-usage.csv`, `evidence/inventory.json`, `app/backend_codex.py:736-752`.
2. Generated OpenAPI has 99 paths; the static inventory has 103 unique paths including `/docs`, `/redoc`, `/openapi.json`, and `/uploads`. **CONFIRMED — generated OpenAPI/Starlette registry.** Evidence: `evidence/cutoff-and-db.json`, `evidence/route-inventory.csv`.
3. SQLite stores `logs.type='tool'` and `logs.type='tool_result'`, but no persisted HTTP method/path census or dashboard click/event census. **CONFIRMED — schema inspection and inventory generation.** Evidence: `evidence/cutoff-and-db.json`, `evidence/route-inventory.csv`, `evidence/ui-inventory.csv`.
4. Named MCP telemetry starts on 2026-08-13; earlier tool rows contain NULL or wrapper names such as `Bash`, `Read`, and `Edit`, so they cannot be safely mapped to distinct MCP semantics. **CONFIRMED — direct DB distribution.** Evidence: `evidence/mcp-usage.csv` observation-gap column and `evidence/cutoff-and-db.json`.
5. Equal-session `tool_use_id` pairing is a lower-bound result oracle; unpaired calls are `unknown`, not successful. **CONFIRMED — direct join implementation in generator.** Evidence: `evidence/mcp-usage.csv`, `evidence/progress-detail.csv`.

### F2 — measured usage does not support broad deletion

1. Highest measured MCP usage is `send_message` 299, `search_memory` 164, `list_agents` 131, `worker_wip` 121, `bg_create` 117, `merge_worker` 89, `spawn_worker` 90, `codex_review` 78, `task_get` 28, `bg_list` 19, `get_worker_logs` 16, and `open_fan` 7 in the frozen 90-day named window. **CONFIRMED — direct measurement.** Evidence: `evidence/mcp-usage.csv`.
2. `update_progress` has exactly five named calls, all successful and worker-side: three distinct agent names, two scopes, two runtimes, zero orchestrator calls, zero errors, zero unknown paired outcomes. **CONFIRMED — direct measurement.** Evidence: `evidence/progress-detail.csv`.
3. Zero named calls were observed for several tools, but zero is not a deletion verdict when telemetry is incomplete or a critical caller exists. **CONFIRMED policy application — measured counts plus static call graph/tests.** Evidence: `evidence/decision-matrix.csv`, `evidence/static-callgraph.json`, `evidence/feature-footprint.csv`.
4. DB rows show active `bg_jobs` (128), `merge_operations` (196), `initial_deliveries` (34), `subagents` (4,429), `turn_usage` (4,305), `usage_snapshots` (12,066), and `tm_tasks` (611) at the frozen backup. **CONFIRMED — direct backup measurement.** Evidence: `evidence/db-footprint.csv`.

### F3 — progress is a live compatibility contract, while its UI is unmeasured

1. `update_progress` calls `/api/sessions/{WORKER_NAME}/progress`; the route clamps the percentage, persists `progress_pct`/`progress_status`, and intentionally keeps detached sessions at 404. **CONFIRMED — source code.** Evidence: `app/mcp_stdio.py:1505-1514`, `app/routes/sessions.py:1794-1807`.
2. Progress state is present in the session object, DB migration/upsert, manager hydration, turn reset, and both session serialization paths. **CONFIRMED — source code call graph.** Evidence: `app/session.py:426-427,1144-1145,4572-4573,4623-4624`, `app/manager.py:1383-1384`, `app/db.py:614-616,972-1010`, `evidence/static-callgraph.json`.
3. The frontend renders progress in selected-agent details and agent-row bars/status lines, with no progress click listener. **CONFIRMED — source code.** Evidence: `app/static/js/app.js:2711-2729,3035-3050`, `evidence/ui-inventory.csv`.
4. User observation of the progress UI is not measurable from the current DB. **CONFIRMED — missing telemetry.** Evidence: `evidence/ui-inventory.csv`.
5. A prior rename audit measured stale `WORKER_NAME` causing `POST /api/sessions/ghost/progress` → 404; the subsequent #82 repair moved identity to immutable session IDs/refresh. **CONFIRMED historical counter-evidence.** Evidence: `docs/tasks/82/research.md` F2/F3 and `docs/tasks/82/report.md`.
6. A later Telegram audit characterized progress as cosmetic rendering. **LIKELY — local report evidence, not a user-observation metric.** Evidence: `docs/tasks/189/report.md`.

### F4 — confirmed deletion/merge candidates are narrow

1. The legacy `POST /api/sessions/{name}/merge` route is intercepted in `app/main.py` middleware and returns typed 426 directing callers to merge-operation-v1 before the old endpoint body executes. **CONFIRMED — source code plus generated route registry.** Verdict: DELETE candidate after v1 negative oracle.
2. `POST /api/models/refresh` is defined twice identically in `app/routes/system.py`; OpenAPI generation emits a duplicate operation-ID warning. **CONFIRMED — source code + generator warning.** Verdict: MERGE the duplicate registration, retain one handler.
3. Proxy/tunnel controls are confusingly coupled to an external route owner: repository instructions identify `ai-proxy-manager` as the owner, while the dashboard exposes list/check/set-env/restart controls. **CONFIRMED ownership mismatch from project instruction + source inventory; usage UNCERTAIN.** Verdict: HIDE or reduce to status/link-only only after live health controls.
4. YouGile and payments are removable by explicit #299 decision. **PRE-DECIDED — do not re-litigate.** Evidence: user instruction and `docs/tasks/299/research.md`; verdict rows are labeled `PRE-DECIDED (#299)` in `evidence/decision-matrix.csv`.

## Counter-evidence and safety exclusions

- A zero named count can mean a newly introduced field, an old wrapper name, an uninstrumented direct caller, or a recovery path waiting for an incident. It cannot mean unused without complete telemetry.
- Progress has only five calls, but deleting its API/fields would break current workers that still call it and would require active-session migration. Therefore the safe current action is UI HIDE, not DELETE.
- `artifacts` has zero DB rows at the cutoff, but publish/revoke/redeem/content routes and tests form a delivery/recovery contract. Keep until a delivery oracle proves it is not needed.
- Runtime handoff tables are empty at this cutoff, but handoff code and recovery tests are safety surfaces. Keep; absence of recent rows is not evidence of irrelevance.
- `test_lock`, `resolve_merge_operation`, `retry_initial_delivery`, `delivery_status`, `compact_worker`, and `send_file` are rare or zero in named MCP logs but protect tests, merge recovery, delivery recovery, compaction, or fallback delivery. Keep despite count.
- Route and UI rows cannot be scored as zero because HTTP/click telemetry is absent. Any future DELETE candidate must first add observation instrumentation.

## Decision matrix and preregistered thresholds

The preregistered thresholds are: DELETE only when 0 uses in 90 days + complete telemetry + no live/import/dynamic/critical caller + a mechanical removal oracle; HIDE/DEPRECATE for fewer than 3 uses/90 days when compatibility may matter; KEEP for critical auth/recovery/data-integrity mechanisms; MERGE for duplicate representations of one state. Thresholds are candidate gates, not verdicts.

`evidence/decision-matrix.csv` applies the exact required columns to every registered MCP tool and decision-level route/UI/integration row:

`feature | usage evidence | critical negative control/recovery role | current consumers | prompt/tool/UI footprint | maintenance/confusion evidence | deletion blast radius | replacement | verdict KEEP/HIDE/MERGE/DEPRECATE/DELETE | confidence | deletion oracle`

## Candidates and smallest safe experiment

Concrete candidates (research only; no deletion performed):

1. **Progress frontend — HIDE, LIKELY.** Five worker-side calls; no UI click metric; API remains a live compatibility path. Experiment: hide only the two progress renderers behind a reversible UI flag, then observe next worker calls and user-visible regressions.
2. **Legacy merge route — DELETE after gate, CONFIRMED.** Middleware already rejects it with 426; replacement is merge-operation-v1. Experiment: add a negative route/OpenAPI oracle and replay v1 recovery cases before removing code.
3. **Duplicate model refresh registration — MERGE, CONFIRMED.** Two identical handlers; retain one and assert unique operation ID.
4. **Proxy/tunnel dashboard controls — HIDE/reduce, UNCERTAIN.** No click telemetry and external proxy-manager ownership; preserve health/status and test route safety before hiding mutation controls.
5. **YouGile and payments — DELETE, PRE-DECIDED (#299).** Label only; migration is outside #309.

The smallest safe progress experiment has negative controls for (a) active worker `update_progress` at 0/50/100 → success, (b) detached worker → intentional 404, (c) unchanged session hydration/list output, (d) no visible progress DOM after the UI-only hide, and (e) no unrelated chat/agent-status regression. Automatic tickets/stages are not part of this experiment.

## Affected files, risks, and future Class-C tickets

Affected progress files are `app/mcp_stdio.py`, `app/routes/sessions.py`, `app/session.py`, `app/manager.py`, `app/db.py`, `app/static/js/app.js`, `app/templates/dashboard.html`, and `pipelines/default/prompts/roles/worker.md`. Affected candidate surfaces also include `app/main.py`, `app/routes/system.py`, `app/routes/proxy.py`, `app/proxy_manager.py`, `app/ssh_tunnel.py`, `app/merge_operations.py`, `app/routes/merge_operations.py`, `app/tm.py`, and `app/tm_yougile.py`.

Risks: breaking active worker calls; deleting recovery paths based on an empty incident window; stale route/UI telemetry; dynamic registry/catalog callers; duplicate task/payment/YouGile state; proxy ownership mismatch; old sessions resuming with missing columns; and confusing a tool schema's prompt/catalog cost with call cost. The footprint evidence keeps these dimensions separate.

Future Class-C tickets only:

- **C1:** instrument HTTP path/method census and privacy-safe dashboard click/event counters.
- **C2:** run the reversible progress UI-hide experiment with active-session negative controls.
- **C3:** remove legacy merge route after v1 OpenAPI/recovery oracle.
- **C4:** merge duplicate model-refresh registration and assert unique OpenAPI operation ID.
- **C5:** execute already-decided #299 YouGile/payments migration; no new decision here.
- **C6:** audit proxy/tunnel UI ownership and replace mutation controls with status/link-only controls after live health validation.

## Sources and review constraint

No external URLs were needed: the question is answered by local primary source code, generated registries, and a WAL-safe DB measurement. Sources opened this session: `app/mcp_stdio.py`, `app/backend_codex.py`, `app/main.py`, `app/routes/sessions.py`, `app/routes/system.py`, `app/session.py`, `app/manager.py`, `app/db.py`, `app/static/js/app.js`, `pipelines/default/prompts/roles/worker.md`, `docs/tasks/82/research.md`, `docs/tasks/82/report.md`, `docs/tasks/189/report.md`, `docs/tasks/299/research.md`, and the generated evidence files under `docs/tasks/309/evidence/`.

The user explicitly prohibited model/provider/eval/review calls. No external review call was made; conclusions are traceable to the generated artifacts and local source/measurement evidence.

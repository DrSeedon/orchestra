# #309 feature-usage audit — measurements

## Measurement contract

The source was `/mnt/data/Projects/Python/orchestra/data/orchestra.db`, opened read-only and copied with `sqlite3.Connection.backup()` into `:memory:`. The frozen cutoff is the exact maximum completed timestamp in that backup: `2026-08-24T06:12:06.860886+00:00` (see `evidence/cutoff-and-db.json`). Windows are `[2026-07-25T06:12:06.860886+00:00, cutoff]`, `[2026-06-25T06:12:06.860886+00:00, cutoff]`, and `[2026-05-26T06:12:06.860886+00:00, cutoff]`.

`logs.type='tool'` is the call denominator. Autoincrement `logs.id` was not used. Exact MCP names are normalized only by removing the `mcp__orchestra__` prefix; `Bash`, `Read`, `Edit`, `mcp__websearch__*`, NULL historical names, and arbitrary wrapper names remain distinct/unknown. Equal-session `tool_use_id` joins to `tool_result` provide lower-bound success/error coverage. At the backup: 158,775 logs, 43,915 tool rows, 43,321 result rows, 11,400 joinable tool calls, and 11,064 joinable tool results. These are frozen facts from `cutoff-and-db.json`.

Raw sanitized outputs:

- `evidence/mcp-usage.csv` — all 41 registered MCP tools, 30/60/90-day calls, sessions, agents, scopes, orchestrator/worker split, runtime, result state, last use, schema bytes, telemetry gap.
- `evidence/route-inventory.csv` — generated Starlette/OpenAPI route inventory; route calls are explicitly `UNMEASURED`.
- `evidence/ui-inventory.csv` — dashboard controls and literal JS endpoint references; clicks are explicitly `UNMEASURED`.
- `evidence/inventory.json` — joined MCP/OpenAPI/UI/subsystem inventory.
- `evidence/feature-footprint.csv` — MCP function LOC, prompt-anchor proxy, frontend literal refs, test files, schema bytes.
- `evidence/db-footprint.csv` — table/column/row footprint from the same backup.
- `evidence/progress-detail.csv` — every observed `update_progress` call with timestamp, agent, scope, runtime, percent, sanitized status hash/length, and paired result.
- `evidence/static-callgraph.json` — AST definitions, parsed call sites, and imports for registered tools and named subsystem symbols.
- `evidence/decision-matrix.csv` — exact required decision columns for every MCP tool plus decision-level route/UI/integration rows.

The generator is `evidence/measure_309.py`; it has no write path to the database. OpenAPI generation exposed 99 paths; the Starlette inventory has 103 unique paths including framework docs. The generation emitted duplicate operation-ID warnings for the two identical `POST /api/models/refresh` definitions and the artifact open route; this is maintenance evidence, not a usage count.

## Usage shape

The active named MCP catalog is not empty or uniformly cold. Highest measured 90-day calls are `send_message` (299), `search_memory` (164), `list_agents` (131), `worker_wip` (121), `bg_create` (117), `merge_worker` (89), `spawn_worker` (90), `codex_review` (78), `bg_list` (19), `get_worker_logs` (16), `open_fan` (7), and `task_get` (28). Full values for all 41 tools are in `mcp-usage.csv`; tool schema bytes are separate from call counts (`send_chart` has 2,134 schema bytes and zero named calls; `update_progress` has 328 schema bytes and five calls).

The zero/rare named-call set includes `acquire_test_lock`, `compact_worker`, `payment_receive`, `payment_status`, `publish_artifact`, `release_test_lock`, `rename_worker`, `resolve_merge_operation`, `retry_initial_delivery`, `send_chart`, and `test_lock_status`. These are not one verdict: several are recovery/safety mechanisms covered by tests and must remain; payment tools are pre-decided removable under #299; the zero named-call conclusion is `UNKNOWN` wherever the historical wrapper/NULL telemetry gap prevents the preregistered DELETE test.

The DB footprint confirms that low call count does not imply low subsystem activity:

| Surface | Measured footprint | Interpretation |
|---|---:|---|
| `sessions` | 479 rows, 52 columns | active lifecycle state; retain |
| `logs` | 158,775 rows at frozen backup | primary evidence source |
| `bg_jobs` | 128 rows | background jobs are live, not a deletion candidate |
| `merge_operations` | 196 rows | merge recovery/state machine is live |
| `initial_deliveries` | 34 rows | delivery recovery path exists even when retry tool calls are rare |
| `subagents` | 4,429 rows | subagent visibility is live |
| `turn_usage` | 4,302 rows | usage accounting is live |
| `usage_snapshots` | 12,066 rows | quota/usage surfaces are live |
| `tm_tasks` | 611 rows | task store is live |
| `tm_payments` / allocations | 2 / 3 rows | payment accounting is small and pre-decided removable under #299 |
| `tm_sync_log` | 488 rows | YouGile/task sync history exists; removable by #299 decision, not by this audit |
| `artifacts` | 0 rows | absence is not enough to delete the publication/recovery contract; test and delivery callers remain |
| runtime handoff tables | 0 current rows | rare recovery path; keep until a handoff-specific oracle proves safe removal |

Exact, non-abbreviated row counts are in `evidence/db-footprint.csv`.

## Route groups and dashboard controls

The generated route groups are: `/api/sessions` (28 paths), `/api/models` (5), `/api/artifacts` (5), `/api/merge-operations` (4), `/api/proxy` (3), `/api/orchestrators` (3), `/api/test-lock` (3), `/api/files` (3), `/api/tm` (7), `/api/usage` (7), `/api/bg` (2), `/api/memory` (2), `/api/tg` (2), plus single-purpose groups for logs, blobs, deliveries, fan, projects, pipelines, profiles, stats, subagents, reporting, restart, upload/transcribe, tunnel, webhook, and role-icons. See `inventory.json` for exact path/method/owner mappings.

Platform-level goal controls (`create_goal`, `get_goal`, `update_goal`) are not Orchestra MCP registrations, FastAPI routes, dashboard controls, or SQLite feature tables; they are outside this app-surface deletion audit.

No persisted request-census row contains HTTP method/path, so every route count is `UNMEASURED`; an API path appearing in a tool payload is not treated as a request count. The dashboard has 105 statically discoverable controls/references (buttons, inputs, anchors, and JS endpoint literals); no click/event telemetry is persisted. Therefore a route/UI row with no observed use is `UNKNOWN`, never `UNUSED`.

Static import/AST evidence matters for the safety decision. `backend_codex.py:_orchestra_full_mcp_tools()` builds Codex's allowlist from the authoritative FastMCP registry and currently has no exclusions. `app/main.py` middleware explicitly rejects the legacy merge route with typed 426 and directs callers to merge-operation-v1. `app/routes/system.py` currently defines the same `POST /api/models/refresh` handler twice; generated OpenAPI warns about the duplicate operation ID.

## Progress deep dive

### Observed mechanism

- MCP `update_progress` is registered in `app/mcp_stdio.py:1505-1514`, sends `POST /api/sessions/{WORKER_NAME}/progress`, and returns the API result.
- The API is `app/routes/sessions.py:1794-1807`; it clamps `percent`, stores `session.progress_pct` and `session.progress_status`, and persists them only for a live session. A detached session is still a 404 by design.
- State is represented in `app/session.py:426-427`, loaded by `app/manager.py:1383-1384`, added/migrated by `app/db.py:614-616`, written/upserted by `app/db.py:972-1010`, reset on turn boundary by `app/session.py:1144-1145`, and serialized in `app/session.py:4572-4573` and `4623-4624`.
- The role prompt tells workers to call it at natural checkpoints (`pipelines/default/prompts/roles/worker.md:49`).
- The frontend renders text in selected-agent metadata (`app/static/js/app.js:2711-2729`) and a small bar/status line in agent rows (`app/static/js/app.js:3035-3050`). There is no click handler for either progress element.

### Exact calls

`evidence/progress-detail.csv` contains all five named calls in the frozen 90-day window:

| UTC | agent | scope | runtime | percent | paired result |
|---|---|---|---|---:|---|
| 2026-08-20 08:40 | `fix-dashboard-resilience` | Orchestra | Claude | 15 | success |
| 2026-08-20 09:19 | `fix-dashboard-resilience` | Orchestra | Claude | 75 | success |
| 2026-08-23 13:51 | `runtime-license-slice` | comfy-image-pipeline | Codex | 50 | success |
| 2026-08-23 13:57 | `identity-adapters-slice` | comfy-image-pipeline | Codex | 75 | success |
| 2026-08-23 14:22 | `identity-adapters-slice` | comfy-image-pipeline | Codex | 100 | success |

Thus: 5 calls, 3 distinct agent names, 2 scopes, 2 runtimes, 0 orchestrator calls, 5 worker calls, 5 successful paired results, 0 errors, 0 unknown. This is worker progress reporting, not evidence that a user clicked or saw the frontend bar. UI observation remains `UNMEASURED`.

### Footprint and confusion/failure evidence

The MCP schema is 328 bytes, the function is eight source lines, the API route is 13 source lines including the live-only guard, and the frontend has two independent renderers plus tool-result formatting branches. The two DB fields are part of the 52-column `sessions` row. `feature-footprint.csv` reports the measured structural counts and test files.

The prior rename audit measured a real failure mode: a stale `WORKER_NAME` made `POST /api/sessions/ghost/progress` return 404 (`docs/tasks/82/research.md` F2/F3; `docs/tasks/82/report.md` live evidence). That failure was subsequently repaired through immutable session identity and MCP refresh, so it is counter-evidence against deleting the API, not a current progress defect. A later Telegram audit describes progress as cosmetic status rendering (`docs/tasks/189/report.md`), which supports hiding the UI while retaining the API but does not prove a user never observes it.

### Four options

1. **Keep:** preserves all five callers and the current API/UI, but retains two UI renderers and a low-use manual percentage contract.
2. **Hide UI, retain API:** smallest safe experiment and current recommendation. Remove/hide only the selected-agent progress text/bar behind a reversible UI flag; retain MCP, route, fields, serialization, and active-session semantics. This tests whether the dashboard control is confusing without breaking workers.
3. **Remove both:** not currently justified. It would require a migration for active sessions, prompt/catalog removal, route and schema compatibility handling, and an oracle proving no running worker can still call the API or rely on progress fields.
4. **Replace with automatic task tickets/stages:** future alternative, not assumed solution. It needs a separate Class-C design/measurement ticket; it cannot be used as a reason to delete the existing path now.

### Recommendation

`HIDE` the frontend progress bar/text as a reversible experiment; retain the MCP/API/database contract until complete route/UI telemetry and active-session negative controls exist. Confidence is `LIKELY` for UI hiding and `UNCERTAIN` for any claim that the feature is unused. The required deletion oracle for eventual removal is: (a) active-session worker calling `update_progress` fails the test if the API is absent, (b) `/api/sessions` and session hydration have no progress fields after an explicit migration, (c) generated MCP/OpenAPI registries contain no progress surface, (d) old workers/sessions resume without error, and (e) the frontend has no progress selectors/renderers.

## Preregistered thresholds and decision matrix

Thresholds were fixed before interpreting rows: DELETE requires 0 use in 90 days **and** complete telemetry **and** no live/import/dynamic/critical caller **and** a mechanical removal oracle. HIDE/DEPRECATE is for fewer than 3 uses in 90 days when compatibility may matter. KEEP overrides count for critical auth/recovery/data-integrity paths. MERGE applies when two surfaces represent the same state. These are candidate thresholds, not verdicts.

The full matrix is `evidence/decision-matrix.csv` with the exact columns requested:

`feature | usage evidence | critical negative control/recovery role | current consumers | prompt/tool/UI footprint | maintenance/confusion evidence | deletion blast radius | replacement | verdict KEEP/HIDE/MERGE/DEPRECATE/DELETE | confidence | deletion oracle`

Decision-level conclusions from that matrix:

- **DELETE candidate (confirmed):** legacy `POST /api/sessions/{name}/merge` is rejected in middleware with typed 426 before its old implementation; merge-operation-v1 is the replacement. Delete only after the route/OpenAPI negative oracle and v1 recovery tests are in place.
- **MERGE candidate (confirmed):** duplicate `POST /api/models/refresh` definitions are identical; retain one handler and require a unique OpenAPI operation ID.
- **HIDE candidate (likely):** progress UI, with API retained as above.
- **HIDE candidate (uncertain):** proxy/tunnel dashboard controls because the external `ai-proxy-manager` is the route owner and the UI still offers `.env`/restart controls; runtime proxy health and safety must be tested before hiding.
- **DELETE candidates (pre-decided, not re-litigated):** YouGile integration and payments under #299. This audit records their rows and DB footprint but does not implement or newly justify deletion.
- **KEEP despite zero/rare observations:** test lock, compact, initial-delivery status/retry, merge-operation resolve, artifact publication, handoff, quota admission, fan barrier, auth, and worker lifecycle. Their count is not a sufficient deletion argument.

## Smallest safe experiment and future Class-C tickets

The smallest safe experiment is a reversible UI-only hide of progress selectors/renderers while preserving the API/MCP fields and logging the next observed worker calls. It must not mutate production state in this research phase. Negative controls: an active worker calls `update_progress` at 0/50/100 and receives success; a detached worker still receives the intentional 404; session list/hydration remains unchanged; no progress element is visible in the browser; and no unrelated chat/agent status rendering changes.

Future Class-C tickets only:

- **C1:** add persisted HTTP route census by method/path and explicit UI click/event telemetry with privacy-safe aggregation.
- **C2:** run the reversible progress UI hide experiment and collect active-session/user-visible negative controls.
- **C3:** remove legacy merge route after v1 OpenAPI and recovery oracle passes.
- **C4:** merge duplicate model-refresh registration and lock a unique operation-ID oracle.
- **C5:** execute the already-decided #299 YouGile/payments migration; no design decision is made here.
- **C6:** audit proxy/tunnel UI ownership and replace mutation controls with status/link-only controls only after live proxy health checks.

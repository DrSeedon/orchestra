# feature-usage-audit

## Установлено

- The frozen #309 backup at cutoff `2026-08-24T06:12:06.860886+00:00` contained 41 generated MCP tools, 99 OpenAPI paths, 103 unique Starlette paths including framework docs, and 105 static dashboard controls/references · `.orchestra/tasks/309/evidence/cutoff-and-db.json` · 2026-08-24, #309
- MCP tool usage must normalize only the `mcp__orchestra__` prefix; NULL historical names and wrappers (`Bash`, `Read`, `Edit`) are not safely mergeable into distinct MCP semantics · `.orchestra/tasks/309/evidence/mcp-usage.csv`, `static-callgraph.json` · 2026-08-24, #309
- HTTP route request counts and dashboard click/event counts are not persisted by path/control in the current SQLite logs; rows with no observed count are UNKNOWN, not UNUSED · `.orchestra/tasks/309/evidence/route-inventory.csv`, `ui-inventory.csv` · 2026-08-24, #309
- `update_progress` had 5 named calls in the frozen 90-day window, all successful worker-side calls across 3 agent names, 2 scopes, 2 runtimes, and 0 orchestrator calls; frontend observation is unmeasured · `.orchestra/tasks/309/evidence/progress-detail.csv`, `research.md` F3 · 2026-08-24, #309
- Progress is a live compatibility path: MCP → `/api/sessions/{name}/progress` → `sessions.progress_pct/progress_status`; detached sessions intentionally return 404, and frontend has two renderers without click listeners · `app/mcp_stdio.py:1505-1514`, `app/routes/sessions.py:1794-1807`, `app/static/js/app.js:2711-2729,3035-3050` · 2026-08-24, #309
- The safest current progress action is HIDE frontend UI while retaining API/MCP/DB fields; automatic task tickets/stages are a future alternative only · `.orchestra/tasks/309/metrics.md`, `decision-matrix.csv` · 2026-08-24, #309
- The legacy merge route is intercepted with typed 426 before its endpoint body and directs callers to merge-operation-v1; it is a confirmed future DELETE candidate with a route/OpenAPI negative oracle · `app/main.py:430-452`, `.orchestra/tasks/309/evidence/decision-matrix.csv` · 2026-08-24, #309
- Duplicate `POST /api/models/refresh` definitions emit an OpenAPI duplicate operation-ID warning and are a confirmed MERGE candidate; retain one handler · `app/routes/system.py:388-400`, generator stderr in `evidence/measure_309.py` run · 2026-08-24, #309
- YouGile and payments are pre-decided removable under #299 and are recorded as such without a new deletion argument or implementation · user task instruction, `.orchestra/tasks/299/research.md`, `decision-matrix.csv` · 2026-08-24, #309

## Отвергнуто

- Zero named MCP calls imply safe deletion · incomplete wrapper/NULL telemetry and rare recovery/safety callers refute count-only deletion · 2026-08-24, #309
- A route/UI row with no count is unused · request/click telemetry is absent, so the observation state is UNKNOWN · 2026-08-24, #309
- The progress bar can be deleted together with its API immediately · five current worker calls plus session persistence/active-session compatibility make UI-only hiding the smaller safe experiment · 2026-08-24, #309

## Пробелы

- Exact historical MCP semantics before named `tool_name` telemetry began 2026-08-13 remain unresolved · wrapper payloads are intentionally not merged without a semantic parser · 2026-08-24, #309
- HTTP route and dashboard click usage is unmeasured · add privacy-safe request/event census in future Class-C work · 2026-08-24, #309
- Whether a human actually observes progress UI is unmeasured · run the reversible UI-hide experiment with active-session and browser negative controls · 2026-08-24, #309
- Whether automatic task tickets/stages outperform or safely replace manual progress is unmeasured · requires a separate design/measurement ticket, not an assumption in #309 · 2026-08-24, #309

## Источники

- `.orchestra/tasks/309/research.md` — full hypotheses, findings, counter-evidence, candidate decisions, and future Class-C tickets.
- `.orchestra/tasks/309/metrics.md` — measurement contract, progress deep dive, footprint, thresholds, and experiment.
- `.orchestra/tasks/309/evidence/` — sanitized generated registries, usage counts, DB footprint, progress rows, AST graph, and decision matrix.

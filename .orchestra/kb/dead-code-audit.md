# dead-code-audit

## Established

- Current `main` at `1c5bf6db` has 40 `@mcp.tool()` functions, 100 FastAPI route decorators, and zero duplicate `(verb,path)` keys in the source registries; `POST /api/models/refresh` is one definition and the catalog refresh route is distinct · `.orchestra/tasks/332/evidence/registry-summary.txt` · 2026-08-24, #332
- Serena `1.7.1.dev0` Python LSP was ready, but returned zero references for decorator/registry/tombstone symbols (`update_progress`, `refresh_models_endpoint`, `cleanup_old_logs`, `fan_id_for_reducer`); zero Serena refs are candidate generation only, not deletion proof · `.orchestra/tasks/332/evidence/serena.txt` · 2026-08-24, #332
- `app/static/js/app.js:1646-1657` `deleteOrchestrator` has one token occurrence (declaration only); the live deletion path is `initTabContextMenu → openDeleteOrchModal` and remains wired through the dashboard modal · `.orchestra/tasks/332/evidence/js-summary.txt` · 2026-08-24, #332
- Старые `scripts/99-orchestra-proxy` и `scripts/check-proxies.sh` удалены после повторной проверки: установленного dispatcher-hook нет, активный `ai-proxy-manager.service` — единственный владелец маршрута · `.orchestra/tasks/332/evidence/script-entrypoints.txt` · 2026-08-24, #332
- Six pipeline skill files exactly match manifest names, all dashboard template assets exist, and all five loaded JS files pass `node --check` · `.orchestra/tasks/332/evidence/registry-summary.txt`, `js-summary.txt`, command `scripts/check_pipeline_manifest.py --check` · 2026-08-24, #332

## Rejected

- «Serena `{}` означает безопасное удаление» · FastMCP/FastAPI decorators, string/runtime registries, prompt consumers, or tombstone semantics reach or protect the zero-reference symbols · 2026-08-24, #332
- «Старый #309 duplicate `POST /api/models/refresh` всё ещё current» · current main has one route decorator and zero duplicate keys; #309 CSV is pre-implementation baseline evidence · 2026-08-24, #332
- «Нулевая прямая ссылка на JS function означает dead» · inline/template handlers and DOM/event dispatch account for live symbols; only `deleteOrchestrator` survived all arms as a production-unreachable duplicate · 2026-08-24, #332

## Gaps

- Whether an operator-installed copy of the proxy scripts exists outside the audited checkout remains unverified; live route/service changes were forbidden · 2026-08-24, #332
- Whether an external reducer integration calls `fan_id_for_reducer` remains unobservable from repo/static registries; no deletion proposed · 2026-08-24, #332
- A browser-shaped deletion/mutation run for `deleteOrchestrator` was not executed because the task forbids service/provider/environment changes; exact future oracle is recorded in `candidate-table.csv` · 2026-08-24, #332

## Источники

- `.orchestra/tasks/332/research.md` — full current-main dead-code reachability synthesis
- `.orchestra/tasks/332/metrics.md` — counts, registry metrics, and exclusions
- `.orchestra/tasks/332/candidate-table.csv` — fixed decision table and future red/mutation oracles
- `.orchestra/tasks/309/research.md` and `.orchestra/tasks/309/evidence/` — pre-#309 baseline, not current registry truth

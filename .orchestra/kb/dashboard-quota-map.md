# dashboard-quota-map

## Установлено

- Quota refresh создаёт browser-only `TimeoutError`, когда 2-секундный `AbortSignal` начинается до получения HTTP/1.1 slot: контроль с существующим SSE + 5 extra SSE повторил exact failure на local и tunnel; у normal local failure нет completion lines, но ingress не инструментирован · `docs/tasks/234/browser-baseline.json`, `browser-controls.json`, `server-correlation.json`, `review-research-sol.md` · 2026-08-23, #234
- Один refresh phase запускает `/api/usage` и ДВА `/api/usage/quota-map`: `initUsageBar()` и `initQuotaLines()` стартуют рядом, оба 120-секундных цикла живут вне phase-shift coordinator · `app/static/js/app.js:924-925,8943-8970`; `app/static/js/usage.js:815-823,879` · 2026-08-23, #234
- Server refresh усиливает browser storm: `build_quota_map()` зовёт `_get_usage_data()` без single-flight; в измеренном burst было 10 одинаковых Grok GET за одну секунду локально и 2 Anthropic GET на VPS · `docs/tasks/234/journal-local.txt`, `journal-remote.txt`; `app/routes/system.py:944-1074,1428` · 2026-08-23, #234
- `⚠ Usage unavailable` принадлежит отказу `/api/usage`, не quota-map: quota-map-only fault сохранил usage, usage-only fault дал точный текст; rejected `Promise.allSettled` обнуляет `_usageData` и сохраняет `null`, поэтому fallback #197 не выполняется · `docs/tasks/234/browser-controls.json`; `app/static/js/usage.js:820-846`; named #197 test → exit 1 · 2026-08-23, #234
- Public reverse proxy увеличивает tail, но не является единственной причиной: direct tunnel 0/4 >2 с, public 3/4 >2 с; browser final failure был 1/4 на каждом из local/tunnel/public · `docs/tasks/234/http-baseline.json`, `browser-baseline.json` · 2026-08-23, #234

## Отвергнуто

- «Текущий quota-map timeout требует IndexedDB corruption» · fresh context упал до dirty state; 688 rows / 1,651,200 bytes + mismatched-watermark repair overlapped with successful quota response in 1,497.7 ms; historical corrupted #364 profile не сохранился · `docs/tasks/234/browser-controls.json` · 2026-08-23, #234
- «401/redirect ошибочно ретраится как обрыв» · controlled 401: one attempt, `Error`, network banner hidden · `docs/tasks/234/browser-controls.json` · 2026-08-23, #234
- «SQLite trace scan — главный механизм» · live read-only SQL 3–12 ms local и 8–20 ms VPS; общий event-loop stall остаётся unsupported, а не полностью refuted, потому что exact overlap timestamps HEAD/quota не сохранены · `docs/tasks/234/http-baseline.json`, `server-correlation.json`, `review-research-sol.md` · 2026-08-23, #234
- «Queue of four alone is complete fix» · scratch A/B/A/B: queue arms 10/11 then 11/11, current 10/11 then 11/11; queue reduced retries in one arm but still lost cold quota-map once · `docs/tasks/234/queue-candidate.json` · 2026-08-23, #234

## Пробелы

- Exact minimal queue width and ownership contract are not selected; queue-only candidate was insufficient, so client admission must be tested together with server refresh single-flight/cache-only behavior · stopped at Phase 1 by task scope · 2026-08-23, Orchestra-orchestrator
- Original #364 corrupt IndexedDB state is unavailable; synthetic volume/mismatch refutes necessity, not every possible corruption mode · raw user profile was intentionally not copied or mutated · 2026-08-23, Orchestra-orchestrator
- Long-run production failure probability is unknown; 12 normal browser actions establish mechanism, not a stable rate · bounded-run requirement · 2026-08-23, Orchestra-orchestrator

## Источники

- `docs/tasks/234/research.md` — three-origin browser/server correlation, controls, fallback regression, and bounded fix class.

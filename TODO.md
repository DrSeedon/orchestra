# Orchestra TODO

## Next
- [ ] **Task Context Space** — `task_context` param in `spawn_worker()`. Points to a folder (e.g. `docs/tasks/victoria-fsm/`), Orchestra auto-adds "Read TASK.md and PLAN.md from <path> before starting" to worker system_prompt. Convention: `docs/tasks/<slug>/` with TASK.md, PLAN.md, RESEARCH.md, CONTEXT.md, REVIEW.md. Feature request from Parsing-orchestrator
- [ ] **Global SSE stream** — replace polling with single EventSource for all dashboard updates
- [ ] **TG images** — send screenshots/uploads via bot.send_photo() to TG bridge
- [ ] **Git tree view** — git branches/commits visualization in dashboard
- [ ] **Auto-merge worker** — auto merge worker branches with conflict detection
- [ ] **Stop vs Kill** — `stop_worker` = interrupt + idle (can inspect), `kill_worker` = full delete
- [ ] **HTML артефакты** — агент генерит HTML (отчёт, план, сравнение вариантов) → сохраняет в файл → preview в дашборде или send_file в TG. Идея из https://habr.com/ru/articles/1033326/
- [ ] **Rename worker** — ~~MCP tool для переименования воркера~~ DONE (v2.5.0)
- [ ] **Worker progress tracking** — MCP tool `update_progress(percent, status)` чтобы воркер мог трекать % выполнения задачи. На фронте отображается в списке воркеров (прогресс-бар + статус). Воркер: получил задачу → 0%, сделал часть → 30%, всё готово → 100%. Видно снаружи без захода в логи
- [ ] **TG persistent client fix** — persistent client Parsing-orchestrator периодически умирает, TG сообщения не доходят. Нужен heartbeat/watchdog или fallback на fresh client

## Done (v2.5.0)
- [x] **Usage status bar** — OAuth API, 5h/7d bars, HSL gradient, `/api/usage` endpoint
- [x] **Persistent client** — mid-turn inject via `query()`, auto-reconnect
- [x] **TG flood fix** — turn-based batching, 37→11 calls/turn
- [x] **Custom bubbles** — spawn_worker, WebSearch, WebFetch, ToolSearch, report_bug
- [x] **Auto-compact orchestrators** — enabled for all agents

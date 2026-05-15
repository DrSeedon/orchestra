# Orchestra TODO

## In Progress
- [ ] **Idle hibernate** — убивать CLI + MCP при idle (5/10 мин), reconnect при send. -1.2 GB RAM. feat-idle-optimization реализует
- [ ] **Worker project MCP** — воркеры подхватывают MCP из project settings (Playwright, Serena). feat-idle-optimization реализует

## Later
- [ ] **Max turns strategy** — воркер упирается в max_turns=500. Ресёрч: авто-продолжение (detect turn limit → inject "continue"), или compact + restart, или просто убрать лимит? Что делает Claude Code без лимита?
- [ ] **Agent scheduler** — агенты могут ставить отложенные задачи: `schedule(delay="2h", message="проверь деплой")` или `schedule(event="pr_merged", message="запусти тесты")`. MCP tool для создания, SQLite хранение, фоновый loop проверяет таймеры/события и инжектит сообщение агенту. Юзкейсы: мониторинг деплоя, напоминания, периодические проверки, "разбуди через час"
- [ ] **Emergency migrate** — кнопка "⚡ Migrate to GPT" в дашборде. Server-side: логи из DB → spawn на GPT → inject summary
- [ ] **CI failure auto-routing** — PR зафейлился → логи автоинжектятся воркеру → самофикс
- [ ] **Dashboard streaming (Phase 1)** — flip `include_partial_messages=True`, rewrite SSE
- [ ] **TG streaming (Phase 2)** — TgStreamer state machine
- [ ] **Task Context Space** — `task_context` param in `spawn_worker()`
- [ ] **HTML артефакты** — preview HTML в дашборде + send_file в TG

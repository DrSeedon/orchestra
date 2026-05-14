# Orchestra TODO

## Later
- [ ] **Emergency migrate** — кнопка "⚡ Migrate to GPT" в дашборде. `POST /api/sessions/{name}/emergency-migrate?target_model=gpt-5.5`. Server-side: собрать логи из DB → kill сессию → spawn новую на target модели → inject логи как первое сообщение, target модель сама делает summary и продолжает. Не зависит от живого агента
- [ ] **CI failure auto-routing** — PR зафейлился → логи автоинжектятся воркеру → самофикс. Идея из Composio
- [ ] **Dashboard streaming (Phase 1)** — flip `include_partial_messages=True`, rewrite SSE
- [ ] **TG streaming (Phase 2)** — TgStreamer state machine
- [ ] **Task Context Space** — `task_context` param in `spawn_worker()`
- [ ] **HTML артефакты** — preview HTML в дашборде + send_file в TG

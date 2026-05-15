# Orchestra TODO

## In Progress
- [ ] **Worker MCP auto-discovery** — `setting_sources=["user","project","local"]` чтобы воркеры видели все MCP. feat-idle-optimization делает
- [ ] **Monitor tool blocked** — заменяем на server-side watch. feat-idle-optimization делает

## Later
- [ ] **Server-side watch()** — MCP tool `watch(source, pattern, on_match)`. Живёт в Orchestra сервере, переживает hibernate. Замена Monitor/run_in_background. Ресёрч: `docs/research/background-tasks.md`
- [ ] **Agent scheduler** — `schedule(delay, event, message)` для отложенных задач и будильников
- [ ] **Emergency migrate** — кнопка "⚡ Migrate to GPT". Server-side: логи → spawn на GPT → inject summary
- [ ] **CI failure auto-routing** — PR fail → логи автоинжект воркеру → самофикс
- [ ] **Dashboard streaming** — `include_partial_messages=True`, rewrite SSE
- [ ] **Task Context Space** — `task_context` param in `spawn_worker()`
- [ ] **HTML артефакты** — preview HTML в дашборде + send_file в TG
- [ ] **TG topic icons** — `icon_custom_emoji_id` вместо 🟢/🟡 в названии (⚡️=running, ☕️=idle)

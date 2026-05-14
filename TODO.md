# Orchestra TODO

## Now
- [ ] **TG images** — `send_file` определяет тип: картинки → `send_photo` (inline preview), остальное → `send_document`. Файлы: `tg_bridge.py`, `mcp_stdio.py`
- [ ] **Worker progress tracking** — MCP tool `update_progress(percent, status)`, прогресс-бар в sidebar. Файлы: `mcp_stdio.py`, `session.py`, `app.js`
- [ ] **TG persistent client fix** — heartbeat/watchdog для persistent client, auto-reconnect при тихой смерти. Файлы: `session.py`
- [ ] **Stop vs Kill** — `stop_worker` = interrupt + idle (worktree живой), `kill_worker` = full delete. Файлы: `manager.py`, `mcp_stdio.py`

## Later
- [ ] **Task Context Space** — `task_context` param in `spawn_worker()`, auto-adds docs folder to prompt
- [ ] **HTML артефакты** — preview HTML в дашборде + send_file в TG

## Research needed
- [ ] **Global SSE stream** — заменить polling на EventSource. Нужен ресёрч: архитектура, edge cases, стоит ли вообще
- [ ] **Auto-merge worker** — auto merge worktree веток в main. Ресёрч: стратегия конфликтов, git merge pitfalls
- [ ] **Git tree view** — визуализация веток/коммитов. Ресёрч: готовые библиотеки (gitgraph.js, etc)
- [ ] **TG streaming redesign** — стриминг ответов LLM на фронт и в TG. Ресёрч: нагрузка, rate limits TG, архитектура

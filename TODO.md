# Orchestra TODO

## Done ✅
- [x] External stdio MCP server (no in-process deadlocks)
- [x] Simplified session.py (fresh client per turn)
- [x] Worker Inbox + Job Registry
- [x] Turn timeout (300s)
- [x] Smart color picker
- [x] SSE realtime logs
- [x] Offline CSS (Tailwind bundled)
- [x] Hiddify proxy everywhere
- [x] Systemd service
- [x] Health check loop
- [x] Dynamic cli_path
- [x] Auto sender tag

## Next
- [x] **File browser panel** — tree view слева, drag-and-drop в chat, иконки по типу файла
- [ ] **Orchestra skill** — Claude Code skill `/orchestra` для запуска задач из любого проекта. Триггеры: "запусти оркестратор", "создай воркеров", "/orchestra". Skill проверяет что сервер запущен, создаёт/находит orchestrator для текущего проекта, отправляет задачу. Можно из любой Claude Code сессии без открытия dashboard
- [ ] SSE for session list/stats (not just logs)
- [ ] Worker templates — `.claude/agents/*.md` as presets
- [ ] Auto-compact at 30% context
- [ ] Media in chat (images/files from workers)
- [ ] Multi-orchestrator support in dashboard
- [ ] Worker restart with retry on failure

# Orchestra TODO

## Next
- [ ] **Global SSE stream** — replace polling with single EventSource for all dashboard updates
- [ ] **Orchestra skill** — `/orchestra` slash command from any Claude Code session
- [ ] **Watchdog** — auto-ping worker if idle >10min without send_message after receiving task
- [ ] **TG images** — картинки из чата (screenshots, uploads) не отображаются в Telegram bridge. На фронте видны, в TG — нет. Нужно отправлять через bot.send_photo()
- [ ] **Git tree view** — визуализация git веток/коммитов в дашборде (как в Cursor Source Control)
- [ ] **Usage status bar** — в header дашборда показывать:
  - Session % (5h block) — из OAuth API `https://api.anthropic.com/api/oauth/usage`
  - Weekly % (7d rolling) — оттуда же
  - Per-model: Opus %, Sonnet % — оттуда же
  - Auth: OAuth token из `~/.claude/.credentials.json` + refresh через `https://platform.claude.com/v1/oauth/token`
  - Кеш: 60 сек TTL, backend endpoint `/api/usage`
  - Frontend: progress bars в header рядом со stats
- [ ] **Auto-merge worker** — автоматический merge веток воркеров с conflict detection. Если конфликт → спросить оркестратора вместо тихого фейла
- [ ] **Stop vs Kill разделение** — MCP tools: `stop_worker(name)` = interrupt текущий turn, воркер idle, можно посмотреть логи/diff. `kill_worker(name)` = полное удаление. Сейчас kill сразу удаляет без возможности проверить результат

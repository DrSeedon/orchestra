# Orchestra TODO

## Next
- [ ] **Auto-compact** — trigger at context >90% automatically (platform-level). Tool `compact_worker` already works — need auto-trigger in session.py after ResultMessage
- [ ] **Global SSE stream** — replace polling with single EventSource for all dashboard updates
- [ ] **Orchestra skill** — `/orchestra` slash command from any Claude Code session
- [ ] **Watchdog** — auto-ping worker if idle >10min without send_message after receiving task
- [ ] **TG images** — картинки из чата (screenshots, uploads) не отображаются в Telegram bridge. На фронте видны, в TG — нет. Нужно отправлять через bot.send_photo()
- [ ] **Orchestra skill done** — skill создан в app/skills/orchestra/SKILL.md, нужно скопировать в ~/.claude/skills/ и протестировать
- [ ] **Git tree view** — визуализация git веток/коммитов в дашборде (как в Cursor Source Control)
- [ ] **Usage status bar** — показывать session usage %, weekly cap %, context %, model, effort level — как в Claude Code status line. Для каждого агента в sidebar или в header

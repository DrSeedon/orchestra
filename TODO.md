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

## Done (this session) ✅
- [x] **File browser panel** — tree view слева, drag-and-drop в chat
- [x] **Delete orchestrator** — `DELETE /api/orchestrators/{name}`, кнопка ✕ в хедере
- [x] **Remember last orchestrator** — localStorage
- [x] **Stop vs Delete** — stop = unload (сохраняет логи), delete = remove (каскад)
- [x] **Scroll fix** — не дёргает при чтении истории
- [x] **Context %** — правильный подсчёт (last iteration, per-model limit, cache stats)
- [x] **Context bar** — цветная полоска в списке агентов
- [x] **Cache hit %** — в agent info panel
- [x] **Auto-report** — воркеры без send_message автоматически отчитываются
- [x] **Inject messages** — сообщения running агентам доставляются мгновенно
- [x] **Prompt hot-reload** — обновлённые промпты инжектятся при первом turn'е
- [x] **Base/orchestrator/worker промпты** — shared platform knowledge
- [x] **Cross-project messaging** — list_orchestrators, send_message across scopes
- [x] **notify_kesha** — оркестраторы шлют результат в Telegram
- [x] **Kesha inbox server** — HTTP endpoint для обратной связи Orchestra → Kesha
- [x] **report_bug** — агенты файлят баги в BUGS.md
- [x] **Restart button** — ⟳ в дашборде, sudo -n
- [x] **Orchestrator tabs** — pill buttons вместо dropdown
- [x] **Image paste** — Ctrl+V upload с дедупликацией по md5
- [x] **Newlines in tool/result** — json.dumps + pre-wrap
- [x] **Status badges** — ⚡ в чате для system events
- [x] **MCP absolute path** — работает из любого CWD (worktrees)
- [x] **No .mcp.json copy** — worktrees не override'ят Orchestra MCP
- [x] **Interrupt fix** — реально ставит IDLE + persist
- [x] **Trailing slash fix** — scope нормализация
- [x] **Ghost workers fix** — kill DB-only sessions
- [x] **Multi-repo tested** — Parsing (5 sub-repos), worktree isolation OK

## Next
- [ ] **Global SSE stream** — один endpoint для session list, stats, orch status. Заменит polling `/api/orchestrators` + `/api/sessions` + `/api/stats`. Сейчас polling 3s — работает, но не масштабируется
- [ ] **Diff view for Edit tool** — парсить old_string/new_string из Edit input, рендерить как diff с красным/зелёным (как в Claude Code). file_path как заголовок
- [ ] **System prompt viewer** — кнопка в agent info показывает полный system_prompt агента
- [ ] **File preview in dashboard** — клик на .md/.txt/.png открывает содержимое в модалке, отдельная кнопка "отправить в чат" рядом с файлом
- [ ] **TG media support** — фото/документы/голосовые в TG bridge (план в docs/tg-media/PLAN.md, Codex review done)
- [ ] **Orchestra skill** — `/orchestra` для запуска задач из любого проекта
- [ ] Worker templates — `.claude/agents/*.md` as presets
- [ ] **Auto-compact** — summary → reset session_id → continue with summary as first message. Kesha pattern (compact.py). Trigger: context >80%. Need reset_session() in AgentSession
- [ ] **Auto-merge** — MCP tool for orchestrator to merge worker branch into main. `git merge --no-ff feat/...`
- [ ] **Auto-deploy** — MCP tool: `ssh deploy@vps 'cd /opt/project && git pull'`. Per-project config
- [ ] **Watchdog** — if worker idle >10min without send_message after task → auto-ping
- [ ] Worker restart with retry on failure

# Orchestra TODO

## Now
- [ ] **Codex migration plan** — ресёрч: можно ли мигрировать Orchestra на OpenAI Codex CLI если Anthropic забанит. Разница SDK, session management, tool calling, MCP support. План B на случай бана

## Later
- [ ] **Dashboard streaming (Phase 1)** — flip `include_partial_messages=True`, add `_ui_queue` per session, rewrite SSE endpoint. Ресёрч: `docs/research/streaming-redesign.md`. Отложено — не трогать работающее
- [ ] **TG streaming (Phase 2)** — TgStreamer state machine. Отложено вместе с Phase 1
- [ ] **Task Context Space** — `task_context` param in `spawn_worker()`, auto-adds docs folder to prompt
- [ ] **HTML артефакты** — preview HTML в дашборде + send_file в TG
- [ ] **Встроенный таск-менеджер** — замена YouGile для Parsing. Отдельный MCP сервер, SQLite, 5-6 tools, TG нотификации. Feature request от Parsing-orchestrator

# Orchestra TODO

## Later
- [ ] **Dashboard streaming (Phase 1)** — flip `include_partial_messages=True`, add `_ui_queue` per session, rewrite SSE endpoint. Ресёрч: `docs/research/streaming-redesign.md`. Отложено — не трогать работающее
- [ ] **TG streaming (Phase 2)** — TgStreamer state machine. Отложено вместе с Phase 1
- [ ] **Task Context Space** — `task_context` param in `spawn_worker()`, auto-adds docs folder to prompt
- [ ] **HTML артефакты** — preview HTML в дашборде + send_file в TG

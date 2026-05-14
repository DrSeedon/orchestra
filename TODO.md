# Orchestra TODO

## In Progress
- [ ] **Task manager** — встроенный таск-менеджер с YouGile sync и payment engine. Дизайн Codex-approved (1010 строк). research-taskmanager реализует. `docs/research/task-manager-design.md`
- [ ] **Codex backend** — AgentBackend абстракция, CodexBackend на `codex exec --json`. research-codex-migration планирует. `docs/research/codex-migration.md`

## Later
- [ ] **CI failure auto-routing** — PR зафейлился → логи автоинжектятся воркеру → самофикс. Идея из Composio. Ресёрч: `docs/research/competitor-analysis.md`
- [ ] **Dashboard streaming (Phase 1)** — flip `include_partial_messages=True`, rewrite SSE. Ресёрч: `docs/research/streaming-redesign.md`
- [ ] **TG streaming (Phase 2)** — TgStreamer state machine
- [ ] **Task Context Space** — `task_context` param in `spawn_worker()`
- [ ] **HTML артефакты** — preview HTML в дашборде + send_file в TG

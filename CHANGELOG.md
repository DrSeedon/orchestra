# Changelog

## v1.0.0 — 2026-04-30

Complete rewrite from MVP v0.4. One class, one way, Apple-level simplicity.

### Added
- 🏗️ **`AgentSession`** — single SDK wrapper replacing both `Worker` and `Orchestrator` classes. One class for all agents, config-driven (model, system_prompt, mcp_servers)
- 🌿 **`workspace.py`** — isolated worktree management. Scope-namespaced paths (`worktrees/{scope_slug}/{name}`), fail loud, no silent fallbacks
- 🔧 **MCP tools for orchestrator** — `spawn_worker`, `send_to_worker`, `list_workers`, `get_worker_logs`, `kill_worker`. Orchestrator manages workers natively via MCP, not prompt hacking
- 🔧 **MCP tools for workers** — `send_message` (to any agent), `list_agents`. Workers can communicate with orchestrator and each other
- 📝 **System prompts** — `orchestrator_prompt.md` and `worker_prompt.md` in `app/`. Editable .md files, not hardcoded strings
- 🖥️ **Dashboard v2** — single-screen UI: chat with any agent (left), agent list + info (right). Click to switch between orchestrator and workers. Markdown rendering, debounce indicator, adaptive polling (500ms when waiting, 3s idle)
- 📊 **Message debounce** — multiple rapid messages batched into one (2s window, like Kesha). Visual ring timer on pending messages
- 💉 **Live inject** — messages sent while agent is RUNNING inject directly into current turn (no queue, no "session busy")
- 🧪 **97 TDD tests** — `test_db.py` (29), `test_workspace.py` (16), `test_session.py` (18), `test_manager.py` (14), `test_api.py` (20). Written before code (RED→GREEN)
- 🔑 **UUID primary keys** — `UNIQUE(name, scope)` for display, UUID internally. No collisions between scopes
- 📡 **Multi-orchestrator support** — one dashboard, multiple orchestrators (one per project). Picker in header, scope filtering
- 🔄 **Auto-resume** — orchestrators survive server restart (status stays `idle`, SDK resumes via `session_id`)
- 🛡️ **Permission fix** — `default` + `can_use_tool` auto-approve instead of `bypassPermissions` (known regression: Claude Code #36497, #37157, #36923)

### Removed
- `worker.py` — replaced by `AgentSession` in `session.py`
- `orchestrator.py` — replaced by `AgentSession` in `session.py`
- `callbacks` table — replaced by session logs with `type="notification"`
- 18 API endpoints → 9 (one resource `/api/sessions`)
- `max_turns` parameter — SDK manages this
- `data/orchestrator_session` file — session_id now in SQLite
- Separate notifications tab — everything in chat

### Changed
- **DB schema** — `sessions` + `logs` (was `workers` + `logs` + `callbacks`). UPSERT, CASCADE, `busy_timeout=5000`, `foreign_keys=ON`
- **API** — one resource `/api/sessions`. Pydantic validation, proper HTTP status codes (404/409/422), no `{"ok": false}`
- **Dashboard** — HTML/CSS/JS split into separate files. DOM API rendering (no innerHTML XSS). Cursor-based log pagination

### Architecture
```
app/
  main.py            — FastAPI, 9 endpoints
  session.py         — AgentSession (single SDK wrapper)
  manager.py         — SessionManager (registry + lifecycle)
  workspace.py       — git worktree create/remove
  db.py              — SQLite (sessions + logs)
  tools.py           — MCP tools for orchestrator + workers
  orchestrator_prompt.md
  worker_prompt.md
  static/css/style.css
  static/js/app.js
  templates/dashboard.html
```

### Process
- 4-round Codex (GPT-5.5) adversarial review of spec before implementation
- TDD for all modules: tests written first, then minimal code
- Codex code review (Round 5) caught 4 real bugs post-implementation

# Changelog

## v2.2.0 — 2026-05-05

### Added
- 🗑️ **Delete orchestrator** — `DELETE /api/orchestrators/{name}` removes orchestrator + all
  workers in scope (active sessions, worktrees, DB records). Dashboard button `✕ Delete` with
  confirm dialog. `manager.remove_scope(scope)` handles cleanup.
- 💾 **Remember last orchestrator** — `localStorage` saves `lastOrchScope`/`lastOrchName` on
  switch, restores on page load. No more "always opens first in list".

### Fixed
- **Stop deleted logs (critical)** — `POST /stop` called `manager.remove()` which ran
  `DELETE FROM sessions` → `ON DELETE CASCADE` wiped all logs. Now stop calls `unload()`
  (stops session, removes from memory, preserves DB). Only explicit Delete removes from DB.
  - Triggered case: kesha-tg-bot orchestrator stuck running after interrupt, used stop to
    unstick it → 2318 log entries deleted by cascade. User saw empty chat.
- **Scroll hijack on history read** — three sources of forced scroll-to-bottom:
  1. `showWaitingIndicator()` unconditionally set `scrollTop` — now checks `wasAtBottom`
  2. SSE handler had duplicate scroll check after `addChatEntry` (which already handles it)
  3. `refreshSessions` re-created waiting indicator every 3s (SSE removed it → refresh
     recreated → scroll). Removed re-creation from refresh loop.

## v2.1.0 — 2026-05-04

### Added
- 📡 **SSE realtime logs** — `GET /api/sessions/{name}/stream` replaces polling for chat
- 🏥 **Health check loop** — detects crashed worker tasks every 60s
- 🔌 **Systemd service** — `orchestra.service` with auto-restart and Hiddify proxy
- 🎨 **Smart color picker** — unique color per worker, least-used fallback
- 🏷️ **Auto sender tag** — server adds `[from:name]`, workers send plain text
- 📴 **Offline CSS** — Tailwind/marked/DOMPurify bundled locally

### Fixed
- **Auto-resume crash** — error sessions marked stopped on startup
- **cli_path** — dynamic via `shutil.which("claude")`
- **Worker logs** — filtered (text/tool/error only), no raw dumps
- **tool_result parsing** — unwraps `{"result":"..."}` wrapper
- **Proxy** — `HTTPS_PROXY` set in session.py, manager.py, service file

## v2.0.0 — 2026-05-03

### Changed
- **External stdio MCP server** — MCP tools now run as separate process (`app/mcp_stdio.py`)
  via FastMCP, communicating with Orchestra API over HTTP. Replaces in-process `create_sdk_mcp_server`
  which caused deadlocks (SDK issue #425). External process = no shared event loop = no hang.
- **Simplified session.py** — removed persistent client, locks, _is_connected, _cleanup_client.
  Each turn: create fresh ClaudeSDKClient → connect → query → receive → disconnect (in finally).
  Root cause of ALL hangs was accumulated state in persistent connection.
  Proven: direct SDK test = 5 MCP calls in 17s. Old session.py = hang on 3rd call.
  New session.py = 18 MCP calls in 85s, zero hangs. -328 lines, +166 lines.
- **Worker communication via HTTP** — workers send reports via `curl POST /api/sessions/{name}/send`.
  Orchestrator receives via debounce → new turn. No MCP inject needed.
- **System CLI** — uses system Claude CLI 2.1.126 via `cli_path` instead of bundled 2.1.117

### Added
- 📬 **Worker Inbox** — `inbox` DB table + `GET /api/sessions/{name}/inbox` endpoint.
  `send_to_worker` queues messages in inbox. Real delivery semantics.
- 📋 **Job Registry** — `jobs` DB table + `GET /api/jobs` endpoint + `list_jobs` MCP tool.
  spawn/kill create tracked jobs with status (queued/executing/succeeded/failed).
- ⏱️ **Turn timeout** — 300s hard deadline on `_listen()`, 60s on `connect()`.
  TimeoutError → ERROR status. No more infinite hangs.
- 🔒 **Scoped lookups** — `find_worker(name, scope)`, `find_session_id_by_name(name, scope)`.
- 🧪 **`.mcp.json`** — project-level MCP config for local testing from Claude Code
- `alwaysLoad: true` — MCP tools skip ToolSearch deferral (v2.1.121 feature)

### Removed
- `create_sdk_mcp_server` in-process MCP (deadlock source)
- Persistent client connection in session.py (accumulation source)
- `.env` copy to worktrees (security fix)
- Prompt rule "max 2 MCP calls" (no longer needed)
- SDK monkey-patches (buffer, stdin) — no longer needed

### Fixed
- **Duplicate user_message logs** — send() logs once, _run_turn no longer duplicates
- **Timestamps** always visible in white on dashboard
- **pytest discovery** — testpaths=["tests"], norecursedirs for worktrees

## v1.3.0 — 2026-05-02

### Fixed
- **SDK MCP tool hang — root cause found and workarounds applied** — in-process MCP tool calls
  (`create_sdk_mcp_server`) hung after 2-3 calls per turn. Root cause: SDK `Query._read_messages`
  single read task handles both control_request routing AND bounded message stream (`max_buffer_size=100`).
  When buffer fills, read task blocks on `send()` → control_requests never reach Python MCP handlers → CLI
  waits for control_response forever → deadlock. SDK issue #425 (open, no PR).
  - **SDK patch: buffer 100→10000** — `query.py` monkey-patch, prevents backpressure up to 10000 messages
  - **SDK patch: stdin kept open** — `wait_for_result_and_end_input()` no longer closes stdin when SDK MCP
    servers present. Needed for persistent connections with multiple query() calls
  - **Spawn queue** — `spawn_worker` MCP tool no longer does heavy work (git worktree + session start)
    inside the MCP handler. Jobs enqueued to `asyncio.Queue`, processed by background supervisor task
    with 0.5s delay to let control_response flush first (Codex review finding)
  - **git worktree via to_thread** — `create_worktree()` sync subprocess moved to `asyncio.to_thread()`
    to avoid blocking event loop during MCP response path
  - **Inject removed** — `session.send()` no longer calls `client.query()` inject on RUNNING sessions.
    Messages queue in `_pending`, processed as new turn when session goes IDLE. Inject caused transport
    deadlock (both directions: worker→orch and orch→worker)
  - **Worker HTTP callback** — workers send reports via `curl POST /api/sessions/{name}/send` instead of
    MCP `send_message` inject. Eliminates transport deadlock entirely for worker→orchestrator communication
  - **Async DB writes** — `_log()` and `_persist()` via `run_in_executor()` to avoid blocking event loop
  - **include_partial_messages=False** — reduces stream event volume in SDK bounded buffer
  - **Orchestrator prompt: max 2 MCP calls per response** — prevents hitting CLI tool call limit per turn
  - Triggered case: every test with orchestrator + worker — spawn→list_workers→get_worker_logs chain hung
    on 3rd MCP call every time. Single MCP calls worked fine (5s). Multiple calls = deadlock.

### Changed
- **SDK pinned** — `claude-agent-sdk>=0.1.72` in pyproject.toml. Was unpinned, any `uv sync` could
  break everything. v0.1.72 fixes silent MCP tool result loss (v0.1.70+)

### Added
- **Spawn queue** — `SessionManager.enqueue_worker_spawn()`, `_spawn_worker_loop()` background task
- **Session error callback** — `AgentSession.on_error` + `SessionManager._on_session_error()` moves
  errored sessions from active to archived automatically

## v1.2.0 — 2026-05-01

### Changed
- **Data layer refactor — single source of truth** — `SessionManager` is now the sole data gateway.
  `manager.archived: dict[str, dict]` holds stopped/error sessions in memory. `list_sessions()` reads
  purely from memory (active + archived), zero DB merges. `stop()` moves session from active → archived.
  `tools.py` has zero direct DB imports (except `get_logs`). `main.py` reduced from 4 DB fallback paths to 0.
  - `load_archived()` at startup populates archived dict from DB
  - `find_worker()`, `find_session_id_by_name()`, `archive_by_id()`, `get_session_id()` — new manager methods
  - `ensure_loaded()` skips archived sessions (no zombie resurrections)
  - `kill_worker` for DB-only sessions now properly archives via `archive_by_id()`
  - 10 new TDD tests for archived dict behavior (107 total)
  - **Before**: 8 code paths with direct DB access scattered across tools.py + main.py, different formats (AgentSession vs dict), merge logic, fallback reconnects
  - **After**: manager = memory cache, DB = write-through backup + logs storage. One path, one format

## v1.1.0 — 2026-05-01

### Added
- 📡 **Streaming text** — responses appear live as chunks, not after full generation. `StreamEvent` + `content_block_delta` handling
- 📎 **Tool results visible** — MCP tool outputs (`ToolResultBlock`) shown in chat with 📎 prefix
- 🪦 **Agent archive** — stopped/killed workers get hash suffix (e.g. `worker-1-abc123`), move to archive section. Name freed for reuse. Chat history preserved, read-only
- 🏷️ **Model registry** — `app/models.py` single source of truth. Aliases resolved (`sonnet` → `claude-sonnet-4-6`). API validates, dropdown loads from `/api/models`
- 🔄 **restart_worker** MCP tool — kill + respawn in one call
- 📊 **Context display** — `5% (12k/200k)` format, cached on agent switch

### Fixed
- **Worktree preserved on stop** — `stop()` no longer deletes worktree. Only explicit `kill/remove` does
- **Auto-resume rehydrate** — all fields restored from DB (worktree_path, branch, created_at)
- **`_run_turn()` exceptions** — done callback logs errors, sets ERROR status
- **Error UX** — no "waiting for response" after 404/error. Debounce cancelled on failure
- **Stopped agent resume** — writing to stopped agent auto-resumes it (fallback cwd if worktree missing)
- **Duplicate names** — stopped agents archived with hash, name freed for new workers
- **`list_workers`** — shows active + archived workers

### Changed
- `shutdown_all` — orchestrators stay `idle` (not stopped) for auto-resume. Workers get stopped with worktrees intact

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

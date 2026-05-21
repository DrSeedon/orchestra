# Changelog

## v2.6.0 — 2026-05-14

### Added
- 🔄 **Auto-resume ALL sessions on restart** — `auto_resume_all()` restores orchestrators AND workers from DB (was orchestrators-only). Sessions that were `running` at shutdown get a restart notice injected after 3s: `[system] Orchestra server restarted. Your session was restored — continue where you left off.`
  - `_inject_restart_notice()` in `manager.py` — delayed inject with error handling
  - `auto_resume_orchestrators()` kept as backward-compat wrapper
- 🤝 **Cross-orchestrator awareness** — `_other_orchestrators_block(scope)` dynamically generates a list of all other orchestrators with project names, injected into `ORCHESTRATOR_SYSTEM_PROMPT`. Each orchestrator knows who else exists and can `send_message` them. List updates on restart/compact
- 👤 **TG sender name** — all messages from TG now include `[from TG: Name]` prefix so agents know who's writing. Works for text, photos, files, video, audio, voice, video notes, stickers
- 🔒 **TG polling auto-restart** — `_safe_polling()` wraps `dp.start_polling` with crash recovery (auto-restart after 10s) + logging. No more silent polling deaths
- 📊 **Usage cache persistence** — `data/usage_cache.json` survives server restarts. No more empty usage bar after reboot caused by Anthropic rate limit + cold cache
- 🔀 **merge_worker MCP tool** — orchestrator can merge a worker's branch into main with one call. `git merge-tree` precheck detects conflicts before merging. fcntl lock serializes parallel merges. Auto-commits dirty worktree. `workspace.py`, `mcp_stdio.py`, `main.py`
- 🛑 **stop_worker MCP tool** — interrupt + idle without destroying session/worktree. Resumable via send_message. Separate from kill_worker (full delete)
- 📈 **Worker progress tracking** — `update_progress(percent, status)` MCP tool. Green glow progress bar in sidebar. Resets on new task. `session.py`, `db.py`, `mcp_stdio.py`, `app.js`
- 🖼️ **TG images as photos** — `send_file` auto-detects images (.jpg/.png/.gif/.webp/.bmp) → `send_photo()` for inline preview. `as_document=True` forces file attachment
- 🌿 **Git status in worker cards** — sidebar shows `branch+N 💾N "last commit"` per worker. `GET /api/git-status?scope=` with 10s server cache. Green/yellow/gray coloring
- 💓 **Persistent client heartbeat** — 60s heartbeat detects silent listener death, auto-reconnects with inject notice. Silence warning >300s. Full tracebacks on crash

### Changed
- **Usage cache TTL 120→300s** — backend and frontend polling aligned at 5min to reduce Anthropic API rate limit hits
- **TG logger** — `tg-bridge` logger now has `StreamHandler` + `DEBUG` level, all TG events visible in journalctl
- **SSE disconnect leak** — `stream_session_logs` generator now checks `request.is_disconnected()`, stops on tab close

### Fixed
- 🟢🟡 **TG topic status desynced from frontend** — single source of truth via `_any_running_in_scope(scope)`. When orchestrator finishes turn but workers still running → stays 🟢 (was: immediately 🟡). When ANY worker goes idle → `_notify_scope_idle()` checks scope → flips to 🟡 only when ALL idle
  - `check_scope_idle()` in `tg_bridge.py` — public function called from `session.py` and `stream_logs`
  - `_notify_scope_idle()` in `session.py` — fires on every worker IDLE transition, not just auto-report
- 🟢🟡 **TG topic status on startup** — `_sync_all_topic_statuses()` sets correct 🟢/🟡 on all topics when bridge starts
- 🪞 **TG mirror formatting** — mirror messages now receive `converted` text + `entities` from `md_convert()` (was: raw plain text without formatting). All 3 send paths: text/status, tool, tool_result

## v2.5.0 — 2026-05-11

### Added
- 🚀 **Persistent client + mid-turn message injection** — replaced "fresh client per turn" with persistent client per session. `send()` → `client.query()` directly via SDK stdin transport. No more pending queue, debounce, turn boundary waiting. Messages inject mid-turn as system-reminders
  - `_ensure_client()` — connects once, reuses across turns
  - `_persistent_listen()` — infinite loop over `receive_messages()`, does NOT disconnect on ResultMessage
  - `_disconnect_client()` — clean shutdown helper
  - Auto-reconnect: detects dead listener, retries `query()` on failure
  - Removed: `_pending`, `_debounce_task`, `_turn_task`, `_run_turn()`, `_arm_debounce()`, `_on_debounce()`, `debounce_sec`
- 📊 **Usage status bar** — global bar at top of dashboard. OAuth API (`/api/oauth/usage`) with 120s cache, shows 5h/7d utilization with HSL gradient color (green=under budget, yellow=on track, red=burning fast), reset progress % in parentheses. `/api/usage` endpoint combines Anthropic data + per-agent cost from DB
- 🎯 **Spawn worker bubble** — card with `🚀 Spawning name` + model badge pill (color-coded) + markdown task preview + system prompt + repo path. Single click expands all
- 🌐 **WebSearch result renderer** — bracket-counting JSON parser for Links format, Perplexity markdown with token/cost header, standalone detection when `lastTool` is null. Collapsible (5 lines preview)
- 🔍 **ToolSearch bubble** — `🔍 Loading: query` → `✅ Loaded: ToolName` on result
- 🐛 **report_bug bubble** — `🐛 Bug: title` with collapsible description
- 🖼️ **Base64 image rendering** — tool_results with image data render as `<img>`, not raw base64 text
- 📝 **Textarea resize upward** — drag handle above textarea, pull up to expand (bottom of screen = can't drag down)
- 🔄 **Auto-compact for orchestrators** — removed `not self.is_orchestrator` exclusion, orchestrators auto-compact at >90% context

### Changed
- **`interrupt()`** — uses `client.interrupt()` SDK method instead of asyncio task cancellation
- **`compact()`** — stops listener first (race condition fix), bracket-counted JSON parse, disconnects cleanly
- **Turn timeout** — tracked via `_turn_start` timestamp instead of `asyncio.wait_for()`
- **send_message bubble** — split by lines (5 preview), re-render full on expand. No more mid-word cuts
- **Tool result expand** — line-based preview (was char-based), single element with maxHeight (no gap/separator), universal click-to-expand on all bubble types
- **Model aliases** — `claude-opus-4-6` → `claude-opus-4-6[1m]` auto-resolve
- **Worker custom prompt** — `_safe_format_prompt()` replaces `str.format()`, only substitutes known placeholders. Resume correctly extracts custom portion
- **Load-more tool_result matching** — `_findLastBefore()` constrains querySelector to prepended batch only

### Fixed
- **WebSearch `isEdit` bug** — spawn_worker/WebSearch/ToolSearch bubbles had `dataset.isEdit='1'` which caused tool_result handler to early-return, silently swallowing results
- **WebSearch regex** — replaced fragile regex with bracket-counting parser for Links JSON arrays (handles truncated SDK output, multi-item arrays, special chars)
- **Load-more rendering** — old messages now use `addChatEntry()` with full custom bubbles
- **compact() race condition** — listener paused before iterating `receive_messages()`
- **Persistent client dead process** — `_ensure_client()` checks `_listen_task.done()`, `send()` retries with reconnect on `query()` failure
- **Universal click-to-expand** — audit of all handlers, WebSearch and Read .md fixed (were hint-only)

## v2.4.0 — 2026-05-10

### Added
- 🎤 **TG Voice** — Deepgram Nova-3 транскрипция голосовых в TG bridge
- 📷 **TG Media** — полная поддержка: фото, документы, видео, video_note (ffmpeg), аудио, стикеры, forwards с caption. Кеши файлов + транскрипций
- 🔄 **TG Debounce** — state machine IDLE→COLLECTING→WAITING_MEDIA. 5s debounce + 30s media timeout. Батч сообщений в один turn
- 📂 **File preview** — клик по файлу → модалка. MD рендерится через marked.js, картинки через `<img>`, код с горизонтальным скроллом. `/api/files/content` + `/api/files/raw` endpoints
- ✏️ **Diff view** — Google `diff-match-patch` для char-level inline подсветки. LCS line diff + inline highlight для похожих строк (>40% common). Preview 5 строк + expand
- 📖 **Read view** — code viewer с shimmer skeleton, 5 строк preview + expand. Картинки рендерятся как `<img>`
- ✍️ **Write view** — содержимое как diff (всё зелёное)
- 📨 **send_message bubble** — `📨 → target` + markdown preview вместо сырого JSON
- 📜 **Prompt viewer** — 3 секции (📦 Platform / 🎭 Role / ✨ Custom) с реальными подставленными именами
- 📋 **Compact mode** — toggle 📋/📄 в header. Тулы в одну строку, клик раскрывает
- 🖼 **Картинки везде** — user messages, Read tool, text — кликабельные → file preview
- 💰 **Ценник в sidebar** — `$X.XX` зелёным рядом с моделью
- 🌐 **WebSearch рендер** — title (ссылка) + snippet вместо JSON
- 🔧 **Autocommit** — `git add -A && commit "wip:"` перед spawn_worker. Worktree создаётся от актуального кода — нет конфликтов
- ⚡ **Seamless turn** — после ResultMessage если есть pending → сразу новый turn (0ms вместо 2.5s debounce)
- 📊 **stop_reason логирование** — каждый turn пишет `stop_reason=X, num_turns=N`
- 🎼 **Orchestra skill** — `/orchestra` Claude Code skill в `app/skills/orchestra/SKILL.md`
- 🔒 **XSS fixes** — 3 innerHTML→textContent fixes (Codex review)

### Changed
- **max_turns 25→50** — воркеры не обрубаются на больших задачах
- **kill_worker** — теперь `DELETE` (полное удаление), не `POST /stop` (воркеры-призраки больше не висят)
- **Inject убран** — все сообщения в pending queue, нет потерянных/дублей
- **Logs limit 200→5000** — старые сообщения видны в чате
- **MAX_CHAT_NODES 500→5000** — DOM не обрезает историю
- **Deepgram Nova-2→Nova-3** — точнее для русского, та же цена
- **Orchestrator prompt** — обязательный system_prompt для воркеров (шаблон + примеры), file conflict rule, CTO delegation
- **Worker prompt** — bash rules (no polling loops), identity placeholders

### Fixed
- **TG flood control** — retry с backoff вместо fallback на plain text
- **TG error logging** — видно почему formatted send фейлится
- **HTML injection в tool_result** — escape `<>` перед innerHTML
- **Paste preview** — сохраняется/восстанавливается при переключении агентов
- **Markdown everywhere** — user messages, [from:worker], все рендерятся через marked.js
- **chat-bot border** — `#1e293b`→`rgba(99,102,241,0.1)` (видимый)
- **diff-code overflow** — `break-all`→`overflow-wrap: anywhere`
- **Read skeleton** — shimmer placeholder пока tool_result не пришёл
- **Expand hint** — rHint перенесён, querySelector работает
- **Restart без confirm** — убран confirm dialog
- **Prompt viewer identity** — реальные имена вместо `{worker_name}` placeholder
- **Custom prompt после ребута** — кастомная часть сохраняется при hot-reload
- **streamBubble на смене orchestrator** — сброс при переключении
- **initFilePanel drag listeners** — guard от накопления
- **refreshSessions stale scope** — capturedScope проверка

## v2.3.1 — 2026-05-09

### Added
- 🗜 **compact_worker MCP tool** — orchestrator can compact a worker's context (summary → reset session → continue fresh). Tested: 81%→17%, 56%→16%, 20%→16%
- ⚠️ **Context warning >90%** — platform auto-appends `⚠️ CONTEXT CRITICAL` to worker messages
- 🚫 **AskUserQuestion + run_in_background denied** — blocked via `can_use_tool` deny
- 🔧 **Tool+result merged** — one bubble on frontend, one expandable on TG
- 🎨 **Tool icons** — 🖥 Bash, 📖 Read, 🎼 orchestra, 🔌 MCP
- 📝 **Draft per agent** — unsent text preserved when switching
- 🔗 **URL linkify** — clickable links in tool_result
- 💊 **Status badge** — pill with colored bg on idle/running text

### Fixed
- **compact_worker timeout** — was 30s, compact takes ~40s → empty error → double compact. Now 120s
- **Prompt placeholders** — `{orchestrator_name}` was literal in hot-reload for workers
- **Scroll on switch** — chat now scrolls to bottom when opening agent
- **Timestamps overlap** — inline block instead of absolute positioning

## v2.3.0 — 2026-05-09

### Added
- 📱 **TG Bridge** (`app/tg_bridge.py`) — mirrors orchestrators to Telegram group topics.
  Auto-creates topic per orchestrator, bidirectional messaging, real-time log streaming.
  Separate bot (`@orchestraClaude_bot`), config in `.env` / `data/tg_bridge.json`
- 📬 **Kesha inbox server** (`inbox_server.py` in kesha-tg-bot) — HTTP endpoint :18081,
  Orchestra → Kesha via `notify_kesha` MCP tool → shows in Telegram chat
- 🔄 **Auto-report** — workers that finish without `send_message` get force-reported to
  orchestrator with last 3 text outputs. `[from:worker] [auto-report]` format
- 💉 **Message inject** — messages to RUNNING agents injected via `client.query()` immediately,
  no waiting for turn end. Fallback to pending queue on failure
- 🔥 **Prompt hot-reload** — updated `app/prompts/*.md` injected on first turn after restart.
  `[Orchestra platform note]` tag avoids prompt injection detection
- 📊 **Context tracking** — `input + cache_creation + cache_read` from last iteration,
  per-model limits (Opus 1M, Sonnet 200k), cache hit % in agent info panel
- 📈 **Context bar** — colored progress bar per agent in sidebar (green/yellow/red)
- 🌐 **Cross-project messaging** — `list_orchestrators()` discovers all orchestrators,
  `send_message` fallback searches by name across all scopes (`ensure_loaded_any`)
- 🐛 **report_bug MCP tool** — agents file bugs to `BUGS.md` with timestamp/reporter/scope
- ⟳ **Restart button** — dashboard header, `sudo -n systemctl restart orchestra`
- 💊 **Orchestrator tabs** — pill buttons replace dropdown, recent-first, live status dots
- 🖼 **Image paste** — Ctrl+V upload with md5 dedup, preview under input, render in chat
- ⚡ **Status badges** — `⚡ interrupted`, `⚡ system prompt updated` as centered badges in chat
- 📐 **Shared prompts** — `app/prompts/base.md` + `orchestrator.md` + `worker.md`, shared platform knowledge

### Fixed
- **Stop deleted logs** — `POST /stop` now calls `unload()` (preserves DB), not `remove()` (cascade)
- **Scroll hijack** — `showWaitingIndicator` respects `wasAtBottom`, no re-creation in refresh loop
- **Context 0%** — usage is dict not object (`.get()` not `getattr()`), last iteration not sum
- **Context 227%** — top-level usage sums all API calls, context = last iteration only
- **Trailing slash** — scope normalized with `rstrip("/")` at creation and lookup
- **Ghost workers** — `kill_worker` for DB-only sessions deletes from DB directly
- **MCP not visible** — `.mcp.json` no longer copied to worktrees (was overriding Orchestra MCP);
  `mcp_stdio.py` invoked by absolute path (was failing with `-m` from non-orchestra CWD)
- **SendMessage vs send_message** — prompts explicitly say `mcp__orchestra__send_message`
- **Interrupt stuck** — now awaits task cancellation, drops client, sets IDLE + persist
- **Newlines lost** — tool input via `json.dumps(indent=2)`, `white-space: pre-wrap` on frontend
- **Lost messages** — SSE user_message replaces pending bubble instead of skipping
- **Prompt injection** — `[SYSTEM UPDATE]` tag softened to `[Orchestra platform note]`
- **Repeated prompt inject** — `system_prompt` synced after inject, no more every-turn spam

### Changed
- **spawn_worker scope** — uses orchestrator's ORCHESTRA_SCOPE, not repo_path (workers visible in list_agents)
- **Prompts split** — old `orchestrator_prompt.md` + `worker_prompt.md` → `prompts/base.md` + role-specific
- **SDK 0.1.74** — updated from 0.1.72

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

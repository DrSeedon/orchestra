# Orchestra v1.0 — Technical Specification

Date: 2026-04-30
Status: DRAFT v4 — post Codex Round 3, all blocking resolved

## Goal

Rewrite Orchestra from MVP (dual Worker/Orchestrator with duplication) into a clean single-class architecture. One way to do everything. Apple-level simplicity.

## Core Decisions (agreed with user)

1. **One class `AgentSession`** — both orchestrator and workers are the same class, different config
2. **Agent definitions = `.md` files** in `.claude/agents/` (global + local). SDK handles discovery natively — no custom scanning, no overrides, no enum roles
3. **Orchestrator = persistent `AgentSession`** with `orchestrator.md` as system_prompt. Auto-starts on server boot, resumes on reboot
4. **Workers are reusable** — stay `idle` after task, get new tasks via inject. Orchestrator decides lifecycle
5. **Worktree = optional**, driven by agent `.md` frontmatter (`isolation: worktree` or none)
6. **Permissions**: all sessions use `permission_mode="default"` + `can_use_tool` auto-approve callback. NOT `bypassPermissions` (known regression: Claude Code issues #36497, #37157, #36923 — protected dirs still prompt, tool calls silently fail). Every auto-approve is logged as audit entry. **Accepted risk**: unconditional auto-approve = full agent autonomy. This is a local dev tool, not multi-tenant. Prompt injection risk acknowledged.
7. **Multiple orchestrators** — one per project (scoped by `cwd`). One dashboard, one server, orchestrator picker in UI
8. **One SQLite database** — `scope` field (cwd) filters data per orchestrator
9. **Callbacks table removed** — everything is a session log entry

## Architecture

```
app/
  main.py           — FastAPI app, ~9 endpoints + dashboard route
  session.py        — AgentSession (single SDK wrapper)
  manager.py        — SessionManager (registry, auto-start orchestrator, persistence)
  workspace.py      — create_worktree / remove_worktree
  db.py             — SQLite (sessions + logs tables)
  templates/
    dashboard.html  — single-screen UI
```

5 Python files. Each does exactly one thing.

## `session.py` — AgentSession

Single class wrapping `ClaudeSDKClient`. No subclasses.

```python
class AgentStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    IDLE = "idle"
    STOPPED = "stopped"
    ERROR = "error"

@dataclass
class AgentSession:
    id: str                             # UUID, primary key everywhere
    name: str                           # human-readable display name
    scope: str                          # cwd of parent orchestrator (or own cwd)
    cwd: str                            # working directory for this session
    model: str = "claude-sonnet-4-6"
    system_prompt: str = ""
    max_turns: int = 50
    status: AgentStatus = AgentStatus.STARTING
    session_id: str | None = None       # SDK session_id for resume
    cost_usd: float = 0.0
    worktree_path: str | None = None    # set if isolation=worktree
    branch: str | None = None           # feat/{scope_slug}/{name}
    created_at: datetime
    is_orchestrator: bool = False       # affects auto-resume on boot

    # SDK internals (not persisted)
    _client: ClaudeSDKClient | None
    _turn_task: asyncio.Task | None     # current background _run_turn task
    _lock: asyncio.Lock                 # one query at a time per session
```

### Concurrency model

Each session has exactly ONE `asyncio.Lock` (`_lock`).

All SDK interaction goes through `_run_turn(message)`:

```python
async def _run_turn(self, message: str) -> None:
    """Single turn: connect (if needed) + query + listen. Owns lock for entire duration."""
    async with self._lock:
        try:
            self._persist()
            self._log("user_message", message)
            if not self._client_connected():
                await self._client.connect()
            await self._client.query(message)
            await self._listen_loop()
        except Exception as e:
            self.status = AgentStatus.ERROR
            self._log("error", str(e))
            self._persist()
            raise
```

Rules:
- `_run_turn()` is the ONLY code path that calls `client.connect()`, `client.query()`, or `_listen_loop()`.
- `_run_turn()` checks connection state and connects if needed (handles both fresh start and IDLE resume).
- Lock is held for the entire turn (connect + query + receive all messages + ResultMessage).
- If `send()` is called while lock is held → raises `RuntimeError("session busy")` (HTTP 409). No queuing.
- `_listen_loop()` sets status `IDLE` after `ResultMessage`. Lock releases when `_run_turn` exits.
- `_turn_task` is always assigned when `_run_turn` is spawned. `stop()` cancels/awaits it.

### Idle → Resume behavior

When `send()` is called on an `IDLE` session:
1. Set `status = RUNNING` synchronously (TOCTOU guard)
2. Disconnect current `_client` (clean shutdown)
3. Create NEW `ClaudeSDKClient(options.resume=self.session_id)` — fresh SDK client, resumed context. Do NOT connect yet.
4. `_turn_task = create_task(_run_turn(message))` — `_run_turn` calls `connect()` inside the lock, then queries, listens

This avoids the unproven assumption that SDK supports re-iterating `receive_messages()` after `ResultMessage`.

### Methods

```python
async def start(self, initial_message: str | None = None) -> None
```
- Validates `cwd` exists and is a directory
- Creates `ClaudeAgentOptions(model=self.model, cwd=self.cwd, max_turns=self.max_turns, permission_mode="default", can_use_tool=_auto_approve, system_prompt=self.system_prompt)`
- If `session_id` set → `options.resume = self.session_id`
- Creates client (does NOT connect — `_run_turn` handles connection inside lock)
- If `initial_message` → `status = RUNNING`, `self._turn_task = create_task(_run_turn(initial_message))`
- If NO `initial_message` → `await self._client.connect()`, status = `IDLE`, persist (ready for send())
- Persists to DB

```python
async def send(self, message: str) -> None
```
- **Atomically** check and transition: if `_lock.locked()` OR `status == RUNNING` → raise `RuntimeError("session busy")` (HTTP 409)
- Set `status = RUNNING` **synchronously before scheduling** (prevents TOCTOU: two simultaneous sends both seeing IDLE)
- If was `IDLE` → reconnect SDK client with resume: disconnect old, create new `ClaudeSDKClient(resume=session_id)`
- `self._turn_task = asyncio.create_task(self._run_turn(message))` — always stored for `stop()` cancellation

```python
async def _listen_loop(self) -> None
```
- Single loop over `client.receive_messages()`
- `AssistantMessage` → log each `TextBlock` as `("text", content)`, each `ToolUseBlock` as `("tool", f"{name}: {input_preview}")`
- `ResultMessage` → save `session_id`, accumulate `cost_usd`, set status `IDLE`, persist, break
- Transient transport error → log, bounded retry (max 3), then `ERROR`
- Protocol/permission error → `ERROR` immediately

```python
async def interrupt(self) -> None
```
- Calls `client.interrupt()`
- Logs `("status", "interrupted")`

```python
async def stop(self) -> None
```
- If `_turn_task` and not done → cancel and await (ensures no orphaned turns survive shutdown)
- Calls `client.disconnect()`
- Sets status `STOPPED`, persists
- If has worktree → `remove_worktree()`

```python
@staticmethod
async def _auto_approve(tool_name, tool_input, _context=None):
    logger.info(f"auto-approve: {tool_name}")
    return PermissionResultAllow(updated_input=tool_input)
```

### What AgentSession does NOT do
- Does NOT create worktrees (that's `workspace.py`)
- Does NOT parse `.md` files (that's `manager.py` — single source of truth for agent config)
- Does NOT manage other sessions

## `workspace.py` — Worktree management

```python
WORKTREE_ROOT = Path(__file__).parent.parent / "worktrees"
PROJECT_FILES = ("CLAUDE.md", ".mcp.json", ".env", ".worktreeinclude")

@dataclass
class Worktree:
    path: str
    branch: str

def create_worktree(repo_path: str, name: str, scope: str) -> Worktree:
    """Create git worktree. Fails loud on error."""
    # Validate inputs
    repo = Path(repo_path).resolve()
    if not repo.is_dir():
        raise ValueError(f"repo_path does not exist: {repo_path}")

    # Scope-namespaced path AND branch to avoid collisions
    scope_slug = _slugify(scope)
    wt_dir = WORKTREE_ROOT / scope_slug
    wt_dir.mkdir(parents=True, exist_ok=True)
    wt_path = wt_dir / name
    branch = f"feat/{scope_slug}/{name}"

    # Never auto-remove existing — must explicitly remove session first
    if wt_path.exists():
        raise ValueError(f"worktree already exists: {wt_path}. Remove session first.")

    result = subprocess.run(
        ["git", "worktree", "add", str(wt_path), "-b", branch],
        cwd=str(repo), capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Branch may already exist — try without -b
        result = subprocess.run(
            ["git", "worktree", "add", str(wt_path), branch],
            cwd=str(repo), capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git worktree add failed: {result.stderr}")

    # Copy project files
    for fname in PROJECT_FILES:
        src = repo / fname
        if not src.exists():
            src = repo.parent / fname
        if src.exists():
            shutil.copy2(str(src), str(wt_path / fname))

    return Worktree(path=str(wt_path), branch=branch)

def remove_worktree(repo_path: str, worktree_path: str) -> None:
    """Remove a specific worktree by its full path."""
    wt = Path(worktree_path)
    if not wt.exists():
        return
    result = subprocess.run(
        ["git", "worktree", "remove", str(wt), "--force"],
        cwd=repo_path, capture_output=True, text=True,
    )
    if result.returncode != 0:
        logger.warning(f"worktree remove failed: {result.stderr}")
```

Key design:
- Path: `worktrees/{scope_slug}/{name}` — no collision between scopes
- Branch: `feat/{scope_slug}/{name}` — no collision in git refs
- Never auto-removes existing worktree — must explicitly remove session first
- `remove_worktree` takes full path, not name (no ambiguity)
- `repo_path` validated before any git operations

## `manager.py` — SessionManager

```python
class SessionManager:
    sessions: dict[str, AgentSession] = {}  # key = session.id (UUID)

    async def create_session(
        self,
        name: str,
        scope: str,
        cwd: str,
        model: str,
        system_prompt: str = "",
        max_turns: int = 50,
        use_worktree: bool = False,
        repo_path: str | None = None,
        is_orchestrator: bool = False,
        initial_message: str | None = None,
    ) -> AgentSession: ...

    async def send(self, session_id: str, message: str) -> None: ...
    async def interrupt(self, session_id: str) -> None: ...
    async def stop(self, session_id: str) -> None: ...
    async def remove(self, session_id: str) -> None: ...

    def get(self, session_id: str) -> AgentSession | None: ...
    def get_by_name(self, name: str, scope: str) -> AgentSession | None: ...
    def list_sessions(self, scope: str | None = None) -> list[dict]: ...
    def stats(self, scope: str | None = None) -> dict: ...

    async def auto_resume_orchestrators(self) -> None: ...
    async def shutdown_all(self) -> None: ...
```

### Key: UUID everywhere internally, name for display

- `sessions` dict keyed by UUID
- `get_by_name(name, scope)` for human-readable lookups
- API endpoints accept `name` in URL but resolve to UUID via `get_by_name`
- No collision possible: two `worker-1` in different scopes = different UUIDs

### `create_session` flow
1. Validate: `cwd` exists, `name` unique within `scope` (check DB)
2. Generate UUID
3. **Persist session as STARTING immediately** (before SDK connect or worktree) — ensures DB has owner record for cleanup
4. If `use_worktree` and `repo_path` → `workspace.create_worktree(repo_path, name, scope)` → update session `cwd` and `worktree_path`
5. Create `AgentSession` with all params
6. `await session.start(initial_message)` — wrapped in try/except: on failure, cleanup worktree if created, mark session ERROR
7. Store in `self.sessions[session.id]`

### `auto_resume_orchestrators` (called on server startup)
1. Query DB: `is_orchestrator=1 AND session_id IS NOT NULL AND status IN ('running', 'idle')`
2. Validate each: `cwd` still exists
3. Mark stale non-orchestrator `running` sessions as `error` (crashed during previous run)
4. For each valid orchestrator: create `AgentSession` with saved `session_id`, call `start()` (SDK resumes)
5. Log what was resumed / what was marked stale

### Agent `.md` config resolution
Manager is the single source of truth for agent config. When creating a session from an agent definition:
1. Manager reads the `.md` file
2. Parses frontmatter: `model`, `isolation`, any other fields
3. Passes extracted values as parameters to `create_session()`
4. `AgentSession` receives flat config — knows nothing about `.md` files

### `list_sessions`
- Returns active in-memory sessions merged with DB history
- If `scope` provided → filter by scope
- Active sessions take priority over DB records (same UUID)

## `db.py` — SQLite

Two tables only. All functions are sync — manager wraps in `asyncio.to_thread()`.

### Connection management

```python
def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
```

PRAGMAs set on EVERY connection (SQLite requires this — they are per-connection, not per-database).

### Schema

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,              -- UUID
    name TEXT NOT NULL,
    scope TEXT NOT NULL,
    cwd TEXT NOT NULL,
    model TEXT NOT NULL,
    system_prompt TEXT DEFAULT '',
    max_turns INTEGER DEFAULT 50,
    status TEXT DEFAULT 'starting',
    session_id TEXT,                   -- SDK session_id for resume
    cost_usd REAL DEFAULT 0.0,
    worktree_path TEXT,
    branch TEXT,
    is_orchestrator INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(name, scope)               -- human-readable uniqueness
);

CREATE TABLE logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,                -- text | tool | error | status | user_message | notification
    content TEXT NOT NULL
);
CREATE INDEX idx_logs_session ON logs(session_id, id DESC);
CREATE INDEX idx_sessions_scope ON sessions(scope, is_orchestrator, status);
```

Key design:
- UUID PK + `UNIQUE(name, scope)` for display
- `ON DELETE CASCADE` on logs FK — deleting session deletes its logs
- `PRAGMA foreign_keys=ON` per connection (required by SQLite)
- `PRAGMA busy_timeout=5000` per connection
- `notification` in log type list

### Functions
```python
def init_db() -> None                                    # called in lifespan, NOT at import
def save_session(session: AgentSession) -> None          # UPSERT — see below
def get_session(session_id: str) -> dict | None
def get_session_by_name(name: str, scope: str) -> dict | None
def get_all_sessions(scope: str | None = None) -> list[dict]
def delete_session(session_id: str) -> None              # CASCADE deletes logs
def add_log(session_id: str, ts: datetime, type: str, content: str) -> int  # returns log.id
def get_logs(session_id: str, after_id: int = 0, limit: int = 200) -> list[dict]  # cursor-based
def get_stats(scope: str | None = None) -> dict
def get_orchestrators() -> list[dict]                    # for auto-resume
def mark_stale_sessions(exclude_ids: list[str]) -> int   # running→error for crashed sessions
```

### save_session uses UPSERT with ALL mutable fields
```sql
INSERT INTO sessions (id, name, scope, cwd, model, system_prompt, max_turns,
    status, session_id, cost_usd, worktree_path, branch, is_orchestrator,
    created_at, finished_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET
    status=excluded.status,
    session_id=excluded.session_id,
    cost_usd=excluded.cost_usd,
    worktree_path=excluded.worktree_path,
    branch=excluded.branch,
    cwd=excluded.cwd,
    finished_at=excluded.finished_at
```
Updates all fields that can change post-creation: status, session_id, cost, worktree_path, branch, cwd, finished_at. Immutable fields (name, scope, model, system_prompt, max_turns, is_orchestrator, created_at) are not updated.

## `main.py` — API

```python
@asynccontextmanager
async def lifespan(app):
    init_db()
    await manager.auto_resume_orchestrators()
    yield
    await manager.shutdown_all()

# === Sessions ===
GET    /                                    → dashboard.html
GET    /api/sessions?scope=...              → list sessions (optional scope filter)
POST   /api/sessions                        → create session (Pydantic model)
GET    /api/sessions/{name}?scope=...       → session detail (metadata)
GET    /api/sessions/{name}/logs?scope=...&after_id=0  → cursor-based logs
POST   /api/sessions/{name}/send            → {message, scope}
POST   /api/sessions/{name}/interrupt       → {scope}
DELETE /api/sessions/{name}?scope=...       → stop + remove

# === Meta ===
GET    /api/stats?scope=...                 → stats filtered by scope
GET    /api/orchestrators                   → list all orchestrator sessions (for UI picker)
```

9 endpoints. One resource. Separate `/logs` endpoint for cursor-based polling.

### Request validation
- `POST /api/sessions` uses Pydantic `CreateSessionRequest` model
- `cwd` validated: must exist, must be directory
- `repo_path` validated if `use_worktree=True`: must exist, must be git repo (`git rev-parse --show-toplevel`)
- `name` validated: `^[a-zA-Z0-9][a-zA-Z0-9._-]{0,49}$`
- On validation failure: 422 with clear error message

### Error responses
- 404: session not found
- 409: session name already exists in scope / session busy (RUNNING)
- 422: validation error
- 500: internal error with logged traceback

No `{"ok": false}`. HTTP status codes only.

## `dashboard.html` — Single Screen

### Layout
```
┌─────────────────────────────────────────────────────────────┐
│ 🎼 Orchestra    [Orchestrator: Parsing ▼]    ● connected    │
├────────────────────────────────────┬────────────────────────┤
│                                    │  Workers               │
│   Chat with Orchestrator           │  ┌──────────────────┐  │
│                                    │  │ worker-1  ● run  │  │
│   [orchestrator thinking...]       │  │ task: fix auth    │  │
│   [tool: Bash: git status]         │  │ $0.12 │ 3m ago   │  │
│   [orchestrator response text]     │  └──────────────────┘  │
│   [user message]                   │  ┌──────────────────┐  │
│   [orchestrator response]          │  │ researcher ● idle│  │
│                                    │  │ task: analyze...  │  │
│                                    │  └──────────────────┘  │
│                                    │                        │
│                                    │  Click worker → expand │
│                                    │  with logs + inject    │
├────────────────────────────────────┴────────────────────────┤
│ [Send message to orchestrator...]                    [Send] │
└─────────────────────────────────────────────────────────────┘
```

### Rendering contract
- **No innerHTML with server data** — all dynamic content via `textContent` or `<template>` + `dataset`
- **No inline JS event handlers** — `addEventListener` only
- Worker cards created via DOM API, name stored in `dataset.name`
- XSS-safe by construction

### Polling contract
- **One `setInterval(refresh, 2000)`** — single polling loop
- `refresh()` calls `GET /api/sessions/{orchestrator}/logs?scope=X&after_id={lastLogId}` for chat
- `refresh()` calls `GET /api/sessions?scope={scope}` for worker list
- **Cursor-based log loading**: `after_id` param → only new logs fetched, appended to DOM
- **AbortController**: each refresh cancels previous in-flight request (no overlap)
- **Bounded DOM**: max 500 log entries in chat, oldest removed when exceeded
- **No separate notification polling** — notifications are log entries, rendered in chat

### Orchestrator picker
- On load: `GET /api/orchestrators` → populate dropdown
- On change: update `scope`, clear chat, reset `lastLogId`, refresh

## Test Plan

### Approach: TDD for data/logic, integration for SDK

```
tests/
  test_db.py          — TDD: schema, CRUD, cursor, cascade, scope
  test_workspace.py   — TDD: git worktree create/remove/errors (temp repos)
  test_session.py     — async: state machine, lock, TOCTOU, cancel (mock SDK)
  test_manager.py     — create flow, cleanup on failure, resume logic (mock session)
  test_api.py         — TestClient: endpoints, validation, HTTP status codes
```

### `test_db.py` — SQLite (TDD, in-memory DB)
- `test_init_creates_tables` — tables exist after init
- `test_save_and_get_session` — round-trip save → get
- `test_unique_name_scope` — two sessions same (name, scope) → IntegrityError
- `test_same_name_different_scope` — two "worker-1" in different scopes coexist
- `test_upsert_updates_mutable_only` — status/cost change, name/scope/created_at preserved
- `test_get_all_sessions_scope_filter` — scope=X returns only X sessions
- `test_delete_cascades_logs` — delete session → its logs gone
- `test_add_log_returns_id` — monotonically increasing
- `test_get_logs_cursor` — after_id=5 returns only logs with id>5
- `test_get_logs_limit` — limit=10 returns max 10
- `test_get_orchestrators` — only is_orchestrator=1 with session_id and valid status
- `test_mark_stale_sessions` — running non-orchestrators → error
- `test_get_stats` — counts and cost aggregation

### `test_workspace.py` — Worktree (TDD, temp git repos)
- `test_create_worktree_success` — creates dir, branch, copies files
- `test_create_worktree_copies_project_files` — CLAUDE.md, .mcp.json present
- `test_create_worktree_copies_from_parent` — fallback to parent dir for files
- `test_create_worktree_scope_namespaced` — path is worktrees/{slug}/{name}
- `test_create_worktree_branch_scoped` — branch is feat/{slug}/{name}
- `test_create_worktree_exists_raises` — ValueError if path exists
- `test_create_worktree_bad_repo_raises` — ValueError if repo_path not dir
- `test_create_worktree_git_fail_raises` — RuntimeError with stderr
- `test_create_worktree_existing_branch` — reuses branch without -b
- `test_remove_worktree_success` — dir removed
- `test_remove_worktree_nonexistent` — no error
- `test_remove_worktree_git_fail_warns` — logs warning, no exception

### `test_session.py` — State machine + concurrency (async, mock SDK client)
- `test_start_no_message_goes_idle` — start(None) → IDLE
- `test_start_with_message_goes_running` — start("task") → RUNNING
- `test_send_idle_goes_running` — send on IDLE → RUNNING
- `test_send_running_raises` — send on RUNNING → RuntimeError
- `test_send_stopped_raises` — send on STOPPED → error
- `test_listen_result_goes_idle` — ResultMessage → IDLE, cost accumulated
- `test_listen_error_goes_error` — exception → ERROR
- `test_stop_cancels_turn_task` — _turn_task cancelled and awaited
- `test_stop_disconnects_client` — client.disconnect() called
- `test_concurrent_send_second_gets_409` — two sends, second raises
- `test_idle_resume_creates_new_client` — old disconnected, new with resume
- `test_auto_approve_logs` — logger.info called with tool name

### `test_manager.py` — SessionManager (mock AgentSession)
- `test_create_session_generates_uuid` — id is valid UUID
- `test_create_session_validates_cwd` — nonexistent cwd → ValueError
- `test_create_session_unique_name_scope` — duplicate → 409
- `test_create_session_with_worktree` — workspace.create called
- `test_create_session_persists_starting` — DB has STARTING before SDK
- `test_create_failure_cleans_worktree` — SDK fail → worktree removed, ERROR in DB
- `test_send_routes_to_session` — message forwarded
- `test_stop_and_remove` — session stopped, removed from dict and DB
- `test_list_sessions_merges_active_and_db` — active overrides DB
- `test_auto_resume_only_valid_orchestrators` — filters by status/session_id/cwd
- `test_auto_resume_marks_stale` — crashed workers → error

### `test_api.py` — HTTP endpoints (TestClient)
- `test_create_session_201` — valid request → 201
- `test_create_session_422_bad_name` — invalid chars → 422
- `test_create_session_409_duplicate` — same name+scope → 409
- `test_get_sessions_scope_filter` — ?scope=X works
- `test_get_session_404` — nonexistent → 404
- `test_send_409_busy` — send to RUNNING → 409
- `test_logs_cursor` — after_id pagination works
- `test_delete_session` — removes and cleans up
- `test_orchestrators_endpoint` — returns only orchestrators

## Migration Path

### Order of implementation
1. `workspace.py` — standalone, no dependencies
2. `db.py` — new schema, `init_db()` called in lifespan (not import)
3. `session.py` — `AgentSession` using new `db.py` and `workspace.py`
4. `manager.py` — `SessionManager` using `AgentSession`
5. `main.py` — new API endpoints
6. `dashboard.html` — new single-screen UI
7. Delete `worker.py`, `orchestrator.py`, old `data/orchestrator_session` file

### Data migration
Old `orchestra.db` has different schema. Back up to `orchestra.db.bak`, start fresh. **Note: this is destructive** — loses runtime logs, cost data, and session_ids. This is acceptable for a v0→v1 rewrite of a local dev tool with 12 commits of history.

### What to preserve
- `worktrees/` directory structure and `.gitignore`
- Concept of session resume via `session_id`
- Auto-approve permission pattern (from Kesha, proven)

## What's NOT in scope
- SSE/WebSocket (polling is fine for dev dashboard)
- Authentication (local tool)
- Multiple dashboard instances
- Agent `.md` file management in UI (orchestrator creates them via filesystem)
- Worker-to-worker communication (always through orchestrator)
- Tool deny/allow policy (intentional: full autonomy for local dev agents — accepted risk, see Core Decision #6)

## Resolved Questions (from Codex Rounds 1-2)

1. **PK**: UUID as primary key. `UNIQUE(name, scope)` for human-readable constraint.
2. **`_listen_loop` errors**: bounded retry (max 3) for transient transport errors. Protocol/permission errors → `ERROR` immediately.
3. **Idle resume**: disconnect + new `ClaudeSDKClient(resume=session_id)`. No reuse of finished client.
4. **Race condition**: `_run_turn()` helper owns `asyncio.Lock` for entire turn. `send()` on locked session raises 409. One listener, one query at a time. Lock released in `finally` block — no orphaned locks.
5. **`start(None)` status**: connects and goes `IDLE`. Only `start(message)` enters `RUNNING` via `_run_turn()`.
6. **Orphan worktrees**: session persisted as `STARTING` before SDK connect. On failure → cleanup worktree, mark `ERROR`.
7. **SQLite PRAGMAs**: `busy_timeout`, `journal_mode=WAL`, `foreign_keys=ON` set per-connection in `_conn()`.
8. **FK cascade**: `ON DELETE CASCADE` on logs. `delete_session()` cleans up everything.
9. **API logs endpoint**: separate `GET /api/sessions/{name}/logs?after_id=` for cursor-based polling.
10. **Branch collision**: branch = `feat/{scope_slug}/{name}`, not just `feat/{name}`.
11. **UPSERT fields**: all mutable fields updated explicitly. Immutable fields preserved.
12. **TOCTOU in `send()`**: status set to `RUNNING` synchronously before scheduling `_run_turn`. Second concurrent `send()` sees `RUNNING` and returns 409.
13. **`_turn_task` tracking**: renamed from `_listen_task`. Always assigned when `_run_turn` spawned. `stop()` cancels and awaits it — no orphaned turns.
14. **`_run_turn()` connects**: `_run_turn()` calls `_client_connected()` check + `connect()` inside the lock. Handles both fresh start and IDLE resume paths uniformly.

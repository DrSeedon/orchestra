# Plan: Orchestra Architecture Refactoring (4 steps)

**Task:** #47
**Based on:** debate-report.md consensus

## Step 1: `app/prompting.py` — extract pure prompt helpers

### Problem
`manager.py` has ~170 LOC of prompt file/template logic mixed with session CRUD.
`session.py:251` has lazy import `from app.manager import _prompt_template_hash` — circular dependency smell.

### What moves to `app/prompting.py`

Pure functions (read files, return strings, no DB/runtime state):

| Function | Lines in manager.py | Dependencies |
|---|---|---|
| `_parse_role_frontmatter()` | 96-109 | yaml |
| `_load_modules()` | 115-123 | pathlib |
| `_role_prompt_file()` | 126-146 | `is_orchestrator_role`, `_parse_role_frontmatter`, `_load_modules` |
| `_role_can_spawn()` | 153-169 | `_parse_role_frontmatter` |
| `_skills_catalog()` | 172-184 | `_parse_role_frontmatter` |
| `get_role_icons()` | 187-198 | `_parse_role_frontmatter` |
| `_roles_catalog()` | 201-229 | `_parse_role_frontmatter` |
| `_prompt_template_hash()` | 258-267 | `_read_prompt`, `_role_prompt_file` |
| `_read_prompt()` | 49-51 | pathlib |
| `_safe_format_prompt()` | 44-46 | re |
| `_inject_skills_to_worktree()` | 270-289 | `_parse_role_frontmatter`, shutil |
| Constants: `_PROMPTS_DIR`, `_MODULES_DIR`, `_SKILLS_DIR`, `_IDENTITY_PLACEHOLDERS` | 39,112,149,41 | pathlib, re |

### Import cycle fix

**Problem:** `_role_prompt_file()` calls `is_orchestrator_role()` which lives in `session.py`.
If `prompting.py` imports from `session.py` and `session.py` imports from `prompting.py` → cycle.

**Solution:** Move `is_orchestrator_role()` and `_ORCHESTRATOR_ROLES` to `prompting.py`.
- `session.py` imports `is_orchestrator_role` from `prompting.py` (not the other way around)
- `manager.py` imports `is_orchestrator_role` from `prompting.py`
- `main.py:1099` — update lazy import to `from app.prompting import is_orchestrator_role`

This is safe because `is_orchestrator_role` is a pure function (frozenset lookup), no runtime deps.

### What stays in `manager.py`

Dynamic blocks that read DB/sessions:
- `_other_orchestrators_block()` — reads `get_all_sessions()`
- `_workers_block()` — reads `get_all_sessions()`
- `ROLE_SYSTEM_PROMPT()` — composes static + dynamic, stays in manager
- `ORCHESTRATOR_SYSTEM_PROMPT()` — wrapper, stays
- `WORKER_SYSTEM_PROMPT()` — wrapper, stays

### Import graph after change
```
prompting.py  (pure: files, strings, no DB)
    ↑ imports from
session.py    (is_orchestrator_role, _prompt_template_hash)
    ↑ imports from
manager.py    (AgentSession, AgentStatus + prompt helpers from prompting)
main.py       (get_role_icons from prompting, _read_prompt from prompting)
```

No cycles. `prompting.py` imports nothing from `app.*`.

---

## Step 2: `app/backend_protocol.py` — BackendLike Protocol

### Design
```python
from typing import Protocol, AsyncIterator, Optional, runtime_checkable
from app.events import AgentEvent

class BackendLike(Protocol):
    @property
    def session_id(self) -> Optional[str]: ...
    async def connect(self) -> None: ...
    async def send(self, message: str) -> None: ...
    async def events(self) -> AsyncIterator[AgentEvent]: ...
    async def interrupt(self) -> None: ...
    async def disconnect(self) -> None: ...
```

Optional methods (not in Protocol, checked via hasattr at call site):
- `reconnect()` — Claude only
- `context_usage()` — Claude only

### Changes
- `session.py`: `_backend: Optional[object]` → `_backend: BackendLike | None` (import from backend_protocol)
- No changes to backend_claude.py or backend_codex.py — they already satisfy the Protocol structurally

---

## Step 3: Extract-methods in `_handle_turn_end()`

### Current structure (session.py:467-542)
75 lines, 12+ side effects in strict order.

### Proposed decomposition (all private methods of AgentSession)

```python
def _handle_turn_end(self, event: AgentEvent) -> None:
    meta = event.metadata
    self._turn_start = 0
    ok, sr, nt = self._apply_turn_result(meta)

    self._update_context_from_turn(meta)
    self._spawn_bg(self._refresh_context_from_api())

    if not ok:
        errors = meta.get("errors") or []
        err_txt = "; ".join(str(e) for e in errors) if errors else sr
        self._log("error", f"turn FAILED: {err_txt}")

    # EARLY RETURN — max_turns auto-continue (MUST stay before IDLE/WAITING)
    if sr in ("error_max_turns", "max_turns") and ok:
        self._log("status", f"max_turns reached ({nt}), auto-continuing")
        self._spawn_bg(self._auto_continue())
        return

    cost = meta.get("cost_usd", 0)
    live_pct = self._last_context.get("percentage", 0)
    ctx_s = f"ctx:{live_pct}%" if live_pct else ""
    self._log("status", f"turn ended ({sr}, {nt} turns, ${cost:.2f} {ctx_s})")

    self._finish_turn_status()
    # _persist() called inside _finish_turn_status — MUST happen before after-turn actions
    self._after_turn_idle_actions(live_pct)
```

### Helper methods

```python
def _apply_turn_result(self, meta: dict) -> tuple[bool, str, int]:
    """Update session_id, costs, token totals from turn metadata."""
    ok = meta.get("ok", True)
    sr = meta.get("stop_reason", "unknown")
    nt = meta.get("num_turns", 0)
    self._last_turn_ok = ok
    self._last_stop_reason = sr

    sid = meta.get("session_id")
    if sid and sid != self.session_id:
        self._last_cost = 0.0
        self._last_cost_cached = 0.0
    if sid:
        self.session_id = sid
    new_cost = meta.get("cost_usd", 0)
    self.cost_usd += max(0, new_cost - self._last_cost)
    self._last_cost = new_cost
    new_cost_cached = meta.get("cost_usd_cached", 0)
    self.cost_usd_cached += max(0, new_cost_cached - self._last_cost_cached)
    self._last_cost_cached = new_cost_cached
    self.total_turns += nt
    self.total_input_tokens += meta.get("input_tokens", 0)
    self.total_output_tokens += meta.get("output_tokens", 0)
    return ok, sr, nt

def _update_context_from_turn(self, meta: dict) -> None:
    """Update context window stats from turn metadata."""
    ctx_pct = meta.get("context_pct", 0)
    ctx_tokens = meta.get("context_tokens", 0)
    if ctx_pct:
        self._last_context["percentage"] = ctx_pct
        self._last_context["total_tokens"] = ctx_tokens
    self._last_context["max_tokens"] = meta.get("max_tokens", 200000)
    self._last_context["cache_hit"] = meta.get("cache_hit", 0)
    self._last_context["cache_read"] = meta.get("cache_read", 0)
    self._last_context["cache_create"] = meta.get("cache_create", 0)

def _finish_turn_status(self) -> None:
    """Set IDLE or WAITING based on bg jobs, then persist."""
    from app.bg_jobs import bg_manager
    if bg_manager and bg_manager.has_active_jobs(self.id):
        self.status = AgentStatus.WAITING
        self._log("status", "waiting for bg jobs")
    else:
        self.status = AgentStatus.IDLE
    self._persist()

def _after_turn_idle_actions(self, live_pct: int) -> None:
    """Post-turn actions: compact ack, scope idle, auto-compact, auto-report, flush/hibernate."""
    if self._compact_ack_event is not None and self._turn_gen == self._compact_ack_gen:
        self._compact_ack_event.set()

    self._spawn_bg(self._notify_scope_idle())

    if live_pct > 90 and not self.is_orchestrator and not self._compacting:
        self._log("status", f"auto-compact triggered ({live_pct}%)")
        self._spawn_bg(self._auto_compact())

    self._fire_auto_report()

    if self._pending_messages:
        self._spawn_bg(self._flush_pending())
        return

    self._schedule_hibernate()
```

### Invariants preserved
1. Early return for `max_turns` → BEFORE `_finish_turn_status()` (no IDLE/WAITING set)
2. `_persist()` → INSIDE `_finish_turn_status()`, BEFORE `_after_turn_idle_actions()`
3. No helper calls `_persist()` except `_finish_turn_status()`
4. All helpers are sync (no async), same class, same field access

---

## Step 4: main.py split — `deps.py` + routers

### Phase 4a: `app/deps.py`

```python
"""Shared dependencies for routers — avoids importing from main."""
from app.manager import SessionManager

manager = SessionManager()
```

`main.py` changes: `manager = SessionManager()` → `from app.deps import manager`

### Phase 4b: `app/routes/tm.py` (Task Manager routes)

Move from main.py:
- `TmTaskCreate`, `TmTaskUpdate`, `TmPaymentReceive` models (lines 1288-1314)
- `_resolve_client_id()` (lines 1373-1384)
- All `/api/tm/*` endpoints (lines 1316-1449)
- ~165 LOC

### Phase 4c: `app/routes/bg.py` (Background Jobs routes)

Move from main.py:
- `BgJobCreateRequest` model (lines 1454-1461)
- All `/api/bg/*` endpoints (lines 1463-1496)
- ~45 LOC

### Phase 4d: `app/routes/proxy.py` (Proxy routes)

Move from main.py:
- `/api/proxy/*` and `/api/tunnel/*` endpoints (lines 1632-1655)
- ~25 LOC

### Phase 4e: `app/routes/files.py` (File operations)

Move from main.py:
- `_get_allowed_roots()`, `_is_safe_path()`, `_encode_path()`, `_build_path_map()` (lines 201-299)
- `/api/files/*`, `/api/open-file`, `/api/open-folder` (lines 300-375)
- `/api/upload`, `/uploads/*` (lines 1166-1199)
- ~160 LOC

### NOT moving (stays in main.py):
- Session endpoints (most complex, tight manager coupling)
- SSE streaming
- Auth middleware
- Lifespan
- Webhook (own logger setup)
- Git status cache + endpoint

### Expected result:
- main.py: ~1655 → ~1260 LOC (cut ~395)
- New files: deps.py (~5), routes/tm.py (~165), routes/bg.py (~45), routes/proxy.py (~25), routes/files.py (~160)

---

## Execution order

1. Step 1 (`prompting.py`) — breaks circular dep, pure file move
2. Step 2 (`backend_protocol.py`) — independent, tiny
3. Step 3 (`_handle_turn_end`) — depends on Step 1 (clean imports)
4. Step 4a-4e (`deps.py` + routers) — last, largest surface area

Each step: implement → codex-debate on diff → fix → commit.

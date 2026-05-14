# Implementation Plan: CodexBackend for Orchestra

**Date**: 2026-05-14  
**Based on**: `codex-migration.md` (verified research)  
**Scope**: Add Codex CLI as alternative backend, keep Claude as default  
**Target**: 7-10 working days

---

## 1. AgentEvent — Unified Event Model

New file: `app/events.py`

```python
from dataclasses import dataclass, field

@dataclass
class AgentEvent:
    type: str
    content: str = ""
    metadata: dict = field(default_factory=dict)

# type values:
# "text"           — agent text output (content = text)
# "tool_use"       — tool invocation (content = "tool_name: input_summary")
# "tool_result"    — tool output (content = result text)
# "file_change"    — file edit (content = "add /path/to/file" or "update ...")
# "turn_end"       — turn completed (metadata = {session_id, cost_usd, input_tokens, ...})
# "error"          — error (content = error message)
# "status"         — lifecycle event (content = description)
# "subagent_start" — sub-agent spawned (content = description)
# "subagent_progress" — sub-agent working (content = description)
# "subagent_end"   — sub-agent finished (content = description)
```

No class hierarchy. No inheritance. One flat dataclass with a string `type` discriminator. The `metadata` dict carries backend-specific data without leaking types.

---

## 2. AgentBackend — Protocol

New file: `app/backend.py`

```python
from typing import Protocol, AsyncIterator, Optional

class AgentBackend(Protocol):
    async def connect(self) -> None: ...
    async def send(self, message: str) -> None: ...
    async def events(self) -> AsyncIterator[AgentEvent]: ...
    async def interrupt(self) -> None: ...
    async def disconnect(self) -> None: ...
    
    @property
    def session_id(self) -> Optional[str]: ...
```

Minimal surface. No `resume` method — resume is a construction-time concern (you pass `session_id` to constructor, backend handles it internally). No `change_model` — disconnect + create new backend.

---

## 3. ClaudeBackend — Extract from session.py

New file: `app/backend_claude.py`

Extract the Claude-specific logic from `session.py` into a class implementing `AgentBackend`:

### What moves out of `session.py`:

| Current location | What | Destination |
|---|---|---|
| Lines 10-25 | `from claude_agent_sdk import ...` | `backend_claude.py` |
| Lines 42-49 | `_auto_approve()` | `backend_claude.py` |
| Lines 53-69 | `_extract_tool_result()` | `backend_claude.py` |
| Lines 109-125 | `_make_client()` | `ClaudeBackend.__init__` / `connect()` |
| Lines 157-172 | `_ensure_client()` | `ClaudeBackend.connect()` |
| Lines 174-306 | `_persistent_listen()` | `ClaudeBackend.events()` — yields `AgentEvent` instead of raw SDK types |
| Lines 347-380 | `_heartbeat_loop()` | `ClaudeBackend._heartbeat_loop()` |
| Lines 384-391 | `interrupt()` | `ClaudeBackend.interrupt()` |
| Lines 500-519 | `_disconnect_client()` | `ClaudeBackend.disconnect()` |

### What stays in `session.py`:

| Lines | What | Why |
|---|---|---|
| 72-106 | `AgentSession` dataclass fields | Session = metadata container, backend-agnostic |
| 127-155 | `start()`, `send()` | Delegation to backend |
| 308-340 | `_poll_bg_outputs()`, `_on_task_done()` | Session-level concerns, not backend |
| 394-461 | `compact()` | Uses backend internally but orchestrates multiple steps |
| 463-476 | `_notify_scope_idle()`, `_auto_compact()` | Session lifecycle, not backend |
| 488-498 | `change_model()` | Session-level operation |
| 521-560 | `stop()`, `_persist()`, `_log()`, `_to_db_dict()`, `to_dict()` | Persistence layer |

### ClaudeBackend implementation sketch:

```python
class ClaudeBackend:
    def __init__(self, model: str, cwd: str, system_prompt: str = "",
                 resume_session_id: str | None = None,
                 mcp_servers: dict | None = None):
        self.model = model
        self.cwd = cwd
        self.system_prompt = system_prompt
        self._resume_id = resume_session_id
        self._mcp_servers = mcp_servers
        self._client: ClaudeSDKClient | None = None
        self._session_id: str | None = resume_session_id
    
    async def connect(self) -> None:
        self._client = self._make_client()
        await asyncio.wait_for(self._client.connect(), timeout=60)
    
    async def send(self, message: str) -> None:
        await self._client.query(message)
    
    async def events(self) -> AsyncIterator[AgentEvent]:
        async for msg in self._client.receive_messages():
            for event in self._convert(msg):
                yield event
    
    async def interrupt(self) -> None:
        if self._client:
            await self._client.interrupt()
    
    async def disconnect(self) -> None:
        if self._client:
            await self._client.disconnect()
            self._client = None
    
    @property
    def session_id(self) -> str | None:
        return self._session_id
    
    def _convert(self, msg) -> list[AgentEvent]:
        # All the isinstance() checks from current _persistent_listen(),
        # but returning AgentEvent instead of directly logging
        ...
```

The `_convert` method translates `AssistantMessage`, `ResultMessage`, `ToolUseBlock`, etc. into `AgentEvent`. This is the bulk of the refactoring work.

---

## 4. CodexBackend — New Implementation

New file: `app/backend_codex.py`

```python
import asyncio
import json
import shutil
from typing import AsyncIterator, Optional
from app.events import AgentEvent

CODEX_BIN = shutil.which("codex") or "/home/maxim/.npm-global/bin/codex"

# Codex model context windows (from session_meta in JSONL)
CODEX_CONTEXT_LIMITS = {
    "gpt-5.5": 258400,
    "gpt-5.4": 258400,
    "gpt-5.4-mini": 258400,
}

# Codex API token prices (for cost estimation when on API mode)
CODEX_TOKEN_PRICES = {
    "gpt-5.5":      {"input": 1.25, "output": 10.0},
    "gpt-5.4":      {"input": 0.625, "output": 3.75},
    "gpt-5.4-mini": {"input": 0.1875, "output": 1.13},
}


class CodexBackend:
    def __init__(self, model: str, cwd: str, system_prompt: str = "",
                 resume_thread_id: str | None = None):
        self.model = model
        self.cwd = cwd
        self.system_prompt = system_prompt
        self._thread_id: str | None = resume_thread_id
        self._proc: asyncio.subprocess.Process | None = None
        self._cumulative_input_tokens: int = 0
    
    async def connect(self) -> None:
        pass  # No persistent connection — subprocess per turn
    
    async def send(self, message: str) -> None:
        # Build command
        cmd = [CODEX_BIN]
        if self._thread_id:
            cmd += ["exec", "resume", "--json", self._thread_id, message]
        else:
            cmd += ["exec", "--json", "-m", self.model,
                    "--sandbox", "workspace-write",
                    "-C", self.cwd]
            if self.system_prompt:
                escaped = self.system_prompt.replace('"', '\\"').replace('\n', '\\n')
                cmd += ["-c", f'developer_instructions="{escaped}"']
            cmd.append(message)
        
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._build_env(),
        )
    
    async def events(self) -> AsyncIterator[AgentEvent]:
        if not self._proc or not self._proc.stdout:
            return
        
        async for raw_line in self._proc.stdout:
            line = raw_line.decode("utf-8").rstrip("\n")
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            etype = event.get("type", "")
            
            if etype == "thread.started":
                self._thread_id = event["thread_id"]
                yield AgentEvent("status", f"codex thread={self._thread_id}")
            
            elif etype == "item.completed":
                item = event.get("item", {})
                itype = item.get("type", "")
                
                if itype == "agent_message":
                    yield AgentEvent("text", item.get("text", ""))
                
                elif itype == "command_execution":
                    cmd_str = item.get("command", "")
                    yield AgentEvent("tool_use", f"Bash: {cmd_str}")
                    output = item.get("aggregated_output", "")
                    exit_code = item.get("exit_code")
                    yield AgentEvent("tool_result", output,
                                     metadata={"exit_code": exit_code})
                
                elif itype == "file_change":
                    changes = item.get("changes", [])
                    desc = ", ".join(f"{c.get('kind','')} {c.get('path','')}" for c in changes)
                    yield AgentEvent("file_change", desc)
                
                elif itype == "mcp_tool_call":
                    server = item.get("server", "")
                    tool = item.get("tool", "")
                    args = json.dumps(item.get("arguments", {}), ensure_ascii=False)
                    yield AgentEvent("tool_use", f"{server}__{tool}: {args[:200]}")
                    result = item.get("result")
                    if result:
                        content = result.get("content", [])
                        text = "\n".join(
                            b.get("text", str(b)) for b in content if isinstance(b, dict)
                        ) if content else str(result)
                        yield AgentEvent("tool_result", text[:2000])
                    error = item.get("error")
                    if error:
                        yield AgentEvent("error", error.get("message", str(error)))
                
                elif itype == "error":
                    yield AgentEvent("error", item.get("message", ""))
            
            elif etype == "item.started":
                item = event.get("item", {})
                itype = item.get("type", "")
                if itype == "command_execution":
                    yield AgentEvent("tool_use", f"Bash: {item.get('command', '')}")
            
            elif etype == "turn.completed":
                usage = event.get("usage", {})
                input_t = usage.get("input_tokens", 0)
                cached_t = usage.get("cached_input_tokens", 0)
                output_t = usage.get("output_tokens", 0)
                self._cumulative_input_tokens = input_t
                
                ctx_window = CODEX_CONTEXT_LIMITS.get(self.model, 258400)
                context_pct = int(input_t * 100 / ctx_window) if ctx_window else 0
                
                prices = CODEX_TOKEN_PRICES.get(self.model, {"input": 0, "output": 0})
                cost = (input_t * prices["input"] + output_t * prices["output"]) / 1_000_000
                
                yield AgentEvent("turn_end", "", metadata={
                    "session_id": self._thread_id,
                    "input_tokens": input_t,
                    "cached_input_tokens": cached_t,
                    "output_tokens": output_t,
                    "cost_usd": cost,
                    "context_pct": context_pct,
                    "context_tokens": input_t,
                    "max_tokens": ctx_window,
                })
            
            elif etype == "turn.failed":
                error = event.get("error", {})
                yield AgentEvent("error", error.get("message", "turn failed"))
        
        await self._proc.wait()
        self._proc = None
    
    async def interrupt(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()
    
    async def disconnect(self) -> None:
        await self.interrupt()
    
    @property
    def session_id(self) -> str | None:
        return self._thread_id
    
    def _build_env(self) -> dict:
        import os
        env = dict(os.environ)
        env.pop("HTTPS_PROXY", None)
        env.pop("HTTP_PROXY", None)
        return env
```

### Key design decisions:

1. **No persistent process** — new `codex exec --json` subprocess per `send()`. Resume via `codex exec resume --json <thread_id>`. Simpler, works today.

2. **`events()` is a one-shot generator** — yields events for current turn, then returns when process exits. `session.py` calls `send()` then iterates `events()` for each turn.

3. **Cost estimation** — Codex on subscription doesn't report real cost. We estimate from token prices for dashboard display. These are "virtual" costs (same as Claude subscription).

4. **No proxy** — Codex authenticates via ChatGPT OAuth, doesn't need our Hiddify proxy. Strip HTTPS_PROXY from env.

5. **MCP via config.toml** — Codex workers load MCP servers from `~/.codex/config.toml`. We'll add Orchestra MCP entry per-worker project config, or use global config since all workers need Orchestra MCP.

---

## 5. AgentSession Refactoring

### Changes to `app/session.py`:

**Remove**: All `claude_agent_sdk` imports and direct SDK usage.

**Add**: Backend factory and event consumption loop.

```python
# session.py — after refactoring

from app.events import AgentEvent
from app.backend import AgentBackend

# No more claude_agent_sdk imports at top level

@dataclass
class AgentSession:
    # ... existing fields ...
    backend_type: str = "claude"  # "claude" | "codex"
    
    _backend: Optional[AgentBackend] = field(default=None, repr=False)
    # Remove: _client, replace with _backend

    def _make_backend(self) -> AgentBackend:
        if self.backend_type == "codex":
            from app.backend_codex import CodexBackend
            return CodexBackend(
                model=self.model, cwd=self.cwd,
                system_prompt=self.system_prompt,
                resume_thread_id=self.session_id,
            )
        else:
            from app.backend_claude import ClaudeBackend
            return ClaudeBackend(
                model=self.model, cwd=self.cwd,
                system_prompt=self.system_prompt,
                resume_session_id=self.session_id,
                mcp_servers=self.mcp_servers,
            )
    
    async def _ensure_backend(self) -> AgentBackend:
        if self._backend is None:
            self._backend = self._make_backend()
            await self._backend.connect()
            self._listen_task = asyncio.create_task(self._event_loop())
            self._listen_task.add_done_callback(self._on_task_done)
            if self._heartbeat_task is None or self._heartbeat_task.done():
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        return self._backend
    
    async def send(self, message: str) -> None:
        # ... existing prompt-reload logic stays ...
        backend = await self._ensure_backend()
        await backend.send(message)
        # ... existing status tracking stays ...
    
    async def _event_loop(self) -> None:
        """Replaces _persistent_listen(). Consumes AgentEvent from backend."""
        while True:
            try:
                async for event in self._backend.events():
                    self._last_msg_time = asyncio.get_event_loop().time()
                    self._handle_event(event)
            except asyncio.CancelledError:
                return
            except Exception as e:
                # Reconnect logic (same as current, but backend-agnostic)
                ...
    
    def _handle_event(self, event: AgentEvent) -> None:
        """Unified event handler — replaces all isinstance() checks."""
        if event.type == "text":
            self._log("text", event.content)
            self._turn_logs.append(event.content)
        elif event.type == "tool_use":
            self._log("tool", event.content)
            short = event.content[:80]
            self._turn_logs.append(f"[tool] {short}")
            if "send_message" in event.content or "mcp__orchestra__send_message" in event.content:
                self._did_report = True
        elif event.type == "tool_result":
            self._log("tool_result", event.content)
        elif event.type == "file_change":
            self._log("tool", f"file: {event.content}")
        elif event.type == "turn_end":
            self._handle_turn_end(event.metadata)
        elif event.type == "error":
            self._log("error", event.content)
        elif event.type == "subagent_start":
            self._log("subagent_start", event.content)
        elif event.type == "subagent_progress":
            self._log("subagent_progress", event.content)
        elif event.type == "subagent_end":
            self._log("subagent_end", event.content)
        elif event.type == "status":
            self._log("status", event.content)
    
    def _handle_turn_end(self, meta: dict) -> None:
        """Unified turn-end handler."""
        self._turn_start = 0
        sid = meta.get("session_id")
        if sid:
            self.session_id = sid
        self.cost_usd += meta.get("cost_usd", 0)
        
        self._last_context = {
            "percentage": meta.get("context_pct", 0),
            "total_tokens": meta.get("context_tokens", 0),
            "max_tokens": meta.get("max_tokens", 200000),
            "cache_hit": meta.get("cache_hit", 0),
            "cache_read": meta.get("cached_input_tokens", 0),
            "cache_create": meta.get("cache_create", 0),
        }
        
        self._log("status", f"turn ended (ctx={self._last_context['percentage']}%)")
        self.status = AgentStatus.IDLE
        self._persist()
        # ... existing auto-compact, idle notification logic ...
```

### `_event_loop` for Claude vs Codex

**Claude**: `events()` is an infinite async generator (persistent connection). The `while True` loop handles reconnections.

**Codex**: `events()` yields for one turn then returns. The `while True` loop restarts when `send()` is called again (which spawns a new subprocess).

For Codex, the loop structure works differently — `events()` returns after each turn, so the loop waits. When `send()` is called, it spawns a new process and `events()` becomes iterable again. We need a `send_and_iterate` pattern:

```python
async def _event_loop(self) -> None:
    if self.backend_type == "codex":
        # Codex: events() is per-turn, iterate once then return
        async for event in self._backend.events():
            self._handle_event(event)
    else:
        # Claude: events() is persistent, loop with reconnect
        while True:
            try:
                async for event in self._backend.events():
                    self._handle_event(event)
            except asyncio.CancelledError:
                return
            except Exception:
                # reconnect...
```

**IMPORTANT**: Both backends use the same non-blocking contract. `send()` returns immediately. Events are consumed by `_event_loop` background task. For Codex, the task is started per-turn in `send()` after subprocess spawns. See Section 12 FIX 1 and Section 13 NB1 for the corrected design.

---

## 6. Model Registry

Extend `app/models.py`:

```python
MODELS = {
    "claude-opus-4-6[1m]": "Opus 4.6 (1M)",
    "claude-sonnet-4-6": "Sonnet 4.6",
    "claude-haiku-4-5": "Haiku 4.5",
    "gpt-5.5": "GPT-5.5",
    "gpt-5.4": "GPT-5.4",
    "gpt-5.4-mini": "GPT-5.4 Mini",
}

CONTEXT_LIMITS = {
    "claude-opus-4-6[1m]": 1000000,
    "claude-sonnet-4-6": 200000,
    "claude-haiku-4-5": 200000,
    "gpt-5.5": 258400,
    "gpt-5.4": 258400,
    "gpt-5.4-mini": 258400,
}

ALIASES = {
    # ... existing claude aliases ...
    "gpt-5.5": "gpt-5.5",
    "gpt5.5": "gpt-5.5",
    "gpt-5.4": "gpt-5.4",
    "gpt5.4": "gpt-5.4",
    "gpt-5.4-mini": "gpt-5.4-mini",
    "gpt5.4mini": "gpt-5.4-mini",
}

BACKENDS = {
    "claude-opus-4-6[1m]": "claude",
    "claude-sonnet-4-6": "claude",
    "claude-haiku-4-5": "claude",
    "gpt-5.5": "codex",
    "gpt-5.4": "codex",
    "gpt-5.4-mini": "codex",
}

def backend_for_model(model: str) -> str:
    return BACKENDS.get(model, "claude")
```

Backend is inferred from model name. No explicit `backend` parameter needed in spawn API — if you say `model="gpt-5.5"`, you get Codex. If you say `model="claude-sonnet-4-6"`, you get Claude.

---

## 7. Database Schema

Add `backend_type` column to sessions table:

```python
# db.py migration
if "backend_type" not in cols:
    c.execute("ALTER TABLE sessions ADD COLUMN backend_type TEXT DEFAULT 'claude'")
```

---

## 8. Files Changed

| File | Change type | Description |
|---|---|---|
| `app/events.py` | **NEW** | `AgentEvent` dataclass |
| `app/backend.py` | **NEW** | `AgentBackend` Protocol |
| `app/backend_claude.py` | **NEW** | Claude SDK wrapper, extracted from session.py |
| `app/backend_codex.py` | **NEW** | Codex CLI subprocess + JSONL parser |
| `app/session.py` | **MODIFY** | Remove SDK imports, add backend factory + unified event handler |
| `app/models.py` | **MODIFY** | Add Codex models, `BACKENDS` dict, `backend_for_model()` |
| `app/manager.py` | **MODIFY** | Pass `backend_type` to session creation |
| `app/db.py` | **MODIFY** | Add `backend_type` column migration |
| `app/main.py` | **MODIFY** | Minor: pass backend info in API responses |
| `app/tools.py` | **MODIFY** | Add Codex models to spawn_worker schema. Dead paths (archive_by_id) are pre-existing tech debt, not in scope. |
| `app/mcp_stdio.py` | **NO CHANGE** | External MCP server, works with both CLIs |

---

## 9. Implementation Phases

### Phase 1: Foundation (2 days)
1. Create `app/events.py` with `AgentEvent`
2. Create `app/backend.py` with `AgentBackend` Protocol
3. Create `app/backend_claude.py` — extract from session.py
4. Refactor `session.py` to use `ClaudeBackend` via `_make_backend()`
5. Rewrite `_persistent_listen()` → `_event_loop()` consuming `AgentEvent`
6. **Test**: all existing functionality works identically

### Phase 2: CodexBackend (2-3 days)
1. Create `app/backend_codex.py`
2. Test `CodexBackend` standalone (simple prompt, tool use, resume)
3. Update `app/models.py` with Codex models and `BACKENDS`
4. Update `app/db.py` with `backend_type` column
5. Wire `_make_backend()` to select by model
6. **Test**: spawn Codex worker via API, verify JSONL parsing, resume

### Phase 3: MCP + Integration (2 days)
1. Codex MCP config for Orchestra tools:
   - Option A: Add to global `~/.codex/config.toml` (one entry, all workers share)
   - Option B: Per-project `.codex/config.toml` in worktree (isolated but more setup)
   - **Go with Option A** — simpler, all workers need Orchestra MCP anyway
2. Update `manager.py` to pass `backend_type` based on model
3. Dashboard: show backend badge (Claude/Codex icon) per agent
4. **Test**: Codex worker receives Orchestra MCP tools, can `send_message` back

### Phase 4: Polish (1-2 days)
1. Codex worker prompt template (different from Claude — no CLAUDE.md reference)
2. Context tracking for Codex (percentage from input_tokens / context_window)
3. Model change for Codex workers
4. Compact for Codex (prompt-based, same strategy, different subprocess mechanics)
5. Error handling: Codex process crash recovery
6. **Test**: full cycle — orchestrator spawns Codex worker, worker does task, reports back

---

## 10. Risks & Fallbacks

### Risk 1: Codex subscription rate limits
**Problem**: OpenAI Pro has per-5-hour credit limits. Multiple concurrent workers may exhaust credits.
**Fallback**: Track cumulative token usage per 5h window. Warn orchestrator when approaching limit. Fall back to API key mode or throttle spawn rate.

### Risk 2: Codex session resume breaks
**Problem**: `codex exec resume` may fail if session storage corrupts or CLI updates change format.
**Fallback**: If resume fails, start fresh session with context preamble (same as our compact strategy). Log warning and continue.

### Risk 3: MCP tool calls not visible
**Problem**: Codex may not surface `mcp_tool_call` events in `--json` output for all MCP servers.
**Verified**: JSONL format includes `mcp_tool_call` item type with `server`, `tool`, `arguments`, `result`. Should work.
**Fallback**: If Orchestra MCP calls aren't visible, we still have the HTTP callback (MCP server hits Orchestra API directly). Communication works regardless of event visibility.

### Risk 4: System prompt injection via `-c developer_instructions=...`
**Problem**: Long prompts with special characters may break shell escaping.
**Fallback**: Write prompt to temp file, pass via `codex exec` stdin (SDK does this — writes prompt to stdin, not CLI arg). Or use `AGENTS.md` file in worktree directory.

### Risk 5: Codex CLI updates break JSONL format
**Problem**: We parse raw JSON, not SDK models. CLI update may change event structure.
**Fallback**: `json.loads()` is forward-compatible for unknown fields. Add `try/except` around each event type. Log and skip unknown events rather than crashing. Version-pin Codex CLI via npm.

---

## 11. What We Explicitly DON'T Do

1. **No app-server protocol** — too complex for MVP. Subprocess per turn is good enough.
2. **No Python SDK dependency** — it has bugs (FileChangeItem status), we parse JSONL directly.
3. **No mid-turn injection for Codex** — Codex turns are sequential. Messages sent during active turn are queued and sent after turn completes.
4. **No Codex orchestrator** — orchestrators stay on Claude (Opus). Only workers get Codex option.
5. **No Codex-specific dashboard views** — same dashboard, just a backend badge.
6. **No multi-provider-per-session** — one backend per session lifetime. Model change = new backend.

---

## 12. Codex Review Fixes (Round 1)

Codex (GPT-5.5) reviewed this plan and found 2 blocking + 7 suggestions. All accepted with fixes below.

### FIX 1 (blocking): Codex `send()` must not block the caller

**Problem**: The plan proposed inline event consumption in `send()` for Codex. But `send()` is called from HTTP API (`main.py:334`) and MCP tools (`mcp_stdio.py:65`) which have timeouts. A Codex turn can take 30-300 seconds.

**Fix**: Codex `send()` must have the same async contract as Claude — return immediately, consume events in a background task.

```python
async def send(self, message: str) -> None:
    backend = await self._ensure_backend()
    await backend.send(message)  # starts subprocess
    # For BOTH backends: events flow via _event_loop background task
    # No inline iteration. No if/else per backend type.
```

For `CodexBackend`, `send()` spawns the subprocess and returns. A separate `events()` async generator reads stdout. The `_event_loop` task (same for both backends) consumes it:

```python
async def _event_loop(self) -> None:
    while True:
        try:
            async for event in self._backend.events():
                self._handle_event(event)
        except asyncio.CancelledError:
            return
        except Exception:
            # For Claude: reconnect. For Codex: just break inner loop, 
            # next send() will spawn new process
            if self.backend_type == "claude":
                await self._reconnect_backend()
            else:
                break
```

For Codex: `events()` yields until the process exits, then returns. The `_event_loop` loop breaks. Next `send()` spawns a new process and restarts the loop.

### FIX 2 (blocking): Process death must emit terminal event

**Problem**: If `codex exec` crashes (non-zero exit, killed, broken pipe), no `turn.completed` JSONL event is emitted. Session stays `RUNNING` forever.

**Fix**: After `events()` generator exhausts (process exited), always emit a synthetic terminal event:

```python
async def events(self) -> AsyncIterator[AgentEvent]:
    # ... JSONL parsing loop ...
    
    # After stdout exhausts:
    returncode = await self._proc.wait()
    stderr = (await self._proc.stderr.read()).decode("utf-8", errors="replace")[-500:]
    
    if not self._got_turn_completed:
        yield AgentEvent("turn_end", "", metadata={
            "session_id": self._thread_id,
            "ok": False,
            "stop_reason": f"process_exit_{returncode}",
            "returncode": returncode,
            "stderr_tail": stderr,
            "cost_usd": 0,
            "context_pct": 0,
        })
    
    self._proc = None
```

And `_handle_turn_end` checks `meta.get("ok", True)`:

```python
def _handle_turn_end(self, meta: dict) -> None:
    ok = meta.get("ok", True)
    sr = meta.get("stop_reason", "unknown")
    self._log("status", f"turn ended: ok={ok}, stop_reason={sr}")
    # ... rest of handling ...
```

### FIX 3 (suggestion): Persist `backend_type` through full lifecycle

Add `backend_type` to:
- `AgentSession._to_db_dict()` — include in dict
- `save_session()` — INSERT/UPDATE with backend_type column
- `_load_from_db()` — read from DB row, pass to session
- `to_dict()` — include in API responses
- Validation on load: `assert backend_type == backend_for_model(model)`

### FIX 4 (suggestion): Block cross-backend model change

```python
async def change_model(self, new_model: str) -> dict:
    old_backend = backend_for_model(self.model)
    new_backend = backend_for_model(new_model)
    if old_backend != new_backend:
        return {"ok": False, "error": f"Cannot change from {old_backend} to {new_backend}. Kill and respawn."}
    # ... existing logic ...
```

### FIX 5 (suggestion): Add `ok`, `stop_reason`, `returncode` to turn_end metadata

Update `AgentEvent` documentation and both backends:
- Claude: `ok=True`, `stop_reason` from `ResultMessage.stop_reason`, `num_turns` from `ResultMessage.num_turns`
- Codex: `ok=True` if got `turn.completed`, `ok=False` if process died. `returncode` from process.

### FIX 6 (suggestion): Update `app/tools.py` model schema

Add Codex models to `spawn_worker` tool's model parameter description. The `@tool` decorator doesn't enforce schema — it's just documentation for the LLM.

Note: `app/tools.py` uses in-process SDK MCP (`from claude_agent_sdk import tool`) only for orchestrators. Workers use external `mcp_stdio.py`. Since orchestrators stay on Claude, `tools.py` keeps its SDK import. But model list needs updating.

### FIX 7 (suggestion): Per-worktree MCP config instead of global

Each Codex worker gets a `.codex/config.toml` in its worktree directory:

```python
# In manager.py, after worktree creation for Codex workers:
def _write_codex_mcp_config(worktree_path: str, name: str, scope: str):
    codex_dir = Path(worktree_path) / ".codex"
    codex_dir.mkdir(exist_ok=True)
    config = f'''[mcp_servers.orchestra]
command = "{sys.executable}"
args = ["{_MCP_SCRIPT}"]

[mcp_servers.orchestra.env]
ORCHESTRA_URL = "http://127.0.0.1:8888"
ORCHESTRA_SCOPE = "{scope}"
ORCHESTRA_ROLE = "worker"
WORKER_NAME = "{name}"
PYTHONPATH = "{_PROJECT_ROOT}"
'''
    (codex_dir / "config.toml").write_text(config)
```

This gives each worker its own identity. `-C <worktree>` makes Codex pick up this config automatically.

### FIX 8 (suggestion): Resume parameter verification

`codex exec resume` only accepts `--json`, `-m`, `--skip-git-repo-check`, `--ephemeral`. It does NOT accept `-C`, `--sandbox`, `--add-dir`. These are inherited from the original session.

This means: first turn MUST set correct `-C`, `--sandbox`, and model. Resume inherits them. Verified via `codex exec resume --help`.

Add acceptance test in Phase 2: verify resumed session runs in correct worktree CWD.

### FIX 9 (question): Remove `--dangerously-bypass-approvals-and-sandbox`

Verified: `--yolo` overrides `--sandbox` to `danger-full-access`. Worker gets unrestricted file access beyond worktree.

**Fix**: Use only `--sandbox workspace-write`. Codex exec already defaults to `approval_policy: never` in non-interactive mode — no human prompts appear.

### FIX 10 (thought): compact() depends on Claude SDK

`compact()` directly creates a `ClaudeSDKClient` and reads `AssistantMessage`/`ResultMessage`. For Codex, compact needs to use the backend:

```python
async def compact(self) -> dict:
    # Same strategy for both backends:
    # 1. Send compact prompt via backend.send()
    # 2. Read events via backend.events()
    # 3. Extract summary from text events
    # 4. Disconnect, reset session_id, send preamble
```

This is already implied by the refactoring but worth calling out explicitly: `compact()` must use the backend abstraction, not raw SDK calls.

---

## 13. Codex Review Fixes (Round 2)

Round 2 found 3 STILL BROKEN + 2 new blocking + 5 new suggestions. All accepted.

### STILL BROKEN fixes:

**SB1: Old inline send() sketch not removed** — The old Section 5 code (inline Codex iteration) is SUPERSEDED by Round 1 FIX 1. Delete the old `if self.backend_type == "codex"` inline pattern. Only the background task pattern is valid. Non-goals section: remove "Codex send() blocks" — it doesn't anymore.

**SB6: tools.py table says NO CHANGE** — Update files table: `app/tools.py` → **MODIFY** (add Codex models to spawn_worker schema). Dead paths (`_manager.archived`, `archive_by_id`) are pre-existing tech debt, not in scope for this plan — note in table.

**SB9: Old sketch still has --yolo flag** — Remove `--dangerously-bypass-approvals-and-sandbox` from the CodexBackend `send()` sketch in Section 4. Only `--sandbox workspace-write` remains.

### NEW blocking fixes:

**NB1: Race on Codex event_loop start** — `_ensure_backend()` starts `_event_loop` before `send()` spawns subprocess. For Codex, `events()` sees `_proc=None` and returns immediately.

**Fix**: Don't start `_event_loop` in `_ensure_backend()` for Codex. Instead, start it inside `send()` after `backend.send()` spawns the process:

```python
async def send(self, message: str) -> None:
    backend = await self._ensure_backend()
    await backend.send(message)
    
    if self.backend_type == "codex":
        # Start/restart event loop AFTER process is spawned
        if self._listen_task and not self._listen_task.done():
            pass  # already running (shouldn't happen — Codex turns are sequential)
        else:
            self._listen_task = asyncio.create_task(self._event_loop())
            self._listen_task.add_done_callback(self._on_task_done)
    
    # Claude: _event_loop started once in _ensure_backend, persists across turns
```

**NB2: No send() guard against concurrent turns** — Second `send()` during active Codex turn would overwrite `_proc`.

**Fix**: Add status check at session level (already exists for Claude but not enforced):

```python
async def send(self, message: str) -> None:
    if self.backend_type == "codex" and self.status == AgentStatus.RUNNING:
        # Queue message for after current turn completes
        self._pending_messages.append(message)
        self._log("status", "message queued (Codex turn in progress)")
        return
    # ... proceed with send ...
```

After turn completes in `_handle_turn_end`, check queue:
```python
if self._pending_messages:
    next_msg = self._pending_messages.pop(0)
    asyncio.create_task(self.send(next_msg))
```

### NEW suggestion fixes:

**NS1: Reset _got_turn_completed per turn** — Add `self._got_turn_completed = False` at start of `CodexBackend.send()`.

**NS2: stderr drain race** — Use `asyncio.create_task` to drain stderr concurrently with stdout reading. Or use `stderr=asyncio.subprocess.DEVNULL` and skip stderr (simpler, loses debug info). Compromise: `stderr=asyncio.subprocess.PIPE` + concurrent drain task, store last 500 bytes.

```python
async def send(self, message: str) -> None:
    # ...spawn proc...
    self._stderr_task = asyncio.create_task(self._drain_stderr())

async def _drain_stderr(self) -> bytes:
    chunks = []
    while True:
        chunk = await self._proc.stderr.read(4096)
        if not chunk:
            break
        chunks.append(chunk)
    data = b"".join(chunks)
    self._last_stderr = data[-500:].decode("utf-8", errors="replace")
    return data
```

**NS3: assert → if/log for backend validation** — Replace `assert backend_type == backend_for_model(model)` with:
```python
expected = backend_for_model(row["model"])
actual = row.get("backend_type", "claude")
if actual != expected:
    logger.warning(f"backend mismatch for {row['name']}: stored={actual}, model implies={expected}. Using {expected}.")
    actual = expected
```

**NS4: TOML escaping in config generation** — Use `json.dumps()` for string values (JSON strings are valid TOML basic strings):
```python
config = f'''[mcp_servers.orchestra]
command = {json.dumps(sys.executable)}
args = [{json.dumps(_MCP_SCRIPT)}]

[mcp_servers.orchestra.env]
ORCHESTRA_URL = "http://127.0.0.1:8888"
ORCHESTRA_SCOPE = {json.dumps(scope)}
WORKER_NAME = {json.dumps(name)}
'''
```

**NS5: .codex/config.toml gitignore** — After creating `.codex/config.toml`, add to `.git/info/exclude`:
```python
exclude_path = Path(worktree_path) / ".git" / "info" / "exclude"
exclude_path.parent.mkdir(parents=True, exist_ok=True)
with open(exclude_path, "a") as f:
    f.write("\n.codex/\n")
```
Note: worktrees use `.git` file pointing to main repo's `.git/worktrees/<name>/`, so `info/exclude` is per-worktree.

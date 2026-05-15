# Idle Session Optimization Research

**Date**: 2026-05-15
**Author**: feat-idle-optimization worker

## Problem Statement

Orchestra keeps CLI processes + MCP servers alive for idle sessions, wasting ~1.5 GB RAM across 10 claude processes and their child MCP servers. "Idle" = waiting for next message, doing zero computation.

## Current State: Live Measurement

### Process Inventory (2026-05-15 snapshot)

10 Claude CLI processes with the following child MCP servers per session:

| Session Type | Claude RSS | Children RSS | Total | Child processes |
|---|---|---|---|---|
| Orchestrator (Parsing, 4×serena) | 46 MB | 62 MB | **171 MB** | node(websearch), python3(mcp_stdio), uv(pandoc), python(aperant), npm(playwright), python(yougile), 4×serena |
| Orchestrator (Sensar, 4×serena + chrome) | 158 MB | 88 MB | **886 MB** | Same as above + Playwright-spawned Chrome (~500 MB) |
| Worker (Orchestra, pyright) | 181 MB | 38 MB | **223 MB** | node(websearch), python3(mcp_stdio), uv(pandoc), pyright |
| Worker (minimal MCP) | 41-50 MB | 11 MB | **56-64 MB** | node(websearch), python3(mcp_stdio), uv(pandoc) |
| Worker (active, this session) | 289 MB | 167 MB | **486 MB** | node(websearch), python3(mcp_stdio), uv(pandoc) (larger due to active use) |

**Total across all 10 processes: ~1,527 MB (1.5 GB)**

### Per-Session RAM Breakdown (typical idle worker)

```
Claude CLI process:     ~45 MB   (Node.js runtime + loaded context)
  ├── node (websearch):  ~4 MB   (MCP: websearch index.js)
  ├── python3 (mcp_stdio): ~5 MB (MCP: Orchestra tools)  
  ├── uv (pandoc):       ~2 MB   (MCP: pandoc converter)
  └── [grandchild of uv]: ~5 MB  (python running pandoc server)
                        --------
Total per idle worker:  ~60 MB
Total per idle orchestrator: ~170 MB (+ serena/playwright/yougile)
```

### Key Finding: MCP Servers Are Children of Claude CLI

```
claude (PID 344223)
  ├── node (websearch)       ← dies when claude dies
  ├── python3 (mcp_stdio)   ← dies when claude dies  
  ├── uv (pandoc)           ← dies when claude dies
  └── serena ×4             ← dies when claude dies
```

MCP servers are **child processes** of the Claude CLI process, not of Orchestra. Killing the CLI process kills all its MCP children automatically.

## Architecture Analysis

### Current Flow: Persistent Client

```
Orchestra (FastAPI)
  └── AgentSession._ensure_backend()
       └── ClaudeBackend.connect()
            └── ClaudeSDKClient(options).connect()
                 └── SubprocessCLITransport.connect()
                      └── anyio.open_process(["claude", ...])  ← STAYS ALIVE
                           ├── Initialize (handshake)
                           └── Waiting on stdin forever...
```

When idle:
- `_claude_event_loop()` blocks on `self._backend.events()` → `self._client.receive_messages()` → waiting on stdout
- `_heartbeat_loop()` ticks every 60s checking if listen task is alive
- CLI process sits idle, all MCP servers sit idle
- **RAM usage: constant, never freed**

### How Resume Works (from SDK source)

The `--resume <session_id>` flag:
1. CLI finds `~/.claude/projects/<sanitized-cwd>/<session_id>.jsonl` on disk
2. Reads the full JSONL transcript (conversation history)
3. Reconstructs context window from the transcript
4. Continues as if the conversation never stopped

**Critical insight**: Session state is stored in the JSONL file on disk, NOT in the process memory. The CLI process is just a runner that reads from disk on startup.

This means: **we CAN kill the process and restart it with `--resume`**.

### ClaudeSDKClient Lifecycle

```python
# Connect: spawns subprocess
client = ClaudeSDKClient(options)
await client.connect()  # starts CLI process + initializes

# Query: writes to stdin, reads from stdout
await client.query("message")
async for msg in client.receive_messages():
    ...  # yields until ResultMessage

# Disconnect: kills subprocess
await client.disconnect()  # SIGTERM → wait 5s → SIGKILL
```

`disconnect()` in `SubprocessCLITransport.close()`:
- Closes stdin (sends EOF)
- Waits up to 5s for graceful exit (CLI flushes JSONL)
- SIGTERM if still alive
- Waits 5s more
- SIGKILL as last resort

### What `_ensure_backend()` Already Does

```python
async def _ensure_backend(self):
    if self._backend is not None:
        return self._backend
    self._backend = self._make_backend()
    await self._backend.connect()
    self._listen_task = asyncio.create_task(self._claude_event_loop())
    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
    return self._backend
```

**This is already a lazy-connect pattern!** The backend is created on first `send()`. If we `disconnect()` + set `self._backend = None`, the next `send()` will reconnect automatically.

## Proposed Solution: Idle Hibernate

### Concept

When a session goes idle (turn_end event), start a timer. After N minutes of idleness, kill the CLI process + all MCP children. On next `send()`, `_ensure_backend()` reconnects with `--resume`.

### Implementation Plan

#### Phase 1: Basic Hibernate/Wake (Quick Win)

Add to `AgentSession`:

```python
IDLE_TIMEOUT = 300  # 5 minutes after turn ends

async def _handle_turn_end(self, event):
    # ... existing code ...
    self.status = AgentStatus.IDLE
    self._persist()
    
    # Schedule hibernate
    if self._hibernate_task:
        self._hibernate_task.cancel()
    self._hibernate_task = asyncio.create_task(self._idle_hibernate())

async def _idle_hibernate(self):
    await asyncio.sleep(self.IDLE_TIMEOUT)
    if self.status != AgentStatus.IDLE:
        return  # got a message while waiting
    await self._disconnect_backend()
    self._log("status", "hibernated (idle timeout)")

async def send(self, message):
    # Cancel hibernate if pending
    if self._hibernate_task and not self._hibernate_task.done():
        self._hibernate_task.cancel()
    # _ensure_backend() handles reconnect
    backend = await self._ensure_backend()
    await backend.send(message)
```

#### Critical: ClaudeBackend Must Support Reconnect-on-Resume

Current `_make_client()` uses `self._resume_id` which is set at construction time:

```python
def _make_client(self):
    options = ClaudeAgentOptions(...)
    if self._resume_id:
        options.resume = self._resume_id
    else:
        options.system_prompt = {...}
    return ClaudeSDKClient(options=options)
```

After first turn, `session_id` is captured from `ResultMessage`. On reconnect, the backend should ALWAYS use `resume` mode with the last known session_id. This is already handled because `ClaudeBackend._session_id` is updated on each turn end.

**But there's a gap**: `_make_client()` reads `self._resume_id` (set at construction), not `self._session_id` (updated on each turn). Fix:

```python
def _make_client(self):
    resume_id = self._session_id or self._resume_id
    options = ClaudeAgentOptions(...)
    if resume_id:
        options.resume = resume_id
    else:
        options.system_prompt = {...}
    return ClaudeSDKClient(options=options)
```

### Phase 2: Smart Timeout

Different timeouts per session type:
- **Workers**: 2 minutes (they're task-specific, wake-on-demand is fine)
- **Orchestrators**: 10 minutes (they receive frequent messages)
- **Active conversations**: Never hibernate during a burst (< 30s between messages)

### Phase 3: Metrics & Dashboard

Show hibernate state in dashboard:
- Status: `idle` vs `idle (hibernated)` vs `running`
- Memory saved indicator
- Last hibernate/wake timestamps

## Risk Analysis

### Will Resume Work Correctly?

**YES**, with caveats:

1. **Context is preserved**: The JSONL file has the full conversation. `--resume` reads it back.
2. **Session ID persists**: We store it in SQLite (`session_id` column) and in `AgentSession.session_id`.
3. **MCP servers restart**: Claude CLI spawns new MCP children on connect. The MCP servers are stateless (orchestra tools, websearch, pandoc).
4. **Cost**: Resume has a context-rebuild cost (reads the full transcript). For large sessions this means a short delay (1-3s) but no API token cost — it's local file I/O.

### Potential Issues

1. **Playwright state lost**: Chrome process dies on hibernate. Tests in progress would fail. Mitigation: Don't hibernate sessions with active Playwright.
2. **Serena LSP state**: Serena restarts clean. This is fine — it indexes on startup.
3. **Race condition**: Message arrives during hibernate/wake transition. Mitigation: Use a lock.
4. **First-message latency**: ~3-5s for CLI startup + MCP initialization. Acceptable for idle sessions.

### What About Context Percentage?

Resume reloads the full transcript. Context percentage is preserved because it depends on the conversation content, not the process state.

## Memory Savings Estimate

With 5-minute idle timeout:

| Before | After (typical) | Savings |
|---|---|---|
| 10 processes always alive | 2-3 processes (active + recently active) | ~1.2 GB freed |
| ~1.5 GB total | ~300 MB | **80% reduction** |

Most sessions are idle most of the time. In a typical scenario with 1-2 active workers and 1 orchestrator running, the rest (7-8 sessions) hibernate after 5 minutes.

## Worker MCP Access (Bonus Research)

### Problem
Workers don't see project-level MCP servers (Playwright, Serena, YouGile). They only get the Orchestra MCP passed via `_make_mcp_config()`.

### How CLI Discovers MCP Servers

1. Global: `~/.claude/settings.json` → `mcpServers` (always loaded)
2. Project: `<cwd>/.claude/settings.json` → `mcpServers`
3. SDK: Passed via `ClaudeAgentOptions.mcp_servers`

Workers run in worktrees under `orchestra/worktrees/<scope>/<name>/`. Their CWD is the worktree, not the original project. So project-level `.claude/settings.json` from the original project is NOT loaded.

### Solutions (simplest first)

1. **Symlink `.claude/` into worktree**: `ln -s /original/project/.claude /worktree/.claude/`
   - Pros: Zero code change, CLI picks it up naturally
   - Cons: Symlink management, worktree cleanup gets complicated

2. **Pass MCP via SDK options**: Add project MCP servers to `ClaudeAgentOptions.mcp_servers`
   - Pros: Explicit, no filesystem hacks
   - Cons: Need to discover project MCP config, parse settings.json

3. **Copy `.claude/settings.json` into worktree on spawn**
   - Pros: Clean, isolated
   - Cons: Stale if project config changes

**Recommendation**: Option 2 is cleanest. Read project's `.claude/settings.json`, merge with orchestra MCP, pass via SDK.

## Quick Win: What Can We Do TODAY

1. **Implement basic hibernate** (Phase 1): ~50 lines of code change in `session.py` + minor fix in `backend_claude.py`
2. **Add `IDLE_TIMEOUT` config**: Different values per session type
3. **Fix the resume_id bug**: `_make_client()` should use `self._session_id` for reconnection

Expected result: **~1.2 GB RAM freed** within 5 minutes of sessions going idle.

## What's Impossible with Current SDK

- **Hot-swap MCP servers**: Can't add/remove MCP servers without killing the CLI process. `toggle_mcp_server()` exists but only for already-configured servers.
- **Partial context unload**: Can't selectively unload parts of conversation from memory. The CLI loads the full transcript on resume.
- **Shared MCP instances**: Each CLI spawns its own MCP children. Can't share a single websearch node process across sessions.
- **Process-less idle**: SDK doesn't support a "paused" state where the CLI process is suspended (SIGSTOP). The MCP stdio protocol doesn't handle reconnection after pause.

## Appendix: Full Process Tree (snapshot)

```
python3 (Orchestra FastAPI, PID 343539, 156 MB)
├── claude 344223 (46 MB) — Parsing-orchestrator [4×serena, all MCP]
├── claude 344790 (158 MB) — Sensar-orchestrator [4×serena, chrome, all MCP]
├── claude 345749 (181 MB) — Orchestra worker [pyright, websearch, mcp_stdio, pandoc]
├── claude 349906 (49 MB) — Worker [websearch, mcp_stdio, pandoc]
├── claude 360569 (179 MB) — Worker [websearch, mcp_stdio, pandoc]
├── claude 406754 (42 MB) — Worker [websearch, mcp_stdio, pandoc]
├── claude 410563 (50 MB) — Worker [websearch, mcp_stdio, pandoc]
├── claude 439654 (44 MB) — Worker [websearch, mcp_stdio, pandoc]
├── claude 559519 (167 MB) — Worker [websearch, mcp_stdio, pandoc]
└── claude 625533 (289 MB) — THIS SESSION (active) [websearch, mcp_stdio, pandoc]
```

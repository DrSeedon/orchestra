# Background Tasks & Monitoring Research

**Date**: 2026-05-15
**Author**: feat-idle-optimization worker

## 1. How Monitor Works in Claude Code

### Architecture

Monitor is a **built-in CLI tool**, not an SDK feature. It's part of the Claude Code binary, not the `claude_agent_sdk` Python package.

The tool shifts from polling to interrupt-driven: instead of "did it finish?" every N seconds (burning tokens), Monitor holds an open connection to a background process's output stream and waits for a trigger pattern.

### Implementation

When an agent calls `Bash` with `run_in_background: true`:
1. CLI spawns the command as a child process
2. Redirects stdout/stderr to a temp file (e.g., `/tmp/claude-xxx-output.txt`)
3. Returns immediately with: `"Command running in background. Output is being written to: /path/to/file"`
4. The Monitor tool can then `tail -f` that file with a pattern filter

Monitor parameters:
- **command/path**: What to watch (file path or command output)
- **pattern**: Regex trigger (e.g., `"ERROR|DONE"`)
- **persistent**: `true` = lives as long as the session; `false` = one-shot

### What Happens on Hibernate

When we disconnect the CLI (hibernate):
1. CLI process receives SIGTERM → flushes JSONL → exits
2. **All child processes die** (background commands, Monitor tail processes)
3. The output files remain on disk
4. On resume: CLI restarts, but **monitors are NOT restored**

Background processes with `persistent: true` supposedly persist across sessions in vanilla Claude Code (they sync state to disk). But this relies on the CLI managing its own lifecycle — which we override via the SDK.

### What Happens on Resume

The Claude CLI `--resume <session_id>` reads the JSONL transcript and reconstructs the conversation context. But it does NOT:
- Restart killed background processes
- Recreate Monitor watchers
- Resume `tail -f` commands

The agent's context includes the memory that it started a monitor, but the actual process is dead. If the agent tries to check the monitor, it'll get an error or stale data.

## 2. Background Jobs in SDK

### `run_in_background` — Why We Blocked It

Orchestra blocks `run_in_background` in `backend_claude.py:40-41`:

```python
if isinstance(tool_input, dict) and tool_input.get("run_in_background"):
    return PermissionResultDeny(message="run_in_background is disabled in Orchestra — 
        background processes are killed when your turn ends. Run synchronously instead.")
```

**Why**: The SDK's persistent client model means the CLI process outlives individual turns. But:
1. Background processes become orphans when the turn ends (no one reads their output)
2. On hibernate, CLI dies → background processes die → work lost
3. No mechanism to notify the agent when a background task completes between turns

### Orchestra's Existing Workaround: `_poll_bg_outputs`

`session.py:364-382` has a polling mechanism:
1. After `turn_end`, collect paths from `_bg_outputs` list
2. Every 5 seconds, check if the output file exists and has stabilized (size unchanged for 2s)
3. Read last 3000 chars and inject as a new message to the agent
4. Timeout: 120 iterations × 5s = 10 minutes max

**Problems**:
- Fixed 5s polling interval (too slow for fast tasks, wasteful for slow ones)
- No pattern matching — waits for file to "stabilize" (wrong heuristic for streaming logs)
- Dies on hibernate (it's an asyncio task on the Orchestra server, but the output file may be gone)
- Only works for `run_in_background` outputs, not arbitrary file watching

### SDK Hooks/Events

The SDK provides:
- `can_use_tool` callback — we use this to block tools
- `receive_messages()` async iterator — yields events from CLI
- `query()` — injects messages mid-conversation

No built-in "file changed" or "process exited" events. Everything is pull-based (read from stdout).

## 3. Competitor Analysis

### Claude Code Native (Agent View + /background)

Anthropic's own solution (May 2026):
- `/background` or `/bg` moves a conversation to background
- Agent View dashboard manages multiple sessions
- Background tasks persist within the session lifecycle
- No cross-session monitoring — each session is self-contained

**Limitation**: Background processes live inside the CLI session. No server-side monitoring.

### Agent Teams (Built-in)

- One session = team lead, others = teammates
- Communication via `SendMessage` tool
- Each teammate has its own context window
- Teammates work in worktrees (isolation)

**Limitation**: No shared monitoring. Each agent polls independently.

### Claude Squad

- Zero-setup terminal parallelism
- Multiple tmux panes, each running claude
- File-based signaling between agents

**Limitation**: Terminal-bound. No daemon-mode monitoring.

### Claude Flow (ruflo)

- Background commands via process spawning
- Session persistence: syncs state to S3, restores in fresh containers
- "From its perspective, the session was never interrupted"

**Interesting pattern**: Full state serialization. But requires S3 infrastructure.

### File-Based Signaling Pattern

Common across tools:
1. Agent writes to a "signal file" (e.g., `/tmp/task-done.signal`)
2. Another agent or monitor watches for the file
3. On detection, sends message to wake the target agent

This is essentially what we need, but server-side.

## 4. Orchestra-Native Background Tasks: Design

### Concept: Server-Side Watchers

Watchers live in the **Orchestra FastAPI server**, not in the CLI process. They survive hibernate because they're asyncio tasks in the Orchestra event loop.

### MCP Tool: `watch`

```
watch(
    source: str,          # file path, command, or "cron:SPEC"
    pattern: str,         # regex to match
    on_match: str = "wake",  # "wake" | "wake_and_report" | "log"
    timeout: int = 3600,  # max seconds to watch (default 1h)
    name: str = "",       # optional human-readable name
)
```

Returns: `{"watch_id": "w-abc123", "status": "watching"}`

### MCP Tool: `unwatch`

```
unwatch(watch_id: str)  # or "all" to clear
```

### Architecture

```
Agent calls watch() via MCP tool
  → Orchestra MCP server receives request
  → Creates asyncio task (WatcherTask) in SessionManager
  → WatcherTask:
      ├── File watch: asyncio subprocess running `tail -f <path> | grep -m1 <pattern>`
      ├── Command watch: asyncio subprocess running `<command> 2>&1 | grep -m1 <pattern>`
      └── Cron watch: apscheduler or asyncio.sleep loop
  → On match:
      ├── Injects message into agent: session.send("[Watch triggered] ...")
      └── Logs event
  → On timeout: auto-cleanup, log "watch expired"
```

### Key Properties

1. **Survives hibernate**: Watcher is an asyncio task in Orchestra server, not a CLI child process
2. **Survives turn boundaries**: Not tied to agent turns
3. **Agent-independent**: Watcher runs even when agent is idle/hibernated
4. **Auto-cleanup**: Timeout prevents zombie watchers
5. **Wake-on-match**: Uses existing `session.send()` to inject message (same as MCP inject)

### Implementation Sketch

```python
@dataclass
class Watcher:
    id: str
    session_id: str
    source: str
    pattern: str
    on_match: str
    timeout: float
    task: asyncio.Task
    created_at: float

class WatcherManager:
    def __init__(self):
        self.watchers: dict[str, Watcher] = {}

    async def create(self, session_id: str, source: str, pattern: str, 
                     on_match: str, timeout: float) -> str:
        watcher_id = f"w-{uuid4().hex[:8]}"
        task = asyncio.create_task(
            self._run_watcher(watcher_id, session_id, source, pattern, on_match, timeout)
        )
        self.watchers[watcher_id] = Watcher(...)
        return watcher_id

    async def _run_watcher(self, watcher_id, session_id, source, pattern, on_match, timeout):
        try:
            async with asyncio.timeout(timeout):
                if source.startswith("cron:"):
                    await self._cron_watch(...)
                else:
                    await self._stream_watch(source, pattern, session_id, on_match)
        except asyncio.TimeoutError:
            pass  # expired
        finally:
            self.watchers.pop(watcher_id, None)

    async def _stream_watch(self, source, pattern, session_id, on_match):
        # If source is a file path: tail -f
        # If source contains spaces/pipes: run as shell command
        cmd = f"tail -f '{source}'" if Path(source).exists() else source
        proc = await asyncio.create_subprocess_shell(
            f"{cmd} | grep -m1 -E '{pattern}'",
            stdout=PIPE, stderr=PIPE
        )
        stdout, _ = await proc.communicate()
        match_line = stdout.decode().strip()
        if match_line:
            await self._trigger(session_id, source, pattern, match_line, on_match)

    async def _trigger(self, session_id, source, pattern, match_line, on_match):
        session = manager.get(session_id)
        if session and on_match in ("wake", "wake_and_report"):
            msg = f"[Watch triggered]\nSource: {source}\nPattern: {pattern}\nMatch: {match_line}"
            await session.send(msg)
```

### Examples

```
# Watch migration log for completion
watch("/tmp/migration.log", pattern="ERROR|DONE", on_match="wake")

# Watch remote nginx for 502 errors
watch("ssh root@vps 'journalctl -f -u nginx'", pattern="502", on_match="wake")

# Periodic health check
watch("cron:*/5 * * * *", command="curl -s https://site.ru", pattern="200", on_match="wake_if_not_200")

# Watch deploy output
watch("/var/log/deploy.log", pattern="DEPLOYED|FAILED", timeout=1800)
```

### Edge Cases

1. **Session killed while watcher active**: Watcher detects session gone → auto-cleanup
2. **Multiple watchers per session**: Supported, each independent
3. **Pattern never matches**: Timeout handles cleanup (default 1 hour)
4. **Watcher source file doesn't exist yet**: `tail -f` waits for file creation (or use `inotifywait`)
5. **SSH command dies**: Grep gets EOF → watcher exits → auto-cleanup with "source closed" log

## 5. Blocking Monitor Tool

### Options

**Option A: Block Monitor for all Orchestra agents**

Add `"Monitor"` to `_BLOCKED_TOOLS` in `backend_claude.py`:

```python
_BLOCKED_TOOLS = {"AskUserQuestion", "Monitor"}
```

Pros: Clean, prevents confusion
Cons: Some agents might legitimately want short-lived monitors during a turn

**Option B: Block Monitor for orchestrators, allow for workers**

```python
_ORCH_BLOCKED_TOOLS = {"AskUserQuestion", "Agent", "Monitor"}
_BLOCKED_TOOLS = {"AskUserQuestion"}  # workers can use Monitor
```

Pros: Workers can use Monitor during active turns
Cons: Monitor dies on hibernate anyway

**Option C: Don't block Monitor, but replace with our `watch` MCP tool**

Don't block — let agents discover that Monitor doesn't survive hibernate. Our `watch` tool becomes the recommended alternative because it survives everything.

**Recommendation: Option A** — Block Monitor for everyone. It's confusing to have a tool that works during a turn but silently dies on hibernate. Replace with server-side `watch` MCP tool.

Additionally, `run_in_background` is already blocked. Together:
- No `run_in_background` (processes die on turn end)  
- No `Monitor` (processes die on hibernate)
- Yes `watch` (server-side, survives everything)

---

## 6. Worker MCP Auto-Discovery

### How Claude CLI Discovers MCP Servers

The CLI loads MCP servers from multiple sources, merged in this priority order (lowest → highest):

1. **Plugins** (`~/.claude/plugins/*/`): Each plugin can define `.mcp.json` with server configs. Example: Serena plugin provides `serena` MCP server.

2. **User mcp-configs** (`~/.claude/mcp-configs/*.json`): JSON files like `playwright.json`, `yougile.json`, `serena-disabled.json`. Each defines `{"mcpServers": {...}}`.

3. **User settings** (`~/.claude/settings.json`): Global `mcpServers` section. Currently has: `aperant`, `kwin`, `orchestra`.

4. **Project settings** (`<cwd>/.claude/settings.json`): Project-specific MCP servers.

5. **Project local settings** (`<cwd>/.claude/settings.local.json`): Local overrides, gitignored.

6. **SDK --mcp-config** flag: Passed via `ClaudeAgentOptions.mcp_servers`. **ADDS to** discovered servers (does NOT replace, unless `--strict-mcp-config` is used).

### The `--setting-sources` Flag

```
SettingSource = Literal["user", "project", "local"]
```

Controls which levels CLI loads:
- `"user"` → user settings + user mcp-configs + plugins
- `"project"` → project settings (`<cwd>/.claude/settings.json`)
- `"local"` → project local settings (`<cwd>/.claude/settings.local.json`)

Default (when not passed): **all three**.

### What Workers Actually Get (Measured)

**Orchestrator** (CWD = `/mnt/data/Projects/Python/Parsing`):
- websearch, mcp_stdio (orchestra), pandoc — from user mcp-configs
- aperant — from global settings.json
- playwright — from user mcp-configs
- yougile — from user mcp-configs
- 4×serena — from plugin, detects projects under CWD
- **Total: 10 MCP children**

**Worker** (CWD = worktree `/orchestra/worktrees/.../fix-calltrack-js/`):
- websearch — from user mcp-configs
- mcp_stdio (orchestra) — from SDK --mcp-config
- pandoc — from user mcp-configs
- **Total: 3 MCP children**

**Missing from worker**: aperant, playwright, yougile, serena (7 servers!)

### Root Cause Analysis

The worker process command line shows `--mcp-config {"mcpServers": {"orchestra": {...}}}` without `--strict-mcp-config`. So it **should** merge with discovered servers. But it only has 3.

**Hypothesis confirmed by testing**: The SDK-spawned CLI sessions receive a reduced set of MCP servers compared to interactive CLI sessions. The likely cause:

1. **Plugins not loaded**: SDK sessions may skip plugin sync (the `--bare` flag docs mention "skip hooks, LSP, plugin sync..."). Without the `--setting-sources` flag explicitly including `"user"`, plugin-based MCP (serena) may not load.

2. **mcp-configs not discovered**: The `~/.claude/mcp-configs/*.json` files may require explicit setting-source `"user"` to load in SDK mode.

3. **CWD mismatch for project-level**: Worker CWD is a worktree (`/orchestra/worktrees/.../worker-name/`), not the actual project root. Project-level `.claude/settings.json` is not found.

### Our `_load_scope_mcp_servers(scope)` Fix — Does It Work?

**No, it's insufficient.** It reads `<scope>/.claude/settings.json` which has no MCP servers for any current project. The actual MCP servers are in:
- `~/.claude/mcp-configs/*.json` (user-level, separate files)
- `~/.claude/plugins/*/` (plugin-provided)

Our fix only catches the rare case of project-specific MCP in `.claude/settings.json`. The real problem is user-level MCP and plugins not loading.

### Solutions (ranked by reliability)

**Solution 1: Pass `setting_sources=["user", "project", "local"]` in SDK options** ⭐

```python
options = ClaudeAgentOptions(
    ...
    setting_sources=["user", "project", "local"],
)
```

This tells the CLI to load all setting levels, including user mcp-configs and plugins.

Pros: One-line fix. CLI handles all discovery natively.
Cons: Loads ALL user MCP (some may be unwanted). Need to test if this actually enables mcp-configs loading.

**Solution 2: Read user mcp-configs and pass via `--mcp-config`**

```python
def _load_user_mcp_servers() -> dict:
    servers = {}
    mcp_configs_dir = Path.home() / ".claude" / "mcp-configs"
    if not mcp_configs_dir.is_dir():
        return servers
    for f in mcp_configs_dir.glob("*.json"):
        if "disabled" in f.stem:
            continue
        try:
            data = json.loads(f.read_text())
            for k, v in data.get("mcpServers", {}).items():
                servers[k] = v
        except Exception:
            pass
    return servers
```

Then merge into `ClaudeAgentOptions.mcp_servers`.

Pros: Explicit control over which MCP servers workers get.
Cons: Doesn't handle plugins (serena). Need to also read plugin `.mcp.json` files.

**Solution 3: Read everything (user mcp-configs + plugins + project settings)**

Combine Solution 2 with plugin scanning:

```python
def _discover_all_mcp_servers(scope: str) -> dict:
    servers = {}
    # User mcp-configs
    for f in (Path.home() / ".claude" / "mcp-configs").glob("*.json"):
        if "disabled" in f.stem:
            continue
        ...merge servers...
    # Plugin MCP
    for mcp_json in (Path.home() / ".claude" / "plugins").rglob(".mcp.json"):
        ...merge servers...
    # Global settings.json
    ...merge from ~/.claude/settings.json mcpServers...
    # Project settings
    ...merge from <scope>/.claude/settings.json...
    # Filter out "orchestra" (we pass our own)
    servers.pop("orchestra", None)
    return servers
```

Pros: Complete MCP parity with interactive CLI.
Cons: Complex. Duplicates CLI's own discovery logic. Plugin configs may have special resolution rules.

**Recommendation: Try Solution 1 first** (`setting_sources`). It's one line and leverages the CLI's own discovery. If that doesn't work, fall back to Solution 2+3.

### Serena Special Case

Serena uses `--project-from-cwd` or `--project <path>` to detect which codebases to index. When the orchestrator runs in `/mnt/data/Projects/Python/Parsing`, serena finds 4 sub-projects.

For workers in worktrees, serena would need explicit `--project <path>` pointing to the actual project root, not the worktree. This requires either:
- Symlink `.serena/` config into worktree
- Custom serena MCP config per worker with explicit project paths
- Or: don't give serena to workers (they have `grep`/`Read` which is sufficient for most tasks)

### Automatic, Zero-Cognitive-Load Approach

The orchestrator should NOT think about MCP. Workers should inherit automatically.

Implementation:
1. At `_make_backend()` time, discover all user-level MCP servers (mcp-configs + global settings)
2. Merge with orchestra MCP (orchestra overrides)
3. For serena: pass `--project <scope>` instead of `--project-from-cwd`
4. Pass everything via `ClaudeAgentOptions.mcp_servers`

This way every worker gets the same MCP servers as an interactive CLI session, plus orchestra MCP on top.

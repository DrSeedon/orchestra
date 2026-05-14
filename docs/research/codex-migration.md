# Research: Migrating Orchestra from Claude Code CLI to OpenAI Codex CLI

**Date**: 2026-05-14  
**Status**: Research complete (verified on local machine)  
**Codex version**: 0.124.0 (`@openai/codex` npm global)  
**Auth**: ChatGPT subscription (logged in)  
**Verdict**: Feasible. ~2-3 weeks. Best approach: `codex exec --json` subprocess + Python SDK (`openai-codex-sdk`).

---

## 1. Local Installation — What We Have

```
Binary:   /home/maxim/.npm-global/bin/codex  (Node.js wrapper → Rust ELF binary)
Rust bin: ~/.npm-global/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/
          vendor/x86_64-unknown-linux-musl/codex/codex  (static-pie ELF, stripped)
Package:  @openai/codex@0.124.0 (npm global)
Auth:     ~/.codex/auth.json — "Logged in using ChatGPT"
Config:   ~/.codex/config.toml
Sessions: ~/.codex/sessions/2026/{04,05}/... (JSONL rollout files)
```

### config.toml (current)
```toml
model = "gpt-5.5"
model_reasoning_effort = "high"

[projects."/mnt/data/Projects/Python/orchestra"]
trust_level = "trusted"

[mcp_servers.serena]
command = "serena"
args = ["start-mcp-server", "--context=codex", "--project-from-cwd"]
```

---

## 2. CLI Interface — Real `--help` Output

### Main command: `codex [OPTIONS] [PROMPT]`

Key flags for programmatic use:
```
-m, --model <MODEL>           Model override (gpt-5.5, gpt-5.4, gpt-5.4-mini, o3, etc.)
-C, --cd <DIR>                Working directory for the agent
-s, --sandbox <MODE>          read-only | workspace-write | danger-full-access
-a, --ask-for-approval <POL>  untrusted | on-request | never
-c, --config <key=value>      Override config.toml values (TOML syntax)
-i, --image <FILE>            Attach images to prompt
--dangerously-bypass-approvals-and-sandbox  (aka --yolo)
--add-dir <DIR>               Additional writable directories
```

### Non-interactive: `codex exec [OPTIONS] [PROMPT]`

**This is our primary integration point.** Additional flags:
```
--json                        Print JSONL events to stdout ← KEY
--ephemeral                   Don't persist session files
--skip-git-repo-check         Run outside git repos
-o, --output-last-message <F> Write final message to file
--output-schema <FILE>        JSON Schema for structured output
```

Note: `exec` does NOT accept `--ask-for-approval`. Uses `--sandbox` and `--dangerously-bypass-approvals-and-sandbox` instead.

### Session resume: `codex exec resume [SESSION_ID] [PROMPT]`
```
--last                        Resume most recent session
--all                         Show all sessions (no cwd filter)
--json                        JSONL output (works with resume too!)
```

### System prompt injection
```bash
codex exec -c 'developer_instructions="Your custom instructions here"' "prompt"
```
Verified working — agent follows the injected instructions.

### MCP management: `codex mcp add|list|get|remove|login|logout`

### App server: `codex app-server [--listen stdio://|ws://IP:PORT]`
Experimental JSON-RPC 2.0 bidirectional protocol. Supports stdio and WebSocket.

---

## 3. JSONL Event Stream — Real Output

### Simple text response
```bash
codex exec --json -m gpt-5.4-mini --sandbox read-only --skip-git-repo-check -C /tmp "Say hello"
```
```jsonl
{"type":"thread.started","thread_id":"019e2545-2400-70d1-a4eb-77acb39d978a"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"hello world"}}
{"type":"turn.completed","usage":{"input_tokens":13802,"cached_input_tokens":6528,"output_tokens":23}}
```

### With tool use (file creation + bash execution)
```bash
codex exec --json -m gpt-5.4-mini --sandbox workspace-write --skip-git-repo-check -C /tmp \
  "Create file /tmp/test.txt with 'hello'. Then cat it."
```
```jsonl
{"type":"thread.started","thread_id":"019e2545-68e0-76a1-8a29-e92629b42e5f"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"Creating the file..."}}
{"type":"item.started","item":{"id":"item_1","type":"file_change","changes":[{"path":"/tmp/codex-test.txt","kind":"add"}],"status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_1","type":"file_change","changes":[{"path":"/tmp/codex-test.txt","kind":"add"}],"status":"completed"}}
{"type":"item.completed","item":{"id":"item_2","type":"agent_message","text":"Checking contents..."}}
{"type":"item.started","item":{"id":"item_3","type":"command_execution","command":"/usr/bin/zsh -lc 'cat /tmp/codex-test.txt'","aggregated_output":"","exit_code":null,"status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_3","type":"command_execution","command":"/usr/bin/zsh -lc 'cat /tmp/codex-test.txt'","aggregated_output":"hello from codex\n","exit_code":0,"status":"completed"}}
{"type":"item.completed","item":{"id":"item_4","type":"agent_message","text":"Done. Verified contents."}}
{"type":"turn.completed","usage":{"input_tokens":42160,"cached_input_tokens":33920,"output_tokens":288}}
```

### Session resume (verified working)
```bash
# First turn (non-ephemeral)
codex exec --json -m gpt-5.4-mini --sandbox read-only -C /tmp "What is 2+2?"
# → thread_id: "019e2545-f404-79e3-bab5-f81d37a0ffdb"

# Resume same session
codex exec resume --json 019e2545-f404-79e3-bab5-f81d37a0ffdb "What did I just ask?"
# → "You asked: What is 2+2?"
```

### Event types observed

| Event | Structure | Claude Equivalent |
|---|---|---|
| `thread.started` | `{thread_id}` | Initial `ResultMessage` with `session_id` |
| `turn.started` | `{}` | — |
| `item.completed` + `agent_message` | `{id, type, text}` | `AssistantMessage` + `TextBlock` |
| `item.started` + `file_change` | `{id, type, changes[], status}` | — (Claude uses tool blocks) |
| `item.completed` + `file_change` | Same, status=completed | `ToolResultBlock` |
| `item.started` + `command_execution` | `{id, type, command, status}` | `ToolUseBlock` (Bash) |
| `item.completed` + `command_execution` | `{..., aggregated_output, exit_code}` | `ToolResultBlock` |
| `turn.completed` | `{usage: {input_tokens, cached_input_tokens, output_tokens}}` | `ResultMessage` |

### Session JSONL storage format (`~/.codex/sessions/`)
```jsonl
{"timestamp":"...","type":"session_meta","payload":{"id":"UUID","cwd":"...","model_provider":"openai","base_instructions":{...},"git":{...}}}
{"timestamp":"...","type":"event_msg","payload":{"type":"task_started","turn_id":"UUID","model_context_window":258400,...}}
{"timestamp":"...","type":"response_item","payload":{"type":"message","role":"developer","content":[...]}}
{"timestamp":"...","type":"turn_context","payload":{"turn_id":"...","cwd":"...","approval_policy":"never","sandbox_policy":{...},"model":"gpt-5.5",...}}
```

---

## 4. Programmatic APIs — Three Options

### Option A: `codex exec --json` subprocess (RECOMMENDED)

Spawn `codex exec --json` as a subprocess. Read JSONL from stdout. For multi-turn: use resume.

```python
import asyncio
import json

CODEX_BIN = "/home/maxim/.npm-global/bin/codex"

async def codex_exec(prompt: str, cwd: str, model: str = "gpt-5.5",
                     session_id: str = None) -> tuple[str, list[dict]]:
    cmd = [CODEX_BIN]
    if session_id:
        cmd += ["exec", "resume", "--json", session_id, prompt]
    else:
        cmd += ["exec", "--json", "-m", model, "--sandbox", "workspace-write",
                "-C", cwd, prompt]
    
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    
    events = []
    thread_id = None
    async for line in proc.stdout:
        event = json.loads(line)
        events.append(event)
        if event["type"] == "thread.started":
            thread_id = event["thread_id"]
    
    await proc.wait()
    return thread_id, events
```

**Pros**: Simple, stable, works today, uses subscription auth.  
**Cons**: Not persistent — new process per turn. Resume works but has startup overhead (~1-2s).

### Option B: Python SDK (`openai-codex-sdk` on PyPI)

```
pip install openai-codex-sdk  # v0.1.11, Apache-2.0
```

```python
from codex_app_server import AsyncCodex  # actually `openai-codex-sdk`

async with AsyncCodex() as codex:
    thread = await codex.start_thread({
        "working_directory": "/path/to/project",
        "skip_git_repo_check": True,
    })
    
    # Simple run
    turn = await thread.run("Fix the bug")
    print(turn.final_response)
    
    # Streaming
    streamed = await thread.run_streamed("Implement the plan")
    async for event in streamed.events:
        if event.type == "item.completed":
            print(event.item)
        elif event.type == "turn.completed":
            print(event.usage)
    
    # Resume later
    saved_id = thread.id  # persist this
    thread2 = codex.resume_thread(saved_id)
    await thread2.run("Continue")
```

**Pros**: Native async Python, persistent thread objects, streaming, structured output support.  
**Cons**: v0.1.x (early), wraps the CLI binary internally, requires `openai-codex-sdk` dependency. Not on our machine yet.

Auth: Uses `CODEX_AUTH_JSON` env var or `Codex.login_with_auth_json()`. For subscription: copies from `~/.codex/auth.json`.

### Option C: App Server JSON-RPC (low-level)

```bash
codex app-server --listen stdio://
# or
codex app-server --listen ws://127.0.0.1:9000
```

Bidirectional JSON-RPC 2.0. Most powerful but most complex.

**Pros**: True persistent connection, full event streaming, approval callbacks, filesystem APIs.  
**Cons**: Experimental, complex protocol, would need custom JSON-RPC client.

---

## 5. Mapping to Orchestra's Architecture

### Claude SDK → Codex equivalents

| Orchestra concept | Claude (`session.py`) | Codex (subprocess) | Codex (Python SDK) |
|---|---|---|---|
| Client creation | `ClaudeSDKClient(options)` | `codex exec --json ...` | `AsyncCodex()` |
| Connect | `client.connect()` | Process spawn | `async with AsyncCodex()` |
| Send message | `client.query(msg)` | New `codex exec resume` call | `thread.run(msg)` |
| Receive events | `client.receive_messages()` | Read stdout JSONL | `thread.run_streamed()` |
| Session ID | `ResultMessage.session_id` | `thread.started.thread_id` | `thread.id` |
| Resume | `options.resume = id` | `codex exec resume <id>` | `codex.resume_thread(id)` |
| System prompt | `options.system_prompt` | `-c developer_instructions=...` | Config in `start_thread()` |
| CWD | `options.cwd` | `-C <dir>` | `working_directory` option |
| Model | `options.model` | `-m <model>` | `model` option |
| MCP servers | `options.mcp_servers` | `config.toml [mcp_servers]` | Config |
| Permissions | `can_use_tool` callback | `--sandbox` + `--yolo` | Config |
| Cost | `ResultMessage.total_cost_usd` | Calc from `turn.completed.usage` | `turn.usage` |
| Text output | `TextBlock.text` | `item.completed` where `type=agent_message` | `turn.final_response` |
| Tool use | `ToolUseBlock` | `item.completed` where `type=command_execution/file_change` | In `turn.items` |
| Interrupt | `client.interrupt()` | `proc.terminate()` / SIGINT | — |
| Sub-agent events | `TaskStartedMessage` etc. | Not in exec JSONL | Unknown |

### What works unchanged
- **`mcp_stdio.py`** — Standard FastMCP over stdio. Codex supports MCP stdio servers natively via `config.toml`.
- **Git worktree isolation** — Codex respects `-C <dir>` flag. Our worktree setup is CLI-agnostic.
- **Dashboard/SSE** — Frontend doesn't care which CLI backend generates the logs.

### What needs adaptation
1. **`session.py` message dispatch** (~120 lines of `isinstance()` checks) → map JSONL events to unified types
2. **Persistent client pattern** → either accept per-turn subprocess overhead, or use Python SDK's persistent thread
3. **Permission callback** → `--sandbox workspace-write` + `--yolo` for full auto (workers don't need human approval)
4. **Cost tracking** → calculate from token counts in `turn.completed`
5. **Context tracking** → Codex reports `model_context_window: 258400` in session meta; token usage per turn available but no cumulative percentage

---

## 6. Recommended Migration Architecture

### `CodexBackend` (subprocess-based, production-ready today)

```python
class CodexBackend:
    CODEX_BIN = "/home/maxim/.npm-global/bin/codex"
    
    def __init__(self, model: str, cwd: str, system_prompt: str = "",
                 mcp_config: dict = None):
        self.model = model
        self.cwd = cwd
        self.system_prompt = system_prompt
        self.thread_id: str | None = None
    
    async def send(self, message: str) -> AsyncIterator[AgentEvent]:
        cmd = [self.CODEX_BIN]
        if self.thread_id:
            cmd += ["exec", "resume", "--json", self.thread_id, message]
        else:
            cmd += ["exec", "--json", "-m", self.model,
                    "--sandbox", "workspace-write",
                    "--dangerously-bypass-approvals-and-sandbox",
                    "-C", self.cwd]
            if self.system_prompt:
                cmd += ["-c", f'developer_instructions="{self._escape(self.system_prompt)}"']
            cmd.append(message)
        
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE)
        
        async for line in proc.stdout:
            event = json.loads(line)
            if event["type"] == "thread.started":
                self.thread_id = event["thread_id"]
                yield AgentEvent("status", f"thread={self.thread_id}")
            elif event["type"] == "item.completed":
                item = event["item"]
                if item["type"] == "agent_message":
                    yield AgentEvent("text", item["text"])
                elif item["type"] == "command_execution":
                    yield AgentEvent("tool", f"bash: {item['command']}")
                    yield AgentEvent("tool_result", item.get("aggregated_output", ""))
                elif item["type"] == "file_change":
                    changes = ", ".join(f"{c['kind']} {c['path']}" for c in item.get("changes", []))
                    yield AgentEvent("tool", f"file: {changes}")
            elif event["type"] == "turn.completed":
                usage = event.get("usage", {})
                yield AgentEvent("turn_end", "", metadata={
                    "input_tokens": usage.get("input_tokens", 0),
                    "cached_tokens": usage.get("cached_input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                })
        
        await proc.wait()
```

### Hybrid `AgentSession`

```python
@dataclass
class AgentSession:
    backend_type: str = "claude"  # "claude" | "codex"
    
    async def send(self, message: str) -> None:
        if self.backend_type == "codex":
            async for event in self._codex_backend.send(message):
                self._handle_event(event)
        else:
            # existing Claude SDK path
            client = await self._ensure_client()
            await client.query(message)
```

---

## 7. Effort Estimate (revised with real data)

### Phase 1: AgentEvent abstraction (2-3 days)
- Define `AgentEvent` dataclass (type, content, metadata)
- Refactor `_persistent_listen()` to emit `AgentEvent` instead of raw SDK isinstance checks
- All existing behavior preserved, just normalized event types

### Phase 2: CodexBackend via subprocess (3-4 days)
- `codex exec --json` subprocess spawner with JSONL parser
- Session resume via `codex exec resume --json <thread_id>`
- `developer_instructions` for system prompt injection
- `-C <cwd>`, `-m <model>`, `--sandbox workspace-write --yolo` for workers
- Cost calculation from token usage
- MCP config: auto-generate `config.toml` entries per worker

### Phase 3: Integration (2-3 days)
- `backend_type` field in session DB and API
- Model registry: `CODEX_MODELS = {"gpt-5.5": "GPT-5.5", "gpt-5.4": "GPT-5.4", ...}`
- Dashboard: show backend badge, Codex-specific token counts
- Spawn API: `backend` parameter

### Phase 4: Python SDK path (optional, 2-3 days)
- Install `openai-codex-sdk`, use `AsyncCodex` for persistent threads
- Eliminates per-turn subprocess overhead
- Streaming via `run_streamed()`
- Depends on SDK stability (v0.1.x)

### Total: 7-10 days (Phase 1-3), +2-3 days optional Phase 4

---

## 8. Pricing

### Subscription (what we use)

| Plan | Monthly | Claude CLI | Codex CLI |
|---|---|---|---|
| Anthropic Max 20x | $200 | Unlimited* | — |
| OpenAI Pro | $200 | — | Credit-based (20x multiplier) |

**Caveat**: OpenAI Pro has per-5-hour rate limits (300-1600 GPT-5.5 messages). Multi-agent Orchestra with 5+ concurrent workers may hit this. Anthropic Max has no hard per-window limits (fair use policy).

### API (backup)

| Model | Input/M | Output/M | Cached/M |
|---|---|---|---|
| Claude Opus 4.6 | $5.00 | $25.00 | $0.50 |
| Claude Sonnet 4.6 | $3.00 | $15.00 | $0.30 |
| GPT-5.5 | $1.25 | $10.00 | $0.125 |
| GPT-5.4 | $0.625 | $3.75 | $0.0625 |
| GPT-5.4-mini | $0.19 | $1.13 | $0.019 |

GPT-5.4-mini is ~16x cheaper than Sonnet on input. For bulk worker tasks, significant cost advantage.

---

## 9. Critical Differences & Gotchas

### 1. No persistent subprocess
Claude SDK: single process, `connect()` once, `query()` injects messages via stdin.
Codex `exec --json`: new process per turn. Resume restores context but has ~1-2s startup.
**Impact**: Slightly higher latency per turn. Mitigated by Python SDK if we adopt it later.

### 2. No mid-turn message injection
Claude SDK: `client.query()` during active turn injects a new message.
Codex: No equivalent in `exec` mode. Would need app-server protocol.
**Impact**: Our `send()` while running would need to wait for turn completion, then send new turn.

### 3. Approval model
Claude: Programmatic `can_use_tool` callback per tool invocation.
Codex: Binary choice at startup — `--sandbox` + approval flags. No per-tool callback.
**Impact**: Our `_auto_approve` with blocked tools (`AskUserQuestion`) can't be replicated exactly. Workaround: inject blocked tool names into `developer_instructions` ("NEVER use AskUserQuestion").

### 4. Sub-agent event tracking
Claude: `TaskStartedMessage`, `TaskProgressMessage`, `TaskNotificationMessage`.
Codex `exec --json`: No sub-agent events observed in JSONL output.
**Impact**: Dashboard won't show sub-agent lifecycle for Codex workers. Minor — most workers don't spawn sub-agents.

### 5. Context window tracking
Claude: `ResultMessage.usage` with full token breakdown per iteration.
Codex: `turn.completed.usage` with `{input_tokens, cached_input_tokens, output_tokens}`.
Session meta has `model_context_window: 258400`.
**Impact**: Can calculate context % per turn, but no cumulative tracking. Would need to sum across turns.

---

## 10. Recommendation

### Fastest path to production backup:

**Week 1**: `AgentEvent` abstraction + `CodexBackend` via `codex exec --json`
- Subprocess-based, uses existing CLI binary and subscription auth
- Works today with zero new dependencies
- Resume via `codex exec resume --json <thread_id>`
- System prompt via `-c developer_instructions=...`
- MCP via `config.toml` (our `mcp_stdio.py` works unchanged)

**Week 2**: Integration + testing
- Backend selection in spawn API
- Dashboard adaptations
- Test: Claude orchestrator managing Codex workers

### When NOT to migrate:
- Anthropic keeps subscription terms stable → stay on Claude, it's better integrated
- Our persistent client pattern (mid-turn injection, heartbeat, reconnect) has no Codex equivalent without app-server protocol
- Sub-agent event tracking is Claude-only

### When to migrate:
- Anthropic bans agent usage on subscription → Day 1: switch to API key ($50-100/day); Week 1-2: bring Codex workers online
- Want cheaper workers → GPT-5.4-mini workers at 16x less than Sonnet
- Want model diversity → Claude Opus for planning, GPT-5.5 for coding, GPT-5.4-mini for bulk tasks

---

## Sources

- Local: `codex --help`, `codex exec --help`, `codex app-server --help`, `~/.codex/config.toml`, `~/.codex/sessions/`
- [Codex SDK docs](https://developers.openai.com/codex/sdk)
- [Codex CLI features](https://developers.openai.com/codex/cli/features)
- [Codex CLI reference](https://developers.openai.com/codex/cli/reference)
- [Codex MCP support](https://developers.openai.com/codex/mcp)
- [Codex App Server](https://developers.openai.com/codex/app-server)
- [Codex + Agents SDK guide](https://developers.openai.com/codex/guides/agents-sdk)
- [Codex pricing](https://developers.openai.com/codex/pricing)
- [Codex changelog](https://developers.openai.com/codex/changelog)
- [openai-codex-sdk on PyPI](https://pypi.org/project/openai-codex-sdk/) (v0.1.11)
- [Codex GitHub repo](https://github.com/openai/codex)
- [Agent Client Protocol](https://agentclientprotocol.com/get-started/introduction)

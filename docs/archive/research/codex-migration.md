# Research: Migrating Orchestra from Claude Code CLI to OpenAI Codex CLI

**Date**: 2026-05-14  
**Status**: Research complete (verified on local machine)  
**Codex version**: 0.124.0 (`@openai/codex` npm global)  
**Auth**: ChatGPT subscription (logged in)  
**Verdict**: Feasible. ~7-10 days. Best approach: `codex exec --json` subprocess with raw JSON parsing. Python SDK exists but has bugs.

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
pip install openai-codex-sdk  # v0.1.11, Apache-2.0, Python >=3.10
```

**Installed and tested locally.** The SDK is a thin wrapper around `codex exec --json` subprocess:

```python
# Actual SDK source (exec.py line 128-131):
proc = await asyncio.create_subprocess_exec(
    self.executable_path, *command_args,
    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    env=env,
)
# Writes prompt to stdin, reads JSONL from stdout. That's it.
```

**API surface (verified from source):**
```python
from openai_codex_sdk import Codex

codex = Codex({"codex_path_override": "/home/maxim/.npm-global/bin/codex"})
thread = codex.start_thread({
    "model": "gpt-5.4-mini",
    "sandbox_mode": "workspace-write",
    "working_directory": "/tmp",
    "skip_git_repo_check": True,
    "approval_policy": "never",  # also: "on-request", "untrusted"
    "model_reasoning_effort": "high",  # "minimal", "low", "medium", "high"
    "network_access_enabled": True,
    "web_search_enabled": True,
})

# Buffered (returns when turn completes)
turn = await thread.run("Fix the bug")
print(turn.final_response)  # str
print(turn.items)            # List[ThreadItem]
print(turn.usage)            # Usage(input_tokens, cached_input_tokens, output_tokens)

# Streaming (async generator of events)
streamed = await thread.run_streamed("Implement the plan")
async for event in streamed.events:
    # event types: ThreadStartedEvent, TurnStartedEvent, ItemStartedEvent,
    #              ItemUpdatedEvent, ItemCompletedEvent, TurnCompletedEvent,
    #              TurnFailedEvent, ThreadErrorEvent
    pass

# Resume (persists in ~/.codex/sessions/)
saved_id = thread.id
thread2 = codex.resume_thread(saved_id)
await thread2.run("Continue")
```

**Verified working** (simple text, resume). **BUT has a critical bug:**

#### SDK Bug: `FileChangeItem.status` missing `"in_progress"`

SDK v0.1.11 defines `PatchApplyStatus = Literal["completed", "failed"]` but CLI v0.124.0 sends
`item.started` events with `status: "in_progress"`. This crashes both `run()` and `run_streamed()`
with a Pydantic `ValidationError` whenever the agent creates or edits files.

**Impact**: SDK is unusable for any task involving file changes (i.e., all real coding tasks).
**Workaround**: Monkey-patching fails because Pydantic union validators cache the original models.
Would need to patch the installed source files directly or wait for SDK update.

**Verdict**: SDK is architecturally correct (same subprocess approach we'd write ourselves) but
too immature. Use raw `codex exec --json` + `json.loads()` instead.

Auth: Inherits `~/.codex/auth.json` automatically. For programmatic: `CODEX_AUTH_JSON` env var
or `Codex.login_with_auth_json()`.

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

## 9. Critical Differences — Problems & Solutions

### 1. No persistent subprocess → SOLVABLE via app-server

**Problem**: Claude SDK keeps a single process alive. `codex exec --json` spawns new process per turn (~1-2s startup).

**Solution A** (easy): Accept per-turn overhead. Use `codex exec resume --json <thread_id>` for multi-turn. 1-2s startup is negligible for agent tasks that take 30-300s.

**Solution B** (advanced): Use `codex app-server --listen ws://127.0.0.1:<port>` per worker. This gives a persistent WebSocket connection with full JSON-RPC protocol:
```
initialize → thread/start → turn/start → [stream events] → turn/start again → ...
```
Thread persists across turns. No subprocess overhead. But requires custom JSON-RPC client.

**Solution C** (experimental): `codex exec-server --listen ws://127.0.0.1:0` — standalone WebSocket service for spawning/controlling processes. Less relevant for our use case.

### 2. No mid-turn message injection → SOLVABLE via `turn/steer`

**Problem**: Claude SDK `client.query()` injects messages during active turns. Codex `exec` has no equivalent.

**Solution**: App-server protocol has `turn/steer` method — "adds user input to an already in-flight regular turn without starting a new turn." Requires `threadId`, input array, and `expectedTurnId`.

This is the exact equivalent of Claude's mid-turn injection. Only available in app-server mode, not `codex exec`.

**For subprocess mode**: Wait for turn completion, then `codex exec resume` with new message. Slightly different semantics but functionally equivalent for Orchestra's use cases (our `send()` during running queues the message anyway).

### 3. Per-tool approval → SOLVABLE via config

**Problem**: Claude has `can_use_tool` callback for per-tool approval/deny. Codex has global sandbox/approval flags.

**Solution**: Multiple layers of control exist:
1. `approval_policy` with granular sub-categories: `sandbox_approval`, `rules`, `mcp_elicitations`, `skill_approval`
2. `execpolicy` rules in `.rules` files — prefix-based command patterns with `prompt` or `forbidden` decisions
3. Per-MCP-server `enabled_tools` / `disabled_tools` lists
4. Per-app `tools.<tool>.approval_mode: auto | prompt | approve`
5. `developer_instructions` — instruct the model to never use specific tools

For Orchestra workers: `--sandbox workspace-write` + `approval_policy: "never"` + `developer_instructions` with "NEVER use AskUserQuestion" covers our needs.

### 4. Sub-agent events → PARTIAL via built-in subagents

**Problem**: Claude emits `TaskStartedMessage`, `TaskProgressMessage`, `TaskNotificationMessage` for sub-agents.

**Reality**: Codex has **built-in subagent support** (GA since March 2026):
- `agents.max_threads = 6` (concurrent threads)
- `agents.max_depth = 1` (nesting depth)
- Three types: `default`, `worker`, `explorer`
- Custom agents with `developer_instructions`, `model`, `sandbox_mode`, `mcp_servers`

**But**: Subagent events are NOT exposed in `codex exec --json` output. They're visible in the interactive TUI (`/agent` command) and possibly in app-server notifications. For our dashboard, we wouldn't see subagent lifecycle.

**Workaround**: Our workers don't typically spawn sub-agents (Orchestra itself is the orchestrator). If a Codex worker uses subagents, the results still come back in the final turn output.

### 5. Context window tracking → SOLVABLE

**Problem**: Claude gives cumulative context % per turn. Codex gives per-turn tokens.

**Solution**: Codex session meta includes `model_context_window: 258400`. Each `turn.completed` gives `{input_tokens, cached_input_tokens, output_tokens}`. Track `input_tokens` as the current context size:

```python
context_pct = int(usage["input_tokens"] * 100 / 258400)
```

The `input_tokens` count in each turn represents the full context sent to the model (including all previous turns), so it naturally grows as the session progresses. No manual summation needed.

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

## 11. Community Orchestrators — Others Already Doing This

### Symphony (by OpenAI themselves)

[github.com/openai/symphony](https://github.com/openai/symphony) — Open-source spec for Codex orchestration. Turns a Linear board into a continuous dispatch system: every open task gets an agent, agents run until done, humans review results. OpenAI reported **500% increase in landed PRs** on some teams.

Written in Elixir/BEAM. Released April 27, 2026. Not a standalone product — it's a SPEC.md + reference implementation.

**Relevance**: Similar architecture to Orchestra but focused on issue tracker integration. Validates that multi-agent Codex orchestration works at scale.

### Oh-My-Codex (OMX)

[github.com/Yeachan-Heo/oh-my-codex](https://github.com/Yeachan-Heo/oh-my-codex) — Community orchestration layer. Provides:
- 33 specialized prompts + 36 workflow skills
- Isolated parallel execution with git worktrees
- Team runtime with tmux coordination
- Persistent state & memory MCP servers

v0.13.1, MIT license. Uses `$team` for coordinated parallel execution with worktree isolation — very similar to our worker model.

### Codex-Orchestrator / Codex-YOLO (tmux-based)

Community tools for spawning multiple Codex agents in tmux sessions:
- `codex-orchestrator start/jobs/send/capture` — job management with metadata persistence
- `codex-yolo` — auto-approval daemon polling every 0.3s, audit logs to `/tmp/`
- Both use git worktrees for isolation

### Parallel Patterns in Production

From [codex.danielvaughan.com](https://codex.danielvaughan.com/2026/04/18/running-multiple-codex-agents-parallel-orchestration/):
- **3-5 concurrent agents** is the practical sweet spot
- 8-10 GB RAM per agent
- Each agent should own distinct files to avoid merge conflicts
- Token budgets recommended: hard limits (180k frontend, 280k backend)
- Auto-kill agents stuck after 3+ iterations on same error

---

## 12. Python SDK — Source Code Analysis

### Architecture (from installed source)

```
openai_codex_sdk/
├── codex.py      — Codex class: start_thread(), resume_thread()
├── thread.py     — Thread class: run(), run_streamed()
├── exec.py       — CodexExec: subprocess spawner, builds CLI args
├── types.py      — Pydantic models: events, items, options
├── parsing.py    — JSONL → Pydantic model dispatch
├── auth.py       — login_with_auth_json(), device_code flow
├── install.py    — Download/install Codex CLI binary
├── abort.py      — AbortController/Signal for cancellation
├── output_schema_file.py — Temp file for structured output schema
└── utils.py      — normalize_input() for text/image entries
```

### How it works internally

1. `Codex()` finds the `codex` binary (vendored or PATH)
2. `start_thread()` creates `Thread(exec_, options, thread_id=None)`
3. `thread.run(prompt)` → calls `thread.run_streamed()` → collects all events → returns `Turn`
4. `_run_streamed_internal()` builds CLI args from options, calls `exec_.run(args)`
5. `CodexExec.run()` does `asyncio.create_subprocess_exec("codex", "exec", "--experimental-json", ...)`:
   - Writes prompt to stdin (not as CLI arg!)
   - Reads JSONL lines from stdout
   - Returns async iterator of raw strings
6. `parse_thread_event_line()` deserializes each line to Pydantic model via dispatch dict

### Key detail: `--experimental-json` vs `--json`

The SDK uses `--experimental-json` flag (line 52 of exec.py), not `--json`. Both seem to work identically. The `--json` flag is the documented one.

### ThreadItem types (SDK's Pydantic models)

```python
ThreadItem = Union[
    AgentMessageItem,       # {"type": "agent_message", "text": "..."}
    ReasoningItem,          # {"type": "reasoning", "text": "..."}
    CommandExecutionItem,   # {"type": "command_execution", "command": "...", "aggregated_output": "...", "exit_code": N}
    FileChangeItem,         # {"type": "file_change", "changes": [...], "status": "completed"}
    McpToolCallItem,        # {"type": "mcp_tool_call", "server": "...", "tool": "...", "arguments": {...}}
    WebSearchItem,          # {"type": "web_search", "query": "..."}
    TodoListItem,           # {"type": "todo_list", "items": [...]}
    ErrorItem,              # {"type": "error", "message": "..."}
    UnknownThreadItem,      # Fallback for forward-compatibility
]
```

**Notable**: `McpToolCallItem` has `server`, `tool`, `arguments`, `result`, `error` fields. This means MCP tool calls are fully visible in the event stream — we can track our Orchestra MCP tool invocations (send_message, spawn_worker, etc.).

### ThreadOptions (all available config)

```python
class ThreadOptions:
    model: str                          # "gpt-5.5", "gpt-5.4", etc.
    sandbox_mode: SandboxMode           # "read-only" | "workspace-write" | "danger-full-access"
    working_directory: str              # -C flag
    skip_git_repo_check: bool           # --skip-git-repo-check
    model_reasoning_effort: str         # "minimal" | "low" | "medium" | "high"
    network_access_enabled: bool        # sandbox_workspace_write.network_access
    web_search_enabled: bool            # features.web_search_request
    approval_policy: ApprovalMode       # "never" | "on-request" | "untrusted"
    additional_directories: List[str]   # --add-dir
```

**Missing**: No `developer_instructions` in ThreadOptions. System prompt injection must go through `-c` config override (which the SDK doesn't expose). This is another SDK limitation.

---

## Sources

- Local machine: `codex --help`, `codex exec --help`, `codex app-server --help`, `codex exec-server --help`, `~/.codex/config.toml`, `~/.codex/sessions/`, `~/.codex/auth.json`
- Local SDK source: `/tmp/codex-sdk-test/lib/python3.12/site-packages/openai_codex_sdk/` (all .py files)
- [Codex SDK docs](https://developers.openai.com/codex/sdk)
- [Codex CLI features](https://developers.openai.com/codex/cli/features)
- [Codex CLI reference](https://developers.openai.com/codex/cli/reference)
- [Codex Non-interactive mode](https://developers.openai.com/codex/noninteractive)
- [Codex MCP support](https://developers.openai.com/codex/mcp)
- [Codex Config reference](https://developers.openai.com/codex/config-reference)
- [Codex App Server](https://developers.openai.com/codex/app-server)
- [Codex App Server README (GitHub)](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)
- [Codex Subagents](https://developers.openai.com/codex/subagents)
- [Codex + Agents SDK guide](https://developers.openai.com/codex/guides/agents-sdk)
- [Codex pricing](https://developers.openai.com/codex/pricing)
- [Codex changelog](https://developers.openai.com/codex/changelog)
- [openai-codex-sdk on PyPI](https://pypi.org/project/openai-codex-sdk/) (v0.1.11)
- [Codex GitHub repo](https://github.com/openai/codex)
- [Symphony — OpenAI orchestration spec](https://github.com/openai/symphony)
- [Oh-My-Codex (OMX)](https://github.com/Yeachan-Heo/oh-my-codex)
- [Parallel Codex orchestration patterns](https://codex.danielvaughan.com/2026/04/18/running-multiple-codex-agents-parallel-orchestration/)
- [Agent Client Protocol](https://agentclientprotocol.com/get-started/introduction)

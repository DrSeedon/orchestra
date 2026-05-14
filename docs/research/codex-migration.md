# Research: Migrating Orchestra from Claude Code CLI to OpenAI Codex CLI

**Date**: 2026-05-14  
**Status**: Research complete  
**Verdict**: Feasible but non-trivial. ~2-3 weeks for a hybrid backend. Full migration is structurally possible but loses MCP injection pattern.

---

## 1. What Is Codex CLI?

OpenAI Codex CLI is a terminal-native coding agent (Rust-based, open source: `github.com/openai/codex`). It reads, edits, and executes code in a local directory — functionally equivalent to Claude Code CLI.

### Models
- **GPT-5.5** (default for complex tasks) — flagship
- **GPT-5.4** — fast, cheaper
- **GPT-5.4-mini** — budget
- **GPT-5.3-Codex** — optimized for code tasks (cloud)
- **GPT-5.3-Codex-Spark** — research preview (Pro only)

### Authentication
Two modes:
1. **ChatGPT auth** (default): CLI usage draws from your subscription plan (Plus $20/mo, Pro $200/mo). No extra cost.
2. **API key mode**: Billed per token at standard API rates. GPT-5.5: $1.25/$10 per M input/output tokens.

### Key Difference from Claude Code
Codex has **cloud tasks** — spin up a sandboxed environment, work on a GitHub issue, open a PR. Claude Code is local-only. But for Orchestra's purposes, we use local agent sessions, so this is irrelevant.

---

## 2. Codex SDK — Programmatic API

### TypeScript SDK (`@openai/codex-sdk`)
```typescript
import { Codex } from "@openai/codex-sdk";

const codex = new Codex();
const thread = codex.startThread();
const result = await thread.run("Fix the CI failure");

// Resume later
const thread2 = codex.resumeThread(threadId);
await thread2.run("Pick up where you left off");

// Streaming events
for await (const event of thread.runStreamed("Implement the plan")) {
  // event.type: "item.completed", "turn.completed", etc.
}
```

### Python SDK (`codex_app_server`)
```python
from codex_app_server import AsyncCodex
import asyncio

async def main():
    async with AsyncCodex() as codex:
        thread = await codex.thread_start(model="gpt-5.4")
        result = await thread.run("Fix the bug")
        print(result.final_response)
```

**Critical**: Python SDK is experimental, requires local Codex repo checkout, and uses Pydantic models over JSON-RPC. Not as mature as `claude-agent-sdk`.

### App Server (Low-Level Protocol)
Codex has an "app server" — a JSON-RPC 2.0 bidirectional protocol over stdio or WebSocket. This is the real power:

- `thread/start`, `thread/resume` — session lifecycle
- `turn/start` — send user message
- `item/started`, `item/completed`, delta streams — event notifications
- `item/commandExecution/requestApproval` — permission callbacks
- Threads persist in `~/.codex/sessions`

This is architecturally equivalent to our `claude-agent-sdk` pattern:
| Orchestra (Claude) | Codex App Server |
|---|---|
| `client.connect()` | `initialize` + `thread/start` |
| `client.query(msg)` | `turn/start` with input |
| `client.receive_messages()` | Stream notifications (items, turns) |
| `ResultMessage` | `turn/completed` notification |
| `AssistantMessage` + `TextBlock` | `item/completed` with message type |
| `ToolUseBlock` | `item/completed` with tool_call type |
| `PermissionResultAllow/Deny` | Approval response to `requestApproval` |
| `session_id` for resume | `threadId` for `thread/resume` |

---

## 3. MCP Support in Codex

**Full MCP support.** Both stdio and HTTP transports.

Configuration via `~/.codex/config.toml` or `codex mcp add`:
```toml
[mcp_servers.orchestra]
command = "python"
args = ["-m", "app.mcp_stdio"]
env = { ORCHESTRA_URL = "http://127.0.0.1:8888" }
```

Our `mcp_stdio.py` MCP server would work with Codex **as-is** — it's a standard FastMCP stdio server. Codex just needs the config entry.

**Codex as MCP server**: `codex mcp-server` exposes Codex itself as an MCP server with `codex` and `codex-reply` tools. This enables the OpenAI Agents SDK to orchestrate Codex agents — interesting for a different architecture pattern.

---

## 4. What Maps Cleanly

| Feature | Claude Code | Codex CLI | Migration Effort |
|---|---|---|---|
| Session persistence | `session_id` via SDK | `threadId` via app-server | Low — rename fields |
| Session resume | `options.resume = session_id` | `thread/resume(threadId)` | Low |
| System prompts | `options.system_prompt` | `base-instructions` in config | Low |
| MCP servers (external) | `options.mcp_servers` | `config.toml` `[mcp_servers]` | Low — our MCP server works as-is |
| Permission modes | `permission_mode`, `can_use_tool` callback | `ask-for-approval` + `sandbox` flags | Medium — different approval flow |
| Tool calling | `ToolUseBlock` in `AssistantMessage` | `item/completed` with tool type | Medium — different event structure |
| Working directory | `options.cwd` | `--cd` flag or `workingDirectory` | Low |
| Model selection | `options.model` | `--model` flag or config | Low |
| Streaming events | `receive_messages()` async generator | `runStreamed()` or app-server notifications | Medium |
| Cost tracking | `ResultMessage.total_cost_usd` | Token usage in `turn/completed` | Medium — need to calculate from tokens |
| Context usage | Token counts in `ResultMessage.usage` | Usage data in turn events | Medium |

---

## 5. What Breaks

### 5.1 Deep SDK Type Coupling (`session.py`)

Our `session.py` imports 10+ types from `claude_agent_sdk`:

```python
from claude_agent_sdk import (
    ClaudeSDKClient, ClaudeAgentOptions,
    AssistantMessage, ResultMessage, TextBlock, ToolUseBlock,
    PermissionResultAllow, PermissionResultDeny,
    TaskStartedMessage, TaskProgressMessage, TaskNotificationMessage,
)
from claude_agent_sdk.types import (
    ToolResultBlock, ServerToolResultBlock, UserMessage,
)
```

**Every `isinstance()` check in `_persistent_listen()` must be rewritten.** This is ~120 lines of tightly coupled message dispatch logic.

### 5.2 Persistent Client Pattern

Our pattern:
```
connect() → query() → receive_messages() [infinite async loop] → query() again → ...
```

The Claude SDK keeps a single subprocess alive and injects messages via stdin. Codex's equivalent is the app-server protocol, but:

- **TypeScript SDK** has `thread.run()` / `thread.runStreamed()` — one-shot per turn, not a persistent listener
- **Python SDK** is experimental and wraps the same one-shot pattern
- **App-server** protocol supports persistent connections (stdio/WebSocket) with streaming notifications — this IS the equivalent

**Migration path**: Use the app-server JSON-RPC protocol directly (not the high-level SDK). This gives us the same persistent bidirectional channel.

### 5.3 `tools.py` — In-Process MCP

```python
from claude_agent_sdk import tool, create_sdk_mcp_server
```

This creates an **in-process** MCP server that injects tools directly into the Claude CLI process. We don't actually use this for workers (they use `mcp_stdio.py`), but it exists.

For Codex: MCP servers must be external (stdio or HTTP). No in-process equivalent. But since we already have `mcp_stdio.py`, this is a non-issue.

### 5.4 Permission Callback

Our `_auto_approve` callback:
```python
async def _auto_approve(tool_name, tool_input, _context=None):
    if tool_name in _BLOCKED_TOOLS:
        return PermissionResultDeny(...)
    return PermissionResultAllow(updated_input=tool_input)
```

In Codex, approvals work via the app-server `requestApproval` notification → client responds with accept/decline. Same concept, different mechanism. We'd implement an approval handler in our JSON-RPC client.

### 5.5 Sub-Agent Events

We track `TaskStartedMessage`, `TaskProgressMessage`, `TaskNotificationMessage` for sub-agent lifecycle. Codex's equivalent is unclear — their multi-agent v2 has thread caps and depth handling, but the event model for nested agents isn't well-documented yet.

### 5.6 Cost Calculation

Claude: `ResultMessage.total_cost_usd` gives us a direct dollar amount.
Codex: Returns token counts per turn. We'd need to calculate cost ourselves:
```python
cost = (input_tokens * INPUT_PRICE + output_tokens * OUTPUT_PRICE) / 1_000_000
```

---

## 6. Hybrid Architecture — Running Both

### The `AgentBackend` Abstraction

```python
class AgentBackend(Protocol):
    async def connect(self, options: SessionOptions) -> None: ...
    async def send(self, message: str) -> None: ...
    async def receive_events(self) -> AsyncIterator[AgentEvent]: ...
    async def interrupt(self) -> None: ...
    async def disconnect(self) -> None: ...

@dataclass
class AgentEvent:
    type: str  # "text", "tool_use", "tool_result", "turn_end", "error", "subagent_start", ...
    content: str
    metadata: dict  # session_id, cost, tokens, etc.

class ClaudeBackend(AgentBackend):
    """Wraps claude-agent-sdk ClaudeSDKClient"""
    ...

class CodexBackend(AgentBackend):
    """Wraps Codex app-server JSON-RPC protocol"""
    ...
```

### `AgentSession` Refactor

Replace direct `ClaudeSDKClient` usage with the backend protocol:

```python
@dataclass
class AgentSession:
    backend: str = "claude"  # or "codex"
    _backend: AgentBackend = field(default=None)
    
    def _make_backend(self) -> AgentBackend:
        if self.backend == "codex":
            return CodexBackend(model=self.model, cwd=self.cwd, ...)
        return ClaudeBackend(model=self.model, cwd=self.cwd, ...)
```

### MCP Server — Works for Both

Our `mcp_stdio.py` is a standard MCP server talking HTTP to Orchestra. It's CLI-agnostic. Both Claude Code and Codex can use it.

### Per-Worker Backend Choice

Workers could specify their backend:
```python
await manager.spawn(name="researcher", backend="codex", model="gpt-5.5", ...)
await manager.spawn(name="implementer", backend="claude", model="claude-sonnet-4-6", ...)
```

---

## 7. Effort Estimate

### Phase 1: Backend Abstraction (3-5 days)
- Define `AgentBackend` protocol + `AgentEvent` dataclass
- Extract `ClaudeBackend` from current `session.py`
- Refactor `AgentSession` to use the backend protocol
- Update `_persistent_listen()` to consume `AgentEvent` instead of raw SDK types
- Tests pass with `ClaudeBackend` — zero behavior change

### Phase 2: Codex Backend (5-7 days)
- Implement `CodexBackend` using Codex app-server JSON-RPC protocol
- Handle: connect, thread lifecycle, turn management, event streaming
- Map Codex events to `AgentEvent` types
- Implement approval handler (auto-approve with blocked tools)
- Cost calculation from token counts
- Context percentage estimation

### Phase 3: Integration & Hybrid Mode (3-5 days)
- Backend selection in spawn/session creation
- Model registry for both providers (`MODELS`, `CONTEXT_LIMITS`)
- Dashboard updates (show backend type, Codex-specific metrics)
- Codex MCP config generation (auto-create `config.toml` entries for workers)
- Test hybrid scenario: Claude orchestrator + Codex workers

### Total: ~2-3 weeks of focused work

---

## 8. Pricing Comparison

### Subscription Mode (Flat Rate)

| Plan | Claude (Anthropic) | Codex (OpenAI) |
|---|---|---|
| Individual | Max $200/mo | Pro $200/mo |
| Team/Business | Enterprise (custom) | Business (per-seat + credits) |

Both offer subscription modes where CLI usage is "included." For Orchestra's heavy usage, subscription is the way.

### API Mode (Per Token)

| Model | Input (per M) | Output (per M) | Cache Read |
|---|---|---|---|
| Claude Opus 4.6 | $5.00 | $25.00 | $0.50 |
| Claude Sonnet 4.6 | $3.00 | $15.00 | $0.30 |
| GPT-5.5 | $1.25 | $10.00 | $0.125 |
| GPT-5.4 | $0.625 | $3.75 | $0.0625 |
| GPT-5.4-mini | $0.1875 | $1.13 | $0.01875 |

**Codex is significantly cheaper per token**, especially GPT-5.4-mini which is ~16x cheaper than Sonnet on input.

### Subscription-to-Subscription

Both are ~$200/mo for heavy individual use. The real difference:
- Anthropic subscription: unlimited* within fair use (Max 20x plan)
- OpenAI Pro: credit-based with multipliers (Pro 20x = ~1600 GPT-5.5 messages per 5h window)

For Orchestra running multiple agents continuously, OpenAI's credit system may hit limits faster. Anthropic's "unlimited" subscription is more predictable.

---

## 9. Alternatives to Codex

### Viable for Orchestration

| Tool | SDK | MCP | Session Resume | Verdict |
|---|---|---|---|---|
| **Codex CLI** | TS + Python (experimental) | Full | Yes (threadId) | Best alternative |
| **Gemini CLI** | TS + Python (community) | Yes | Partial | Promising but SDK immature |
| **Aider** | Python (library, not SDK) | No native | Git-based history | No programmatic session control |
| **OpenCode** | Go (no SDK) | Yes | Unknown | No programmatic API |
| **Goose** | Python | Yes | Unknown | Less mature |

### Agent Client Protocol (ACP)

ACP is emerging as the "LSP for coding agents" — a standard JSON-RPC protocol for editor-to-agent communication. Supported by JetBrains, Zed, GitHub Copilot CLI, Cline. 

**Interesting angle**: If we implemented an ACP client, we could potentially talk to ANY ACP-compatible agent, not just Claude or Codex. But ACP is editor-focused, not orchestrator-focused. The overhead of adapting it may not be worth it.

---

## 10. Recommendation

### If Anthropic bans third-party agent usage:

1. **Immediate** (Day 1): Switch Claude Code CLI to API key mode. This bypasses subscription restrictions — we'd pay per token, but it works. Cost: ~$50-100/day for heavy usage.

2. **Short-term** (Week 1-2): Implement `AgentBackend` abstraction. Keep Claude as primary, but make the architecture ready for alternatives.

3. **Medium-term** (Week 2-4): Build `CodexBackend`. The Codex app-server protocol is rich enough to support our persistent-client pattern. The Python SDK is experimental but the protocol is stable.

4. **Long-term**: Hybrid mode. Use the best model for each task — Claude Opus for complex orchestration, GPT-5.5 for bulk coding, GPT-5.4-mini for simple tasks.

### If Anthropic doesn't ban it:

Don't migrate. The `claude-agent-sdk` is more mature, better integrated, and we'd lose features (sub-agent event tracking, direct cost reporting, in-process MCP). The abstraction layer is still worth building as insurance, but there's no urgency.

### Key Risk

The Codex Python SDK is **experimental** and requires a local Codex repo checkout. For production use, we'd likely need to:
- Use the TypeScript SDK (more mature) via a Node.js sidecar process, OR
- Implement our own Python client for the Codex app-server JSON-RPC protocol directly

The JSON-RPC approach is more work but gives us full control and no dependency on an experimental SDK.

---

## Sources

- [Codex SDK docs](https://developers.openai.com/codex/sdk)
- [Codex CLI features](https://developers.openai.com/codex/cli/features)
- [Codex CLI reference](https://developers.openai.com/codex/cli/reference)
- [Codex MCP support](https://developers.openai.com/codex/mcp)
- [Codex App Server](https://developers.openai.com/codex/app-server)
- [Codex + Agents SDK guide](https://developers.openai.com/codex/guides/agents-sdk)
- [Codex pricing](https://developers.openai.com/codex/pricing)
- [Codex changelog](https://developers.openai.com/codex/changelog)
- [Codex GitHub repo](https://github.com/openai/codex)
- [Codex TS SDK README](https://github.com/openai/codex/blob/main/sdk/typescript/README.md)
- [Codex Python SDK](https://github.com/openai/codex/tree/main/sdk/python)
- [Agent Client Protocol](https://agentclientprotocol.com/get-started/introduction)
- [ACP in Copilot CLI](https://github.blog/changelog/2026-01-28-acp-support-in-copilot-cli-is-now-in-public-preview/)
- [AI Coding CLI comparison (DEV)](https://dev.to/soulentheo/every-ai-coding-cli-in-2026-the-complete-map-30-tools-compared-4gob)
- [DigitalOcean: Claude Code alternatives](https://www.digitalocean.com/resources/articles/claude-code-alternatives)
- [Gemini CLI SDK (community)](https://github.com/oneryalcin/gemini-cli-sdk)

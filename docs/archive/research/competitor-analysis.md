# Competitor Analysis: AI Agent Orchestrators

**Date**: 2026-05-14  
**Context**: Orchestra is a FastAPI+HTMX dashboard that spawns Claude Code CLI workers via `claude-agent-sdk`, each in a git worktree. Telegram bridge for user comms. External MCP server for inter-agent communication.

---

## Tier 1: Direct Competitors (same problem space)

### 1. Symphony (OpenAI)
| | |
|---|---|
| **GitHub** | [openai/symphony](https://github.com/openai/symphony) |
| **Stars** | 23,720 |
| **Stack** | Elixir/BEAM + Codex CLI |
| **License** | MIT |

**What it is**: OpenAI's own orchestration spec. Polls a Linear board, dispatches one Codex agent per issue, each in its own workspace. "Every open task gets an agent."

**Architecture**:
- Single-threaded polling orchestrator (30s default interval)
- Subprocess isolation per task (not threads)
- Reusable sessions within worker lifetime (up to 20 turns)
- WORKFLOW.md with YAML frontmatter = version-controlled config, file-watch hot reload
- Stall detection: kill + retry if no codex event in 5min
- Exponential backoff: 10s → 20s → 40s → ... → 5min cap
- Per-state concurrency slots (e.g., max 2 concurrent reviews)

**What we don't have / should steal**:
- 🔥 **Issue tracker integration** — poll Linear/GitHub Issues, auto-dispatch agents. Orchestra is manual (user sends tasks via TG)
- 🔥 **WORKFLOW.md config** — version-controlled workflow config with hot reload. We hardcode prompts in session creation
- **Stall detection with auto-retry** — we have heartbeat + timeout but no exponential backoff retry
- **Per-state concurrency limits** — we have no slot management
- **Workspace lifecycle hooks** (`after_create`, `before_run`, `after_run`, `before_remove`)

**Why Elixir**: OTP supervision trees = if one agent crashes, supervisor auto-restarts with error context while others keep running. "Process isolation you'd spend months building in Python."

**500% PR increase** on some OpenAI teams in first 3 weeks.

---

### 2. Composio Agent Orchestrator
| | |
|---|---|
| **GitHub** | [ComposioHQ/agent-orchestrator](https://github.com/ComposioHQ/agent-orchestrator) |
| **Stars** | 7,023 |
| **Stack** | TypeScript, 40K LOC, 3,288 tests |
| **License** | Apache-2.0 |

**What it is**: AI orchestrator that reads your codebase + backlog, decomposes features into parallel tasks, assigns each to a coding agent. "Human spawns agents, walks away, gets notified."

**Architecture**:
- 8 pluggable abstraction slots (Runtime, Agent, Workspace, Tracker, SCM, Notifier, Terminal UI)
- Git worktree isolation per agent
- Auto CI-fix loop: CI fails → inject failure logs into agent → agent fixes → re-push
- Auto review-comment routing: reviewer requests changes → comments forwarded to agent
- Web dashboard at localhost:3000 (Kanban board: failing CI / awaiting review / running)
- Agent-agnostic: Claude Code, Codex, Aider, Cursor as backends

**What we don't have / should steal**:
- 🔥 **CI failure auto-routing** — agent's PR fails CI → automatically gets failure logs injected → fixes and re-pushes. We don't track CI at all
- 🔥 **Review comment routing** — PR review comments → forwarded to agent with context. Our merge is manual
- 🔥 **Plugin architecture** — 8 pluggable slots with single-interface plugins. Our architecture is monolithic
- **Kanban dashboard** — grouped by CI state, not just agent status
- **Multi-backend** — we're Claude-only (this research covers Codex migration)

**Key design principle**: "Coordination, isolation, and feedback loops as first-class concerns." Not just spawning agents — managing the entire PR lifecycle.

---

### 3. AWS CLI Agent Orchestrator (CAO)
| | |
|---|---|
| **GitHub** | [awslabs/cli-agent-orchestrator](https://github.com/awslabs/cli-agent-orchestrator) |
| **Stars** | 575 |
| **Stack** | Python + MCP server |
| **License** | Apache-2.0 |

**What it is**: Lightweight supervisor-worker orchestrator. A supervisor agent coordinates multiple worker agents running in tmux terminals. MCP-based communication.

**Architecture**:
- Supervisor-worker hierarchy via MCP tools
- 3 delegation patterns: Handoff (sync), Assign (async), Send Message (ongoing)
- 7 CLI providers: Claude Code, Codex, Kiro, Gemini, Copilot, Kimi, Q Developer
- Each agent in isolated tmux session with `CAO_TERMINAL_ID`
- REST API (port 9889) + Web UI dashboard bundled in Python wheel
- SKILL.md-based skills system, auto-seeded at startup
- Python plugin system for outbound events (Slack, Discord, TG, webhooks)

**What we don't have / should steal**:
- 🔥 **Provider-agnostic design** — 7 CLI backends, mix providers in same workflow. Our backend is Claude-only
- 🔥 **Delegation patterns** (Handoff/Assign/Send) — formalized communication primitives. Our agents use ad-hoc `send_message`
- **Human-in-the-loop via `tmux attach`** — direct terminal access to running agents. We have log viewing but no terminal attach
- **Skills system** — portable SKILL.md files auto-seeded across agents
- **Outbound plugins** — event-driven hooks for Slack/Discord/TG notifications

**Most architecturally similar to Orchestra**: Python + MCP + multiple CLI backends. But they use tmux sessions, we use SDK subprocess.

---

### 4. Claude Squad
| | |
|---|---|
| **GitHub** | [smtg-ai/claude-squad](https://github.com/smtg-ai/claude-squad) |
| **Stars** | 7,453 |
| **Stack** | Go |
| **License** | MIT |

**What it is**: Terminal TUI for managing multiple Claude Code agents in tmux + git worktrees. Lighter than Orchestra — no dashboard, no persistence.

**Architecture**:
- Go TUI with tmux session per agent
- Git worktree isolation per session
- Supports Claude Code, Codex, Aider, Gemini, OpenCode
- No web dashboard, no API, no persistence
- "Terminal-native developers who want multi-agent without leaving CLI"

**What we don't have / should steal**:
- **Multi-CLI support** — not just Claude Code
- **Speed** — Go binary starts instantly vs our FastAPI + SDK startup. Not a pattern to steal, just a trade-off note

**What we have that they don't**: Dashboard, Telegram bridge, MCP inter-agent communication, persistent sessions, cost tracking, context tracking, auto-compact.

---

## Tier 2: Larger Ecosystem Players

### 5. Ruflo (formerly Claude Flow)
| | |
|---|---|
| **GitHub** | [ruvnet/ruflo](https://github.com/ruvnet/ruflo) |
| **Stars** | 50,580 |
| **Stack** | TypeScript + WASM (250K LOC) |
| **License** | Apache-2.0 |

**What it is**: Self-described "leading agent orchestration platform for Claude." Swarm intelligence, self-learning memory, federated comms, enterprise security. Claims 84.8% SWE-bench solve rate, 75% API cost savings.

**Architecture**:
- "Cognitum.One" agentic engine (Rust-based)
- Three queen types (Strategic, Tactical, Adaptive) + 8 worker types
- Self-learning neural capabilities
- 100+ specialized agents across machines and trust boundaries
- RAG integration, federated communication

**What we don't have / should steal**:
- **Self-learning memory** — agents learn from task execution and route work to specialists
- **Swarm topology** — hierarchical queens + workers vs our flat orchestrator-worker model

**Caveat**: 50K stars but the codebase is... ambitious. 250K LOC TypeScript + WASM for an orchestrator is a red flag. Orchestra's ~2K LOC Python is intentionally minimal. Different philosophy entirely.

---

### 6. Aider
| | |
|---|---|
| **GitHub** | [paul-gauthier/aider](https://github.com/paul-gauthier/aider) |
| **Stars** | 44,789 |
| **Stack** | Python |
| **License** | Apache-2.0 |

**What it is**: AI pair programming in terminal. Not an orchestrator — single-agent tool. But has patterns worth studying.

**Key patterns**:
- **Architect mode**: reasoning model proposes changes → editor model translates to file edits. Two-model pipeline.
- **Repo map**: Tree-sitter based structural index of entire codebase (classes, functions, imports). Gives AI awareness without sending all code.
- **Three coder variants**: EditBlockCoder (surgical edits), WholeFileCoder (rewrites), ArchitectCoder (multi-step refactors)
- **Git-native**: auto-commits every change, git history = undo

**What we don't have / should steal**:
- 🔥 **Architect/Editor split** — use expensive model for reasoning, cheap model for implementation. Our workers use one model for everything
- **Repo map** — compressed structural index. Our agents re-read files every turn

**Not a direct competitor** but the architect pattern is directly applicable: use Opus for planning, Sonnet/GPT-5.4-mini for execution.

---

### 7. SWE-agent
| | |
|---|---|
| **GitHub** | [SWE-agent/SWE-agent](https://github.com/SWE-agent/SWE-agent) |
| **Stars** | 19,213 |
| **Stack** | Python |
| **License** | MIT |

**What it is**: Princeton/Stanford research. Takes a GitHub issue → automatically fixes it. Focused on benchmark performance (SWE-bench), not production orchestration.

**Key patterns**:
- **Agent-Computer Interface (ACI)**: custom commands and feedback formats optimized for LM interaction with codebase. Not raw bash — structured tools.
- **mini-swe-agent**: 100-line version scoring >74% on SWE-bench verified. Proves that minimal agents can be highly effective.

**What we don't have / should steal**:
- **ACI concept** — purpose-built tools for code navigation/editing vs raw bash. Our agents use generic CLI tools

---

### 8. Open SWE (LangChain)
| | |
|---|---|
| **GitHub** | [langchain-ai/open-swe](https://github.com/langchain-ai/open-swe) |
| **Stars** | 9,790 |
| **Stack** | Python (LangGraph + Deep Agents) |
| **License** | MIT |

**What it is**: Asynchronous coding agent with cloud sandboxes, Slack/Linear invocation, subagent orchestration, auto PR creation.

**What we don't have / should steal**:
- **Slack/Linear invocation** — trigger agents from team tools, not just our TG bridge
- **Cloud sandboxes** — isolated environments vs local worktrees

---

### 9. Cursor (Background Agents)
| | |
|---|---|
| **Product** | [cursor.com](https://cursor.com) |
| **Type** | Commercial, closed-source |

**What it is**: IDE with multi-agent support. Up to 8 parallel agents, each in isolated worktree. Background Agents work in cloud VMs, open PRs autonomously.

**Key patterns**:
- **Background Agents**: work in isolated VM, create branch, open PR with demo screenshot. Triggered from phone/Slack/GitHub.
- **Composer model**: frontier model trained specifically for agentic IDE interactions. Throughput-optimized.
- **8 parallel agents** with compare-and-choose results

**What we don't have / should steal**:
- 🔥 **Demo screenshots in PRs** — Background Agent captures screenshot of result. Visual proof of work
- **Cloud VMs** — full isolation beyond git worktrees

---

### 10. Agent of Empires
| | |
|---|---|
| **GitHub** | [njbrake/agent-of-empires](https://github.com/njbrake/agent-of-empires) |
| **Stars** | 2,225 |
| **Stack** | Rust |
| **License** | MIT |

**What it is**: TUI + Web UI for managing multiple CLI agents. Supports Claude Code, Codex, Gemini, Copilot, OpenCode, Pi.dev, Mistral Vibe, Factory Droid.

**What we don't have / should steal**:
- **Mobile web access** — manage agents from phone via web UI
- **8 CLI providers** — widest agent backend support

---

### 11. Devin
| | |
|---|---|
| **Product** | [devin.ai](https://devin.ai) |
| **Type** | Commercial, closed-source ($500/mo) |

**What it is**: Autonomous AI software engineer. Cloud sandbox, Slack/Teams integration, dynamic re-planning.

**Architecture**: Compound AI system — Planner (high-reasoning), Coder (code-specialized), Critic (adversarial review). Multiple Devins run in parallel.

**What we don't have / should steal**:
- 🔥 **Adversarial Critic agent** — separate model reviews code for security/logic bugs before commit
- **Dynamic re-planning** — agent hits roadblock, alters strategy without human intervention
- **Slack/Teams invocation** — our TG bridge is similar but less enterprise-ready

---

## Summary: What to Steal (Priority Order)

### 🔥 HIGH PRIORITY (concrete, implementable, high ROI)

| Feature | Source | Effort | Impact |
|---|---|---|---|
| **CI failure auto-routing** | Composio AO | 3-5 days | Agents self-heal failing PRs |
| **Provider-agnostic backend** | CAO, Composio | 5-7 days | Codex, Gemini, etc. |
| **Issue tracker polling** | Symphony | 3-5 days | Auto-dispatch from Linear/GitHub |
| **Architect/Editor split** | Aider | 2-3 days | Opus plans, Sonnet executes |
| **Demo screenshots in PRs** | Cursor | 1-2 days | Visual proof of work |
| **Adversarial review agent** | Devin | 2-3 days | Quality gate before merge |

### 🟡 MEDIUM PRIORITY (nice to have, moderate effort)

| Feature | Source | Effort | Impact |
|---|---|---|---|
| **Review comment routing** | Composio AO | 2-3 days | PR feedback → agent |
| **Plugin architecture** | Composio AO, CAO | 5-7 days | Extensible integrations |
| **Stall detection + retry** | Symphony | 1-2 days | Self-healing stuck agents |
| **Per-state concurrency limits** | Symphony | 1 day | Prevent resource exhaustion |
| **WORKFLOW.md hot reload** | Symphony | 2-3 days | Config without restart |
| **Formalized delegation patterns** | CAO | 2-3 days | Handoff/Assign/Send |

### ⚪ LOW PRIORITY (interesting but overkill for now)

| Feature | Source | Why low |
|---|---|---|
| Self-learning memory/swarm | Ruflo | 250K LOC complexity for marginal gain |
| Cloud VM isolation | Cursor, Devin | Local worktrees work fine for our scale |
| Repo map (Tree-sitter) | Aider | Agents manage context themselves |
| 8 provider support | Agent of Empires | Claude + Codex is sufficient |

---

## Our Unique Advantages (what competitors don't have)

| Feature | Competitors' approach |
|---|---|
| **Persistent SDK sessions** (connect → query → mid-turn inject) | Most use subprocess-per-turn or tmux attach |
| **Real-time dashboard** (SSE + HTMX, live token/cost tracking) | Most are TUI-only or basic web views |
| **Telegram bridge** (user talks to orchestrator via TG group) | Most require CLI or web UI access |
| **Auto-compact** (90% context → automatic summarize + reset) | No competitor does this |
| **MCP inter-agent communication** (external MCP server, HTTP callback) | Most use file-based or tmux pipe communication |
| **Cost tracking** (real-time per-agent USD cost) | Most don't track costs at all |
| **Context % tracking** (live context window usage per agent) | Unique to Orchestra |
| **Session persistence** (SQLite, survive server restart) | Most lose state on restart |

---

## Architectural Landscape

```
                    Agent-Agnostic
                         │
           CAO ──────────┤──────── Agent of Empires
           (MCP)         │         (Rust TUI+Web)
                         │
    Claude Squad ────────┤──────── Composio AO
    (Go TUI, light)      │         (TS, CI loops)
                         │
                    ─────┤──────── Symphony
                         │         (Elixir, spec-first)
                         │
              Orchestra ─┤
              (Python,   │
               SDK+MCP)  │
                         │
                Claude-Native
```

Orchestra sits at the intersection of Claude-native deep integration and growing need for provider diversity. The Codex migration research (see `codex-migration.md`) addresses the provider diversity gap.

---

## Sources

- [OpenAI Symphony](https://github.com/openai/symphony) (23.7K stars)
- [Composio Agent Orchestrator](https://github.com/ComposioHQ/agent-orchestrator) (7K stars)
- [AWS CAO](https://github.com/awslabs/cli-agent-orchestrator) (575 stars)
- [Claude Squad](https://github.com/smtg-ai/claude-squad) (7.5K stars)
- [Ruflo](https://github.com/ruvnet/ruflo) (50.6K stars)
- [Aider](https://github.com/paul-gauthier/aider) (44.8K stars)
- [SWE-agent](https://github.com/SWE-agent/SWE-agent) (19.2K stars)
- [Open SWE](https://github.com/langchain-ai/open-swe) (9.8K stars)
- [Cursor](https://cursor.com)
- [Agent of Empires](https://github.com/njbrake/agent-of-empires) (2.2K stars)
- [Devin](https://devin.ai)
- [Oh-My-Codex](https://github.com/Yeachan-Heo/oh-my-codex) (28.6K stars)
- [CrewAI](https://github.com/crewAIInc/crewAI) (51.4K stars)

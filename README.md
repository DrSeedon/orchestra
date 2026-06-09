<p align="center">
  <img src="docs/banner.png" alt="Orchestra" width="100%">
</p>

<h1 align="center">Orchestra</h1>
<h3 align="center">AI agent teams that think like managers, not state machines</h3>

<p align="center">
  <a href="#quick-start">Quick Start</a> ·
  <a href="#how-it-works">How It Works</a> ·
  <a href="#comparison">Comparison</a> ·
  <a href="#features">Features</a> ·
  <a href="https://seedon.ru">Website</a> ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

<p align="center">
  <img src="https://img.shields.io/github/stars/DrSeedon/orchestra?style=social" alt="Stars">
  <img src="https://img.shields.io/github/license/DrSeedon/orchestra" alt="License">
  <img src="https://img.shields.io/badge/python-3.12+-blue" alt="Python">
  <img src="https://img.shields.io/badge/built_by-itself-brightgreen" alt="Built by itself">
</p>

---

**Orchestra is an AI agent orchestration platform where you manage a team of agents the way a CEO manages a company — not the way a programmer writes a pipeline.**

You describe the goal. The orchestrator (Claude Opus) breaks it down, assigns workers (Claude Sonnet), reviews their output through a different model (GPT-5.5), and deploys the result. Each worker runs in an isolated git worktree. They communicate via messages, not function calls. They persist for hours or days, not the length of one API request.

> **The AI agent market is moving from SDKs to products.**
> 2024: "here's an SDK, build it yourself." 2025: "here's an agent, give it a task." 2026: "here's a TEAM, give it a goal." Orchestra is the third thing.

<p align="center">
  <!-- TODO: Replace with actual GIF of the dashboard showing agents working in parallel -->
  <img src="docs/dashboard.png" alt="Dashboard showing agents working" width="100%">
  <br>
  <em>Real-time dashboard: 6 agents working in parallel on a client project</em>
</p>

## Quick Start

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 18+, [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (requires Claude Max subscription)

```bash
# Clone and install
git clone https://github.com/DrSeedon/orchestra.git
cd orchestra
cp .env.example .env
uv sync

# Run
uv run uvicorn app.main:app --host 127.0.0.1 --port 8888

# Open http://localhost:8888
# Create an orchestrator, point it at a project, start chatting
```

No graph definitions, no YAML workflows, no node configurations. You talk to the orchestrator like you'd talk to a tech lead.

## How It Works

```
You (Telegram / Dashboard)
  │
  ▼
Orchestrator (Claude Opus) ─── thinks like a manager
  │   Decomposes task, assigns workers, reviews results
  │
  ├─► Worker A (Sonnet) ── git worktree: feature/auth
  ├─► Worker B (Sonnet) ── git worktree: feature/api
  ├─► Worker C (Sonnet) ── git worktree: fix/bug-123
  │
  ▼
Reviewer (GPT-5.5) ── cross-model review
  │   Different model = different blind spots
  │
  ▼
Merge ── squash to main
```

Each worker is a full Claude Code session in its own git worktree. They don't share context, don't step on each other's code, and merge through squash PRs. The orchestrator coordinates. Not a graph engine. An actual AI deciding what to do next.

Workers can talk to each other via `send_message`. The backend worker finishes an API endpoint and messages the frontend worker: "endpoint ready at /api/users, here's the schema." No human relay needed.

<a id="comparison"></a>
## Orchestra vs. the field

| | LangGraph | CrewAI | AutoGen | Claude Code | **Orchestra** |
|---|---|---|---|---|---|
| **Mental model** | Wire a graph | Assemble a crew | Chat between agents | Talk to one agent | **Manage a team** |
| **Who it's for** | Engineers | Developers | Researchers | Developers | **Teams with AI-native devs** |
| **Agents** | Nodes in a graph | Agents with roles | Conversable agents | One agent | **Persistent fleet** |
| **Isolation** | Shared state | Shared state | Shared state | Single context | **Git worktree per worker** |
| **Duration** | One pipeline run | One task run | One conversation | One session | **Hours to days** |
| **Cross-model review** | Manual | No | No | No | **Built-in (Claude→GPT)** |
| **Telegram control** | No | No | No | No | **Voice, text, media** |
| **Task management** | No | No | No | No | **Built-in (priorities, payments)** |
| **Self-building** | No | No | No | No | **Yes** |

The analogy:
- **LangGraph** = build a car from parts (for mechanics)
- **CrewAI** = LEGO kit (for hobbyists)
- **AutoGen** = group chat between bots (for researchers)
- **Claude Code** = hire one contractor (for developers)
- **Orchestra** = **hire a team (for builders)**

## Features

### 🏗️ Persistent Agent Fleet
Agents live for hours or days. They maintain context across tasks, remember past decisions, accumulate project knowledge. Not one-shot functions.

### 🌳 Git Worktree Isolation
Every worker gets its own git worktree — a full copy of the repo on its own branch. Two workers editing the same project never touch the same files. Merge conflicts are structurally minimized. `owned_dirs` per worker + `check_conflict()` before merge = safe parallel work.

### 📱 Telegram Bridge
Manage your AI team from your phone. Voice messages, photos, documents — the orchestrator transcribes voice (Deepgram Nova-3), understands images, processes files. Real-time status updates in topic threads.

### 🔀 Cross-Model Review
Code written by Claude is reviewed by GPT-5.5 (Codex). Different models have different blind spots. Two perspectives catch bugs that one model misses.

### 🏰 Hierarchy: Orchestrator → Sub-Orchestrators → Workers
One orchestrator per project. Sub-orchestrators manage sub-teams. Workers do the work. Cross-project messaging lets orchestrators coordinate across repos.

### 🔄 Built by Itself
Orchestra-orchestrator is the agent that builds Orchestra. 8 workers write the code for the platform they run on. No other framework can say: "our product was built by our product."

### ⚙️ Per-Role Model Policy
Orchestrators run on Opus (deep thinking). Workers run on Sonnet (fast execution). Full-cycle research agents run on Opus 4.8. Each role gets the right model for the job, not one-size-fits-all.

### 📋 Task Manager
Built-in task management with priorities, assignments, and payment tracking. Agents create, update, and close tasks. No external project management tool needed.

### 💾 Persistent Sessions
Agents survive restarts. Sessions are stored in SQLite, auto-resumed on boot. Context is compacted automatically when it fills up. Workers pick up where they left off.

### 📊 Real-Time Dashboard
HTMX + SSE dashboard shows every agent, their status, context usage, cache hit rate, current task, and live logs. No polling, no refresh.

## Real Projects Built with Orchestra

These aren't demos. They run in production right now, on one server.

| Project | What it does | Scale |
|---------|-------------|-------|
| **Parsing** (client, Kamchatka) | Data import, dedup, genealogy search | 166M records in MySQL |
| **Seedon** (our company) | Registration, accounting, legal, site, marketing, first client | Full business ops |
| **Kesha** | Personal Telegram bot on Claude Agent SDK | 24/7 on VPS |
| **VPN Service** | Marzban VLESS+Reality management | Self-hosted |
| **RimWorld Mods** | 70+ mod translations, C# DLL | 2000+ text keys |
| **Sensar** (medtech) | Software validation protocol for video laryngoscope | 36 test items, 20 pages |
| **University** | MSc thesis, lecture notes, ML dashboards | 45 pages, 29 DOI sources |
| **Orchestra itself** | Self-development: 8 workers build the platform | Recursive self-improvement |

## Architecture

```
Dashboard (HTMX + SSE) ◄──► FastAPI :8888 ◄──► Session Manager
                                                  │
                               ┌──────────────────┼──────────────────┐
                               ▼                  ▼                  ▼
                         Orchestrator A     Orchestrator B     Orchestrator C
                         (Project: site)    (Project: bot)     (Project: data)
                           │                  │                  │
                      ┌────┼────┐         ┌───┼───┐          ┌──┼──┐
                      ▼    ▼    ▼         ▼   ▼   ▼          ▼  ▼  ▼
                     W1   W2   W3        W4  W5  W6         W7 W8 W9
                    (fe) (be) (seo)     (tg)(api)(db)      (import)(dedup)(search)

TG Bridge (aiogram) ◄──► Orchestra API ◄──► Telegram group (topics per agent)

SQLite (WAL) ── sessions, logs, tasks, payments, jobs
Git Worktrees ── one per worker, squash merge to main
```

## Telegram Bridge

Mirror everything to a Telegram group with topic threads. Write in TG, agents receive. Send voice — transcribed via Deepgram. Send screenshots — agents see them.

```bash
# Add to .env
TG_BRIDGE_TOKEN=your_bot_token
TG_BRIDGE_GROUP=your_group_id
# Optional: voice transcription
DEEPGRAM_API_KEY=your_key
```

## Stack

- Python 3.12+, FastAPI, Jinja2, SSE
- `claude-agent-sdk` — Claude Code SDK (persistent client per session)
- SQLite (WAL mode), git worktrees
- Tailwind CSS, highlight.js, marked.js (bundled offline)
- aiogram 3.x (Telegram bridge)
- Deepgram Nova-3 (voice transcription)

## Contributing

We welcome contributions. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Good first issues are labeled `good-first-issue`.

## License

**AGPL-3.0** for open source use. Commercial license available for businesses that need it.

See [LICENSE](LICENSE) for details. Contact [@DrSeedon](https://t.me/DrSeedon) for commercial licensing.

---

<p align="center">
  <b>Orchestra</b> — stop building pipelines, start managing teams
  <br>
  <a href="https://seedon.ru">seedon.ru</a> · <a href="https://t.me/DrSeedon">Telegram</a> · <a href="https://github.com/DrSeedon/orchestra">GitHub</a>
</p>

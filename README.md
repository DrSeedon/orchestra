# 🎼 Orchestra — AI Agent Orchestrator

**v1.0.0** | [Changelog](CHANGELOG.md)

Your own AI agent orchestrator. Opus orchestrator manages a team of Sonnet workers, each in isolated git worktrees. Dashboard shows everything in real-time.

## Quick Start

```bash
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8888
# Open http://localhost:8888
```

## How It Works

1. **Create an orchestrator** — click "+ New", pick a project path and model
2. **Chat with it** — give tasks, it spawns workers automatically via MCP tools
3. **Workers work** — each in isolated git worktree, own branch, own session
4. **See everything** — switch between orchestrator and worker chats, monitor progress

## Architecture

```
Dashboard (HTMX) ←→ FastAPI API ←→ SessionManager
                                       ├── Orchestrator (AgentSession + MCP tools)
                                       │     └── spawn/send/list/kill workers
                                       └── Workers (AgentSession + MCP tools)
                                             └── send_message/list_agents
```

- **One class** `AgentSession` for both orchestrator and workers
- **MCP tools** — orchestrator manages workers natively, workers report back
- **Git worktrees** — each worker gets isolated copy, own branch
- **SQLite** — sessions, logs, survives restart
- **97 TDD tests** — written before code

## Stack

- Python 3.12+, FastAPI, Jinja2
- `claude-agent-sdk` — Claude Code SDK
- SQLite (WAL mode)
- Tailwind CSS, marked.js

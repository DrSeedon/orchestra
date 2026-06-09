# Contributing to Orchestra

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — package manager
- [Claude CLI](https://github.com/anthropics/claude-code) — installed and logged in (`claude --version`)
- Node.js (optional — only for Codex CLI integration)

## Setup

```bash
git clone https://github.com/your-org/orchestra.git
cd orchestra

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env — set DASHBOARD_USER, DASHBOARD_PASSWORD, INTERNAL_TOKEN at minimum
# Generate INTERNAL_TOKEN: openssl rand -hex 32

# Run
uv run uvicorn app.main:app --host 127.0.0.1 --port 8888
```

Dashboard opens at http://localhost:8888.

## Running tests

```bash
uv run pytest -x -q
```

Tests are in `tests/`. No external services required — SQLite uses an in-memory DB for tests (see `tests/conftest.py`).

## Code style

- No inline comments unless the *why* is non-obvious
- Follow existing patterns — no new abstractions for one-off code
- Keep changes surgical: touch only what the task requires
- Dead code → delete, don't comment out

## Project structure

```
app/
  main.py           — FastAPI app, routes, startup
  session.py        — AgentSession: backend-agnostic session wrapper
  manager.py        — spawn/stop/archive workers, worktree management
  db.py             — SQLite schema + queries
  auth.py           — cookie + INTERNAL_TOKEN auth middleware
  mcp_stdio.py      — External MCP server (tools for Claude CLI agents)
  tg_bridge.py      — Telegram ↔ Orchestra bridge (aiogram)
  tm.py             — Task manager CRUD + payment tracking
  bg_jobs.py        — Server-side background jobs (timer/file/command/cron)
  backend_claude.py — Claude CLI backend (claude-agent-sdk)
  backend_codex.py  — Codex CLI backend
  workspace.py      — Git worktree creation and cleanup
  proxy_manager.py  — HTTP proxy rotation
  ssh_tunnel.py     — SSH tunnel auto-reconnect
  routes/           — Extra route blueprints (proxy, task manager, bg jobs)
  prompts/          — Agent role/module/skill prompts (Markdown)
    roles/          — orchestrator, worker, sub-orchestrator, full-cycle
    modules/        — git-workflow, orchestration, report-format
    skills/         — codex-debate, html-artifacts, vps-deploy
  static/           — CSS, JS, favicon

deploy/
  install.sh                — one-shot VPS setup script
  nginx.conf.template       — Nginx reverse proxy config
  orchestra.service.template — systemd unit template

tests/              — pytest suite
```

## Pull request process

1. Fork the repo and create a branch: `git checkout -b feat/your-feature`
2. Make your changes — keep commits focused
3. Run tests: `uv run pytest -x -q`
4. Open a PR with a clear description of *what* and *why*

For significant changes (new features, architectural decisions) — open an issue first to discuss.

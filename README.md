<p align="center">
  <img src="docs/banner.png" alt="Orchestra" width="100%">
</p>

# 🎼 Orchestra — AI Agent Orchestrator

[Changelog](CHANGELOG.md)

AI agent orchestrator. Opus orchestrator manages Sonnet/Haiku workers via MCP tools. Each worker in isolated git worktree. Persistent client sessions, real-time dashboard + Telegram bridge.

<p align="center">
  <img src="docs/dashboard.png" alt="Dashboard" width="100%">
</p>

## Quick Start

```bash
cp .env.example .env  # edit tokens
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8888
# Open http://localhost:8888
```

## How It Works

1. **Create an orchestrator** — pick a project, model. Pill button in header
2. **Chat with it** — give tasks, it spawns workers automatically
3. **Workers work** — isolated git worktree, own branch, MCP communication
4. **See everything** — real-time SSE logs, context %, cache hit rate, usage bar
5. **Telegram** — optional TG bridge mirrors all activity to group topics

## Architecture

```
Dashboard (HTMX+SSE) <-> FastAPI :8888 <-> SessionManager
                                            |-- Orchestrators (Opus, per-project)
                                            |     +-- spawn/send/stop/kill workers
                                            |-- Workers (Sonnet/Haiku, per-task)
                                            |     +-- send_message back to orchestrator
                                            +-- Cross-project messaging

TG Bridge (aiogram) <-> Orchestra API
                    <-> Telegram group with topics per orchestrator
                    <-> Bidirectional mirrors to other groups
```

## Features

- **Persistent client per session** — connect once, `query()` injects mid-turn via SDK stdin. Auto-reconnect on failure
- **Heartbeat watchdog** — 60s heartbeat detects silent client death, auto-reconnects with inject notice
- **Auto-resume on restart** — all sessions (orchestrators + workers) restored from DB. Running sessions get restart notice injected
- **Auto-report** — workers that finish without send_message get force-reported to orchestrator
- **Prompt hot-reload** — updated prompts injected on first turn after restart
- **Cross-orchestrator awareness** — each orchestrator knows all others, can send_message across projects
- **Context tracking** — per-model limits (200k/1M), cache hit %, auto-compact at >90%
- **Usage bar** — OAuth API usage tracking, 5h/7d utilization, persisted cache
- **Worker progress tracking** — `update_progress(percent, status)` MCP tool, progress bar in sidebar
- **Stop vs Kill** — `stop_worker` = interrupt + idle (resumable), `kill_worker` = full delete
- **Image paste** — Ctrl+V upload with md5 dedup
- **Bug reports** — agents file bugs to BUGS.md via report_bug MCP tool
- **30+ custom tool bubbles** — spawn_worker, WebSearch, diff view, Read, Write, send_message, etc.

## Telegram Bridge (optional)

Mirror agent activity to a Telegram group with topic threads. Bidirectional — write in TG, agents receive with `[from TG: Name]` prefix.

1. Create a bot via [@BotFather](https://t.me/BotFather)
2. Create a TG group, enable topics, add your bot as admin
3. Add to `.env`:
   ```
   TG_BRIDGE_TOKEN=your_bot_token
   TG_BRIDGE_GROUP=your_group_id
   ```

### TG features
- **Voice/video notes** — Deepgram Nova-3 transcription, auto-injected as text
- **Media support** — photos, documents, video, audio, stickers, forwards with captions
- **Topic status** — 🟢/🟡 icons synced with actual agent status (single source of truth)
- **Mirror formatting** — entities (bold/italic/code) preserved in mirror groups
- **Images as photos** — `send_file` auto-detects images, sends via `send_photo` for inline preview
- **Debounce** — state machine batches rapid messages into single turn (5s window)
- **Polling auto-restart** — crash recovery wrapper with 10s retry

### Large file support (optional)
```bash
sudo bash scripts/setup-tg-bot-api.sh
# Add to .env:
TG_LOCAL_API_URL=http://localhost:8081
```

### Voice transcription (optional)
```
DEEPGRAM_API_KEY=your_key
```

## Stack

- Python 3.12+, FastAPI, Jinja2, SSE
- `claude-agent-sdk` — Claude Code SDK (persistent client per session)
- SQLite (WAL mode), git worktrees
- Tailwind CSS, highlight.js, marked.js, DOMPurify, diff-match-patch (bundled offline)
- aiogram 3.x (TG bridge)

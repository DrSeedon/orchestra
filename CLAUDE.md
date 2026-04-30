# Orchestra — AI Agent Orchestrator

## Что это
Свой оркестратор AI-агентов. Замена Agent Teams (Claude Code built-in) и AO (ComposioHQ).
Каждый worker = ClaudeSDKClient в отдельном git worktree. Оркестратор = FastAPI + HTMX dashboard.

## Стек
- Python 3.12+, FastAPI, HTMX, Jinja2
- `claude-agent-sdk` — SDK для Claude Code sessions
- SQLite — task queue, worker state, logs
- `git worktree` — изоляция работников

## Архитектура

```
Оркестратор (FastAPI)
├── Dashboard (HTMX) — http://localhost:8888
├── Task Queue (SQLite) — задачи + статусы
├── Worker Manager — spawn/inject/interrupt/kill
└── Workers (N штук)
    ├── ClaudeSDKClient — Claude Code session
    ├── git worktree — изолированная рабочая копия
    └── worker.md — протокол работы (scorecard, Codex, фидбек)
```

## Dev Commands
```bash
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8888
```

## Принципы (Pit of Success)
- Минимальный код, линейный, явный
- Crash > corrupt state
- Один способ
- Никакой обратной совместимости

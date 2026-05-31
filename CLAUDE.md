# Orchestra — AI Agent Orchestrator

[Changelog](CHANGELOG.md)

## Что это
Свой оркестратор AI-агентов. Opus оркестратор управляет Haiku/Sonnet воркерами через MCP tools.
Каждый worker = Claude CLI в отдельном git worktree. Dashboard = FastAPI + HTMX + SSE.

## Стек
- Python 3.12+, FastAPI, Jinja2, SSE
- `claude-agent-sdk` — SDK для Claude Code sessions
- External stdio MCP server (FastMCP) — tools как отдельный процесс
- SQLite — sessions, logs, inbox, jobs
- `git worktree` — изоляция работников

## Архитектура

```
Оркестратор (FastAPI :8888)
├── Dashboard (HTMX + SSE) — http://localhost:8888
│   ├── Auth (cookie session, login/password from .env)
│   └── Login page (glass-style dark theme)
├── SQLite — sessions, logs, inbox, jobs, tasks, payments
├── External MCP Server (app/mcp_stdio.py) — tools для Claude CLI
│   └── Auth: INTERNAL_TOKEN header для всех API запросов
├── Auth middleware — cookie OR internal token
├── Session Manager — spawn/stop/archive/compact
├── Task Manager (app/tm.py) — CRUD, priorities, payments, YouGile sync
├── TG Bridge (app/tg_bridge.py) — bidirectional, topics, voice transcription
└── Workers (N штук)
    ├── Claude CLI (persistent client per session via SDK)
    ├── git worktree — изолированная рабочая копия
    ├── MCP: Orchestra + scope .mcp.json (Playwright и т.д.)
    └── Stats: turns, tokens, tool_calls
```

Deployed: localhost:8888 (dev) + VPS клиента (auth enabled)

## Dev Commands
```bash
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8888

# Systemd
sudo systemctl start orchestra
sudo systemctl status orchestra
```

## Принципы
- Persistent client per session (connect once, `query()` injects mid-turn via stdin)
- External MCP (no in-process deadlocks)
- Workers communicate via HTTP callback, not MCP inject
- Proxy через Hiddify (127.0.0.1:12334) everywhere
- **НЕ рестартить сервер при изменении фронта** (JS/CSS/HTML) — статика подтягивается автоматически. Рестарт только при изменении Python-кода
- **sudo без пароля** для `systemctl restart/stop/start/status orchestra` и `telegram-bot-api` — можно рестартить сервер самому через `sudo systemctl restart orchestra`
- **НЕ рестартить сервер самостоятельно** — только по явной команде юзера ("ок", "рестартни", "перезапусти"). Ребут убивает все активные сессии агентов
- **НЕ обновлять VPS самостоятельно** — git pull, systemctl restart на VPS делает только юзер вручную. Не пушить и не деплоить на VPS без команды
- **TG /restart** — команда в TG группе для рестарта Orchestra
- **Воркеры могут общаться друг с другом** через `send_message(to="worker-name")`. Пример: backend воркер добавил endpoint → пишет frontend-opus чтобы тот добавил кнопку. Оркестратор не нужен как посредник для координации между воркерами

## Pricing
- **Max 20x subscription ($200/мес)** — все $ в dashboard виртуальные (API-equivalent), НЕ реальные траты
- API цены (для калькуляции): Opus $5/$25, Sonnet $3/$15, Haiku $1/$5 per M tokens
- Не паниковать от "$172 на оркестратора" — monopoly money. Оптимизировать КАЧЕСТВО, не стоимость

## AI Efficiency (design principle)
Orchestra automates humans — but the AI agents themselves must be optimized too.
Every feature should minimize agent overhead: fewer tool calls, less context waste, less repetition.

**Design for AI, not humans:**
- If an agent does the same 3 tool calls every time → automate into 1 MCP tool or server-side logic
- If agents waste context reading the same files → pre-inject via system prompt or worktree setup
- If a pattern causes context rot (agent re-reads, re-explains, loops) → fix the root cause, don't add more instructions
- Measure cost-per-task, not just "does it work". $2 task done in 3 tool calls > $8 task done in 30 tool calls
- Prompt engineering = agent optimization. Shorter, clearer prompts = fewer confused retries = less $ burned
- Every new feature ask: "does this reduce total agent tool calls/tokens across typical workflows?"

**Anti-patterns to avoid:**
- Agent reads entire file when it needs 5 lines → give it grep/line-range hints
- Agent asks orchestrator for permission it could decide itself → expand decision tree
- Agent retries failed command 5 times → fail fast, report, let orchestrator decide
- Two agents duplicate work because they don't know about each other → worker-to-worker communication
- Agent spends 20 tool calls on setup that could be pre-configured → inject at spawn time

## Agent Determinism (design principle)
Агенты должны быть ПРЕДСКАЗУЕМЫМИ. Один путь, один маршрут, минимум свободы.

**Правила проектирования промптов и тулов:**
- **1 задача = 1 workflow.** Не давать агенту 3 способа сделать одно и то же — он выберет худший. Один оптимальный маршрут, жёстко прописанный
- **Минимум тулов.** Каждый лишний тул = развилка где агент может свернуть не туда. Давать ТОЛЬКО те тулы которые нужны для конкретной роли
- **Decision tree > свобода.** Вместо "реши сам" — чёткое дерево решений: если X → делай A, если Y → делай B. Агент не должен "думать" о стратегии
- **Fail loud, не fail creative.** Если что-то не получилось — СТОП + report_bug + сообщение оркестратору. НЕ пытаться "обойти" проблему креативно, НЕ молча бросать задачу
- **Баг = запись.** Любая ошибка/неожиданное поведение → `report_bug()`. Не "ой ладно попробую по-другому". Даже если агент обошёл проблему — баг должен быть записан
- **Нет импровизации в проде.** Агент следует промпту буквально. Если промпт не покрывает ситуацию — спросить оркестратора, а не выдумывать

**При разработке новых ролей/промптов:**
- Тестировать: "может ли агент пойти не тем путём?" Если да — сузить промпт
- Каждый edge case в промпте = потенциальная развилка. Лучше 3 конкретных правила чем 1 "умное" обобщение
- Логировать когда агент отклоняется от ожидаемого пути → добавлять guardrails

## BUGS.md — баг-репорты от агентов
- Агенты (оркестраторы и воркеры) могут вызывать `report_bug(title, description)` MCP tool
- Баги пишутся в `BUGS.md` в корне проекта
- **При старте сессии** — чекни `BUGS.md`, если есть новые баги — разбери или упомяни
- **Чистка**: fixed/closed баги — удалять из BUGS.md. TODO.md — done items удалять. Держать оба файла компактными

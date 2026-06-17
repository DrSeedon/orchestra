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
- **Рестарт безопасен** — сессии персистентные (SQLite), auto_resume_all поднимает агентов. Контекст НЕ теряется. Активные turns прерываются, но idle воркеры восстанавливаются
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

## Session notes (2026-06-03 to 2026-06-09)

### Model policy
- Opus 4.6 — orchestrators/sub-orchestrators (4.8 has tool call bugs in orchestration)
- Opus 4.8 — full-cycle/reviewer (overthinking = feature for research)
- Opus 4.7 — REMOVED, deprecated
- Fable 5 — added and tested (works!), but 2x more expensive than Opus → burns limits 2x faster. Use only for one-off critical tasks, NOT as default
- Sonnet 4.6 — system workers, disposable

### Worktree lifecycle (deterministic, no LLM dependency)
- `merge_worker(next_task_id=)` — atomic merge+switch in one call (PREFERRED)
- `needs_switch` guard — after merge without next_task_id, worker blocked until switch
- `switch_worker_branch` — blocks on unmerged commits, resets to main via `git reset --hard`
- `kill_worker` — blocks on dirty/unmerged, `force=True` to override
- Auto-cleanup stale worktrees — startup + every 24h
- `change_model` — immediate DB persist (survives restart)

### TG bridge
- proxychains4 wraps telegram-bot-api — works without Hiddify VPN (через Ёжик SSH tunnel 12340)
- Health check loop — 3 consecutive fails → auto-restart telegram-bot-api
- Diff images (Edit/Write/Read/Grep/Bash) — Pillow render, ~40ms, ~30KB. TG_DIFF_IMAGES env (default true)
- send_message HTML formatting — `<b>→ to</b>` + `<pre>` for code
- `_find_orch_for_scope` — uses parent_name="" to find top-level orchestrator (not role)

### Prompt architecture
- Shared `modules/orchestration.md` — used by both orchestrator and sub-orchestrator
- `modules/background-jobs.md` — extracted from base.md, "message must explain WHY"
- `modules/task-management.md` — extracted from orchestration, full CRUD workflow
- Pre-compact auto-save — orchestrators get instruction to persist CLAUDE.md/TODO/BUGS before summary
- Sub-orchestrator sees only top-level orchestrators (not other sub-orchestrators)
- "NEVER type tool calls as text" — critical rule added after dev-lead Opus 4.8 bug

### Open source launch (ready)
- README with comparison table, fleet looping, infographics
- .env.example, CONTRIBUTING.md, Dockerfile, docker-compose.yml
- GitHub Actions CI (pytest on push), 522 tests pass
- app.js split: 5303→4489 lines, 3 leaf modules extracted (utils, tool-renderers, usage)
- 9 Playwright smoke tests
- Currency symbol from .env (CURRENCY_SYMBOL, default ₽)
- Pipeline-as-config (Вадим PR #2) merged and rebased

### Seedon enterprise fork
- Safety prompt (SAFETY_PREFIX) — was in main, REVERTED. Lives in private fork orchestra-enterprise
- Per-role lean tools — was in main, REVERTED. Will return when coding-worker role exists

## Session notes (2026-06-11 to 2026-06-16)

### Major refactoring
- **P0-P4 full codebase refactor** (Fable 5 full-cycle, $33): session.py split → CostTracker/TurnManager/HibernateManager; main.py 1574→91 lines; 3 circular deps cut; 34 isinstance killed; 487 tests green
- **tg_bridge split** — refactor-tg worker (Opus 4.8) in progress, research+plan done, awaiting impl

### New roles
- `experimenter` — hypothesis → experiment → measure → conclude. Opus 4.8
- `researcher` — search → verify → synthesize. Web research with counter-evidence. Opus 4.8
- Both in `pipelines/default/pipeline.yaml` + `prompts/roles/`

### Key features
- **4-level cost**: turn/ctx/session/total. ctx persisted in DB (survives reboot), session = in-memory only
- **Worker persistent memory** (#81): `docs/workers/{name}.md` auto-injects into prompt on spawn/resume
- **Dynamic model list**: `available_models_block()` from models.py → orchestrator prompts
- **Prompt visualization** (#77, #80): dashboard shows prompt blocks by source (file/module/dynamic/skill)
- **TG topic toggle**: right-click agent → toggle TG topic
- **Change-scope modal** (#78): CLI session files migrated to preserve context
- **Codex proxy wrapper**: `~/.local/bin/codex` → HTTPS_PROXY=12340 (Ёжик), works without Hiddify

### Enterprise separation
- `/mnt/data/Projects/Python/orchestra` = PUBLIC (origin=DrSeedon/orchestra.git). My territory
- `/mnt/data/Projects/Python/orchestra-enterprise` = PRIVATE (dev-lead's territory)
- Enterprise remote REMOVED from public repo. dev-lead has no-push to upstream
- Reverted enterprise code from main: DeepSeek models, proxy fetching, auto-bootstrap, block-creation, auth-gated UI

### Research findings
- `stop_reason=tool_use` = ALWAYS external interrupt (31 interrupt + 4 permission + 2 inject). Never "agent wants more"
- `ede_diagnostic` = CLI telemetry noise, not real errors. Filtered
- Fable 5 banned in USA — model dead as of 2026-06-15. Use Opus 4.8 instead

### Process rules
- **Step 0: Clarify before acting** — added to orchestration.md decision tree
- **Reply to agents via send_message** — not plain text to user chat
- **repo_path in spawn_worker** — set explicitly when task targets different repo than scope
- **Hardcoded role=orchestrator** for New Orchestrator modal — hidden dropdown was picking random role

### VPS клиента (147.45.101.84)
- orchestra.zahoron.ru — Parsing client
- SSH: `root@147.45.101.84`
- DB: `/opt/orchestra/data/orchestra.db`
- Auth: Bearer `d3f73e4c1d459201661e4419ef6917337a8a8920adf13fa2204cf2169cdc82bd`
- Parsing-orchestrator = $2230 (85% of total). Deep research sub-agents caused $118+$112 turns → 7d 100%

## BUGS.md — баг-репорты от агентов
- Агенты (оркестраторы и воркеры) могут вызывать `report_bug(title, description)` MCP tool
- Баги пишутся в `BUGS.md` в корне проекта
- **При старте сессии** — чекни `BUGS.md`, если есть новые баги — разбери или упомяни
- **Чистка**: fixed/closed баги — удалять из BUGS.md. TODO.md — done items удалять. Держать оба файла компактными

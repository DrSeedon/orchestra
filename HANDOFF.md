# Orchestra — Handoff для следующей сессии

## Что это
Свой оркестратор AI-агентов на `claude-agent-sdk`. Замена Agent Teams (Claude Code built-in) и AO (ComposioHQ). MVP работает.

## Статус: MVP v0.4 — работает, нужен рефакторинг

### Что работает ✅
- **Spawn workers** через SDK — каждый в git worktree, своя ветка
- **Persistent sessions** — worker остаётся `idle` после задачи, inject даёт новую
- **Inject** в работающего агента
- **Interrupt / Kill** агентов
- **TaskNotification** — нативный push от worker'а к оркестратору (как Agent Teams)
- **Dashboard** — HTMX, 3 таба (Chat/Workers/Notifications), sidebar с логами
- **SQLite** — все данные персистентны (workers, logs, callbacks)
- **worker.md** подтягивается как system_prompt
- **CLAUDE.md + .mcp.json** копируются в worktree (с fallback на parent dir)
- **Cost tracking** per worker
- **Resume** — session_id сохраняется, переживает рестарт

### Что НЕ работает / нужно доделать ❌
1. **Архитектура: worker.py и orchestrator.py дублируют** — оба используют ClaudeSDKClient, нужно унифицировать в один `AgentSession` класс
2. **Ответы оркестратора в чат** — приходят через callbacks, подвисают. Нужен streaming или лучший polling
3. **cwd** — worktree path работает, но агент иногда путается между worktree и repo root
4. **Codex review** запущен — результат в `docs/CODEX_REVIEW.md` (если успел дописать)
5. **Dashboard**: нет Markdown рендеринга в логах, нет streaming ответов

## Файлы

```
orchestra/
├── app/
│   ├── main.py          — FastAPI app, все API endpoints
│   ├── worker.py         — Worker класс (SDK session + worktree + logs)
│   ├── orchestrator.py   — Orchestrator класс (SDK session + spawn + listen)
│   ├── manager.py        — WorkerManager (dict wrapper + DB)
│   ├── db.py             — SQLite (workers, logs, callbacks)
│   └── templates/
│       └── dashboard.html — Full dashboard (Chat + Workers + Notifications)
├── data/
│   ├── orchestra.db      — SQLite database
│   └── orchestrator_session — session_id для resume
├── worktrees/            — git worktrees для workers (gitignored)
├── test_agent_notify.py  — proof of concept TaskNotification
├── CLAUDE.md
├── pyproject.toml
└── docs/
    └── CODEX_REVIEW.md   — Codex архитектурный ревью (если готов)
```

## API Endpoints

### Workers (прямые SDK сессии)
```
POST   /api/workers/spawn          — {name, task, repo_path, model}
GET    /api/workers                — список всех
GET    /api/workers/{name}         — детали + логи
POST   /api/workers/{name}/inject  — {message} в работающего
POST   /api/workers/{name}/kill    — убить
DELETE /api/workers/{name}         — удалить из БД
```

### Orchestrator (SDK сессия-оркестратор)
```
POST   /api/orchestrator/start     — {cwd} подключить
POST   /api/orchestrator/spawn     — {name, task, repo_path, model} через оркестратора
POST   /api/orchestrator/send      — {message} в чат оркестратору
GET    /api/orchestrator/status    — connected/session_id
```

### Общие
```
GET    /api/stats                  — total/active/done/cost
GET    /api/callbacks              — непрочитанные notifications
POST   /api/callbacks/read         — пометить прочитанными
POST   /api/workers/{name}/callback — worker вызывает оркестратора (curl)
```

## Ключевые решения

### Почему SDK а не Agent Teams
- Agent Teams: worktree сломан (Issue #37549, #28175), idle путается, нельзя прервать
- SDK: полный контроль — inject, interrupt, resume, TaskNotification нативно
- Кеша (kesha-tg-bot) уже использует SDK — проверенный подход

### Модели
- **Sonnet 4.6** (200k) — дефолт для workers. 3% галлюцинаций, 2x быстрее Opus, 40% дешевле
- **Opus 4.6** (1M) — для оркестратора и complex planning. `[1m]` суффикс автоматически
- **Haiku 4.5** — для read-only задач (дёшево)

### Worker protocol
- `~/.claude/agents/worker.md` — глобальный, подтягивается как system_prompt
- Scorecard 15/15, Pit of Success (10 принципов), Codex workflow, фидбек на процесс
- Callback: worker вызывает `curl POST /api/workers/{name}/callback` чтобы оповестить

### Worktree
- Создаются в `orchestra/worktrees/{name}` (вне repo)
- CLAUDE.md + .mcp.json копируются из repo (или parent dir)
- Ветка `feat/{name}` автоматически
- Cleanup при kill

## Рефакторинг (TODO) — из Codex Review

Полный ревью: `docs/CODEX_REVIEW.md` (342 строки).

### 1. Унификация (ГЛАВНОЕ)
```
worker.py + orchestrator.py → agent_session.py (AgentSession)
```
Один класс для всех агентов. Различия в конфиге:
```python
ORCHESTRATOR = AgentConfig(role="orchestrator", model="opus-4-6[1m]", max_turns=200, permission_mode="bypassPermissions")
WORKER = AgentConfig(role="worker", model="sonnet-4-6", max_turns=50, permission_mode="default")
```

### 2. Worktree → отдельный модуль `workspace.py`
```python
def create_worktree(repo_path, name) -> Worktree
```
Один способ, fail loud (check=True), копирование CLAUDE.md/.mcp.json/.env.

### 3. API → один ресурс `/api/sessions`
```
GET/POST  /api/sessions
GET       /api/sessions/{name}
POST      /api/sessions/{name}/messages
POST      /api/sessions/{name}/interrupt
DELETE    /api/sessions/{name}
GET       /api/stats
```
Удалить: `/api/workers/*`, `/api/orchestrator/*`, `/api/callbacks/*`.

### 4. Удалить dead code
- `json` import в db.py
- `AgentDefinition`, `SystemMessage`, `RateLimitEvent` imports
- `_worker_md` в orchestrator (не используется)
- `WorkerStatus.DONE` (агент не ставит done, только idle)
- `context_pct` (нигде не обновляется)
- `chatHistory` в dashboard

### 5. Статусы упростить
```
starting → running → idle → stopped
                \→ error
```

### 6. Dashboard — один polling loop
Один `setInterval(refresh, 2000)` → `/api/sessions`. Убрать отдельный notifications tab, pollOrchestratorResponse, callbacks.

### 7. Fail loud
- API: 404/409/500 вместо `{ok: false}`
- subprocess: `check=True`
- dashboard: показывать ошибки в toast

### Порядок рефакторинга (Codex)
1. `AgentSession` ← SDK lifecycle из Worker/Orchestrator
2. `workspace.py` ← worktree/copy logic
3. `AgentManager` ← переписать manager
4. Удалить worker.py + orchestrator.py
5. API → `/api/sessions`
6. Dashboard → один polling
7. Удалить callbacks → обычные session logs

## Dev Commands
```bash
cd /mnt/data/Projects/Python/orchestra
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8888

# Dashboard: http://localhost:8888
# НЕ использовать --reload (убивает asyncio tasks)
```

## Зависимости
- `claude-agent-sdk` — Claude Code SDK
- `fastapi` + `uvicorn` — web server
- `jinja2` — templates
- SQLite — storage (встроенный)

## Контекст проекта Parsing
- 4 проекта: parsing-hub, zahoron-mobile, ai-assistants (Victor), seo-platform
- Все на VPS 147.45.101.84, GitHub Actions CI
- Правила в `~/.claude/CLAUDE.md` и `Parsing/CLAUDE.md`
- Worker protocol в `~/.claude/agents/worker.md`
- Память в `~/.claude/projects/-mnt-data-Projects-Python-Parsing/memory/`

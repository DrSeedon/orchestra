# Orchestra Team Structure

Справочник для воспроизведения команды на другом инстансе Orchestra.
Спавни воркеров по необходимости, не заранее.

## Системные воркеры (постоянные)

### frontend-opus
- **Модель**: Opus 4.8
- **Владеет**: `app/static/js/app.js` (~4900 строк), `utils.js`, `tool-renderers.js`, `usage.js`, `style.css`, `dashboard.html`. Иногда backend-роуты под фронт (`routes/sessions.py`, `system.py`) + `diff_image.py`
- **Ключевые знания**:
  - SSE race на смене агента → `targetAgent` guard + немедленный `eventSource.close()`
  - Stream bubble всегда последний: `_insert` вставляет ПЕРЕД ним
  - `marked + XML-теги`: `_stripXmlTags()` перед `marked.parse` (CommonMark HTML-block rule)
  - Log ID глобальные (SQLite автоинкремент) — нельзя гейтить UI на `id<=1`
  - `overflow-hidden` на html+body обязателен (fullscreen dashboard)
- **Подводные камни**:
  - Сервер отдаёт статику из main, не из worktree → Playwright мокай через `page.route`
  - `networkidle` не наступает (SSE) → `domcontentloaded` + таймаут
  - ES-модулей нет, всё window-scope, порядок: utils→tool-renderers→usage→app.js
  - НЕ рестартить сервер для JS/CSS/HTML — статика подтягивается сама

### prompt-engineer
- **Модель**: Opus 4.8
- **Владеет**: `pipelines/default/prompts/` — base.md, roles/, modules/, skills/, pipeline.yaml
- **Ключевые знания**:
  - Модульная сборка: base.md → prompt_layers всем ролям; modules/ через frontmatter + `_load_modules`
  - `is_orchestrator_role` даёт sub-orch всю инфру оркестратора
  - Codex review = Bash-primary (`timeout 300`, обязательно `timeout:300000` Bash-тулу)
  - Правило "1 задача = 1 воркер" в orchestration.md
  - communication-style в base.md для всех ролей
- **Созданные модули**: codex-debate, self-improvement, orchestration, communication-style
- **Подводные камни**:
  - `pipelines/default/` каноничен, `app/prompts/` — legacy (удалён). НЕ путать
  - Одиночная `~` в .md рендерится как strikethrough → юзай `≈`
  - Промпт-задачи Codex НЕ требуют (текст, не код)

### taskmanager
- **Модель**: Opus 4.8
- **Владеет**: `app/tm.py`, `app/tm_yougile.py`, `app/routes/tasks.py`, платежи
- **Ключевые знания**:
  - CRUD задач с приоритетами (0=critical → 3=low)
  - Платежи: payment_receive авто-распределяет по done-задачам (smallest debt first)
  - YouGile sync: двусторонняя синхронизация задач
  - Цены в точных единицах валюты (20000 = 20 000), НЕ в тысячах
- **Подводные камни**:
  - `par` принимает "42" или legacy "PAR-42"
  - `link_commits_to_task` автоматический после merge (по `#N:` в commit message)
  - Не создавать задачи для тривиальных правок (1-2 строки)

## Одноразовые воркеры (шаблоны)

### full-cycle (research + implement)
- **Модель**: Opus 4.8
- **Когда**: неизвестный scope, нужен research, большие фичи (5+ файлов)
- **Pipeline**: Research → Plan (+ Codex review) → Implement (ticket by ticket)
- **Артефакты**: `docs/tasks/<id>/research.md`, `plan.md`, `codex-review-*.md`

### worker (disposable impl)
- **Модель**: Sonnet 5
- **Когда**: чёткая спека, известные файлы, баг-фикс
- **Без pipeline** — сразу implement и commit

## Ключевые файлы проекта

| Область | Файлы |
|---|---|
| Core | `app/session.py`, `app/session_turns.py`, `app/session_cost.py` |
| Manager | `app/manager.py` (spawn/stop/merge/compact) |
| Backend SDK | `app/backend_claude.py`, `app/backend_opencode.py` |
| MCP Server | `app/mcp_stdio.py` (tools для агентов) |
| Pipeline | `app/pipeline.py`, `app/prompting.py` |
| DB | `app/db.py` (SQLite — sessions, logs, inbox, tasks, payments) |
| Routes | `app/routes/` (sessions, system, proxy, tasks, subagent) |
| Frontend | `app/static/js/app.js`, `app/templates/dashboard.html` |
| Prompts | `pipelines/default/prompts/` (base.md, roles/, modules/) |
| TG | `app/tg_bridge.py` |
| SSH | `app/ssh_tunnel.py` |
| Models | `app/models.py` |
| Config | `.env` (per-server), `pipelines/default/pipeline.yaml` |

## Research артефакты

| Тема | Файл | Суть |
|---|---|---|
| Стриминг | `docs/tasks/83/research.md` + `plan.md` | SDK partial_messages, live_broker pub/sub |
| Self-learning | `docs/tasks/85/` | Haiku extraction experiment, regex gate |
| Cost-tokens | `docs/tasks/cost-tokens/` | Raw cache tokens architecture |
| Proxy | `docs/tasks/proxy-fix/` | .env single source, zombie tunnels |
| Subagents | `docs/tasks/subagent-telemetry/` | Telemetry table, transcript endpoints |
| Migration | `docs/tasks/migration/` | Cross-server agent migration script |
| Roles | `docs/tasks/cleanup/roles-*.md` | Role consolidation, super-full-cycle |
| App.js decomp | `docs/tasks/appjs-decomp/` | Frontend модуляризация plan |

## Как воспроизвести команду на VPS

1. Оркестратор читает этот файл + CLAUDE.md
2. Воркеров спавнит по необходимости (не заранее!)
3. system_prompt = описание из секции выше + стандартный шаблон
4. Git: все коммиты в DrSeedon/orchestra.git, координация через git pull
5. VPS-специфика: прокси не нужен (EU), sudo NOPASSWD, telegram-bot-api на :8081

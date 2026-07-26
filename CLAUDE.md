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
- Proxy — см. секцию «🔌 ПРОКСИ» ниже (источник истины = .env HTTPS_PROXY)
- **НЕ рестартить сервер при изменении фронта** (JS/CSS/HTML) — статика подтягивается автоматически. Рестарт только при изменении Python-кода
- **sudo без пароля** для `systemctl restart/stop/start/status orchestra` и `telegram-bot-api` — можно рестартить сервер самому через `sudo systemctl restart orchestra`
- **НЕ рестартить сервер самостоятельно** — только по явной команде юзера ("ок", "рестартни", "перезапусти"). Ребут убивает все активные сессии агентов
- **Рестарт безопасен** — сессии персистентные (SQLite), auto_resume_all поднимает агентов. Контекст НЕ теряется. Активные turns прерываются, но idle воркеры восстанавливаются
- **НЕ обновлять VPS самостоятельно** — git pull, systemctl restart на VPS делает только юзер вручную. Не пушить и не деплоить на VPS без команды
- **TG /restart** — команда в TG группе для рестарта Orchestra
- **Воркеры могут общаться друг с другом** через `send_message(to="worker-name")`. Пример: backend воркер добавил endpoint → пишет frontend-opus чтобы тот добавил кнопку. Оркестратор не нужен как посредник для координации между воркерами

## 🔌 ПРОКСИ (единственный источник истины = .env)
- **`.env` `HTTPS_PROXY`/`HTTP_PROXY` = ЕДИНСТВЕННЫЙ источник.** Нет DB, нет hot-switch, нет кеша статусов
- Один прокси везде: systemd EnvironmentFile → `os.environ` → наследуют все (Orchestra + CLI агенты + MCP subprocess). Рассинхрон невозможен by design
- **Сменить прокси:**
  ```
  1. Отредактируй HTTPS_PROXY И HTTP_PROXY в .env (оба!)
  2. sudo systemctl restart orchestra
  ```
  Всё. Живой прокси найти: `bash scripts/check-proxies.sh` (диагностика — покажет живой и впишет в .env; рестарт — руками)
- **Дашборд:** только индикатор активного (из `os.environ`, read-only) + кнопка Check (проверить живость on-demand). Кнопки «выбрать/активировать» НЕТ — переключение только через .env
- `proxy_manager.py` — read-only: `list_proxies()` + `check_all()`. НЕ мутирует env, НЕ пишет в DB
- SSH-туннели (`ssh_tunnel.py`) поднимают локальные порты к VPS. `HTTPS_PROXY` указывает на нужный порт. Мёртвые VPS не спамят реконнектом (health-gate + backoff)
- **TG bot** (telegram-bot-api) — через proxychains (`/etc/proxychains4.conf`), C++ бинарник не читает .env. Обычно socks5 Contabo (12345). **ВАЖНО**: при смене прокси обновлять ОБА файла: `/etc/proxychains4.conf` И `~/.proxychains/proxychains.conf` — user-config имеет приоритет

## Pricing
- **Claude Max $100/мес + Codex Pro $100/мес** — все $ в dashboard виртуальные (API-equivalent), НЕ реальные траты
- **Стратегия (2026-07-22)**: все воркеры → Sol (gpt-5.6-sol), оркестраторы → Opus 4.6 (Claude). Codex планируется апгрейд до $200 (20×), Claude остаётся $100 (5×)
- **RULE: Квота (отдельный пул) — first-order фактор при выборе модели, не risk footnote.** Sol использует отдельный Codex-пул; Claude расходуется только при task-level эскалации на Opus 4.6 для brand/voice copy или Opus 4.8 для deep analysis/research/citations/1M/vision
- Codex 5× хватает на ~2.5 рабочих дня, 20× на ~5-10 дней (замерено). Claude 5× без воркеров = ~30% утилизации (хватает)
- Fable 5 НЕ юзать — 2× дороже Opus по лимитам, сжигает 5h окно
- API цены (для калькуляции): Opus $5/$25, Sonnet $3/$15, Haiku $1/$5 per M tokens
- Не паниковать от "$172 на оркестратора" — monopoly money. Оптимизировать КАЧЕСТВО, не стоимость
- **ТОЛЬКО ПОДПИСКА. НИКАКИХ API-КЛЮЧЕЙ.** Работаем исключительно на Max подписке. ANTHROPIC_API_KEY не используем, не покупаем, не обсуждаем. На VPS — те же креды подписки (claude login). Это окончательное решение
- **БИНАРНИКИ — КОПИРОВАТЬ, НЕ КОМПИЛИРОВАТЬ.** Если бинарник (telegram-bot-api, и т.д.) уже собран локально — `scp` на VPS. Не тратить 10+ мин на компиляцию из исходников. Локальные бинарники: `/usr/local/bin/telegram-bot-api` (x86_64, ELF)

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

## ⚡ PROCESS RULES (оркестратор)
- **КРАТКОСТЬ — не лей воду.** Юзер видит логи tool-вызовов. НЕ пересказывай что сделал ("Спавнил X", "Проверю что закоммитилось") — он это видит. НЕ дублируй статус по 2-3 раза за ответ. НЕ объясняй очевидное ("безобидно, всё чисто").
- **Сделал → одна фраза** (что + результат). Панчлайны/таблицы/резюме — ТОЛЬКО для реального итога или решения, НЕ на рутину (спавн, merge, "жду воркера", "как вернётся покажу").
- **Не отчитывайся о промежуточном** — "жду Codex", "воркер работает" = шум. Юзер узнает из авто-репортов/логов. Пиши когда есть РЕЗУЛЬТАТ или нужно РЕШЕНИЕ юзера.
- Панчлайн-аналогия из глобального промпта — на ИТОГ сессии/крупное решение, не на каждый чих.
- **ВСЕ воркеры ВСЕХ проектов — МОЯ ответственность.** Воркеры в kesha-tg-bot, polus, seedon и любом другом проекте управляются Orchestra. Баги воркеров (status-desync, зацикливание, idle-while-running) — разбираю Я, не делегирую проектному оркестратору. Проектный оркестратор (kesha-tg-bot, polus-orchestrator) — это разработчик проекта, НЕ менеджер воркеров.
- **НЕ убивать full-cycle воркеров после merge.** Full-cycle на гейте ("awaiting approval to plan/implement") = ЖДЁТ продолжения. merge → оставить idle, НЕ kill. Kill только одноразовых (impl-*, fix-*, research-*-без-фаз). Если воркер написал "STOP на гейте" — он ЖИВОЙ и ждёт следующую фазу.

## 🪤 Грабли (то, на чём уже спотыкались)

Формат: симптом → причина → что делать. Хроника, из которой это вынуто, — в `docs/archive/sessions/`.

**Модели и лимиты**
- Opus 5 вдруг с 200K контекста → голый `claude-opus-5` репортит `contextWindow: 200000`, а `claude-opus-5[1m]` — 1000000 (проверено пробой CLI, докой НЕ подтверждается) → всегда пинить `[1m]`, alias `opus` в сохранённой модели сессии не использовать. Отдельного бакета у Opus 5 нет — ест общий 5h/7d счётчик
- `UPDATE sessions SET model=...` отработал, а после рестарта модель прежняя → живой сервер перезаписывает `sessions.model` из памяти при auto_resume → править при остановленном сервере и ПЕРЕПРОВЕРЯТЬ после рестарта; при смене бэкенда Codex→Claude обнулять ещё и `session_id`
- Лимиты кончаются вдвое быстрее «без причины» → после даунгрейда Max $200→$100 ход стоит 0.270% вместо 0.142% (1.9×, замер за 14 дней) → планировать вдвое меньше ходов. Fable на оркестраторе = 4× (2× цена × 2× лимит)
- full-cycle крашится сразу на старте на Claude-модели → `effort=xhigh` из pipeline.yaml, а Claude API отвергает xhigh без thinking → auto-downgrade xhigh→high (`backend_claude.py`)
- Оркестратор на Opus 4.8 молча ломает оркестрацию → у 4.8 баги tool-calls именно в orchestration-режиме → оркестраторы на Opus 5, 4.8 только full-cycle/reviewer
- Финальное ревью на Spark пропускает баги → в A/B Spark прошляпил реальный double-count, который поймал Sol → финальные ревью не роутить на дешёвую модель

**Codex / Sol**
- Свежие правила «не работают» у Sol-воркеров → Codex грузит проектный `AGENTS.md` максимум на 32 KiB (`project_doc_max_bytes`) и режет ПОСРЕДИ фразы; кириллица = 2 байта/символ → держать `CLAUDE.md` компактным, страховка — `project_doc_max_bytes` в `~/.codex/config.toml` (на VPS/новой машине выставить заново)
- Codex-воркер видит правила месячной давности → `AGENTS.md` — зеркало `CLAUDE.md`, обновляется при коннекте бэкенда (`workspace.sync_agents_md`); если репозиторий ТРЕКАЕТ свой `AGENTS.md`, зеркало не трогает его
- Codex жжёт время в `sleep` (74 сна на 1579 вызовов, у Claude — ноль) → формулировка «do NOT poll, just wait» читается им буквально → в описаниях тулов писать END YOUR TURN NOW; глобально `sleep` не блокировать
- Codex ретраит вечно на исчерпанной квоте → «You've hit your usage limit» не матчилось паттернами, и Codex НЕ шлёт отдельный text-event перед error → терминальный лимит проверять прямо в error handler
- Codex падает на длинном JSONL → не баг Codex: `asyncio.StreamReader` по умолчанию 64KB → `limit=16MB` + fail-soft readline
- Планируешь Sol задачу под 1M контекста → при ChatGPT-auth эффективный контекст 258K → считать бюджет от 258K
- precompact на Codex делает хуже → у Codex cache TTL ≈30 мин и 10× cold penalty, precompact убивает cache key → precompact только для Claude
- `codex_review` — это bg job (type=run), возвращается сразу и будит воркера → не ждать его, закончить ход

**Агенты и оркестрация**
- Воркер игнорирует твой ответ → plain text в чате = сообщение ЮЗЕРУ, воркер его не видит → даже «ок, работай» слать через `send_message(to="worker")`
- Воркер после merge «залипает» → сработал `needs_switch` guard → `merge_worker(next_task_id=...)` одним вызовом
- Убил воркера — потерял фазу → full-cycle на гейте ЖИВОЙ и ждёт продолжения → kill только одноразовых
- Один агент съел $2230 (85% расхода) → deep-research сабагенты дают ходы по $118 → research-фан-аут спавнить осознанно
- Агент «сделал» работу, а её нет → напечатал tool call текстом вместо вызова → проверять артефакт, а не рассказ
- `stop_reason=tool_use` читают как «агент хочет продолжить» → это ВСЕГДА внешнее прерывание → не строить на нём логику

**Инфраструктура и код**
- Все исходящие TG встали намертво → `important=True` на пачке tool-сообщений → lock contention → вечная очередь; зеркально `important=False` = молча дропается → косметика и реальные доставки не делят очередь и retry-путь
- merge воркера не проходит на ровном месте → инжектированные `.claude/skills/` дёргают дерево → исключать через git common-dir `info/exclude`, не `.gitignore`
- Файлы воркера «не существуют» для остальных → они невидимы до merge → мержить часто
- «Мёртвый» модуль оказался живым → грепали строку, а читалось через 12 функций (fallback + дашборд) → перед удалением грепать РЕАЛЬНЫЕ импорты и fallback-пути, широко (app/, tests/, static/, манифесты)
- Вывод «Opus 5 заменяет Sol» оказался ложным → зелёную линию на графике приняли за Sol, а это был Sonnet 5 → проверять легенды до того, как повторить вывод юзеру

## 📚 Где искать остальное
- `docs/archive/sessions/` — хроника сессий (что делали, что чинили, какие решения принимали)
- `docs/tasks/<id>/` — research/plan/report по каждой задаче
- Оба слоя проиндексированы: `search_memory("как мы решали X")` ищет по смыслу, переиндексация — на `merge_worker`

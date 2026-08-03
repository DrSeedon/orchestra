# Orchestra — AI Agent Orchestrator

[Changelog](CHANGELOG.md)

## Что это
Свой оркестратор AI-агентов. Оркестратор управляет воркерами через MCP tools.
Каждый worker = CLI-сессия (Claude или Codex-бэкенд) в отдельном git worktree.
Dashboard = FastAPI + HTMX + SSE.

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
- Фронтенд (JS/CSS/HTML) обновляется без рестарта; Python-код требует рестарта для загрузки, но это не разрешение на него
- `sudo systemctl` для `orchestra`/`telegram-bot-api` доступен технически, но это НЕ authorization: `restart/stop/start` — только по явной команде текущего юзера; `status` остаётся read-only. Рестарт прерывает active turns
- После разрешённого рестарта SQLite-сессии и idle workers восстанавливаются; активные turns прерываются
- **НЕ обновлять VPS самостоятельно** — git pull, systemctl restart на VPS делает только юзер вручную. Не пушить и не деплоить на VPS без команды
- **Remotes:** `origin` (github.com/DrSeedon/orchestra) — наш публичный, держать актуальным. `enterprise` и `vadim` — ЧУЖИЕ, НЕ трогать никогда: ни push, ни pull, ни ветки
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
- **Claude Max 20× + Codex Pro** — все $ в dashboard виртуальные (API-equivalent), НЕ реальные траты
- **Модели: единственный source of truth — `<model-routing>` системного промпта.** Выбор идёт по классу задачи и текущему quota runway, не по историческим процентам; при отсутствии telemetry используется manifest default
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
- **Fail loud, не fail creative.** Ошибку маршрутизировать по контракту BUGS ниже; не обходить молча. СТОП — только когда безопасно продолжить нельзя
- **Нет импровизации в проде.** Агент следует промпту буквально. Если промпт не покрывает ситуацию — спросить оркестратора, а не выдумывать

**При разработке новых ролей/промптов:**
- Тестировать: "может ли агент пойти не тем путём?" Если да — сузить промпт
- Каждый edge case в промпте = потенциальная развилка. Лучше 3 конкретных правила чем 1 "умное" обобщение
- Логировать когда агент отклоняется от ожидаемого пути → добавлять guardrails

## BUGS.md — баг-репорты от агентов
- `report_bug(title, description)` — только сбои платформы Orchestra (MCP, сессии, worktree, TG, dashboard, model routing); писать сразу, даже если найден обход
- Баг кода текущего проекта → `docs/tasks/<id>/` + сообщение оркестратору, НЕ `report_bug`
- **При старте корневой Orchestra-сессии** — чекни `BUGS.md`; worker получает нужный контекст через задачу/промпт
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
- full-cycle крашится сразу на старте на Claude-модели → `effort=xhigh` из pipeline.yaml, а Claude API отвергает xhigh без thinking → auto-downgrade xhigh→high (`backend_claude.py`)
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
- `codex_review(mode="review")` на закоммиченной работе отвечает «no changes to review» и раунд сгорает → для закоммиченного: `git diff <merge-base> HEAD > /tmp/x.diff` + `mode="exec"`
- Ревью уползает читать посторонние файлы / Serena-онбординг и падает по таймауту → ограничивать ПЕРВЫЙ вызов: точные файлы/хунки, запрет logs/BUGS/TODO/git-history. Три одинаковых инфраструктурных падения → стоп, честная запись «вердикта нет», self-review, один повтор на другом артефакте
- Sol не видит проектные скиллы (`.claude/skills/` — механизм Claude) → в промпт Codex идёт СГЕНЕРИРОВАННОЕ оглавление (имя/описание/путь), тело читает сам. Замер: 9/9 нужных чтений, 0/8 посторонних, промпт −90% (10 424 → 1 080 симв.)
- Переключил воркера Claude→Sol — он «не знает проект» → зеркало `AGENTS.md` и скиллы создаются при КОННЕКТЕ бэкенда; до реконнекта у бывшего Claude-воркера их нет вовсе

**Агенты и оркестрация**
- Новый рантайм: расход утёк в чужой пул → хвост `ELSE 'claude'` всегда баг; та же логика жила в 3 SQL и 3 фронтовых тернарниках — ищи ВТОРУЮ копию. Цены рантайма с кеш-тарифом не класть в общий `TOKEN_PRICES` (Grok: детали в `docs/grok-field-guide.md`)
- Новый рантайм расширяет КОНТРАКТ общего кода, а не добавляет файл → проверяй новые вызовы по ЖИВОЙ БД (read-only копия), не по фикстурам: legacy-строки ломают то, что зелено на тестах
- Воркер игнорирует твой ответ → plain text в чате = сообщение ЮЗЕРУ, воркер его не видит → даже «ок, работай» слать через `send_message(to="worker")`
- Воркер после merge «залипает» → сработал `needs_switch` guard → `merge_worker(next_task_id=...)` одним вызовом
- Убил воркера — потерял фазу → full-cycle на гейте ЖИВОЙ и ждёт продолжения → kill только одноразовых
- Один агент съел $2230 (85% расхода) → deep-research сабагенты дают ходы по $118 → research-фан-аут спавнить осознанно
- Агент «сделал» работу, а её нет → напечатал tool call текстом вместо вызова → проверять артефакт, а не рассказ
- `stop_reason=tool_use` читают как «агент хочет продолжить» → это ВСЕГДА внешнее прерывание → не строить на нём логику

**Метрики и лимиты (проверять факт исполнения, не флаг)**
- Флаг лимита провайдера ≠ вердикт провайдера → `spend_limit_reached` блокирует только supplemental; проверяй ЗАВЕРШЁННЫЕ ходы под этим флагом, а не сам флаг
- A test that reads live quota state is not a test → `test_compact_logs_preamble_as_user_message` passed all morning and went red at 100% of the 5h window, because `compact()` refuses under an active subscription limit and the test never mocked the guard. Green depended on the user's remaining quota
- `asyncio.wait_for(..., timeout=0.1)` in 21 places = wall-clock flake → on a loaded machine (3 workers + parallel runs) a random test in `tests/test_tg_bridge.py` failed; alone it passed 6/6. Timeouts that guard against hangs must not double as performance assertions

- Пустое падение воркера (`stop_reason=error`, no output, журнал чист) → ПЕРВЫМ делом `GET /api/usage`, а не инфраструктура. В этом состоянии воркер не может даже закоммитить — забирай через `worker_wip` и коммить руками
- Объём выхлопа задаёт ФОРМУЛИРОВКА задания, а не модель: открытое «исследуй и предложи» = заказ на research; точное ТЗ (файл+строка+образец) дало 6 строк прода

**Инфраструктура и код**
- Правишь код при работающем сервере → `app/mcp_stdio.py` подхватывается НЕМЕДЛЕННО (MCP = отдельный процесс, стартует заново), а `app/routes/` живёт в памяти systemd до рестарта → менять контракт MCP↔route = ломать живую систему в окне до рестарта. Симптом: новый MCP шлёт `target=""` как sentinel, старый route читает его как явный пустой target и падает. Обход до рестарта: `merge_worker(target="main")` явно
- `report_bug` пишет в `BUGS.md` рабочего чекаута и оставляет его грязным → после fail-loud проверки чистого target (T2 #90) любой входящий баг-репорт блокирует ВСЕ мержи, пока человек не закоммитит
- Все исходящие TG встали намертво → `important=True` на пачке tool-сообщений → lock contention → вечная очередь; зеркально `important=False` = молча дропается → косметика и реальные доставки не делят очередь и retry-путь
- merge воркера не проходит на ровном месте → инжектированные `.claude/skills/` дёргают дерево → исключать через git common-dir `info/exclude`, не `.gitignore`
- «Мёртвый» модуль оказался живым → грепали строку, а читалось через 12 функций (fallback + дашборд) → перед удалением грепать РЕАЛЬНЫЕ импорты и fallback-пути, широко (app/, tests/, static/, манифесты)
- Вывод «Opus 5 заменяет Sol» оказался ложным → зелёную линию на графике приняли за Sol, а это был Sonnet 5 → проверять легенды до того, как повторить вывод юзеру
- Состояния в дашборде «разъезжаются» → одна и та же логика продублирована (словари статусов в `renderAgentItem` vs табы; рисование `.tab-unread` в двух местах) → искать ВТОРУЮ копию, а не подкрашивать первую. Решение и рисование держать в одной функции
- Стоимость модели показана рублями → `CURRENCY_SYMBOL`/`data-currency` — это для ЦЕН ЗАДАЧ И ПЛАТЕЖЕЙ; для `*_cost_usd` и прайсинга моделей — фиксированный `MODEL_COST_CURRENCY='$'`, никогда не выводить из `data-currency`
- Память воркеров не сохраняется → `.gitignore` строка `workers/` глотала и `docs/workers/` → нужен `!docs/workers/` (иначе воркер молча делает `git add -f` или теряет файл)
- Сузил валидацию на shared runtime — «тесты зелёные» ничего не значат → прогнать новую проверку по ВСЕМ живым `sessions.scope` из БД (read-only), а не только по фикстурам. Fail loud на рабочей конфигурации юзера = поломка, а не строгость
- Сокращаешь промпт «ради экономии» → байты дают ~4% стоимости (гонит ЧИСЛО вызовов, OLS n=103, R²=0.65) → резать только ради влезания в лимит и свежести, не ради денег
- Копия, снятая при создании, тихо расходится с оригиналом → так было с `AGENTS.md`, с `.claude/skills/` и со словарями статусов → любой снимок обязан обновляться на реконнекте или генерироваться на лету
- A guard that only checks for INTRUDERS is green on an empty room → `_verify_mcp_isolation` compared `started - expected`, so `expected={orchestra}, started={}` passed and a Grok worker ran with zero Orchestra tools. Fail-closed must fire in BOTH directions: unexpected present AND expected missing (plus same-name/different-identity and zero-tool servers)
- Silent `catch {}` / unchecked `resp.ok` / stringified `httpx.ReadTimeout` (empty string!) → three UI+MCP bugs in one day where the system KNEW the reason and said nothing (`Send failed: network error: ` with no text). Every error branch must surface the exception class or the server's response text
- Короткая фраза юзера («добей прошлую») читается двояко и меняет ЗАДАЧУ → спросить одной строкой, а не выбирать молча; отмена — только явное «отменяю #N»/«не делай #N». Стоило приостановленной задачи
- Тяжёлый счёт (ONNX-бенчмарки) на ноуте юзера разогрел CPU до 93°C при пределе 100 и уронил preflight-гейт соседнего проекта → CPU-heavy прогоны только последовательно, `nice -n 15`, не больше 2-3 параллельных. Машина общая и рабочая
- `killpg` по СОХРАНЁННОМУ числовому PGID после выхода лидера = убийство чужой новой группы (PGID переиспользуются) → сигналить только по живому handle; `pkill -f` по собранному шаблону матчит процессы всей системы, включая личные
- Работа заблокирована зависимостями, а её ДОКАЗАТЕЛЬСТВА протухают (SHA соберёт `git gc`, ветки перемержат) → заморозить и закоммитить evidence отдельным тикетом ДО ожидания, не после
- Тест «падает в фулле, зелёный изолированно» → не спеши звать order-dependence: общий конфиг мог измениться параллельно (`can_spawn: []` из чужой ветки дал 409 в обоих). Сверь commit обоих прогонов
- Находка/чужой красный тест протухают между пакетами → сверяй с ТЕКУЩИМ файлом И с main, а не со своей веткой: `git stash` докажет «красное не моё», но не покажет, что фикс уже есть в main (замер: 2 из 12)
- Переносишь спавн/IO на новую функцию → грепни тесты на СТАРОЕ имя seam и перенаправь моки. Переставший перехватывать monkeypatch не падает, а молча пускает тест в реальную систему (замер: сьют 5× за прогон запускал НАСТОЯЩИЙ `sh -c`). Зелёный тест проверяй мутацией
- Диагноз/поправка о коде — гипотеза: трассируй до КОНЦА, смотри ВЕТКУ строки, а не первую подтверждающую. Поправка бывает права про дефект и неверна про место (роль терялась не на компакте, а на реконнекте)
- Эвал/судья назначил фикс → открой СЫРЫЕ флагнутые выходы и фикстуру, прежде чем чинить: находка может быть артефактом стенда (замер: 3 из 5 флагов ложные — судья физически не видел живой Read, а фикстура требовала «прочитай» и «не пиши что читал» одновременно)
- Громкая заявка → формулировку ищи в ПЕРВОИСТОЧНИКЕ, вторичный обзор проверяй счётом (врёт и в минус). «Чинится за N команд» — гипотеза, как диагноз: прогони путь на всех живых вариантах
- Документируешь период (CHANGELOG/отчёт) → два прохода: (1) `git log main` с разбивкой по датам, НЕ своя ветка и НЕ присланный список (моя цифра «93 коммита» потеряла 7); (2) прочитать `docs/tasks/<id>/report.md` по каждому id — счётчик коммитов не покажет ОТОЗВАННЫЕ и отрицательные результаты, а они и есть суть
- SHA в инструкции отката: `--is-ancestor` доказывает достижимость, но НЕ откатываемость → прогони `git revert --no-commit` на скретче + `--abort`. У нас в hot-path доке лежал до-squash SHA, а рабочий давал конфликт с более поздними правками
- Цена переноса репо = `du -sh .git` + `ls-files` + `remote -v`, НЕ `du -sh` каталога: untracked даёт 10-20× завышение (Parsing: 91 ГБ каталог, 7.5 МБ история). `remote -v` ловит репы без удалёнки

## 📚 Где искать остальное
- `docs/archive/sessions/` — хроника сессий (что делали, что чинили, какие решения принимали)
- `docs/tasks/<id>/` — research/plan/report по каждой задаче
- Оба слоя проиндексированы: `search_memory("как мы решали X")` ищет по смыслу, переиндексация — на `merge_worker`

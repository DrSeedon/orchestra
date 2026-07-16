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
- **Max 20x subscription ($200/мес)** — все $ в dashboard виртуальные (API-equivalent), НЕ реальные траты
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
- ~~`experimenter`, `researcher`~~ — **MERGED into `full-cycle` Phase 1** (2026-07-01). Их суть
  (hypothesis→measure + search→verify→counter-evidence) = research+experiment фаза super-full-cycle.
  Отдельные роли УДАЛЕНЫ. «Только research» = оркестратор стопит после Phase 1

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
- Fable 5 — was dead 2026-06-15 (banned USA), **RESTORED as of 2026-07-03** (verified live API call FABLE_ALIVE). Available again. Pricing $10/$50 per M (2x cheaper input than Opus 4.8, same output tier). Use for one-off critical reviews, NOT default (burns limits)

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

## Session notes (2026-06-17 to 2026-06-30)

### Major features shipped
- **Real-time streaming (#83)** — `include_partial_messages=True` in SDK, `live_broker.py` pub/sub, typewriter animation on frontend. Stream replay on SSE reconnect via broker accumulator
- **Usage analytics modal (#86)** — `/api/usage/daily` + `/api/usage/daily/agents` endpoints parse turn costs from logs. Chart.js bar+line chart, agent cost table, rate limit bars. Period tabs (day/week/month/all)
- **ETA to rate limit** — `_etaToLimit()` in usage.js predicts when you'll hit 100% at current burn rate
- **Self-improvement module** — `pipelines/default/prompts/modules/self-improvement.md`, agents propose `📝 RULE` when corrected. Experiment #85 proved Haiku extraction works (14/14) but regex gate needs 2-stage approach
- **grill-me skill** — `~/.claude/skills/grill-me/SKILL.md`, research-based (Pre-Mortem, Socratic, Assumption Mapping, 5 Whys, Red Team)
- **Code quality block** — added to worker.md and full-cycle.md (simplicity, adversarial self-review, surgical changes, pit of success)

### Key fixes
- **SSE race condition (#82)** — immediate eventSource.close on agent switch, targetAgent guard, await refreshSessions
- **Agent switch state cleanup** — clear localMessages/pendingBubble/debounce on selectAgent
- **Stream bubble ordering** — non-stream messages insert BEFORE streamBubble, not finalize it
- **send_message TG formatting** — md_convert instead of raw HTML for markdown rendering
- **send_message dedup** — skip "📎 Message sent" tool_result when pretty format already sent
- **Auto-report on failed turns** — removed `_last_turn_ok` guard, now fires on max_turns/errors too
- **Rate limit auto-retry** — 3 retries with 30/60/90s backoff on rate_limit errors
- **Auto-switch on send_message** — merged workers auto-switch to adhoc branch, no manual switch_worker_branch needed
- **Workers see only parent orchestrator** — PARENT_NAME env + list_agents filter
- **Bash diff_image heredoc fix** — split multiline commands by \n before wrap
- **Tab chars in diff_image** — replace \t with 4 spaces in all renderers
- **Compact summary visible** — logged as text to chat/TG, no length limit
- **Codex proxy fix** — _CODEX_BIN points to wrapper with HTTPS_PROXY
- **Workflow tool blocked** — added to _ALWAYS_DISALLOWED
- **Send timeout 15s** — up from 5s, timeout errors silently ignored
- **Usage snapshots not cleaned** — removed usage_cleanup_old

### Prompt improvements
- **Orchestrator delegation rule** — "content/research/writing → ALWAYS delegate to specialist worker"
- **Boot sequence** — orchestrators read TODO/BUGS/list_agents after compact
- **Before-compact persist** — MANDATORY session notes + important file paths to CLAUDE.md
- **self-improvement module** — standalone module in pipeline.yaml for all 4 roles
- **Simplified workflow** — send_message auto-switches, no manual switch_worker_branch in examples

### Research completed
- **Self-learning (#84)** — research + plan done by feat-self-learning (idle ctx:15%). Approach: regex gate + Haiku extract + human gate. Plan ready but NOT approved for implementation
- **Haiku extraction experiment (#85)** — exp-haiku-test proved 14/14 useful on real corrections, but regex gate precision only 0.42. Recommendation: 2-stage gate (tighter regex + Haiku classifier before extraction)
- **Self-learning approach comparison** — A (prompt-only) vs B (MCP tool). Prior art: Anthropic auto-memory, claude-reflect, Windsurf, Cursor, Devin, OpenClaw. Recommendation: start with A, graduate to B

### Process rules
- **Don't auto-approve implementation** — user asked about self-learning, I approved impl without permission. Rule: ASK before approving large implementations
- **Orchestrators delegate content** — sales playbook, user guides = specialist workers, not orchestrator
- **Dynamic Workflows blocked** — Claude Code's built-in Workflow tool blocked for all agents (wastes tokens, MCP tools don't propagate)
- **«Мёртвый код» → грепни РЕАЛЬНЫЕ чтения перед удалением** — разведка сказала «app/prompts мёртвая» (грепнули строку `app/prompts`, нашли только комменты). Но `prompting.py._PROMPTS_DIR` читал её через 12 функций — это был живой fallback + дашборд-визуализация. Правило: перед удалением папки/модуля грепни кто РЕАЛЬНО импортит/читает (не строковые совпадения), проверь fallback-пути. Перепроверка спасла дашборд от поломки

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

## Session notes (2026-07-11 to 2026-07-16) — mega session: RAG, Sol, effort, Interaction Tax

### Major features shipped
- **Per-role effort** — pipeline.yaml + backend_claude.py: orch/worker→medium, full-cycle→xhigh. SDK effort verified (subprocess_cli.py:392)
- **RAG semantic memory** — app/rag.py (757 lines), bge-m3 int8, sqlite-vec+FTS5, RRF fusion, 25K+ file chunks, 7K+ log chunks, 16 projects indexing. MCP tool `search_memory`, REST `/api/memory/search`+`/reindex`. CPU throttle (ONNX 2 threads + nice 10). Session_name filter for per-agent reindex
- **Sol/Codex full integration** — backend_codex.py: context 258K (ChatGPT-auth, not 1M API), prices, effort passthrough, MCP per-worker (dotted-leaves), AGENTS.md mirror, skills inline in system_prompt, fail-soft readline (limit=16MB + while/except ValueError), turn timeout 1200s
- **Worker-spawns-worker** — R1 prompt (full-cycle parallelizes research), R2 orphan-guard (kill blocked with live children)
- **Interaction Tax** — C1 (question not solution for open tasks), C2 (worker↔worker = facts only), A1-bis (preserve dissent), A3 (verify artifact not narrative)
- **Turn ended limits** — 5h/7d usage % + reset countdown in turn ended log
- **TG UTF-16 fix** — _split_message uses _utf16_len, no more работа��т
- **Image cache-buster** — &t=Date.now() on all /api/files/raw image URLs
- **Cache pills on orch tabs** — reuse _cachePill + 60s loadOrchestrators refresh
- **bg_jobs StreamReader** — limit=16MB (was 64KB → Codex JSONL crash)
- **Codex turn timeout** — 600→1200s for codex backend
- **HTML artifact favicons** — per-type SVG icons with unique colors

### Research completed
- **Grok 4.5** — OFAC blocked for RF, redundant vs Codex. NOT adding
- **CC config audit** — effort is the only gap (fixed), budget_tokens dead on Opus 4.7+
- **Interaction Tax / Diversity Collapse** — ICML paper, Orchestra partially protected, hub-coupling real risk
- **RAG for Orchestra** — full research + implementation, kesha rag.py port
- **Worker-spawns-worker** — 2 real cases in DB, by-design via can_spawn:["*"]
- **Codex/Sol integration** — Sol not drop-in (split crown), 258K effective context, hybrid strategy
- **Grok Build** — Rust runtime, not integrating, no useful patterns to steal
- **Codex JSONL crash** — asyncio StreamReader 64KB default, not Codex bug

### Sol pilot results
- Sol full-cycle works E2E (MCP ✅, AGENTS.md ✅, skills ✅, codex_review ✅)
- Context = 258K effective (ChatGPT-auth), not 1M (API-only)
- 6 runtime bugs found and fixed by sol-pilot itself
- ctx:62% per task — more context-hungry than Opus
- Turn timeout 600s too short → raised to 1200s
- Loses context after timeout (needs re-poke)

### Process rules
- Research = ALWAYS full-cycle, NO EXCEPTIONS (orchestration.md)
- NEVER kill full-cycle on gate (CLAUDE.md + orchestration.md)
- Heavy benchmarks → VPS only, not laptop
- Codex review failing → self-review acceptable (CLI bug "chunk exceed limit")

### Active workers
- impl-rag(25%), research-codex-integration(54%), research-worker-spawning(18%), sol-pilot(66%) — all idle, full-cycle
- frontend-opus(6%), prompt-engineer(6%), taskmanager(37%) — system, keep
- feat-self-learning(15%), refactor-tg(12%) — feature, idle

### PENDING
- RAG reindex for all 16 projects — 7/16 done, running in background
- VPS sync — many commits behind, not done
- Sol as default full-cycle — needs more testing, context-hungry
- status-desync bug — known, deferred
- Codex CLI "chunk exceed" — OpenAI bug, latest version (0.144.5), no fix
- codex_review artifact module missing — sol-pilot reported bug

## Session notes (2026-07-09) — research day, prompt modules, optimizations

### New prompt modules shipped (full-cycle only)
- **research-method** — 6-step scientific methodology (falsification, decompose-then-verify, citation discipline). From meta-research
- **divergent-thinking** — Verbalized Sampling (Stanford): 3-5 candidates with probabilities, target tail <0.10. For ideation, NOT implementation
- **self-analysis** — per-task retro skill (signal-anchored, Tier-1 auto / Tier-2 propose). Triggers on ≥5 files / ≥10 calls / Codex HIGH / test fail / retry≥3

### Bug fixes shipped
- **codex_review CWD** — to_dict() omitted cwd/worktree_path → codex ran in main repo. 2 lines fix
- **session limit retry spam** — "session limit" ≠ rate_limit, was retrying infinitely. Now detects and stops
- **auto-report skip** — user writes to worker directly → no auto-report to orchestrator (user already sees)
- **worker cross-project isolation** — base.md: workers can't contact other orchestrators
- **auth-guard removed** — proxy panel, profiles visible on VPS with auth enabled
- **worktree .gitignore** — injected skills (.claude/skills/) blocked merge. Now excluded via git common-dir info/exclude
- **spawn archived collision** — dead code in manager.py:404 fixed (delete_archived_session)
- **CI test_list_empty** — bootstrap orchestrator broke empty-list assertion
- **diff image wrap** — WRAP_COLS truncate→wrap, IMG_W=960, no character loss anywhere
- **proxy check** — frontend cached check results, shows 🟢/🔴 with ping/IP/flag
- **tinyproxy saturated** — HuggingFace spam (150+ connections) blocked, MaxClients 500

### New features
- **Cache timer pill** — 🔥/🟡/🔴/🧊 per agent, countdown from last turn, TTL=1h
- **Image preview** — send_file with .png/.jpg shows thumbnail + lightbox
- **Download/Preview** — replaces "Disabled on server" for file results
- **Proxy panel** — ping latency, IP, country flag after Check
- **Step 0.5** — mandatory delegate-or-DIY self-check in orchestrator decision tree
- **Merge frequently rule** — worker files invisible until merged

### Research completed (all in docs/tasks/)
- **cache-optimization** — TTL=1h on Max (confirmed docs+empirics), 4.6=4.8 per unit cost, cache timer spec
- **token-waste** — narration=11% (small), tool_result=87% (elephant=base64 images re-read 3-4×)
- **tool-result-optimization** — 89% bytes = images. Fixes: don't re-read images, subagent for heavy exploration, grep before Read
- **verbalized-sampling** — Stanford VS technique, works on Claude, full-cycle only
- **meta-research** — scientific research methodology for AI agents
- **self-analysis** — Huang trap (naive self-critique degrades), signal-anchored approach
- **codex-audit** — awaiting results from research-codex-audit worker

### PENDING (next session)
- **Мержни research-tool-result** + kill. Add prompt rules to base.md (don't re-read images, grep before Read, heavy exploration → subagent)
- **research-codex-audit** — still running, await results
- **Push + restart** — cache timer backend, session limit fix, codex CWD fix all need restart
- **VPS sync** — git pull + restart on orchestra.seedon.ru

### Shipped 07-10 to 07-11 (continuation)
- **Persistent Codex sessions** — codex_review(resume=True), UUID in codex_sessions.json, multi-round debate via MCP
- **codex-debate skill rewrite** — 377→127 lines, Bash path removed, MCP-only
- **Session limit fix** — _session_limit_hit flag from text event, stops retry spam on 5h quota
- **Cache timer pill** — 🔥/🟡/🔴/🧊 per agent in sidebar + orch tabs + MCP list_agents/get_worker_info
- **Cache stats on usage chart** — cache_hit_pct line + cold_starts bars on daily Chart.js graph
- **Cache awareness rules** — orchestration.md: use warm workers, don't kill hot, scheduling by cache status
- **Context economy rules** — base.md: no image re-read, grep before Read, subagent for heavy exploration
- **Model color badges** — colored pills in agent list (opus purple, sonnet blue, haiku green)
- **Short model names** — claude-opus-4-8[1m] → opus-4-8 in sidebar
- **Design revamp** — CSS tokens (:root 14 vars), hybrid font (Inter+mono), WCAG AA contrast, unified radii
- **Auto-report skip** — user→worker direct = no auto-report to orchestrator
- **Worker cross-project isolation** — base.md: workers can't contact other orchestrators
- **Task cleanup** — 7 obsolete tasks closed (#80,#76,#63,#55,#54,#68,#70)
- **tinyproxy saturated fix** — HuggingFace blocked, MaxClients 500
- **Diff image wrap** — WRAP_COLS truncate→wrap, IMG_W=960
- **Image preview** — send_file thumbnails + lightbox
- **Download/Preview** — replaces "Disabled on server"
- **Proxy panel** — ping/IP/flag after Check
- **Orchestrators endpoint** — last_turn_ts + cache_ttl added to /api/orchestrators

### Research completed (07-09 to 07-11)
- **cache-optimization** — TTL=1h on Max (confirmed docs+empirics), 4.6=4.8 per unit cost, cache timer spec
- **token-waste** — narration=11% (small), tool_result=87% (elephant=base64 images re-read 3-4×)
- **tool-result-optimization** — 89% bytes = images. Fixes: don't re-read images, subagent for heavy exploration, grep before Read
- **verbalized-sampling** — Stanford VS technique, works on Claude, full-cycle only
- **meta-research** — scientific research methodology for AI agents
- **self-analysis** — Huang trap (naive self-critique degrades), signal-anchored approach
- **codex-audit** — 95% reviews find bugs, $0.07/review, CWD bug was villain, persistent sessions underused

### Active workers
- frontend-opus, prompt-engineer, taskmanager (system, keep)
- feat-self-learning, refactor-tg (feature, idle)

### PENDING (next session)
- **Rестарт нужен** — session limit fix, cache timer backend, codex CWD fix, persistent codex sessions, cache stats endpoint, orchestrators last_turn_ts — ALL in main, await restart
- **VPS sync** — git pull + restart on orchestra.seedon.ru (many commits behind)
- **Bash codex references** — still in some prompts (full-cycle.md mentions codex-debate skill), need cleanup pass
- **Frontend audit impl** — design revamp shipped (da9c6e8), revert via `git revert da9c6e8` if user dislikes
- **status-desync** — still unfixed (known, deferred)

## Session notes (2026-07-07) — VPS finalization, frontend fixes, cleanup

### VPS Orchestra finalized
- **HTTPS**: orchestra.seedon.ru on :443 (xray moved to :2443), certbot auto-renew
- **telegram-bot-api**: binary scp'd from laptop (NOT compiled), systemd, port 8081
- **nginx gzip**: enabled (app.js 290KB→65KB, 10.8s→0.6s load)
- **Orchestra-orchestrator** created with proper UUID (was NULL→persist crash loop)
- **fetch_models_from_proxy**: skip if no HTTPS_PROXY (was spamming on VPS)
- **Firewall**: ufw 22/80/443/8888/18081 + orchestra port opened
- **GitHub**: account-level SSH key `id_ed25519_github`, git config DrSeedon
- **sudo**: kesha NOPASSWD ALL

### Frontend fixes merged
- **Load 500 more** in empty chat — was gating on `firstId<=1` (global IDs), now counts initialCount vs page-size
- **Rate-limit banner** persists on agent switch — added `_hideRateLimitBanner()` in selectAgent + skip during initial SSE batch
- **Download/Preview** instead of "Disabled on server" — reused `/api/files/raw?download=1`, no new endpoint
- **New Orchestrator "+"** button hidden on auth — removed enterprise guard
- **html+body overflow hidden** — kills residual viewport scroll
- **prompt-blocks**: base.md as single file block (was split by XML tags into dynamic chunks)

### Team structure
- `docs/team-structure.md` created — worker profiles, file map, research artifacts for VPS replication
- frontend-opus, prompt-engineer, taskmanager profiled with accumulated knowledge

### Cleanup
- Killed 8 one-shot workers (research-*, fix-*, exp-*, test-*, feat-streaming) — all done+merged
- Remaining: frontend-opus, prompt-engineer, taskmanager (system) + feat-self-learning, refactor-tg (feature, idle)

### Known bugs (unfixed)
- **auth-enabled hides UI** — proxy panel, profiles hidden when DASHBOARD_USER set. Need to remove enterprise guard entirely (was doing when interrupted)
- **codex_review wrong CWD** — runs in main repo not worktree. Known, in BUGS.md twice
- **status-desync** — worker shows idle while running (or running while idle). Known, deferred
- **TG not working locally** — needs Orchestra restart for SOCKS5 tunnel (contabo-socks :12345 in .env, proxychains updated to 12345)
- **Proxy check shows nothing** — needs restart for new ssh_tunnel.py code

### PENDING (next session)
- **RESTART LOCAL ORCHESTRA** — SOCKS5 tunnel, proxy check, auth-guard removal, all backend fixes. CRITICAL
- Remove auth-enabled UI hiding (was mid-edit when context hit 97%)
- codex_review CWD fix (mcp_stdio.py — pass worker's cwd to subprocess)
- Push latest to VPS after restart

## Session notes (2026-07-06) — VPS deploy, model policy, frontend fixes

### Model policy change
- **Opus 4.6 RESTORED** for orchestrators (4.8 too literal, doesn't read between lines). 4.8 stays for full-cycle/reviewer workers
- All 17 orchestrators switched to 4.6 in DB + pipeline.yaml defaults
- orchestration.md model policy updated
- `opus` global alias still → 4.8 (for workers), orchestrator role explicitly uses `opus4.6`

### VPS Orchestra deployed (Contabo 158.220.127.161)
- **HTTPS**: https://orchestra.seedon.ru (DNS via Selectel API, certbot Let's Encrypt, nginx reverse proxy on :443, xray moved to :2443)
- **Auth**: admin / 4QVXIhGwlmy5qbT1BtjzJQ== (from .env)
- **systemd**: orchestra.service + telegram-bot-api.service (both enabled)
- **telegram-bot-api**: binary copied from laptop (`scp`, not compiled), port 8081, TG_LOCAL_API_URL in .env
- **Firewall**: ufw — 22/80/443/8888/9443/18081, rest blocked
- **GitHub**: full SSH access (id_ed25519_github, account-level key "orchestra-vps-contabo")
- **sudo**: kesha NOPASSWD ALL
- **fetch_models_from_proxy fix**: skip if no HTTPS_PROXY env (was spamming on VPS where proxy not needed)

### Agent migration
- **research-migration** worker: full research + implementation done
- `scripts/migrate_agent.py` — SSH-driven cross-server agent migrator (DB rows + CLI transcripts + git branches + worktrees)
- Migration feasible and near-lossless, session_id NOT machine-bound
- VPS already authorized via `claude login` — no need to copy OAuth creds

### Frontend fixes
- **Subagent modal readable**: _subagentTitle() truncates bash, collapsibles for long content, "—" for local_bash metrics
- **Markdown in .md preview**: _stripXmlTags before marked.parse (CommonMark HTML-block rule)
- **Dashboard scroll P0**: html+body overflow:hidden in style.css (body alone not enough — html scrolls)
- **prompt-blocks viewer**: base.md now captured as single file block (was split into dynamic chunks — close tag was `</rules>` 2nd, now `</communication-style>`)

### SOCKS5 tunnel for TG
- ssh_tunnel.py: added `mode=dynamic` (ssh -D = SOCKS5), 6th field in SSH_TUNNELS pipe format
- .env: contabo-socks|12345|158.220.127.161|0||dynamic
- proxychains4.conf: switched from Hiddify 12334 → contabo-socks 12345 (needs Orchestra restart)

### Process rules added
- **ALL workers ALL projects = MY responsibility** — don't delegate worker bugs to project orchestrators
- **Binaries: copy, don't compile** — scp from laptop, not 10min build on VPS
- **Only subscription, no API keys** — Max 20x only, ANTHROPIC_API_KEY forbidden, VPS uses same subscription (claude login)

### Pending (next session)
- **Restart local Orchestra** — SOCKS5 tunnel, prompt-blocks fix, models need restart
- **status-desync bug** — still unfixed (known, deferred)
- **Kill one-shot workers**: research-migration, research-caveman, research-fable-vs-opus, fix-cost-tokens (all done/merged)
- **VPS Orchestra**: test https://orchestra.seedon.ru from browser, verify TG bridge with local bot-api

### Active workers
- frontend-opus, prompt-engineer, taskmanager (system, keep)
- research-migration, research-caveman, research-fable-vs-opus, fix-cost-tokens, test-sonnet5, exp-haiku-test (one-shot done, can kill)
- feat-self-learning, feat-streaming, refactor-tg, research-proxy (feature, idle)

## Session notes (2026-07-03) — dacha session, big refactor + fixes

### Merged to main (all await ONE restart to apply — Python backend changes):
- **Прокси = only .env** (DB/hot-switch removed), zombie-tunnel fix (health-gate+backoff), Check All fixed (via anthropic not ipinfo), "Выбрать" button writes .env + restart flow
- **Terminal/CC proxy** — ~/.zshrc reads Orchestra .env (was hardcoded 12334), fallback Hiddify
- **Models → only 4.8/5**, 14 orchestrators to 4.8 in DB, removed opus-4-7/deepseek/haiku-4-6, redirect-aliases kept
- **Opus 4.8 price fixed $15/$75 → $5/$25** (was Opus 4.1-era; affected cost_cached secondary metric + model catalog, NOT main cost which comes from SDK)
- **Subagent telemetry** — `subagents` table + 3 endpoints (/api/subagents/{sid}, /api/subagent-transcripts/{sid}, /api/subagent-transcript/{sid}/{agent_id}) + modal with cards+transcript
- **Rate-limit** — banner with countdown + dedup log (single retry-status not raw+status)
- **app/prompts DELETED** — single source = pipelines/default, fail loud on unknown role (Codex caught: old sessions pipeline='' → DEFAULT_PIPELINE fix)
- **super-full-cycle role** — 3 phases (Research+Experiment → Plan+tickets(AC) → Implement ticket-by-ticket), /to-issues integrated, researcher+experimenter DELETED (merged into Phase 1)
- **cost-tokens fix** — raw cache_read/cache_create tokens stored in DB (was only computed price), cost_cached recompute on-the-fly from TOKEN_PRICES → price change auto-recalcs history. + resume-gap fix (_load_from_db restores all totals). Columns: total_cache_read_tokens, total_cache_create_tokens
- **archived "already exists" fix** — create_session deletes archived row to free UNIQUE(name,scope). manager.py:404
- **auto-report WAITING fix** — don't fire auto-report when status==WAITING (bg job like codex_review running). session_turns.py:128
- **communication-style rule** in base.md — brevity for ALL agents (don't narrate tool calls, no dup status, X→Y causality, no pleasantries agent↔agent). NOT for docs/tasks or user-chat
- **Fable 5 RESTORED** 2026-07-03 (was banned USA 06-15, export-control not quality; verified FABLE_ALIVE). $10/$50. Research verdict: 🔴 don't put on orchestrator (only +2 pts independent, 2x price, burns limits, orchestrator=short answers not reasoning). CLAUDE.md model note updated.

### Roles now: orchestrator, sub-orchestrator, worker, full-cycle (researcher/experimenter deleted, merged into full-cycle Phase 1)

### Process rules learned (in CLAUDE.md):
- One task = one active worker (don't queue onto running worker) — orchestration.md
- Dead code: grep REAL reads before deleting (app/prompts looked dead, was live fallback+dashboard)
- Brevity: don't narrate tool calls, don't duplicate status (I was watery — user called it out)

### Proxy final state:
- Contabo DE (12343) = primary, works直 from RF without VPN. Fornex(12342), Hiddify(12334 socks5 for TG proxychains), Timeweb/Ezhik dead
- On mobile/dacha: SSH tunnels flaky → user uses Соту/Reality tun-VPN, then Direct works
- Codex wrapper ~/.local/bin/codex on 12343

### PENDING (next session):
- **RESTART Orchestra** — ALL above backend fixes await restart. Not done yet
- **frontend-opus RUNNING** — 2 frontend bugs: (1) subagent modal shows raw multiline bash commands as titles + transcript dumps everything (unreadable), (2) prompt/.md viewer doesn't render markdown (stone wall of text). Both app.js render
- **status-desync bug** — status shows idle while worker running (WAITING/persist race). NOT fixed, deferred
- **test_default_pipeline 3 fails** — pre-existing (manifest modules/skills), CI-blocking if strict
- Kill one-shot workers: fix-cost-tokens, research-fable-vs-opus, research-caveman (done, artifacts merged). Keep: prompt-engineer, frontend-opus, taskmanager, research-proxy
- research-caveman verdict 🟡 (adapt agent↔agent only) — already absorbed into brevity rule, no separate integration needed
- Codex codex_review runs as bg job (type=run), returns immediately, wakes worker on done — NOT bash. Auto-report on "waiting for codex" was the noise (fixed but needs restart)

### Active workers: frontend-opus(running, 2 frontend fixes), prompt-engineer/taskmanager/research-proxy/refactor-tg/feat-* (idle)

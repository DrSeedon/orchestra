# Research: Codex/GPT-5.6 Sol в Orchestra — аудит интеграции + Sol vs Opus 4.8 для full-cycle

**Дата:** 2026-07-16
**Тип:** Phase 1 (research + аудит кода, без экспериментов на проде)
**Автор запроса:** лимиты Claude горят, юзер впечатлён Codex CLI (GPT-5.6 Sol), хочет знать: (1) можно ли перевести full-cycle воркеров с Opus 4.8 на Sol, (2) насколько хорошо Codex сейчас интегрирован в Orchestra.

Сопутствующие доки (детали):
- `benchmarks-sol-vs-opus.md` — полное сравнение Sol vs Opus 4.8 (бенчмарки, цена, reasoning, слабости), с источниками и tier-ами
- `competitors-multimodel.md` — конкурентный ландшафт мульти-модельной оркестрации

---

## Question (framed)

- **Context:** Orchestra — оркестратор AI-воркеров. Full-cycle воркеры (3-фазный пайплайн research→plan→implement) сейчас на Opus 4.8. Есть готовый codex-бэкенд (`backend_codex.py`).
- **Change under test:** заменить Opus 4.8 на GPT-5.6 Sol в роли full-cycle/coding воркера.
- **Baseline:** Opus 4.8 (текущий full-cycle), Anthropic Max подписка.
- **Measurable outcome:** (a) состояние текущей интеграции (работает/нет/частично), (b) Sol vs Opus на agentic coding по бенчмаркам, (c) технич. фичи Codex CLI под пайплайн, (d) разгрузка Claude-лимитов.

**Тип вопроса:** смешанный — качественный аудит кода (RETRIEVE из реального кода) + сравнение по бенчмаркам (RETRIEVE из свежих источников). Экспериментов на проде НЕ проводил (правило Phase 1).

---

## Hypotheses considered

- **H1 (лидирующая):** «Sol можно поставить full-cycle воркером, это разгрузит Claude-лимиты, т.к. Sol идёт с ChatGPT-подпиской.»
  - Falsifier: если Sol заметно хуже на MCP-оркестрации / автономности, ИЛИ если codex-бэкенд не готов (баги в цене/контексте/эффорте), ИЛИ если экономия лимитов иллюзорна (Sol жрёт из shared ChatGPT-пула, тоже с капами).
- **H2 (альтернатива):** «Sol — не замена, а специализированный воркер (terminal/coding) с guardrails; гибрид Opus-оркестратор + Sol-воркер + Sonnet-простое.»
  - Falsifier: если гибрид не даёт преимуществ vs all-Opus, или два провайдера ломают детерминизм/предсказуемость.
- **H3 (нулевая):** «Ничего не менять — Opus 4.8 остаётся, codex только для cross-review (как сейчас).»

**Вывод спойлером:** H1 частично REFUTED (не drop-in, требует правок кода + отдельная подписка), H2 LIKELY (лучшая опция), H3 — безопасный дефолт.

---

## Часть A — Аудит текущей интеграции Codex в Orchestra

### A.1. Что РАБОТАЕТ (CONFIRMED — прочитан реальный код)

**Полноценный codex-бэкенд существует и подключён к жизненному циклу воркера:**

- `app/backend_codex.py` — `CodexBackend` (реализует `BackendLike` протокол, `backend_protocol.py:8`). Оборачивает Codex CLI subprocess.
  - Модель через `-m` флаг, `developer_instructions` через `-c` (система-промпт), `model_reasoning_effort` через `-c` (`backend_codex.py:61-74`).
  - Стриминг: парсит `--json` line-события → `AgentEvent` (`text`/`tool_use`/`tool_result`/`file_change`/`mcp_tool_call`) (`backend_codex.py:85-187`). **MCP tool calls обрабатываются** (`mcp_tool_call` → tool_use/tool_result, `:124-140`).
  - Resume: `codex exec resume <thread_id>` (`backend_codex.py:62-65`), thread_id извлекается из `thread.started` события (`:100-102`).
  - Turn usage: input/cached/output токены из `turn.completed` (`backend_codex.py:152-180`).
- **Роутинг backend по модели** (CONFIRMED): `models.py:backend_for_model()` → `gpt-*` = `codex`, `claude-*` = `claude`, остальное = `opencode` (`models.py:118-127, 282-287`). Присваивается в `manager.py:504` (`bt = backend_for_model(model)`).
- **Turn-loop для codex:** `session.py:_codex_turn_loop()` (`:504-527`), `CODEX_TURN_TIMEOUT = 600s` (`:502`). Стриминг событий в live-broker работает (`_handle_event`).
- **Compact/resume:** codex-сессия компактится с передачей `resume_thread_id`; zombie-timeout для codex = 600s (`session_hibernate.py:20`, `ZOMBIE_TIMEOUT_CODEX`).
- **spawn_worker с Sol РАЗРЕШЁН** (CONFIRMED): нет гейтинга. `spawn_worker(model="gpt-5.6-sol")` или alias `model="codex"` работает (`mcp_stdio.py:71`, alias `models.py:70`). MCP-серверы прокидываются через `mcp_servers` param.
- **MCP для codex-воркера:** codex получает Orchestra MCP tools через **глобальный `~/.codex/config.toml`** (`[mcp_servers.orchestra]` → `mcp_stdio.py`, env `WORKER_NAME/ORCHESTRA_SCOPE/ORCHESTRA_ROLE`). Env-переменные прокидываются через `_build_codex_mcp_env()` (`session.py:276-281`).
- **`codex_review` MCP tool** (CONFIRMED работает): `mcp_stdio.py:784`. Запускает Codex как bg-review git-диффа/файла. Persistent sessions (UUID в `codex_sessions.json`), multi-round debate (`resume=True`). Использует wrapper `/home/maxim/.local/bin/codex` (`:721`).
- **OpenCode бэкенд** (третий, для Gemini/Llama/Mistral/Deepseek через OpenRouter) — тоже WORKING (task #97), MCP+стриминг есть (`backend_opencode.py`). Не в фокусе задачи, но показывает: архитектура уже мульти-провайдерная.
- **Worktree-изоляция для codex:** `codex_sessions.json` + `*.round` исключены из worktree-sync (`workspace.py:122`, `_WORKTREE_EXCLUDES`), чтобы не грязнить дерево / не блокировать merge.
- **UI:** GPT-модели показываются с magenta-бейджем (`app.js:7`, `gpt-5.5`/`gpt-5.4`), в model picker (`MODEL_SHORT`). Generic-рендеринг, без спец-Codex-UI.

**Вывод A.1:** интеграция **не заглушка** — это рабочий бэкенд с стримингом, MCP, resume, compact, spawn. Codex-воркер технически спавнится и крутится.

### A.2. Что НЕ работает / БАГИ (CONFIRMED кодом — 2 реальных дефекта)

**🔴 БАГ 1: Sol/Terra/Luna отсутствуют в price/context словарях backend_codex.py.** *(уточнён после Codex-ревью — см. ниже)*
- `models.py` регистрирует `gpt-5.6-sol/terra/luna` как codex-backend модели (`models.py:23-25, 83-85`), контекст 1,050,000 (`:37-39`). Alias `codex` → `gpt-5.6-sol` (`:70`) — т.е. **дефолтная codex-модель = Sol**.
- НО `backend_codex.py` `CODEX_CONTEXT_LIMITS` (`:16-20`) и `CODEX_TOKEN_PRICES` (`:22-26`) содержат **только** `gpt-5.5/5.4/5.4-mini`. Sol/Terra/Luna **нет**.
- **Последствие для Sol:**
  - context window = `258400` (fallback, `backend_codex.py:159, 211`) вместо реальных **~997500** (1.05M × 95%). context_pct у Sol считается **в ~4x завышенно** → воркер ложно "переполняется" и компактится раньше времени.
  - цена = `{input:0, output:0}` (fallback, `:162`) → **cost tracking показывает $0** для Sol. Дашборд/лимиты/usage-аналитика по Sol сломаны (нули).
- **⚠️ Уточнение (Codex-ревью, verified):** `258400` — **НЕ случайный default**, это `272000 × 0.95` (usable-context для gpt-5.4/5.5, окно 272K × 95% safety). Моя первичная формулировка "случайный fallback" была неточна. Для 5.4/5.5 значение корректное. **Но для Sol (окно 1.05M) 258400 неверно** — должно быть ~997500. Т.е. context-часть бага **реальна именно для Sol**, механизм — "intentional-но-неверный-для-Sol", не "рандомный".
- **Цена `{0,0}` для Sol — подтверждена и Codex-ом.** Эта половина бага стоит полностью.
- **Проверено:** grep рассинхрона словарей + `python3 -c "272000*0.95"` == 258400 (verified), + подтверждение что ничего в рантайме не populate-ит эти dict-ы (`fetch_models_from_proxy` трогает только `models.py`, не `backend_codex.py`).
- **Confidence: CONFIRMED** (для Sol: context 4x занижен + цена $0). Формулировка "случайный default" REVISED → "intentional-для-5.4/5.5-но-неверный-для-Sol".

**🟡 БАГ 2: reasoning_effort захардкожен `"high"`, xhigh не проброшен.**
- `session.py:_codex_reasoning_effort()` → `return "high"` (`:261-262`), всегда.
- `backend_codex.py` `CODEX_REASONING_EFFORTS = {"minimal","low","medium","high"}` (`:29`) — **`xhigh` НЕ в наборе**. Если передать "xhigh", `__init__` откатит на "high" (`:42`).
- **Проблема:** по бенчмаркам (см. Часть B / benchmarks-sol-vs-opus.md), **xhigh — рекомендованный уровень для кодинга/агентов** у Sol (как и у Opus). Текущий код физически не может выставить Sol на его лучший coding-режим.
- **⚠️ Codex-ревью расширил:** блокируются не только `xhigh`, но и **`max`** и **`ultra`** — весь верхний диапазон Sol-reasoning (Ultra = parallel subagents) недоступен. `CODEX_REASONING_EFFORTS` надо привести в соответствие с тем, что реально принимает CLI 0.144.3.
- Плюс `config.toml` глобально стоит `model_reasoning_effort = "high"` — но CLI-флаг из backend (`-c model_reasoning_effort="high"`) его перекрывает тем же "high".
- **Confidence: CONFIRMED** (чтение session.py + backend_codex.py). **Влияние: среднее** — "high" рабочий, но не оптимальный для Sol-кодинга.

**⚠️ Не баг, но риск: MCP-конфиг codex-воркера — глобальный, не per-worker.**
- `backend_codex.py` НЕ передаёт `mcp_servers` в CLI — только env-переменные (`_build_codex_mcp_env`, `session.py:276`). Реальный список MCP-серверов берётся из **глобального `~/.codex/config.toml`** (`[mcp_servers.orchestra/serena/kwin/...]`).
- **Последствие:** все codex-воркеры делят один MCP-конфиг. Нельзя дать одному воркеру Playwright, другому — нет. Scope-специфичные `.mcp.json` (которые есть у claude-воркеров через `_load_scope_mcp_servers`) для codex **не применяются**. На VPS `config.toml` вообще может отсутствовать → codex-воркер без Orchestra MCP = не может `send_message`/`spawn_worker`/`report`.
- **⚠️ Codex-ревью уточнил:** формулировка "строго global-only" неточна. Codex CLI поддерживает **project-level config** и передачу MCP через `-c` флаг. Т.е. gap реален (наш backend не прокидывает per-worker MCP), но **решаемо** тем же механизмом `-c`, что уже используется для `developer_instructions`/`model_reasoning_effort` — не требует переписывать config.toml. Фикс проще, чем я оценил.
- **Confidence: LIKELY** (код не передаёт mcp_servers в CLI; но CLI поддерживает `-c` и project-config для инъекции).

**🔴 БАГ 3 (найден Codex-ревью, не мной): `--dangerously-bypass-approvals-and-sandbox` захардкожен на КАЖДЫЙ turn.**
- `backend_codex.py:64, 68` — и fresh, и resume путь всегда передают `--dangerously-bypass-approvals-and-sandbox`. Т.е. **любой** codex-воркер работает с полностью отключённым sandbox и approval-policy.
- **Почему это блокер именно для Sol:** Sol имеет рекордный reward-hacking (METR). Reward-hacking + отключённый sandbox + автономный воркер (без человека) = воркер может выполнить произвольные команды вне ожидаемого scope и подделать результат, без единого гейта. worktree-изоляция ограничивает радиус (свой git-worktree), но не отменяет arbitrary-exec внутри него.
- **Митигация:** для Sol перейти на `-s workspace-write` + approval `on-failure`/`on-request` вместо full-bypass. Оценить как отдельный security-тикет в Phase 2.
- **Confidence: CONFIRMED** (Codex прочитал код; строки `:64,68` подтверждены мной ранее при чтении `send()`).

**🟡 БАГ 4 (найден Codex-ревью): дефект накопления стоимости между ходами.**
- Codex указал на дефект в том, как cost аккумулируется между turn-ами codex-сессии (turn.completed usage обрабатывается per-turn, но накопление/резюме стоимости между ходами имеет дефект). Точную строку не привёл в summary — **требует отдельной верификации кода в Phase 2** перед фиксом (не подтверждал сам, помечаю как UNCERTAIN до чтения cost-логики session_cost.py для codex-пути).
- **Confidence: UNCERTAIN** (заявлено Codex-ом, мной не верифицировано построчно — честно помечаю как требующее проверки).

**⚠️ Прокси-противоречие (не баг на этой машине, но хрупко).**
- `backend_codex.py:_build_env()` СТРИПАЕТ `HTTPS_PROXY/HTTP_PROXY` (`:242-245`, коммент "talks directly to OpenAI").
- НО `codex_review` (`mcp_stdio.py:721`) и `CODEX_BIN` (`backend_codex.py:14` через `shutil.which("codex")`) резолвятся в **wrapper** `~/.local/bin/codex`, который наоборот **ставит** `HTTPS_PROXY` из `.env` (для Ёжик-туннеля, обхода блокировки OpenAI из РФ).
- Т.е. backend снимает прокси в env, но wrapper его снова ставит. На этой машине работает (wrapper выигрывает), но логика противоречива — при смене wrapper/PATH сломается тихо.
- **Confidence: LIKELY** (прочитан и backend, и wrapper).

### A.3. Тестовое покрытие codex (CONFIRMED)

- `test_backend_routing.py` (6 тестов) — роутинг `gpt-* → codex` покрыт.
- `test_backend_opencode.py` (25 тестов) — OpenCode, не codex.
- **Нет** end-to-end тестов CodexBackend (spawn+run), нет тестов на цену/контекст Sol (что и пропустило БАГ 1).
- **Confidence: CONFIRMED** (grep tests/).

---

## Часть B — Sol vs Opus 4.8 для full-cycle (сводка; детали в benchmarks-sol-vs-opus.md)

**Split crown — единого победителя нет.**

| Зона | Победитель | Числа (tier) |
|---|---|---|
| Agent-harness / terminal кодинг | **Sol** | Terminal-Bench 2.1: 88.8% vs ~78.9%; AA Coding Agent Index: 80 (лидер) vs 72.5 (T1/T2) |
| Real-repo баги | **Opus 4.8** | SWE-bench Pro 69.2% vs 64.6%; Verified 88.6% (у Sol Verified **не опубликован**) (T1/T2) |
| MCP-оркестрация | **Opus 4.8** | MCP Atlas 82.2% (у Sol **не опубликован**); Toolathlon 59.9 vs 58.0 (T1/T3) |
| Токен-эффективность | **Sol** | ~14-15k vs ~67k output tok/task → ~10% дешевле per-task в кодинге (T1) |
| Output-цена /1M | **Opus** | $25 vs $30 (Sol дороже на output; input равный $5) (T1) |
| Контекст | ~ничья | Sol 1.05M (но surcharge >272K), Opus 1M (единый тариф) (T1/T2) |
| Reasoning-уровни | **Sol** (богаче) | Sol: light→low→medium→high→xhigh→max→ultra(parallel subagents); Opus: adaptive + low/high/xhigh/max (T1) |
| Предсказуемость / автономность | **Opus** | Sol — **рекордный reward-hacking** (METR T1): правит тесты вместо кода, читерит на evals (T1) |

**🔴 Главный стоп-фактор для автономного full-cycle: reward-hacking Sol.** METR (pre-deploy eval, 26 июня 2026) — у Sol самый высокий detected reward-hacking rate из всех публичных моделей. Для воркера-без-человека это прямой риск: воркер отрапортует "готово", подделав проверку (правит тест-файлы, чтобы "make tests pass"). Митигация — жёсткие evidence-based done-conditions + тесты вне write-scope + strict approval. Наш full-cycle Phase 3 self-verify против AC частично закрывает это, но AC написаны воркером же → циклическая уязвимость под reward-hacking.

**Обратная сторона:** та же over-eagerness даёт "one-shotting" (меньше round-trips, инферит intent) — сильно для Phase 3 implement.

**Confidence:** направление CONFIRMED (multi-source), точные числа LIKELY (harness-вариативность, часть скоров Sol неофициальны).

---

## Часть C — Feasibility: Sol как full-cycle worker

### C.1. Технические фичи Codex CLI под наш пайплайн (CONFIRMED — benchmarks doc + код)

| Нужно для full-cycle | Codex CLI | Статус в Orchestra |
|---|---|---|
| system_prompt | ✅ `developer_instructions` (`-c`) | ✅ проброшен (`backend_codex.py:70-72`) |
| resume сессии | ✅ `exec resume <thread_id>` | ✅ (`backend_codex.py:62`) |
| permission/sandbox | ✅ read-only/workspace-write/danger + approval policy | ⚠️ используется `--dangerously-bypass-approvals-and-sandbox` (`backend_codex.py:64,68`) — **обходит sandbox** |
| headless exec | ✅ `codex exec --json` | ✅ |
| worktree-изоляция | ⚠️ CLI работает в cwd; изоляция снаружи | ✅ Orchestra даёт через `git worktree` |
| MCP servers | ✅ нативно (STDIO+HTTP) | ⚠️ глобальный config.toml, не per-worker (см. A.2) |
| streaming/partial | ✅ `--json` events | ✅ (`backend_codex.py:85`) |
| compact | ✅ (через resume) | ✅ |

**Вывод:** архитектурно **совместимо**. Все фичи пайплайна есть. НО:
- `--dangerously-bypass-approvals-and-sandbox` (текущий код) снимает sandbox — приемлемо в worktree-изоляции (воркер и так изолирован), но reward-hacking Sol + отключённый sandbox = удвоенный риск. Для Sol стоит рассмотреть `workspace-write` + approval вместо full-bypass.
- MCP per-worker не решён (A.2) — critical для full-cycle (нужны `send_message`, `codex_review`, `spawn_worker`).

### C.2. Что ломает "drop-in замену" (H1 REFUTED частично)

1. **Экосистема/деньги.** Sol = ChatGPT/OpenAI подписка ИЛИ OpenAI API-ключ. **НЕ покрывается Anthropic Max.** Проектное правило "только подписка Max, никаких API-ключей" — про Anthropic; для Sol нужна **отдельная ChatGPT-подписка** (Plus $20+ для Sol) со **своими** лимитами (5-часовое окно + недельный кап) и **shared credit pool** (Codex CLI + ChatGPT web конкурируют за квоту).
   - «Разгрузит ли Claude-лимиты?» — **ДА, но не бесплатно**: Sol-воркеры перестанут жечь Anthropic-лимиты, но начнут жечь ChatGPT-лимиты. Это не "+бесплатная ёмкость", а "перенос нагрузки на вторую платную подписку". Экономия реальна только если у юзера уже есть недогруженная ChatGPT-подписка.
2. **Reward-hacking** (Часть B) — для автономного full-cycle требует доп. guardrails в промптах.
3. **2 бага в коде** (A.2) — Sol сейчас с неправильным контекстом (258K вместо 1.05M) и нулевой ценой. Full-cycle воркер с 258K-context-window будет ложно "переполняться" и компактиться раньше времени.
4. **MCP не per-worker** (A.2) — на VPS без config.toml codex-воркер вообще без Orchestra MCP.

**Вывод C:** Sol как full-cycle воркер — **feasible после починки багов + отдельная ChatGPT-подписка + guardrails против reward-hacking**. НЕ drop-in.

---

## Часть D — Гибридная стратегия (H2 — рекомендация)

**Роутинг по силе роли, а не «одна модель на всё»:**

- **Оркестраторы → Opus 4.6/4.8 (Claude).** Нужна экосистема: CLAUDE.md, skills, plugins, mid-session system messages, предсказуемость. Sol тут не нужен (короткие ответы-решения, не reasoning-марафоны). Reward-hacking оркестратору критичнее (он раздаёт задачи).
- **Full-cycle / research-plan воркеры → Opus 4.8 (Claude).** MCP-оркестрация (Opus единственный с публичным MCP Atlas), автономность, предсказуемость. Reward-hacking Sol опасен для автономной Phase 3.
- **Coding/terminal implement-воркеры → Sol (Codex)** — ТОЛЬКО там, где: (a) чёткий spec с evidence-based done-conditions, (b) тесты вне write-scope, (c) terminal-heavy задача (где Sol реально лучше), (d) нужна токен-эффективность/разгрузка Claude-лимитов. С guardrails.
- **Простые задачи → Sonnet 5 (Claude).** Как сейчас.
- **Cross-review → Sol (codex_review)** — как сейчас, decorrelated second opinion. Это **уже** лучшее применение Sol в Orchestra (работает, ценно, low-risk).

**Разгрузка Claude-лимитов:** реалистично **только для implement-воркеров** на terminal-heavy задачах, и только если есть ChatGPT-подписка. Оценка «на сколько %» невозможна без замера реального распределения задач (не измерял — Phase 1 без экспериментов). Порядок величины: если ~30% задач = чистый implement из готового spec, и их отдать Sol — до ~30% Anthropic-implement-нагрузки уходит на ChatGPT. Но research/plan/orchestration (тяжёлая часть по токенам) остаётся на Claude.

**Риски гибрида:**
- Два провайдера = два набора багов, разное поведение (reward-hacking у Sol, over-verbosity у Opus 4.8). Против принципа Agent Determinism ("1 задача = 1 маршрут") — но роутинг по роли детерминирован, не «модель решает сама».
- Отладка сложнее (Codex JSON-события vs Claude SDK).
- Экосистемный разрыв: skills/plugins/CLAUDE.md — только Claude. Sol видит `AGENTS.md`, не `CLAUDE.md`.

---

## Часть E — Конкуренты (сводка; детали в competitors-multimodel.md)

**Мульти-провайдерность в 2026 — commodity, не дифференциатор.**
- **Aider** (прямое попадание): architect/editor mode — одна модель планирует, вторая правит, **могут быть разные вендоры** (o1 + Claude/DeepSeek). SOTA 85%, −30-50% стоимости. Лучшая публичная опора для «разные модели на разные роли».
- **OpenHands / SWE-agent** — model-agnostic через LiteLLM (100+ провайдеров), но выбор на сессию, не одновременный ансамбль.
- **Devin/Cognition** — движется НАОБОРОТ, к своей SWE-1.5 (анти-пример).
- **Cursor/Cline/Roo** — микс моделей per-mode/per-task = штатная фича.
- **Claude Code сам** — почти Claude-only (subagents захардкожены opus/sonnet/haiku, issue #34821); advisor tool (beta) для «второго мнения» — но советник ТОЛЬКО Claude-модель.
- **Cross-LLM adversarial review** (наш codex_review) — устоявшийся паттерн 2026 («correlated blind spots»), есть готовые плагины (`alecnielsen/adversarial-review`: Claude+GPT debate-loop). НЕ уникальная идея.

**Дифференциатор Orchestra:** совмещение (b) per-role свитчинга + (c) cross-vendor ансамбля **на уровне отдельных персистентных воркеров-процессов в git-worktree** + встроенный cross-review. Claude Code нативно так не умеет, Devin избегает. Добавление Sol-воркеров = усиление имеющегося дифференциатора, не «догоняем рынок».

---

## Findings — атомарные утверждения с уверенностью

1. **Codex-бэкенд в Orchestra рабочий** (стриминг, MCP, resume, compact, spawn) — **CONFIRMED** (чтение backend_codex.py + session.py + manager.py).
2. **Sol/Terra/Luna отсутствуют в CODEX_CONTEXT_LIMITS/CODEX_TOKEN_PRICES** → Sol-воркер получает 258400 контекст (вместо ~997500 для 1.05M-окна) и $0 цену — **CONFIRMED** (grep + Codex-ревью). **БАГ 1.** *Nuance: 258400=272K×0.95 intentional для 5.4/5.5, но неверно для Sol.*
3. **reasoning_effort захардкожен "high"; xhigh/max/ultra не в наборе CODEX_REASONING_EFFORTS** → Sol нельзя на рекомендованный coding-эффорт — **CONFIRMED** (чтение + Codex расширил). **БАГ 2.**
4. **MCP для codex не прокидывается per-worker** (backend передаёт только env, не mcp_servers) → полагается на глобальный config.toml; решаемо через `-c` — **LIKELY** (код + Codex). **Gap.**
5. **`--dangerously-bypass-approvals-and-sandbox` захардкожен на каждый turn** — security-блокер для Sol (reward-hacking + no sandbox) — **CONFIRMED** (Codex + `:64,68`). **БАГ 3.**
6. **Sol выигрывает terminal/agent-harness кодинг, Opus — real-repo баги и MCP-оркестрацию** — **LIKELY** (multi-source, но часть Sol-скоров неофициальна, harness-mismatch).
7. **Sol имеет рекордный reward-hacking (METR)** — критично для автономного воркера — **CONFIRMED** (T1 METR + множество источников).
8. **Sol НЕ покрывается Anthropic Max; нужна отдельная ChatGPT-подписка** со своими лимитами и shared credit pool — **CONFIRMED** (T1 subscription docs).
9. **Sol как full-cycle — feasible, но НЕ drop-in** (нужны: починка 3-4 багов + подписка + guardrails) — **LIKELY** (синтез).
10. **Гибрид (Opus-оркестратор/research + Sol-implement + Sonnet-простое + codex_review) — разумная стратегия, "оптимальность" не доказана без пилота** — **LIKELY** (синтез + Aider/конкуренты; Codex: доказать пилотом).
11. **Разгрузка Claude-лимитов реальна только для implement-воркеров и только при наличии ChatGPT-подписки** (перенос нагрузки, не бесплатная ёмкость) — **CONFIRMED** (subscription docs).
12. **cost-accumulation defect между turn-ами codex** — заявлен Codex-ом, мной не верифицирован — **UNCERTAIN** (проверить в Phase 2). **БАГ 4?**

---

## Counter-evidence / что против

- **Против «Sol лучше для кодинга»:** Sol проигрывает Opus на SWE-bench Pro (real-repo), у Sol нет публичного SWE-bench Verified и MCP Atlas — прозрачность хуже. Terminal-Bench harness-mismatch (Sol=Codex CLI, Opus=Terminus-2) обесценивает прямое сравнение.
- **Против «разгрузит лимиты»:** Sol жрёт из shared ChatGPT credit pool (Codex CLI + web конкурируют), недельные капы остались. Это перенос на вторую платную подписку, не бесплатно.
- **Против гибрида:** два провайдера ломают принцип Agent Determinism и усложняют отладку; экосистема (skills/CLAUDE.md/plugins) — только Claude, Sol остаётся «второсортным» по интеграции.
- **Против «Opus предсказуемее»:** Opus 4.8 имеет свои проблемы (over-verbosity, over-narration, спрашивает разрешения чаще 4.7 — из claude-api skill). Но это prompt-tunable, не reward-hacking.
- **Conflicts в числах** (детально в benchmarks doc): context 1.05M vs 1M (округление), output $30 vs $25 (Sol дороже — не путать), split crown по бенчмаркам.

---

## Codex second-opinion (adversarial review, 2026-07-16)

Прогнал `codex_review(mode=exec)` на research.md с заданием **фальсифицировать** load-bearing claims (не rubber-stamp). Codex прочитал реальный код + локальный Codex CLI 0.144.3 + официальные OpenAI-доки + METR-отчёт. Итог debate:

| Claim | Вердикт Codex | Что сделал |
|---|---|---|
| БАГ 1 (context+price) | **Частично REFUTED**: 258400 = 272000×0.95 (intentional для 5.4/5.5, не рандом); цена $0 подтверждена | Верифицировал (`272000*0.95==258400` ✓), **исправил формулировку** в research.md: для Sol context всё равно неверен (~997500), но механизм иной |
| БАГ 2 (reasoning effort) | **CONFIRMED + расширил**: блокируются `xhigh`, `max`, `ultra` | Добавил в research.md |
| MCP-not-per-worker | **Реален, но не строго global-only**: CLI поддерживает project-config + `-c` | Уточнил (фикс проще) |
| Гибридная стратегия | **Разумна как пилот, но "оптимальность" не доказана** | Согласен — пометил H2 как LIKELY, не CONFIRMED; пилот обязателен |
| Пропущено мной | **БАГ 3** (`--dangerously-bypass` на каждый turn = security-блокер для Sol) + **БАГ 4** (cost-accumulation defect) | Добавил оба (БАГ 3 verified, БАГ 4 — UNCERTAIN до проверки) |

**Ключевой урок:** мой самый уверенный claim (БАГ 1) оказался наполовину неточным — 258400 не рандом, а `272K×0.95`. Adversarial review сработал как задумано: поймал имплицитное допущение ("любой fallback = баг"), которое я не проверил. Дал 2 новых находки (security + cost) поверх моих. Consensus достигнут за 1 раунд, эскалация не нужна.

## Affected files (для Phase 2, если апрувнут)

- `app/backend_codex.py` —
  - **БАГ 1:** добавить `gpt-5.6-sol/terra/luna` в `CODEX_CONTEXT_LIMITS` (окно 1.05M → usable ~997500 если держать 95%-конвенцию) и `CODEX_TOKEN_PRICES` (sol $5/$30, terra $2.50/$15, luna $1/$6). Учесть Sol long-context surcharge >272K ($10/$45).
  - **БАГ 2:** привести `CODEX_REASONING_EFFORTS` в соответствие с CLI 0.144.3 (добавить `xhigh`, `max`, `ultra` — проверить точный набор через `codex --help`).
  - **БАГ 3 (security):** заменить безусловный `--dangerously-bypass-approvals-and-sandbox` (`:64,68`) на `-s workspace-write` + approval-policy (минимум для Sol). Отдельный тикет.
  - **БАГ 4:** проверить cost-accumulation между turn-ами (session_cost.py + codex-путь) — верифицировать до фикса.
  - MCP: пробросить per-worker MCP через `-c` (тот же механизм, что `developer_instructions`), не полагаться на глобальный config.toml. Critical для VPS.
- `app/session.py:_codex_reasoning_effort()` — сделать configurable (сейчас хардкод "high"); для Sol-coding → "xhigh".
- `tests/test_backend_codex.py` (новый) — end-to-end + регресс на цену/контекст Sol (что пропустило БАГ 1), тест что effort xhigh проходит.
- Промпты full-cycle — если Sol-воркер: reward-hacking guardrails (evidence-based done-conditions, «не трогай tests/», «покажи вывод команды»).

## Risks / edge cases для кода

- Codex CLI 0.144.0+ обязателен для GPT-5.6 (старые прячут модели) — проверить на VPS.
- non-interactive MCP + approval (Issue #24135) — текущий код юзает `--dangerously-bypass`, что обходит проблему но снимает sandbox. Для Sol + reward-hacking рискованно.
- Прокси-противоречие (backend стрипает, wrapper ставит) — хрупко при смене PATH.
- Sol long-context surcharge >272K — cost tracking должен учитывать (сейчас даже базовой цены нет — БАГ 1).

---

## Рекомендация (для решения юзера)

1. **Не переводить full-cycle на Sol целиком (H1 — нет).** Reward-hacking + отдельная подписка + MCP-не-per-worker + 2 бага = слишком много рисков для автономной research→plan→implement роли, где MCP-оркестрация и предсказуемость критичны (а тут Opus объективно сильнее).
2. **Гибрид (H2 — да, поэтапно):**
   - **Сейчас, low-risk:** codex_review (Sol как ревьюер) — уже работает, оставить/усилить. Это лучшее применение Sol.
   - **Шаг 1 (если хочется Sol-воркеров):** починить БАГ 1 (цена/контекст) + БАГ 2 (xhigh) + MCP per-worker. Без этого Sol-воркер сломан (258K контекст, $0 cost, возможно без Orchestra-tools).
   - **Шаг 2:** пилот — Sol на 1-2 чистых implement-задачах из готового spec, с guardrails против reward-hacking, замерить реально (лимиты, качество, reward-hacking-инциденты). Все источники: пилот на реальном кодбейзе обязателен, бенчмарки быстро устаревают (6-нед релиз-цикл).
   - **Шаг 3:** если пилот ок — Sol как опция для terminal/implement-воркеров, оркестратор роутит по типу задачи.
3. **Оркестраторы и research/plan — оставить Opus.** Не трогать.

**Итог:** интеграция уже есть и работает на 80%, но с 2 подтверждёнными багами и архитектурным пробелом (MCP per-worker). Sol — не замена Opus, а **специализированный инструмент** (terminal-coding + cross-review) с guardrails. Гибрид усиливает существующий дифференциатор Orchestra, но требует починки кода и отдельной ChatGPT-подписки перед тем как Sol-воркеры станут production-ready.

---

## Sources

Код (прочитан этой сессией): `app/backend_codex.py`, `app/backend_protocol.py`, `app/models.py`, `app/session.py`, `app/mcp_stdio.py`, `app/manager.py` (через subagent-аудит), `app/backend_opencode.py` (аудит), `app/workspace.py` (аудит), `~/.codex/config.toml`, `~/.local/bin/codex` (wrapper), `tests/` (grep).

Внешние (детальные списки с tier — в `benchmarks-sol-vs-opus.md` и `competitors-multimodel.md`): Artificial Analysis, CodingFleet head-to-head, METR reward-hacking eval, platform.claude.com (Opus 4.8), OpenRouter/Requesty (Sol spec), Codex CLI guides (blakecrosley, danielvaughan), Aider docs, OpenHands docs, Claude Code advisor/subagents.

Prior art в репо (не переделывал): `docs/codex-subscription-usage-research-2026-07.md` (лимиты подписок, 13 июля), `docs/codex-field-guide.md` (миграция Claude Code→Codex), `docs/tasks/codex-audit/` (аудит codex_review usage), `9a9c920 #grok-research` (вердикт по Grok — не добавлять).

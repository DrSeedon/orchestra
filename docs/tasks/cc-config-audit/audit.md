# Аудит конфигурации Claude Code в Orchestra

**Дата:** 2026-07-11
**Автор:** research-cc-config (full-cycle, Phase 1)
**Область:** SDK-параметры воркеров, глобальный/проектный конфиг Claude Code, skills, memory, hooks, MCP
**Метод:** чтение реальных файлов + primary-source docs (platform.claude.com) + инспекция установленного SDK 0.2.87

---

## TL;DR — что важно

1. **Orchestra НЕ передаёт воркерам `effort`** → все агенты (оркестраторы, воркеры, full-cycle) молотят на API-дефолте `high`. Это единственная реальная «дырка» с измеримым эффектом на стоимость/скорость. SDK 0.2.87 **поддерживает** `effort`, код его не использует.
2. **`budget_tokens` / manual `thinking` — МЁРТВАЯ рекомендация.** На Opus 4.7/4.8 и Sonnet 5 (наши модели) `thinking:{type:"enabled",budget_tokens:N}` возвращает **HTTP 400**. Забудьте про budget_tokens — управление глубиной размышления теперь ТОЛЬКО через `effort` + adaptive thinking [1][2].
3. **Всё остальное — в порядке или монетизации не стоит.** Skills инъектятся через worktree (не через SDK), memory局部 замусорена но безвредна, hooks минимальны, MCP настроен корректно.

---

## 1. Как Orchestra создаёт SDK-клиента (факт из кода)

Источник: `app/backend_claude.py:135-167` (метод `_make_client`).

```python
options = ClaudeAgentOptions(
    model=self.model, cwd=self.cwd, cli_path=cli,
    permission_mode="default", can_use_tool=_make_auto_approve(...),
    disallowed_tools=_disallowed_tools(...),
    include_partial_messages=True, max_turns=200,
    max_buffer_size=50 * 1024 * 1024,
    env=env, user=agent_uid,
)
# + options.resume ЛИБО options.system_prompt (preset claude_code + append)
# + options.mcp_servers (merge user<scope<instance)
# + options.setting_sources = ["user","project","local"] или ["local"]
```

env, задаваемый воркеру (`backend_claude.py:121-133`):
- `DISABLE_NON_ESSENTIAL_MODEL_CALLS=1` — глушит фоновые Haiku-вызовы (tips/banter). ✅ правильно
- `DISABLE_TELEMETRY=1` ✅
- проксирование `HTTPS_PROXY/HTTP_PROXY/NO_PROXY` ✅
- `CLAUDE_CONFIG_DIR` (если задан профиль)

**Что НЕ передаётся вообще нигде** (grep по `app/`, `pipelines/` — 0 совпадений):
`effort`, `thinking`, `max_thinking_tokens`, `fallback_model`, `betas`, `max_budget_usd`, `output_format`, `task_budget`.

SDK-версия: **claude-agent-sdk 0.2.87** (pyproject требует `>=0.1.72`). Поля `ClaudeAgentOptions` в этой версии включают все перечисленные — то есть они ДОСТУПНЫ, просто не используются.

---

## 2. Главный чеклист

| Фича | Статус сейчас | Нужна? | Рекомендация | Действие |
|---|---|---|---|---|
| **`effort` (low/med/high/xhigh/max)** | ❌ не задаётся → API-дефолт `high` для всех | **ДА** | Задавать per-role. Дешёвые роли → `medium`/`low`, full-cycle → `xhigh` | Добавить `effort` в `ClaudeAgentOptions` + проброс из pipeline.yaml. См. Quick Win #1 |
| **`thinking` / `budget_tokens`** | ❌ не задаётся | **НЕТ** | НЕ трогать. На Opus 4.7+/Sonnet 5 manual budget_tokens = HTTP 400 [1] | Ничего. adaptive thinking включён by default на наших моделях |
| **`fallback_model`** | ❌ не задаётся | 🟡 опц. | Можно добавить для устойчивости к rate-limit (Sonnet как fallback Opus) | LIKELY-полезно, но у нас уже есть retry-backoff 30/60/90s. Низкий приоритет |
| **`max_turns`** | ✅ `200` | ДА | Оставить. 200 — разумный потолок для длинных задач | Не трогать |
| **`permission_mode`** | ✅ `"default"` + `can_use_tool` авто-approve | ДА | Оставить. Авто-approve с блок-листом (AskUserQuestion/Monitor/Agent/run_in_background) — правильный паттерн | Не трогать |
| **`include_partial_messages`** | ✅ `True` | ДА | Оставить — это фундамент real-time streaming (#83) | Не трогать |
| **`max_buffer_size`** | ✅ `50MB` | ДА | Оставить (защита от SDK backpressure #425) | Не трогать |
| **`setting_sources`** | ✅ `["user","project","local"]` управляемо через `inherit_claude_md` | ДА | Оставить. F4 даёт контроль наследования CLAUDE.md | Не трогать |
| **`disallowed_tools`** | ✅ ScheduleWakeup/Cron*/Workflow всем; Task/Agent оркестраторам | ДА | Оставить — детерминизм, Orchestra сама管ит scheduling | Не трогать |
| **`max_budget_usd` / `task_budget`** | ❌ не задаётся | 🟡 опц. | task_budget (beta `task-budgets-2026-03-13`) мог бы ограничивать loop-стоимость | Экспериментальное. НЕ сейчас — beta, нужны замеры |
| **`skills` (options.skills)** | ❌ сознательно None | ОК | Скиллы инъектятся через worktree (`_inject_skills_to_worktree`), не через SDK. Задокументировано в `backend_claude.py:162-166` | Не трогать — это осознанное решение |
| **`alwaysThinkingEnabled`** (settings.json) | `false` | НЕТ | На adaptive-моделях (наши) это legacy-флаг. Effort рулит | Не трогать |
| **`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`** | `"1"` в settings.json | 🟡 | Для твоих личных сессий CC. Orchestra воркерам Agent/Task ЗАБЛОКИРОВАН (используем spawn_worker). Флаг не мешает, но воркерам бесполезен | Оставить для личных сессий |
| **`DISABLE_NON_ESSENTIAL_MODEL_CALLS`** | `1` (в env воркера) | ДА | Оставить — экономит Haiku-вызовы | Не трогать |
| **Prompt caching** | ✅ управляется CLI автоматически (TTL 1h на Max) | ДА | Ничего. Cache timer pill уже мониторит | Не трогать |
| **Streaming** | ✅ `include_partial_messages=True` + `live_broker` | ДА | Не трогать | — |

---

## 3. Effort levels — TRUTH (primary source)

### Что подтверждено (CONFIRMED — primary docs [1][2])

- **5 уровней:** `low`, `medium`, `high`, `xhigh`, `max`. Это поведенческий сигнал (глубина reasoning + агрессивность tool-calls), **не** токен-бюджет.
- **API-дефолт = `high`.** `effort="high"` ≡ не задавать параметр вообще.
- **`xhigh`** доступен на: Fable 5, Opus 4.8, Opus 4.7, Sonnet 5. (**НЕ** на Opus 4.6 и Sonnet 4.6 — там потолок `max`, xhigh нет.)
- **`max`** доступен на всех наших моделях, но «prone to overthinking», diminishing returns.
- **Effort ⊥ model.** Выбираются независимо. Модель = потолок способностей, effort = сколько от потолка тратим на ход.
- **Стоимость:** `max` может жечь **10× токенов** vs `low` на той же задаче [2].

### Рекомендации Anthropic по нашим моделям (CONFIRMED [2])

| Модель (наша роль) | Рекомендация Anthropic |
|---|---|
| **Opus 4.8** (full-cycle) | «Start with `xhigh` for coding/agentic», `high` для прочего, вниз до `medium/low` только после замеров |
| **Opus 4.6** (orchestrator/sub-orch) | xhigh **НЕДОСТУПЕН**. Дефолт `high`. Для оркестрации (короткие ответы, делегирование) → `medium` разумно |
| **Sonnet 5** (worker) | Дефолт `high`. `medium` = «cost-saving step-down, ≈ Sonnet 4.6 на high». Для воркеров-исполнителей `medium` — хороший баланс |
| **Fable 5** | Start `high`, `xhigh` для capability-sensitive |

### Как это ложится на Orchestra (вывод)

Роли из `pipeline.yaml`:
- `orchestrator` / `sub-orchestrator` = **opus4.6**, задача = делегирование, короткие решения → **`medium`** (снижает latency/стоимость, xhigh им недоступен)
- `worker` = **sonnet** (sonnet5), исполнение по споке → **`medium`**
- `full-cycle` = **opus4.8**, research + сложный код → **`xhigh`** (прямая рекомендация Anthropic для agentic/coding)

⚠️ **Осторожно (UNCERTAIN):** я НЕ измерял фактическую экономию на наших задачах. Anthropic даёт «10× между low и max», но между `high`→`medium` дельта скромнее. Перед раскаткой на все роли — прогнать 3-5 типовых задач с замером turn-cost. Это Phase-1-предупреждение, не блокер.

---

## 4. `budget_tokens` — почему рекомендация из ТЗ УСТАРЕЛА

ТЗ спрашивало «`budget_tokens`? `effort`?». Ответ однозначный (CONFIRMED, primary [1]):

- **Opus 4.8:** `thinking:{type:"enabled",budget_tokens:N}` → **HTTP 400**. Только adaptive (`thinking:{type:"adaptive"}`), глубина — через effort.
- **Opus 4.7:** то же — manual budget_tokens не поддерживается.
- **Sonnet 5:** то же — 400 на manual thinking. adaptive on by default.
- **Opus 4.6:** budget_tokens ещё принимается, но **deprecated**, удалят в будущем релизе.

**Вывод:** любая рекомендация «поднять budget_tokens» для наших моделей = крашнуть запрос. Не делать. Adaptive thinking уже включён by default на Sonnet 5 / Fable 5 и активируется на Opus 4.8 через effort. Единственный правильный рычаг — `effort`.

---

## 5. Memory аудит (`~/.claude/projects/*/memory/`)

**Факт:** memory лежит per-project, у 20+ проектов. Размеры:

| Проект | memory |
|---|---|
| TradingCryptoBot | 132K |
| COG-second-brain | 96K |
| Parsing | 84K |
| **orchestra** | **36K** |
| kesha-tg-bot | 20K |
| остальные | 4-24K |

**Оценка:** это НЕ мусор — auto-memory Claude Code, читается только в своём проекте (per-project изоляция). Orchestra-memory (36K) индексируется через `MEMORY.md` (видно в контексте). Один файл (`sdk_persistent_client_research.md`) помечен OUTDATED в индексе — кандидат на удаление, но 36K погоды не делают.

**Рекомендация:** чистка memory НЕ приоритет. Если чистить — только `~/.claude/projects/-mnt-data-Projects-Python-orchestra/memory/sdk_persistent_client_research.md` (устарел, persistent client теперь работает). Остальное не трогать — это память других проектов.

---

## 6. Skills аудит (`~/.claude/skills/`)

**Факт:** 30 скиллов. Категории:
- **Активно используются Orchestra-воркерами** (через worktree-инъекцию по pipeline.yaml): `codex-debate`, `self-analysis`, `grill-me`, `html-artifacts`. ✅
- **Личные/ситуативные** (твои сессии, не воркеры): `close`, `quick-skill`, `accounting`, `habr-publish`, `starsector-modding`, `reddit-reader`, `youtube-reader`, `orchestra`.
- **Anthropic bundled-стиль** (документы): `docx`, `pdf`, `pptx`, `xlsx`, `frontend-design`, `mcp-builder`, `skill-creator`, `webapp-testing`, `computer-use`, `unity-mcp-skill`.
- **Потенциально мёртвые/дубли:** `review` (дублирует `code-review` встроенный?), `codex-review` (старый, есть `codex-debate` — новее, 127 строк vs старый), `fact-checker`, `humanizer`, `doc-coauthoring`, `page-cro`, `seo-audit`, `task-observer`.

⚠️ **`task-observer`** — его description требует session-start hook для надёжного срабатывания, а у тебя в hooks только `Stop`. То есть скилл почти никогда не активируется автоматически. Либо повесить хук, либо признать что он спит.

⚠️ **`codex-review` vs `codex-debate`** — дубликат. `codex-debate` новее (переписан 377→127 строк, MCP-only). Старый `codex-review` — кандидат на удаление.

**Рекомендация:** скиллы не жгут ни токены (грузятся по триггеру), ни контекст воркеров (инъектятся только нужные по pipeline.yaml). Чистка = гигиена, не оптимизация. Реальный кандидат на удаление — `codex-review` (дубль `codex-debate`).

---

## 7. Прочее (быстро)

- **Hooks:** только `Stop` → `notify-stop.sh` (звук + notify-send). Безобидно, личный QoL. ✅
- **statusLine:** `claude-pulse` (кастомный Python статусбар). Работает, не трогать.
- **enabledPlugins:** `pyright-lsp`, `up@ultrapack`. Личные. Воркеров не касаются.
- **CLAUDE.md размеры:** global 192 строки, project orchestra **480 строк**. Проектный раздут session-notes (7 сессий подряд). НЕ баг, но каждый воркер его наследует (`copies: [CLAUDE.md]` в worktree). 480 строк × N воркеров = контекст-налог. Кандидат на архивацию старых session-notes в отдельный файл.
- **MCP серверы (global settings.json):** `aperant`, `kwin`, `orchestra` (`alwaysLoad:true`). Orchestra-MCP правильно настроен. ✅
- **`.claude.json`:** `autoUpdates:false` (native install, protected). Миграции (sonnet45/opus45/thinking) завершены. Чисто.
- **project `.claude/settings.local.json`:** `enableAllProjectMcpServers:true` + `enabledMcpjsonServers:[orchestra]`. Корректно.

---

## Quick Wins (можно сделать сейчас)

### #1 — Задать `effort` per-role (ЕДИНСТВЕННЫЙ реальный выигрыш)

**Проблема:** все агенты на дефолтном `high`. Оркестраторы (короткие решения) и воркеры (исполнение) переплачивают токенами/latency.

**Wiring подтверждён (CONFIRMED):** `options.effort` реально доходит до CLI. SDK-исходник `_internal/transport/subprocess_cli.py:392-393`:
```python
if self._options.effort is not None:
    cmd.extend(["--effort", self._options.effort])
```
Т.е. `ClaudeAgentOptions(effort="xhigh")` → подпроцесс `claude ... --effort xhigh`. Не output_config, а CLI-флаг. Quick Win не «в теории» — проброс существует в установленном 0.2.87.

**Правка 1 —** `app/backend_claude.py`, добавить параметр `effort` в `__init__` и в `ClaudeAgentOptions`:
```python
# в __init__: effort: str | None = None
# в options (backend_claude.py:135):
options = ClaudeAgentOptions(
    ...,
    effort=self.effort,   # None → API-дефолт high
)
```

**Правка 2 —** `pipelines/default/pipeline.yaml`, добавить `effort` в роли:
```yaml
orchestrator:     { model: opus4.6, effort: medium, ... }
sub-orchestrator: { model: opus4.6, effort: medium, ... }
worker:           { model: sonnet,  effort: medium, ... }
full-cycle:       { model: opus4.8, effort: xhigh,  ... }
```

**Правка 3 —** проброс через `pipeline.py` (резолв роли) → `manager.create_session` → `ClaudeBackend(...)`. Так же как сейчас пробрасывается `model`.

⚠️ **ПЕРЕД раскаткой:** прогнать 3-5 типовых задач на каждой роли, замерить turn-cost `medium` vs `high`. Не раскатывать вслепую — экономия между high→medium скромнее, чем маркетинговые «10×» (те про low↔max).

### #2 — Удалить дубль-скилл `codex-review`
`codex-debate` его полностью заменяет (MCP-only, новее). `trash ~/.claude/skills/codex-review`.

### #3 — Удалить устаревший memory-файл
`~/.claude/projects/-mnt-data-Projects-Python-orchestra/memory/sdk_persistent_client_research.md` (помечен OUTDATED в MEMORY.md).

---

## Не трогать (работает — руки прочь)

- `max_turns=200`, `permission_mode="default"` + auto-approve, `include_partial_messages`, `max_buffer_size=50MB` — фундамент, стабильно.
- `disallowed_tools` (Task/Agent/Cron/Workflow) — детерминизм, осознанное решение.
- `options.skills=None` + worktree-инъекция скиллов — задокументированный паттерн.
- **`thinking`/`budget_tokens`** — НЕ добавлять. На наших моделях = HTTP 400.
- `DISABLE_NON_ESSENTIAL_MODEL_CALLS`, `DISABLE_TELEMETRY` — экономят, оставить.
- Memory других проектов, personal hooks, statusLine, plugins.

---

## Confidence по находкам

| Находка | Confidence | Основание |
|---|---|---|
| Orchestra не передаёт effort/thinking/fallback | **CONFIRMED** | grep по коду = 0 совпадений + чтение backend_claude.py |
| SDK 0.2.87 поддерживает effort/thinking/fallback | **CONFIRMED** | инспекция `dataclasses.fields(ClaudeAgentOptions)` установленного пакета |
| `options.effort` доходит до CLI как `--effort` | **CONFIRMED** | SDK-исходник `subprocess_cli.py:392-393` — прямой `cmd.extend(["--effort", ...])` |
| budget_tokens → 400 на Opus 4.7+/Sonnet 5 | **CONFIRMED** | primary docs platform.claude.com/effort [1] |
| API-дефолт effort = high, xhigh не на 4.6 | **CONFIRMED** | primary docs [1][2] |
| effort=medium сэкономит на наших задачах | **UNCERTAIN** | не измерено на наших workflow; docs дают общее направление, не наши числа |
| fallback_model полезен | **LIKELY** | docs упоминают, но у нас уже есть retry-backoff; не проверял поведение на Max-подписке |
| codex-review дублирует codex-debate | **LIKELY** | CLAUDE.md session-notes: codex-debate переписан MCP-only 377→127 строк |

---

## Counter-evidence / оговорки

- **fallback_model на Max-подписке:** web-поиск не дал чёткого подтверждения что SDK-параметр `fallback_model` авто-переключает модель на rate-limit именно на подписке (не API-key). Источники путаются в billing-контексте (июнь-2026 credit-pool change был отменён, потом спорно). НЕ рекомендую внедрять без проверки — у нас и так есть retry-backoff.
- **task_budget (beta):** есть, но beta-хедер `task-budgets-2026-03-13`, включает thinking в счётчик. Потенциально полезно для лимита loop-стоимости, но экспериментальное — не для прода без замеров.
- **Экономия от effort:** маркетинговые «10×» — это low↔max. Реальная дельта high→medium на agentic-задачах меньше и зависит от задачи. Не обещать экономию до замеров.

---

## Sources

[1] Effort — Claude Platform Docs. https://platform.claude.com/docs/en/build-with-claude/effort (fetched 2026-07-11)
[2] Adaptive thinking + effort levels — сводка из platform.claude.com/docs (build-with-claude/adaptive-thinking, /effort), WebSearch 2026-07-11
[3] Установленный `claude-agent-sdk` 0.2.87 — инспекция `ClaudeAgentOptions` полей и `ThinkingConfig`/`EffortLevel` типов (`Literal['low','medium','high','xhigh','max']`)
[4] Реальные файлы: `app/backend_claude.py`, `app/models.py`, `pipelines/default/pipeline.yaml`, `~/.claude/settings.json`, `~/.claude/.claude.json`

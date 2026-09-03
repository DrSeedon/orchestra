# #172 — аудит активных prompt surfaces Orchestra под GPT-5.6 Sol

**Фаза:** 1, research-only. Активные промпты и код не менялись. Срез кода и официальных
документов снят 2026-08-10.

## Короткий ответ

Гигантская перепись не обоснована. Официальная рекомендация для GPT-5.6 — начинать с уже
рабочего prompt/tool set, удалять по одной группе и повторять те же evals [1]. Наши точные
дословные дубли внутри одного role prompt малы: скрипт нашёл только заголовок background jobs
(61 B) и строку про commit (68 B). Но аудит обнаружил три более сильных точечных дефекта:

1. **Обычный reload воркера при неизменном template-prefix дублирует весь `<worker-memory>`.**
   На текущем `prompt-engineer` это
   `84 652 → 129 655 B`, то есть **+45 003 B** и два memory-блока после reload; последующий
   `refresh_worker_memory()` оставляет оба.
2. **В активном `CLAUDE.md` три Sol/Codex-факта протухли:** конфиг назван 64 KiB при фактических
   131 072 B; сказано, что Sol не видит project skills и получает сгенерированный index, хотя
   текущий путь — native `.codex/skills` с выключенным index fallback; сказано «precompact только
   Claude», хотя Codex имеет native precompact с порогом 60%.
3. **`codex_review` всегда предпосылает чужой масштаб `small team, MVP stage`.** Это прямо
   противоречит активному skill, который требует брать PROJECT CONTEXT из текущего проекта и
   предупреждает, что чужой scale занижает severity.

Управляемый нижний предел статического контекста одного свежего Sol-run — **118 462–139 043 B**
в зависимости от роли: role prompt + global/project `AGENTS.md` + 34 включённые Orchestra
tool schemas. Это байты сериализованных источников, **не токены**: точного офлайн-токенайзера
GPT-5.6 в окружении нет, поэтому пересчёта «4 символа = токен» здесь нет. Для текущего
full-cycle с личной памятью нижний предел — **179 551 B fresh** и **224 554 B после одного
reload**. Skill bodies, built-in Codex tools, user task, custom overlay и динамический список
воркеров в эти суммы не входят. Полный MCP transport для тех же 34 tools, включая
`outputSchema`, равен 23 651 B; prompt-tax таблица использует более консервативный
model-facing core `name + description + inputSchema` = 18 886 B, потому что включение
`outputSchema` в model context текущего host не доказано.

## 1. Вопрос и гипотезы

### 1.1 Структурированный вопрос

- **Контекст:** все активные слои, которые Orchestra передаёт orchestrator, worker и
  full-cycle при backend `gpt-5.6-sol`, включая native Codex guidance, skills, MCP schemas,
  review/compact/handoff paths.
- **Изменение под проверкой:** точечное удаление повторов, исправление протухших/конфликтных
  инструкций и role-specific tool exposure.
- **Baseline:** текущая сборка без правок.
- **Исход:** качество/полнота доказательств и соблюдение границ не хуже baseline; меньше input
  tokens, latency, tool calls, повторных/no-progress loops и turns. Размеры слоёв — диагностика,
  не самостоятельный verdict.

### 1.2 Гипотезы и фальсификаторы

| Гипотеза | Что доказало бы её неверной | Итог Phase 1 |
|---|---|---|
| H1. В активных слоях есть крупный повтор/конфликт, который можно убрать хирургически | Дословный и структурный аудит не находит крупного same-run повтора; инструкции согласованы с текущим кодом | **Подтверждена частично:** общий exact-line duplication мал, но reload даёт +45 003 B memory; найдены точечные фактические конфликты |
| H2. Длина сама по себе не главный локальный рычаг; число tool calls/loops важнее | Контролируемый prompt-only A/B даёт устойчивый выигрыш за пределами шума при неизменных calls | **Остаётся вероятной:** прошлый Sol-замер показывает доминирование calls, но A/B #172 не проводился [4] |
| H3. Текущая специфичность защитна; массовое сокращение ухудшит evidence/safety | Lean-arm сохраняет качество и границы, одновременно снижая tokens/calls/latency | **Не опровергнута:** локального A/B нет; правила с измеренными failure modes нельзя снимать по одному размеру |

## 2. Метод и границы

1. До кода выполнены `pwd`, `search_memory`; прочитаны `docs/tasks/127/`, затем релевантные
   `context-engineering`, `sol-efficiency`, `fullcycle-audit`, `118`, `137`. Opus-выводы #127
   не переносились на Sol: использованы только как история уже сделанных изменений и локальные
   измерения.
2. Официальный Codex manual собран helper-скриптом из `openai-docs` skill в
   `/tmp/openai-docs-cache/codex-manual.md`; затем открыта live model guidance [1]. OpenAI Docs
   MCP в доступном tool registry отсутствовал, поэтому после manual helper использован
   разрешённый fallback только на `developers.openai.com`.
3. Prompt claims ниже берутся **только** из `Prompting best practices` live GPT-5.6 guidance
   [1]. Codex manual [2][3] используется только для runtime behavior: AGENTS/skills/app-server.
4. Код прослежен от manifest до backend transport. Размеры и tool schemas воспроизводятся:
   `PYTHONPATH=. /home/kesha/orchestra/.venv/bin/python docs/tasks/172/measure_prompts.py`.
5. Живая DB, prod, auth/token stores и API-key маршруты не читались; сервис не рестартовался.
   Поэтому нет утверждений о частоте найденных путей в текущем проде.
6. External Codex verdict недоступен: единственный разрешённый `codex_review` завершился до
   старта job ошибкой `weekly_quota_upgrade_required: New Codex worker turn blocked: the FastAPI
   readiness server does not provide worker-weekly-v1.` Повтор/обход не делался; строгая Sol
   self-review — `docs/tasks/172/self-review.md`.

## 3. Официальные best practices именно GPT-5.6

Ниже — атомарный пересказ только секции `Prompting best practices` [1]:

1. **Lean prompt — проверяемая гипотеза, не лицензия на rewrite.** OpenAI сообщает направление
   внутренних coding-agent evals: примерно +10–15% score, −41–66% total tokens и −33–67% cost
   у более lean конфигураций; сама страница требует считать эти диапазоны directional и проверять
   на своих representative tasks.
2. **Менять по одной группе.** Начать с работающего prompt/tool set, удалить одну группу
   instructions/examples/tools, повторить те же evals. Каждую инструкцию формулировать один раз.
3. **Показывать только релевантные tools.** Tool descriptions должны быть concise/precise;
   для программного вызова — заранее описывать return fields, types и error behavior.
4. **Примеры и style guidance оставлять, если они кодируют product requirement или закрывают
   измеренный gap.** Следить за context в начале и по мере роста длинной сессии: повторные prompt
   и tool layers усиливаются.
5. **Одна компактная autonomy/approval policy.** Явно назвать разрешённые safe local actions и
   остановки перед external/destructive/costly/scope-expanding actions. Повторение `ask first`,
   `do not mutate`, `wait for approval` может вызывать лишние паузы на безопасной работе.
6. **Не добавлять общую краткость автоматически.** GPT-5.6 по умолчанию короче GPT-5.5;
   broad `be concise` иногда делает ответ слишком кратким. Лучше задать обязательное содержание,
   что можно опустить, и `text.verbosity`, если surface его поддерживает.
7. **Outcome-focused prompt.** Для сложной задачи достаточно goal, relevant context, constraints,
   required evidence, success criteria и output format; `think harder` и генерация нескольких
   кандидатов не нужны сами по себе.
8. **Tool routing должен быть детерминирован формой задачи.** Programmatic Tool Calling годится
   для bounded filtering/joining/ranking/dedup/aggregation; direct calls — когда нужен один вызов,
   semantic judgment, approval, native artifact или каждый результат меняет решение. Оценивать
   final answer и program output, затем tokens/latency/cost/calls/turns/retries.

Термин **Sol публично подтверждён**, bounded uncertainty здесь не нужна: та же live страница
говорит, что alias `gpt-5.6` маршрутизируется на `gpt-5.6-sol`, flagship member семейства [1].

## 4. Полный путь сборки Sol prompt

```text
pipelines/default/pipeline.yaml
  → app/pipeline.py:369 resolve_role()
  → app/pipeline.py:427 build_system_prompt()
      base.md + roles/<role>.md + manifest modules
  → app/manager.py:300 ROLE_SYSTEM_PROMPT()
      + orchestrator role catalog + available models + live peer/worker blocks
  → app/manager.py:605-615 create_session()
      + optional custom system_prompt + ownership + personal <worker-memory>
  → app/session.py:685 _make_backend()
      + project-doc truncation warning, only when preflight proves overflow
  → app/runtime_registry.py:192 _codex_factory()
      + optional generated skill index (OFF by default)
  → app/backend_codex.py:396-413 connect()
      thread/start or thread/resume with developerInstructions
  → Codex native layers
      global AGENTS → project AGENTS chain → native skill metadata/body on trigger
      + 34 enabled Orchestra MCP tool schemas
  → turn user input
      optional runtime handoff / refreshed-prompt wrapper / pending facts
```

Ключевые детали:

- `AGENTS.md` в worktree — byte-identical untracked mirror `CLAUDE.md`; `sync_agents_md()`
  обновляет его перед backend connect и не перезаписывает tracked/symlink path
  (`app/workspace.py:400-430`). В модели это **один** project-doc слой, а не два.
- Codex official manual загружает global guidance, затем project root→CWD и ближний файл имеет
  больший приоритет [2]. Здесь global `~/.codex/AGENTS.md` = 13 867 B, project mirror =
  62 146 B. Текущий `project_doc_max_bytes=131072`; project mirror помещается полностью.
- `app/runtime_registry.py:203-227` по умолчанию не генерирует skill index:
  `ORCHESTRA_CODEX_SKILL_INDEX=false`. `_refresh_skills()` кладёт files в `.codex/skills`
  перед connect (`app/session.py:1025-1037,1119-1128`).
- На resume `app/session.py:913-927` один раз добавляет весь `_current_prompt` в **user message**.
  Одновременно `backend_codex.py:406-413` передаёт `system_prompt` как
  `developerInstructions` в `thread/resume`. Причина cross-runtime понятна, но для Sol это два
  prompt channels; необходимость user-copy отдельно не измерена.
- Runtime switch handoff — user-priority, с явным disclaimer и максимум 32 000 символов
  (`app/session.py:985-995,2055-2092`). Это корректно отделяет историю от instructions.

## 5. Inventory: source → consumer/runtime → размер → назначение

### 5.1 Manifest, roles и modules

`pipeline.yaml` — 3 527 B/84 lines, сам не инлайнится: он определяет composition, model,
skills, modules и spawn capabilities.

| Source | Consumers | Bytes / lines | Назначение |
|---|---|---:|---|
| `pipelines/default/prompts/base.md` | все роли, все runtimes | 7 464 / 86 | platform transport, tools index, safety, comms, model routing |
| `roles/orchestrator.md` | orchestrator | 578 / 9 | минимальная role identity |
| `roles/sub-orchestrator.md` | sub-orchestrator | 929 / 11 | parent/subteam boundary |
| `roles/worker.md` | worker | 4 214 / 77 | worker invariants, code quality, identity, before-work/done |
| `roles/full-cycle.md` | full-cycle | 10 570 / 168 | 3 phases, gates, artifacts, review rules |
| `modules/git-workflow.md` | все роли | 1 995 / 33 | worktree/branch/commit contract |
| `modules/orchestration.md` | orchestrator, sub | 17 215 / 263 | delegation, task handoff, lifecycle, PROJECT CONTEXT |
| `modules/worker-lifecycle.md` | orchestrator, sub, full-cycle | 979 / 18 | stop/kill gate |
| `modules/background-jobs.md` | orchestrator, sub | 1 778 / 23 | server-side long jobs |
| `modules/task-management.md` | orchestrator, sub | 1 848 / 28 | task/payment workflow |
| `modules/report-format.md` | worker, full-cycle | 1 112 / 28 | DONE/WIP/gate report contracts |
| `modules/research-method.md` | full-cycle | 8 770 / 134 | evidence method and experiment design |
| `modules/self-improvement.md` | все роли | 6 496 / 98 | shared-rule triage and personal memory |
| `modules/memory-search.md` | все роли | 2 276 / 40 | mandatory semantic-memory gate |

Уникальный corpus этих 14 source files — **66 224 B**. В один run входит только role-specific
subset; сборка измерена ниже.

### 5.2 Role assemblies до dynamic overlays

| Role | Собранный static system prompt | Lines | Layers |
|---|---:|---:|---:|
| orchestrator | 40 638 B | 608 | base + role + 7 modules |
| sub-orchestrator | 40 989 B | 609 | base + role + те же 7 modules |
| worker | 23 563 B | 369 | base + role + 4 modules |
| full-cycle | 39 670 B | 614 | base + role + 6 modules |

У orchestrator дополнительно детерминированно добавляются role catalog + available models:
3 093 B; у sub-orchestrator — 3 155 B. Live peer/worker list, ownership, custom overlay и
memory имеют переменный размер.

### 5.3 Project/global guidance и Codex skills

| Source | Consumer | Размер | Статичность |
|---|---|---:|---|
| `CLAUDE.md` → generated `AGENTS.md` mirror | все Codex роли этого repo | 62 146 B / 268 lines | auto-loaded project guidance |
| `~/.codex/AGENTS.md` | все Codex runs пользователя | 13 867 B / 110 lines | global guidance, repo не владеет |
| `docs/workers/prompt-engineer.md` | только этот persistent worker | 44 969 B / 392 lines | всегда инлайнится в developerInstructions |
| `.codex/skills/codex-debate/SKILL.md` | worker/full-cycle; orchestrator по manifest | 12 376 B / 140 lines | generated copy; full body только при trigger |
| `.codex/skills/html-artifacts/SKILL.md` | worker/full-cycle/orchestrator | 12 263 B / 158 lines | generated copy; full body только при trigger |

Canonical skill sources и manifest consumers:

| Source | Roles | Bytes / lines |
|---|---|---:|
| `skills/codex-debate.md` | orchestrator, worker, full-cycle | 12 376 / 140 |
| `skills/html-artifacts.md` | orchestrator, worker, full-cycle | 12 263 / 158 |
| `skills/grill-me.md` | orchestrator | 7 300 / 118 |
| `skills/orchestra-agents.md` | orchestrator, sub | 12 692 / 167 |
| `skills/vps-deploy.md` | orchestrator | 2 127 / 58 |

Итого canonical skill bodies 46 758 B, но это **не per-run body tax**. Official manual говорит
о progressive disclosure: стартуют name+description+path, полный `SKILL.md` читается при выборе
[3]. Точный размер native metadata serialization из repo не наблюдаем.

Есть bounded discrepancy по адресу: current official manual 2026-08-10 документирует repo skills
в `.agents/skills` [3], а текущий `codex-cli 0.146.0`, эта живая сессия и код Orchestra
фактически обнаруживают `.codex/skills` (`runtime_registry.py:203`; skill был реально доступен).
Не мигрировать путь по одной документации: сначала отдельный clean-repo probe на 0.146.0.

`.claude/roles/**` отсутствует. Tracked `AGENTS.md` отсутствует; текущий `AGENTS.md` generated и
ignored. `.codex/skills/**` и `.claude/skills/**` — generated/ignored copies, не canonical source.

### 5.4 Runtime builders, review/compact/handoff и tools

| Surface | Consumer/runtime | Размер/граница | Назначение |
|---|---|---:|---|
| `app/manager.py:300-329 ROLE_SYSTEM_PROMPT` | все | variable | static role + orchestrator catalog/models/peers |
| `app/manager.py:459-467 _ownership_prompt` | workers with `owned_dirs` | variable | hard edit boundary |
| `app/manager.py:605-615` | all sessions | variable | custom overlay + ownership + memory |
| `app/prompting.py:371-379` | Codex only on proven overflow | variable | project-doc truncation recovery instruction |
| `app/runtime_registry.py:192-240` | Codex | normally +0 | optional fallback skill index; default OFF |
| `app/backend_codex.py:396-413` | Sol/Terra/Luna/Codex | assembled size | `developerInstructions` on start/resume |
| `app/backend_claude.py:189-192` | Claude only | external preset + assembled | `claude_code` preset with append; not Sol tax |
| `app/backend_grok.py:979-995` | Grok only | assembled + 118 B header | temporary agent profile; not Sol tax |
| `app/backend_opencode.py:264-274` | OpenCode only | assembled | per-turn `system` field; not Sol tax |
| `app/session.py:913-927` | resumed all runtimes | full current prompt + wrapper | refreshed prompt delivered as user message |
| `app/session.py:985-995,2055-2092` | runtime switch | ≤32 000 chars history + wrapper | provider-neutral user-priority handoff |
| `app/session.py:1670-1698 COMPACT_PROMPT` | Claude only | fixed prompt + summary | custom structured handoff; Codex bypasses it at `:1664-1665` |
| `app/session.py:1590-1644` | Codex | native response | `thread/compact/start`; no custom compact prompt |
| `app/mcp_stdio.py:1976-2105` | separate Sol review | 204 B fixed context + caller context | `codex_review` review prompt |
| `app/bootstrap.py:23-25` | first bootstrapped orchestrator | 75 B | emergency default prompt stored in DB |
| `app/mcp_stdio.py` tool docstrings + schemas | all current Codex roles | 34 tools; 18 886 B prompt core / 23 651 B full MCP transport | Orchestra MCP tool selection/calling contract |

FastMCP registry содержит 36 tools (21 723 B compact serialization), но
`backend_codex.py:247-257,1509-1516` включает Sol только 34: `send_chart` и
`resolve_merge_operation` исключены. Для 34 enabled tools: descriptions 8 905 B, input schemas
7 977 B, raw output schemas 4 237 B; compact transport wrappers дают 23 651 B. Нижняя оценка
prompt tax ниже считает только `name + description + inputSchema` (18 886 B), как прежний
model-facing метод #137; точная host-side передача output schema модели не наблюдалась.
`manager.py:391-406` задаёт всем ролям одинаковый
`ORCHESTRA_ACCESS_MODE=full`; role-specific schema filtering нет.

HTML/Jinja templates в `app/templates/**` — UI, не model prompt; исторические `docs/tasks/**`
не включались в inventory как активные prompts.

## 6. Общий статический prompt tax

Это **контролируемый lower bound в байтах**, не полный request и не token count:

| Role | Role prompt | Fixed manager dynamic | global + project AGENTS | 34 Orchestra tools | Lower bound fresh |
|---|---:|---:|---:|---:|---:|
| orchestrator | 40 638 | 3 093 | 76 013 | 18 886 | **138 630 B** |
| sub-orchestrator | 40 989 | 3 155 | 76 013 | 18 886 | **139 043 B** |
| worker | 23 563 | 0 | 76 013 | 18 886 | **118 462 B** |
| full-cycle | 39 670 | 0 | 76 013 | 18 886 | **134 569 B** |

Для текущего full-cycle после identity formatting:

| Состояние | developerInstructions | + AGENTS + tools | Actual memory blocks |
|---|---:|---:|---:|
| fresh spawn | 84 652 B | **179 551 B** | 1 |
| reload current code path | 129 655 B | **224 554 B** | 2 |
| reload + `refresh_worker_memory()` | 129 655 B | **224 554 B** | 2 |

Не включены: Codex built-in instructions/tools, native skill metadata, triggered skill body,
live workers/peers, custom overlay, ownership, project-doc warning, user message и runtime handoff.
Поэтому это нижняя граница управляемой статики, а не размер полного model input.

## 7. Конфликты, повторы и вредные для Sol инструкции

### F1 — reload с совпавшим template-prefix удваивает personal memory — CONFIRMED, P0

`manager.py:1418-1422` строит `current_prompt` уже с текущей памятью. Затем
`manager.py:1502-1510` считает всё после старого formatted base «custom_part» и дописывает хвост
старого prompt — вместе со старым `<worker-memory>`. `refresh_worker_memory()` заменяет только
первое совпадение (`app/prompting.py:91-96`, `count=1`), второе остаётся.

Условие ветки — `old_prompt.startswith(formatted_base)` (`manager.py:1508`); при изменившемся
base хвост не добавляется и этот конкретный дубль не возникает. Стенд на реальных текущих
role/memory files с совпадающим base: `84 652 → 129 655 B`, 1 → 2 блока, после refresh без
изменения. Это одновременно token tax и precedence bug: старый memory расположен позже свежего
и может противоречить ему. Частота в prod не измерялась.

### F2 — три протухших Codex-факта в project guidance — CONFIRMED, P0

1. `CLAUDE.md:198` говорит «VPS 64 KiB»; фактический
   `/home/kesha/.codex/config.toml:1` — `project_doc_max_bytes = 131072`. Полезное правило
   «проверять config» оставить, snapshot удалить.
2. `CLAUDE.md:208` говорит, что Sol не видит project skills и получает generated index.
   Текущий default ровно обратный: native `.codex/skills`; fallback index выключен
   (`runtime_registry.py:20-24,203-227`).
3. `CLAUDE.md:204` говорит «precompact только Claude». Текущий Codex policy — native mode,
   arm/context threshold 60%, delay 25 min (`session.py:402-404,425-432,542-570`), а manual
   compact вызывает тот же native path (`session.py:1590-1644,1663-1665`).

Дополнительный тот же конфликт: tool description `compact_worker` всё ещё обещает
«summarize, reset session, continue fresh; use >80%; 30–60s» (`mcp_stdio.py:1081-1084`). Для
Sol native compact не обязан reset thread, а auto-policy уже с 60%.

### F3 — review получает чужой PROJECT CONTEXT — CONFIRMED, P0

`app/mcp_stdio.py:1976-1981` безусловно вставляет:

```text
Scale: small team, MVP stage
```

после чего лишь добавляет caller `context` (`:2092-2095`). Активный skill требует context всегда
и на `skills/codex-debate.md:126-132` запрещает подставлять чужой scale: это занижает severity
high-load проектов. Оба текста идут одному Sol review, причём fixed context расположен первым.
Дефект подтверждён source path; magnitude ошибки на review corpus не измерен.

### F4 — model routing имеет второй hardcoded owner — CONFIRMED, P1

`base.md:76-85` объявляет `<model-routing>` единственным decision rule; `spawn_worker` description
также намеренно не повторяет model ids (`mcp_stdio.py:721-732`). Но on-demand
`skills/orchestra-agents.md:56-70` создаёт orchestrator с `claude-opus-5[1m]` и утверждает
«оркестраторы всегда на Opus», а `:75-84` снова hardcode'ит Opus для persistent specialist.
При запуске skill из Sol-контекста это обход текущего manifest default/quota routing. Проблема —
не «Opus плох», а два владельца решения.

### F5 — всем Sol-ролям отдаются одинаковые 34 Orchestra tools — CONFIRMED, P1

Текущий Sol schema tax — 18 886 B для каждой роли. `worker.md:9` одновременно запрещает
orchestrator-only tools, то есть prompt компенсирует лишнюю affordance запретом. Это совпадает с
GPT-5.6 guidance «expose only tools relevant to the task» [1].

Но наивный фильтр `worker/not worker` опасен: прошлый измеренный аудит #137 нашёл, что worker DB
rows реально вызывали `merge_worker`, `spawn_worker`, `kill_worker`; full-cycle имеет
`can_spawn=["*"]` [5]. Фильтр должен исходить из manifest role/capabilities и реального usage,
а не `is_orchestrator`.

### F6 — крупные повторы в основном смысловые, не дословные — LIKELY, P1/P2

Measured block sizes:

| Same-run / maintenance pair | Размеры | Вывод |
|---|---:|---|
| full-cycle Phase 1 `roles/full-cycle.md:19-45` ↔ detailed `research-method.md:8-109` | 1 811 B ↔ 6 707 B | роль повторяет retrieval/cross-check/research.md/report; оставить gate+output в роли, метод — в module |
| base background summary `base.md:28-34` ↔ module | 571 B ↔ 1 778 B | orchestrator/sub получают оба; base нужен workers, module можно сократить до типов/параметров, которых нет в tool schema |
| orchestration task summary `orchestration.md:77-85` ↔ task-management module | 630 B ↔ 1 848 B | один consumer получает обе схемы task ids/status/commit refs |
| base communication `base.md:56-74` ↔ project orchestrator brevity `CLAUDE.md:132-136` | 1 766 B ↔ 1 215 B | не exact duplicate, но два сильных brevity controllers в Sol orchestrator |
| worker ↔ full-cycle code-quality blocks | 1 067 B ↔ 1 120 B | почти exact, но роли взаимоисключающие: maintenance duplicate, не per-run tax |
| full-cycle gate report ↔ report-format | 157 B ↔ 297 B | небольшое same-run повторение |

Exact-line detector не подтверждает тезис «весь prompt — копипаста»: внутри одного role assembly
он нашёл только 61 B duplicate header для orchestrator/sub и 68 B commit rule для worker.
Поэтому смысловые пары — кандидаты на one-group A/B, не автоматическое удаление.

### F7 — broad brevity для Sol не откалибрована — UNCERTAIN, P2

`base.md:59-65` задаёт общую краткость всем, а `CLAUDE.md:133-136` усиливает её для
orchestrator. OpenAI предупреждает, что GPT-5.6 уже короче GPT-5.5 и broad brevity иногда теряет
нужную полноту [1]. Но локального failure corpus «Sol ответил слишком коротко из-за этих строк»
нет. Не удалять: проверить arm с одним owner и явным перечнем сохраняемого содержания.

### F8 — prompt refresh на resume повторяет весь role prompt в user history — UNCERTAIN, P2

`session.py:913-927` инлайнит `_current_prompt` в user message, а Codex backend передаёт
`developerInstructions` и на `thread/resume` (`backend_codex.py:396-413`). Official app-server
manual подтверждает, что resume принимает те же configuration overrides, что start [6], но live
эксперимент, доказывающий применение обновлённых `developerInstructions`, здесь не запускался.

Возможный выигрыш велик — убрать full prompt copy из растущей истории; риск тоже велик — потерять
hot update role/worker list. Сначала same-version app-server probe: старый thread, новый unique
developer sentinel, resume, behavioral check; только потом менять cross-runtime injector.

### F9 — bootstrap orchestrator начинает с 75 B вместо role assembly — CONFIRMED, P1

Когда в fresh workspace нет `/workspace/project/prompts/orchestrator.md`,
`app/bootstrap.py:23-25,114-138` сохраняет короткий `_DEFAULT_SYSTEM_PROMPT` прямо в DB.
`manager.py:1418-1451` на load выбирает `old_prompt or current_prompt`; на первом fresh turn
`session.py:913` не inject'ит `_current_prompt`, потому что native `session_id` ещё отсутствует.
Следовательно, первый turn auto-bootstrap orchestrator получает короткий developer prompt; полный
role prompt появится как user refresh не раньше следующего turn. Это касается only-first-install,
но именно там agent должен создать правильную систему.

## 8. Что оставить

1. **Фазовые gates full-cycle, artifact evidence и Codex debate.** Они ограничивают side effects и
   дают наблюдаемый completion bar. #127 уже удалил Opus-specific unconditional self-review; не
   возвращать его и не переносить тот вывод на Sol [7].
2. **Memory-search trigger, current-code check, measurement noise/pilot rules.** Они основаны на
   локальных failure modes, а OpenAI отдельно велит сохранять guidance, закрывающую measured gap
   [1].
3. **Lifecycle/merge/destructive-action boundaries.** Это safety/authorization, не stylistic
   verbosity. Свести owner можно, ослаблять семантику нельзя.
4. **Короткий tool discovery index в base.** #137 показал, что тяжёлая schema без prompt mention
   не гарантирует discovery; сначала role-filter tools, затем A/B index [5].
5. **Native progressive skills и AGENTS mirror guards.** Body не платится до trigger; tracked и
   symlink guards защищают чужие repo files.
6. **Runtime-handoff disclaimer.** История остаётся user-priority и явно не выдаётся за system
   instruction.
7. **Measured anti-loop правила:** no sleep/poll, bounded outputs, one log read. Sol corpus показал
   0 sleeps в 356 post-fix calls против 88 до фикса; это реальный behavioral effect [4].
8. **Dynamic model routing как один owner.** Удалить hardcoded copies, но оставить решение по
   task class/quota runway.

## 9. Приоритетные точечные правки

| Приоритет | Surgical edit | Ожидаемый эффект | Главный риск / gate |
|---|---|---|---|
| P0 | В `_load_from_db` отделять custom overlay/ownership от memory; собирать ровно один свежий memory block | −45 003 B на этом worker после reload; убрать stale-last precedence | shared runtime; tests с old/new memory + custom overlay + ownership, затем Codex review |
| P0 | Удалить fixed `small team, MVP` из `_REVIEW_CONTEXT`; для exec review fail loud без текущего PROJECT CONTEXT либо использовать нейтральный no-scale default | корректная severity calibration | пустой context может сломать legacy callers; grep всех call sites + review corpus |
| P0 | Исправить `CLAUDE.md:198,204,208` и `compact_worker` description по current behavior; убрать машинный snapshot там, где можно назвать проверяемый route | Sol перестаёт следовать несуществующему generated index и отказываться от native compact | future CLI drift; формулировать capability check, не новую вечную версию |
| P1 | В `orchestra-agents` убрать model id/«always Opus», ссылаться на manifest/model-routing | один owner routing, нет случайного Opus override из Sol | bootstrap вне manifest должен fail loud/получить явный model |
| P1 | Bootstrap создавать с полным role prompt либо пустым overlay через тот же assembler | правильный первый turn | import cycle/startup ordering; isolated bootstrap test |
| P1 | Формировать `enabled_tools` из manifest role/capabilities и measured workflow | до 18 886 B доступно для сокращения; меньше неверных affordances | нельзя отрезать full-cycle spawn/merge/coordination; сначала current usage inventory и role contract |
| P1 | По одному свернуть Phase 1↔research-method, task summary↔task-management, background summary↔module | ориентир 2–4 KB без снятия safety | semantic loss; каждый блок — отдельный A/B arm |
| P2 | Проверить и при успехе перенести refreshed Codex prompt с user-copy в resume developerInstructions | убрать целую повторную копию role prompt из history | hot update может не примениться; direct 0.146.0 probe обязателен |
| P2 | Оставить один owner brevity с required-content priority, второй убрать только после A/B | меньше риска слишком коротких итогов | рабочий Telegram/chat tone может стать длиннее |
| P3 | Для 44 969 B personal memory проверить indexed/progressive вариант, не резать вслепую | потенциально крупнейший fresh-worker tax | потеря редких, но дорогих уроков; нужен retrieval/eval, не size-only cap |

Не предлагать сейчас: глобальный rewrite `CLAUDE.md`, удаление всех примеров, объединение
worker/full-cycle code-quality ради maintenance-only дубля, миграцию `.codex/skills` на
`.agents/skills` без probe.

## 10. Контролируемый A/B eval: old vs surgical edits

### 10.1 Arms и порядок

Нельзя смешивать все правки в один lean-arm — потеряется причинность.

1. **Correctness tests без LLM A/B:** memory reload, bootstrap, review-context construction,
   compact description/current route.
2. **Arm A:** stale factual/model-owner edits only.
3. **Arm B:** one semantic duplicate group only.
4. **Arm C:** role-specific tools only.
5. **Arm D:** one-owner brevity only.
6. **Arm E:** Codex resume developerInstructions вместо user-copy — только после protocol probe.

Каждый следующий arm строится от последнего прошедшего, но сравнивается и с frozen original.

### 10.2 Corpus

- Pilot: 2 representative tasks × 3 роли (`orchestrator`, `worker`, `full-cycle`) × 2 repeats
  на arm/baseline. Один task на роль обязан быть из далёкой предметной области.
- Full run для переживших pilot: 6 tasks × 3 роли × 3 repeats × 2 arms = 108 runs.
- Fresh Codex threads; одна версия `gpt-5.6-sol`, одинаковые effort, repo snapshot, tool data,
  timeouts и task text. Порядок arm случайный и сбалансированный.
- Только isolated fixtures/worktrees; никакого prod/external write. Если task меняет состояние,
  evaluator получает artifact diff и side-effect log, не один transcript.

### 10.3 Метрики

**Quality/safety — primary gate:**

- checkable AC pass rate;
- required evidence/artifact completeness;
- correctness of final answer;
- unauthorized mutation / missed approval boundary;
- phase/lifecycle/report violations;
- unavailable-tool attempts и потерянные required capabilities.

**Efficiency — secondary:**

- initial and total input tokens, cached input, output tokens;
- wall latency p50/p90, turns;
- Orchestra tool calls;
- exact repeated call+args;
- no-progress loop: повторный call к тому же target без изменения relevant state/result;
- retries/errors and context growth per turn.

Измерять outcome, не «агент процитировал новое правило».

### 10.4 Success rule до full run

1. На pilot измерить split-half noise каждой метрики; **до** full run зафиксировать
   non-inferiority margin quality из этого шума, а не круглым числом.
2. Arm проходит только если нет safety regression и quality/evidence не хуже baseline за
   зафиксированной margin.
3. Efficiency win — хотя бы одна target metric (input tokens, calls/no-progress loops или latency)
   улучшается больше measured noise, а 95% paired bootstrap interval не пересекает нулевой эффект;
   остальные target metrics не имеют material regression.
4. Static byte reduction сама по себе — только diagnostic. Lower calls/tokens считаются выигрышем
   лишь при пройденном quality gate, как требует [1].

### 10.5 Candidate-specific checks

- **Memory:** после spawn/reload/compact ровно один block, содержимое только current; custom
  overlay/ownership сохранены; prompt size idempotent after second reload.
- **Review context:** high-load fixture не содержит `small team, MVP`; пустой context fail loud;
  findings не теряют real blocking issues.
- **Tools:** full-cycle может spawn/review/report; terminal worker не видит orchestrator-only;
  schema bytes и unavailable attempts падают.
- **Dedup:** research artifact сохраняет hypotheses/falsifiers/sources/confidence/counter-evidence;
  gate report и STOP остаются.
- **Brevity:** итог сохраняет conclusion, evidence, caveat и next action.
- **Resume:** unique new sentinel влияет на первый post-resume turn; старый sentinel не влияет;
  history не получает full user-copy.

## 11. Counter-evidence и ограничения

1. OpenAI ranges +10–15%/−41–66%/−33–67% — internal sample и directional, не обещание для
   Orchestra [1].
2. Exact duplicate evidence против массовой резки: same-run дословных повторов почти нет.
3. Предыдущий Sol OLS (`n=103` turns, `R²=0.646`) связывает cost прежде всего с числом calls;
   coefficient bytes имеет широкий interval, включающий ноль [4]. Prompt bytes важны для context,
   но их денежный эффект здесь не измерен.
4. Многие длинные правила несут локальный measured failure mode. #127 показал, что Opus-specific
   self-review можно удалить, но artifact verification переносить нельзя без собственного Sol A/B
   [7].
5. Skill bodies progressive; суммировать все 46 758 B в static tax было бы ошибкой [3].
6. Current prod frequency reload/bootstrap/review paths не измерялась по запрету задачи.
7. Native `.codex/skills` работает в текущей 0.146.0 сессии, но public manual предпочитает
   `.agents/skills`; до clean probe причина расхождения неизвестна.
8. Prompt refresh user-copy может быть cross-runtime safety mechanism. Его вред по размеру
   правдоподобен и согласуется с [1], но удаление без behavioral resume probe не готово.

## 12. Confidence

| Finding | Confidence | Основание |
|---|---|---|
| Официальные GPT-5.6 prompt practices и public Sol naming | **CONFIRMED** | primary official live source [1] |
| Assembly path и role/file inventory | **CONFIRMED** | current source trace + reproducible script |
| Static byte lower bounds и 34-tool/18 886 B tax | **CONFIRMED** | direct local serialization; token count отдельно не заявлен |
| Reload даёт второй memory block и +45 003 B | **CONFIRMED** | current code-path simulation на реальных role/memory files |
| `CLAUDE.md` skill/config/precompact facts stale | **CONFIRMED** | current config + current code + CLI version |
| Fixed MVP review context conflicts with current skill | **CONFIRMED** | оба active source texts открыты |
| Same-run semantic repeats вредят Sol | **LIKELY** | block sizes + official direction, но нет local A/B |
| Broad brevity уже ухудшает ответы | **UNCERTAIN** | official warning, local failure corpus отсутствует |
| User-copy prompt на Codex resume можно безопасно убрать | **UNCERTAIN** | duplicate route виден, application of updated developerInstructions не probed |
| Role-specific tool filtering улучшит итоговое качество | **UNCERTAIN** | tax доказан; outcome и безопасный subset требуют eval |
| External Codex second opinion | **UNAVAILABLE** | readiness отказал до старта job; strict Sol self-review записана отдельно |

## 13. Возможные затронутые файлы будущих фаз

- `app/manager.py`, `app/prompting.py`, `tests/test_manager.py`, `tests/test_prompting.py` — memory
  reconstruction/idempotence.
- `app/mcp_stdio.py`, `pipelines/default/prompts/skills/codex-debate.md`, review tests — context и
  tool descriptions.
- `CLAUDE.md` (и generated mirror автоматически, не вручную) — stale Codex facts.
- `pipelines/default/prompts/skills/orchestra-agents.md` — model owner.
- `app/backend_codex.py`, `app/manager.py`, pipeline manifest/tests — role tool exposure.
- `pipelines/default/prompts/roles/full-cycle.md`, modules `research-method`, `background-jobs`,
  `orchestration`, `task-management`, `base.md` — one-group dedup arms.
- `app/session.py`, `app/backend_codex.py`, session/backend tests — resume prompt channel.
- `app/bootstrap.py`, bootstrap tests — first-turn full role prompt.

## 14. Источники и evidence tiers

1. **[Primary official, fetched 2026-08-10]** OpenAI, *Model guidance — GPT-5.6*, секция
   `Prompting best practices`; introduction использована только для public naming `gpt-5.6-sol`:
   <https://developers.openai.com/api/docs/guides/model-guidance?model=gpt-5.6>
2. **[Primary official, fetched helper 2026-08-10]** OpenAI Codex manual,
   *Custom instructions with AGENTS.md*:
   <https://learn.chatgpt.com/docs/agent-configuration/agents-md>
3. **[Primary official, fetched helper 2026-08-10]** OpenAI Codex manual, *Build skills*:
   <https://learn.chatgpt.com/docs/build-skills>
4. **[Direct local measurement, prior task]** `docs/tasks/sol-efficiency/research.md` — Sol
   call/byte/cost corpus and anti-loop measurement.
5. **[Direct local measurement, prior task]** `docs/tasks/137/measurements.md` — historical
   tool usage/schema audit; used only with date/current-code caveats.
6. **[Primary official, fetched helper 2026-08-10]** OpenAI Codex manual,
   *Codex App Server*: <https://learn.chatgpt.com/docs/app-server>
7. **[Direct local measurement + primary Anthropic source, prior task]**
   `docs/tasks/127/research.md` — historical Opus audit; used to avoid repeating/provider-porting
   its conclusions.
8. **[Direct measurement, this task]** `docs/tasks/172/measure_prompts.py` plus command outputs
   recorded in this research: role/file bytes, exact duplicates, reload simulation, live FastMCP
   schemas.

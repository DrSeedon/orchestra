# Аудит промптов Orchestra

**Дата:** 2026-05-31
**Аудитор:** prompt-engineer (Opus)
**Скоуп:** `app/prompts/**` + сборка в `app/manager.py` / `app/backend_claude.py` + `CLAUDE.md`

---

## TL;DR

Промпты в неплохой форме: XML-структура, priority-уровни, decision tree у оркестратора — всё это правильные паттерны. Но есть **одна архитектурная дыра, которая обесценивает половину работы**, и **системное дублирование с тем, что и так инжектит харнесс**.

> **Версия 2** (после Codex review, 2026-05-31). Codex нашёл 2 фактические ошибки в v1 (энфорсмент `run_in_background` и `Agent`/`Task`) и 2 пропущенные находки. Все сверены по коду, исправлены ниже. Token-saving рекомендации, которые Codex счёл over-severe для MVP, смягчены.

**Топ-находки (по убыванию важности):**

1. 🔴 **Custom `system_prompt` оркестратора ПОЛНОСТЬЮ затирает роль-шаблон** (`manager.py:391`). Юзер пишет «ты — оркестратор проекта X» → теряются весь decision tree, tools, worker-каталог, модули. У воркеров — append (правильно), у оркестратора — replace (баг). Codex подтвердил: blocking, severity калибрована верно.
2. 🟠 **Часть NEVER-правил в base.md мертва, но НЕ все** — критично различать. После сверки с кодом (`backend_claude.py`):
   - `AskUserQuestion`, `Monitor` → `PermissionResultDeny` (deny для всех). Прозу можно сжать в 1 строку.
   - `Agent`/`Task` → вырезаны через `disallowed_tools` **ТОЛЬКО у оркестратора**. У воркеров `_disallowed_tools(False) == []` — правило в base load-bearing для воркеров. **НЕ удалять.**
   - `run_in_background` → **денится** в `_make_auto_approve()` (`backend_claude.py:45`) для всех. Я в v1 ошибочно назвал его «только прозой». Правило полезно (избегает wasted denied call + даёт альтернативу), но не единственный энфорсмент.
   - `SendMessage`, `send_message(to="user")` → ничем кроме прозы. Load-bearing. **НЕ удалять.**
3. 🟠 **orchestrator.md раздут (11KB)** — голые сигнатуры тулов дублируют MCP descriptions. НО (поправка Codex): роль-промпт даёт *one-path routing* (какие тулы orchestrator-approved, когда spawn/reuse/kill/merge) — это канонический tool-map, его НЕ трогать. Резать только сухой перечень параметров.
4. 🟠 **Stale skill в worker.md** (пропущено в v1, нашёл Codex): worker.md:70 велит юзать `Skill(skill="codex-review")`, а full-cycle.md и текущая система — нативный `codex_review()` MCP tool. Воркер пойдёт устаревшим путём. Реальный correctness-баг.
5. 🟡 **Конфликт по `report_bug`**: base.md «platform bug only» vs CLAUDE.md «любая ошибка». Фикс — узкий (одна строка), без размывания fail-loud.
6. 🟡 **bg_create cron-drift** (пропущено в v1, нашёл Codex): base.md `<background-jobs>` перечисляет timer/file/command/ssh/run и говорит «one-shot», но `bg_create()` поддерживает ещё `cron` (recurring). Либо добавить cron, либо убрать blanket «one-shot».

---

## 1. Структура: иерархия base → modules → roles

### Как собирается (по факту кода)

```
backend_claude.py:116  system_prompt = claude_code preset + append(ORCHESTRA_PROMPT)
                                                                      │
manager.py:219  ROLE_SYSTEM_PROMPT = base.md + role.md (+ modules) [+ catalogs для orch]
manager.py:135  role.md + "\n\n" + _load_modules(modules)   # git-workflow вклеивается
manager.py:391  is_orch:  prompt = custom_system_prompt OR role_template   ← ЗАМЕНА
manager.py:393  worker:   prompt = role_template + custom_system_prompt    ← ДОБАВЛЕНИЕ
```

**Вердикт по иерархии:** сама идея `base → modules → roles` **здоровая и правильная**. Модульность git-workflow — хороший ход (выносится в reuse, видно из коммита `a8bd151`). Frontmatter с `when`/`not_for`/`modules`/`skills` — отличный self-документирующийся паттерн, его не трогать.

### Проблемы структуры

**1.1 🔴 Асимметрия replace/append (manager.py:391-393).**
Для оркестратора `system_prompt or ROLE_SYSTEM_PROMPT(role, scope)` — если юзер задал кастомный prompt при спавне оркестратора, **роль-шаблон выкидывается целиком**. Decision tree, tools, pricing, memory-правила — всё теряется. Для воркера правильно: шаблон + кастом.

Это не промпт-баг, а баг сборки, но он напрямую убивает детерминизм оркестратора. **Рекомендация:** сделать симметрично — `ROLE_SYSTEM_PROMPT(role, scope) + ("\n\n" + system_prompt if system_prompt else "")`. Если намеренно нужен режим полной замены — он должен быть явным флагом, а не молчаливым поведением по `or`.
> ⚠️ Это правка Python-кода (вне моего скоупа «только .md»). Выношу как **рекомендацию для отдельной задачи**, не правлю сам.

**1.2 🔴 Дублирование с `claude_code` preset.**
`base.md` повторяет то, что preset уже даёт:
- «Respond in the same language the user communicates in» — preset + CLAUDE.md уже это покрывают (у меня в системном промпте это есть дважды).
- Communication tone, file-persistence советы — частично пересекаются с Claude Code guidance.

Не надо выпиливать всё подряд (Orchestra-специфика обязана остаться), но **всё, что дублирует preset, — кандидат на удаление**. См. раздел 3.

**1.3 🟡 Что дублируется между ролями.**
- `worker.md` и `full-cycle.md` оба несут «commit before DONE / git status clean» — но это УЖЕ есть в `git-workflow.md` модуле, который инжектится в обе роли. Тройное повторение.
- `worker.md:25` «ALWAYS use `mcp__orchestra__send_message`» дублирует base.md `<platform>` Communication-блок.

---

## 2. Детерминизм: где агент может свернуть не туда

**2.1 🟠 `report_bug` — двойная семантика (конфликт base.md ↔ CLAUDE.md).**
- base.md:25 → «report an **Orchestra platform** bug only».
- CLAUDE.md Agent Determinism → «Любая ошибка → `report_bug()`».
Агент не знает: репортить баг своего кода тоже? или только платформы? Развилка. **Фикс:** в base.md одной фразой развести — «`report_bug` = баги платформы Orchestra (MCP/SDK/харнесс). Баги в коде задачи → в `docs/tasks/<id>/` + сообщение оркестратору».

**2.2 🟡 «Fail loud» vs «One path» местами противоречат сами себе по форме.**
base.md `<rules standard>` даёт хороший fail-loud алгоритм (1-stop, 2-report_bug, 3-report orch, 4-wait). Но full-cycle.md и worker.md дают свои вариации «если непонятно — спроси оркестратора». Три формулировки одного правила в трёх файлах → агент сшивает их по-разному. **Фикс:** канонизировать fail-loud ОДИН раз в base.md, из ролей убрать дубли (оставить ссылку «see base fail-loud»).

**2.3 🟡 orchestrator decision tree — Step 1 «Trivial → do it yourself» конфликтует с critical-правилом «NEVER debug/fix/research yourself».**
Decision tree (orchestrator.md:42) разрешает делать тривиальное самому; critical rules (orchestrator.md:193) — «ONLY exception: truly trivial (1-2 lines)». Формально согласовано, но «trivial» определяется в двух местах по-разному (config/typo vs 1-2 lines). Свести к одному определению.

**2.4 🟢 Хорошо сделано:** orchestrator `<task-workflow>` с готовыми code-блоками (disposable/system/urgent worker) — это образцовый детерминизм. Не трогать.

---

## 3. Токен-эффективность

Каждый turn каждого агента тащит base.md + role.md + (preset). На длинных сессиях это main cost driver.

**3.1 🟠 base.md `<rules critical>` — 6 правил. Сверено по коду `backend_claude.py` (v1 содержала 2 ошибки, исправлены).**

| Правило base.md | Чем реально энфорсится (по коду) | Вердикт |
|---|---|---|
| NEVER Agent tool | оркестратор: `disallowed_tools=["Task","Agent"]` (вырезан). **Воркер: `_disallowed_tools(False)==[]` — НЕ вырезан**, тул доступен | ⚠️ load-bearing для ВОРКЕРОВ — **НЕ удалять**. Можно отметить, что у оркестратора это дубль (тул и так вырезан) |
| NEVER AskUserQuestion | `_BLOCKED_TOOLS` → `PermissionResultDeny` (все роли) | 🔸 сжать в 1 строку (тул в наборе, deny на вызов) |
| NEVER Monitor | `_BLOCKED_TOOLS` → `PermissionResultDeny` (все роли) | 🔸 сжать в 1 строку |
| NEVER run_in_background | **`_make_auto_approve()` денит** любой input с `run_in_background` (`backend_claude.py:45`, все роли) | ⚠️ не «только проза» (моя ошибка v1). Энфорсится. Правило полезно (избегает wasted denied call + альтернатива) — оставить кратко |
| NEVER SendMessage (built-in) | **ничем кроме прозы** | ✅ load-bearing — **НЕ удалять** |
| NEVER send_message(to="user") | **ничем кроме прозы** | ✅ load-bearing — **НЕ удалять** |

**Поправка после Codex (важно):** в v1 я ошибочно записал `run_in_background` в «ничем не энфорсится» и обобщил вырезание `Agent`/`Task` на всех агентов. По факту: `run_in_background` денится permission-хуком для всех; `Agent`/`Task` вырезаны ТОЛЬКО у оркестратора. Вывод: **массового удаления NEVER-правил НЕ делать.** Реальная экономия скромная — сжать только `AskUserQuestion` и `Monitor` в одну строку каждое (они deny, но видны модели → объяснение полезно, но 3 абзаца на тул избыточны). Это ~3-4 строки экономии, не «убрать половину блока».

> Принцип из research: >5 NEVER-правил снижает сигнал. Но для MVP, где детерминизм > минимализм (и Codex это подчеркнул), **сохранение явных guardrails важнее экономии токенов**. Сжимаем формулировки, не выпиливаем правила.

**3.2 🟠 orchestrator.md `<tools>` (строки 76-104) — справка по тулам дублирует MCP descriptions.**
Каждый MCP-тул уже имеет `description` (видно в схеме — `spawn_worker`, `merge_worker` и т.д. с полными доками). orchestrator.md переписывает их прозой. **Это самый жирный кусок на удаление** (~28 строк). Оставить только то, чего НЕТ в tool description: *стратегию выбора* (когда spawn vs reuse vs kill) — это ценно. Сухой перечень сигнатур — выкинуть.

**3.3 🟡 `<background-jobs>` в base.md (13 строк) для воркеров.**
Воркеру bg-jobs нужны редко (это больше оркестраторный паттерн). Но base.md инжектит их ВСЕМ. Кандидат: вынести bg-jobs в модуль `modules/background-jobs.md` и подключать только тем ролям, кому надо. Экономия ~13 строк × каждый turn воркера.

**3.4 🟢 skills (html-artifacts, vps-deploy) инжектятся как нативные Claude skills в worktree** (`manager.py:256` — копируются в `.claude/skills/`), а НЕ в системный промпт. Это правильно — они грузятся лениво. Не трогать.

---

## 4. Конфликты между уровнями

| # | Уровень A | Уровень B | Конфликт |
|---|---|---|---|
| 4.1 🟠 | base.md: report_bug = platform only | CLAUDE.md: report_bug на любую ошибку | Граница применения (см. 2.1) |
| 4.2 🟡 | base.md `<platform>`: «STOP and respond IMMEDIATELY» на mid-turn | full-cycle.md: «STOP. Wait for approval» (phase gates) | Два разных STOP с разной семантикой. Не баг, но агент может спутать «mid-turn user msg» с «phase gate». Развести терминологию |
| 4.3 🟡 | base.md: «Respond in same language as user» | CLAUDE.md (моя роль): «English for prompts, Russian for reports» | Для prompt-engineer роли — норм, но в общем base это потенциальный конфликт для воркеров, общающихся с оркестратором (англ) vs юзером (рус) |
| 4.4 🟢 | git-workflow.md squash-only | orchestrator merge_worker | Согласовано, конфликта нет |

---

## 5. Пропуски (uncovered scenarios)

**5.1 🟠 Нет правила про context-limit для воркера.** Оркестратор знает про `compact_worker` и «CONTEXT CRITICAL: N%». Воркер в worker.md/full-cycle.md НЕ знает, что делать при росте своего контекста. full-cycle с 3 фазами + Codex может упереться в лимит на Phase 3. **Фикс:** в base.md или worker.md одна строка — «при `CONTEXT CRITICAL` сообщи оркестратору, он решит compact/respawn».

**5.2 🟡 full-cycle: что если оркестратор не отвечает на gate.** Phase 1/2 заканчиваются «STOP, wait for approval». А если оркестратор молчит N времени? Сейчас воркер висит idle вечно (это ок по дизайну — idle = 0 ресурсов), но стоит явно написать «idle indefinitely, do NOT self-approve and proceed» — иначе Opus может «проявить инициативу» и пойти в Phase 2 сам. Это прямой риск детерминизма.

**5.3 🟡 Нет инструкции про конкурентные правки shared-файлов в реальном времени.** git-workflow.md говорит «coordinate through orchestrator» для shared files, но не описывает что делать при уже возникшем конфликте мёржа. Для MVP — приемлемо (оркестратор разрулит), упоминаю для полноты.

**5.4 🟢 Не пропуск, но отмечу:** vps-deploy.md хардкодит хост `orchestra.zahoron.ru`, а CLAUDE.md в одном месте упоминает старый `194.87.250.243` (это VPN, не Orchestra — ок). Деплой-скилл консистентен сам с собой.

**5.5 🟠 STALE: worker.md велит юзать `Skill(skill="codex-review")`, а надо `codex_review()` MCP tool** (нашёл Codex, сверено: `worker.md:70`). full-cycle.md явно говорит «Codex review via `codex_review()` MCP tool — NOT via bash/skill», а worker.md противоречит — отсылает к скиллу. Generic-воркер, которого попросят сделать Codex review, пойдёт устаревшим путём. **Реальный correctness-баг + прямой конфликт между ролями.** Фикс: в worker.md заменить на `codex_review()` MCP tool, как в full-cycle.

**5.6 🟡 bg_create cron-drift** (нашёл Codex). base.md `<background-jobs>` перечисляет timer/file/command/ssh/run и утверждает «Jobs are one-shot». Но `bg_create()` поддерживает ещё тип `cron` (recurring, по cron-расписанию). Агент, прочитав «one-shot», не узнает про cron и будет городить timer-перевызовы вместо одной cron-джобы. Фикс: либо добавить `cron` в список + убрать blanket «one-shot» (заменить на «большинство типов one-shot, `cron` — recurring»), либо, если cron не для агентов, убрать его из MCP description тула.

---

## 6. Конкретные правки по файлам

### `app/prompts/base.md`
- 🔸 **Сжать (НЕ удалять) `<rules critical>`**: `AskUserQuestion` и `Monitor` сжать в одну строку каждый («вызовут отказ — не используй»). `Agent`, `run_in_background`, `SendMessage`, `send_message(to=user)` — **ОСТАВИТЬ** (см. таблицу 3.1: `Agent` load-bearing для воркеров, `run_in_background` энфорсится но объяснение полезно, остальные — только проза). Реальная экономия ~3-4 строки, не «полблока».
- 🟠 **Развести `report_bug`** (одна строка): «`report_bug` = баги платформы Orchestra/MCP/SDK/харнесс. Баги в коде задачи → в `docs/tasks/<id>/` + сообщение оркестратору». Не размывать fail-loud (так настоял Codex).
- 🟠 **bg_create cron-drift** (см. 5.6): в `<background-jobs>` добавить тип `cron` либо заменить «Jobs are one-shot» на «большинство типов one-shot; `cron` — recurring».
- 🟡 **Вынести `<background-jobs>`** в `modules/background-jobs.md`, подключать через frontmatter только ролям, кому нужно (оркестратор, full-cycle). Опционально, не P0.
- 🟡 «Respond in the same language» — **НЕ удалять** (поправка Codex: не полагаться на недокументированное поведение preset). Оставить.
- 🟢 `<platform>` Communication, Persistence, Mid-turn — оставить, это Orchestra-специфика.

### `app/prompts/roles/orchestrator.md`
- 🟠 **Урезать `<tools>` (строки 76-104) ТОЧЕЧНО**: удалить только сухие перечни параметров, которые 1:1 совпадают с MCP descriptions. **СОХРАНИТЬ канонический tool-map**: какие тулы orchestrator-approved, when spawn/reuse/kill/merge, naming convention, task-ref. Это one-path routing — его удаление навредит детерминизму (поправка Codex). Экономия скромнее, чем в v1 (~10-12 строк, не 18).
- 🟡 Свести определение «trivial» к одному месту (decision tree Step 1 ↔ critical rule).
- 🟢 `<task-workflow>` code-блоки и `<decision-tree>` — образец, не трогать.

### `app/prompts/roles/worker.md`
- 🟠 **STALE FIX (см. 5.5):** заменить `Skill(skill="codex-review")` на `codex_review()` MCP tool, как в full-cycle.md. Реальный баг — конфликт между ролями.
- 🟡 Убрать дубли git-правил («commit before DONE», «task ref в коммите») — они в `git-workflow.md` модуле. Оставить ссылку.
- 🟡 Убрать дубль «ALWAYS use mcp__orchestra__send_message» (есть в base `<platform>`).
- 🟠 Добавить 1 строку про context-limit (см. 5.1).

### `app/prompts/roles/full-cycle.md`
- 🟡 Phase gates: добавить «idle indefinitely on gate, do NOT self-approve» (см. 5.2).
- 🟡 Убрать дубль git-правил (в модуле).
- 🟢 Сам 3-фазный pipeline — чёткий и детерминированный, структуру не трогать.

### `app/prompts/modules/git-workflow.md`
- 🟢 Хороший модуль. Единственное — он сейчас single source of truth для git-правил, значит из ролей дубли надо убрать В ЕГО ПОЛЬЗУ (см. выше).

### `app/prompts/skills/*`
- 🟢 html-artifacts.md: мелочь — два пункта пронумерованы «2» (CSS-in-file и works-offline). Косметика.
- 🟢 vps-deploy.md: консистентен, не трогать.

### Не .md, выношу как отдельную задачу (Python):
- 🔴 `manager.py:391` — починить replace→append для оркестратора (см. 1.1).

---

## Приоритизация правок

| Приоритет | Правка | Эффект |
|---|---|---|
| P0 | manager.py:391 replace→append (Python, отд. задача) | Чинит потерю роли оркестратора |
| P0 | worker.md: stale `Skill(codex-review)` → `codex_review()` MCP | Correctness — воркер шёл устаревшим путём |
| P1 | base.md: развести report_bug (1 строка) | Детерминизм |
| P1 | base.md: cron-drift в `<background-jobs>` | Correctness — агент не знает про cron |
| P1 | orchestrator.md: точечно урезать сухие сигнатуры в `<tools>` | ~10-12 строк/turn, БЕЗ удаления tool-map |
| P2 | base.md: сжать `AskUserQuestion`/`Monitor` в 1 строку | ~3-4 строки, сигнал |
| P2 | Убрать git-дубли из ролей | Чистота, меньше конфликтов |
| P2 | worker context-limit + full-cycle gate-idle | Закрыть пропуски |
| P3 | Вынести bg-jobs в модуль | Токены воркеров (опционально) |

> **Калибровка после Codex:** для MVP детерминизм > минимализм токенов. Token-saving правки понижены в приоритете; correctness-правки (stale skill, cron-drift, report_bug) — подняты. Массовое удаление NEVER-правил из v1 **отменено**.

---

## Что НЕ трогать (явно)

- Модульная архитектура base→modules→roles и frontmatter — здоровая.
- orchestrator `<decision-tree>` и `<task-workflow>` — образец детерминизма.
- full-cycle 3-фазный pipeline.
- Skills как нативные `.claude/skills/` (ленивая загрузка).
- `<platform>` Orchestra-специфика в base.md.
- Load-bearing NEVER-правила: `SendMessage` и `send_message(to=user)` (только проза), `Agent` (load-bearing для воркеров), `run_in_background` (энфорсится хуком, но объяснение альтернативы полезно).
- fail-loud алгоритм — не размывать в гибкую таксономию (настоял Codex).

---

## Метод аудита

Прочитаны все 7 промпт-файлов + CLAUDE.md. Проверена реальная сборка промптов в `manager.py` (`ROLE_SYSTEM_PROMPT`, `_load_modules`, replace/append логика) и `backend_claude.py` (preset `claude_code` + append, `disallowed_tools`, `_make_auto_approve` блоклисты). Best practices собраны отдельным research-агентом (источники: Anthropic prompt-engineering docs, Agent SDK system-prompt docs, multi-agent research системная статья Anthropic — ссылки в research-выжимке). Каждое утверждение про «харнесс уже энфорсит» сверено с кодом блоклистов.

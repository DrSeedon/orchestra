# Research: воркеры спавнят воркеров

**Дата:** 2026-07-15
**Автор:** research-worker-spawning (full-cycle, Opus 4.8)
**Задача:** как устроен worker-spawns-worker в Orchestra, реальные кейсы из DB, паттерны, риски, что улучшить, сравнение с built-in Agent Teams.

---

## Question (framed)

- **Контекст:** Orchestra — процесс-на-агента оркестратор. Каждый агент = отдельный Claude CLI в своём git worktree, состояние в SQLite.
- **Change under test:** воркеры (не только оркестраторы) УЖЕ могут спавнить своих саб-воркеров через `spawn_worker`. Насколько это осознанный паттерн, что ломается, что улучшить.
- **Baseline:** оркестратор→воркер (штатный путь, 97% всех спавнов).
- **Outcome (measurable):** реальные кейсы в DB, наличие/отсутствие лимитов и cleanup в коде, поведение git worktree при вложенном спавне.

---

## TL;DR (truth + confidence)

1. **Воркеры МОГУТ спавнить воркеров — by design, не баг.** `can_spawn: ["*"]` у всех ролей, MCP-сервер отдаёт ВСЕ тулы каждому агенту без фильтра по роли. **CONFIRMED (код).**
2. **Реально используется, но редко и только `full-cycle`:** 2 родителя-воркера, 6 детей, все archived чисто, 0 orphaned live, 0 depth-3. Vs 190 детей у оркестраторов. **CONFIRMED (DB).**
3. **Worktree детей физически НЕ вкладываются** — `git worktree add` из воркер-worktree создаёт плоский sibling на общий `.git` (проверено эмпирически). НО коллизия по имени/slug возможна и падает громко (`if wt_path.exists(): raise`). **CONFIRMED (эксперимент + код).**
4. **Нет лимитов глубины/числа детей, нет kill-cascade.** Убьёшь родителя → дети становятся orphaned (живут до ручного kill). **CONFIRMED (код).**
5. **В промптах `full-cycle`/`worker` НЕТ ни слова про суб-воркеров** — capability немая. Фронт уже рисует дерево по `parent_name`. **CONFIRMED (код).**
6. **Built-in субагенты (2026)** = комплементарный ВНУТРЕННИЙ слой для эфемерного fan-out, не конкурент внешней оркестрации. Точный depth-cap вложенности — **UNCERTAIN** (web-источники конфликтуют, Codex оспорил «depth=5»). «Built-in дешевле для fan-out» — **гипотеза без A/B** (cost субагентов уже входит в session-total, прямое сравнение невалидно).

> **Валидация:** research прошёл adversarial Codex-ревью (CLI 2.1.197 + актуальные docs + read-only DB). Codex подтвердил F1.3, F6.2/6.3, R4; оспорил абсолютность F3, «любого воркера» (→ scope-bound), depth=5 (→ UNCERTAIN), «built-in дешевле» (→ гипотеза). Все правки внесены inline с пометкой «правка после Codex». Полный вердикт: `codex-review-research.md`.

---

## Findings

### F1. Механика: кто может спавнить и почему

**F1.1 — `can_spawn: ["*"]` у ВСЕХ ролей**, включая `worker` и `full-cycle`.
Источник: `pipelines/default/pipeline.yaml:26,40,56,71`. Гейт `validate_spawn` (`app/pipeline.py:493`) на `"*" in parent.can_spawn` → `return` (разрешено). **CONFIRMED — primary (код).**

**F1.2 — MCP-сервер отдаёт ВСЕ `@mcp.tool()` каждому агенту.** В `app/mcp_stdio.py` нет фильтрации тулов по роли. `spawn_worker`, `merge_worker`, `kill_worker`, `switch_worker_branch` доступны воркеру так же, как оркестратору. Единственная роль-логика — косметика в `list_agents` (`is_worker = ROLE not in _ORCH_ROLES`, строка 235) для группировки вывода. **CONFIRMED — primary (код).**

**F1.3 — built-in `Agent`/`Task` тулы блокируются ТОЛЬКО оркестраторам, воркерам оставлены.**
`_ORCH_DISALLOWED_TOOLS = ["Task", "Agent"]` применяется если `is_orchestrator=True` (`app/backend_claude.py:39,64-65`). Воркер (`is_orchestrator=False`) сохраняет built-in субагентов. То есть у воркера ДВА пути параллелизма: (а) `spawn_worker` (Orchestra CLI-процесс) и (б) built-in `Agent` (in-process субагент). **CONFIRMED — primary (код).**
> ⚠️ Это нарушает принцип Agent Determinism («1 задача = 1 workflow»): у воркера две развилки для «сделай параллельно». См. R-риски.

**F1.4 — `parent_name` пробрасывается автоматически = имя вызывающего.**
MCP-тул хардкодит `"parent_name": WORKER_NAME` (`app/mcp_stdio.py:85`), где `WORKER_NAME` = env спавнящего агента. Значит любой агент, вызвавший `spawn_worker`, становится родителем ребёнка. `parent_id` дорезолвится из `parent_name` (`manager.py:482-485`). **CONFIRMED — primary (код).**

### F2. Реальные кейсы из DB (все scope)

Данные: `data/orchestra.db`, self-join `sessions` по `child.parent_name = parent.name`.

**2 родителя-воркера, оба `full-cycle` + Opus, оба спавнили 3 `worker`+Sonnet ребёнка:**

| Родитель | Роль/модель | Scope | Дети | Статус детей |
|---|---|---|---|---|
| `global-job-researcher` | full-cycle / opus-4-8 | COG-second-brain | jr-region-west, jr-region-eu, jr-region-asia-cis (все Sonnet) | 3/3 archived |
| `customer-finder` | full-cycle / opus-4-8 | seedon | cf-vc-habr, cf-forums-tg, cf-triggers (все Sonnet) | 3/3 archived |

Оба — **параллелизация research** (регионы / источники лидов). Дети жили 7-14 мин, отработали и archived. Стоимость: родитель ~$11 + 3 ребёнка ~$10 = ~$21 на задачу (global-job-researcher).

**Метрики масштаба:**
- Распределение спавнеров: оркестраторы — 190 детей (97.2%), воркеры — 6 детей (2.8%).
- Роль спавнера-воркера: `full-cycle` — 2, `worker` — 0. **Обычный `worker` не спавнит вообще.**
- Scopes с worker-spawns-worker: 2 (COG-second-brain + seedon), **не только COG.**
- Depth-3 nesting: **0** (ни один ребёнок-воркера сам не спавнил).
- Orphaned live (ребёнок running/idle при мёртвом родителе): **0.**
- Status детей: 6/6 archived (100% чистое завершение).

**Историческая аномалия (orphan):** 2 archived-ребёнка (`grounded-dev`, `translator-1`, scope RimWorld) с `parent_name='Mods-orchestrator'`, которого уже нет в DB. Оба archived — не активная проблема, но демонстрирует: **orphan возможен, cleanup не подчищает.** **CONFIRMED — measurement (DB).**

### F3. Git worktree детей: физически плоские, но коллизия по имени возможна

> **Правка после Codex-ревью:** исходная формулировка «nesting невозможен by design» была слишком абсолютной. Верно: worktree детей физически НЕ вкладываются (git резолвит в общий `.git`). Неверно: «никаких коллизий» — коллизия по name/slug возможна и падает громко.

**F3.1 — worktree детей плоские, keyed по scope-slug+name.**
`WORKTREE_ROOT = app/../worktrees` — **фиксированный абсолютный путь от install Orchestra**, НЕ относительно cwd вызывающего (`app/workspace.py:24`). Даже когда воркер зовёт `spawn_worker(repo_path=<свой worktree>)`, ребёнок создаётся в `worktrees/<scope-slug>/<child-name>`, siblings с родителем. DB подтверждает: дети `global-job-researcher` лежат в `worktrees/home-maxim-cursor-cog-second-brain/jr-region-*`, рядом с родителем, не внутри. **CONFIRMED — primary + measurement.**

**F3.1b — коллизия по имени → спавн падает громко (не тихий баг).**
`wt_path = WORKTREE_ROOT/scope_slug/name`; `if wt_path.exists(): raise ValueError("worktree already exists")` (`workspace.py:171,179-180`). Плюс `UNIQUE(name, scope)` в DB и явная проверка `create_session` (`manager.py:399-403`). Значит: два ребёнка (или ребёнок+существующий sibling) с одинаковым `name` в одном scope → второй спавн **фейлится с ошибкой**, а не молча перезаписывает. Коллизия ВОЗМОЖНА (fail-loud), «невозможности» нет. Разные scope с одинаковым именем — разные slug-папки, не сталкиваются. **CONFIRMED — primary (код).**

**F3.2 — эксперимент: `git worktree add` из worktree → плоский sibling.**
```
main-repo (master) → wtA (featA)
  из wtA: git worktree add ../wtB -b featB master
  → wtB.git-common-dir = main-repo/.git   (НЕ wtA)
  → wtB.toplevel = /tmp/.../wtB            (sibling, не вложен)
  → worktree list: main-repo, wtA, wtB — все плоские
```
Git всегда резолвит в common `.git`. **Вложенности worktree не бывает.** **CONFIRMED — measurement (эксперимент /tmp).**

**F3.3 — base_branch детей = `main` (default pipeline).**
`base_branch_strategy: main` в `pipelines/default/pipeline.yaml:15`. Все дети ответвляются от `main`, НЕ от ветки родителя. DB: `jr-region-*` на `main`, `cf-*` на `feat/.../`. Merge тоже идёт в `main` (`merge_worktree_to_main`, hardcoded target). **CONFIRMED — primary + measurement.**
> Нюанс: если у пайплайна `base_branch_strategy: parent`, ребёнок ответвится от ветки родителя-воркера (`_resolve_base_branch`, `manager.py:879-884`), но merge всё равно пойдёт в `main` — работа ребёнка может «перепрыгнуть» незамерженную работу родителя. Для `default` (strategy=main) это не проблема.

### F4. Кто мержит детей воркера

**Любой агент может мержить любого воркера В ТОМ ЖЕ SCOPE** — merge-route (`app/routes/sessions.py:609,615`) не имеет orchestrator-only гейта, но резолвит цель через `get_by_name(name, scope)` → ограничено scope вызывающего (правка после Codex: «любого воркера» без оговорки было переширено). Воркер-родитель может сам вызвать `merge_worker(child)` → его дети попадут в `main`. На практике (F2) дети были research-only (пишут в `docs/`, код не трогают) → мержить нечего, просто archived. **CONFIRMED — primary (код).**

### F5. Видимость и коммуникация саб-воркеров

**F5.1 — родитель видит своих детей как «Your workers»** (`list_agents`: `pn == WORKER_NAME`, строка 244).
**F5.2 — саб-воркеры-сиблинги НЕ видят друг друга как «своих».** Для `jr-region-west` брат `jr-region-eu` попадает в «Other orchestrators' workers» (parent = researcher, не west) с ворнингом «avoid sending tasks directly». Общаться технически могут (`send_message` доступен всем, работает по имени), но получат ownership-warning (`mcp_stdio.py:176-177`). **CONFIRMED — primary (код).**
**F5.3 — фронт уже рисует иерархию деревом.** `app.js:1381-1416` — рекурсивный `buildNode` по `childrenMap[parent_name]`, CSS `tree-node/tree-child/tree-children`, cycle-guard. Дети-воркера отображаются вложенными под родителем-воркером на любой глубине. **CONFIRMED — primary (код).**

### F6. Лимиты и cleanup — отсутствуют

**F6.1 — НЕТ лимита глубины, НЕТ лимита числа детей.** Grep по `max_depth|depth|max_children|spawn_limit|nesting` в `app/*.py` — ноль совпадений (кроме UI-indent). Ничто не мешает воркер→саб→саб-саб рекурсии, кроме того что промпты про это молчат. **CONFIRMED — primary (код).**

**F6.2 — НЕТ kill-cascade.** `manager.remove(session_id)` (`manager.py:606-619`) снимает ОДНУ сессию: cancel bg-jobs, disconnect backend, remove свой worktree, `archive_session`. **Ни одной ссылки на детей — каскада нет.** Убьёшь родителя → `parent_name` детей указывает на archived-строку (kill **архивирует** parent row, а не удаляет — правка после Codex, поэтому self-join мог бы его ещё найти; но на фронте `list_sessions` не отдаёт archived → `byName.has(pn)` false → дети «всплывают» как roots). Дети живут до ручного kill. Доказательство — сам код `remove` (measurement по F2-orphans лишь иллюстрирует, не доказывает: там parent вообще исчез из DB, что другой сценарий). **CONFIRMED — primary (код remove).**

> Асимметрия: `change_orchestrator_scope` (`manager.py:642-645`) БЛОКИРУЕТ операцию при живых воркерах в scope, а `remove`/kill родителя — НЕТ. Гейт «не оставляй сирот» существует для смены scope, но не для kill. Аргумент за R2-guard.

**F6.3 — auto-cleanup чистит только осиротевшие ДИРЕКТОРИИ, не сессии.** `cleanup_stale_worktrees` (`workspace.py:747`) удаляет worktree-папку только если её пути НЕТ ни в одной DB-сессии И она clean. Живой orphan (DB-сессия есть, родитель мёртв) — в `alive_paths`, worktree сохраняется. **CONFIRMED — primary (код).**

### F7. Сравнение с built-in Agent Teams / субагентами (Claude Code 2026)

> Источник: web-research (Anthropic docs fetched 2026-07) + third-party. **⚠️ Codex-ревью (CLI 2.1.197 + актуальные docs) оспорил часть цифр этого раздела — см. правки ниже.** Разделяю documented / inference / DISPUTED.

**Три РАЗНЫХ built-in примитива (не путать):**
| Примитив | Что | Процесс | Персист | Peer-to-peer |
|---|---|---|---|---|
| Субагенты (`Agent`/`Task`) | helpers внутри одной сессии | тот же процесс, отдельный контекст | эфемерны (но resumable через `.jsonl`) | нет (только report наверх) |
| Agent Teams (experimental) | несколько полных сессий CC | отдельные инстансы CC | task-list переживает resume, teammates — нет | ДА (mailbox + shared task list) |
| Background agents | детач-процессы CC + supervisor | отдельные процессы | **переживают закрытие терминала; после sleep/shutdown восстанавливаются из сохранённого состояния** (правка Codex: не «выполнение переживает sleep», а состояние; при attach/reply — respawn/restart) | через supervisor |

**Что изменилось в 2026 (осторожно — цифры спорны):**
- **DISPUTED: вложенность субагентов и hard-cap depth=5.** Мой web-research-субагент заявил «nested since v2.1.172, cap=5» со ссылкой на third-party (ofox.ai). Codex, проверив установленный CLI 2.1.197 + актуальные официальные docs, утверждает что это **противоречит текущей документации**. Конфликт источников не разрешён из кода Orchestra (это внешний факт про Claude CLI). **UNCERTAIN — сырое противоречие двух вторичных источников, НЕ опираться на конкретное число «5» в архитектурных решениях.** Для Orchestra практический вывод не зависит от точной цифры: built-in имеет *какой-то* лимит вложенности, у Orchestra — нет (F6.1), и это аргумент за R3 независимо от того, 5 там или иначе.
- **`Task` переименован в `Agent`** (алиас `Task(...)` работает) — согласовано обоими.
- **Есть first-class peer-to-peer** — Agent Teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`): mailbox + shared task-list с file-locking, nested teams запрещены. LIKELY (docs).
- **Субагент `isolation: worktree`** — built-in даёт временный worktree субагенту. LIKELY (docs).

**Orchestra vs built-in — где Orchestra это по сути тот же shape что Anthropic:**
- Orchestra (CLI-процесс + worktree + SQLite + Opus-оркестратор) архитектурно = Agent Teams (peer messaging + shared task list) + background agents (detached persist + worktree + supervisor). Anthropic пришёл к тому же независимо.
- Built-in субагенты = **комплементарный ВНУТРЕННИЙ слой** для эфемерного fan-out, НЕ конкурент внешней оркестрации.

**Когда что (documented recommendation):**
- **Эфемерный fan-out** («5 источников параллельно → summary») → built-in субагенты дешевле (результат сворачивается наверх, общий repo, нет per-process prompt-налога). Отдельный CLI-процесс на источник = оверинжиниринг (платишь N контекстов, выкидываешь N-1).
- **Долгоживущая параллельная имплементация** (агенты часами правят разные модули) → процесс-на-worktree (Orchestra / Teams / background). Субагенты плохо: эфемерны, привязаны к живому родителю, делят cwd (коллизии) если без `isolation: worktree`.
- **Комбинировать МОЖНО и это рекомендованный слоёный паттерн:** оркестратор спавнит долгоживущих CLI-воркеров (worktree каждому), каждый воркер ВНУТРИ юзает built-in субагентов для эфемерного fan-out (research/тесты/verify), чтобы verbose-вывод не засорял его контекст. **Именно так этот research и делался** (я — CLI-воркер, юзал built-in `Explore`/`general-purpose` субагентов для DB-анализа и web-research).

---

## Counter-evidence / что против

- **«Воркеры спавнят воркеров» звучит как риск бесконтрольного размножения** — но DB показывает 0 depth-3, 0 orphaned live, 6/6 archived. На практике `full-cycle` использует это дисциплинированно (research fan-out, дети без кода → нечего мержить). Риск теоретический, не реализовавшийся. Но: выборка мала (2 кейса, оба за 2026-07-15), паттерн новый — статистику рано считать репрезентативной.
- **Cost-аргумент против:** Opus-родитель + N Sonnet-детей = N+1 полных контекстов, каждый со своим system-prompt. global-job-researcher: ~$21 на задачу. Но это Max-подписка (виртуальные $), и fan-out дал реальный параллелизм (14 мин vs последовательно ~40+). Trade-off оправдан для research, сомнителен для мелочи.
- **ГИПОТЕЗА (не CONFIRMED): built-in субагенты дешевле для этого же fan-out** (F7). Правка после Codex: субагент ТОЖЕ имеет отдельное context window и model usage; более того, cost Orchestra-сессии в DB УЖЕ включает usage её субагентов (`app/db.py:722` — «session total already counts subagents»). Значит сравнивать напрямую session-rows нельзя, а «сэкономил бы 3 CLI-процесса» — неизмеренное допущение. Что documented (docs): у built-in субагентов меньше coordination/context-overhead относительно Agent Teams. Что НЕ измерено: конкретная экономия для этих Orchestra-задач. **UNCERTAIN — нужен controlled A/B, сейчас гипотеза.** Контр-контр (в пользу spawn_worker): Orchestra-воркеры видны на дашборде/в DB (телеметрия, resume, TG), built-in субагенты — чёрный ящик внутри воркера. Видимость — реальное преимущество spawn_worker независимо от cost.

---

## Affected files (для Phase 2, если делаем улучшения)

- `pipelines/default/prompts/roles/full-cycle.md` — добавить паттерн «когда спавнить суб-воркеров vs built-in субагенты».
- `pipelines/default/prompts/roles/worker.md` — то же (или явно запретить обычному воркеру).
- `app/manager.py` — если делаем kill-cascade / orphan-cleanup / depth-limit.
- `app/mcp_stdio.py:85` — `parent_name` проброс (уже корректен).
- `app/static/js/app.js:1381` — tree-view (уже есть, возможно доработка индикации orphan).
- `pipelines/default/pipeline.yaml` — если сужаем `can_spawn` для роли `worker`.

## Risks / edge cases (для кода, что придёт)

- **R1 (детерминизм):** у воркера ДВА пути параллелизма (`spawn_worker` + built-in `Agent`). Нарушает «1 задача = 1 workflow». Надо явно развести в промпте: fan-out эфемерный → built-in `Agent`; долгоживущий/видимый → `spawn_worker`.
- **R2 (orphan):** нет kill-cascade. Убитый/compacted родитель → живые дети-сироты. Нужен либо cascade, либо cleanup осиротевших сессий, либо запрет kill родителя с живыми детьми.
- **R3 (unbounded recursion):** нет depth-limit. Воркер может уйти в саб-саб-саб. Built-in Claude имеет *какой-то* лимит вложенности субагентов (точная цифра UNCERTAIN, см. F7) — сам факт лимита у built-in vs его отсутствия у Orchestra — аргумент за soft depth-guard.
- **R4 (merge target = main, реальный design bug при strategy=parent):** `merge_worker` дефолтит `target="main"` (не hardcoded — это неудачный дефолт, target параметризуем). При `base_branch_strategy=parent` ребёнок ответвлён от ветки родителя, но merge в `main` переносит в main **совокупную работу родителя И ребёнка** (всё что между main и точкой ветвления ребёнка), опережая незамерженную работу родителя. Для `default`-пайплайна (strategy=main) — не проблема (ребёнок и так от main). **Реальный баг для parent-стратегии; правка после Codex — уточнил «не hardcoded, а default; переносит совокупную работу».**
- **R5 (cost без контроля):** N+1 Opus/Sonnet контекстов. Нет предупреждения «ты создаёшь 6 агентов на одну задачу». Стоит логировать/предупреждать.
- **R6 (sibling isolation):** саб-воркеры-сиблинги видят друг друга как «чужих» с ворнингом — если родитель хочет их скоординировать (west+eu обменялись данными), UX не помогает.

## Рекомендации (пойдут в Phase 2 plan, НЕ реализовано)

1. **Промпт-паттерн для `full-cycle`:** явный decision-tree «fan-out research → built-in `Agent` (дешевле, эфемерно); долгоживущая видимая имплементация по тикетам → `spawn_worker`». Закрывает R1.
2. **Обычному `worker` — сузить `can_spawn` до `[]` (terminal)** или явно в промпте «не спавни, ты лист». DB: обычный worker и так не спавнит — закрепить.
3. **Orphan guard:** при kill/archive родителя с живыми детьми — либо cascade-kill (с confirm), либо блок «сначала разберись с детьми». Закрывает R2.
4. **Depth-limit = 2-3** (у нас процессы дороже built-in субагентов, так что лимит строже разумен) — мягкий (warning) или жёсткий (block). Закрывает R3.
5. **Spawn-cost awareness:** предупреждение в ответе `spawn_worker` когда у вызывающего уже N≥3 живых детей. Закрывает R5.
6. **Tree-view:** индикатор orphan (родитель мёртв) на фронте — сейчас orphan «всплывает» как root без пометки. Мелочь.

Приоритет: **R1 (промпт-развод spawn vs built-in) и R2 (orphan) — самые ценные.** R3-R5 — nice-to-have. Улучшения фронта — косметика (дерево уже работает).

---

## Sources

**Код (primary, tier-2):**
1. `pipelines/default/pipeline.yaml:15,26,40,56,71` — can_spawn, base_branch_strategy
2. `app/pipeline.py:454-499` — validate_spawn
3. `app/mcp_stdio.py:60-122,167-260,397-427` — spawn_worker, send_message, list_agents, merge_worker
4. `app/backend_claude.py:33-66` — disallowed_tools (Agent/Task блок только оркестраторам)
5. `app/manager.py:383-509,606,859-884` — create_session, remove, _resolve_base_branch
6. `app/workspace.py:24,158-233,747-795` — WORKTREE_ROOT, create_worktree, cleanup_stale_worktrees
7. `app/routes/sessions.py:603-660` — merge route (нет orch-only гейта)
8. `app/static/js/app.js:1381-1424` — tree-view render

**DB (measurement, tier-1):** `data/orchestra.db`, sessions self-join. 2 worker-parents, 6 children, 190 orch-children, 0 depth-3, 0 orphaned-live, 2 historical archived-orphans.

**Эксперимент (measurement, tier-1):** `/tmp` git worktree nesting test — `git worktree add` из worktree → плоский sibling на общий `.git`.

**Web (secondary, tier-3/4):** Anthropic docs (fetched 2026-07): code.claude.com/docs/en/{sub-agents, agent-teams, agent-view, worktrees}; third-party: ofox.ai/blog/claude-code-nested-subagents-2026, shipyard.build, mindstudio.ai. Depth=5 cap — docs + ofox corroboration. Agent Teams experimental flag — docs.

# Research: коллекция скиллов mattpocock/skills — что интегрировать в Orchestra

**Дата:** 2026-07-03
**Автор:** researcher
**Источник:** https://github.com/mattpocock/skills (ветка `main`, коммиты читал через `gh api`, доступ 2026-07-03)

---

## Вопрос

Изучить коллекцию скиллов Matt Pocock, оценить применимость к Orchestra (роли orchestrator / sub-orchestrator / worker / full-cycle / experimenter / researcher), решить что интегрировать в `pipelines/default/`. Особый фокус — `/to-tickets` (дробление плана на тикеты с AC), сравнение `/grill-me`, отсев дублей.

## TL;DR

Коллекция mattpocock — это **не набор скиллов, а целостная методология "idea → ship"**, которая по структуре почти 1:1 совпадает с моделью Orchestra (оркестратор дробит → воркеры делают в чистом контексте). Главный кандидат — **`to-issues`** (бывший `/to-tickets`): он ровно решает нашу боль «большой план перегружает контекст» — режет план на **вертикальные слайсы (tracer bullets) с acceptance criteria и `blocked-by`**, каждый слайс = отдельный воркер в чистом контексте. Это идеальная Phase-2 для будущего super-full-cycle. Ещё 3-4 скилла стоит адаптировать (`to-prd`, `handoff`, паттерны из `code-review`/`diagnosing-bugs`/`tdd`). Наш `grill-me` **богаче** оригинала — не заменять, максимум дополнить одним приёмом. Прямых дублей с нашими скиллами почти нет.

**Важно:** `/caveman` и `/zoom-out`, которые юзер использует, **удалены из репы самим mattpocock** (коммит `47bde84`): caveman — «случайный дубль, не для публики», zoom-out — «на практике не использовался». У юзера остались локальные копии. В текущей репе их SKILL.md нет — оценить могу только по описанию из CHANGELOG.

---

## Ключевая находка: это методология, а не коллекция

Файл `skills/engineering/ask-matt/SKILL.md` — роутер, который описывает **main flow** всей коллекции. Он читается как описание Orchestra:

```
idea
 → /grill-with-docs  (заострить идею интервью, копит CONTEXT.md + ADR)
 → [ветка] нужен прототип? → /handoff → /prototype → /handoff обратно
 → [ветка] multi-session build?
     ДА → /to-prd → /to-issues → чистый контекст на каждый issue → /implement
     НЕТ → /implement прямо здесь
 → /implement гоняет /tdd внутри (red-green по слайсам) → /code-review → commit
```

Плюс явное правило **context hygiene**, которое у нас в CLAUDE.md сформулировано как «большой план перегружает контекст»:

> Keep grill→PRD→issues in **one unbroken context window**… Each `/implement` then starts **fresh**, working from the issue. The limit is the **smart zone** (~120k tokens) within which the model still reasons sharply. If a session approaches it, `/handoff` and continue in a fresh thread.

**Вывод для Orchestra:** mattpocock решает ту же проблему тем же способом (дроби + чистый контекст на слайс), но **вручную, одним человеком в одном Claude Code**. У нас это автоматизировано через оркестратор+воркеры. Значит их скиллы-дисциплины (что класть в тикет, как резать слайсы, как ревьюить) ложатся на наши роли почти без переделки — надо взять *содержание*, а не *механику переключения контекста* (у нас она своя, лучше).

---

## Таблица всех скиллов

Легенда вердикта: 🟢 интегрировать · 🟡 адаптировать (взять идею/куски, не копировать as-is) · 🔴 не нужно

### engineering/

| Скилл | Что делает | Вердикт | Куда |
|---|---|---|---|
| **to-issues** (`/to-tickets`) | Режет план/PRD на независимо-берущиеся issue вертикальными слайсами (tracer bullets), каждый с AC + `blocked-by`. | 🟢 **топ-1** | orchestrator + будущий super-full-cycle (Phase 2) |
| **to-prd** | Синтезирует текущий разговор в PRD (problem/solution/user stories/decisions/testing/out-of-scope). Без интервью. | 🟡 | orchestrator / full-cycle (шаблон плана) |
| grill-with-docs | `/grilling` + `/domain-modeling` — интервью, которое копит `CONTEXT.md` (глоссарий) и ADR. | 🟡 | глобально (для проектов с кодовой базой) |
| triage | Гоняет входящие issue/PR через state-machine ролей (needs-triage→ready-for-agent→…), пишет agent-brief. | 🔴 | — (у нас Task Manager + YouGile) |
| code-review | Ревью diff по 2 осям (Standards+Fowler-смеллы / Spec) параллельными сабагентами. | 🟡 | worker/full-cycle (дополнить codex-debate) |
| tdd | Red-green-refactor, «seam», анти-паттерны тестов, вертикальные слайсы. | 🟡 | worker/full-cycle (у нас TDD в CLAUDE.md уже) |
| diagnosing-bugs | 6-фазный цикл диагностики: сначала tight red-capable feedback loop, потом гипотезы. | 🟡 | новый bug-роль / worker-модуль |
| codebase-design | Словарь «deep modules» (module/interface/seam/depth/adapter/leverage). Design-it-twice. | 🟡 | глобально (reference) |
| improve-codebase-architecture | Скан кодовой базы на «deepening opportunities», HTML-отчёт, грилл выбранной. | 🔴 | — (узкий, требует их setup) |
| research | Фоновый агент читает primary sources → cited markdown в репу. | 🔴 **дубль** | — (= наша роль `researcher`) |
| implement | Реализует PRD/issues через /tdd на seam'ах, потом /code-review, commit. | 🔴 **дубль** | — (= наш worker/full-cycle) |
| domain-modeling | Активно точит доменный язык проекта, ведёт `CONTEXT.md` + ADR. | 🟡 | глобально (reference, с grill-with-docs) |
| prototype | Одноразовый прототип (terminal app или несколько UI-вариантов) чтобы ответить на design-вопрос. | 🟡 | experimenter (близко по духу) |
| ask-matt | Роутер по скиллам репы. | 🔴 | — (специфичен для их набора) |
| setup-matt-pocock-skills | Разовая настройка issue-tracker/лейблов/doc-layout под их скиллы. | 🔴 | — (инфра их набора) |
| resolving-merge-conflicts | (не читал детально — узкий) | 🔴 | — (у нас squash-merge оркестратором) |

### productivity/

| Скилл | Что делает | Вердикт | Куда |
|---|---|---|---|
| **handoff** | Сжимает разговор в handoff-документ (+ «suggested skills»), чтобы свежий агент продолжил. Не дублирует PRD/ADR — ссылается. | 🟢 | глобально + модуль перед compact |
| grill-me | Просто запускает `/grilling`. | 🔴 **у нас лучше** | — (наш grill-me богаче) |
| grilling | Примитив: интервью по одному вопросу за раз, на каждый — рекомендованный ответ, ветки дерева решений. | 🟡 | (взять правило «один вопрос за раз» в наш grill-me) |
| teach | Учит юзера концепции через несколько сессий, текущая директория = workspace. | 🔴 | — |
| writing-great-skills | Reference как писать скиллы (у нас есть quick-skill/skill-creator). | 🔴 **дубль** | — |

### misc / personal / deprecated / in-progress

| Скилл | Что | Вердикт |
|---|---|---|
| misc/git-guardrails-claude-code | Git-хуки-предохранители для CC | 🔴 |
| misc/setup-pre-commit, scaffold-exercises, migrate-to-shoehorn | узкие/личные | 🔴 |
| personal/edit-article, obsidian-vault | личный сетап Matt | 🔴 |
| **in-progress/wayfinder** | Планирование огромной «туманной» работы как карты investigation-тикетов на трекере, резолвит по одному; fog-of-war. | 🟡 **интересно** | (см. раздел ниже — альтернатива to-issues для foggy-скоупа) |
| in-progress/wizard | Генерит bash-визард, проводящий человека по ручной процедуре (setup/миграция), пишет .env + gh secrets. | 🟡 | (для нашего setup/deploy — низкий приоритет) |
| in-progress/loop-me | Грилл про «loops» в жизни юзера → workflow-специи в `workflows/*.md`. | 🔴 | — |
| in-progress/claude-handoff, writing-* | черновики | 🔴 |
| deprecated/* (design-an-interface, qa, request-refactor-plan, ubiquitous-language) | устарели у самого автора | 🔴 |
| **caveman** (УДАЛЁН) | По CHANGELOG — «дубль другого скилла, не для публики». В репе нет. | 🔴 | — |
| **zoom-out** (УДАЛЁН) | По CHANGELOG — «на практике не использовался». В репе нет. | 🔴 | — |

---

## Топ-кандидаты детально

### 🟢 1. to-issues (бывший `/to-tickets`) — ГЛАВНЫЙ

**Что даёт.** Берёт большой план/PRD и режет на issue, каждый из которых:
- **вертикальный слайс (tracer bullet)** — тонкий, но проходит СКВОЗЬ все слои (schema→API→UI→tests), а не горизонтальный слой одного уровня;
- **демонстрируем/проверяем сам по себе**;
- имеет **acceptance criteria** (чеклист) и **blocked-by** (граф зависимостей);
- НЕ содержит путей к файлам и сниппетов (устаревают быстро) — только поведение end-to-end.

Шаблон issue из скилла:
```
## What to build   — end-to-end поведение, не layer-by-layer
## Acceptance criteria — [ ] criterion 1 / 2 / 3
## Blocked by       — ссылки на блокеры или "None - can start immediately"
```

Процесс: gather context → (optional) explore codebase + prefactor → draft слайсы → **quiz user** (гранулярность? зависимости верны? слить/разбить?) → публикация в трекер в порядке зависимостей.

**Почему это ровно наша боль.** В CLAUDE.md записано: «большой план перегружает контекст воркера → плохой результат. Хотим дробить на маленькие задачи с AC». `to-issues` — это и есть готовая дисциплина дробления. Причём ключевые две вещи, которых у нас нет как формализованного правила:
1. **Вертикальные слайсы, а не горизонтальные.** Это критично для нашей модели: воркер, получивший вертикальный слайс, может довести его до demoable-состояния и самопроверить по AC — не завися от других воркеров, которые «делают свой слой». Горизонтальные слайсы (один воркер — schema, другой — API) создают жёсткие зависимости и merge-конфликты (см. наш git-workflow «two workers editing same files = conflict»).
2. **Acceptance criteria = механизм самопроверки воркера.** Воркер закрывает задачу, только когда все AC ✅. Это снижает overhead (не бегает к оркестратору «а что дальше») — прямо по нашему принципу AI Efficiency.

**Как ложится на Orchestra.**
```
Оркестратор получает большой план (или full-cycle выдал план)
  → применяет дисциплину to-issues → N вертикальных слайсов с AC + blocked-by
  → task_create() на каждый слайс (AC → в description, blocked-by → priority/порядок)
  → spawn_worker() на каждый НЕзаблокированный слайс, в чистом контексте
  → воркер сверяется с AC, закрывает → merge_worker → следующий слайс
```
`blocked-by` идеально маппится на наш порядок спавна: сначала спавним слайсы без блокеров, зависимые — после merge блокера.

**Куда интегрировать.** Два варианта (см. раздел «Рекомендация»):
- как **скилл** `to-issues` на роль `orchestrator` (и будущий `super-full-cycle`);
- ИЛИ как **модуль** `task-splitting.md` в prompt_layers оркестратора (мы уже так дробим оркестрацию на модули: orchestration/task-management/…).

Для super-full-cycle это **Phase 2 (PLAN)**: full-cycle выдаёт план → оркестратор дробит его через to-issues на тикеты с AC → раздаёт воркерам. Именно то, что описано в задаче.

**Адаптация под нас (обязательно):**
- Выкинуть привязку к GitHub/Linear issue-tracker — у нас свой Task Manager (`task_create`). AC → в `description`, blocked-by → порядок спавна.
- «Publish with ready-for-agent label» → у нас = `task_create(status=..., assignee=...)`.
- «Quiz the user» → у нас оркестратор либо сам решает гранулярность (determinism!), либо в super-full-cycle это гейт с аппрувом (как сейчас Research/Plan гейты).

---

### 🟢 2. handoff

**Что даёт.** Сжимает текущий разговор в markdown-handoff (+ секция «suggested skills»), чтобы свежий агент продолжил без потери контекста. Правила: не дублировать то что уже в PRD/ADR/issue/commit (ссылаться по пути), редактить секреты, писать в temp-директорию.

**Почему нам.** У нас уже есть `compact_worker` (суммаризация + reset session) и pre-compact auto-save для оркестраторов. Но `handoff` — это **другой паттерн**: не «сжать и продолжить в той же сессии», а «форкнуть в свежую сессию с чистым контекстом, сохранив мысль». Это ровно то, что делает наш оркестратор, когда воркер упёрся в контекст и надо перезапустить его на остатке задачи. Формализованный handoff-документ («что сделано / что осталось / suggested next steps») улучшит наши WIP-репорты и передачу между воркерами.

**Куда.** Глобально + как усиление нашего WIP-report-format / pre-compact модуля. Низкий-средний приоритет (у нас частично покрыто compact + memory).

---

### 🟡 3. to-prd

**Что даёт.** Синтезирует текущий разговор в PRD по чёткому шаблону (Problem / Solution / User Stories / Implementation Decisions / Testing Decisions / Out of Scope). Без интервью — просто структурирует уже обсуждённое. Важная деталь: **«seams»** — где тестировать фичу, «чем меньше seam'ов, тем лучше, идеал — один».

**Почему нам.** Наш full-cycle уже пишет план в `docs/tasks/<id>/`. Шаблон to-prd — хороший **стандарт структуры плана**, особенно секции User Stories (для проверки полноты) и Out of Scope (борьба со scope creep — наш принцип «surgical changes»). Не самостоятельный скилл, а шаблон для full-cycle Phase 2.

**Куда.** Взять шаблон в prompt full-cycle (роль уже пишет план). 🟡 адаптировать, не копировать.

---

### 🟡 4. code-review (двухосевой)

**Что даёт.** Ревьюит diff двумя **параллельными сабагентами**, чтобы не загрязнять контексты:
- **Standards** — соответствие документированным стандартам репы + baseline из 12 code-смеллов Фаулера (Mysterious Name, Duplicated Code, Feature Envy, Shotgun Surgery, Speculative Generality…);
- **Spec** — реализует ли diff то, что просил issue/PRD (missing / scope-creep / wrong impl).

Разделение осей — чтобы одна не маскировала другую.

**Почему нам.** У нас есть `codex-debate` (cross-LLM ревью через Codex/GPT-5.5). code-review mattpocock — **ортогонален**: он про *встроенную* дисциплину ревью силами самих сабагентов Claude, с явным чеклистом смеллов и разделением «код правильный» vs «код делает что просили». Наш principle «adversarial self-review» из CLAUDE.md — ровно про это. Спарринг: **Spec-ось** особенно ценна в нашей модели, где воркер легко «сделал не то что в тикете» (проверка diff против AC тикета!).

**Куда.** 🟡 Взять **чеклист смеллов + Spec-vs-Standards разделение** в worker/full-cycle code-quality блок. Не тащить механику «два сабагента» — у нас для второго мнения есть Codex.

---

### 🟡 5. diagnosing-bugs

**Что даёт.** 6 фаз, но суть в Phase 1: **не теоретизируй, пока нет tight red-capable feedback loop** — одной команды (тест/curl/скрипт), которая УЖЕ падает на этом баге. «Build the right feedback loop, and the bug is 90% fixed». Дальше: reproduce+minimise → 3-5 ранжированных falsifiable гипотез → инструментирование (тегированные `[DEBUG-xxx]` логи) → фикс + regression-тест → post-mortem.

**Почему нам.** Прямо ложится на наш принцип «Fail loud, fail fast» и на будущую bug-роль. У нас в CLAUDE.md есть «Codex как напарник при баге», но нет формализованного цикла диагностики. Этот скилл — лучший из виденных мной по дисциплине дебага.

**Куда.** 🟡 Кандидат в отдельную роль `debugger` ИЛИ модуль для worker. Средний приоритет.

---

### 🟡 6. wayfinder (in-progress) — альтернатива to-issues для «туманного» скоупа

**Что даёт.** Когда работа огромна И в тумане (маршрут к плану ещё не виден): строит **карту** investigation-тикетов на трекере (research/prototype/grilling/task), резолвит по одному, каждый резолв «рассеивает туман» и рождает новые тикеты. «Fog of war»: не чарти то, что ещё не видно. Каждый тикет ≈ одна 100k-токен агент-сессия.

**Почему интересно.** Это **промежуточное звено между full-cycle (research) и to-issues (plan→tickets)**. to-issues предполагает, что план УЖЕ есть. wayfinder — для случая «идея настолько большая и мутная, что даже план нельзя составить за раз». В нашей модели это = многосессионная работа sub-orchestrator'а, где каждый investigation-тикет = отдельный researcher/experimenter воркер. Очень близко к нашему pipeline `tasks-pm` (Хаб→ПМ→аналитик/кодер/тестер).

**Осторожно:** in-progress (сам автор не довёл), сильно завязан на issue-tracker. Не тащить as-is. Но **паттерн «fog + investigation-тикеты по одному» стоит держать в уме для super-full-cycle** на очень больших скоупах.

**Куда.** 🟡 Идея для super-full-cycle / sub-orchestrator при foggy-скоупе. Низкий приоритет, наблюдать.

---

## /grill-me: наш vs mattpocock

**Их версия** (`productivity/grill-me` + `grilling`): минималистичная. `grill-me` = одна строка «Run a /grilling session». `grilling` = «интервьюируй relentlessly, по одному вопросу за раз (несколько вопросов = bewildering), на каждый — рекомендованный ответ, иди по веткам дерева решений, если ответ можно найти в коде — иди в код».

**Наш версия** (`~/.claude/skills/grill-me`): существенно **богаче и научно-обоснованнее** — 5 фреймворков (Pre-Mortem по Klein/Wharton, Socratic 6 типов, Assumption Mapping по Bland&Osterwalder, 5 Whys, Red Team), фазы (Silent Analysis → Pre-Mortem → Structured Grill 10 вопросов → 5 Whys deep dive), категории (unit-экономика, moat, масштаб…), правило «каждый вопрос ссылается на конкретный факт/документ».

**Вердикт:** наш **лучше** для бизнес/продукт/план-прожарки. НЕ заменять. 🔴 их grill-me не тащить.

**Единственное что стоит позаимствовать** — явное правило из их `grilling`:
> «Ask questions **one at a time**, waiting for feedback. Asking multiple at once is bewildering. If a question can be answered by exploring the codebase, **explore instead of asking**.»

У нас Phase 3 = «10 вопросов пачкой». Для интерактивной прожарки «по одному» часто лучше (юзер не тонет). Стоит добавить в наш grill-me режим-развилку: пачка (когда юзер хочет обзор) vs по одному (глубокая проработка). Мелкое улучшение, не блокер.

---

## Дубли с тем, что у нас уже есть

| Наш скилл/фича | Дубль у mattpocock | Действие |
|---|---|---|
| роль `researcher` (search→verify→synthesize) | engineering/**research** | 🔴 не тащить — у нас полнее (counter-evidence, confidence levels) |
| роль `worker`/`full-cycle` (implement) | engineering/**implement** | 🔴 не тащить — их 5 строк, наши роли детальнее |
| `codex-debate` (cross-LLM ревью) | engineering/code-review | частично — взять чеклист смеллов, не механику |
| наш `grill-me` (5 фреймворков) | productivity/grill-me | 🔴 наш богаче |
| `quick-skill` / `skill-creator` | productivity/writing-great-skills | 🔴 не тащить |
| `experimenter` (hypothesis→experiment) | engineering/prototype | частично — prototype уже, наш experimenter шире |
| Task Manager + YouGile sync | engineering/triage, setup-matt-pocock-skills | 🔴 не тащить — у нас своя таск-система |
| `html-artifacts` | improve-codebase-architecture (HTML-отчёт) | 🔴 не тащить весь скилл |

**Итог по дублям:** прямых 1:1 дублей, которые надо тащить, НЕТ. `research` и `implement` — концептуальные дубли наших ролей, но наши реализации сильнее. Не плодить.

---

## Механика интеграции

### Формат совместим?
**Да, полностью.** Наш загрузчик (`app/prompting.py:180 inject_skills_to_worktree`) просто копирует `skills/<name>.md` → `worktree/.claude/skills/<name>/SKILL.md` как нативный Claude CLI скилл. mattpocock SKILL.md — это **и есть** нативные Claude CLI скиллы с frontmatter (`name`, `description`, `disable-model-invocation`, `argument-hint`). Совместимость 100%.

Нюансы frontmatter:
- **Наши** скиллы имеют лишние ключи `roles: [all]`, `integrations: [web-search]` — Claude CLI их игнорирует, это наша мета для pipeline. У mattpocock их нет — не проблема.
- **Их** ключ `disable-model-invocation: true` — это нативный Claude CLI ключ (скилл только по явному вызову юзером, агент сам не дёрнет). У нас его нет ни на одном скилле. Для `to-issues` он **нужен** (не хотим чтобы воркер случайно сам начал дробить) — просто оставить как есть при копировании.
- Их скиллы ссылаются на sub-файлы (`tests.md`, `AGENT-BRIEF.md`, `template.sh`, `DEEPENING.md`) — при интеграции надо тащить всю директорию скилла, а не только SKILL.md. Наш загрузчик копирует **только SKILL.md** (`cp SKILL.md`). Для скиллов с доп-файлами (code-review, tdd, diagnosing-bugs, wizard) это **ограничение** — либо инлайнить всё в один SKILL.md, либо доработать загрузчик на копирование директории. Для `to-issues`/`handoff`/`to-prd` это неважно — они одно-файловые.

### Два способа (по нашей архитектуре)
1. **pipeline.yaml `skills: [...]` на роль** — скилл инъектится только этой роли в worktree. Подходит для ролевых: `to-issues` → orchestrator, `code-review`-чеклист → worker.
2. **Модуль в `prompt_layers` / `modules:`** — если это дисциплина, а не отдельно-вызываемый скилл. У нас так сделаны orchestration/task-management. Подходит для «дробления плана» как встроенного поведения оркестратора.
3. **Глобально `~/.claude/skills/`** — для кросс-проектных (handoff, grill-me).

**Мой выбор для to-issues:** скилл на роль orchestrator (`disable-model-invocation: true`, вызывается явно оркестратором когда получил большой план) + позже завести в super-full-cycle Phase 2. Не модуль — потому что дробление это дискретный акт, а не фоновое поведение, и determinism-принцип требует «оркестратор явно решает: план большой → зову to-issues».

---

## Рекомендация: что интегрировать в default пайплайн

**Приоритет 1 (делать):**
1. **`to-issues`** → адаптировать под наш Task Manager, завести скиллом на роль `orchestrator`. Ключевое: вертикальные слайсы + AC + blocked-by. Это Phase 2 будущего super-full-cycle. **Решает заявленную боль напрямую.**

**Приоритет 2 (стоит):**
2. **`to-prd` шаблон** → в prompt full-cycle как стандарт структуры плана (User Stories + Out of Scope особенно).
3. **`code-review` — чеклист 12 смеллов Фаулера + Spec-vs-Standards** → в code-quality блок worker/full-cycle. Spec-ось = «diff соответствует AC тикета».
4. **`handoff`** → усилить наш WIP-report / pre-compact паттерн формализованным handoff-документом.

**Приоритет 3 (наблюдать / опционально):**
5. **`diagnosing-bugs`** → если заведём роль `debugger`, взять как основу (Phase 1 feedback loop — золото).
6. **`wayfinder`-паттерн** → держать в уме для super-full-cycle на foggy-скоупах (fog + investigation-тикеты по одному).
7. **`grilling` правило «один вопрос за раз»** → опция в наш grill-me.

**Не трогать:** research, implement, triage, ask-matt, setup-*, teach, writing-great-skills, personal/*, deprecated/*, misc/*, caveman, zoom-out (последние два вообще удалены автором).

---

## /to-tickets — отдельный раздел (как решает нашу боль)

**Боль (из CLAUDE.md):** «большой план перегружает контекст воркера → плохой результат. Хотим дробить на маленькие задачи с AC».

**Как `to-issues` её закрывает — три механизма:**

1. **Дробление на независимые единицы.** План режется так, что каждый кусок берётся отдельно и не тянет за собой весь контекст плана. Воркер видит только свой тикет — контекст чистый, «smart zone» (~120k) не забита. Это ровно наш паттерн «fresh session per issue».

2. **Вертикальные слайсы вместо горизонтальных.** Каждый тикет — тонкий срез СКВОЗЬ все слои, demoable сам по себе. Для нас критично: воркер доводит слайс до готовности и самопроверяет, не завися от параллельных воркеров → меньше merge-конфликтов (наш git-workflow: «different directories = safe parallel», а вертикальный слайс держит изменения локально в фиче, не размазывает по слоям между воркерами).

3. **Acceptance criteria = контракт самопроверки.** Воркер закрывает тикет только когда все AC ✅. Убирает главный failure mode нашей модели — «воркер сделал не то, что в задаче» (наш principle determinism + AI efficiency «не бегай к оркестратору»). AC — это то, против чего code-review Spec-ось проверяет diff.

**Маппинг на Orchestra (конкретно):**
```
big plan (от юзера или full-cycle Phase-Plan)
  → orchestrator вызывает /to-issues
  → выдаёт слайсы: {title, what-to-build (end-to-end), AC[], blocked-by[]}
  → на каждый слайс: task_create(title, description=what-to-build+AC, priority=по blocked-by)
  → spawn_worker() на слайсы без блокеров (чистый контекст)
  → воркер: реализует → сверяет AC → commit → DONE
  → merge_worker(next_task_id=следующий разблокированный слайс)
```

**Для super-full-cycle** (задача упоминает «скоро super-full-cycle»): это естественная **Phase 2 (PLAN)**:
- Phase 1 RESEARCH (как в full-cycle) → гейт аппрув
- **Phase 2 PLAN: full-cycle пишет план (to-prd шаблон) → сразу дробит через to-issues на тикеты с AC** → гейт аппрув
- Phase 3 IMPLEMENT: тикеты раздаются воркерам (или сам full-cycle идёт по ним по одному в чистых под-контекстах)

Это устраняет ровно тот failure mode, ради которого заводится super-full-cycle: один агент с гигантским планом в контексте деградирует. Дробление на тикеты с AC = каждый шаг в чистом окне + встроенная самопроверка.

**Что адаптировать при интеграции:** убрать GitHub/Linear-специфику (→ наш Task Manager), «quiz user» сделать либо авто-решением оркестратора (determinism), либо гейтом аппрува в super-full-cycle. Шаблон issue (What to build / AC / Blocked by) взять почти дословно — он хорош.

---

## Counter-evidence / риски

- **Не всё, что работает у mattpocock (один человек, один Claude Code), переносится на мульти-агента.** Их «context hygiene» — ручное переключение сессий человеком. У нас это автоматизировано иначе (spawn/merge/compact). Не копировать механику — только дисциплины.
- **`disable-model-invocation` и sub-файлы скиллов** — наш загрузчик копирует только SKILL.md. Скиллы с доп-файлами (tdd/code-review/diagnosing-bugs) потребуют либо инлайна, либо доработки `inject_skills_to_worktree` на копирование директории. Для to-issues/handoff/to-prd не актуально (одно-файловые).
- **to-issues «quiz the user» ломает наш determinism-принцип**, если оставить как есть (агент интерактивно спрашивает гранулярность). Надо заменить на авто-решение или явный гейт. Иначе оркестратор зависнет в интерактиве.
- **wayfinder in-progress** — сам автор не довёл, сильно tracker-зависим. Только как идея, не код.
- **caveman/zoom-out удалены автором** — оценить их SKILL.md не могу (нет в репе), сужу только по одной строке CHANGELOG. Если юзеру они реально полезны — это его локальные форки, к текущей репе отношения не имеют.

## Confidence

**HIGH** по фактам о скиллах — читал SKILL.md напрямую из репы (`gh api`, ветка main, 2026-07-03), не пересказы. Роутер `ask-matt` дал целостную картину методологии. Формат-совместимость проверил по нашему `app/prompting.py`.

**MEDIUM** по рекомендациям интеграции — это оценочные суждения о применимости к нашей архитектуре; финальное решение (скилл vs модуль, приоритеты) за оркестратором/юзером. По caveman/zoom-out — **LOW** (нет исходников, только CHANGELOG).

## Sources

1. https://github.com/mattpocock/skills — репозиторий, ветка `main` (accessed 2026-07-03 via `gh api`)
2. `skills/engineering/ask-matt/SKILL.md` — роутер / карта методологии (main flow)
3. `skills/engineering/to-issues/SKILL.md` — vertical slices + AC + blocked-by (sha 333f1ee)
4. `skills/engineering/to-prd/SKILL.md` — PRD шаблон
5. `skills/productivity/handoff/SKILL.md`, `grill-me/SKILL.md`, `grilling/SKILL.md`
6. `skills/engineering/{code-review,tdd,diagnosing-bugs,codebase-design,triage,implement,research}/SKILL.md`
7. `skills/in-progress/{wayfinder,wizard,loop-me}/SKILL.md`
8. `CHANGELOG.md` коммит `47bde84` — удаление caveman + zoom-out
9. `README.md`, `CLAUDE.md` репы — философия «Skills For Real Engineers», 4 failure modes
10. `app/prompting.py:180` (наш) — механика инъекции скиллов в worktree
11. `pipelines/default/pipeline.yaml` (наш) — текущие роли и их skills/modules
12. `~/.claude/skills/grill-me/SKILL.md` (наш) — для сравнения grill-me

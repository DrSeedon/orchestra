# #418 — Проекты, видимое ожидание и сторож застоя

Дата среза: 2026-08-30 UTC. Фаза: research-only; архитектура не выбрана и реализация не начата.

## Короткий ответ

`scope` и проект — не одно и то же.

- `scope` сейчас является техническим адресом одной agent-сессии: строка пути попадает в
  `ORCHESTRA_SCOPE`, определяет видимость агентов, MCP-контекст, task lookup и часть runtime-
  lifecycle. Одна сессия имеет ровно один `scope`.
- Сущность проекта уже наполовину существует как `tm_projects`: у задачи есть обязательный
  `project_id`, а у проекта — `id`, имя, префикс и уникальный `scope`. Не хватает владельца,
  явного состояния ожидания и достоверной связи worker/task с целевым проектом.
- Поэтому отдельную вторую таблицу проектов создавать не надо. Рекомендуемый вариант для
  обсуждения — сделать существующий `tm_projects` человеческим owner проекта, оставить `scope`
  техническим и добавить отношение «проект → ровно один orchestrator». Один orchestrator может
  стоять владельцем в нескольких строках проектов.
- Чистая надстройка над `scope` годится только для read-only прототипа доски. Она не обеспечивает
  уникального владельца, не умеет честно отнести cross-repo worker/task к целевому проекту и
  нарисует текущую ложь task lifecycle.
- Предлагаемый порог застоя — **elapsed time ≥30 минут от неизменившегося `actionable_since`**.
  При polling раз в пять минут это шесть полных интервалов и первое обнаружение через 30–35 минут,
  но только для явно actionable-состояния и с одним durable wake на `stall_generation`. Порог без
  исправления данных и edge-дедупликации неприемлем.
- Codex `goal` **существует**: это stable `/goal`, привязанный к активному chat/thread и
  сохраняющий objective между turns. Он полезен как модель self-continuation, но не заменяет
  проект, ownership, task board или project-level waiting state. [1][2]

## 1. Вопрос и критерий решения

### Контекст

Один orchestrator должен вести несколько из пяти пользовательских проектов; каждый проект должен
иметь ровно одного владельца. Пользователю нужно отдельное окно со сводной доской и видимым
вопросом, когда работа ждёт его решения. Текущий dashboard агентов остаётся как есть.

### Изменение под проверкой

Сравниваются:

1. **(а) `scope` + человеческая read-only надстройка** без новой domain identity;
2. **(б) отдельная domain identity проекта**, причём не новая дублирующая таблица, а доведение
   существующего `tm_projects` до authoritative project owner при сохранении `scope` как runtime-
   маршрута.

### Baseline

Сейчас project identity выводится из `scope`, а cross-repo spawn меняет только worktree/repository;
task и session lifecycle остаются в проекте родительского `scope`.

### Измеримый исход

Вариант проходит, только если одновременно:

1. одна project identity допускает не более одного orchestrator-owner, а один owner — несколько
   проектов;
2. task и worker однозначно относятся к целевому проекту, включая cross-repo spawn;
3. доска не показывает мёртвую binding как «в работе»;
4. `waiting for decision` переживает restart и подавляет watchdog, не тегая пользователя;
5. watchdog будит orchestrator не чаще одного раза на одно неизменившееся состояние застоя.

## 2. Гипотезы и фальсификаторы

### H1 — `scope` достаточно

**Гипотеза:** `scope` уже является project identity; достаточно подписать пути человеческими
именами и агрегировать tasks/sessions на новой странице.

**Фальсификатор:** один agent должен владеть несколькими проектами или cross-repo worker должен
получить binding/task целевого проекта, но единственный process `ORCHESTRA_SCOPE` и scoped binding/
default lookup не могут представить это без второй оси identity. Явные `project` branches у части
task operations обходят default selector, но не дают owner membership и не чинят session binding.

**Вердикт:** **REFUTED как полное решение**, допустим только read-only prototype. Фальсификатор
срабатывает в текущем коде: `spawn_worker` сохраняет `SCOPE` родителя, а task resolver выбирает
проект только через session scope.

### H2 — нужна совершенно новая таблица `projects`

**Гипотеза:** `tm_projects` — лишь служебный task namespace; human project нужно создать рядом.

**Фальсификатор:** `tm_projects` уже имеет уникальный scope и является обязательным FK-owner всех
задач; новая таблица создаст две project identity и reconciliation между ними.

**Вердикт:** **REFUTED.** Нужна эволюция `tm_projects`, а не второй project registry.

### H3 — `tm_projects` становится domain project, `scope` остаётся runtime key

**Гипотеза:** явный owner и явный project context закрывают cardinality и isolation, не превращая
`ORCHESTRA_SCOPE` в список и не ломая технический runtime-маршрут.

**Фальсификатор:** если все task/session/merge consumers всё равно требуют заменять один scope на
список scopes, такой split не дешевле полного варианта (б).

**Вердикт:** **LIKELY, требует решения пользователя и Phase 2.** Код показывает достижимый seam,
но точная форма session project context (`project_id` против stable task record id) ещё не выбрана.

## 3. Что такое `scope` сейчас

### 3.1 Runtime identity

- `AgentManager._make_mcp_config` записывает единственную строку `ORCHESTRA_SCOPE` в env MCP-
  процесса (`app/manager.py:417-430`).
- MCP читает её один раз при старте процесса: `SCOPE = os.environ.get("ORCHESTRA_SCOPE", "")`
  (`app/mcp_stdio.py:40`).
- `sessions` хранит `scope TEXT NOT NULL`; единственное ограничение identity —
  `UNIQUE(name, scope)`, а не один orchestrator на scope (`app/db.py:53-77`).
- Смена scope отключает backend, перестраивает MCP config и лениво reconnect'ит его; это не
  multi-scope, а перенос одной сессии (`app/manager.py:1255-1322`).

**CONFIRMED — evidence tier 2 (primary source code).**

### 3.2 Scope сейчас одновременно выполняет слишком много ролей

1. **Agent visibility / parent lookup.** Worker без явного родителя получает первого
   orchestrator в том же scope (`app/manager.py:729-739,1957-1961`). При двух orchestrator порядок
   in-memory iteration становится скрытым выбором владельца.
2. **Task default selector и binding boundary.** `resolve_scoped_task_identity()` превращает
   session scope в `tm_projects.id` и только затем разрешает `#N` (`app/tm.py:605-634`). Но это
   **не универсальная authorization boundary**: `task_create` и `task_update` принимают явный
   `project`, а обычные (не acceptance-oracle) write branches разрешают его без owner check
   (`app/mcp_stdio.py:2762-2764,2823-2824`; `app/routes/tm.py:48-59,113-136,219-239`).
3. **Task binding.** `bind_task_to_session()` требует равенства session scope и scope запроса,
   после чего ставит task `in_progress` (`app/tm.py:685-729`).
4. **MCP defaults.** `task_create/list/get/update` по умолчанию передают `SCOPE`
   (`app/mcp_stdio.py:2740-2853`).
5. **Dashboard aggregate.** `/api/orchestrators` вычисляет `any_running/any_waiting` по равенству
   scope (`app/routes/system.py:2178-2202`).

Это объясняет цену полного `scope → scopes[]`. Число **32** дано task owner как результат прежнего
аудита и зафиксировано в решении пользователя 28.08 (`CLAUDE.md:9`, commit `98dd43c8`), но raw
перечня/команды в доступных артефактах нет. Поэтому #418 использует 32 как **supplied planning
estimate, не новый подтверждённый замер**; Phase 2 обязана заново перечислить seam перед tickets.
Новое требование даёт другой выход — не расширять scope, а отделить от него project ownership.

**CONFIRMED для current scope semantics; UNCERTAIN для точного знаменателя 32** (recorded decision
есть, воспроизводимого inventory нет).

### 3.3 Что уже является проектом

`tm_projects` уже содержит project identity и unique mappings:

```text
tm_projects: id PK, name, prefix UNIQUE, scope UNIQUE, yougile_*, created_at
tm_tasks: project_id NOT NULL REFERENCES tm_projects(id)
```

Источник: `app/db.py:375-411`. `task_create` уже принимает явный project id/scope, а task numbers
уникальны внутри `project_id` (`app/tm.py:162-177,198-239,1023-1065`).

Пробел — ownership отсутствует. Прямой live-срез:

```sql
SELECT COUNT(*) projects, COUNT(DISTINCT scope) project_scopes,
       SUM(scope IS NULL OR TRIM(scope)='') projects_without_scope
FROM tm_projects;
```

```text
projects=19  project_scopes=13  projects_without_scope=6
tasks=732    task_projects=19
session_scopes=21  live_scopes=20  resumable_scopes=18
```

Команда: `sqlite3 -readonly /mnt/data/Projects/Python/orchestra/data/orchestra.db ...`,
2026-08-30 05:53–06:08 UTC. Шесть project rows без scope и case/path aliases (`University`/
`university`, absolute-path ids) показывают: текущий registry годится как migration source, но не
как готовая human board без normalization.

**CONFIRMED — tier 1 (live SQLite measurement).**

### 3.4 Cross-repo portfolio сейчас

`spawn_worker` делает `scope = SCOPE or repo_path`, а затем отдельно передаёт `cwd/repo_path`
(`app/mcp_stdio.py:932-967`). Если parent agent жив, `SCOPE` непустой: worker получает scope
родителя даже при другом repository. Встроенное предупреждение прямо говорит, что tasks/numbers
остаются в проекте родителя (`app/mcp_stdio.py:920-928`).

Это рабочий технический механизм для одного редкого cross-repo ticket, но не честная project board:
место Git-worktree и task project расходятся.

**CONFIRMED — tier 2 (primary source code).**

## 4. Варианты и цена

### Вариант (а) — scope + human read-only overlay

**Что делается:** отдельная standalone-страница агрегирует `tm_projects`, `tm_tasks` и sessions по
совпадающему scope. Human name берётся из `tm_projects.name`; existing dashboard/agent list не
заменяется.

**Минимальная цена:** один read endpoint + отдельные template/JS/CSS (четыре production surfaces)
и focused UI/API tests. Схема task/session не меняется.

**Что даёт:** быстро показывает текущую картину по уже однозначным 1:1 project/scope и не трогает
agent runtime.

**Что ломается или остаётся ложным:**

- один orchestrator нельзя честно показать владельцем нескольких scopes;
- уникальность owner не принуждается — две разные name в одном scope законны;
- cross-repo task остаётся в project родительского scope;
- durable waiting/question хранить негде;
- board принимает stale `in_progress` за работу;
- `/api/projects` нельзя переиспользовать: сейчас это filesystem picker для create/change-scope UI,
  не task project registry (`app/routes/system.py:141-158`, consumers
  `app/static/js/app.js:1646-1670,2166-2180`).

**Итог:** дешёвый diagnostic prototype, но не выполнение заказанных инвариантов.

### Вариант (б) — domain project поверх существующего `tm_projects` (рекомендуется к обсуждению)

**Identity:** `tm_projects` становится единственным project owner. `scope` остаётся runtime route,
а не human identity.

**Новые durable relations, минимально необходимые по исследованию:**

1. `tm_projects.owner_session_id` (или отдельный one-row-per-project owner record): одна строка
   проекта содержит не более одного owner; одинаковый owner id разрешён у нескольких projects.
2. Явный target project/stable task identity у worker session. Точная форма — решение Phase 2:
   `sessions.project_id` либо stable task DB/canonical id, который уже несёт project.
3. Durable wait record: `project_id`, optional task stable id, owner session id, question,
   `opened_at`, `resolved_at`, status.
4. Durable watchdog generation/receipt, чтобы polling не означал повторный model wake каждые пять
   минут.

**Enforcement seam:** сейчас `_create_session_locked()` блокирует только совпадающие
`(name, scope)` (`app/manager.py:652-670`), а роль orchestrator определяется позже
(`app/manager.py:698-700`). Code guard может стоять сразу после определения `is_orch` и до prompt/
worktree side effects; настоящий invariant должен фиксироваться atomic owner compare-and-swap при
публикации session. `change_orchestrator_scope()` тоже обязан либо сохранить project ownership,
либо явно передать его — сейчас он меняет только scope/cwd и связанные runtime rows.

**Цена:** schema migration + обязательный аудит известных 32 seam, где scope сейчас означает
project. Не каждую точку обязательно переписывать, если selected stable task id позволяет оставить
runtime scope, но продавать реализацию как «меньше 32» до Phase 2 нельзя. Минимальный production
контур затрагивает как минимум:

- `app/db.py` — owner/project/wait/watchdog persistence;
- `app/tm.py` — project resolution, binding, lifecycle reconciliation;
- `app/manager.py` — owner uniqueness, spawn/restore/parent relation;
- `app/mcp_stdio.py` — target-project inference и единственный wait tool;
- `app/routes/sessions.py`, `app/routes/tm.py`, `app/merge_operations.py` — create/send/switch/
  merge identity и authorization;
- новый board aggregate + standalone view + scheduler hook;
- `app/ia/runtime.py:451-508,544-560` и canonical task/knowledge migration — IA уже хранит
  `scope → canonical_project_id` и отдельно remap'ит legacy `tm_projects`; смена semantics без
  versioned registry migration изменит canonical identity/authorization;
- миграционные и behavioral tests.

**Что даёт:** все пять acceptance outcomes из §1; scope path можно переименовывать/переносить без
смены human project identity; один owner естественно получает несколько project rows.

**Главный риск:** добавить owner column, но оставить хотя бы один scoped mutation, который принимает
caller-supplied explicit project без проверки ownership. `task_create/list/get/update` уже имеют
explicit `project` branch; authorization должен проверяться на всех write paths, не только на
acceptance oracle.

### Не предлагать: совершенно новая таблица рядом с `tm_projects`

Она потребует join/reconciliation между двумя project registries и не даёт свойства, которого
нельзя добавить существующей таблице. Для пяти проектов это лишняя архитектура «на вырост».

## 5. Seedon: как появился второй orchestrator и как разрешить долг

### Причина

Два разных имени проходят текущие guards:

- DB запрещает только одинаковое `(name, scope)` (`app/db.py:76`);
- spawn lock также keyed by `(scope, name)` (`app/manager.py:608-611`);
- `_create_session_locked` ищет только `get_session_by_name(name, scope)`
  (`app/manager.py:666-670`).

Поэтому `seedon-orchestrator` и `dev-lead` в одном scope никогда не конфликтовали. Отдельного
project owner record нет.

### Live facts

```text
seedon-orchestrator  role=orchestrator  parent_name=''                    created=2026-05-09
dev-lead             role=orchestrator  parent_name=seedon-orchestrator   created=2026-05-31 task_id=35
```

Оба `idle`, scope `/mnt/data/Projects/Python/seedon`. `dev-lead` фактически создавался как child:
у него заполнен `parent_name`, а task #35 давно `done`. Последний substantive turn `dev-lead`
03.08 закончился явным ожиданием решения по push для task #203; сама #203 сейчас `new`. У него шесть
неархивных idle children; единственный child с task binding — `infra`, task #113 уже `done`.

Команды: joins `sessions ↔ tm_tasks ↔ logs` по exact scope/name; результат снят из live read-only DB
2026-08-30.

### Предложение ручного разрешения (не выполнено)

1. Оставить owner **`seedon-orchestrator`**: он старше, не имеет parent и совпадает с project
   boundary; `dev-lead` уже ссылается на него как на parent.
2. До архивации `dev-lead` перенести его открытый decision про #203 в новый wait record и доставить
   parent'у как handoff.
3. Перепривязать шесть live idle children к `seedon-orchestrator` **атомарно по обоим полям**:
   `parent_id=<seedon owner session id>` и `parent_name='seedon-orchestrator'`. Обновить те же поля
   у loaded runtime objects либо force reconnect; только ID не меняет current owner rendering/
   child enumeration, только name создаёт identity drift (`app/manager.py:1360-1381`,
   `app/mcp_stdio.py:1643-1671`).
4. Архивировать, не удалять, `dev-lead`: transcript сохранится, а второй owner исчезнет.

Перед commit миграции нужны два read-back guards: все шесть exact child session ids имеют одинаковые
новые `parent_id/parent_name`, и ни одна unfinished task не bound к `dev-lead`/его children. После
runtime refresh `list_agents` должен показать их под `seedon-orchestrator`; любое расхождение
отменяет архивацию `dev-lead`.

По текущим bindings это не бросает незавершённую child task: #35 и #113 `done`, остальные live
children не имеют task id. Но `feat-remove-ip-api` и другие unbound idle sessions всё равно нужно
сохранить/reparent, а не kill. Этот один случай — migration debt, не аргумент против isolation.

**CONFIRMED facts / LIKELY migration procedure.** Procedure требует user approval в Phase 2/3.

## 6. Почему текущая task board соврёт

Постановка упоминала восемь старых `in_progress`. Live-срез уже другой. Следующие числа заморожены
как narrative snapshot в **2026-08-30T06:28:16.825Z**; база живая и позднее естественно изменится:

```text
status       tasks  projects
backlog          3         1
new            183        18
in_progress     79         8
done           444        10
paid             2         1
cancelled        22         4
```

Разбор 79 `in_progress` по exact rule `LEFT JOIN sessions ON sessions.id=worker_session_id`, где
NULL join становится `NO_BINDING`, а остальные rows группируются по дословному `sessions.status`:

```text
worker_state  tasks  projects
idle             31         3
archived          26         5
NO_BINDING        18         6
running            3         2
waiting            1         1
```

Полный SQL:

```sql
SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now') AS snapshot_utc;
WITH ip AS (
  SELECT t.project_id, s.status AS worker_status
  FROM tm_tasks t LEFT JOIN sessions s ON s.id=t.worker_session_id
  WHERE t.status='in_progress'
)
SELECT COALESCE(worker_status,'NO_BINDING') AS worker_state,
       COUNT(*) AS tasks, COUNT(DISTINCT project_id) AS projects
FROM ip GROUP BY COALESCE(worker_status,'NO_BINDING') ORDER BY tasks DESC;

SELECT status, COUNT(*) AS tasks, COUNT(DISTINCT project_id) AS projects
FROM tm_tasks GROUP BY status ORDER BY status;
```

То есть 44 task не имеют live binding (`archived` + `NO_BINDING`); ещё 31 привязана к idle worker,
где без durable project wait невозможно отличить approval gate, забытый task и законную паузу.
`waiting` считается отдельным живым background-work состоянием, а не idle/no-binding.

Текущий код уже частично чинит будущее: с commit `6f874ace` от 24.08
`release_session_task_binding()` в одной transaction с archive выбирает живого наследника либо
переводит orphaned `in_progress → new` (`app/tm.py:906-938`, caller
`app/db.py:1588-1599`). Старые records не были backfilled, а idle ambiguity этим seam не решается.

### Чинится ли тем же механизмом

**Частично.** Нужен один project-lifecycle owner, но две разные операции:

1. **One-time reconciliation до включения watchdog.** 44 no-live bindings можно механически
   пометить migration debt/requeue после fresh snapshot check. 31 idle-bound нельзя массово
   менять: сначала owner должен решить, это work, wait или закрытый долг.
2. **Постоянный invariant.** Spawn/bind/archive/merge и `project_wait` меняют task/project state
   атомарно. Board показывает anomaly отдельно и никогда не выводит orphan binding как active work.

Watchdog не должен сам чинить или закрывать задачи: он consumer project truth, не её owner.

## 7. Доска

### Окно

Standalone route/window, не replacement dashboard. Существующий dashboard, agent list и chat не
меняются. На одном экране — пять project swimlanes; каждая строка показывает owner, последнюю
meaningful activity и cards в колонках.

Рекомендуемый поток слева направо:

1. **Планируется** — `backlog/new`; это не означает standing approval или готовность к запуску.
2. **В работе** — `in_progress` с live binding; badge `running/idle`, agent и age.
3. **Ждёт решения** — durable open wait с вопросом, временем и optional task ref.
4. **Сделано** — `done/paid`, только recent window или последние N cards; все 444 завершённых на
   одной доске не нужны.

Если пользователь хочет буквальный visual order «сделано → в работе → планируется», это UI choice,
не data model; до Phase 2 его нужно утвердить отдельно.

### Источники данных

- project/owner: нормализованный `tm_projects` + explicit owner;
- task state: canonical task state/SQLite projection, но только после reconciliation receipt;
- activity: session lifecycle and worker binding, не свободный text log;
- waiting: отдельный durable wait record;
- watchdog badge: last evaluated `stall_generation`, wake delivery receipt и следующий check.

### Card semantics

- orphan/missing owner или duplicate owner → красная **«требует миграции»**, watchdog не шлёт ping;
- `waiting` не считается stalled и никогда не тегает пользователя;
- idle-bound actionable task после 30 минут → stalled badge и один wake owner'у;
- другая работа в том же project не должна скрывать task-level anomaly, но project watchdog не
  будит owner, пока хоть одна live worker activity подтверждает, что проект движется. Anomaly всё
  равно видна на card.

## 8. Сторож застоя и порог

### Предрегистрированный predicate

Проверка каждые пять минут. Project становится eligible, только если одновременно:

1. owner ровно один;
2. есть хотя бы одна **actionable** task (не просто `new/backlog` и не open wait);
3. нет running/waiting worker или owner turn по проекту;
4. elapsed time `now - actionable_since >= 30 minutes`;
5. для текущего `stall_generation` нет accepted wake receipt.

Действие: durable internal message **orchestrator'у**, не пользователю. Транспортный retry повторяет
delivery той же wake, но не создаёт новый model ping. Новый wake возможен только после state change,
создавшего новый `stall_generation`.

### Почему 30 минут

- это шесть полных пятиминутных интервалов; при checker phase первое наблюдение eligibility может
  быть сразу, но alarm возможен только после elapsed 30 минут, фактически в диапазоне 30–35 минут;
- проблема обнаруживается в тот же час, а не через сутки;
- spam ограничивает generation receipt, не большой таймер;
- live data показывает, что увеличение threshold не исправляет ложный task state.

### Замер на наших данных

**Exact current snapshot 2026-08-30T06:30:15.888Z:** если буквально взять `in_progress` и отсутствие
`running|waiting` session в project scope, candidate шесть projects. У четырёх ровно один owner;
Seedon имеет двух и должен быть quarantined, `University` не имеет mapped owner. После ручного
разрешения Seedon было бы пять pingable projects. Поэтому initial watchdog до reconciliation должен
быть muted.

**30-day dirty-state sensitivity replay (не historical stall counter):** task status history до
canonical cutover неполна. Скрипт [watchdog_replay.py](watchdog_replay.py) back-project'ит только
нынешние `in_progress` от `created_at`; projects с owner count не равным одному исключаются; для
каждой session первый `user_message` при closed interval
парится со следующим `status LIKE 'turn ended (%'` строго по `ts`; steering не открывает второй
interval; незакрытый active/idle interval заканчивается ровно на cutoff. SQL ограничен
`start <= ts <= end`. Background-job intervals отсутствуют. Команда:

```bash
python3 docs/tasks/418/watchdog_replay.py \
  --end 2026-08-30T06:08:18.418883+00:00
```

Input — живая read-only SQLite; поэтому алгоритм воспроизводим, но exact historical input не
immutable и результат нельзя называть точной частотой. Captured output:

```text
threshold=30m   edge_triggers=176  repeated_5m_triggers=33885  projects=6
threshold=60m   edge_triggers=112  repeated_5m_triggers=33021  projects=6
threshold=360m  edge_triggers=62   repeated_5m_triggers=28554  projects=6
threshold=1440m edge_triggers=20   repeated_5m_triggers=19613  projects=5
reconstructed_intervals=3639
```

Post-review boundary controls on a four-table scratch SQLite fixture:

```text
case: task becomes actionable 25m before cutoff + two logs after cutoff
threshold=30m edge_triggers=0 repeated_5m_triggers=0 projects=0
reconstructed_intervals=0

case: one project has two non-archived orchestrator owners
threshold=30m edge_triggers=0 repeated_5m_triggers=0 projects=0
reconstructed_intervals=0
```

Первый case одновременно доказывает отсутствие подарочного post-cutoff tick и отсечение
`ts > end`; второй — owner quarantine. Scratch DB создавался в `mktemp -d` и удалён после прогона.

Это **не верхняя граница и не историческая частота настоящих stalls**: missing status transitions
и bg-work могут менять результат в обе стороны. Это только sensitivity counterexample против двух
опасных решений:

1. polling не может отправлять ping на каждом tick;
2. даже threshold 24 часа не делает лживый `in_progress` безопасным.

**Confidence порога: LIKELY.** Данные подтверждают необходимость state predicate/dedupe, но не
оптимальность именно 30 минут. После rollout нужен 14-day shadow log без model wake: candidates,
suppression reason, owner, generation; затем сравнить 15/30/60 минут до включения.

## 9. Tool gate

### Предлагается ровно один новый agent tool

`project_wait(project, question, task_ref="")`

Atomic effect:

1. требует exact `project` id (или project-qualified ref) и по immutable caller session проверяет,
   что этот project принадлежит caller; project нельзя выводить из home scope у multi-project owner;
2. validates optional task;
3. создаёт/обновляет open wait с exact question;
4. исключает соответствующую actionable generation из watchdog;
5. возвращает wait id и board-visible state.

**Как то же сделать без tool:** агенту пришлось бы самому resolve caller session + explicit project
→ owner membership →
task identity, сформировать authenticated POST/curl или Python, обеспечить compare-and-swap от
дубликата, записать question и suppression receipt. Существующий `task_update` не годится:
`in_progress/done` platform-owned, а `waiting` отсутствует в schema
(`app/db.py:387-407`, `app/mcp_stdio.py:2728-2735,2776-2792`). Это именно неочевидная multi-write
операция; tool проходит пользовательский гейт.

### Не предлагаются tools

- `project_board` / `project_status`: без него агент делает `task_list(project=...)` +
  `list_agents`; это 2 коротких вызова, а доска нужна человеку.
- `resolve_wait`: без отдельного tool wait закрывается platform lifecycle event — worker start,
  task cancel/complete либо project action после решения. Если Phase 2 докажет, что нужен ручной
  endpoint, один короткий POST не оправдывает новый agent tool.
- `assign_project_owner`: редкая admin/migration операция; UI/route достаточно.

## 10. Судьба `notify_user`

Текущий `notify_user` ничего не записывает: его вызов является log marker, который затем читает TG
bridge (`app/mcp_stdio.py:2109-2131`). Поэтому он не способен показать, какой project/task ждёт,
когда ожидание началось и закрыто ли оно.

Live usage:

```text
calls=21  sessions=4  scopes=4
first=2026-08-16T09:32:51Z  last=2026-08-25T15:00:12Z
```

Причины смешаны: incidents, reversed conclusions, completed work и approval decisions. Нельзя
безопасно переинтерпретировать старый `reason` как project wait.

**Предложение:** waiting/approval часть переносится в `project_wait` без Telegram tag. Но немедленно
удалять весь `notify_user` небезопасно: 21 live call смешивает минимум четыре taxonomy — project
decision, incident, withdrawn/reversed conclusion и plan-changing result. Выбор для обсуждения:

1. **Интегрировать (рекомендуется безопасным переходом):** existing `notify_user` временно пишет
   durable `project_event(kind='attention', reason)` и сохраняет TG marker только для трёх
   non-wait categories. Project decisions через него запрещаются и идут в `project_wait`.
2. **Удалить полностью:** пользователь явно отказывается от urgent tag для incidents/reversals;
   обычный user-facing reply/TG delivery становится единственным каналом.

После миграции 21 historical reason и принятия варианта 1 или 2 agent-facing `notify_user` можно
вырезать вместе с prompt section; `project_wait` никогда не пингует пользователя. Так требование
«вырезать или встроить» выполнено без тихой потери других текущих use cases.

**LIKELY — architecture recommendation; usage and no-op mechanics CONFIRMED.**

## 11. Codex goal — вердикт

### Существует

#### Public CLI/desktop surface

Официальная OpenAI документация на 30.08.2026 описывает `/goal` как durable objective для
long-running work: `/goal <objective>` создаёт цель, `/goal` показывает её, а `edit/pause/resume/
clear` управляют run. Goal attached to active chat; Codex может работать независимо много часов и
останавливается при достижении stopping condition. Objective непустой и не длиннее 4 000
characters. Public docs не обещают machine-readable `blocked` transition. [1][2]

Локальный контроль подтверждает доступность:

```text
$ codex --version
codex-cli 0.150.1
$ codex features list | rg '^goals'
goals  stable  true
```

#### Current host tool surface (отдельный контракт)

В текущей host-provided Codex tool surface есть `create_goal(objective, token_budget?)`, `get_goal()` и
`update_goal(status="complete"|"blocked")`. `get_goal()` в этой research-session вернул
`{"goal":null,...}` — goal не был создан, а не отсутствует. Tool contract требует `blocked` только
после трёх подряд goal turns с тем же настоящим blocker. Это измерение **host interface этой
сессии**, а не свойство, подтверждённое public `/goal` docs. Storage/internal implementation из
этого интерфейса не выводится.

### Что применимо

- durable objective + verifiable stop condition;
- продолжение между turns;
- явные complete/blocked outcomes;
- остановка бесконечного retry после повторённого blocker.

### Что не применимо напрямую

- goal живёт в одном chat/thread, не является project registry;
- goal не принуждает project→one-owner;
- official contract не даёт общей multi-project board;
- Orchestra owners работают на разных runtimes, поэтому Codex-only state нельзя сделать
  authoritative project truth.

Правильное заимствование: project может показывать current objective/goal status, а watchdog может
возобновлять owner loop. Но owner, tasks и waits остаются Orchestra-owned durable state.

**CONFIRMED — tier 2 official docs + tier 1 local CLI/tool measurement.**

## 12. Confidence по load-bearing findings

| Finding | Confidence | Основание |
|---|---|---|
| Scope — одна process/session string, не portfolio entity | CONFIRMED | Primary code и DB schema |
| `tm_projects` уже является task project identity | CONFIRMED | FK/schema + 732-task live join |
| Pure frontend overlay не выполняет owner/task/wait invariants | CONFIRMED | Три прямых counterexamples в текущем коде |
| Existing `tm_projects` лучше новой дублирующей таблицы | LIKELY | Минимальная synthesis; architecture ещё не утверждена |
| Seedon owner должен остаться `seedon-orchestrator` | LIKELY | Parent/age/task evidence однозначны, но это manual migration choice |
| Task state сейчас нельзя напрямую рисовать как kanban truth | CONFIRMED | Frozen 06:28 snapshot: 79 IP; 44 no-live; 31 idle-bound |
| 30 минут + generation receipt — разумный initial threshold | LIKELY | Шесть checks и counter-replay; нужен 14-day shadow calibration |
| Точная месячная частота настоящих stalls | UNCERTAIN | Полной historical task-state timeline до cutover нет; replay synthetic |
| Codex goal существует | CONFIRMED | Две official pages + local stable feature/tool interface |

## 13. Counter-evidence и открытые края

### Counter-evidence

- Existing `repo_path` уже позволяет одному orchestrator физически работать в другом repository.
  Это поддерживает дешёвый overlay для rare cross-repo execution, но не task project correctness.
- `release_session_task_binding` уже защищает новые archive transitions. Это уменьшает будущий
  migration debt, но не исправляет frozen-snapshot 44 no-live rows и idle/wait ambiguity.
- Codex `/goal` уже решает self-continuation внутри одного thread. Это уменьшает объём собственного
  loop code для Codex, но не даёт cross-runtime project truth.
- 30-day replay — synthetic sensitivity test, не верхняя оценка; его нельзя цитировать как
  «190 реальных застоев».

### Пробелы до Phase 2

1. Утвердить вариант: read-only (а) либо authoritative `tm_projects` (б). Исследование рекомендует
   (б), но пользователь обязан выбрать архитектуру до стройки.
2. Выбрать worker project context: `sessions.project_id` или stable task identity. Это определит,
   сколько из 32 scope seam реально меняются.
3. Утвердить visual column order.
4. Определить, является ли idle owner сам по себе «работой»; предложение считает только
   running/waiting turn, а idle actionable task — кандидатом после 30 минут.
5. Снять 14-day shadow telemetry после reconciliation; exact historical month восстановить нельзя.

## 14. Риски и edge cases для будущего плана

- duplicate owner race при одновременном create/change-scope;
- sub-orchestrator/manager role нельзя случайно засчитать вторым project owner;
- project path rename и case aliases;
- explicit project mutation из чужого owner scope;
- worker работает cross-repo, а task/merge ищутся в home project;
- waiting question без task ref;
- несколько одновременных decisions в одном project;
- user ответил, но owner ещё не сделал action — wait должен оставаться видимым;
- restart во время watchdog delivery;
- initial reconciliation не должен автоматически закрывать/терять старые tasks;
- `new` не означает user approval; watchdog не должен считать весь backlog actionable.

## 15. Review gate inputs

- Changed artifacts/consumers: `docs/tasks/418/research.md` (user/orchestrator decision),
  `docs/tasks/418/watchdog_replay.py` (research measurement), и
  `docs/kb/project-portfolio.md` (future agents at memory gate); production consumers не изменены.
- Author metadata: `research-projects-board`, `gpt-5.6-sol`, runtime `codex` — live sessions query.
- AC: все пункты из task #418: scope analysis, two variants/cost, measured threshold, board/data
  truth, notify_user, Codex goal, tool gate, Seedon migration.
- Mechanical checks: headings/anchors/source URLs/file-line refs + `git diff --check`; numerical
  claims cross-checked read-only against live SQLite; replay has two targeted scratch-DB boundary
  controls recorded in §8.
- Review route: causal/statistical research without a strong independent oracle would normally
  select Sol; auxiliary Sol was not authorized. One fresh Luna completeness/falsification pass is
  used under the documented fallback.

## 16. Review outcome

Route: fresh Luna, two rounds (prose ceiling reached). Round 1 found four blocking gaps; Round 2
marked tool project identity, authorization wording and Seedon migration `FIXED`, then found two
boundary bugs in the replay script. After the round ceiling, both script bugs were accepted and
fixed; the 25-minute/post-cutoff and duplicate-owner scratch controls in §8 are green. The reviewer
artifact therefore ends with `CHANGES REQUESTED` from the pre-fix Round 2; this research does **not**
claim an `APPROVED` verdict. Full evidence and author resolutions:
`docs/tasks/418/review-research-luna.md`.

## Источники

1. [OpenAI — Follow a goal](https://learn.chatgpt.com/use-cases/follow-goals) — public behavior,
   lifecycle commands, stopping condition, multi-hour continuation; opened 2026-08-30.
2. [OpenAI — Developer commands: `/goal`](https://learn.chatgpt.com/docs/developer-commands?surface=cli) —
   persistent target, view/edit/pause/resume/clear; opened 2026-08-30.
3. Local primary source: `app/db.py`, `app/manager.py`, `app/mcp_stdio.py`, `app/tm.py`,
   `app/routes/sessions.py`, `app/routes/system.py`, `app/routes/tm.py`, `app/merge_operations.py`
   at current branch HEAD; exact anchors inline.
4. Local direct measurements: live read-only
   `/mnt/data/Projects/Python/orchestra/data/orchestra.db`; Codex CLI 0.150.1 feature registry and
   current goal tool interface; commands/output reproduced inline.

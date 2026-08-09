# #169 — fail-closed task/project identity: implementation plan (Phase 2)

Основание: `docs/tasks/169/research.md`. Код Phase 3 ещё не написан.

## Цель

Устранить silent cross-project read/write/link/payment при совпадающих `par`, не меняя
существующие строки legacy-проектов. Любой task get/update/link получает ровно один
authoritative project: явно переданный project либо exact project, связанный с scope.
Отсутствующая, неоднозначная или противоречащая prefix authority отклоняется до side effects.

## Зафиксированные контракты

| Область | Контракт Phase 3 |
|---|---|
| Exact legacy id | Существующий exact `Seedon` и exact `seedon` выбираются раздельно и остаются адресуемыми |
| Casefold alias | При отсутствии exact id: одно casefold-совпадение возвращает его stored id; два и более дают ambiguity error |
| Новый project | При отсутствии совпадений создаётся один deterministic `project_id.casefold()`; повторная variant-запись переиспользует его |
| Existing data | Никаких rename/merge/delete/update существующих `Seedon`/`seedon` и `Orchestra`/`orchestra`; schema migration и startup cleanup отсутствуют |
| Explicit project vs scope | Это альтернативные authority; explicit project выигрывает. Scope — fallback и только opportunistic binding нового проекта |
| Task get/update | Требуют explicit project либо mapped scope; missing/unmapped/ambiguous authority → 4xx до lookup/mutation/sync/payment |
| Prefix | `TASK-N`/plain `N` разрешаются внутри authority; legacy prefix обязан совпасть с prefix authoritative project и не может выбрать другой project |
| Commit link | `link_commits_to_task` не принимает пустой project; merge route продолжает передавать project из worker scope |
| Worker lifecycle | Spawn/switch/merge-next сохраняют существующую scope-pinned `TaskIdentity(id, project_id, par_number, sync_revision)` и CAS |
| Status/payment | `auto_deduct_prepayment` получает только DB id уже доказанно выбранного task внутри той же транзакции; direct payment SQL остаётся client-project scoped |
| Scope change | При target-scope project collision с непустой session `task_id` move отклоняется атомарно; без task association прежний explicit relocation сохраняется |
| Cleanup | Только отдельная будущая dry-run/human-approved задача; в #169 cleanup-кода и live data operations нет |

## Дизайн изменения

### 1. Exact-first project identity в `app/tm.py`

Добавить один helper разрешения project id, используемый create/API callers:

1. Проверить exact `tm_projects.id = requested` и вернуть row без нормализации.
2. Только если exact отсутствует, сравнить существующие ids через Python `str.casefold()`.
3. Одно совпадение вернуть как canonical stored row; несколько — `ValueError` с перечислением
   вариантов, не выбирая первый; ни одного — вернуть `None` для lookup либо создать
   `requested.casefold()` для create.

`ensure_project()` применяет этот contract до INSERT и возвращает реальный stored row/id.
`api_create_task()` выполняется под существующим `BEGIN IMMEDIATE`, использует возвращённый id
для `create_task()`, сравнения с scope owner и response `project`. Scope другого exact legacy
проекта не переносится и не сбрасывает explicit identity: он просто не привязывается к вновь
выбранному проекту. `app/tm_import_yougile.py` также использует returned stored id для client/task
FK, чтобы unique alias reuse не превратился в stale mixed-case FK. Для нового canonical id
display `name` сохраняет явно переданное имя (либо исходное requested spelling), а не вынуждает
UI показывать folded id.

Case-insensitive unique index не добавляется: он не создастся поверх live legacy duplicates.
Все production project creation paths уже проходят через `ensure_project`; API create и import
держат write transaction, поэтому check→insert сериализован без автоматической миграции.

### 2. Одна authority для public task get/update

В `app/routes/tm.py` добавить узкий resolver входной authority:

- непустой `project` разрешается тем же core exact-first/casefold-unique helper и имеет приоритет
  над scope;
- иначе непустой scope разрешается только exact `tm_projects.scope`;
- ни project, ни mapped scope → 400;
- ambiguous/nonexistent explicit project → 4xx; task, отсутствующий внутри валидного project,
  остаётся 404.

GET и PUT `/api/tm/tasks/{par}` получают query `project` вместе с существующим `scope` и передают
в core только resolved stored project id. List сохраняет global behavior без project; непустой
explicit project также проходит exact-first resolver (ambiguous alias не превращается в пустой
список), а каждая row возвращает stored `project`, который caller передаёт в get/update.

В `app/mcp_stdio.py` сигнатуры `task_get`/`task_update` получают optional `project=""`:
explicit project отправляется без подмены scope; при его отсутствии отправляется текущий `SCOPE`.
Это backward compatible для scoped agents и закрывает list→get/update continuity для explicit
cross-project работы.

`resolve_task_ref()` в `app/tm.py` теряет optional/global contract: project становится обязательным,
разрешается exact-first/casefold-unique и затем используется для lookup. Поэтому
`api_get_task()`, `api_update_task()` и direct Python callers не обходят route. Plain/generic
`TASK-N` разрешается только внутри stored project; legacy prefix сверяется с prefix этого же
project. Prefix другого project даёт ошибку, даже если он существует глобально. `get_task_by_par`
может сохранить read-only global ambiguity helper для импорта/диагностики, но ни get/update/link
side-effect API не вызывает его без project. Update response включает stored project.

`api_update_task(status="done")` сохраняет порядок одной транзакции:

```text
resolve project-bound task → capture immutable task.id → update that id
→ auto_deduct_prepayment(conn, same task.id) → commit → sync same task.id
```

Ни один authority error не должен достигать `update_task`, `auto_deduct_prepayment`, `_fire_sync`
или YouGile callback. Direct receive/status/history payment queries не переписываются.

### 3. Commit linking и worker lifecycle

`link_commits_to_task()` в `app/tm.py` делает `project_id` обязательным runtime contract и
отказывает до `BEGIN IMMEDIATE`, если он пуст. Непустой id проходит exact-first/casefold-unique
resolution, затем тот же project-bound prefix check.
`app/routes/sessions.py` уже выводит project из pinned worker scope, не вызывает link helper при
unmapped scope и передаёт project третьим аргументом; production flow не меняется, но получает
интеграционные тесты с case-variant duplicate `par`.

Spawn, switch и merge-next production algorithms не рефакторятся. Тесты закрепляют, что каждый
путь сначала получает `TaskIdentity` из persisted/session scope, а status mutation выполняется
по DB id с проверкой project/par/revision. Commit-message normalization в `app/workspace.py`
остаётся без изменений.

### 4. Scope-change collision без identity drift

В `app/db.py:change_scope()` расширить исходный session SELECT полем `task_id`. До первого UPDATE
в той же транзакции получить source/target project owners по exact scope. Если target scope занят
другим project и session хранит непустой task ref, вернуть error: session scope/cwd/task_id,
tm project scopes, bg jobs и test lock остаются неизменными. Это минимальный fail-closed вариант —
никакой guess, clear или remap task association.

Если `task_id` пуст, сохранить текущий явный relocation contract: session переезжает,
`tm_project_migrated=false`, target project остаётся владельцем scope. При свободном target
scope прежняя атомарная миграция project/bg-job/test-lock остаётся прежней.

## Файлы

### Изменяемые

- `app/tm.py` — exact-first project resolver, canonical create, mandatory task/link authority,
  prefix/project validation, project in update response.
- `app/routes/tm.py` — explicit project query + mapped-scope authority and 4xx mapping.
- `app/mcp_stdio.py` — optional project propagation for `task_get`/`task_update`.
- `app/tm_import_yougile.py` — consume canonical stored project id returned by `ensure_project`.
- `app/db.py` — atomic task-associated scope-collision rejection.
- `tests/test_tm.py` — core create/resolver/status/prepayment/legacy/CAS cases.
- `tests/test_api.py` — HTTP identity continuity, merge linking, lifecycle and scope endpoint cases.
- `tests/test_mcp_stdio.py` — exact project vs scope parameter propagation.
- `tests/test_db.py` — scope-collision atomicity and legacy empty-task compatibility.
- `tests/test_manager.py` — spawn task assignment remains scope-pinned under case-variant duplicates.
- `tests/test_merge_operations.py` — adapt lower-level link contract and preserve merge result semantics.

### Не менять

- Содержимое live SQLite и любые existing project/task/client/payment rows.
- SQLite schema/index collation; no migration/trigger that rejects existing legacy rows.
- `app/workspace.py` merge/cherry-pick/message normalization.
- Payment allocation SQL, client selection policy, YouGile runtime sync and usage analytics.
- Frontend: dashboard already supplies current scope for detail reads.
- Session CAS/lock order, Git worktrees, branch naming, merge commit points.
- Prefix generation digit behavior из F1: отдельный compatibility issue, не причина #169.
- Prod/systemd/restart/deploy и cleanup tooling.

## Tickets

### T1 — Canonical create без case-only namespace, с exact legacy compatibility

- Files: `app/tm.py`, `app/tm_import_yougile.py`, `tests/test_tm.py`
- Change: внедрить exact-first/casefold-unique resolver; использовать returned stored id во всех
  production create consumers; не менять существующие rows/scopes.
- AC:
  - isolated DB с `Seedon` и `seedon` остаётся byte-for-byte теми же двумя project rows после
    exact lookup/create каждого id; задачи создаются строго в выбранном exact id;
  - non-exact `SEEDON` при двух variants отклоняется до INSERT/task creation;
  - при единственном `Seedon`, запрос `seedon` переиспользует stored `Seedon`, не создаёт вторую row;
  - brand-new `MixedCase` создаёт один canonical `mixedcase`, повторные case variants возвращают
    тот же id и следующий `par` того же project;
  - scope, уже принадлежащий другому exact legacy id, не rebinding и не создаёт case-only duplicate;
  - API/import используют returned id для task/client FK и response;
  - independent legacy/create mutations из матрицы M1/M2/M3 ниже делают только свои focused tests red.
- blocked-by: none

### T2 — Project-continuous get/update/status/prepayment через HTTP и MCP

- Files: `app/tm.py`, `app/routes/tm.py`, `app/mcp_stdio.py`, `tests/test_tm.py`,
  `tests/test_api.py`, `tests/test_mcp_stdio.py`
- Change: добавить explicit project authority на GET/PUT/MCP, scope fallback, mandatory core
  authority и project-bound prefix validation; сохранить prepayment после выбранного DB id.
- AC:
  - `task_list(project="Seedon")` → `task_get/update("1", project="Seedon")` читает/меняет только
    upper row при MCP scope lowercase; scope-only get/update меняет только lowercase row;
  - explicit exact `Seedon` и `seedon` остаются раздельно адресуемыми; non-exact alias при двух
    variants даёт 4xx и не вызывает core mutation;
  - отсутствие обоих authority и unmapped scope дают 400 до task lookup/update/sync/payment;
  - task, отсутствующий внутри valid project, даёт 404; равный `par` в другом project не влияет;
  - `UPR-1` с authoritative lowercase project отклоняется; обе task rows, commits, revisions,
    payments и sync markers неизменны;
  - `status=done` с explicit correct project распределяет prepayment только client/task того же
    project; wrong-project same-par row и direct payment другого client не меняются;
  - MCP tests проверяют фактические params: explicit project без scope substitution и scope fallback;
  - independent cross-read/write/prefix/prepayment mutations M4-M7b делают соответствующий один
    focused behavioral test red, а не держатся на соседнем assert/fallback.
- blocked-by: T1

### T3 — Fail-closed commit link и сохранение worker scope/CAS

- Files: `app/tm.py`, `tests/test_api.py`, `tests/test_manager.py`,
  `tests/test_merge_operations.py`, `tests/test_tm.py`
- Change: запретить blank project в link helper; закрепить duplicate-project integration tests,
  не меняя worker lifecycle и merge orchestration.
- AC:
  - direct link с пустой authority отклоняется до transaction/write даже для globally unique `par`;
  - link с lower project + `#1` пишет commit только lower task; foreign prefix `UPR-1` при lower
    project отклоняется и не пишет ни одной row;
  - production merge в lower scope связывает normalized `#1` только с lower task; unmapped worker
    scope возвращает failed link и не делает global fallback;
  - spawn, switch и merge-next при `Seedon#1`/`seedon#1` выбирают DB id из worker/session scope;
    foreign task status/revision/worker_session_id остаются неизменны;
  - revision или immutable identity drift между prevalidation и status update оставляет обе rows
    неизменными и возвращает существующий partial/failure contract после соответствующего commit point;
  - mutations M8-M11 отдельно доказывают blank-link guard, route project propagation, prefix guard
    и project/revision CAS; каждый focused test краснеет при удалении своей защиты.
- blocked-by: T2

### T4 — Scope relocation не меняет смысл сохранённого task ref

- Files: `app/db.py`, `tests/test_db.py`, `tests/test_api.py`
- Change: атомарно отклонять target project-scope collision для session с непустым `task_id`;
  сохранить действующее поведение для session без task association.
- AC:
  - isolated old/new projects с одинаковым `par=1` и session `task_id="1"`: collision возвращает
    error/HTTP 409, session scope/cwd/task_id и обе project scopes неизменны;
  - при отказе active bg job target scope и test lock не двигаются;
  - тот же collision при пустом `task_id` сохраняет текущий успешный relocation с
    `tm_project_migrated=false`;
  - свободный target сохраняет существующую полную migration, stale old_scope по-прежнему fail-closed;
  - mutation M12, удаляющая только task-associated collision guard, делает focused drift test red.
- blocked-by: none

## Behavioral verification matrix

Все DB cases используют pytest `db` fixture/temporary `ORCHESTRA_DB_PATH`; live DB не открывается
на запись и HTTP идёт только к isolated FastAPI TestClient.

| Case | Expected observable result |
|---|---|
| Existing exact `Seedon`, `seedon` | Оба exact lookup/create адресуют свою row; row ids/scopes неизменны |
| Alias `SEEDON` при двух rows | Ambiguous 4xx/ValueError, zero INSERT/update |
| Alias `seedon` при единственном `Seedon` | Возвращён stored `Seedon`, новых projects нет |
| Новый `MixedCase` затем `MIXEDCASE` | Один `mixedcase`, обе tasks внутри него |
| Explicit upper + lower MCP scope | List/get/update continuity остаётся upper; scope не подменяет project |
| Scope-only lower | Read/update/status только lower |
| Нет project и scope | GET/PUT 400; revisions/payments/commits/sync unchanged |
| Unmapped scope | GET/PUT 400 до core helper |
| Lower authority + upper prefix | 4xx, ни read escape, ни mutation/link |
| Upper `done` + upper/lower prepayments | Allocation только upper task/client; lower нетронут |
| Direct payment lower client | Только lower done tasks eligible независимо от upper same-par |
| Merge worker lower + duplicate `#1` | Commit только lower; current merge result semantics unchanged |
| Spawn/switch/merge-next lower | Status/CAS только lower immutable id |
| CAS revision/project mutation | Status side effect отсутствует |
| Scope collision + stored `task_id` | Полный atomic reject; task identity не меняется |
| Scope collision + empty `task_id` | Existing explicit relocation contract preserved |

## Independent mutation verification matrix

Каждая mutation выполняется отдельно на уже зелёном focused test: сначала `grep -c` уникального
якоря, затем в одной shell-команде fresh `cp F F.bak` → одна mutation → pytest → `mv F.bak F` →
`grep -c` подтверждение отката. Никакого `git checkout/show/stash`; backup новый для каждой
mutation. Expected result каждой строки — названный single/focused test **красный**, после restore
тот же test зелёный. Логи малы и пишутся в `/tmp/pytest-169-mutation-<id>.log`.

| ID | Удаляемая защита | Независимое доказательство |
|---|---|---|
| M1 | exact-first branch project resolver | exact `Seedon` остаётся адресуемым при legacy duplicate; без branch тест получает ambiguity |
| M2 | unique-casefold reuse перед INSERT | single `Seedon` + request `seedon` создаёт запрещённый duplicate |
| M3 | use returned canonical id в API/import | task/client FK или response указывает request spelling вместо stored id |
| M4 | explicit-project priority над scope в GET | upper read возвращает lower marker |
| M5 | explicit-project priority над scope в PUT route | upper-intended update меняет lower same-par marker |
| M5b | mandatory project guard в core `resolve_task_ref` | direct update globally unique ref снова проходит без authority |
| M6 | prefix must match authoritative project | `UPR-1` выходит из lower project |
| M7a | тот же PUT project-priority mutant, запуская только prepayment-focused test | wrong lower task становится done и получает prepayment; тест краснеет независимо от title asserts |
| M7b | client-project predicate в direct payment allocation query | payment выбранного client начинает уходить foreign done task; payment isolation test краснеет |
| M8 | blank-authority rejection в `link_commits_to_task` | globally unique ref снова линкуется без project |
| M9 | worker project argument в merge link call | duplicate-par merge перестаёт линковать expected lower task/пытается global fallback |
| M10 | commit-link prefix/project check | prefixed foreign link пишет upper task |
| M11 | по одной project/par и revision clause в CAS | existing focused identity/revision tests допускают wrong status; каждую clause мутировать отдельно |
| M12 | task-associated target-scope collision guard | session переезжает, и stored plain `#1` начинает означать foreign DB id |

## Phase 3 verification order

После каждого ticket выполняется его focused suite и AC, затем соответствующие independent
mutations. После T4:

1. Три последовательных прогона изменённых async merge/switch cases.
2. Targeted suite:

   ```text
   uv run python -m pytest -q tests/test_tm.py tests/test_db.py tests/test_mcp_stdio.py \
     tests/test_manager.py tests/test_api.py tests/test_merge_operations.py
   ```

3. Полный suite строго по pipeline:

   ```text
   uv run python -m pytest -x -q > /tmp/pytest-169.log 2>&1
   ```

4. Прочитать каждый log один раз; `git diff --check`; проверить отсутствие изменений `uv.lock`.
5. Codex implementation review обязателен; если quota gate всё ещё недоступен — не обходить и
   честно оформить `external verdict unavailable` + adversarial self-review, не называя его approval.

## Риски и rollback

- Raw get/update/link callers без authority начнут получать 4xx/ValueError даже при globally unique
  `par`. Это намеренный fail-closed contract break; list остаётся доступным для discovery.
- Mixed-case новый project будет возвращён под canonical stored id; response/MCP/import tests должны
  не позволить caller продолжить с исходным stale spelling.
- Legacy duplicates делают любой не-exact alias неоднозначным; это намеренный отказ, а не повод
  выбрать lowercase/uppercase.
- Scope collision reject меняет один старый тест только для session с task association; empty-task
  relocation остаётся совместимым.
- Изменения транзакционные и не содержат data migration. Rollback кода не требует обратной
  миграции, потому что Phase 3 не переписывает существующие ids/rows.

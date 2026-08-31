# #425 — План: дорога по ярлыкам тем

## 1. Результат

Панель `PROJECTS` перестаёт быть канбаном из четырёх status columns и становится выбранной
концепцией 01:

- одна горизонтальная строка на portfolio project;
- 0–7 упорядоченных ярлыков тем слева направо;
- task cards одного ярлыка идут вертикально, то есть показывают параллельность;
- один task имеет 0 или 1 label; отсутствие label законно;
- derived marker `мы здесь` показывает текущий участок без второго mutable current-stage;
- правый общий блок содержит все unlabelled/current tasks, queue/history сворачиваются, но ни одна
  task не режется `slice()`;
- task открывается read-only в existing modal; task mutation controls не появляются;
- open task wait подсвечивает card, а operator может отправить текст открывшей wait сессии через
  existing `message_deliveries`.

Критический invariant из live measurement:

> Источник задач карты = primary technical namespace проекта, **не**
> `portfolio_task_links`. Links остаются additive association для явно привязанной cross-project
> task. Live `orchestra` имеет `274 tm_tasks` и `0 portfolio_task_links`; карта обязана показать 274,
> а linked-only реализация обязана покраснеть.

`0 links` — не defect #418: relation была намеренно optional, поэтому никто не обязан был создать
274 строки. #425 меняет visibility contract, не optional relation semantics.

## 2. Не делаем

- Не реализуем отклонённые 02 «Лента времени» и 03 «Граф зависимостей».
- Не создаём feature/stage entity, multiple labels, deadlines, owners или automatic labelling.
- Не даём пользователю редактировать task или stage в dashboard; stages задаёт owner-orchestrator
  через authenticated service API.
- Не меняем `tm_tasks`, canonical task storage/binding, task lifecycle, `app/tm.py`,
  `app/mcp_stdio.py`, `message_deliveries.py`, `manager.py`, `dashboard.html` или `pipelines/`.
- Не заводим второй delivery channel/outbox.
- Не трогаем `docs/kb/README.md`.

## 3. Data model и migration

### 3.1 Additive columns

`app/db.py` дополняет fresh DDL и idempotent `_migrate()`. Порядок принципиален:

1. early `CREATE TABLE IF NOT EXISTS` definitions получают только новые columns/defaults для fresh
   DB; **ни новый index, ни trigger там не создаётся**;
2. `_migrate()` сначала inventory + `ALTER TABLE ADD COLUMN` для legacy DB;
3. затем safe backfill;
4. только после появления columns создаются partial indexes и submission trigger.

Так legacy `CREATE TABLE IF NOT EXISTS` не пытается создать index по ещё отсутствующему
`task_namespace_id` до `_migrate()`.

```text
portfolio_projects.task_namespace_id TEXT NULL
portfolio_projects.stage_order_json TEXT NOT NULL DEFAULT '[]'
portfolio_task_links.stage_label TEXT NULL
portfolio_waits.response_text TEXT NULL
portfolio_waits.response_delivery_id TEXT NULL
portfolio_waits.response_attempt INTEGER NOT NULL DEFAULT 0
```

Indexes:

```sql
CREATE UNIQUE INDEX uq_portfolio_primary_task_source
ON portfolio_projects(task_namespace_id)
WHERE archived_at IS NULL AND task_namespace_id IS NOT NULL;

CREATE UNIQUE INDEX uq_portfolio_wait_response_delivery
ON portfolio_waits(response_delivery_id)
WHERE response_delivery_id IS NOT NULL;
```

Fresh defaults: project has no source/order; link has no label; historical waits have no response,
delivery id or attempt. `db.init_db()` twice does not change rows or revision counters.

### 3.2 Safe live backfill

Backfill sets `portfolio_projects.task_namespace_id = tm_projects.id` only when all are true in one
transaction:

1. project source is `NULL`;
2. `portfolio_projects.id = tm_projects.id`;
3. exactly one active root owner exists;
4. normalized lookup `RTRIM(scope,'/')` возвращает **ровно одну** technical project row и она
   совпадает с requested namespace; ноль → 403, больше одной raw-scope row (например `/p` и `/p/`)
   → 409;
5. no other active portfolio project already owns that primary source.

Slug equality alone is forbidden. Ambiguous/unmatched projects remain goal-only/unbound. Before the
UPDATE, migration inventories `COUNT(DISTINCT task_namespace_id)` from active links per project but
never rewrites links. Thus current `orchestra` binds safely (id and owner scope both match), while
legacy mixed-namespace links survive byte-for-byte.

### 3.3 Submission-triggered wait completion

An idempotent SQLite trigger, created after both tables exist, handles only the current response
attempt:

```text
AFTER message_deliveries.state changes to SUBMITTED
AND portfolio_waits.response_delivery_id = NEW.delivery_id
AND wait.status = open
→ bump goal last_progress_at/stall_generation/revision once
→ set wait.status=resolved and resolved_at=NEW.updated_at
```

The trigger is intentionally in `app/db.py`: transition `SUBMITTED` already belongs to the existing
delivery table and must resolve the wait in the same SQLite transaction. No callback, polling loop
or second queue is introduced.

## 4. Backend service/API

### 4.1 Complete task payload

`app/portfolio.py::_task_payloads()` becomes one exact SQL union/join:

- every `tm_tasks` row where `t.project_id = portfolio_projects.task_namespace_id`;
- every active explicit `portfolio_task_links` row for the portfolio project;
- deduplicate by `tm_tasks.id`;
- left-join active link metadata so unlinked primary tasks get `stage_label=NULL` and
  `task_stable_id=NULL`;
- return `task_namespace_id=t.project_id` and `task_display_number=t.par_number` for collision-free
  task detail.

An explicit link from another namespace adds that one task only; it never expands the whole foreign
namespace. A project with `task_namespace_id=NULL` still shows explicit links and may have zero
tasks/labels.

### 4.2 Owner-only source and label mutations

New request models/routes in `app/routes/portfolio.py`, backed by atomic functions in
`app/portfolio.py`:

```text
PUT /api/portfolio/projects/{project_id}/source
    {task_project}

PUT /api/portfolio/projects/{project_id}/stages
    {stages: [display labels], renames: {old: new}}

PUT /api/portfolio/projects/{project_id}/tasks/{task_ref}/stage
    {stage: string|null, task_project?: string}
```

Rules:

- all three require current portfolio owner; contributors can read, not mutate roadmap policy;
- source binding is idempotent and one-way in #425; shared resolver получает все normalized
  owner-scope matches and требует ровно одну row: requested namespace mismatch → 403, ambiguous
  `/scope` + `/scope/` → 409; contributor → 403; second project/source collision → 409;
- `stages` accepts 0–7 values, trims/collapses whitespace, rejects empty/>64 chars and casefold
  duplicates; stored display spelling comes from the ordered list;
- `renames` updates order and all matching task link labels in one transaction, including a rename
  while already at the seven-label cap;
- assignment resolves an unambiguous task from primary source or an existing explicit link;
  optional `task_project` disambiguates duplicate `#N`; label must exist case-insensitively in order;
- assigning a primary unlinked task creates its normal link receipt with canonical stable id and
  label; clearing an unlinked source task creates nothing; clearing an existing link preserves the
  link and sets only label `NULL`.

Project payload exposes parsed `stage_order`, `task_namespace_id`, task label/namespace/number and
wait delivery state. Raw JSON is never passed to the browser.

`tests/route_surface_snapshot.json` остаётся побайтно равен `main` на Phase 2. В Phase 3 его нужно
обновить **тем же implementation commit**, который реально добавит три route: snapshot описывает
существующую поверхность, а отсутствие routes уже доказано отдельным T1 RED.

### 4.3 Operator wait answer, existing agent contract preserved

`WaitResolve` has `response: str | None = None`; cancel keeps `WaitClose`. Route behavior branches by
principal:

- agent + header + `response is None` → existing synchronous logical `close_wait(...resolved)`;
- dashboard operator + non-empty response → `require_operator_csrf()` and async delivery flow;
- dashboard response missing/blank/>4000 → 422;
- agent cannot impersonate operator response; operator cannot use fallback session identity.

Authenticated dashboard `GET /api/portfolio/projects` includes a same-origin `csrf_token`; agent
header requests do not. Frontend sends `X-CSRF-Token` on answer POST. `resolve_wait` becomes
`async def`; он **не** передаёт coroutine в sync `_call()`. Agent close выполняется через
`await asyncio.to_thread(portfolio.close_wait, ...)` с прямым `PortfolioError` mapping; operator
branch через `await asyncio.to_thread(reserve/prepare...)`, затем напрямую
`await message_deliveries.accept_message_delivery(...)`, затем формирует response. Остальные sync
handlers и `_call()` не меняются.

State machine:

```text
open + no response
  → durable DB lookup of exact opened_by_session_id
  → archived/missing: 409, no response/id persisted
  → reserve response_attempt=1 + UUID5(wait,attempt)
  → existing message_deliveries.accept_message_delivery(..., kind=portfolio_wait_answer)
  → wait remains open/pending until delivery row reaches SUBMITTED

FAILED_BEFORE_SUBMIT
  → known no provider submit
  → identical answer increments attempt, gets new UUID5 and current target generation

QUEUED | PREPARING | DISPATCHING | DELIVERY_UNKNOWN
  → return current receipt; never create another attempt

SUBMITTED
  → SQLite trigger resolves current wait and bumps goal atomically
```

If a receipt already exists after a crash, retry uses its frozen target tuple/generation, not a
recomputed payload. A different answer after reservation/resolution is 409. Task wait message is
`Пользователь ответил по задаче #N: <response>`; project-level wait names the project. Fallback to
owner or same-name session is forbidden.

## 5. Frontend: concept 01

Only `app/static/js/app.js` and `app/static/css/style.css` change.

### 5.1 Composition

`PortfolioPanel` keeps the `PROJECTS` tab, 15-second poll and existing `#tasks-panel`, but renders:

- sticky board header/legend and project count;
- project header with name, owner/contributors and active goal;
- `[data-portfolio-road]` horizontal axis with 0–7 `[data-road-stage]` frames;
- cards vertical inside each stage, status-coded: done/paid green, in-progress blue, cancelled gray,
  new/backlog muted;
- all stages containing in-progress get active accent;
- one marker: rightmost in-progress stage → leftmost queued stage → unlabelled segment → road end;
- open task wait adds high-contrast glow/badge and exact question; project-level wait gets a visible
  project banner.

A `stage_order=[]` project renders one wide `БЕЗ ЭТАПОВ · N задач` segment with its active tasks,
queue disclosure and marker. Zero-task project remains visible with goal and
`Этапы не заданы · задач пока нет`.

### 5.2 Right edge without losing tasks

Unlabelled right segment shows in-progress immediately. Queue (`new/backlog`) and terminal history
have separate disclosure buttons. Collapsed state renders counts only; expansion lazily renders
**every** matching card and asserts no hard limit in code. `Set` state keyed by
`project_id:queue|history` survives each `PortfolioPanel.render/load`, so the 15-second refresh does
not close what the user is reading.

At 1280–1920 px the file panel keeps its current max width; each project road owns horizontal scroll,
so 7 stages do not widen the document/body. Reduced-motion keeps the current convention.

### 5.3 Read-only task modal + wait response

Extend `showTaskDetail(par, projectSelector='', waitContext=null)`:

- existing TASKS callers with one argument keep `currentScope` behavior;
- road passes `task_namespace_id`, so duplicate `#N` opens through
  `/api/tm/tasks/{par}?project={namespace}`;
- existing `_taskCardBodyHtml()` and commit rows remain read-only;
- open wait appends exact question, textarea and submit button dynamically in `app.js`;
- submit sends response + CSRF to existing resolve route and shows delivery truth:
  `Ответ принят и отправляется` for queued/in-flight, explicit failure/unknown messages otherwise;
- modal/road never navigates away and never renders task-edit fields.

No new element is written into `dashboard.html`. Frontend is hot after merge, but the user must run
`Ctrl+Shift+R`; Python routes/schema need the normal Orchestra restart.

## 6. Test and migration protocol

- Current frozen RED commit: `60178ec3` (`tests/test_project_roadmap_backend_425.py`,
  `tests/test_project_roadmap_frontend_425.py`, real-dashboard smoke in `tests/test_frontend.py`,
  `docs/tasks/425/live_backup_oracle.py`). Earlier `4dbecb64` is superseded after Luna round-1
  findings added owner/CSRF/race/placement/large-corpus/production-load checks; Phase 3 compares
  these oracle paths byte-for-byte with `60178ec3`. `tests/route_surface_snapshot.json` исключён из
  frozen RED и остаётся равен `main` до появления routes.
- T1/T2 fixture resolves the real repository DB through git common-dir, reads live
  `sessions` with SQLite `mode=ro`, installs a connect guard before any app DB call, and prints
  `before=577 after=577` even on RED teardown.
- Browser T3 loads `marked`, DOMPurify, diff-match-patch and highlight in the production order from
  `dashboard.html:8-11`, plus production CSS/tailwind and app dependencies; pre-seam page errors are
  asserted empty.
- Phase 3 migration rehearsal uses `sqlite3.Connection.backup()` of live DB, never `cp`; record
  portfolio/task/session counts before/after and run `init_db()` twice.
- Required live-shaped proof on backup: `orchestra` starts with 274 namespace tasks/0 links and
  returns all 274 after migration; no link rows are synthesized; live `sessions` count is unchanged.
- Executable command is `uv run python docs/tasks/425/live_backup_oracle.py`; it uses
  `sqlite3.Connection.backup()`, derives production from git common-dir, runs `init_db()` twice on
  the copy and prints the production count even on RED. Current RED: exit 1 at
  `#425 T1 missing behavior: task_namespace_id migration`, `sessions 577→577`.
- Focused regressions after each ticket; full suite only after all tickets, with `uv.lock` unchanged.

## 7. Files

Change:

- `app/db.py`
- `app/portfolio.py`
- `app/routes/portfolio.py`
- `app/static/js/app.js`
- `app/static/css/style.css`
- `tests/route_surface_snapshot.json` (сейчас равен `main`; обновить вместе с routes в T1)
- focused #425 tests (already frozen; immutable in Phase 3)

Do not change:

- `app/templates/dashboard.html`
- `app/tm.py`, canonical/task binding storage
- `app/message_deliveries.py`, `app/manager.py`, mailbox/restart inbox
- `app/mcp_stdio.py`, prompts, `pipelines/`
- concepts 02/03 or unrelated dashboard panels

## Plan review outcome

Luna round 1 in `docs/tasks/425/review-plan.md`: `CHANGES REQUESTED`, 5 blocking + 5 suggestions.
Каждое замечание проверено по current code/tests и принято:

- schema objects перенесены после additive legacy columns в `_migrate()`;
- async resolve больше не проходит через sync `_call()`;
- frozen T2 получил missing/invalid CSRF negative controls;
- frozen T1 получил contributor-source denial и ambiguous normalized-scope 409;
- executable `live_backup_oracle.py` доказывает source/live counts/links/sessions/idempotent migration;
- T2 получил stale-old-attempt, duplicate submit и concurrent-identical probes;
- T3 получил exact stage/unlabelled/active/status assertions, 137-row no-slice control и real-dashboard
  `PortfolioPanel.load()` smoke.

Oracle change после review перезаморожен в `60178ec3`; исходный `4dbecb64` исключён из Phase 3.

## Review decision inputs

- Changed consumers planned: SQLite migration/trigger, portfolio auth/task payload/API, shared direct
  message state, PROJECTS panel, existing task modal.
- Author: `roadmap-board`, `gpt-5.6-sol`, Codex runtime (live task #425 session metadata).
- Oracle: independent frozen RED `60178ec3`; DB guard output and exact commands below.
- Risk floor: persistence schema + shared message delivery + operator mutation. Sol is the preferred
  risk route but auxiliary Sol is explicitly not authorized; assignment requires one fresh Luna
  plan/test pass. Research used two Luna rounds and exhausted its prose ceiling; plan is a new
  review subject.

## Tickets

### T1 — Truthful complete task source and one bounded theme label

- Files: `app/db.py`; `app/portfolio.py`; `app/routes/portfolio.py`;
  `tests/route_surface_snapshot.json` (implementation companion: обновить только после добавления
  routes, тем же T1 commit; frozen #425 tests не менять).
- Test: `uv run python -m pytest -q -s tests/test_project_roadmap_backend_425.py::test_t1_complete_task_source_single_label_and_bounded_order` — committed RED in `60178ec3`; supplemental live-backup oracle: `uv run python docs/tasks/425/live_backup_oracle.py`.
- RED: exit 1 — `AssertionError: #425 T1 missing behavior: portfolio roadmap routes [...]`;
  teardown prints `#425 production sessions invariant: before=577 after=577`.
- AC: named command is green + project with primary namespace and **zero links** exposes every
  namespace task; live-backup `orchestra` returns 274/274 while links remain 0; explicit foreign link
  adds one task, not its namespace; 0/7 labels accepted, 8/casefold duplicate/unknown rejected;
  exactly one nullable label per task; clear preserves task visibility; rename at cap is atomic;
  contributor source/stage and foreign source fail 403; duplicate source and ambiguous normalized
  `/scope` + `/scope/` fail 409; source backfill requires id+unique owner-scope;
  `uv run python -m pytest -q tests/test_routes_surface.py::test_route_surface_snapshot` is green;
  supplemental live-backup command is green with payload count equal current namespace count
  (measured baseline 274), links `0→0`, source `orchestra`, migration twice and unchanged production
  `sessions` count.
- blocked-by: none

### T2 — User wait response through durable direct-message states

- Files: `app/db.py`; `app/portfolio.py`; `app/routes/portfolio.py` (same dependency chain as T1;
  do not edit tests or `message_deliveries.py`).
- Test: `uv run python -m pytest -q -s tests/test_project_roadmap_backend_425.py::test_t2_wait_text_delivery_targets_opener_and_resolves_only_on_submission` — committed RED in `60178ec3`.
- RED: exit 1 — `AssertionError: #425 T2 missing behavior: WaitResolve.response`; teardown prints
  `#425 production sessions invariant: before=577 after=577`.
- AC: named command is green + dashboard answer requires cookie+CSRF and exact 1..4000 text; target
  missing/invalid CSRF fail 403 without reservation; target is `opened_by_session_id`; receipt uses
  kind `portfolio_wait_answer` and includes task #/text;
  wait remains open/pending at QUEUED and resolves/bump goal only when current receipt is SUBMITTED;
  repeated SUBMITTED bumps goal once; stale old attempt cannot resolve after current id changes;
  two concurrent identical answers create one current receipt; identical replay does not duplicate;
  retry creates a new attempt only after FAILED_BEFORE_SUBMIT; DELIVERY_UNKNOWN keeps same
  attempt/barrier; archived opener returns 409 and persists no answer/delivery; agent resolve `{}`
  and cancel `{}` remain green.
- blocked-by: T1

### T3 — Concept-01 road, complete disclosure and read-only response modal

- Files: `app/static/js/app.js`; `app/static/css/style.css` (do not edit dashboard template or tests).
- Test: `uv run python -m pytest -q tests/test_project_roadmap_frontend_425.py::test_t3_concept_one_keeps_every_task_and_answers_wait_in_read_only_modal tests/test_frontend.py::test_project_road_425_uses_real_dashboard_dom_and_load_path` — committed RED in `60178ec3`.
- RED: exit 1 — `Failed: #425 T3 missing behavior: concept-01 project road`; pre-seam
  `page_errors == []` proves the production vendor chain loaded.
- AC: named command is green at both 1280 and 1920 px + Memory/Board tasks reside in their exact
  stage frames, unlabelled active task resides in the right segment, done status data is preserved,
  derived marker and both in-progress stage active accents render; open wait glows and exact question
  is visible; zero-stage
  project shows tasks/marker; queue is `+96` collapsed, expands to exactly 96 cards, and remains open
  after re-render; independent 137-task control expands to the exact complete ID set (catches
  `slice(0,100)` and duplication); task detail uses explicit namespace, shows description/status/commits with no edit
  controls/no navigation; response POST carries CSRF/text and reports queued truth; document has no
  horizontal overflow while road owns scroll; no browser page errors; real isolated dashboard page
  loads production template/assets, switches the actual PROJECTS tab and reaches road through
  `PortfolioPanel.load()`.
- blocked-by: T1, T2

## Frozen RED evidence

```text
$ uv run python -m pytest -q -s tests/test_project_roadmap_backend_425.py::test_t1_complete_task_source_single_label_and_bounded_order
F#425 production sessions invariant: before=577 after=577
E AssertionError: #425 T1 missing behavior: portfolio roadmap routes
E ['/api/portfolio/projects/{project_id}/source',
E  '/api/portfolio/projects/{project_id}/stages',
E  '/api/portfolio/projects/{project_id}/tasks/{task_ref}/stage']
1 failed; exit 1

$ uv run python -m pytest -q -s tests/test_project_roadmap_backend_425.py::test_t2_wait_text_delivery_targets_opener_and_resolves_only_on_submission
F#425 production sessions invariant: before=577 after=577
E AssertionError: #425 T2 missing behavior: WaitResolve.response
1 failed; exit 1

$ uv run python docs/tasks/425/live_backup_oracle.py
#425 production sessions invariant: before=577 after=577
E AssertionError: #425 T1 missing behavior: task_namespace_id migration
exit 1

$ uv run python -m pytest -q tests/test_project_roadmap_frontend_425.py::test_t3_concept_one_keeps_every_task_and_answers_wait_in_read_only_modal
E Failed: #425 T3 missing behavior: concept-01 project road
1 failed; exit 1

$ uv run python -m pytest -q tests/test_frontend.py::test_project_road_425_uses_real_dashboard_dom_and_load_path
E Failed: #425 T3 missing behavior: real dashboard project road load path
1 failed; exit 1
```

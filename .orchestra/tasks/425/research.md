# #425 — Дорога по этапам: research

## Вопрос

**Контекст.** В dashboard уже есть portfolio-проект, цель, owner/contributors, optional task links,
waits и кнопка `PROJECTS`, но текущая панель группирует данные по четырём статусным колонкам.
Пользователь выбрал концепцию 01 из `roadmap-concepts.html`: строка проекта, слева направо темы-
этапы, задачи внутри темы вертикалью, маркер «мы здесь», общая очередь справа. [1][2]

**Изменение под проверкой.** Добавить одному portfolio-task не более одного nullable ярлыка темы,
задать на portfolio-project порядок 0–7 ярлыков, показать все задачи проекта на дороге, выделить
task-specific open waits, принять текстовый ответ пользователя и передать его открывшей wait
сессии через штатную direct-message delivery.

**Baseline.** `portfolio_task_links` сейчас optional, проект `orchestra` имеет 0 active links, а
`_task_payloads()` возвращает только linked tasks; `WaitClose` содержит только `now`, а
`close_wait()` лишь меняет status/resolved_at. Текущий frontend строит глобальные status lanes,
не дороги по проектам. [3][4][5]

**Решающие исходы.** После изменения: (1) ни одна текущая task из bound task namespace не исчезает;
(2) одновременно существует 0–7 упорядоченных ярлыков и не более одного ярлыка у task; (3) проект
без ярлыков остаётся полезным; (4) 96 queued tasks не раскрываются при первом кадре, но все доступны
одним раскрытием; (5) ответ принят durable direct-message receipt именно на
`opened_by_session_id`; (6) task detail остаётся read-only и не уводит со страницы.

## Гипотезы и фальсификаторы

### H1 — ярлык в human-portfolio слое, порядок в проекте

`portfolio_task_links.stage_label TEXT NULL` хранит один ярлык, а
`portfolio_projects.stage_order_json TEXT NOT NULL DEFAULT '[]'` хранит порядок 0–7 уникальных
ярлыков. Отдельная nullable связь `portfolio_projects.task_namespace_id` говорит, из какого одного
primary technical namespace брать **все** задачи; explicit links из любых уже законных namespaces
остаются дополнительными rows и не исчезают. Source binding не выводится из отдельного link и не
меняет его прежний смысл.

**Фальсификатор:** схема не может показать unlinked task без автоматического создания link-строк,
ломает законный goal-only project, теряет legacy mixed-namespace links либо допускает один primary
technical namespace одновременно в две неразличимые дороги.

### H2 — ярлык прямо в `tm_tasks`

Nullable `tm_tasks.stage_label` выглядит короче на один JOIN.

**Фальсификатор:** ярлык имеет смысл только внутри human portfolio project, а `tm_tasks.project_id`
остаётся technical namespace/canonical binding; добавление поля потребует менять task owner и
canonical adapter, хотя roadmap — optional presentation metadata. [6]

### H3 — отдельная таблица stage entities

`portfolio_stages(project_id,id,name,position,...)` и FK из task links дают сильную ссылочную
целостность и удобный rename.

**Фальсификатор:** если stage не имеет собственного lifecycle/owner/status/deadline и максимум равен
7, отдельная entity/table не добавляет пользовательского свойства, а создаёт CRUD и join, которые
пользователь прямо исключил уточнением «этап = один необязательный ярлык темы».

### H4 — доставка ответа через новый локальный mailbox/outbox

Специализированный wait-answer outbox мог бы атомарно закрывать wait и ставить сообщение в очередь.

**Фальсификатор:** существующий `message_deliveries.accept_message_delivery()` уже фиксирует
idempotent receipt, пишет user-message в target history и будит target runner; второй канал создал бы
ещё одну FIFO/retry semantics. [7][8]

## Проверенный baseline

### Код

- `portfolio_projects`, `portfolio_task_links`, `portfolio_goals` и `portfolio_waits` уже создаются
  в `app/db.py`; ни task source, ни stage order, ни stage label, ни response text/receipt в таблицах
  нет. [3]
- `_task_payloads()` делает `portfolio_task_links JOIN tm_tasks`, поэтому unlinked task невидима;
  `_project_payload()` уже собирает project/owner/contributors/goal/tasks/waits в один JSON. [4]
- `WaitClose` имеет только `now`; `POST .../resolve` вызывает sync `close_wait()`, который не знает
  текста и delivery. [5]
- Текущий `PortfolioPanel` рисует четыре status lanes (`Планируется`, `В работе`, `Ждёт решения`,
  `Сделано`), а существующий `showTaskDetail()` уже показывает description/status/commits в modal,
  не меняя task. [9]
- Direct-message ingress до принятия receipt отвергает exact archived target как `TARGET_NOT_FOUND`;
  для активного target строит lifecycle generation, вызывает preflight и затем
  `accept_message_delivery()`. Receipt хранит payload hash, target identity и состояние, а runner
  доставляет через обычный `manager.send_message_delivery()`. [7][8]

### Живые данные, read-only

Команда 31.08.2026:

```text
sqlite3 -readonly /mnt/data/Projects/Python/orchestra/data/orchestra.db ...

portfolio  linked_tasks  open_waits
orchestra  0             0

status       n
done         153
new           96
in_progress   20
cancelled      5

all_tasks=274, queued=96, in_progress=20, terminal=158
```

Owner `Orchestra-orchestrator` имеет scope `/mnt/data/Projects/Python/orchestra`; exact scope lookup
даёт `tm_projects.id='orchestra'`, то есть текущий human project можно безопасно backfill-ить по
совпадающему immutable id, не по имени сессии и не по эвристике title. [10]

Макет фиксировал 19 in-progress, живой срез через несколько часов дал 20: количество динамическое,
поэтому `19`/`96` допустимы только как acceptance fixture, не как константы UI. [1][10]

## Findings

### F1 — выбранная модель: один nullable ярлык на portfolio task metadata + порядок в project

**CONFIRMED — решение пользователя + текущая граница human/technical данных.**

Самая дешёвая честная модель:

1. `portfolio_projects.task_namespace_id TEXT NULL` — optional source всех task rows; `NULL`
   сохраняет goal-only project;
2. `portfolio_projects.stage_order_json TEXT NOT NULL DEFAULT '[]'` — ordered unique labels,
   допустима пустая последовательность, максимум 7;
3. `portfolio_task_links.stage_label TEXT NULL` — максимум один ярлык на task, отсутствие законно;
4. migration backfill подключает source только при одновременном доказательстве
   `portfolio_projects.id = tm_projects.id` **и** exact active-owner scope = `tm_projects.scope`;
   ambiguous/unmatched projects остаются unbound;
5. explicit owner-only source mutation задаёт future non-matching project, но только если
   `task_namespace_id` равен exact technical project, mapped из active owner scope тем же правилом,
   что `_resolve_scoped_task()`; caller-supplied foreign namespace получает 403; один primary
   namespace нельзя bound к двум active portfolio projects;
6. legacy links из другого namespace не отвергаются и не расширяются до всего namespace: payload
   объединяет все rows primary source с каждым explicit linked row и deduplicate по task row id.

Это не возвращает `tm_projects` роль human project: namespace остаётся источником task records, а
goal/owner/labels/waits остаются в `portfolio_*`. [6][10]

**Цена вариантов.** Поле в `tm_tasks` дешевле в одном SQL, но дороже по ownership/canonical
consumers. Отдельная stage table сильнее ограничивает rename, но покупает entity lifecycle, которого
нет. JSON order + nullable link label добавляют три additive columns и owner-only operations:
explicit source binding, stage-order replace с atomic rename map и task stage assign/clear.
Whitespace схлопывается, casefold определяет уникальность, display spelling берётся из order;
assignment к отсутствующему label отвергается. Sub-orchestrator contributor читает дорогу, но не
меняет source/order/labels. Rename на полном лимите выполняется одной transaction, а не двумя
противоречивыми запросами.

### F2 — полнота требует source binding; existing links недостаточны

**CONFIRMED — прямой live count + текущий JOIN.**

У live `orchestra` 0 links и 116 non-terminal tasks. Следовательно, «оставить link как visibility
gate» отрисует пустую дорогу и прямо нарушит новый заказ. Payload должен объединять all tasks
primary bound namespace с explicit linked tasks, делать `LEFT JOIN portfolio_task_links` для
metadata и добавлять `stage_label=NULL` тем, у кого metadata строки нет. Explicit link остаётся
нужен для stable id/wait и stage assignment, но не фильтрует primary-source visibility. [4][10]

Это сохраняет прежний mixed-link state: link другого namespace показывает только явно выбранную
task, а не весь чужой namespace. Перед migration нужен inventory `COUNT(DISTINCT
task_namespace_id)` по каждому project; backfill primary source не удаляет и не переписывает links.

Payload обязан отдавать `task_namespace_id`/project selector и display number: иначе клик из
portfolio panel использует глобальный `currentScope` и может открыть одноимённый `#N` из другого
technical project. Existing task detail API уже принимает explicit `project` selector. [9][11]

### F3 — очередь: compact summary first, complete lazy expansion

**CONFIRMED — user constraint + measured cardinality + panel width.**

Правый общий блок хранит unlabelled tasks и разделяется по status:

- in-progress показываются сразу;
- `new/backlog` показываются summary `+N в очереди` и лениво раскрываются полностью;
- terminal history (`done/paid/cancelled`) имеет отдельную свёртку, чтобы 158 старых rows не
  вытесняли текущую работу;
- при раскрытии число task cards обязано совпасть с payload count — никаких `slice(0,N)`.

Disclosure state хранится вне DOM в `Set` по `(project_id, queue|history)` и применяется после
каждого 15-секундного `PortfolioPanel.load()`: refresh обновляет rows, но не схлопывает то, что
пользователь читает.

Панель расширяется максимум до 1180 px (`min(82vw,1180px)`), а проект может иметь 7 тем плюс общий
блок, поэтому project road должен иметь собственный horizontal scroll; свёртка уменьшает именно
правый блок, а не теряет данные. [10][12]

### F4 — проект без этапов рисуется как осмысленная общая дорога

**CONFIRMED — явное решение пользователя, 0 stages является valid state.**

При `stage_order=[]` проект всё равно показывает goal/owner, один широкий сегмент
`БЕЗ ЭТАПОВ · N задач`, активные unlabelled cards и сворачиваемую queue/history. Маркер «мы здесь»
стоит на этом сегменте. Пустой project показывает `Этапы не заданы · задач пока нет`, а не пустые
status columns. Так zero-stage state не требует synthetic stage и не скрывает tasks.

### F5 — «мы здесь» не требует нового mutable поля

**LIKELY — детерминированное правило следует из task statuses, но production UX ещё не измерен.**

Маркер вычисляется при render:

1. rightmost ordered stage с `in_progress`;
2. иначе leftmost ordered stage с `new/backlog`;
3. иначе общий unlabelled segment, если там есть non-terminal tasks;
4. иначе конец последнего stage.

Все stages с in-progress получают active accent, поэтому один marker не скрывает параллельную работу
в более ранней теме. Отдельный `current_stage` сделал бы вторую ручную истину, способную разойтись со
status task.

### F6 — ответ пользователя идёт через durable `message_deliveries`, archived target fail-loud

**CONFIRMED для механизма; LIKELY для UX archived-case — код доказывает semantics, пользовательский
сценарий ещё не проходил browser acceptance.**

Resolve получает отдельную совместимую модель с optional `response`; dashboard operator обязан
передать non-empty trimmed 1..4000 response, а agent `project_wait(resolve)` по-прежнему может
послать `{}`. Cancel остаётся на старой модели. `portfolio_waits` получает nullable
`response_text`, `response_delivery_id` и `response_attempt INTEGER NOT NULL DEFAULT 0`; existing
rows сохраняют `NULL/0`.

Dashboard `GET /api/portfolio/projects` возвращает same-origin CSRF token только валидной operator
cookie-сессии; JS посылает его в `X-CSRF-Token`, а answer branch использует существующий
`require_operator_csrf()`. Agent branch сохраняет `x-orchestra-session-id` authorization.
`resolve_wait` становится `async def`; blocking SQLite preparation/finalization идёт через
`asyncio.to_thread`, а `accept_message_delivery()` обязательно `await`-ится на service event loop.

Resolve flow использует `status='open'` как честное `waiting/pending`, пока normal channel не
подтвердил submission:

1. прочитать open wait и exact `opened_by_session_id`; direct DB status `archived`/missing отвергается
   до manager cache/preflight, wait остаётся open;
2. зарезервировать response text + attempt `1` + deterministic delivery id в open wait одной
   transaction;
3. если receipt с этим id уже существует, повтор использует **его сохранённый target tuple и
   generation**, а не пересчитывает payload; если receipt ещё нет — построить current tuple и
   выполнить normal delivery preflight;
4. принять idempotent receipt через `message_deliveries.accept_message_delivery()` с kind
   `portfolio_wait_answer` и текстом `Пользователь ответил по задаче #N: <response>`;
5. после durable acceptance wait остаётся open/pending; `_wait_payloads()` отдаёт joined delivery
   state, поэтому UI различает queued/dispatching/unknown/failed/submitted;
6. `AFTER UPDATE OF state ON message_deliveries`, когда **текущий** `response_delivery_id` переходит
   в `SUBMITTED`, idempotent SQLite trigger в той же transaction ставит wait `resolved`, пишет
   `resolved_at` и bump-ит goal `last_progress_at/stall_generation/revision`;
7. `FAILED_BEFORE_SUBMIT` доказывает, что provider submit не начался: retry той же response делает
   `response_attempt+1`, заменяет current delivery id на UUID5 `(wait_id,attempt)` и использует
   current authorized target tuple; старый failed receipt остаётся audit row;
8. `DELIVERY_UNKNOWN`/`DISPATCHING` не допускают новый attempt; wait остаётся open с явным status,
   потому что повтор может дать дубль;
9. другой response при reserved/pending/resolved wait получает 409; identical response возвращает
   current receipt/status.

Attempt-scoped deterministic id и reuse frozen tuple закрывают crash-window «receipt уже принят,
route оборвалась» без payload-hash conflict. Acceptance означает durable queue receipt, а не
синхронное завершение model turn; payload wait выводит delivery state, UI пишет `Ответ принят и
отправляется`, не обещает `оркестратор уже прочитал`. Stale generation даёт известный
`FAILED_BEFORE_SUBMIT`, поэтому новый attempt безопасен; archive на повторе даёт 409. Unknown
outcome остаётся barrier и никогда не ретраится автоматически. [7][8]

**Цена archived-вариантов.** Fallback к текущему owner дешевле для пользователя, но отправляет ответ
не адресату; поиск active session по тому же name нарушает stable session identity и неоднозначен
между scopes. Запись в archived log выглядит доставкой, но никогда не будит получателя. 409 + open
wait сохраняет правду и позволяет явно cancel/reopen у нового адресата.

### F7 — task detail переиспользуется, task editing не появляется

**CONFIRMED — existing modal/API уже покрывают description/status/commits.**

Road task вызывает расширенный `showTaskDetail(par, projectSelector, waitContext)` и остаётся в
существующем modal. Поля task read-only. Для highlighted wait в modal динамически добавляются exact
question, textarea ответа и submit; это mutation wait, не task. Новые DOM элементы создаются в
`app/static/js/app.js`, `dashboard.html` не меняется. [9][11]

### F8 — migration и mutation paths должны быть явными

**CONFIRMED — reviewer finding проверен против `_migrate()` и текущих request models.**

`CREATE TABLE IF NOT EXISTS` не добавляет columns в live SQLite. Phase 2 обязан назвать idempotent
`_migrate()` additions: project source/order defaults, task label nullable, wait response/receipt/
attempt defaults, safe source backfill по exact id + owner scope, partial unique source index после
inventory и idempotent `message_deliveries SUBMITTED → current wait resolved` trigger.
`db.init_db()` дважды не меняет rows/revisions.

Owner-only HTTP surface: source bind/unbind; order replace + optional atomic rename map; task
assign/clear. Эти endpoints нужны для orchestrator-authored stages, даже если dashboard остаётся
read-only. Они не требуют нового MCP tool в #425: агентский write path остаётся authenticated HTTP
service API, а расширение MCP — отдельное решение за границей текущего owned scope.

## Counter-evidence и ограничения

- #418 намеренно зафиксировал: unlinked task не видна на board. Новый прямой заказ «все текущие
  задачи видимы» supersedes только visibility contract; он не отменяет optional human project и не
  превращает `tm_projects` обратно в owner/goal truth. [6]
- Safe backfill покрывает live `orchestra`, потому что совпадают и immutable id, и owner scope;
  portfolio project с другим id/ambiguous owner mapping остаётся goal-only до explicit owner source
  mutation. Совпадение slug без scope evidence недостаточно.
- Один derived marker упрощает чтение, но не выражает несколько одновременных «фронтов». Active
  accents на всех stages компенсируют это; если UX окажется неоднозначен на живых данных, потребуется
  отдельное пользовательское решение, не скрытая автоматика.
- Direct-message receipt защищает от дубля и переживает restart, но lifecycle generation может
  измениться между acceptance и dispatch. Wait остаётся open до atomic `SUBMITTED` trigger;
  `FAILED_BEFORE_SUBMIT` разрешает новый attempt, ambiguous state запрещает retry. Receipt state
  остаётся в API/wait payload, а обещание «прочитал» без `SUBMITTED` невозможно. [7][8]
- `opened_by_session_id` FK intentionally retains archived session rows. #425 не меняет archive/
  delete lifecycle; hard delete с referenced wait остаётся запрещён SQLite, а archive получает 409
  на новый ответ.
- 7 тем × много labelled tasks тоже могут дать большую высоту. Свёртка обязательна для общей очереди
  и history; внутри именованного stage задачи не режутся, иначе нарушается полнота.

## Affected files, риски, edge cases

- `app/db.py` — additive migration/backfill/indexes; риск production schema и silent wrong source.
- `app/portfolio.py` — source-bound complete task query, stage validation/assignment, wait answer
  finalize; риск cross-project exposure и task disappearance.
- `app/routes/portfolio.py` — owner-only stage mutations, dashboard operator answer, async delivery;
  риск auth/CSRF confusion и close-before-accept loss.
- `app/static/js/app.js` — project roads, queue disclosure, marker, task modal/wait form; риск duplicate
  handlers after 15-second reload and wrong task namespace.
- `app/static/css/style.css` — 1280–1920 layout, horizontal road scroll, status/wait states;
  risk panel overflow and unreadable 7-stage layout.
- `tests/` — isolated DB oracle with production `sessions` before/after count; browser oracle loads
  the same vendor chain as `dashboard.html:8-9` before app scripts.

Edge cases: 0/1/7/8 labels; duplicates differing only by case/whitespace; task label absent from
order; namespace mismatch; project with zero tasks; all tasks terminal; open project-level wait
without task; two waits for one task; concurrent identical/different responses; opener archived;
target generation change; 96 queue cards; task `#N` collision across technical projects; escaped
task title/question/response; repeated portfolio polling while disclosure/modal is open.

## Review outcome

Luna round 1: `Needs work`, 6 blocking + 4 suggestions in
`docs/tasks/425/review-research.md`. Проверка кода дала:

- ACK: unsafe slug-only source backfill → добавлено owner-scope evidence;
- ACK: project source не может отвергать legacy mixed links → source стал primary supplement, union
  сохраняет explicit rows;
- ACK: lifecycle generation входит в receipt payload hash → retry берёт frozen tuple из existing
  receipt;
- ACK: dashboard cookie без CSRF/header недостаточна → same-origin token +
  `require_operator_csrf()`;
- ACK: resolve route должен быть async/await;
- ACK: archived check обязан читать durable DB, не manager cache;
- ACK suggestions: agent `{}` compatibility, owner-only mutation surface, refresh-preserved disclosure,
  explicit idempotent `_migrate()`.

Luna round 2: шесть round-1 blockers отмечены FIXED; два новых blocking подтверждены кодом.

- ACK: source mutation допускала чужой namespace → добавлена та же owner-scope authorization, что у
  `_resolve_scoped_task()`.
- ACK: resolve на acceptance делал stale-generation receipt невосстановимым → wait теперь pending
  до `SUBMITTED`, завершение атомарно привязано DB-trigger к current attempt; только доказанный
  `FAILED_BEFORE_SUBMIT` создаёт новый attempt, ambiguous state остаётся barrier.

Потолок review прозы равен двум раундам, поэтому третьего запуска нет. Round-2 artifact содержит
проверяемые code references и dispositions, но не обязательную дословную цитату из изменённого
research; итог ревью записан как `Needs work / verdict evidence incomplete`, а не `APPROVED`.
Оба blocking после code verification закрыты в текущей версии research; незакрытых reviewer
requirements для Phase 2 не осталось.

Фраза reviewer `Luna was unavailable` противоречит metadata `gpt-5.6-luna`, завершённому model run,
находкам и проверяемой цитате из research; раунд засчитан как состоявшийся Luna review, а эта строка
не используется как факт о доступности.

## Review decision inputs

- Planned consumers: persistence schema/migration, portfolio API, shared message delivery, dashboard
  road/task modal, existing task-detail API.
- Author: `roadmap-board`, model `gpt-5.6-sol`, Codex runtime; live `sessions` metadata for task #425.
- Exact AC: the six measurable outcomes in **Вопрос** plus ticket commands in Phase 2.
- Current oracle: none yet in Phase 1; Phase 2 must freeze independent REDs before implementation.
- Risk floor: schema migration + shared message delivery are high-risk. Canonical route would prefer
  Sol, but auxiliary Sol is explicitly not authorized; assignment requires one fresh Luna review.

## Sources

1. `docs/tasks/425/roadmap-concepts.html:98-177,280-315` — selected concept, legend, marker,
   `+96`, rejected alternatives and original visual comparison.
2. User decisions in #425 assignment and 31.08 follow-up — read-only task view, orchestrator-owned
   stages, one optional theme label per task, all current tasks visible.
3. `app/db.py:482-580` — current portfolio schema.
4. `app/portfolio.py:145-180,220-255,614-707` — linked-only payload and wait open/close semantics.
5. `app/routes/portfolio.py:45-60,205-235` — `WaitClose` and resolve/cancel routes.
6. `docs/tasks/418/plan.md:15-105,300-325` — authoritative human project vs technical namespace,
   optional task links and superseded linked-only board contract.
7. `app/routes/sessions.py:670-875` — normal keyed direct-message target/auth/archive/preflight path.
8. `app/message_deliveries.py:1-220,430-525`; `app/manager.py:1125-1165` — durable receipt and ordinary
   target delivery runner.
9. `app/static/js/app.js:3585-3710,4160-4285` — current status-lane panel and existing task detail.
10. Read-only SQLite commands recorded in **Живые данные** — live project/link/task/session counts and
    exact owner-scope ↔ task-project mapping, 31.08.2026.
11. `app/routes/tm.py:147-175`; `app/tm.py:1240-1265` — explicit project task detail with commits.
12. `app/static/css/style.css:1048-1168` — current portfolio panel width and four-column layout.

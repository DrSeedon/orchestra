## Tests
"Тесты не применимы — это дизайн-документ, не код."

## Summary
Дизайн в целом попадает в нужную простую форму для MVP, но денежная часть пока небезопасна: баланс, распределения и статусы оплаты не описаны как единая транзакция, а prepayment-логика противоречит собственной формуле баланса. YouGile sync слишком оптимистичен: без очереди/ревизий/идемпотентности можно получить дубли, потерянные обновления и неверный PAR-35. Импорт тоже недоописан для реальных данных: пагинация, PAR-коллизии и проверка полноты критичны, потому что это разовый перенос источника правды. UI и MCP реализуемы в текущей Orchestra, но в дизайне не хватает нескольких контрактов, чтобы агенты и dashboard не работали с неоднозначными состояниями.

## Замечания
blocking: docs/research/task-manager-design.md:470 — `distribute_payment()` читает долги, пишет allocations/tasks/balance и вызывает sync без явно описанной транзакции; два одновременных `payment_receive` могут оба увидеть один и тот же `paid_rub` и переплатить задачу или разъехать `balance_rub`. Фикс: весь прием платежа, распределения, пересчет `paid_rub`/`balance_rub` и sanity checks выполнять в одном `BEGIN IMMEDIATE` transaction; YouGile/TG запускать только после commit.

blocking: docs/research/task-manager-design.md:551 — списание из аванса создает новый "virtual" payment и одновременно уменьшает `balance_rub`, что ломает формулу line 581: `SUM(payments)-SUM(allocations)` не уменьшится, потому что новый payment компенсирует новую allocation. Фикс: при списании аванса распределять уже существующие неаллоцированные платежи FIFO/smallest-id-first или завести отдельный тип ledger entry; не создавать новый incoming payment для внутреннего списания.

blocking: docs/research/task-manager-design.md:66 — `tm_payments.amount_rub`, `tm_payment_allocations.amount_rub`, `tm_tasks.price_rub` и `paid_rub` не `NOT NULL` и без `CHECK(amount_rub > 0)`/`CHECK(price_rub >= 0)`. Сейчас `NULL` или отрицательная сумма может пройти часть проверок SQLite и испортить баланс. Фикс: сделать money-поля `INTEGER NOT NULL`, добавить положительные/неотрицательные CHECK-и и такой же pydantic validation на API/MCP.

blocking: docs/research/task-manager-design.md:30 — `par_number INTEGER NOT NULL UNIQUE` не автоинкрементится само по себе, а `MAX(imported)+1`/`max+1` при создании задач дает race и PAR-коллизии. Фикс: описать атомарный генератор PAR внутри `BEGIN IMMEDIATE` (`tm_counters(name, next_value)` или отдельная таблица sequence) и на импорте сначала зарезервировать диапазон выше `MAX(par_number)`.

blocking: docs/research/task-manager-design.md:165 — `task_update(price: int = 0)` использует `0` как "не менять", но `price_rub=0` является валидной задачей; также не описано, что делать при изменении цены у частично/полностью оплаченной задачи. Фикс: использовать `price: int | None = None`; запретить снижение ниже `paid_rub`, а при повышении цены у `paid` переводить задачу обратно в `done` с долгом или явно запрещать изменение цены оплаченных задач.

blocking: docs/research/task-manager-design.md:599 — правило "all tasks with `paid_rub == price_rub` have `status='paid'`" автоматически делает любую задачу с `price_rub=0` оплаченной, включая `backlog/new/cancelled`. Фикс: либо запретить `price_rub=0` для paid logic, либо менять sanity check на `price_rub > 0 AND paid_rub == price_rub`.

blocking: docs/research/task-manager-design.md:367 — "каждая мутация async push" без версии задачи и сериализации по task_id допускает out-of-order sync: старый push может прийти после нового и вернуть в YouGile старый статус/цену. Фикс: хранить `sync_revision`/`updated_at` и пушить только последнюю ревизию; для одного task_id выполнять sync последовательно.

blocking: docs/research/task-manager-design.md:372 — если `yougile_create()` создал задачу, но `update_task_yougile_id()` не записался или процесс упал, повтор создаст дубль в YouGile. Фикс: при create передавать стабильный внешний идентификатор `PAR-N`/`idTaskProject`, перед повтором искать задачу по PAR, а `yougile_task_id` обновлять в транзакции с sync-log состоянием.

blocking: docs/research/task-manager-design.md:457 — "не блокировать main operation" после ошибки sync допустимо для обычных полей, но для платежей это ломает требование YouGile/PAR-35 как клиентского зеркала: платеж уже учтен в Orchestra, а клиент может видеть старый долг. Фикс: сделать durable pending sync (`tm_sync_log status='pending/error'` с retry API/кнопкой), возвращать caller-у явный `sync_status`, а payment/PAR-35 ошибки подсвечивать в dashboard.

blocking: docs/research/task-manager-design.md:448 — PAR-35 update описан как append в description + comment, но нет идемпотентности; retry после timeout может дважды добавить один платеж, а частичный успех может оставить title/comment/description в разных состояниях. Фикс: включать `payment_id` в строку журнала и комментарий, перед append проверять наличие этого id, обновлять все части через одну функцию с повторяемым результатом.

blocking: docs/research/task-manager-design.md:956 — YouGile import использует `GET /tasks?columnId={id}&limit=30`, но line 347 обещает "ALL tasks"; без пагинации импорт тихо потеряет задачи после первых 30 в колонке. Фикс: описать цикл по offset/next cursor до пустого результата и verification: count per column до/после импорта.

blocking: docs/research/task-manager-design.md:361 — для задач без `idTaskProject` предлагается назначать новый PAR, но не описано обнаружение дублей по title/yougile_task_id и конфликт, если parsed PAR уже занят другой задачей. Фикс: импорт должен быть idempotent по `yougile_task_id`, при PAR collision писать в отдельный conflict report и не продолжать cutover до ручного решения.

blocking: docs/research/task-manager-design.md:941 — `done -> cancelled` и `paid -> cancelled` заявлены, но нет refund/reversal модели; отмена оплаченной задачи оставит allocations и `paid_rub`, а отчеты по долгу/балансу станут неоднозначными. Фикс: запретить cancel для `paid`/partially paid без отдельной операции refund/void allocation или явно описать сторнирующие записи.

suggestion: docs/research/task-manager-design.md:785 — routes перечислены так, что `GET /api/tasks/{par}` стоит перед `GET /api/tasks/sync-log`; в FastAPI параметрический route может перехватить `sync-log`, если порядок реализации повторит документ. Фикс: объявлять static routes до `/{par}` или вынести sync в `/api/task-sync/log`.

suggestion: docs/research/task-manager-design.md:731 — endpoint для dashboard принимает `scope`, но схема task manager оперирует `project_id`, а текущий dashboard имеет только `file-panel` в `app/templates/dashboard.html:77` и выбранный orchestrator scope в JS. Фикс: добавить явный mapping `scope -> tm_project.id` или возвращать дефолтный `parsing-hub` для Parsing scope; иначе tasks tab будет показывать пусто/не тот проект.

## Вердикт
Перед реализацией нужно закрыть денежные транзакции, prepayment ledger и идемпотентный YouGile/PAR-35 sync; после этого дизайн годится для MVP.

## Round 2 Re-review

Проверял фактический файл `docs/research/task-manager-design.md` в workspace. Заявленные фиксы в нем не обнаружены: `rg` не находит `BEGIN IMMEDIATE`, `tm_par_sequence`, `sync_revision`, `/api/tm`, `price: int | None`, `pending`, `[#7]`, `forbidden`; при этом старый virtual payment все еще есть на line 551. Поэтому ниже статус по фактическому документу, а не по описанию в сообщении.

1. STILL BROKEN — docs/research/task-manager-design.md:470: `distribute_payment()` все еще без `conn` и без `BEGIN IMMEDIATE`; YouGile sync вызывается внутри цикла на line 517 до commit.
2. STILL BROKEN — docs/research/task-manager-design.md:551: virtual payment все еще создается через `INSERT INTO tm_payments`, затем balance уменьшается отдельно на line 570; формула line 581 остается сломанной.
3. STILL BROKEN — docs/research/task-manager-design.md:34: `price_rub`/`paid_rub` все еще без `NOT NULL`; docs/research/task-manager-design.md:66 и :77 не имеют `CHECK(amount_rub > 0)`.
4. STILL BROKEN — docs/research/task-manager-design.md:30: `tm_par_sequence` отсутствует, `par_number` по-прежнему просто `INTEGER NOT NULL UNIQUE`; line 358 все еще говорит `MAX(imported)+1`.
5. STILL BROKEN — docs/research/task-manager-design.md:165: `task_update(price: int = 0)` все еще использует `0` как sentinel "don't change".
6. STILL BROKEN — docs/research/task-manager-design.md:599: sanity check все еще требует `paid_rub == price_rub -> paid` без условия `price_rub > 0`.
7. STILL BROKEN — docs/research/task-manager-design.md:367: `sync_revision` отсутствует, stale revision skip не описан.
8. STILL BROKEN — docs/research/task-manager-design.md:38: `yougile_task_id` все еще не `UNIQUE`; create retry на line 372-375 все еще может создать дубль.
9. STILL BROKEN — docs/research/task-manager-design.md:457: sync failure все еще "retry once" и "continue"; pending durable retry, `sync_status` и dashboard warning в документе отсутствуют.
10. STILL BROKEN — docs/research/task-manager-design.md:448: PAR-35 sync все еще append без payment id/idempotency; `[#{payment_id}]`-проверки нет.
11. STILL BROKEN — docs/research/task-manager-design.md:956: API reference все еще `limit=30`; offset/cursor pagination и count verification в тексте отсутствуют.
12. STILL BROKEN — docs/research/task-manager-design.md:361: import все еще назначает новый PAR без описанного `yougile_task_id` idempotency/conflict report; `UNIQUE yougile_task_id` в схеме нет.
13. STILL BROKEN — docs/research/task-manager-design.md:941: `done -> cancelled` все еще разрешен без условия `paid_rub==0`, `paid -> cancelled` все еще описан как refund scenario.
14. STILL BROKEN — docs/research/task-manager-design.md:785: routes все еще под `/api/tasks`, `GET /api/tasks/{par}` стоит перед `GET /api/tasks/sync-log`; `/api/tm` prefix отсутствует.
15. STILL BROKEN — docs/research/task-manager-design.md:15: `tm_projects.scope` отсутствует; docs/research/task-manager-design.md:735 все еще передает `scope` в endpoint без схемного mapping.

Новые баги, введенные фиксом: по фактическому файлу новых багов от фиксов нет, потому что сами фиксы в документ не попали. Новый блокер процесса: сообщение о внесенных изменениях расходится с содержимым `docs/research/task-manager-design.md`, поэтому перед следующей проверкой нужно сохранить/применить актуальную версию документа.

## Round 3 Re-review

Проверял обновленный `docs/research/task-manager-design.md` заново по фактическому содержимому.

1. FIXED — transaction safety. Цитата: `Entire operation runs in a single BEGIN IMMEDIATE transaction` (docs/research/task-manager-design.md:289) и `YouGile sync and TG notification happen AFTER commit` (line 290).
2. FIXED — virtual payments убраны. Цитата: `Prepayment deductions create allocations against the ORIGINAL payment (FIFO), NOT fake "virtual" payments` (docs/research/task-manager-design.md:76-77).
3. FIXED — money constraints добавлены. Цитата: `price_rub INTEGER NOT NULL DEFAULT 0 CHECK (price_rub >= 0)` (docs/research/task-manager-design.md:36), `amount_rub INTEGER NOT NULL CHECK (amount_rub > 0)` (lines 68, 82).
4. FIXED — PAR race закрыт. Цитата: `tm_par_sequence` (docs/research/task-manager-design.md:24) и `UPDATE tm_par_sequence SET next_value = next_value + 1 RETURNING next_value - 1 inside BEGIN IMMEDIATE` (line 114).
5. FIXED — `0` больше не sentinel в update. Цитата: `price: int | None = None` и `0 = set to zero` (docs/research/task-manager-design.md:180).
6. FIXED — zero-price задачи исключены из paid sanity. Цитата: `price_rub > 0 AND paid_rub == price_rub` и `price_rub = 0 are excluded` (docs/research/task-manager-design.md:665).
7. FIXED — out-of-order sync концептуально закрыт. Цитата: `sync_revision` (docs/research/task-manager-design.md:41) и `Sync worker only pushes the latest revision, skipping stale ones` (line 128).
8. STILL BROKEN — retry после успешного `yougile_create()` и падения до записи `yougile_task_id` все еще может создать дубль. Цитата: код делает `result = await yougile_create(task)` (docs/research/task-manager-design.md:408), а затем только после remote create пишет `update_task_yougile_id` (line 411); внешний поиск по `PAR-N`/`idTaskProject` перед повторным create не описан, и `UNIQUE yougile_task_id` не помогает, если id не успел попасть в SQLite.
9. FIXED — payment sync failure теперь видим и ретраится. Цитата: `dashboard prominently shows pending payment syncs`, `payment_receive returns sync_status: "pending"` и `Manual retry button` (docs/research/task-manager-design.md:505-508).
10. FIXED — PAR-35 idempotency добавлена. Цитата: `Include payment_id ... [#7]` и `Before appending, check if [#7] already exists` (docs/research/task-manager-design.md:489-492).
11. FIXED — import pagination добавлен. Цитата: `with pagination (loop until empty page, offset-based: ?columnId={id}&offset={n}&limit=50)` (docs/research/task-manager-design.md:377).
12. FIXED — import dedup/collision report добавлены. Цитата: `Dedup by yougile_task_id` и `PAR collision check` (docs/research/task-manager-design.md:381-382), `conflict report is empty` (line 395).
13. FIXED — paid/partially-paid cancel запрещен. Цитата: `paid -> terminal` (docs/research/task-manager-design.md:941) и `done/paid -> cancelled when paid_rub > 0` forbidden (line 953).
14. FIXED — route collision снят. Цитата: `+ /api/tm/* routes` (docs/research/task-manager-design.md:773) и `Static routes ... registered BEFORE parametric /{par}` (line 799).
15. FIXED — scope→project mapping добавлен. Цитата: `scope TEXT` в `tm_projects` (docs/research/task-manager-design.md:17) и `Scope maps to tm_projects.scope -> returns tasks for that project` (line 754).

NEW BUGS:

blocking: docs/research/task-manager-design.md:405 — create path says `if not task['yougile_task_id']` then create, but does not search YouGile by stable PAR/idTaskProject before POST. Fix: include `idTaskProject: PAR-{par_number}` on create and, before POST, query YouGile for existing task by that external id; if found, only backfill `yougile_task_id`.

suggestion: docs/research/task-manager-design.md:17 — `tm_projects.scope` maps dashboard scope to project, but is not unique; duplicate scopes would make `/api/tm/tasks?scope=...` ambiguous. Fix: use `scope TEXT UNIQUE` or explicitly define first-match/error behavior.

suggestion: docs/research/task-manager-design.md:96 — schema comment allows sync statuses only `'pending', 'ok', 'error'`, but sync code logs `status='skipped'` on stale revisions at docs/research/task-manager-design.md:417. Fix: add `skipped` to allowed statuses/comment and dashboard handling, or log stale skips as `ok` with action detail.

suggestion: docs/research/task-manager-design.md:308 — `payment_receive` return example says `"sync_status": "ok"`, while the algorithm enqueues sync after commit (docs/research/task-manager-design.md:331-333). Fix: either return `"pending"` by default after enqueue, or state that API waits for post-commit sync before returning `"ok"`.

ВЕРДИКТ — NOT YET.

## Round 5

- FIXED — `idTaskProject` issue закрыт. В create body теперь есть `"idTaskProject": f"PAR-{task['par_number']}"` (docs/research/task-manager-design.md:477), а lookup перед create ищет тот же `PAR-N` (docs/research/task-manager-design.md:407).
- NEW BUGS: новых от этого изменения не вижу.
- ВЕРДИКТ: NOT YET — остается не новый, но все еще открытый Round 4 bug: после backfill `yougile_task_id` код вызывает `await yougile_update(task)` со старым `task`, прочитанным до backfill (docs/research/task-manager-design.md:403, 411, 414). Нужно refetch/mutate `task` перед update.

## Round 6

- FIXED — stale `task` после backfill закрыт: после `update_task_yougile_id(...)` теперь есть `task = get_task_by_id(task_id)` перед `await yougile_update(task)` (docs/research/task-manager-design.md:413-415).
- NEW BUGS: не вижу.
- ВЕРДИКТ: APPROVED.

## Round 4

Проверял фактический `docs/research/task-manager-design.md` после Round 4 фиксов.

1. STILL BROKEN — create retry dupe закрыт не полностью. Да, lookup появился: `existing = await yougile_find_by_par(f"PAR-{task['par_number']}")` (docs/research/task-manager-design.md:407). Но create body для `POST /tasks` все еще содержит только `title`, `description`, `columnId` (docs/research/task-manager-design.md:473-477) и не задает `idTaskProject`/другой стабильный PAR marker. Если первый remote create успел пройти, но задача в YouGile не получила `idTaskProject=PAR-N`, retry lookup ее не найдет и снова сделает `yougile_create()`.

2. FIXED — `scope` теперь уникальный. Цитата: `scope TEXT UNIQUE` (docs/research/task-manager-design.md:17).

3. FIXED — `skipped` добавлен в статусы sync log. Цитата: `-- 'pending', 'ok', 'error', 'skipped'` (docs/research/task-manager-design.md:96).

4. FIXED — `payment_receive` больше не обещает sync `ok` для async post-commit sync. Цитата: `"sync_status": "pending"` (docs/research/task-manager-design.md:308).

NEW BUGS:

blocking: docs/research/task-manager-design.md:414 — после crash-recovery backfill код вызывает `await yougile_update(task)`, но локальная переменная `task` была прочитана до `update_task_yougile_id()` и все еще содержит пустой `yougile_task_id`. Фикс: после backfill либо refetch task, либо присвоить `task['yougile_task_id'] = existing['id']` перед `yougile_update(task)`.

ВЕРДИКТ — NOT YET.

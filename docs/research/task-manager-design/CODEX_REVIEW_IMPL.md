## Tests

Запущено: `pytest`.

Результат: 84 collected, 22 passed, 23 failed, 39 errors. Падения не выглядят специфичными для task manager: `tests/test_api.py` не может пропатчить `app.session.AgentSession` (`module 'app' has no attribute 'session'`), а `tests/test_db.py` падают на `save_session()` из-за отсутствующих bind-параметров `context_pct/context_tokens/progress_pct/progress_status` в старых фикстурах.

## Summary

Core payment distribution в `app/tm.py` в целом следует дизайну: суммы в integer rubles, `BEGIN IMMEDIATE` используется в публичных API, allocation идёт через ledger, sanity checks проверяют `paid_rub`, баланс и over-allocation. Основной разрыв с дизайном — синхронизация YouGile фактически не подключена к операциям: CRUD/payment меняют SQLite, но не пушат и не ставят retryable sync job. Самый опасный data-integrity разрыв — импорт: PAR-35 payment journal не импортируется, а `paid_rub` записывается напрямую без `tm_payments`/`tm_payment_allocations`, что ломает ledger-инвариант. Frontend функционально добавлен, но task title/метаданные вставляются через `innerHTML` без escaping.

## Замечания

- blocking: app/tm.py:573, app/tm.py:601, app/tm.py:714 — API create/update/payment коммитят SQLite и возвращают ответ, но не вызывают `yougile_sync_task()`, `yougile_update_par35()` и не создают pending sync job. По дизайну YouGile должен быть mirror после каждой мутации; сейчас новые задачи, смена статусов, оплаты и PAR-35 остаются только локально. Фикс: после `commit()` запускать sync для затронутых task_id и PAR-35, а до/после запуска писать `tm_sync_log` со статусами `pending/ok/error` так, чтобы сбой sync не откатывал деньги, но был виден и retryable.

- blocking: app/tm_import_yougile.py:110, app/tm_import_yougile.py:145 — import пропускает PAR-35 и при этом проставляет `paid_rub` напрямую из заголовка задачи без создания `tm_payments` и `tm_payment_allocations`. Это нарушает ключевой инвариант `paid_rub == SUM(allocations)`; следующий `_sanity_check()` для такого клиента может упасть с `Task payment mismatch`, а баланс клиента будет недостоверен. Фикс: импортировать PAR-35 journal в реальные `tm_payments`, создать allocations к задачам, после этого пересчитать `paid_rub` и `balance_rub` из ledger.

- blocking: app/tm_yougile.py:96 — `sync_revision` не используется как защита от stale push. `yougile_sync_task()` читает текущую задачу и пушит её без проверки "я всё ещё последняя ревизия"; `get_pending_syncs()` есть, но не участвует в алгоритме. При двух близких изменениях старый sync может завершиться позже и перетереть YouGile более старым title/status. Фикс: enqueue sync с конкретным `sync_revision`, перед push сравнивать с актуальной ревизией/последней pending и stale jobs логировать как `skipped`.

- blocking: app/tm_yougile.py:85 — `yougile_find_by_par()` проверяет только первые 50 задач в каждой колонке. Это ломает crash recovery из дизайна: если remote create успел пройти, а локальный `yougile_task_id` не сохранился, retry может не найти существующий `PAR-N` и создать дубль в YouGile. Фикс: добавить offset pagination до пустой страницы или использовать API-поиск/фильтр по `idTaskProject`, если он доступен.

- blocking: app/tm_yougile.py:192 — идемпотентность PAR-35 проверяет только marker в description. Если title/description update прошёл, а comment или column title update на строках 221-224 упали, retry увидит marker и пропустит всю операцию, оставив YouGile payment journal частично синхронизированным. Фикс: проверять результат каждого запроса, не возвращать `ok` при частичном failure, а idempotency делать по каждому подшагу или писать marker только после успешного завершения всех обязательных действий.

- suggestion: app/tm.py:623 — после перехода задачи в `done` вызывается `auto_deduct_prepayment()`, но `api_update_task()` возвращает `result["task"]`, полученный до auto-deduct. Если предоплата полностью закрыла задачу, ответ MCP/API всё равно покажет старые `paid_rub` и `new_status`. Фикс: после auto-deduct перечитать задачу и вернуть уже финальное состояние.

- suggestion: app/tm_import_yougile.py:136 — import вызывает `create_task(... par_number=par_num)` для задач с PAR и `_next_par()` для задач без PAR, но `tm_par_sequence` обновляется только в конце на строках 154-160. Если в середине импорта встретится задача без `idTaskProject`, sequence может выдать PAR, который уже был импортирован явно или встретится позже, и импорт упадёт на UNIQUE. Фикс: сначала собрать занятые PAR и выставить sequence выше max до вставок без PAR либо выдавать временные номера из `max_seen + 1`.

- suggestion: app/main.py:843 — из sync routes реализован только `GET /api/tm/sync/log`; в дизайне ещё есть `POST /api/tm/sync/import` и `POST /api/tm/sync/retry/{id}`. Без retry route ошибки YouGile остаются ручной DB-операцией. Фикс: добавить минимальный retry endpoint, который берёт запись `tm_sync_log`, перечитывает task_id и повторяет нужный sync.

- suggestion: app/static/js/app.js:3625 — `t.title` вставляется в `innerHTML` без escaping. Описание в modal очищается через `DOMPurify`, но title/assignee/project/payment fields в списке и деталях идут как HTML. Фикс: строить DOM через `textContent` или добавить маленький `escapeHtml()` для всех server-provided строк; `DOMPurify` оставлять для markdown description.

- suggestion: app/static/js/app.js:3588 — dashboard показывает только debt, но дизайн обещает `Balance` и предупреждение о pending/failed sync. Для денег это важный operational сигнал: после оплаты пользователь не видит остаток предоплаты и не видит, что PAR-35/статусы не дошли до YouGile. Фикс: подтянуть `/api/tm/payments/status` и `/api/tm/sync/log`, вывести balance и count проблемных sync entries.

- question: app/mcp_stdio.py:262 — MCP `task_update` использует `price=-1` sentinel и пустую строку как "не менять", хотя дизайн описывает `None`. Это практично для MCP, но сейчас нельзя очистить `title`, `description` или `assignee` в пустую строку. Оставляем как сознательное ограничение MVP или нужен отдельный sentinel/JSON body tool для clear-field?

## Вердикт

NOT YET

## Round 2

### Tests

Повторно запущено: `pytest`.

Результат не изменился по сути: 84 collected, 22 passed, 23 failed, 39 errors. Падения всё ещё не из task manager: `app.session.AgentSession` не находится в тестовых моках, а `save_session()` требует отсутствующие в фикстурах `context_pct/context_tokens/progress_pct/progress_status`.

### Проверка прошлых замечаний

- STILL BROKEN: app/tm.py:576 — sync теперь вызывается после commit, но это недолговечный fire-and-forget без durable pending job. В FastAPI-контексте `create_task()` должен сработать, но при рестарте между commit и выполнением coroutine sync потеряется без записи `pending`; в CLI/no-loop контексте helper прямо пропускает sync. Фикс минимально достаточный для happy path, но не закрывает требование дизайна про retryable sync log.

- STILL BROKEN: app/tm_import_yougile.py:110, app/tm_import_yougile.py:145 — `paid_rub` теперь подкреплён allocation, это лучше, но PAR-35 всё ещё пропускается, а вместо реальной истории оплат создаётся fake payment на каждую оплаченную задачу. Это противоречит дизайну ledger: `tm_payments` должны быть реальными входящими платежами клиента, а не синтетическими строками по задачам. Баланс предоплаты и история оплат после импорта будут недостоверны.

- STILL BROKEN: app/tm_yougile.py:152 — stale check сравнивает `current_rev` с `task["sync_revision"]`, прочитанным из той же строки прямо перед этим, поэтому обычно это одно и то же значение. `yougile_sync_task(task_id)` не получает revision конкретного sync job, не читает latest pending revision и не может корректно skip-нуть устаревшую работу. Фикс: передавать/логировать revision at enqueue time и сравнивать job revision с актуальной ревизией непосредственно перед push.

- FIXED: app/tm_yougile.py:85 — `yougile_find_by_par()` теперь ходит по pages через `offset`/`limit=50`, crash recovery больше не ограничен первой страницей колонки.

- STILL BROKEN: app/tm_yougile.py:212 — PAR-35 partial failure всё ещё может стать невосстановимым. Если description update успел записать marker, а comment или column update упали, следующий retry попадёт в `if marker in desc` и вернёт `already applied`, не доделав недостающие шаги. Ошибки теперь собираются, но idempotency всё ещё стоит на слишком раннем marker.

- FIXED: app/tm.py:667 — после `auto_deduct_prepayment()` задача перечитывается перед commit, API/MCP ответ больше не возвращает stale `paid_rub/status`.

- STILL BROKEN: app/tm_import_yougile.py:136 — проблема с `tm_par_sequence` при импорте задач без `idTaskProject` не исправлена: sequence всё ещё обновляется только в конце на строках 164-169. Если `_next_par()` выдаст номер, который уже импортирован явно или встретится дальше, import упадёт на UNIQUE.

- PARTIAL: app/main.py:852 — retry endpoint добавлен, но он умеет только task sync по `task_id`. PAR-35/payment sync не логируется в `tm_sync_log`, поэтому retry route не сможет повторить упавший PAR-35 sync. Ещё один практический дефект: успешный retry создаст новую log entry, но старая `error` entry останется `error`, и dashboard может продолжать показывать pending/error.

- FIXED: app/static/js/app.js:3516, app/static/js/app.js:3634, app/static/js/app.js:3680 — task title, assignee, project и header values теперь проходят через escaping; description по-прежнему sanitizes через DOMPurify.

- FIXED: app/static/js/app.js:3568 — tasks panel теперь подтягивает payment status и sync log, показывает balance и count pending/error sync entries. Для одного клиента MVP это ок.

- UNCHANGED / accepted for MVP: app/mcp_stdio.py:262 — `price=-1` sentinel и невозможность очистить text fields в пустую строку остались. Это не блокер, если принято как ограничение MCP-интерфейса.

### New Bugs

- blocking: app/tm.py:586 — `_fire_par35_sync()` вообще не пишет результат в `tm_sync_log`. Если PAR-35 sync вернул `partial failure: ...`, ошибка останется только в Python log, `/api/tm/sync/log` и dashboard её не увидят, retry endpoint не сможет её поднять. Фикс: логировать payment/PAR-35 sync отдельной записью `tm_sync_log` с `task_id=NULL`, `action='par35_payment'`, payload с `payment_id`, и сделать retry для этого action.

- suggestion: app/main.py:863 — retry старой error-записи не меняет её статус после успешного повтора. Из-за этого warning в dashboard может висеть даже после успешного retry, пока запись не выпадет из `limit=10`. Фикс: либо обновлять исходную entry в `ok/skipped`, либо связывать retry с исходной записью и исключать superseded errors из UI.

### Вердикт

NOT YET

## Round 4

### Проверка

- FIXED: app/tm.py:576 — `_fire_sync()` создаёт pending entry и закрывает свою `sync_log_id` после завершения async task. Вечные pending для happy path больше не должны висеть.

- FIXED: app/tm.py:602 — PAR-35 sync теперь пишет pending в `tm_sync_log` и переводит запись в `ok/error` после результата.

- FIXED: app/tm.py:580 — action для task sync теперь выбирается как `create`, если у задачи ещё нет `yougile_task_id`, иначе `update`.

- ACCEPTED: app/tm_import_yougile.py:170 — consolidated import payment принят как MVP-компромисс; точный PAR-35 journal можно добить вручную после cutover.

- ACCEPTED: app/tm_yougile.py:152 — refetch перед push + skip старых pending revisions принят как достаточный для single-user MVP.

### New Bugs

- suggestion: app/tm.py:585 — `_fire_sync()` закрывает pending как `ok` в `finally`, не глядя на результат `yougile_sync_task()`. При `create failed: ...` или `error` будет отдельная error-запись от `yougile_sync_task()`, но собственная pending-запись станет `ok`, что путает историю. Лучше ставить `ok/error` по возвращаемому результату.

- suggestion: app/main.py:863 — PAR-35 entries теперь видны в `tm_sync_log`, но retry endpoint всё ещё возвращает `no task_id on sync entry` для `task_id=NULL`. Не блокирую MVP, но кнопка retry для payment sync пока не заработает.

### Вердикт

APPROVED

## Round 3

### Проверка

- STILL BROKEN: app/tm.py:576, app/tm_yougile.py:161 — durable pending entry теперь создаётся до fire-and-forget, но успешный sync не закрывает эту же pending-запись. `yougile_sync_task()` добавляет новую `ok/error` запись, а pending с той же `sync_revision` остаётся pending, потому что skip update закрывает только `sync_revision < current`. Итог: dashboard/retry будут видеть вечные pending. Фикс: передавать `sync_log_id` в sync или после успеха обновлять pending rows текущей ревизии в `ok`.

- PARTIAL: app/tm_import_yougile.py:170 — per-task fake payments заменены на один consolidated payment, ledger-инвариант стал лучше. Но PAR-35 всё ещё не парсится: реальные даты/платежи/возможная предоплата теряются. Если нужна точная история денег из дизайна, это всё ещё не fixed.

- PARTIAL: app/tm_yougile.py:152 — перед push задача refetchится, и старые pending revisions помечаются `skipped`. Это снижает риск, но без job revision/sync_log_id текущая pending-запись не закрывается, а update, произошедший во время HTTP PUT, всё ещё может быть перетёрт более старым in-flight push.

- FIXED: app/tm_yougile.py:207 — ранний full-skip по marker убран; comment/column update теперь выполняются даже если description уже содержит marker. Остаточный риск: retry после успешного comment и упавшего column update создаст дубликат comment, потому что comment idempotency не проверяется.

- FIXED: app/tm_import_yougile.py:114 — sequence выставляется выше `MAX(known_pars)` до вставок, `_next_par()` для задач без PAR больше не должен конфликтовать с известными PAR из YouGile.

- STILL BROKEN: app/tm.py:590 — PAR-35/payment sync всё ещё не пишет `tm_sync_log`, поэтому ошибка `partial failure` не видна dashboard и не retryable через `/api/tm/sync/retry/{id}`.

### New Bugs

- blocking: app/tm.py:580 — `_fire_sync()` всегда логирует action=`update`, даже для новой задачи без `yougile_task_id`. Create sync потом пишет отдельный `create ok`, но исходный `update pending` остаётся висеть.

### Вердикт

NOT YET

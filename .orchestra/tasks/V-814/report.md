# V-814 — schema retries, workflow limits, and response evidence

## Проверка исходного прогона

Прочитаны артефакты `/home/kesha/orchestra/data/workflow-runs/V-219-586e65db76e0`: `request.json`, `manifest.json`, `journal.jsonl`, и все файлы до глубины 4 каталогов. В запросе три задачи со схемами. Manifest фиксирует `budget_usd=3`, `spent_usd=0.01617592`, `dispatched_calls=3`, `partial_reason=budget`. В журнале для каждой задачи есть `attempt_finished` (успешный вызов адаптера), `schema_invalid` с `invalid JSON: Expecting value at line 1 column 1`, и `retry_deferred` с `reason=budget`.

В коде `current_prompt` изначально был равен только пользовательскому prompt; схема попадала туда после невалидного ответа. `Budget.exhausted()` объединял `spent_usd >= maximum_usd` и `dispatched_calls >= maximum_calls`, а retry-ветка для обоих случаев писала `budget`. В исходном каталоге прогонов отсутствовали файлы с сырыми ответами: в журнале `schema_invalid` были только ошибка парсинга и номер попытки.

## Изменение

Schema JSON теперь включён в первый prompt и повторные запросы. После каждого `schema_invalid` сырой ответ сохраняется в `calls/<call-key>/attempt-<n>-schema-invalid.txt`; файл ограничен 64 KiB, UTF-8-префикс не разрывается посередине символа, а усечение отмечается в конце. В journal указываются относительный путь, сохранённый размер и факт усечения; полный ответ не дублируется в журнале.

`Budget.exhaustion_reason()` отдельно возвращает `budget` при достижении денежного потолка и `call_limit` при достижении лимита dispatch-вызовов. Оба значения проходят в `retry_deferred` или `skipped`, `partial_reason`, manifest и `_notification_summary`, из которого формируется wake-сообщение. Документация dynamic workflows описывает два независимых потолка.

Три regression-критерия: schema присутствует уже в prompt первой попытки; достижение `max_calls` при недостигнутом долларовом лимите даёт `call_limit` в журнале, manifest и уведомлении, а денежный предел сохраняет `budget`; invalid JSON оставляет сырой ответ в каталоге прогона с размером не выше 64 KiB.

## Проверки

Фокусные проверки regression-тестов: `uv run --frozen python -m pytest tests/test_wf_run.py -q -k 'schema_retries_twice or schema_retry_accepts_a_later or schema_invalid_raw_response or schema_retry_deferred_by_call_budget or budget_exhaustion_returns_none'` — 5 passed. Полный набор `uv run --frozen python -m pytest tests/test_wf_run.py tests/test_dynamic_workflows.py -q` — 80 passed. Абсолютный путь импортированного `app`: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-codex/app/__init__.py`.

## Живой прогон

`dynamic_workflow` на зафиксированном commit `c686f4aeaf7c581993931928c28aec3ff80bcf2e`: один schema-задачный вызов на `gpt-6-luna`, subscription route, `budget_usd=0.50`, `max_calls=2`. Manifest `V-814-6c0275ecefed` завершён: `complete=true`, `partial_reason=null`, один dispatch, расход `$0.00161632`. В журнале единственный `dispatched` — attempt 1; за ним `attempt_finished` и `completed`, событий `schema_invalid`/`retry_deferred` нет. Ответ шага прошёл указанную схему: `{"count":1,"status":"ok"}`. Запрос в сохранённом `request.json` содержит схему, а модель завершила первый вызов без retry.

Приложенная точная копия результата: [live-manifest.json](live-manifest.json). В выводе durable job также была строка `wf_run ... interrupted; resume with ...`; несмотря на это, итоговый manifest и `WORKFLOW_SUMMARY` завершены успешно. Это recovery-инструкция, а не статус финального результата.

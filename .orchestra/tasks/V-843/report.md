# V-843 — восстановление task_run при продолжении задачи

## Исправление

`switch_worker_branch(name, task_id)` при совпадающих задаче и ветке раньше возвращал `already_current` до обращения к task-store. После `PARTIAL`/`binding_released` это оставляло `sessions.task_id` прежним, хотя задача уже была `new` и без владельца; новый task_run не появлялся, поэтому `merge_worker` корректно отказывал с `WORK_ASSIGNMENT_CHANGED`.

Теперь тот же вызов в no-op ветке под блокировкой сессии вызывает `ensure_task_run_for_current_binding`. Helper в `BEGIN IMMEDIATE` проверяет неизменность identity и `sync_revision`, точную связь сессии с задачей, отсутствие резервации и допустимое состояние задачи. Он либо восстанавливает назначение `new`/свободной задачи этой сессии, либо подтверждает уже существующее назначение этой же сессии; затем открывает task_run. Изменение конкурирующего владельца, статуса, ревизии или резервации приводит к отказу, без переключения Git-ветки. Повторный вызов при уже открытом task_run остаётся идемпотентным.

Проверка merge не ослаблялась: при заданном `expected_head` изменившийся HEAD по-прежнему останавливает merge до вызова Git merge.

## Проверка

Добавлены два регрессионных теста в `tests/test_v843_reopen_task_run.py`:

- `test_v843_same_branch_switch_reopens_released_run_and_allows_merge` воспроизводит `binding_released`, вызывает штатный switch на ту же ветку, проверяет новый открытый task_run и успешное завершение merge.
- `test_v843_stale_worker_head_still_refuses_merge` передаёт прежний HEAD после нового коммита и проверяет отказ до запуска merge.

До исправления первый тест наблюдал `state=already_current` вместо `task_run_reopened`; это воспроизведение подтвердило дефект. После исправления: `uv run --frozen python -m pytest tests/test_v843_reopen_task_run.py tests/test_switch_after_continue_620.py tests/test_task_binding_417.py tests/test_task_runtime.py -q` — `22 passed in 39.93s`.

Мутационная проверка выполнена после коммита теста: временно возвращён старый ранний `already_current` без task-store шага, затем запущен закоммиченный `test_v843_same_branch_switch_reopens_released_run_and_allows_merge`. Он упал на `already_current != task_run_reopened` (1 failed); исходный код восстановлен, а повторный прогон 22 тестов прошёл.

## Возобновление fix-dashboard/V-831

После обновления кода и рестарта вызови:

```text
switch_worker_branch(name="fix-dashboard", task_id="V-831")
```

Так как задача и ветка уже совпадают, Git не переключается. Вызов восстанавливает task-store binding и открывает task_run, только если задача всё ещё свободна (`new`) либо уже принадлежит этому воркеру. Затем сними актуальные branch/HEAD через `worker_wip` и запускай обычный `merge_worker` с актуальным `expected_head`.

## Развёртывание

Изменён Python (`app/tm.py`, `app/routes/sessions.py`, `app/mcp_stdio.py`), поэтому после мержа нужен рестарт Orchestra, прежде чем повторять команду выше. Рестарт не выполнялся.

## CI follow-up

После мержа CI выявил два несовпадения. `test_same_task_switch_does_not_clear_ownership` сохранял только строку сессии и подменял scoped resolver, не создавая строку задачи в task-store. После изменения такой неполный снимок нельзя безопасно принять за отслеживаемую задачу, поэтому отказ 409 корректен; тест проверяет сохранение `owned_dirs`, а не работу task-store, и теперь подменяет `ensure_task_run_for_current_binding` результатом «уже привязан и run открыт». Настоящий путь с task-store проверяет `test_v843_same_branch_switch_reopens_released_run_and_allows_merge`; production resolver возвращает identity существующей scoped-задачи.

`test_switch_repairs_current_binding_then_becomes_clean_noop` показал, что `task_status` не нужен в ответе повторного здорового no-op. Поле удалено; состояние `already_current` снова имеет прежнюю форму ответа, а `task_run_reopened` продолжает явно сообщать о возобновлении.

После этих изменений пройден полный набор, запрошенный для регрессии: `uv run --frozen python -m pytest tests/test_api.py tests/test_lifecycle_quarantine_499.py tests/test_manager.py tests/test_switch_*.py tests/test_task_*.py -q` — `408 passed in 308.21s`. Полный вывод сохранён в [switch-regression-tests.log](switch-regression-tests.log).

## Mutation gate follow-up

`test_same_task_switch_does_not_clear_ownership` теперь проверяет весь ответ `already_current`, включая отсутствие дополнительных полей. После коммита теста вручную возвращал в `switch_branch` удалённый `task_status`; тест упал на полном сравнении словаря (`Left contains 1 more item: {'task_status': ...}`). После восстановления исходного кода `uv run --frozen python -m pytest tests/test_api.py::test_same_task_switch_does_not_clear_ownership -q` прошёл (`1 passed`).

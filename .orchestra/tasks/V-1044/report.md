# V-1044: восстановление контрактов merge после V-1034

## Изменено

- `app/merge_operations.py`: для новой операции проверка active operation и ограниченное ожидание idle снова выполняются **до** acceptance-валидации. Занятый воркер возвращает `WORKER_BUSY`; существующая активная операция возвращается по прежнему контракту. Полный SHA и meaningful note по-прежнему обязательны перед snapshot/admission. Повторная проверка idle после snapshot/admission и существующий replay не изменены.
- `tests/test_task_tracker_integration.py`: подмена `_build_squash_message` принимает новый третий аргумент `acceptance_note`, поэтому тест подмены task ref снова проверяет отказ под repository lock, а не случайный TypeError с `commit_point=unknown`. В двух тестах durable replay/checkpoint recovery запросы содержат реальный полный HEAD из созданного ими Git-репозитория и содержательный acceptance note. Добавлена проверка HTTP 202 до ожидания результата.
- `tests/test_taskless_merge_no_id_702.py`: передаются уже полученный реальный HEAD adhoc-ветки и содержательный note; исходные assertions `SESSION_HAS_NO_BOUND_TASK` / `PROMOTE_ADHOC_WORK` сохранены.
- `tests/test_v848_merge_timings.py`: разрешающие тесты передают полный SHA своего замоканного snapshot и содержательный note. Отрицательные active/busy/timeout тесты намеренно остаются без acceptance. Добавлены четыре случая: пустой/короткий SHA, placeholder-note и необходимость acceptance после завершения хода воркера.
- `tests/test_worktree_cleanup_v984.py`: общий helper успешного/неуспешного merge передаёт полный SHA своего замоканного worker identity и содержательный note. Исходные проверки очистки сохранены.

## Неочевидный root-commit случай

В предоставленном коде падающий `git rev-parse <target_after>^` находился в **тесте** `test_t3_first_post_git_checkpoint_loss_recovers_by_exact_trailer`. Запрос без acceptance не создавал merge: `target_after` оставался исходным root commit. Отсюда exit 128, а не доказанный production-дефект squash. Исправлен запрос; инспекция родителя заменена на `git log -1 --format=%P <sha>`, который для root корректно возвращает пустую строку. Assertion `parent == target_before` сохранён: тест по-прежнему требует настоящий дочерний squash commit, а не принимает root за успех.

Production `reconcile_prepared_commit` уже проверяет return code чтения родителя и не присваивает чужой root операции. Отдельно проверены неизменённый root, восстановление одного дочернего коммита с точным trailer/tree и отказ присвоить несвязанный root. Ослаблений проверки родителя, trailer или tree нет.

Правила V-1034 сохранены: полный 40-символьный SHA, запрет placeholder-note, заголовок по последнему subject/acceptance note, блокировка грязного target только при пересечении путей, compact output. `workspace.py`, `diff_budget.py`, `mcp_stdio.py` не изменялись.

## Фактическая проверка

Обязательная команда попыталась запустить **все 21 запрошенный файл**:

```sh
uv run --frozen python -m pytest tests/test_merge*.py tests/test_task_tracker_integration.py tests/test_taskless_merge_no_id_702.py tests/test_v848_merge_timings.py tests/test_worktree_cleanup_v984.py tests/test_workspace.py tests/test_work_acceptance.py -q
```

Результат: exit 127, `uv: not found on the hub and not inside a Mutagen-synced project (cannot forward via on-remote)`. Найденный `uv` — shim; реального runner нет. Лог: `required-tests.log`.

Офлайн fallback той же команды через `/usr/bin/python3.12 -m pytest`: exit 1, `No module named pytest`; лог `fallback-pytest.log`. В этой частичной копии также отсутствуют `fastapi`, `httpx`, `mcp`, `pytest_asyncio`, а из исходников — в частности `app/__init__.py`, `app/db.py`, `app/work_review.py`, `app/task_refs.py`, `scripts/run_tests.py`. Ничего не скачивалось и зависимости не подменялись ради зелёного pytest.

Абсолютный путь доступного namespace `app`: `<hub-workspace>`. Его `__file__` равен `None`, поскольку `__init__.py` не предоставлен. Полноценный импорт production-модуля не выполнен. Состав проверки и отсутствующие компоненты записаны в `validation.json`.

Доступные проверки:

1. Синтаксическая компиляция 23 файлов: production `merge_operations.py`, 21 запрошенный тестовый файл и fallback script — успешно.
2. `PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 nice -n 15 /usr/bin/python3.12 .orchestra/tasks/V-1044/offline_checks.py` с `TMPDIR` внутри каталога задачи — **17 unittest-проверок прошли**, лог `offline-checks.log`. Скрипт извлекает настоящие функции из AST, использует doubles для storage/manager/assignment и приватные локальные Git-репозитории для истории/родителей/trailer/tree. Это ограниченная проверка функций, **не эквивалент pytest/integration-прогону**.
3. Среди этих проверок: PENDING/RUNNING/PARTIAL/UNKNOWN active states; busy/timeout до acceptance; отказ invalid acceptance до Git; успешное завершение хода с acceptance и отказ без неё; drift HEAD; повторная busy-проверка; legacy replay; root и checkpoint recovery; отказ подмены task refs с новой сигнатурой builder; compact output. Возврат старого порядка валидации в памяти воспроизводит ошибочный `WORK_ACCEPTANCE_REQUIRED` для busy-воркера.
4. Изменённые участки просмотрены вручную: в копии нет `.git`, обычный git diff недоступен. Существующие outcome/cleanup/recovery assertions не удалялись и не ослаблялись. Артефакты проверены по формам секретов; временные Git-каталоги удалены самим fallback script.

## Что остаётся

Обязательный pytest-набор **полностью не выполнен**: до collection не дошёл ни один тест. Интеграция с реальными DB/task runtime, весь workspace merge и dirty-target сценарии требуют полного checkout и runner родителя. CI run 39785977845 здесь недоступен; зелёный CI не заявляется. Перезапусков, выкладки, push/commit в рабочем репозитории не было; Git-коммиты создавались только в временных тестовых репозиториях внутри каталога задачи. Передача результата родителю — через `.orchestra-outbox.jsonl`.

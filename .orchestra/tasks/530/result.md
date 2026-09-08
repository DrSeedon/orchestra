# #530 — сохранение знаний #504 поверх текущего main

## Результат и область

Production-перенос отменён постановщиком после обнаружения уже принятой реализации
`264daeb7` в main. **Ни одна строка `app/**` не менялась.** Основой оставлен
`67b1ada1130e67ed635263455e6a5c5dbd91a4ab`; версия #504 не мерджилась и не cherry-pick'алась.
Пофайловых конфликтов при записи не было: конфликтовали утверждения о текущем
контракте, их развязка дана в [дифференциале](diff-main-vs-504.md).

- Все **10 из 10** первоначальных A-площадок закрыты main; новых открытых исходных
  площадок не обнаружено. T4 уже удалён main, xfail не добавлялись.
- Сохранены 43 исторических артефакта #504 и их происхождение, добавлен README архива.
  Устаревшие current-state утверждения отозваны с указанием `264daeb7`.
- Записи KB дословно перенесены в существующие подразделы `agent-control.md`;
  отдельная тема удалена перед приёмкой. README совпадает с main, тем остаётся 16.
- Перенесены ровно два теста: stdout успешного фонового job может содержать прежнюю
  failure-фразу; модельная цитата round guard сохраняется не только в history, но и
  в new_messages для persistence. Оба тела взяты из #504 без изменений. Остальные кандидаты — отменённые
  контракты или уже имеющееся покрытие; причины поимённо перечислены в дифференциале.
- `check_anchors.py` явно проверяет только `1b795300`, не main. Историческая ветка
  `task-504/research-text-oracles` сохранена.

## Фактические проверки

Все pytest запуски: `PYTHONPATH=.` и
`/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q`, через
`systemd-run --user --scope -p MemoryMax=2G nice -n 15 env -u NOTIFY_SOCKET`.
В фоне дополнительно заданы обнаруженные `XDG_RUNTIME_DIR=/run/user/1000` и
`DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus`.
Точные argv, SHA, импортированные модули и RC — [checks.json](checks.json).

| Аргументы pytest / скрипт | Результат | Вывод |
|---|---|---|
| `tests/test_bg_jobs.py` | **55 passed**, RC=0, 7.62 s | [bg-jobs.txt](bg-jobs.txt) |
| `tests/test_harness_tools.py` | **28 passed**, RC=0, 4.43 s | [harness-tools.txt](harness-tools.txt) |
| `tests/test_bg_jobs.py::TestRunExecOutcome::test_t2_exit_zero_stdout_failure_phrase_is_not_rejected tests/test_model_text_control_flow.py tests/test_frontend.py::test_model_xml_is_displayed_without_execution_verdict tests/test_frontend.py::test_chat_request_uses_reserved_slot_ahead_of_background_gets` | **31 passed, 1 failed**, RC=1, 20.36 s; красный только известный reserved-slot frontend | [selected-and-main-controls.txt](selected-and-main-controls.txt) |
| `tests/test_frontend.py::test_chat_request_uses_reserved_slot_ahead_of_background_gets` отдельно | **1 failed**, RC=1; `Page.evaluate: Error: active GETs never drained: 1` | [main-frontend.txt](main-frontend.txt) |
| `PYTHONPATH=. /mnt/data/Projects/Python/orchestra/.venv/bin/python .orchestra/tasks/530/mutation_stdout.py` | **1 failed**, RC=1, 1.77 s; прежний stdout matcher переводит persisted job в failed | [mutation-stdout.txt](mutation-stdout.txt) |
| `tests/test_bg_jobs.py::TestRunExecOutcome::test_t2_exit_zero_stdout_failure_phrase_is_not_rejected` после мутации, новый процесс | **1 passed**, RC=0, 1.66 s | [restored-stdout.txt](restored-stdout.txt) |
| `PYTHONPATH=. /mnt/data/Projects/Python/orchestra/.venv/bin/python .orchestra/tasks/530/mutation_history.py` | **1 failed**, RC=1, 1.44 s; history сохранена, new_messages теряет модельную цитату | [mutation-history.txt](mutation-history.txt) |
| `tests/test_harness_tools.py::test_t3_model_authored_round_guard_prefix_survives_history_cleanup` после мутации, новый процесс | **1 passed**, RC=0, 1.51 s | [restored-history.txt](restored-history.txt) |

Main-воспроизведение выполнено на HEAD=main до коммита переноса. Проверка
`git diff --quiet main -- app tests/test_frontend.py tests/conftest.py pyproject.toml`
дала RC=0: frontend, production и тестовая конфигурация побайтно исходные. Изменённый
`test_bg_jobs.py` в отдельном frontend-прогоне не собирался. Тест не ослаблялся.

Импортированы именно модули текущего worktree:

```text
/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/land-504/app/bg_jobs.py
/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/land-504/app/session.py
```

Мутация применялась через `inspect/compile/exec` только к методу в памяти отдельного
процесса, без записи в app. Для new_messages использована обёртка run, возвращающая
старый prefix-фильтр только после завершения основного генератора.
Восстановление — завершение процесса и новый запуск с исходным main-модулем.
Оба теста хранятся в diff, воспроизводящие скрипты — в этой папке.

Первый диагностический background job не дошёл до pytest: отсутствовали две
переменные D-Bus. Сохранён [вывод ошибки запуска](main-t4-and-frontend.txt); это
не результат тестов. Временный файл для первоначальной xfail-пробы удалён без
выполнения после отмены старого задания. Ни один xfail не добавлен в итоговый diff.

## Проверка рисков и границы

Сверены сохранность production main, отсутствие возврата старого safeguard-fork,
request-only round hint и review finalizer, отсутствие T4-классификатора.
Проверены реальный subprocess, запись terminal job state и уведомление тестовой
сессии; old data и recovery не менялись. Архивные выводы не используются как доказательства
работы нынешнего production. Импортированная тема не заменяет 16-темную раскладку main.

Полный сьют и первоначальные семь модулей целиком не запускались: после смены задания
изменены только `tests/test_bg_jobs.py` и `tests/test_harness_tools.py`, оба проверены полностью; дополнительные контроли
указаны выше. Mutation на остальные тикеты не делалась, поскольку текстовые площадки
в этой работе не снимались и production-перенос отменён. Нет изменений схемы БД,
промптов, B/C, сервисов и VPS. Для этого результата рестарт не требуется.

Review route: по прочитанному `codex-debate` дополнительное модельное ревью необязательно.
Новый модельный запуск не делался: перенесены архив и два неизменённых теста,
production diff пуст, выполнены адресная самопроверка и мутация. Старое ревью Luna
оценивает ветку #504 и не выдаётся за независимую проверку #530.

Оставшаяся неопределённость: нет нового exhaustive-аудита всех app-сайтов и нового
измерения живого provider rejected; отдельный известный frontend-дефект остаётся.
Гейты KB, архива и проверка секретов записаны отдельно в `artifact-checks.txt`.

Уточнение команды KB: локального `.venv/bin/python` в worktree нет, использован
тот же интерпретатор по абсолютному пути. Кроме запрошенного запуска с Markdown в
`--diff`, выполнен реальный гейт с unified diff [kb.diff](kb.diff): валидатор читает
именно diff, а не содержимое темы. Первый вариант печатает OK при нуле разобранных
добавлений и сам по себе проверку темы не доказывает.
В настоящем diff разобраны **30 добавленных строк**, RC=0. Исторический checker:
**102 inventory + 17 document anchors, anchors_failed=0**, snapshot `1b795300`.
Гейт корневых инструкций также RC=0; корневые файлы не менялись.

Обычный `git diff --check` сообщает trailing whitespace в сохранённых выводах pytest.
Они оставлены побайтными историческими доказательствами. Проверка всех остальных
изменений исключает только файлы сырых выводов `.txt/.log` и сохранённый `.diff`.

Memory: updated — окружение D-Bus у background jobs и фактический формат аргумента
`--diff` KB-гейта сохранены в `.orchestra/workers/land-504.md`.

Уточнение перед приёмкой: владелец знаний — `agent-control.md`. Все 16 записей и
строк источников бывшей темы сохранены дословно, прежние записи владельца не менялись.
Гейт переноса проверен на `kb-owner.diff`; вывод — `kb-owner-check.txt`.

# V-1126 — гонка дедлайна в transport-oracle compact

Исправлен тест; production-код не менялся. Причина CI-сбоя подтверждена
детерминированным сдвигом часов event loop, без живого CLI, сети и ожиданий sleep.

## Причина

Autouse-фикстура `offline` устанавливает общий бюджет compact в 0.06 с.
В `compact_context()` этот бюджет начинается до ACK и охватывает всю операцию.
В `_read_stdout()` блок `finally` уже вызывает `_fail_compact_transport()` **до**
`await proc.wait()`: ошибка устанавливается в operation future, состояние освобождается,
а продолжение вызывающей задачи ставится в очередь event loop.

Если к этому моменту бюджет истёк, callback `asyncio.timeout` отменяет вызывающую
задачу раньше обработки готового future. Получается `TimeoutError` с
`remote_outcome=transport_closed`. Это допустимый результат истёкшего бюджета,
а прежний transport-тест ошибочно требовал победы транспортной ошибки при любом
расписании. Доказательств дефекта production-пробуждения нет; приоритет ошибок
и исходный production-дедлайн 120 с сохранены.

## Изменение и oracle

Только `test_transport_failure_wakes_every_stage_without_waiting_process` отключает
внутренний дедлайн (`asyncio.timeout(None)`). Внешний `asyncio.wait(..., timeout=0.5)`
ограничивает зависание и явно требует завершения задачи. Затем проверяются тип
и текст транспортной ошибки, освобождение compact и pending requests, стадия,
`outcome=failed` и `remote_outcome=transport_closed`.

Для EOF/read-error проверяется реальный вызов process.wait через AsyncMock,
ожидающий закрытый Event; JSONL reader при успешном пробуждении всё ещё заблокирован
на выходе процесса. Для disconnect проверяется отсутствие ожидания процесса.
Event остаётся закрытым до teardown; фикстура затем освобождает reader.

Все 3 транспорта × 3 стадии проверяются со сдвигом loop.time на 0 и 0.09 с.
Сдвиг делается после установки стадии и до инъекции закрытия транспорта.
Он делает прежний таймер 60 мс просроченным без изменения глобального monotonic
и без зависимости от скорости машины. Внешний watchdog создаётся после сдвига;
monkeypatch восстанавливает часы после teardown. Исходные тесты таймаута,
отмены, единого бюджета ACK/completion и восстановления не изменены.

`test_import_identity` теперь утверждает импорт именно текущего `app/__init__.py`
и печатает repo-relative путь. Абсолютный путь машины в публичный отчёт не попадает.

## Фактические проверки

Использован provisioned **uv 0.11.28**, `--frozen`, стандартная `.venv`, Python 3.12.3,
обычный `tests/conftest.py`. TMPDIR и pytest basetemp направлены в
`.orchestra/tasks/V-1126/runtime`. Зависимости установлены из lock;
сами compact-тесты сохраняют запрет сети, CLI и SQLite.

1. До правки: `uv run --frozen python -m pytest tests/test_codex_compact_state.py -q`
   с basetemp: **94 passed in 20.97s**, exit 0 (`baseline.txt`).
2. Добавлены stage/oracle assertions и clock injection, но ещё сохранён дедлайн
   60 мс: та же команда с `-k transport_failure_wakes_every_stage`:
   **9 failed, 9 passed, 85 deselected in 20.92s**, exit 1 (`scheduler-before.txt`).
   Все 9 вариантов с 90 мс дали именно `TimeoutError` / `transport_closed`;
   все 9 без задержки прошли. Это воспроизведение причины, а не повтор CI на удачу.
3. После отключения внутреннего дедлайна в oracle: **103 passed in 17.14s**.
   После окончательного усиления проверки process.wait:
   `uv run --frozen python -m pytest tests/test_codex_compact_state.py -q --capture=tee-sys
   --basetemp=.orchestra/tasks/V-1126/runtime/pytest`:
   **103 passed in 19.69s**, exit 0, **APP_IMPORT=app/__init__.py** (`after.txt`).
4. Отрицательный контроль:
   `uv run --frozen python .orchestra/tasks/V-1126/check_broken_wake.py`:
   **18 failed, 85 deselected in 31.29s**, ожидаемый exit 1 (`broken-wake.txt`).
   Плагин временно заменяет `_fail_compact_transport` на no-op только у synthetic
   backend. В 16 случаях внешний watchdog ловит pending waiter; в двух disconnect/ACK
   request сам получает ошибку, но проверка ловит оставшееся compact-состояние.
   Production-файлы не изменяются. Обычный запуск после контроля снова зелёный.

Текстовые evidence-файлы содержат реальные строки вывода; длинные traceback,
repr задач с частичными приватными путями и подробные логи исключены явно.
Diff проверен относительно исходной копии: изменён только указанный тестовый файл
и добавлены артефакты этой задачи. Публичные артефакты проверены `mask_secrets`
по форме секрета и поиском приватных путей, имени пользователя/хоста и runtime IDs.

## Ограничения

Полный host-набор и CI здесь не запускались: их выполняет родитель после DONE.
Результат этой копии не означает зелёный main CI. Иные тесты сохраняют существующий
короткий бюджет 60 мс; задача устраняет подтверждённую гонку transport-oracle.
Live CLI/model/provider/hub, ревьюеры, деплой, рестарты и Git-операции не запускались.
Поведение пользователей, данные, security/ownership/quota/routing-контракты и
CHANGELOG не изменены.

## Приёмка на host

Оркестратор прочитал полный отчёт и фактический diff, проверил отсутствие секретов и приватных идентификаторов во всех изменённых файлах. Обязательный `uv run --frozen python scripts/run_tests.py` в полном worktree завершился: **6684 passed, 54 skipped**, 446.53 s. Пропуски настоящих проверок владения без passwordless sudo сохранены явно. Импорт проверен из worktree данной задачи, публично — `app/__init__.py`.

Независимая мутация оркестратора отключила `_fail_compact_transport` у synthetic backend: все **18** committed transport/stage/delay cases стали красными на pending waiter или неосвобождённом состоянии. Исходники не изменялись; реальные логи сохранены приватно. Генерируемые браузерными тестами PNG сохранены и восстановлены. WIP чистый; результат принят и влит, временный hub-воркер закрыт. Дополнительного модельного хода после исчерпания hub-квоты не потребовалось: результат уже был сохранён.

Удалённый CI проверяется после публикации; локальная приёмка не выдаётся за зелёный CI. Эта правка меняет только тесты и не требует рестарта. Ранее принятые изменения Python имеют отдельную активацию через сторож простоя.

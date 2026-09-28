# V-650 — AUDIT/FINAL в compact-сессии

## Изменение

Черновик по-прежнему пишет исходный compact-ход Claude. После успешного хода `AgentSession.compact()` сохраняет журнал от последней compact-преамбулы в уникальный временный каталог `Path(db.DB_PATH).parent / "compact-sandbox"`, который лежит под `.gitignore` (`data/`) и вне репозитория агента. AUDIT, затем FINAL отправляются через тот же открытый backend и native session. FINAL редактирует файл сводки и становится текстом ack-преамбулы. Текст AUDIT/FINAL не обрабатывается как пользовательский вывод. Каталог журнала удаляется в `finally`.

Удалён прежний путь `agentic_compact.audit_summary()` целиком: больше нет отдельного `claude -p`, свежего черновика, fork/cold cache, sandbox root под БД и ручного сложения CLI cost. Каждая полученная сводка/AUDIT/FINAL turn-result проходит через `CostTracker.apply_turn_result`, который считает дельту cumulative usage одной session; quota permit для проходов не вызывается. Stop проверяется между проходами, таймаут — общий на оба; ошибки, пустой или слишком длинный итог оставляют исходный черновик и журналируют причину. Выключатель и отдельный Codex compact path сохранены.

SDK проверен в установленном runtime: `ClaudeSDKClient.query()` пишет в текущий transport, `receive_messages()` делегирует тому же `_query.receive_messages()`; SDK query читает общий `_message_receive`, завершая его только на событии `end`. AUDIT и FINAL поэтому потребляют один backend event stream между последовательными `send()`.

## Проверка

Команда:

```text
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q tests/test_agentic_compact_650.py tests/test_session.py -k compact tests/test_compact_pending_ack_467.py tests/test_compact_receipt_and_tail.py tests/test_compact_pending_rollback_467.py
```

Итоговая серия после переноса песочницы: **111 passed, 155 deselected**. Тесты core-контракта используют fake backend, мок источника журнала и временную БД из `tests/conftest.py`; CLI-провайдер не запускается. Проверяются подготовка journal-файлов, корень песочницы рядом с БД, замена draft→FINAL и session cost, fallback при ошибке/таймауте/пустой/слишком длинной сводке, stop между AUDIT и FINAL, выключатель. `git check-ignore -v data/compact-sandbox` подтвердил `.gitignore:15:data/`; `git diff --check` чист. В compact-пути вызовы backend не проходят через quota gate.

Импортированный модуль: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/impl-insession-compact/app/session.py`.

### Stop во время чернового хода

Первый полный merge-gate прогон выявил регрессию: после переноса проверки stop ниже AUDIT/FINAL прерванный черновик без `metadata.ok` шёл в retry и ждал 30 секунд. Проверка generation возвращена сразу после завершения/отключения backend черновика, до проверки ошибки и retry; если успешный черновик уже удержал backend, перед abort он закрывается. Поэтому stop на черновике завершает compact до аудита и ack, а проверка после двух проходов сохраняет stop между AUDIT и FINAL.

Команда полной серии:

```text
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q tests/test_session.py tests/test_agentic_compact_650.py tests/test_compact_pending_ack_467.py tests/test_compact_receipt_and_tail.py tests/test_compact_pending_rollback_467.py
```

Результат: **266 passed**.

## Ограничение

Реальный Claude CLI не запускался в соответствии с критерием тестов без провайдера; SDK lifecycle подтверждён локальной реализацией установленной версии и fake backend-тестом, но живой compact-turn не прогонялся.

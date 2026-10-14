# V-856 — штатные прерывания и завершившийся listener

## Наблюдения

В read-only запросе к `/home/kesha/orchestra/data/orchestra.db` проверены все 10 переданных ID (`logs.id`): каждый содержит `turn FAILED: error`. У записей 593380 и 593383 соседняя строка — `turn ended (interrupted, ...)`; у 654978, 655207 и 656476 перед ними есть `interrupt requested`; 677976 тоже завершает ход с `interrupted`. Поэтому список `errors` от CLI не является достаточным признаком сбоя: на остановленном ходе провайдер прислал общий текст `error`.

Для `tts-research` (session `62ebabd1-2f5e-4bc7-902a-7e5b8980716f`) последовательность ID 675140–675149 показывает: `interrupt requested` → штатный `turn_end(interrupted)` → `waiting for bg jobs` → `mailbox: 6 — продолжаю ход вместо пробуждения` → `listen task exited unexpectedly while RUNNING` → `turn FAILED: error` → новый Codex turn начат. Это указывает на гонку callback: завершившийся listener предыдущего хода проверял общий `session.status`, который уже стал `RUNNING` у нового хода. Callback не проверял, что завершившаяся asyncio task всё ещё является текущим listener. ID 675155 показывает повторный шум `turn FAILED: error` на следующем завершившемся как `interrupted` ходе.

## Изменение

`TurnManager.handle_turn_end` теперь трактует `stop_reason="interrupted"` как статус прерывания, даже если CLI добавил общий элемент в `errors`. Другие причины по-прежнему проходят прежнюю классификацию ошибок; тест фиксирует, что `stop_reason="error"` с provider error остаётся `error`.

`AgentSession._on_task_done` игнорирует callback, если его task уже не является `self._listen_task`. Так завершение прежнего per-turn listener не может сбросить новый `RUNNING` ход. Сбой текущего listener по-прежнему заканчивает ход с ошибкой.

## Проверка

Команда (повторена после обеих мутаций и восстановления кода; полный вывод в [tests.log](tests.log)):

```text
uv run --frozen python -m pytest tests/test_listen_task_done_648.py tests/test_session.py -k 'listen_task_done_648 or interrupted_turn_errors_are_not_logged_as_failure or failed_turn_still_logs_real_error' -q
```

Результат: `6 passed, 247 deselected in 4.50s`. Импортированный модуль: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/session.py`.

Обе committed регрессии проверены мутацией после коммита `d0ccbda4`. При отключении условия `sr == "interrupted"` тест `test_interrupted_turn_errors_are_not_logged_as_failure` упал на assertion об отсутствии `turn FAILED:` (`1 failed`). При отключении проверки идентичности listener тест `test_stale_listener_end_does_not_fail_a_new_running_turn` упал на assertion об отсутствии `silent death` (`1 failed`). После восстановления кода полный целевой набор прошёл: `6 passed`.

## Развёртывание

Нужен рестарт Orchestra после слияния: изменены Python-модули `app/session.py` и `app/session_turns.py`. Рестарт выполняет только владелец.

# V-848 — merge timing and busy-worker refusal

## Основание

Прочитаны V-840 §3 и §4, V-844 §4. В V-840 один merge-worker вызов занимал 82.38 с: 42.84 с до durable operation, 38.33 с runner и 1.20 с до ответа. В выборке V-844 у трёх runner отказ `WAITING` последовал после 712.67, 519.66 и 1,669.74 с, всего 48.4 минуты; test/mutation gates были пропущены, Git отказал как `WAITING`. Старые данные не разбивали admission и runner по стадиям.

## Изменения

Каждая durable merge operation теперь хранит `phase_durations_ms` внутри существующего `merge_operations.result_json`, который также возвращается в результате `merge_worker`. Измеряются общая подготовка до записи operation, snapshot, admission, очередь до первого runner claim, acceptance, mapped test gate, mutation gate, Git-вызов и finalization. Стадии, которые операция не запускала, имеют `null`; повторно выполненные стадии накапливают длительность. Это оставляет схему SQLite неизменной и позволяет собирать профиль SQL-выражением `json_extract(result_json, '$.phase_durations_ms.git')`.

Стадии измерены в местах исполнения: snapshot/admission вокруг фактических вызовов, queue от `created_at` до первого `started_at`, acceptance вокруг проверки принятого снимка и oracle, test/mutation gate внутри `evaluate_test_gate`, Git вокруг `merge_worktree_to_main`, finalization вокруг post-Git финализации. `finish_operation` переносит сохранённую карту в терминальный результат и пересчитывает его hash.

Новый вызов сессии, уже имеющей active merge operation, возвращает прежний результат блокировки до snapshot/admission. Если worker `running`, `accept_merge_operation` ждёт turn-completion event не дольше 60 секунд, затем продолжает обычный путь с новым snapshot/admission; статус `waiting` или отсутствие загруженной running-сессии приводит к немедленному `WORKER_BUSY`. Общий дедлайн начинается до подготовки, поэтому поздняя гонка не добавляет второй полный интервал ожидания. Runner повторяет ожидание до 60 секунд, если worker стал running после создания операции; если deadline истёк, durable operation завершается `WORKER_BUSY` до acceptance/test/mutation gates. Если занятость возникает уже после gates, merge route отказывает сразу, без многоминутного ожидания. Проверки HEAD, acceptance, test gate и mutation gate не пропускаются для проходящей операции; busy refusal Git не запускает. `switch_worker_branch` сохраняет прежнее ожидание.

## До/после на одинаковых воспроизведённых сценариях

Одинаковый сценарий конфликта с уже активной operation использует те же два mock-шва snapshot/admission с контролируемой задержкой 50 мс каждый. До изменения `accept_merge_operation` вызвал оба шва: 0.134 с общая задержка. После изменения ни один шов не вызывался: 0.012 с, то есть на 0.122 с (91%) меньше в этом воспроизведении. Это измеряет устранение лишней работы при отказе из-за active operation; оно не переоценивает исторические 42.84 с V-840 для принятой операции.

Одинаковый сценарий поздней гонки busy worker использует wait-callback с задержкой 50 мс. До изменения merge route ожидал callback и возвращал отказ через 0.051 с. После изменения merge route не вызывает callback и возвращает отказ меньше чем за 1 мс. Отдельная проверка switch-worker подтверждает, что его ожидание не изменилось.

## Выбор busy-wait дедлайна по журналам

Выбран дедлайн 60 секунд. По read-only данным `/home/kesha/orchestra/data/orchestra.db` за 2026-10-07—2026-10-14 извлечены 1,248 `turn ended` status logs для ролей worker/full-cycle из 111 сессий; 1,247 имеют совпадающий `turn_usage.event_id`. Внутри этих turn-интервалов найдено 460 DONE-prefixed `mcp__orchestra__send_message` tool calls, сгруппированных в 444 завершившихся хода; в 8 ходах было несколько DONE-сообщений, для времени взято последнее. У всех 444 пар найден соответствующий `tool_result`.

От возврата `send_message` до конца хода: p50 6.48 с, p75 10.00 с, p90 14.92 с, p95 38.74 с, p99 693.64 с, максимум 998.55 с. Через 60 секунд ещё не закончились 19/444 хода (4.28%); через 90 — 16/444 (3.60%), то есть дополнительное ожидание 30 секунд покрывает только ещё 3 хода (0.68 п.п.). Поэтому выбран нижний край диапазона, а длинный хвост завершится явным `WORKER_BUSY`. `done-turn-latency.log` содержит фактический агрегированный вывод и counting definition. MCP POST timeout установлен в 120 секунд, чтобы вместить 60 секунд ожидания плюс измеренный V-840 максимум pre-operation 42.84 секунды.

## Проверки

Добавлены `tests/test_v848_merge_timings.py` и проверка полного `already_current` ожидания в `tests/test_api.py`. Новые тесты проверяют короткий отказ при active operation и busy worker, отсутствие snapshot/admission/operation-row для busy worker, выдачу snapshot/admission/pre-operation и отдельных test/mutation timer, сохранение таймеров в БД и терминальном результате, а также git/finalization durations.

Полный затрагиваемый набор: `uv run --frozen python -m pytest tests/test_merge*.py tests/test_task_tracker_integration.py tests/test_api.py tests/test_lifecycle_quarantine_499.py tests/test_switch_*.py tests/test_task_*.py tests/test_mcp_stdio.py tests/test_v848_merge_timings.py -q` — `535 passed in 161.97s`. Вывод: [focused-tests.log](focused-tests.log). `app` импортирован из `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-spawn/app/__init__.py`.

После добавления bounded wait и MCP timeout прошёл точечный повтор: `uv run --frozen python -m pytest tests/test_v848_merge_timings.py tests/test_mcp_stdio.py::test_merge_worker_with_next_task_id tests/test_merge_operations.py::test_runner_rejects_removed_and_respawned_same_name tests/test_merge_stuck.py::test_primary_failure_blocks_until_it_is_explicitly_resolved tests/test_api.py::test_merge_refuses_running_worker_without_waiting_for_its_turn tests/test_api.py::test_switch_waits_for_running_worker_to_finish_turn -q` — `15 passed`. Он также подтверждает, что поздняя busy-гонка отказывает сразу, а `switch_worker_branch` сохраняет ожидание.

Мутационные проверки предыдущих плеч выполнены после коммита `62180ee3`, содержащего тесты. При отключении active-operation short-circuit `test_active_merge_conflict_is_rejected_before_snapshot_and_admission` покраснел: вызвались оба искусственно задержанных шага (`snapshot`, `admission`). При мутации `_merge_worker_is_idle` на безусловный `True` покраснел `test_busy_worker_is_rejected_without_waiting_for_its_turn`. Для текущего follow-up после фиксации тестов отдельно проверены bounded-wait плечи: немедленный возврат `running` вместо ожидания покраснил `test_running_worker_that_finishes_within_budget_is_accepted`; при timeout подмена результата на `idle` покраснила `test_running_worker_past_budget_returns_busy_without_snapshot_or_operation`. Обе мутации завершились ожидаемым падением, исходный код восстановлен. До мутаций полный затрагиваемый набор прошёл: 535 тестов за 161.97 с; после восстановления прошли 11 focused тестов за 6.73 с.

## Развёртывание

Изменён Python в `app/merge_operations.py` и `app/mcp_stdio.py`; после merge нужен рестарт Orchestra. Я его не выполнял.

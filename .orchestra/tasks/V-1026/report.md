# V-1026 — повторный auto-compaction по старому usage

Исправлено в переданной копии. Сервис не перезапускался. Git-репозитория в hub-копии нет; commit/push не выполнялись по контракту hub. Платформа должна сохранить результат в `task-V-1026/claude-runtime` с заголовком `#V-1026: reset context usage after compaction`.

## Причина и исправление

В `app/session.py::compact()` размер после сжатия вычислялся из расхода ack-хода только для события `finish` и возвращаемого результата. `_last_context` оставался прежним. Более того, `_persist()` вызывался до вычисления post usage: новый native session id сохранялся вместе со старыми `context_pct/context_tokens`.

`app/session_cost.py::CostTracker.update_context_from_turn()` при `DeferredContext` намеренно сохраняет последний известный контекст. `app/session_turns.py::TurnManager.handle_turn_end()` раньше допускал немедленное решение о compaction по этому значению, одновременно планируя асинхронное получение свежего usage. Поэтому следующая завершившаяся реплика могла снова запустить compaction по старым 95%.

Восстановление не создаёт отдельного pending-флага: `SessionManager._hydrate_row()` и `_load_from_db()` читают сохранённые `context_pct/context_tokens` обратно в `_last_context`. Это объясняет, как старое значение может пережить рестарт; утверждать, что именно рестарт был причиной данного инцидента, без его runtime-логов нельзя.

Изменения:

- `compact()` обновляет `_last_context` оценкой post usage до снятия `_compacting`, пробуждения очереди и финального сохранения. Расход нескольких API-вызовов делится на их число, как в прежней квитанции. Если расход отсутствует, старое значение сбрасывается в 0 с `known=False`. Успешный compact также отменяет оставшийся precompact timer. Неуспешный ack не проходит через этот сброс.
- Deferred turn result больше не запускает compaction по кешу: решение принимает свежий API-ответ. Новый настоящий usage выше порога продолжает запускать compaction.
- `_refresh_context_from_api()` отбрасывает ответ, если за время ожидания сменился backend, native session id или поколение хода. Старый запрос не может вернуть прежние 95% после переключения контекста.
- Обновлён существующий тест, который требовал compaction по кешированному DeferredContext; добавлен `tests/test_double_compaction_v1026.py`. Замороженных acceptance-тестов в задании не было.
- Добавлена запись в `CHANGELOG.md`.

## Проверка

Использованы зависимости из неизменённого `uv.lock`. В hub отсутствовал исполняемый uv: установлен task-local bootstrap в игнорируемой `.venv`, затем выполнен `uv sync --frozen`. Сами тесты и мутации запускались с `--offline`, без provider CLI, сети и боевой БД. Импортированный `app` проверен сравнением разрешённого `app.__file__` с `Path.cwd() / 'app/__init__.py'`; это `app/__init__.py` данной копии. Абсолютный hub-путь намеренно не записан согласно заданию.

Финальная команда (здесь `uv` — `.venv/bootstrap/bin/uv`, `UV_CACHE_DIR=.venv/uv-cache`, `TMPDIR` направлен в task-local `tmp/`; процесс запущен с nice 15):

```sh
uv run --frozen --offline python -m pytest \
  tests/test_double_compaction_v1026.py \
  tests/test_agentic_compact_650.py \
  tests/test_compact_pending_ack_467.py \
  tests/test_compact_pending_rollback_467.py \
  tests/test_compact_receipt_and_tail.py \
  tests/test_context_overflow_v995.py \
  tests/test_compact_gate_438.py \
  tests/test_usage_contract.py tests/test_turn_usage.py \
  tests/test_session.py::TestPrecompactTimer \
  tests/test_session.py::TestRateLimitClassification \
  tests/test_session.py::TestRetryAdmissionRaces \
  -q --basetemp=.orchestra/tasks/V-1026/pytest-final
```

**134 passed in 6.79s**, полный вывод: [final-tests.log](final-tests.log). Предварительный целевой набор: 80 passed, [focused.log](focused.log).

Новые тесты проходят реальный путь `compact()` → ack `AgentEvent` → `_handle_event()` → `TurnManager`, проверяют post usage и состояние при освобождении compaction, snapshot для БД и восстановление через настоящий `_hydrate_row()`. Проверены один и три API-вызова, отсутствие usage, отказ ack, отсутствие немедленного повторного запуска, разрешение по новому высокому usage, запоздавшие ответы после смены backend/native id/поколения хода. Соседний набор покрывает native Codex compaction, очереди входящих сообщений, rollback, лимиты и отложенные продолжения.

Первый локальный прогон новых тестов дал 7 passed / 1 failed: тестовая доставка ack обходила `_handle_event()`, где устанавливается число API-вызовов. Доставка исправлена на production-путь; делитель в коде не подгонялся под тест.

### Мутации

Запущен [mutation_check.py](mutation_check.py) через `uv run --frozen --offline python`, с `UV_BIN=.venv/bootstrap/bin/uv`. Скрипт последовательно временно изменяет только целевой source-файл, запускает соответствующий тест из нового regression-файла и восстанавливает оригинал в `finally`.

| Удалённая защита | Результат |
|---|---|
| Обновление `_last_context` после ack | 2 failed: остались 945985 токенов при освобождении compaction |
| Запрет решения по DeferredContext | 1 failed: немедленно вызван `_auto_compact(delay_seconds=0)` |
| Проверка принадлежности ответа текущему контексту | 3 failed: старый ответ вернул 945985 вместо 104899 |

Все три запуска вернули exit 1 именно на поведенческих assertions. Выводы: [mutation.log](mutation.log), [context reset](mutation-context-reset.log), [deferred gate](mutation-deferred-gate.log), [stale refresh](mutation-stale-refresh.log). После восстановления исходников выполнен финальный зелёный набор из 134 тестов.

Проверены компилируемость изменённых Python-файлов, отсутствие хвостовых пробелов и task-логи фильтром `app.secret_mask.mask_secrets` — изменений фильтра нет. Hub-пути в логах заменены относительными. Тестовые временные каталоги и bootstrap-логи исключены task-local `.gitignore`.

## Границы результата

Post usage по-прежнему является прежней оценкой среднего размера API-вызова ack-хода; это не новый точный token counter. Свежий API-ответ уточняет значение. При недоступном API DeferredContext теперь не инициирует автоматическое сжатие по старому кешу; это намеренный выбор, предотвращающий повторный запуск без нового измерения.

Полный suite не запускался: копия частичная, без `.orchestra/pipelines/`, KB и `scripts/run_tests.py`. Тест восстановления использует настоящий detached loader и DB snapshot, но не запускает сервер и полный `_load_from_db()` с восстановлением prompts/backends. Падение процесса посреди ack и живой SDK не воспроизводились. Приведённые timestamps инцидента получены из задания; боевые логи не читались. Изменение Python станет рабочим только после merge и отдельного разрешённого владельцем рестарта.

## Проверка после восстановления hub-копии

В восстановленной копии прочитаны три исправления в `app/session.py` и `app/session_turns.py`, новый regression-файл и изменённый deferred-context тест в `tests/test_session.py`; код и ранее сохранённые результаты присутствуют. Повторный запуск `uv run --frozen --offline python -m pytest tests/test_double_compaction_v1026.py -q` завершился до запуска Python с exit 127: `uv: not found on the hub and not inside a Mutagen-synced project (cannot forward via on-remote)`. `.venv` в восстановленную копию не попала. Вывод сохранён в `resumed-tests.log`, контрольные суммы исходников — в `resumed-source.sha256`.

Следовательно, 134 passed и результаты трёх мутаций выше — сохранённые результаты предыдущего прогона, а не новый прогон после восстановления. Импорт `app` после восстановления не выполнялся. Исходники при возобновлении не изменялись; commit/push, установки зависимостей и перезапуски не выполнялись. Перед интеграцией следует повторить указанную финальную команду в окружении с зависимостями из `uv.lock`.

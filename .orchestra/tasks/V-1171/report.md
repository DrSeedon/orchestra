# V-1171 — изоляция restart-тестов CI

Исправлен тестовый контекст в `tests/test_hot_apply.py`; продуктовый код,
рестарт-защиты, авторизация и бюджеты ожидания не менялись. Changelog не менялся:
продуктового изменения нет. Ветка результата: `task-V-1171/fix-ci-restart`;
коммит создаёт брокер, worker не выполнял Git-операций.

## Причина и границы доказательства

Пять тестов подменяли только `system._drain_sessions()`. Это задавало сессии для
подсчёта прерванных ходов, но реальный durable drain независимо читал
`system.manager.sessions`. Тест мог ждать чужие сессии из предыдущего теста.
Pending log future, чей event loop уже закрыт, остаётся pending даже после
окончания executor-операции: доставить завершение через закрытый loop невозможно.
Внутренний бюджет дренажа длиннее внешних 0,5/5-секундных ограничителей этих тестов.

Детерминированная подложка такой сессии воспроизвела **ровно все пять указанных
TimeoutError**. Стек совпал: `_prepare_restart_service` → `_do_restart_service` →
`_drain_restart_durable_state` → `drain_restart_persistence` →
`_drain_handoff_log_writes` → `_await_log_futures` → `asyncio.wait` → CancelledError.
Это доказанный дефект изоляции тестов; изменение reports не объявляется причиной,
а исходный CI не объявляется flake. Конкретный предшествующий тест, оставивший
сессию в исходном shard 2, не установлен: его порядок и приватный лог не читались.
Синтетический pending future моделирует возможное состояние, а не доказывает
конкретного производителя утечки в исходном CI. Продуктовый дефект не установлен.

## Исправление и регрессия

- `restart_sessions` временно устанавливает один реестр тестовых сессий в manager;
  и подсчёт прерываний, и настоящий durable drain читают его. `monkeypatch`
  восстанавливает прежнее значение, не очищая чужой реестр.
- `_FakeSession` явно реализует успешный drain пустого журнала; отсутствующий метод
  не превращается в ложную потерю журнала. Исходные проверки пяти тестов сохранены.
- Новая регрессия подставляет старую сессию с future из закрытого loop, устанавливает
  текущую настоящую `AgentSession` с pending log future и проходит реальную цепочку
  manager/session. До завершения текущей записи сигнала и outcome-записи нет;
  затем порядок — outcome-запись, сигнал. Старый future остаётся нетронутым.
  Провайдеры не запускаются, запись и сигнал подменены.

## Фактические проверки

Runner: provisioned **uv 0.11.28**, `uv run --frozen python -m pytest`, default
`.venv`, зависимости из неизменённого `uv.lock`.
Подтверждён импорт: **`importpath=worker-copy/app/__init__.py`** (путь нормализован
относительно приватной копии). Все явно заданные basetemp находятся в `/tmp/`,
вне checkout; БД, tmp и сырые логи не входят в публикуемый отчёт.

| Проверка | Результат |
|---|---|
| Исходный `tests/test_hot_apply.py` без подложки | 21 passed, 12.91 s |
| Исходные пять T3 с pending future старого loop | 5 failed (ожидаемое воспроизведение), 16 deselected, 19.53 s |
| Исправленные пять T3 + новая регрессия с той же подложкой | 6 passed, 16 deselected, 4.09 s |
| Целевой соседний набор, `-n 2 --dist=loadscope --timeout=30` | 80 passed, 4 subtests passed, 11.06 s; 0 failed, 0 skipped |
| Мутация `original-seam`: вернуть подмену только `_drain_sessions` | Новая регрессия красная: 1 failed, TimeoutError, 5.11 s |
| Мутация `skip-durable`: обойти реальный durable barrier | Новая регрессия красная: 1 failed, TimeoutError, 5.50 s |
| После восстановления обеих мутаций, публичный seed helper, `-n 2 --dist=loadscope --timeout=30` | 6 passed, 9.93 s; 0 failed, 0 skipped |

Обе мутации выполнялись последовательно и восстановили исходные байты файлов в
`finally`; отрицательные результаты не считаются успешными прогонами тестов.
`check_regression.py` сохраняет эти два независимых контроля для повторения root
на закоммиченном брокером результате. Worker не мог проверить commit SHA: `.git`
в копии отсутствует.

В соседний набор вошли целиком `test_hot_apply`, `test_system_restart`,
`test_seamless_restart`, `test_restart_durable_transfer`, `test_restart_inbox`,
`test_restart_continuation_919`, `test_restart_cut_recovery_1057`,
`test_v1020_log_drain_bounded`, а из `test_restart_generation_liveness` — восемь узлов:

```text
test_t1_production_path_arms_guard_after_interrupt_mark_and_durable_state
test_t1_durable_state_timeout_still_restarts_and_reports_journal_loss
test_t1_locked_log_write_is_retried_before_reporting_success
test_t1_restart_response_contains_current_journal_loss
test_t1_manager_durable_drain_snapshots_and_waits_for_every_session
test_t1_real_durable_barrier_enforces_budget_and_failure_identity
test_t1_real_durable_barrier_names_persistent_log_loss
test_t1_after_arm_signal_failure_aborts_guard_before_reopening_admission
```

Проверены mailbox ack/retry/доставка, восстановление прерванных ходов, admission,
порядок сохранения/взведения защиты/сигнала, ограничение durable drain, повтор записи
при DB lock, явный journal loss и откат после ошибки сигнала. Реальные signal/guard
subprocess-тесты, провайдеры, сервисы и полный suite не запускались. Финальная
приёмка, проверка полного shard и CI принадлежат root.

Для повторения подложки: добавить эту task-директорию в `PYTHONPATH`, передать
pytest `-p seed_previous_loop` и выбрать
`tests/test_hot_apply.py -k 'test_t3_ or test_restart_context'`.
Для отрицательных контролей запускать `check_regression.py original-seam` и
`check_regression.py skip-durable` через provisioned uv последовательно, без
другого pytest в этом checkout. Логи лежат только в игнорируемой
`private-evidence/`; helper-скрипты содержат лишь синтетические данные.

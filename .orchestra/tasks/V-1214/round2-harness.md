# V-1214: lifecycle harness без случайного performance budget

Повторное падение после первого исправления: merge
`ee13b82e-da00-4506-9651-0aceed23c52b`, session success получил timeout стадии ACK
за 0,109 с, а native terminal пришёл за 0,11 с. Старый merge не повторялся.

## Исправление

Общая autouse-фикстура `offline` больше не устанавливает всем compact-операциям
60-мс бюджет: для обычных lifecycle-сценариев тестовый timeout равен `None`.
Их существующие независимые watchdogs harness остаются 0,5 с.

Проверки, которым действительно нужен timeout, явно включают `compact_clock`:
используются настоящий `asyncio.timeout` и управляемые часы текущего event loop.
Прежние 60 мс не повышены: тест сам пересекает deadline, пропускает cancellation
через JSONL-барьер и проверяет outcome `timeout` перед чтением результата.
После этого часы и бюджет возвращаются к обычному lifecycle-режиму. Это необходимо
для deferred callbacks очереди, listener и cleanup после истечения бюджета.
Фикстура также восстанавливает часы в `finally`, включая падение assertion.

Guard общего deadline ACK + completion использует те же реальные asyncio-механизмы
и прежний бюджет 0,2 с, ACK в 0,12 с, success в 0,19 с и поздний completion в 0,24 с.
Проверки pending до deadline и TimeoutError до позднего completion сохранены.

Recovery после retryable error, native interrupt и все четыре session/hibernate
исхода параметризованы паузой 0 / 0,11 с перед ACK. Пауза детерминированная:
сдвиг нижележащих monotonic-часов и два прохода event loop, без реального ожидания.
У clock-controlled timeout-сценариев от такой паузы бюджет не расходуется.
Добавлено шесть вариантов: прежние 104 / 295 тестов стали 110 / 301.

Сохранены assertions успеха, ошибки, отмены, удержания owner, поздней reconciliation,
контекстных токенов, disconnect/hibernate, listeners и очереди. Проверка отсутствия
`turn/started` теперь требует конкретный RuntimeError вместо альтернативы TimeoutError;
timeout/cancel требуют точную стадию, session timeout — точный outcome и stage.

Production-код, продуктовый timeout 600 с, зависимости, lock и changelog не менялись.
Новые абстракции находятся только в тесте.

## Проверки и мутации

Все команды использовали provisioned **uv 0.11.28**, `uv run --frozen python`,
стандартную `.venv`, `TMPDIR=/tmp` вне checkout и `-m 'not live_probe'`.
Сеть, реальные CLI/provider и SQLite заблокированы общей offline-фикстурой harness.

- Весь `tests/test_codex_compact_state.py`: **110 passed, 13,93 с**.
- Полный связанный набор из предыдущего отчёта: **301 passed, 23,86 с**.
- Тот же набор с дополнительной детерминированной паузой 0,11 с перед первым
  ACK каждого теста общего Harness: **301 passed, 38,60 с**. В session-вариантах
  с собственной паузой это суммарно 0,22 с до ACK; обе контрольные deadline-ветки
  и связанные delivery/immediate тесты также прошли. Ретраи не настроены.
- [Сброс deadline после ACK](reset-deadline-after-ack.patch):
  **1 failed, 1 passed**, причина `ACK must not reset the compact deadline`.
- [Возврат общего 60-мс бюджета](restore-short-harness-budget.patch):
  **1 failed, 7 deselected**. Именно `scheduler-pause-success` получил `ok=False`:
  timeout ACK в 0,110 с, native completed/compacted в 0,111 с. Это воспроизводит
  симптом merge и проверяет корень нестабильности фикстуры.

Обе мутации сняты в `finally`; production-source и тест восстановлены перед
итоговым стресс-прогоном. Патчи остаются доказательствами и не применены к коду.

При разработке два диагностических запуска выявили зависание recovery очереди,
пока часы оставались заморожены после timeout; один остановлен после 100 passed,
второй подтвердил место через faulthandler. Это исправлено восстановлением часов
в `expire()`; итоговые проверки выполнены на исправленном коде.

Сырые логи, provenance и временные скрипты находятся только в ignored `raw/`.
Финальный diff проверен; импорт `app` из текущей копии, неизменность backend и
проверка добавленных строк/публичных артефактов фильтром секретов подтверждены.
Полный repository suite и живой сервис не запускались. Перенос файлов и новый
коммит в ветку воркера выполняет платформа; commit/push и повтор merge не выполнялись.

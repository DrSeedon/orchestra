# V-1214 — общий deadline native compact

Актуальное исправление общей нестабильности harness и проверки второго раунда:
[round2-harness.md](round2-harness.md). Ниже сохранён отчёт первого раунда;
он предшествует повторному падению session lifecycle на общем 60-мс бюджете.

Исходное падение: main `ef5cc8268`, CI run `41390641406`, shard 1,
`test_one_deadline_includes_ack_and_completion`.

## Причина и изменение

В `CodexBackend.compact_context` один `asyncio.timeout` уже охватывает ACK,
completion и terminal. Ошибка была в тестовом oracle: позднее возобновление
продолжения теста позволяло второму таймеру установить `too_late` после правильного
таймаута операции, но до проверки флага. Такой флаг не доказывал нарушение deadline.

В тесте сохранены настоящий asyncio timeout и JSONL harness (reader, request,
ACK, native notifications). Управляются только часы текущего event loop, как в
существующем transport-тесте этого файла. Задержки настенного времени больше
не меняют положение проверки относительно виртуальных deadline и completion.

Проверяются две ветки при неизменном тестовом бюджете 0,20 с:

- ACK в 0,12 с, completion в 0,19 с: успешный результат.
- ACK в 0,12 с, операция ещё pending в 0,19 с; в 0,21 с она завершена
  `TimeoutError` на стадии `completion notification`, а таймер completion
  в 0,24 с ещё не сработал. Затем поздние completion/terminal освобождают owner.

Барьер `h.deliver()` пропускает готовые задачи reader/cancellation через реальный
планировщик, не двигая виртуальные часы. Проверка `task.done()` перед ожиданием
результата одновременно обнаруживает продление бюджета и предотвращает зависание
отрицательного теста при замороженных часах.

Production-код восстановлен побайтно после mutation-проверки и не входит
в изменение. Продуктовый таймаут, timing window, зависимости и changelog не менялись.

## Проверки

Runner: provisioned uv **0.11.28**, `uv run --frozen python`, стандартная `.venv`,
`TMPDIR=/tmp` вне checkout. Во всех pytest-прогонах использован локальный `app`;
абсолютный путь проверяется отдельно и сохраняется только в ignored raw-артефакте.
Live probes исключены; реальные CLI/provider и рабочая БД не использовались.

1. Исходный тест: **1 passed**.
2. Детерминированная задержка observer после получения правильного TimeoutError:
   исходный тест падает именно на `assert not too_late.is_set()`. Перед задержкой
   diagnostics: outcome `timeout`, stage `completion notification`, elapsed
   0,204 с, ACK/started 0,121 с. Это воспроизводит гонку без продуктового дефекта.
3. Первичная проверка нового oracle: **2 passed**.
4. Сохранённая мутация [reset-deadline-after-ack.patch](reset-deadline-after-ack.patch)
   перепланирует существующий timeout на `now + budget` после ACK.
   Результат: **1 failed, 1 passed**, точная причина —
   `ACK must not reset the compact deadline`; в 0,21 с операция остаётся pending.
   Разрешающая ветка проходит. Мутация снята в `finally`, исходный backend сверён.
5. Первый полный связанный прогон: **293 passed, 2 failed**.
   `test_retryable_error_can_recover` и `test_native_interrupt_uses_compact_turn`
   истекли по существующему 60-мс тестовому timeout; новый oracle прошёл.
   Эти тесты и их бюджеты не менялись; результат сохранён, повторные попытки
   в pytest не настроены.
6. Контрольный прогон с добавленным `--timeout=30`: **294 passed, 1 error**.
   Watchdog прервал первый setup на импорте схем aiogram/pydantic за 30 с;
   это ограничение прогона, не таймаут compact. Остальные тесты прошли.
7. Штатная команда ниже, без дополнительного watchdog: **295 passed за 39,12 с**.
   Весь `test_codex_compact_state.py` и перечисленные backend/caller тесты зелёные.
8. Дополнительная инъекция задержки observer: после правильного TimeoutError
   нижележащие monotonic-часы сдвинуты на 0,25 с, выполнены два прохода
   event loop. Новый oracle: **2 passed**; его управляемые часы сохраняют
   порядок deadline/completion независимо от позднего observer.

Сверка backend с исходным снимком, импорт `app` из текущей копии и проверка
публичных артефактов фильтром `app.secret_mask.mask_secrets` прошли.

Команда связанного прогона:

```sh
uv run --frozen python -m pytest \
  tests/test_codex_compact_state.py \
  tests/test_backend_codex.py \
  tests/test_backend_stream.py \
  tests/test_codex_compact_delivery_1150.py \
  tests/test_codex_compact_immediate_1150.py \
  tests/test_double_compaction_v1026.py \
  tests/test_compact_receipt_and_tail.py \
  -q -m 'not live_probe'
```

Сырые логи и временные скрипты лежат в `raw/`, исключённом локальным `.gitignore`.
В публичный отчёт не копируются абсолютные пути окружения и сырые traceback.

Полный repository suite и живой сервис не проверялись. Изменение касается теста,
форматов данных и миграций нет. Коммит и перенос в заданную ветку выполняет
платформа после завершения воркера; здесь команды commit/push не запускались.

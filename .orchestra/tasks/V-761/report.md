# V-761: скорость моделей в аналитике

## Измерение

Claude сохраняет CLI `duration_ms` и `duration_api_ms`; для скорости используется API duration, когда он положительный. Полная длительность хода сохраняется отдельно. Для Codex adapter получает `item/started` и `item/completed`, у обоих событий есть `params.item.id` и `params.item.type`; эти поля уже используются при обработке, поэтому живой ход для выяснения формы событий не требовался. Tool intervals измеряются локальным monotonic clock для `commandExecution`, `fileChange`, `mcpToolCall`, `dynamicToolCall`, `webSearch`, `imageView`, `imageGeneration`, `sleep` и `collabAgentToolCall`. `reasoning` и `agentMessage` не входят в этот набор и остаются модельным временем.

Для Codex model-time estimate = wall duration от `turn/start` до terminal event минус объединение tool intervals. Объединение убирает двойной вычет при параллельных инструментах. В БД остаются полная длительность, эффективная `api_duration_ms`, `duration_basis`, raw provider API duration, сырая сумма интервалов, их объединение, количество интервалов и количество несопоставленных событий; estimate также хранится отдельно. Если провайдер передаст native API duration, она становится эффективной длительностью с `duration_basis='api'`; иначе используется estimate с `duration_basis='model_estimate'`. Если tool завершился без наблюдённого start, basis становится `incomplete`, и ход исключается из скоростного сравнения вместо подстановки полной длительности с инструментальным ожиданием.

Claude/Codex сохраняют отдельный `reasoning_tokens`, только когда backend его возвращает. Reasoning tokens не прибавляются повторно к `output_tokens`: OpenAI документирует их как часть output token total ([Agents API observability and usage](https://developers.openai.com/api/docs/guides/agents-api/observability)). Время до первого токена не добавлялось: normalized terminal data не содержит общего значения для обоих backend.

Скорость успешного хода — `output_tokens / effective_duration_seconds`. Аналитика группирует индивидуальные скорости по `(runtime, model)` и считает медианы за скользящие 1 час и 24 часа. График агрегирует медианы по часам при периоде до 30 дней и по дням на более длинном периоде. Для Codex `model_estimate` остаётся оценкой: границы инструментов не дают точных границ API генерации, поэтому остаток включает transport/adapter overhead.

`ensure_turn_usage_timing_schema()` добавляет недостающие nullable timing/interval колонки при старте после `init_db()`; новые базы получают их из `app/schema.sql`. Исторические записи остаются без длительности. UI помечает `API time`, `Model-time estimate` или `Turn time`; строки с `incomplete` basis и старые строки без валидного времени не становятся скоростными точками.

## Проверки

`uv run --frozen python -m pytest tests/test_backend_claude.py tests/test_backend_codex.py tests/test_turn_usage.py tests/test_usage_analytics.py -q` → `170 passed in 48.76s`.

`uv run --frozen python -m pytest tests/test_usage_analytics_frontend.py -q` → `18 passed in 31.20s`.

Codex regression test включает command interval `[20,100]s` и перекрывающий его MCP interval `[60,110]s`: reasoning и agentMessage events остаются модельным временем; при wall duration `130s` сырая сумма равна `130s`, union — `90s`, model estimate — `40s`. Для тех же `2,000` output tokens контрольный ход без инструментов с длительностью `40s` даёт ту же скорость. Отдельные проверки подтверждают: `item/completed` без start даёт `basis=incomplete`, `api_duration_ms=NULL`, и analytics исключает эту строку; tool event с ID прежнего turn не попадает в расчёт следующего. Проверяются также provider API duration при длинном wall time, сохранение timing полей через `TurnManager` для Claude и Codex, миграция старых строк без заполнения, API payload и браузерное отображение.

`node --check app/static/js/analytics.js` и `git diff --check` прошли. Рестарт не выполнялся. Python-код и schema migration заработают после рестарта по слову владельца; JS/CSS горячие.

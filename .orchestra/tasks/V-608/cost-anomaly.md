# V-608 — источник аномальной стоимости Claude

## Сводка

Источник числа — финальный `result`-кадр Claude Code CLI. Python SDK не считает
стоимость и не меняет её: он переносит `data["total_cost_usd"]` в
`ResultMessage.total_cost_usd`. В CLI это накопительная стоимость native Claude
session (включая предыдущие ходы resumed thread), а `result.usage` в том же кадре
содержит расход текущего хода.

Виновата наша граница процесса, не провайдер и не `resume` как таковой. Orchestra
сохраняет native `session_id`, но не сохраняет `_last_cost`. После рестарта новый
`CostTracker` начинает с `_last_cost = 0`; первый resumed `total_cost_usd` принимается
за цену одного хода. Следующий ход уже вычитает этот baseline и выглядит нормально.

Рекомендуемый вариант: для `turn_usage.cost_usd` считать текущий ход из его token
usage по уже принятой локальной тарифной формуле, а provider cumulative cost оставить
только диагностическим сырым значением. Это устраняет ошибку на рестарте и не зависит
от того, сохранился ли in-memory baseline. Альтернатива — сохранять provider
baseline/session-id в БД и восстанавливать его при старте; она меньше меняет
арифметику, но оставляет учёт зависимым от семантики CLI и требует миграции/атомарной
синхронизации.

Код в рамках исследования не изменялся. Живая БД открывалась только через SQLite
`mode=ro`; настройки процесса и рестарт не выполнялись.

## Цепочка значения

1. `app/backend_claude.py:908-985` строит `ClaudeAgentOptions`. Вызов явно выбирает
   `cli_path = shutil.which("claude")`; для resumed session ставится
   `options.resume = resume_id` (`:959-961`). Runtime получает один persistent native
   session id, а не новый id на каждый ход.
2. Установленный Python SDK — `claude-agent-sdk==0.2.114` из `pyproject.toml` и
   `uv.lock`. Его файл
   `.venv/lib/python3.12/site-packages/claude_agent_sdk/_internal/message_parser.py`
   в ветке `case "result"` (`:290-317`) делает буквально:

   ```python
   total_cost_usd=data.get("total_cost_usd")
   usage=data.get("usage")
   model_usage=data.get("modelUsage")
   ```

   Здесь нет пересчёта, дельты или суммирования.
3. SDK transport запускает CLI как `--output-format stream-json --verbose`;
   `app/backend_claude.py` передаёт системный `/usr/bin/claude` напрямую. На диске
   `/usr/bin/claude` — symlink на
   `/usr/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe`, package version
   `2.1.278`. Поэтому реально используется CLI 2.1.278, а не bundled CLI SDK
   (`_cli_version.py` сообщает `2.1.205`) и не зафиксированная в
   `app/runtime_history.py` версия `2.1.197`. Это отдельный drift риска, но он не
   объясняет саму арифметическую ошибку: наблюдаемая семантика CLI подтверждена ниже.
   npm-поставка CLI на диске содержит исполняемый бинарь, а не читаемые TypeScript-
   исходники; поэтому для CLI доказательство — его package metadata, `--help`,
   встроенные protocol/schema strings и фактические NDJSON result-кадры, а не ссылка
   на отсутствующий локальный исходник.
4. `app/backend_claude.py:1414-1486` на `ResultMessage`:
   - обновляет `_session_id` из `msg.session_id` (`:1417-1418`);
   - берёт `cost = getattr(msg, "total_cost_usd", 0) or 0` (`:1428`);
   - отдельно извлекает `input_tokens`, `output_tokens`,
     `cache_read_input_tokens`, `cache_creation_input_tokens` из `msg.usage`
     (`:1438-1443`);
   - эмитит обе величины в `turn_end` (`cost_usd` и token metadata, `:1473-1486`).
5. `app/session_turns.py:283-345` передаёт metadata в `CostTracker`, затем пишет
   `s._turn_cost` в `turn_usage.cost_usd`.
6. `app/session_cost.py:28-78` документирует и реализует дельту:

   ```python
   s._turn_cost = max(0, new_cost - s._last_cost)
   s._last_cost = new_cost
   ```

   baseline сбрасывается только когда меняется native `session_id` (`:40-47`).
   `_last_cost` и `_last_cost_cached` — dataclass fields с default `0.0`
   (`app/session.py:492-496`), в БД не сохраняются.
7. При auto-resume `app/manager.py:2002-2040` загружает из БД native `session_id`,
   `cost_usd` и token totals, но не загружает `_last_cost`. Новый объект поэтому
   получает zero baseline при том же native id. Это ровно окно, в котором полный
   cumulative result становится первым локальным delta.

## Что означает поле: дешёвая воспроизводимость

Выполнены два разрешённых маленьких текстовых вызова, без инструментов и длинного
контекста, на установленном CLI 2.1.278 и модели `claude-haiku-4-5`.

1. Новый session UUID `7b042797-654a-4d4d-a9df-93b56c13eea4`, prompt `Reply with
   exactly OK.`. CLI result:

   ```text
   usage: input_tokens=10, cache_creation_input_tokens=6977,
          cache_read_input_tokens=4295, output_tokens=56
   total_cost_usd=0.014673499999999999
   modelUsage costUSD=0.014673499999999999
   ```

2. Тот же UUID с `--resume`, prompt `Reply with exactly SECOND.`. CLI result:

   ```text
   usage: input_tokens=10, cache_creation_input_tokens=101,
          cache_read_input_tokens=11272, output_tokens=34
   total_cost_usd=0.016182699999999998
   modelUsage: inputTokens=20, outputTokens=90,
               cacheReadInputTokens=15567, cacheCreationInputTokens=7078,
               costUSD=0.016182699999999998
   ```

   Второй `usage` — только текущий вызов. Разница между двумя `total_cost_usd` равна
   `$0.0015092`, что совпадает с token arithmetic второго вызова для наблюдаемой CLI
   тарификации; второе поле — `$0.0161827`, то есть cumulative сумма двух вызовов.
   `modelUsage` во втором result также явно накопительный, тогда как `usage` остаётся
   per-result.

Таким образом, гипотеза «поле означает стоимость одного хода» опровергнута. Гипотеза
«это сумма только с прошлого рестарта» тоже не нужна: native session хранит историю
дольше рестарта; первый result после рестарта включает накопленное до него.

## Сверка с живой БД

Запрос выполнен read-only к `/home/kesha/orchestra/data/orchestra.db`.

Показательный ряд Orchestra (время ниже UTC, event id из `turn_usage`):

| Время | `event_id` | `cost_usd` | input/output/cache_read/cache_create | native session |
|---|---|---:|---:|---|
| 2026-09-20 16:33:00 | `6e90cd42-4267-4f12-9a21-ecf31d8f5757` | 74.739396 | 8 / 2004 / 1,643,281 / 550,024 | `8f0fa9e1-17b3-4943-ae8a-f571bd5540aa` |
| 2026-09-21 04:47:50 | `e3ae7057-c296-483e-b3c5-aa62d7904349` | 97.360260 | 14 / 1579 / 3,645,237 / 609,874 | тот же |
| 2026-09-21 07:29:08 | `0cf6d7c0-841b-4bed-95eb-e41ea0ee05a2` | 154.213324 | 6 / 1299 / 2,352,346 / 31,498 | тот же |
| 2026-09-21 07:31:04 | `fa9e69ff-e1e4-4ccd-a7ae-073158e1a915` | 3.067311 | 14 / 7146 / 5,596,383 / 9,040 | тот же |

Для 07:29 token formula владельца из `app/models.py` ($5/M input, $25/M output,
cache read ×0.1, cache create ×2) даёт `$1.523658`, а в БД стоит `$154.2133235`.
Статусный log той же строки содержит `turn ended ... $154.21 turn, $154.21
session`, показывая, что локальный tracker действительно записал весь provider total
как первый local turn. Уже в 07:31 baseline был обновлён и значение вернулось к
token formula: `$3.067311` против `$3.0673115`.

То же плечо видно для University, seedon и comfy: аномальная строка — первая после
рестарта, следующая строка снова соответствует token arithmetic. Это не похоже на
ошибку суммирования `resume` входных сообщений; native session id остаётся тем же.

## Кто ошибается

### Провайдер/CLI

Доказательств, что CLI врёт о собственной cumulative величине, нет. CLI result
согласован с `modelUsage.costUSD`, а маленький resumed probe показывает ожидаемое
накопление. CLI действительно отдаёт не per-turn цену в `total_cost_usd`, но это
семантический контракт поля, не ошибка числа.

### Python SDK

SDK только декодирует JSON. Ошибка SDK не обнаружена: parser сохраняет отдельно
`total_cost_usd`, `usage` и `modelUsage`.

### Orchestra

Ошибка в предположении границы baseline: код знает, что cost cumulative per native
session, но хранит `_last_cost` только в памяти. После рестарта native session
возобновляется, а baseline — нет. БД получает provider cumulative как `turn_usage`
стоимость первого post-restart хода.

## Варианты исправления

### A — рекомендованный: token-authoritative per-turn accounting

В `app/backend_claude.py` сделать `usage` источником `cost_usd` для Claude turns:
считать текущий result по принятой локальной формуле и не использовать cumulative
`total_cost_usd` для `turn_usage`. Сохранить raw provider total только в metadata/log
для диагностики (или отдельном явно названном поле, если он нужен в UI). Учитывать
доступную CLI разбивку `usage.cache_creation.ephemeral_5m_input_tokens` и
`ephemeral_1h_input_tokens`, если локальный контракт различает эти ставки; не путать
её с уже существующим `cost_usd_cached`, который сейчас считает cache-create как
`1.25×` (`backend_claude.py:1457-1458`, `routes/system.py:904-920`).

Цена: небольшая локальная правка backend + регрессии на (а) первый ход после
рестарта с тем же native id, (б) обычный второй ход, (в) смену native id. Схема БД
не нужна, если raw cumulative не требуется в таблице. Компромисс: при изменении
провайдером тарифов нужно обновлять локальную таблицу/формулу; зато результат не
зависит от restart/resume и provider cumulative semantics.

### B — сохранять provider baseline

Добавить в persistent state raw cumulative provider cost и native session id (новые
колонки/миграция либо отдельная таблица), восстанавливать `_last_cost` при
`manager._load_session`, атомарно записывать новый baseline вместе с terminal turn.
При смене native id baseline обнулять, как сейчас.

Цена: средняя — схема + миграция + восстановление + тесты crash/restart. Компромисс:
минимум изменения текущей арифметики и сохранение provider pricing, но остаётся
зависимость от того, что CLI продолжит отдавать cumulative total; потеря/задержка
baseline write создаёт новый класс under/over-counting.

### C — только сменить CLI/SDK pin

Синхронизировать `app/runtime_history.py`, `pyproject.toml` и фактически запускаемый
CLI, чтобы не было `2.1.197`/bundled `2.1.205`/system `2.1.278` одновременно.

Цена: малая операционная/packaging правка, но это не исправление текущего выброса:
проверенный 2.1.278 всё равно отдаёт cumulative `total_cost_usd`. Pin полезен как
контроль протокола, но нужен вместе с A или B, не вместо него.

## Итоговое решение для владельца

На стороне SDK/CLI число не «хуёвое» — оно означает cumulative cost native session.
Мы ошибаемся, записывая его как per-turn после рестарта, потому что baseline не
переживает процесс. Исправлять следует у себя; предпочтительно A (token-authoritative
turn cost + raw cumulative только для диагностики). B допустим, если принципиально
нужна provider-reported стоимость, но он сложнее и хрупче.

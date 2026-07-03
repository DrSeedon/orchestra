# Research — cost-tracking: store RAW cache tokens, not baked price

## Question
БД хранит готовую цену `cost_usd_cached` (посчитанную по цене-на-момент-турна), но НЕ хранит
сырые cache-токены (`cache_read`, `cache_create`). При смене цены модели (реально было: Opus
$15/$75 → $5/$25) пересчитать историю НЕЛЬЗЯ — сырых токенов нет. Как хранить токены полно,
чтобы цену можно было пересчитать on-the-fly?

## Data flow (verified, with sources)

### 1. Backend — где cache-токены появляются
`app/backend_claude.py:376-396` (ResultMessage handler):
- SDK `msg.usage` (dict) даёт: `cache_creation_input_tokens`, `cache_read_input_tokens`,
  `input_tokens`, `output_tokens`.
- `cost_cached` считается прямо тут (backend:396) по `TOKEN_PRICES[model]`:
  ```
  cost_cached = (input_tokens*p_in + cache_read*p_in*0.1 + cache_create*p_in*1.25 + output_tokens*p_out) / 1e6
  ```
  (Anthropic cache pricing: read = 10% input, create = 125% input.)
- Все 4 токен-поля + `cost_usd_cached` кладутся в metadata события `turn_end` (backend:401-417).
- **`cost_usd` (основной)** = `msg.total_cost_usd` от SDK (backend:366). Для claude-моделей НЕ
  пересчитывается (`if not self.model.startswith("claude-")` — только non-claude). Корректен, НЕ трогаем.

### 2. Session — накопление
`app/session_cost.py:apply_turn_result` (вызывается на каждый turn_end):
- `total_input_tokens += meta["input_tokens"]` (line 48) — накапливается ✓
- `total_output_tokens += meta["output_tokens"]` (line 49) — накапливается ✓
- `cost_usd_cached += max(0, new_cost_cached - _last_cost_cached)` (line 45) — накапливается как ЦЕНА ✓
- **`cache_read` / `cache_create` — НЕ накапливаются в total.** Идут только в
  `_last_context` (session_cost.py:62-63) как снапшот ТЕКУЩЕГО турна (для context-виджета).
  → **ЭТО КОРЕНЬ БАГА: сырые cache-токены нигде не суммируются и в БД не попадают.**

Поля сессии: `app/session.py:143-144` (`total_input_tokens`, `total_output_tokens`),
`110` (`cost_usd_cached`). Нет полей под cache-токены.

### 3. DB — схема, миграции, save/load
- Схема `sessions`: `app/db.py:46-65` (базовая) + additive ALTER в `_migrate` (db.py:286-332).
- Паттерн миграции: `cols = {PRAGMA table_info}` → `if "x" not in cols: ALTER TABLE ADD COLUMN`
  (db.py:289, 323-326). Идемпотентно, additive, старые данные не ломаются. ✓ CONFIRMED — образец есть.
- `save_session` (db.py:463): `setdefault` (474-475) + INSERT-колонки (494) + `ON CONFLICT UPDATE`
  (527-528). Новые колонки надо добавить во ВСЕ три места.
- `_to_db_dict` (session.py:995) строит dict для save_session — сюда тоже добавить новые поля.
- Load: `get_session`/`load_all_sessions` = `SELECT * ... dict(row)` (db.py:593-594, 649). Новые
  колонки подтягиваются автоматически (нет явного списка). ✓
- Restore в объект:
  - `_hydrate_row` (manager.py:748-794) — detached, восстанавливает `total_input_tokens` и т.д. (791-794).
    **Сюда добавить restore новых полей.**
  - `_load_from_db` (manager.py:914-1013) — resume-путь. **НЕ восстанавливает** `total_input_tokens`/
    `total_output_tokens`/`total_turns`/`total_tool_calls` вообще (грепнул — их там нет). Существующий
    баг: после resume эти totals сбрасываются в 0 при первом `_persist`. Не в скоупе задачи, но новые
    cache-поля унаследуют ту же проблему если добавить их только сюда. **Решение: класть restore в
    `_hydrate_row` (как соседи) + ЗАМЕТКА про gap в `_load_from_db`.**

### 4. Где cost_cached отображается
- `app/routes/system.py:441 _get_agents_cost` — единственный потребитель. Читает
  `cost_usd_cached` из БД (готовую цену), суммирует (446-457). Отдаётся в `/api/...` → `orchestra`
  блок (system.py:508).
- **app.js / usage.js — `cost_usd_cached` НЕ используется** (грепнул: 0 совпадений в app.js,
  usage.js только про "cached data" tooltip — не про это). Фронт показывает только `cost_usd`.
  → Значит смена отображения cost_cached затрагивает ТОЛЬКО system.py. Малый blast radius.

### 5. Прецедент пересчёта
`_reconstruct_costs` (db.py:260) уже пересчитывал `cost_usd` из логов при миграции `cost_reset_v1`.
Т.е. паттерн "пересчёт истории при смене логики" в проекте уже есть.

## Решение (что хранить)
**Хранить И сырые токены (для пересчёта), И готовую цену (для скорости отображения).**
Обоснование:
- Сырые токены (`total_cache_read_tokens`, `total_cache_create_tokens`) = источник правды,
  позволяют пересчитать `cost_cached` при любой смене `TOKEN_PRICES`.
- Готовую `cost_usd_cached` оставляем как есть (не ломаем текущее отображение в system.py) —
  но теперь у неё есть «дубликат правды» в виде токенов. Считать on-the-fly в system.py из
  токенов — отдельный опциональный тикет (для истинного пересчёта старой цены).
- Проще, чем выпиливать `cost_usd_cached`: `apply_turn_result` продолжает копить и цену, и токены.
  Fail-safe: старые сессии имеют токены=0 → recompute даст 0, поэтому для старых показываем
  хранимую `cost_usd_cached` (fallback), для новых — можно пересчитать.

⚠️ `cost_usd` (SDK) — НЕ трогаем.
⚠️ Старые сессии: новые колонки DEFAULT 0. Recompute из 0 = 0 → показываем старую хранимую цену. Fail gracefully.

## Affected files
- `app/db.py` — миграция (+2 колонки), save_session (setdefault + INSERT + UPDATE).
- `app/session.py` — 2 новых поля + `_to_db_dict`.
- `app/session_cost.py` — накопление `total_cache_read_tokens`/`total_cache_create_tokens`.
- `app/manager.py` — restore в `_hydrate_row`.
- `app/routes/system.py` — (опц. тикет) on-the-fly recompute cost_cached из токенов.
- Тесты: `tests/`.

## Risks / edge cases
- **Resume-gap** (`_load_from_db` не восстанавливает totals) — существующий баг, документируем, не чиним в этой задаче.
- Старые сессии: cache-токены=0 → recompute=0. Обязателен fallback на хранимую `cost_usd_cached`.
- `cost_usd_cached` продолжает копиться параллельно — двойной источник, но НЕ рассинхрон (оба из
  одного turn_end). Готовая цена = «цена на момент турна» (историческая), токены = для пересчёта.
- `meta.get("cache_read", 0)` — backward-compat: старые логи/turn без ключа → 0, не падает.

## Confidence
**CONFIRMED** — весь путь turn_end → session_cost → db → manager → system.py прочитан вживую.
Корень бага (cache-токены не суммируются) локализован на session_cost.py:62-63. Паттерн
additive-миграции и restore — образцы в коде есть. Counter-evidence: `_load_from_db` resume-gap —
существующая проблема, обходим размещением restore в `_hydrate_row`.

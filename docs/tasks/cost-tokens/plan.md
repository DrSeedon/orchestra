# Plan — store RAW cache tokens, recompute cost_cached on-the-fly

## Goal
Хранить сырые cache-токены (`total_cache_read_tokens`, `total_cache_create_tokens`) полно, чтобы
cost_cached можно было пересчитать при смене `TOKEN_PRICES`. Готовую цену `cost_usd_cached` НЕ
выпиливаем (fallback для старых сессий). `cost_usd` (SDK) не трогаем. Побочно чиним resume-gap.

## What changes (files → functions)
- `app/db.py`
  - `_migrate` (после строки 326): +2 additive ALTER (`total_cache_read_tokens`, `total_cache_create_tokens`).
  - `save_session` (473-476, 494, 502, 527-529): setdefault + INSERT-колонки + ON CONFLICT UPDATE.
- `app/session.py`
  - поля (после 144): `total_cache_read_tokens: int = 0`, `total_cache_create_tokens: int = 0`.
  - `_to_db_dict` (1016-1019): 2 новых ключа.
  - `to_dict` (1051-1054): 2 новых ключа (для API/фронта, консистентность с input/output).
- `app/session_cost.py`
  - `apply_turn_result` (после 49): `s.total_cache_read_tokens += meta.get("cache_read", 0)` и `..._create`.
- `app/manager.py`
  - `_hydrate_row` (после 793): restore 2 новых поля.
  - `_load_from_db` (после 978, до `session.is_orchestrator=`): restore ВСЕХ totals
    (input/output/turns/tool_calls + 2 новых cache) — fix resume-gap.
- `app/routes/system.py`
  - `_get_agents_cost` (445-457): SELECT + recompute cost_cached on-the-fly из токенов+TOKEN_PRICES,
    fallback на хранимую `cost_usd_cached` если оба токена = 0 (старые сессии).
- `tests/` — новый файл `test_cache_tokens.py`.

## What NOT to touch
- `cost_usd` (SDK `total_cost_usd`) и его накопление в `apply_turn_result:37-43`.
- `cost_usd_cached` накопление (session_cost.py:44-46) — остаётся как исторический fallback.
- backend_claude.py — cache-токены УЖЕ в turn_end metadata, менять не надо.
- Формула cache-цены (read=10%, create=125%) — переиспользуем в system.py, не меняем логику.

## Recompute формула (T4, из backend_claude.py:396)
```
cost_cached = (total_cache_read*p_in*0.1 + total_cache_create*p_in*1.25) / 1e6
```
⚠️ ВАЖНО: в backend полная формула включает `input_tokens*p_in + output_tokens*p_out` (не-cached часть).
Но для recompute per-session у нас есть `total_input_tokens`/`total_output_tokens` в БД — значит полная
пересчитанная цена = `(tot_in*p_in + tot_cache_read*p_in*0.1 + tot_cache_create*p_in*1.25 + tot_out*p_out)/1e6`.
Это делает recompute самодостаточным и эквивалентным сумме турновых cost_cached (при неизменной цене).
Fallback: если `total_cache_read == 0 and total_cache_create == 0` → берём хранимую `cost_usd_cached`
(старая сессия без сырых данных).

---

## Tickets

### T1 — DB миграция: колонки под сырые cache-токены
- Files: `app/db.py` (`_migrate`)
- Changes: после строки 326 (total_output_tokens):
  ```python
  if "total_cache_read_tokens" not in cols:
      c.execute("ALTER TABLE sessions ADD COLUMN total_cache_read_tokens INTEGER DEFAULT 0")
  if "total_cache_create_tokens" not in cols:
      c.execute("ALTER TABLE sessions ADD COLUMN total_cache_create_tokens INTEGER DEFAULT 0")
  ```
- AC:
  - После `init_db()` на СТАРОЙ БД (без колонок) — колонки появляются, старые строки не тронуты.
  - `PRAGMA table_info(sessions)` содержит обе колонки с DEFAULT 0.
  - Повторный запуск `_migrate` не падает (идемпотентно).
- blocked-by: none

### T2 — session_cost: накапливать cache-токены в total
- Files: `app/session.py` (поля), `app/session_cost.py` (`apply_turn_result`)
- Changes:
  - session.py после 144: `total_cache_read_tokens: int = 0`, `total_cache_create_tokens: int = 0`.
  - session_cost.py после 49:
    ```python
    s.total_cache_read_tokens += meta.get("cache_read", 0)
    s.total_cache_create_tokens += meta.get("cache_create", 0)
    ```
- AC:
  - 3 турна с cache_read=[100,200,50], cache_create=[10,0,5] → total_cache_read=350, total_cache_create=15.
  - turn_end без ключей cache_read/cache_create (старый формат) → не падает, += 0.
- blocked-by: none

### T3 — persist/restore новых колонок
- Files: `app/session.py` (`_to_db_dict`, `to_dict`), `app/db.py` (`save_session`), `app/manager.py` (`_hydrate_row`)
- Changes:
  - `_to_db_dict` +2 ключа; `to_dict` +2 ключа.
  - `save_session`: setdefault(0) + добавить в INSERT columns/VALUES + ON CONFLICT UPDATE SET.
  - `_hydrate_row` после 793: `s.total_cache_read_tokens = row.get(...) or 0` (×2).
- AC:
  - Round-trip: сессия с total_cache_read=350/create=15 → save_session → get_session → значения совпадают.
  - `_hydrate_row` из строки БД восстанавливает оба поля.
  - save_session на dict БЕЗ новых ключей (старый вызов) не падает (setdefault срабатывает).
- blocked-by: T1, T2

### T4 — recompute cost_cached on-the-fly в system.py
- Files: `app/routes/system.py` (`_get_agents_cost`)
- Changes: SELECT добавить `total_input_tokens, total_output_tokens, total_cache_read_tokens,
  total_cache_create_tokens`. Правило (RESOLVED by Codex):
  ```python
  prices = TOKEN_PRICES.get(model)
  has_raw = (total_cache_read_tokens or 0) > 0 or (total_cache_create_tokens or 0) > 0
  if prices and has_raw:
      cost_cached = recompute(...)   # backend formula (см. выше)
  else:
      cost_cached = stored cost_usd_cached   # fallback: старые строки, codex, нет кеша
  ```
  Codex НЕ репрайсим (TOKEN_PRICES.get → None → fallback). Row никогда не дропаем/не зануляем.
- AC:
  - Сессия model=opus, tot_in=1000, tot_out=500, cache_read=2000, cache_create=100 →
    cost_cached = (1000*5 + 2000*5*0.1 + 100*5*1.25 + 500*25)/1e6, а не хранимая цена.
  - Старая сессия (cache_read=0, cache_create=0, cost_usd_cached=0.42) → возвращает 0.42 (fallback).
  - Модель без записи в TOKEN_PRICES (напр. codex/gpt) → fallback на хранимую цену (не падает на None).
  - total_cost_usd (не cached) — НЕ меняется.
- blocked-by: T3

### T5 — fix resume-gap: _load_from_db восстанавливает totals
- Files: `app/manager.py` (`_load_from_db`)
- Changes: после создания `session` (после 979, до `session.is_orchestrator = is_orch`):
  ```python
  session.total_turns = db_row.get("total_turns") or 0
  session.total_input_tokens = db_row.get("total_input_tokens") or 0
  session.total_output_tokens = db_row.get("total_output_tokens") or 0
  session.total_tool_calls = db_row.get("total_tool_calls") or 0
  session.total_cache_read_tokens = db_row.get("total_cache_read_tokens") or 0
  session.total_cache_create_tokens = db_row.get("total_cache_create_tokens") or 0
  ```
- AC:
  - Сессия с total_input=5000/output=2000/turns=10/tool_calls=30 в БД → после `_load_from_db`
    объект имеет те же значения (не 0).
  - Cache-токены тоже восстанавливаются.
  - Старая строка без колонок (None) → 0, не падает.
- blocked-by: T3

### T6 — Codex review + тесты + commit
- Files: `tests/test_cache_tokens.py`
- Changes: тесты покрывают AC T1-T5. Codex review git diff (миграция + cost calc). Fix CRITICAL/HIGH.
- AC:
  - `uv run pytest -x -q` зелёный (весь suite).
  - Codex review без CRITICAL/HIGH (или задокументированы).
  - Один чистый commit `#cost-tokens: ...`.
- blocked-by: T1, T2, T3, T4, T5

## Adversarial self-review (потенциальные баги)
1. **Двойной учёт цены**: cost_usd_cached копится параллельно с recompute — если фронт покажет
   оба, будет путаница. Митигация: recompute ЗАМЕНЯЕТ значение в _get_agents_cost, хранимая только
   fallback. Один источник в отдаче.
2. **Fallback-условие**: `cache_read==0 AND cache_create==0` может ложно сработать на НОВОЙ сессии
   где реально не было кеша (короткий турн). Но тогда recompute из input/output всё равно даст верную
   цену. Уточнение: fallback ТОЛЬКО если И токены=0 И это старая сессия. Проще: если оба cache=0 →
   пересчитать из input/output (даст 0 по cache-части, корректно), а хранимую использовать лишь если
   input/output тоже 0. Решить в T4 — склоняюсь к «recompute всегда если есть хоть какие-то токены,
   иначе хранимая».
3. **TOKEN_PRICES[model] = None** для codex/неизвестных → KeyError. Митигация: `.get(model)` + проверка.

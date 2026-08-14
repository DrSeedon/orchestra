# #242 — инвентарь тестов, читающих живое состояние

База: `9268255c` (main, 14.08.2026). Счётчик — не греп «есть слово», а явное правило на строку.

## Пересчёт гипотезы «62 места / 48 файлов»

Правило то же, что в #235: строка с `monkeypatch.setattr(...DB_PATH` (или `setattr(mod, "DB_PATH"`).

| | постановка (#235) | сейчас |
|---|---|---|
| setattr-сайты | 62 | **70** |
| файлы | 48 | **56** (55 test_* + conftest) |
| setattr без conftest | — | **69 / 55** |

Гипотеза разошлась: **+8 сайтов, +7 файлов**. Список #235 целиком на месте (удалённых 0). Добавились:

`test_backend_codex.py`, `test_fan_report_delivery.py`, `test_fan_terminal_kind.py`, `test_fd_adopt.py`, `test_restart_inbox.py`, `test_seamless_restart.py`, `test_worker_model_policy.py`.

Это **попытки изоляции**, не чтение прода. Гард `_isolate_production_db` в `tests/conftest.py` (#235) уже падает при коннекте к `_DEFAULT_DB_PATH`. Штучно чинить 70 setattr бессмысленно.

## Классы живого чтения (не патчи)

### 1. Живой HTTP `:8888`

Один файл: `tests/test_frontend.py`.
`BASE = ORCHESTRA_TEST_BASE or http://localhost:8888`.
`_goto_dashboard_or_skip` — **12 вызовов**. Нет сервера → `pytest.skip`, не падение.
`test_header_has_orch_tabs` после #197 пинит `/api/orchestrators`, но всё равно ходит на живой HTML дашборда.

Это тот класс, что стрелял сегодня (#197 в фулле). Скип маскирует «не проверили».

### 2. Живая ФС (`Path.home()` без патча)

| файл | что читает |
|---|---|
| `test_migrate_agent.py:47` | `~/.claude/projects` (скип, если нет) |
| `test_native_history_import.py:191,211` | `~/.claude` / `~/.codex` |
| `test_mcp_config_isolation.py:358` | сравнивает с `~/.codex/auth.json` |

### 3. Wall-clock

- `asyncio.wait_for(..., timeout=0.1)`: **0** (то единственное место на 11.08 не завелось).
- `timeout=0.05` (ещё короче): **4** в `test_tg_bridge.py` (2311, 2610, 2687, 2757). Кандидат на флак-под-нагрузкой.
- `timeout=0.2`: `test_session.py`, `test_api.py` (гейт зависания; часть может быть перф-ассертом).

### 4. Квота / лимиты

Большинство сайтов `_usage_cache` — моки. Живой `/api/usage` в узких unit-тестах не нашёл.
`limit_wake` / `quota_alert` тесты ходят в tmp DB.

### 5. Общий конфиг

`DASHBOARD_*` / `AUTO_COMPACT_ENABLED`: 47 строк в 10 файлах, часть мокает, часть читает env процесса (юнит systemd).

`TestCanSpawn::test_whitelist_allows_listed` я сначала записал сюда как «читает общий конфиг». grok-51 на #278: тест красный **и в одиночку**, причина `unknown parent role 'boss'` после #36, не чужой `can_spawn`. Класс «живой конфиг» с него снят. Файл `tests/test_manager.py` — его.

## Что НЕ входит в этот тикет

- `tests/test_antigravity_{runtime,readiness,usage,usage_frontend}.py` и `test_manager.py` (`test_whitelist_allows_listed`) — #278, grok-51. Он подтвердил: чужие файлы из инвентаря ему не нужны. `test_pipeline.py` он не трогает.

## Предлагаемый порядок (чинить не начал)

1. **Этот тикет** — инвентарь + класс 1 (`test_frontend.py`): свой uvicorn на изолированной БД, `_goto_dashboard` падает без сервера. `pytest.skip` в файле = 0.
2. **Следующий** — `timeout=0.05` ×4 в `test_tg_bridge.py`.
3. **Потом** — `timeout=0.05` в `test_tg_bridge.py` (4 места): таймаут только против зависания, не как перф.
4. **Не трогать пачкой** — 70 setattr `DB_PATH`. Гард уже есть.

Жду, какой пункт брать в работу в #242.

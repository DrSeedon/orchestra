# #366 — План: каталог моделей OpenRouter + два уровня доступности

## Решения (из research.md #366, схема утверждена оркестратором)

1. **Overlay, не разрегистрация.** Все модели кеша каталога регистрируются через
   `register_model()` в общий реестр (`MODEL_SPECS` + производные виды). Флаги
   доступности режут только точки входа. Выключение модели никогда не вызывает
   `unregister_model` → resume/стоимость/контекст живой сессии не ломаются.
2. **Состояние — SQLite kv** (`app/db.py`, таблица уже есть, писателя нет):
   - `model_catalog_cache` → `{"fetched_at": float, "models": [нормализованные…]}`;
   - `model_flags` → `{"<model_id>": {"dashboard": bool|null, "agents": bool|null}}`.
3. **Контроль полный и однородный** (уточнение юзера): оба тумблера на ВСЕ модели всех
   рантаймов — claude/codex/grok и harness-каталог, без исключений. Дефолты: manifest
   (`SELECTABLE_MODEL_SPECS`) = true/true; каталог до включения = false/false.
4. **Уровни независимы**: `dashboard` фильтрует `/api/models` и пользовательские действия;
   `agents` фильтрует `available_models_block()`, спавн воркеров и MCP change-model.
5. **Порядок регистрации**: повторное применение каталога зашито В САМ путь обновления
   реестра (хвост `fetch_models_from_proxy` / `refresh_models`), а не в порядок вызова на
   старте — enterprise-очистка не может его потерять (красный тест T2).

### Решение развилки «юзер погасил все модели»

**Ничего не блокировать — это его право. Обоснование:**
- Локаута нет: экран каталога читает свой `/api/models/catalog` и пишет PATCH мимо
  `/api/models`, поэтому восстановление всегда доступно с того же экрана одним кликом.
- Отказ «на выключение последней» требует определения «последней» по двум уровням ×
  двум классам моделей — сложность без выигрыша безопасности; а состояние «агентам нельзя
  ничего спавнить» легитимно (юзер хочет паузу на спавны).
- Все отказные пути fail-loud с подсказкой (сообщение называет экран и тумблер), сервер
  стартует и работает: `resolve_model`/`get_model_spec` не зависят от флагов,
  `bootstrap` дефолт резолвится. Живые агенты дорабатывают.
- Единственная обязанность плана: сообщения об отказе обязаны называть путь включения
  (AC T6), и пикер при пустом `/api/models` не должен ломаться (сегодня он просто рендерит
  пустой список — сохранить).

## Контракт (имена зафиксированы дословно)

```python
# app/db.py
kv_set(key: str, value: str) -> None          # INSERT OR REPLACE
kv_delete(key: str) -> None

# app/model_catalog.py (новый модуль)
CATALOG_KV_KEY = "model_catalog_cache"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
normalize_catalog_model(raw: dict) -> dict | None
    # -> {"id", "name", "context_length": int,
    #     "price_prompt": float, "price_completion": float,      # $/Mtok, "0" -> 0.0
    #     "input_modalities": list[str], "supports_tools": bool} # "tools" in supported_parameters
    # None если id пуст
async refresh_catalog() -> dict   # fetch -> normalize -> kv_set cache -> apply_model_catalog()
                                  # -> {"fetched": int, "registered": int, "dropped": int}
cached_catalog() -> list[dict]
apply_model_catalog() -> int      # register_model(ModelSpec(runtime="harness",
                                  #   provider="openrouter", …)) для КАЖДОЙ модели кеша,
                                  # idempotent (replace=True); без алиасов; per-model
                                  # try/except со счётчиком dropped; возвращает registered

# app/models.py
MODEL_FLAGS_KV_KEY = "model_flags"
get_model_flags(model_id: str) -> dict            # {"dashboard": bool, "agents": bool};
                                                  # дефолт true/true для SELECTABLE_MODEL_SPECS,
                                                  # false/false для остальных
set_model_flags(model_id, *, dashboard=None, agents=None) -> dict
                                                  # ValueError на неизвестном id (id должен быть
                                                  # в MODEL_SPECS)
ensure_spawn_allowed(model_id) -> None            # ValueError "...disabled for agents —
                                                  # re-enable it in the Models catalog screen"
ensure_dashboard_visible(model_id) -> None        # ValueError "...hidden from the dashboard —
                                                  # re-enable it in the Models catalog screen"
```

Точки принуждения:
- `GET /api/models` (system.py:348): пропускать модели с `dashboard=false`;
- `available_models_block()` (models.py:689): только `agents=true`;
- `manager.create_session` (manager.py:577, после `resolve_model`): `parent_name`
  непустой → `ensure_spawn_allowed`, иначе → `ensure_dashboard_visible`;
- `POST /api/sessions/{name}/change-model` (sessions.py:862): новое поле body `via`
  (`"dashboard"`|`"mcp"`, default `"dashboard"`) → mcp требует `ensure_spawn_allowed`,
  ui требует `ensure_dashboard_visible`; `mcp_stdio.change_worker_model` шлёт `via:"mcp"`;
- внутренние маршруты НЕ гейтятся (`codex_review` резолвит luna через `resolve_model` мимо флагов).

HTTP API:
```
GET   /api/models/catalog        -> {"catalog":[{...normalized..., "flags":{...}}],
                                  "fetched_at": float|null}
POST  /api/models/catalog/refresh -> refresh_catalog() результат (httpx внутри app.model_catalog)
PATCH /api/models/catalog/flags   -> {"id", "dashboard"?, "agents"?} -> 400 на неизвестном id
```

Известное изменение существующего контракта (не баг): тест
`tests/test_backend_routing.py::test_derived_views_carry_exactly_the_declared_specs`
утверждает «производные виды == ровно SELECTABLE_MODEL_SPECS». С динамическим каталогом
виды легитимно становятся надмножеством; тест правится на «надмножество из объявленных +
все зарегистрированы согласованно». Это ЕДИНСТВЕННОЕ изменение чужого теста в задаче.

## Tickets

### T1 — kv-писатели + хранилище флагов
- Files: app/db.py (+kv_set/kv_delete), app/models.py (MODEL_FLAGS_KV_KEY,
  get_model_flags, set_model_flags)
- Test: tests/test_model_flags.py::test_t1_kv_set_and_delete_roundtrip и ещё 3 test_t1_*
        — закоммичены RED в этом коммите
- AC: `uv run python -m pytest tests/test_model_flags.py -q` зелёный; флаги переживают
  перечитывание из sqlite; неизвестный id отклоняется ValueError
- blocked-by: none

### T2 — клиент каталога + кеш + регистрация с гарантией порядка
- Files: app/model_catalog.py (новый), app/models.py (вызов apply_model_catalog() в конце
  успешной ветки fetch_models_from_proxy И в ветке no-proxy refresh_models)
- Test: tests/test_model_catalog.py::test_t2_catalog_survives_enterprise_proxy_refresh
        (+2 normalize-теста) — RED
- AC: `uv run python -m pytest tests/test_model_catalog.py -q` зелёный; сценарий теста =
  «каталог применён ДО enterprise-очистки → после очистки и прокси-перезагрузки модели
  каталога в MODELS/BACKENDS/CONTEXT_LIMITS/TOKEN_PRICES»; тест красен, если очистка
  стирает каталог (требование оркестратора)
- blocked-by: T1

### T3 — точки принуждения двух уровней
- Files: app/models.py (available_models_block filter, ensure_*), app/routes/system.py
  (/api/models filter), app/manager.py (create_session gate), app/routes/sessions.py
  (change-model `via`), app/mcp_stdio.py (change_worker_model via="mcp")
- Test: tests/test_model_gates.py (6 тестов test_t3_*, включая wiring delivery-check) — RED
- AC: `uv run python -m pytest tests/test_model_gates.py -q` зелёный; resolve_model не
  зависит от флагов; codex_review-путь не тронут
- blocked-by: T1

### T4 — HTTP API каталога
- Files: app/routes/system.py (3 эндпоинта)
- Test: tests/test_catalog_api.py (3 теста test_t4_*) — RED (404 сейчас)
- AC: `uv run python -m pytest tests/test_catalog_api.py -q` зелёный; PATCH на неизвестном
  id → 400; POST refresh регистрирует новые модели каталога в общий реестр
- blocked-by: T2, T3

### T5 — экран каталога во фронте
- Files: app/static/js/app.js, app/templates/dashboard.html
- Test: tests/test_model_catalog_frontend.py (delivery-check: бандл несёт catalog-modal,
  /api/models/catalog, якоря search/free/tools/toggle; пикер продолжает читать _MODELS) — RED
- AC: `uv run python -m pytest tests/test_model_catalog_frontend.py -q` зелёный.
  Браузерное поведение проверяется вручную Playwright page.route probe (:8888 отдаёт статику
  из основного чекаута), доказательство — в report.md. Поиск/фильтры (free/paid, контекст,
  тулы, картинки), два тумблера на каждую модель всех рантаймов, кнопка Refresh.
  Пустой /api/models не ломает пикер.
- blocked-by: T4

### T6 — выключенная модель под живым агентом (оба плеча)
- Files: только сообщения об ошибках ensure_* (если AC не выполнен иначе)
- Test: tests/test_toggle_live_agent.py (3 теста test_t6_*) — RED
- AC: `uv run python -m pytest tests/test_toggle_live_agent.py -q` зелёный;
  плечо A — весь resume-поверхности (get_model_spec/resolve/CONTEXT_LIMITS/TOKEN_PRICES/
  backend_for_model) цел после снятия обоих флагов; плечо B — ensure_spawn_allowed падает
  с сообщением, называющим экран включения ([Cc]atalog); уход с выключенной модели
  разрешён (проверяется уровень ЦЕЛЕВОЙ модели). Плюс ручная проба: смена модели
  ОРКЕСТРАТОРУ через пикер на :8888 (page.route), скрин/лог в report.md.
- blocked-by: T3

Порядок реализации: T1 → T2/T3 (параллельно) → T4 → T5/T6.

## Что НЕ трогаем
- SELECTABLE_MODEL_SPECS, ALIASES manifest-моделей, COMPAT_MODEL_SPECS;
- enterprise proxy-путь кроме добавления re-apply хвоста;
- internal-маршруты (codex_review, quota_gate) — они не гейтятся флагами;
- harness runtime/loop (#365) — только потребители его конфига (CONTEXT_LIMITS уже ок).

## Риски / пре-мортем для следующего потребителя
1. `pipeline.py:202` печатает `sorted(MODELS)` в ошибке — станет огромным при 400+ моделях:
   обрезать до N первых + счётчик (внутри T3).
2. `_clear_selectable_models()` в enterprise-режиме — закрыт хвостом T2, покрыт тестом.
3. Коллизии авто-алиасов — каталог-модели алиасов не получают (T2).
4. Промпт живого оркестратора устаревает до рестарта — прикрывается жёстким гейтом T3
   (fail-closed), осознанно.

## Ревью

**Вердикта нет: пул исчерпан.** Codex-пул 100% (`weekly_quota_blocked`), встроенный
`review` дважды не выдал вердикта (обрыв без находок), внешняя проверка отменена решением
юзера («никаких ревью»). Гейт закрывает оркестратор личным чтением плана.

### Чем каждый тикет может тихо пройти на сломанной реализации
- **T1**: флаги положат в модульный кэш памяти, а не read-through kv → раундтрип в одном
  процессе зелёный, рестарт теряет состояние. Тест этого НЕ ловит; защита — контракт
  «каждый get читает kv» в плане + спот-чек Phase 3 (перезапись kv и перечитывание новым
  вызовом после очистки in-memory состояния отсутствует by design: его не должно быть).
- **T2**: re-apply хук поставлен только в dev-ветку `refresh_models`, мимо enterprise-ветки —
  ловится тестом (он именно про enterprise-очистку). Хук вызван ДО `_clear_selectable_models`
  внутри fetch — ловится (модели стёрты после). `apply_model_catalog` регистрирует только
  включённые — ловится (тест сеет кеш без флагов и ждёт регистрации). Остаточное:
  per-model try/except может молча съесть ВСЕ модели — AC требует счётчик `dropped` в
  ответе refresh_catalog, проверяется в T4.
- **T3**: гейт существует, но точка вызова проглатывает ValueError выше по стеку — юнит-тест
  функции не увидит. Защита: wiring delivery-check (inspect.getsource) + ручная проба спавна
  в report.md. Пустое сообщение об ошибке — тест T6 матчит `[Cc]atalog` в тексте.
- **T4**: PATCH валидирует id, но не сохраняет — ловится перечитыванием `get_model_flags`.
  GET может отдать эхо запроса вместо хранимых флагов — ловится (флаги ставились отдельным
  вызовом до GET).
- **T5**: grep-якоря пройдут на мёртвом JS (кнопки без обработчиков) — delivery-check по
  построению слабее поведения; браузерное поведение закрывается ТОЛЬКО ручной Playwright
  пробой через page.route (доказательство в report.md), без неё T5 не закрыт.
- **T6**: resume-surface проверка необходима, но не достаточна (реальный рестарт CLI-процесса
  не эмулируется юнитом) — честная граница; реальный рестарт выключенной модели вручную не
  делаем (не тратить боевой агент), принимаем остаточный риск с пометкой в report.md.


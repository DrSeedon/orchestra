# #366 — Каталог моделей OpenRouter в дашборде: исследование

## Question

- **Context:** Orchestra-дашборд, реестр моделей `app/models.py` (+ фронт-пикер, spawn-путь).
- **Change under test:** динамический каталог OpenRouter с двумя уровнями доступности
  («виден юзеру в дашборде» / «разрешён агентам при spawn_worker») вместо/поверх
  статичного `SELECTABLE_MODEL_SPECS`.
- **Baseline:** сегодня единственный источник — кортеж `SELECTABLE_MODEL_SPECS`
  (app/models.py:48), добавление модели = коммит + рестарт.
- **Outcome:** состояние переключателей переживает рестарт (SQLite); существующие
  потребители `MODELS`/`BACKENDS`/`CONTEXT_LIMITS` не ломаются; оркестраторы
  переключаются так же, как воркеры; живой агент на выключенной модели не ломается.

## Hypotheses considered

- **H1 (ведущая):** флаги доступности — это OVERLAY поверх полного реестра: все модели
  каталога регистрируются через существующий `register_model()`, а флаги режут только
  точки входа (/api/models, available_models_block, create_session). Фальсификатор:
  найдётся код, который итерирует `MODELS`/`MODEL_SPECS` как «то, что видно юзеру» и не
  может быть отфильтрован → overlay даст утечку выключенных моделей в UI.
- **H2 (альтернатива):** включённые каталог-модели физически регистрируются, выключенные —
  разрегистрируются (`unregister_model`). Фальсификатор: разрегистрация ломает resume
  персистентной сессии на этой модели (`get_model_spec` бросает ValueError,
  app/models.py:382–393) — подтверждено чтением кода, см. F3.
- **H3 (альтернатива):** хранить состояние в отдельной таблице SQLite per-model строками.
  Не опровергнуто, но избыточно против kv+JSON при 300–400 записей (см. F5).

## Findings

### F1 — Реестр мутирует in place; реbind никому не нужен · CONFIRMED
`MODELS`, `BACKENDS`, `CONTEXT_LIMITS`, `MODEL_PROVIDERS`, `TOKEN_PRICES`, `MODEL_SPECS` —
модульные dict'ы; ~15 модулей импортируют их по имени (`from app.models import MODELS`) и
держат ССЫЛКУ на тот же объект. Единственные писатели — `_apply_derived_views()`,
`register_model()`, `unregister_model()` (app/models.py:336–379). Прецедент динамического
наполнения уже есть: `fetch_models_from_proxy()` мутирует те же dict'ы in place
(app/models.py:547–610), и это работает. Следствие: каталог-модели добавляются вызовом
готового `register_model(spec)` — он сам валидирует runtime/provider против
`PROVIDER_METADATA` (для harness разрешён provider="openrouter", app/models.py:238–245) и
заполняет ВСЕ производные виды, включая `CONTEXT_LIMITS` (нужно
`HarnessBackend._max_context`, backend_harness.py:426) и `TOKEN_PRICES` (fallback оценки
стоимости, backend_harness.py:418–424). Переприсваивать импортированные имена нельзя ни в
каком виде.

### F2 — Точки принуждения двух уровней · CONFIRMED
- **«Виден в дашборде»**: `/api/models` (app/routes/system.py:348) — единственный источник
  пикера (`_ensureModels`, app/static/js/app.js:2519; рендер 2593–2646). Фильтр здесь
  закрывает весь UI сразу.
- **«Разрешён агентам»**: два слоя.
  - Мягкий: `available_models_block()` (app/models.py:689) → вклеивается в системный промпт
    оркестратора (app/manager.py:345). Это то, что LLM видит списком.
  - Жёсткий: создание сессии — `CreateSessionRequest.validate_model`
    (app/routes/sessions.py:149–154) → `manager.create_session` → `resolve_model()`
    (app/manager.py:577). Спавн воркера проходит ТОЛЬКО здесь.
- **Дискриминатор «спавн агентом vs действие юзера»**: `spawn_worker` шлёт
  `parent_name=<оркестратор>`, `role="worker"`, без `is_orchestrator`
  (app/mcp_stdio.py:907–920); UI создаёт оркестратор с `is_orchestrator: true`
  (app/static/js/app.js:1626). Правило «agents-флаг режет спавны воркеров, dashboard-флаг
  режет UI» ложится на существующие поля без новых механизмов.
- **Гейтить ТОЛЬКО spawn-путь**: внутренние маршруты (например
  `_resolve_codex_review_model` → luna по умолчанию, app/mcp_stdio.py:804–830) должны
  продолжать резолвить модель, даже если юзер запретил её агентам — иначе выключение
  модели ломает codex_review. Проверено: codex_review резолвит через `resolve_model`,
  мимо create_session.

### F3 — Живой агент на выключенной модели: overlay ничего не ломает · CONFIRMED
Если выключение = флаг, а не `unregister_model`, то `get_model_spec()` продолжает
резолвить id (app/models.py:382–393): рестарт/resume существующей сессии работает,
стоимость и контекст считаются. Разрегистрация же роняет resume с ValueError — ровно для
этого случая в коде существует `COMPAT_MODEL_SPECS` (app/models.py:277–310) как список
ручных «мёртвых, но встречающихся в БД» роутов. H2 отвергнута по этому факту.
Семантика выключения: (а) новые спавны воркеров на модели отклоняются жёстким слоем;
(б) живой агент дорабатывает текущий жизненный цикл; (в) смена модели НА выключенную
через change-model отклоняется, С выключенной — разрешена (это выход агента с неё).
Отдельно: `available_models_block()` вшивается в промпт при СОЗДАНИИ сессии — живой
оркестратор до рестарта видит старый список; его прикрывает жёсткий слой (fail-closed на
create_session).

### F4 — Каталог OpenRouter измерен живьём · CONFIRMED (measurement)
`GET https://openrouter.ai/api/v1/models` c ключом из `.env` (`OPENROUTER_API_KEY`),
сегодня: HTTP 200, **421 модель**, тело **689 КБ**, 22 бесплатных
(pricing.prompt==pricing.completion=="0"), 352 модели с `"tools"` в
`supported_parameters`. Полезные поля ответа: `id`, `name`, `context_length`,
`pricing.prompt|completion` (строки, цена ЗА ТОКЕН — тот же формат, что уже парсит
`_proxy_model_spec` с умножением на 1e6, app/models.py:529–531),
`architecture.input_modalities`, `supported_parameters`. Хватает на все фильтры задачи
(бесплатные/платные, контекст, тулы, картинки). Сырой дамп: /tmp/or_models.json.

### F5 — Персистентность: таблица `kv` есть, писателя нет · CONFIRMED
SQLite-таблица `kv(key TEXT PRIMARY KEY, value TEXT)` создаётся (app/db.py:493), читается
`kv_get()` (app/db.py:501), но В САМОМ РЕПО НЕТ НИ ОДНОЙ записи в неё (grep по
`INSERT INTO kv|kv_set` — пусто). То есть инфраструктура готова, нужен маленький
`kv_set/kv_delete` + JSON-ключи. Достаточно двух ключей: кеш каталога (нормализованный —
после обрезки до нужных полей ~десятки КБ вместо 689 КБ) и карта флагов. Отдельная
таблица per-model строками возможна, но даёт ничего при 400 записей и одном владельце —
H3 оставлена как запас, не как рекомендация.

### F6 — Оркестраторы уже переключаются тем же механизмом · LIKELY
Эндпоинт `POST /api/sessions/{name}/change-model` (app/routes/sessions.py:862–876) не
имеет никаких role-ограничений; MCP-тул `change_worker_model` (app/mcp_stdio.py:1515)
тоже. Пикер привязан к выбранной сессии вообще (`_showModelPicker(session.name, ...)`,
app.js:2693), а оркестратор — такая же сессия в менеджере. Ожидание: смена модели
оркестратору работает уже сейчас, проблема задачи — только в СОСТАВЕ списка (каталог) и
в том, что harness-модели обязаны быть зарегистрированы, чтобы change-model прошёл
валидацию `new_model not in MODELS` (sessions.py:869). Остаточный риск для Phase 3:
handoff-путь `session._change_model_locked` для runtime=harness не проверен на живую —
capabilities harness декларируют `resume=True`, `resume_across_models=True`
(app/runtime_registry.py:393–403, дефолты dataclass), но e2e-проверка переключения на
harness-модель обязательна.

### F7 — Фронт: новый экран = модалка по готовому образцу · CONFIRMED
Дашборд собирается из модалок (`analytics-modal`, `subagents-modal`, …
app/templates/dashboard.html:174–206) — каталог просится туда же: поиск/фильтры/тумблеры
клиент-side по нормализованному кешу (421 строка — ничто для браузера), кнопка
обновления дергает новый refresh-эндпоинт. `/api/models` раздувать НЕ надо: heartbeat
дёргает его каждые 3 с (читает только заголовки HEAD, system.py:377–381 — рост GET-тела
безопасен, но незачем), а полный каталог пусть живёт на своём
`GET /api/models/catalog`.

## Counter-evidence / риски

- **Enterprise-режим стирает реестр**: `fetch_models_from_proxy(enterprise_mode=True)`
  вызывает `_clear_selectable_models()` (app/models.py:479–486) — всё, что зарегистрировано
  ДО этого вызова, будет стёрто. На этом деплое auth выключен (dev-merge), но порядок
  «регистрация каталога строго ПОСЛЕ `refresh_models()` (app/main.py:296) + повторная
  регистрация после каждого `/api/models/refresh`» обязателен, иначе каталог молча исчезает.
- **Ошибка одного поля каталога не должна ронять весь реестр**: `register_model` бросает
  ValueError на плохом spec — загрузку каталога делать per-model try/except со счётчиком
  отброшенных (прецедент fail-soft: `_proxy_model_spec` возвращает None на пустом id).
- **Сообщение об ошибке `pipeline.py:202** перечисляет `sorted(MODELS)` целиком — при 400+
  моделях станет огромным. Мелочь, отметить в плане (обрезать или фильтровать по флагам).
- **Алиасы**: авто-генерация коротких алиасов (`_generate_aliases`) для 400 каталог-моделей
  создаст коллизии (хвосты вида "spark", "pro"). Рекомендация: каталог-моделям алиасов не
  давать вообще — агенты используют полный id из `available_models_block()`.
- **Промпт-дрейф**: у живых оркестраторов список в промпте устаревает до рестарта —
  осознанно, прикрывается жёстким слоем (F3).

## Собственная схема (вынос на утверждение)

1. **Состояние** — SQLite `kv`: ключ `model_catalog_cache` (нормализованный каталог +
   `fetched_at`) и `model_flags` (`{id: {dashboard: bool, agents: bool}}`). Писатель —
   новый `kv_set()` в app/db.py. Один владелец состояния — app/models.py.
2. **Регистрация** — старт и кнопка Refresh: fetch каталога → нормализация → per-model
   `register_model()` для ВСЕХ моделей кеша (не только включённых — F3), флаги живут
   отдельно и переживают рефактор реестра. Manifest-модели (`SELECTABLE_MODEL_SPECS`)
   остаются как есть, каталог их дополняет (граница из постановки).
3. **Уровни** — флаг `dashboard` фильтрует `/api/models`; флаг `agents` фильтрует
   `available_models_block()` и жёстко проверяется в create_session при
   `parent_name`/role=worker. Дефолты: manifest — оба true; каталог-модель до включения
   юзером — оба false (в реестре есть, нигде не видна).
4. **Выключение при живом агенте** — флаг, не разрегистрация: агент дорабатывает, новые
   спавны отклоняются, resume работает, смена «с выключенной» разрешена.
5. **Фронт** — модалка каталога на своём эндпоинте, тумблеры пишут флаги, пикер
   (`_showModelPicker`) продолжает читать `/api/models` и потому автоматически получает
   и каталог, и оркестраторскую смену.

Открытый вопрос к оркестратору (решать на PLAN-гейте, не блокирует research): давать ли
юзеру `agents`-тумблер на manifest-моделях (claude/codex/grok). Буква границы — «никуда не
деваются», т.е. остаются зарегистрированными и видимыми; но цитата юзера («ллм дать только
определённый список… сам регулирую») про регулирование всего списка. Рекомендация — дать
`agents`-тумблер и на них (дефолт true), `dashboard`-тумблер не давать.

## Sources

- [1] app/models.py:48–144 (SELECTABLE_MODEL_SPECS), :336–409 (derived views, register/unregister), :479–610 (proxy fetch, clear), :689–702 (available_models_block)
- [2] app/routes/system.py:348–381 (/api/models GET/HEAD), :385–391 (refresh)
- [3] app/routes/sessions.py:124–154 (CreateSessionRequest.validate_model), :245–275 (create_session), :862–876 (change-model)
- [4] app/manager.py:345, :577; app/mcp_stdio.py:804–830 (codex review model resolve), :894–960 (spawn_worker body), :1515–1523 (change_worker_model)
- [5] app/backend_harness.py:130–175 (connect, ключ OPENROUTER_API_KEY), :418–430 (TOKEN_PRICES/CONTEXT_LIMITS); app/harness/llm.py:25 (DEFAULT_BASE_URL)
- [6] app/runtime_registry.py:52–66 (RuntimeCapabilities defaults), :393–403 (harness definition)
- [7] app/db.py:493–506 (kv table, kv_get; writer отсутствует)
- [8] app/static/js/app.js:1207, 2517–2531 (_ensureModels), 2592–2646 (_showModelPicker), 2680–2693 (change button), 1626 (orchestrator create)
- [9] Measurement: `curl https://openrouter.ai/api/v1/models` — 200, 421 models, 689403 B, 22 free, 352 with tools (2026-08-22, /tmp/or_models.json)

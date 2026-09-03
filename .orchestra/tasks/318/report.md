# #318 — полоса Claude в горячей политике + живая карта квот на фронте

## Что просили (после уточнения юзера)
1. Порог для КАЖДОГО пула, по которому мы упираемся, — в той же горячей политике
   (`quota_controller_policy`), а не только для Codex-полос. Для Claude порог считается
   ТОЛЬКО по недельному окну; пятичасовое — справочное.
2. Фронт: живая карта вместо статичного артефакта — расход по пулу, до сброса, что доступно
   и каким порогом. «Простой понятный график», попадание в стиль дашборда.
3. Честно назвать режим: сейчас решает статический порог, адаптивный контроллер — отдельно.

## 1. Полоса `claude` в горячей политике

Дефолт **90.0** — не выдуманное круглое число, а абсолютный worker-стоп уже принятой политики
#227: `pipelines/default/pipeline.yaml:17` (`absolute_block_pct: 90`, комментарий строкой выше:
«Потолок 90% резервирует последние 10% под оркестраторов/кеш») и его реализация в
`app/manager.py:646`. Ссылка на источник продублирована комментарием в обоих местах, где
значение живёт (`app/db.py QUOTA_POLICY_DEFAULTS`, `app/quota_gate.py
CLAUDE_WORKER_WEEKLY_LIMIT_PCT`), равенство этих двух наборов закреплено кодом:
`lane_threshold()` — единственный владелец «полоса → порог».

Соответствие «модель → полоса» тоже стало одним владельцем — `policy_lane_for_model()`
(`app/quota_gate.py`). До правки оно было размазано по `evaluate_worker_admission` и
`_alternatives`, причём во втором месте anthropic гейтился жёсткой константой 95 и разошёлся бы
с полосой при первой же операторской правке.

### Миграция схемы
`quota_controller_policy` создавалась с `CHECK (lane IN ('sol','luna','spark'))`. SQLite не умеет
менять CHECK, а страж схемы (`_quota_controller_schema_complete`) сверяет сохранённый текст
`CREATE` дословно — поэтому `ALTER TABLE ... RENAME` не подходит (SQLite записал бы другой текст,
и страж упал бы `incompatible quota controller object`). `_migrate_quota_policy_lanes()` читает
строки, дропает таблицу и пересоздаёт её ТЕМ ЖЕ оператором, что и путь создания
(общая константа `_QUOTA_POLICY_TABLE_SQL`), затем возвращает строки.

**Проба на копии ЖИВОЙ БД** (`sqlite3.Connection.backup`, не `cp` — при WAL копия файла отдаёт
устаревший срез):

```
BEFORE schema:  IN ('sol','luna','spark'))
  BEFORE row: luna 98.0 rev 1 | initial default
  BEFORE row: sol 95.0 rev 1 | initial default
  BEFORE row: spark 95.0 rev 1 | initial default
  audit rows before: 0
AFTER lanes: {'claude': (90.0, 1), 'sol': (95.0, 1), 'luna': (98.0, 1), 'spark': (95.0, 1)}
AFTER schema:  IN ('sol','luna','spark','claude'))
audit rows after: 0
LOST/CHANGED existing lanes: none
second read ok, revision: 1   ← идемпотентно
```

Новая полоса встаёт на ТЕКУЩУЮ максимальную ревизию набора (не на 1), иначе она выглядела бы
старее остальных, а CAS в `replace_quota_policy` читает максимум.

### Побочный эффект, принятый оркестратором осознанно
Воркеры на Claude блокируются с **90%** недельного окна вместо прежних 95%. Оркестраторы гейт не
проходят вовсе (`app/session.py:1207`, `:2032`, `:2248`) — это и есть резерв #227. Живого эффекта
сейчас нет: Claude 7d = 9%. В панели факт назван прямо, отдельной строкой на карточке Claude.

## 2. Живая карта (фронт)

`GET /api/usage/quota-map` (`build_quota_map()` в `app/routes/system.py`) отдаёт вердикты
**самого гейта**: для каждой зарегистрированной модели зовётся `evaluate_worker_admission` с тем
же снимком телеметрии и той же политикой, что и на реальном допуске. Пороговой арифметики в JS
нет вовсе — разойтись с гейтом карта не может по построению.

Ключевые свойства payload:
- `bucket.window` — ТОЛЬКО недельное окно (`window_minutes == 10080`), оно и решает допуск;
  `bucket.reference_windows` — всё остальное (у Claude это 5h), справочно.
- `bucket.data_available=false` + `window=null`, когда недельного окна в телеметрии нет. Пул без
  данных рисуется как «нет данных», а не как 0% (Grok сейчас отдаёт `null` целиком — он вообще не
  попадает в карточки, только в строку «вне недельной политики»).
- у моделей вне политики `threshold: null` — печатать им чужой дефолт означало бы выдать пустоту
  за число.

Карта едет **в общем снимке аналитики** (`payload["quota_map"]`), а не отдельным запросом:
модалка сохраняет контракт «один запрос на открытие»
(`test_modal_uses_one_snapshot_request_and_tabs_do_not_refetch` остался зелёным без правок).
Журнал правок операторский и в общий снимок намеренно не входит (решение #320), поэтому он
тянется по кнопке «Журнал правок» — не на каждом открытии.

Панель (`_analyticsQuotaMapPanel` в `app/static/js/analytics.js`, стили в `style.css`): по одной
карточке на пул — крупный процент, время до сброса, шкала с отметками порогов, чипы моделей
(зелёная «доступна» / красная «блок» с порогом), внизу ползунки порогов + причина + «Применить
пороги» (PUT с CAS по `revision`) и «Откатить к defaults».

Проверка правки — подменой файлов через Playwright (`page.route` на `js` И `css`), факт
применения — `typeof _analyticsQuotaMapPanel === "function"` в рантайме живой страницы.

## 3. Режим назван прямо — и премисса задания уточнена

Панель печатает: «Сейчас режет ход: статический порог — TEMPORARY STATIC OVERRIDE, source
temporary_static_override, revision N, изменён …».

**Уточнение к постановке:** адаптивный контроллер НЕ является чисто shadow-only.
`enforce_new_worker_turn` (`app/quota_controller.py`) возвращает `hold` при свежей и уверенной
адаптивной телеметрии, а `app/session.py:1452` превращает это в `QuotaGateError(code=
"adaptive_quota_hold")`. Killswitch `ORCHESTRA_ADAPTIVE_ENFORCEMENT` по умолчанию ВКЛЮЧЁН
(`adaptive_enforcement_enabled()`, дефолт «1»), на живом сервере `enforcement_active: true`.
Поэтому панель пишет не «shadow», а честно: killswitch включён, tier precalibration, держит ход
только при свежей телеметрии, иначе решает тот же статический порог, и рядом — число фактических
hold за период. Адаптивный enforcement я не включал и не выключал (#314 — отдельное решение).

## Правки чужих тестов (разрешены оркестратором явно)

Правились ЧИСЛА, не поведение: 95 было константой гейта, а не свойством системы. Ожидания стоят
литералами — тест обязан краснеть при смене политики.

| тест | фикстура до → после | ожидание до → после | сторона границы |
|---|---|---|---|
| `test_quota_gate::test_exact_weekly_threshold_for_each_bucket[anthropic]` | 94.9 / 95 → `threshold-0.1` / `threshold` при `threshold=90` (литерал в parametrize) | available/blocked | сохранена: ниже порога → available, ровно на пороге → blocked |
| `test_quota_gate::test_short_window_does_not_block_weekly_headroom` | weekly 94 → 89 (5h остаётся 100) | available, `weekly_utilization == 94 → 89` | сохранена: weekly под порогом, 5h допуск не решает |
| `test_quota_policy::test_policy_defaults_and_exact_boundaries` | + случай anthropic 89 / 90 | набор полос +`claude: 90.0` | добавлена пара по обе стороны новой границы |
| `test_usage_readiness::test_readiness_endpoint_exposes_worker_weekly_policy` | `_anthropic(95)` без изменений | `threshold == 95 → 90` | сохранена: 95 выше порога, решение по-прежнему blocked |

Пятый тест из моего запроса — `test_mcp_quota_gate::test_spawn_uses_role_aware_server_preflight_
and_execution_recheck` — **править не понадобилось: он падает и БЕЗ моих изменений**. Проверено
прогоном на чистом дереве (`git stash` → тот же `1 failed`), файл теста побайтно совпадает с main,
`app/` между базой ветки `bf70e3ad` и main не менялся. Предсуществующее падение, не мой регресс.

## Мутационные прогоны

Протокол на каждый: `cp` → мутация → прогон → `mv` обратно → `grep -c` маркера ДО и ПОСЛЕ →
`touch` → зелёный повтор. Мутировались только зелёные тесты.

| # | файл, мутация | что покраснело | после отката |
|---|---|---|---|
| M1 | `quota_gate.py`: `CLAUDE_..._PCT 90.0 → 95.0` | `test_exact_weekly_threshold[anthropic-90]` (sol/spark остались зелёными) | 32 passed |
| M1b | `quota_gate.py`: недельный фильтр окна → «любое окно» | `test_short_window_does_not_block_weekly_headroom` | 1 passed |
| M2 | `db.py`: `"claude": 90.0 → 95.0` | 4 теста в трёх файлах (policy, readiness, map) | 22 passed |
| M3 | `db.py`: миграция отключена (`return` в начале) | `test_existing_three_lane_database_migrates_...` (`OperationalError: incompatible quota controller object`) | 6 passed |
| M4 | `system.py`: гейтящим становится ЛЮБОЕ первое окно | `test_claude_five_hour_window_is_reference_and_never_gates`, `test_pool_without_weekly_telemetry_is_no_data_not_zero` | 6 passed |
| M5 | `analytics.js`: `tone` всегда `'ok'` | `test_blocked_pool_is_red_and_names_the_models_it_stops` | 8 passed |
| M6 | `analytics.js`: ветка «нет данных» отключена | `test_pool_without_weekly_telemetry_says_no_data_not_zero` | 7 passed |
| M7 | `system.py`: `quota_map` в снимке подменён пустым | `test_analytics_snapshot_carries_the_map_in_one_request` | 7 passed |
| M8 | `system.py`: owner-гейт отключён | `test_non_owner_dashboard_gets_no_subscription_percentages` | 8 passed |

M5 прогонялся дважды — до и после переезда карты в общий снимок.

## Пре-мортем: что могло сломаться и чем закрыто

1. **Миграция на боевой БД** (DROP+CREATE в транзакции) → проба на копии живой БД выше,
   плюс `test_existing_three_lane_database_migrates_without_losing_revisions` (M3).
2. **Claude-воркеры блокируются раньше** → авторизовано, покрыто литеральными тестами, названо в
   панели («порог останавливает воркеров; оркестратор продолжает работать»).
3. **Лишние запросы модалки** (первая версия делала 3 запроса и роняла
   `test_modal_uses_one_snapshot_request...`) → карта переехала в общий снимок, журнал по кнопке;
   контракт защищён `test_map_costs_no_extra_request_on_open` (M7).
4. **Утечка процентов подписки на не-owner дашборде**: `/api/usage` возвращает `None` вне owner
   mode, а карта читала кеш напрямую → добавлен тот же гейт, тест + мутация M8.
5. **Старый бэкенд + новый JS** (JS доезжает сразу, Python — только рестартом): проверено на живом
   :8888 подменой файлов. Панель рендерится, честно пишет «Живая карта пулов не загрузилась:
   снимок не содержит карту квот. Пороги ниже — из снимка политики», ничего не падает и нулей не
   выдумывает. Скриншот `q318-live-degraded.png`.

## sync-Playwright травил async-тесты в одном прогоне — починено в корне

**Первое лечение было негодным и отбито тест-гейтом.** Я предложил «называть браузерный файл так,
чтобы он сортировался рядом с существующими, и гонять его отдельным вызовом pytest». Гейт собирает
мапнутые тесты в ОДИН прогон и про такую договорённость не знает: отдельный вызов делает человек,
а машина — нет. Мерж справедливо отбился на
`RuntimeWarning: coroutine 'test_readiness_endpoint_exposes_worker_weekly_policy' was never awaited`.

### Механизм (замерен, а не предположен)
Фикстура `playwright` в pytest-playwright — **сессионная**: `sync_playwright().start()`, а `stop()`
только в конце сессии. Пока она жива, в главном потоке висит ЗАПУЩЕННЫЙ event loop, и
`asyncio.Runner.run()` внутри pytest-asyncio отказывается работать. Проба (тест, печатающий
`asyncio.events._get_running_loop()`):

```
проба одна:                     running_loop=None
после test_t314_..._browser.py: running_loop=<_UnixSelectorEventLoop running=True closed=False>
после файла со СВОЕЙ закрытой сессией: running_loop=None
```

Последняя строка и есть лечение: если сессия sync-Playwright закрывается, петля исчезает.

### Что сделано
`tests/conftest.py` переопределяет цепочку фикстур pytest-playwright (`playwright`, `browser_type`,
`launch_browser`, `browser`) с **модульной** областью — каждый браузерный файл закрывает свою
сессию за собой. Опции запуска (`browser_type_launch_args`, `browser_name`) берутся у
pytest-playwright, непокрытый режим `connect_options` (удалённый браузер) падает громко, а не
расходится молча. Файловый костыль в самом тесте убран: владелец правила один.

Выбран этот путь, а не исключение браузерных из мапнутого набора гейта: второй вариант вывел бы
браузерное покрытие из защиты мержа — ровно те тесты, которые проверяют, что панель красная на
99% Codex и «нет данных» вместо нуля.

### Проверка — тем сценарием, который упал, и шире
| прогон (один процесс, алфавитный порядок) | до фикса | после |
|---|---|---|
| `test_t318_quota_map_browser.py` + `test_usage_readiness.py` | 8 failed / 8 passed | **16 passed** |
| `test_t314_analytics_browser.py` + `test_usage_readiness.py` (предсуществующий случай) | 8 failed / 4 passed | **12 passed** |
| `pytest tests/ -k "quota or usage or admission"` (429 тестов) | 48 failed, 24 errors | **3 failed, 426 passed, 0 errors** |
| `t314` + `test_usage_analytics_frontend.py` + `test_frontend.py` | 3 failed, 9 passed, 82 errors | **94 passed** |

Отравление никуда не переехало: в широком прогоне ноль errors и ни одного
`Runner.run() cannot be called…`. Оставшиеся 3 падения — предсуществующие, воспроизводятся на
дереве без моих правок (`test_mcp_quota_gate::test_spawn_uses_role_aware_...`,
`test_mcp_codex_review::{test_codex_review_resume_command_passes_usage_arguments,
test_new_mcp_records_usage_through_unchanged_bg_route}`; последние два падают на
`row["model"] == "gpt-5.6-sol"`, моих файлов в трейсе нет).

Побочный эффект правки — приятный: 82 ошибки в `test_frontend.py` и 24 ошибки в
frontend-файлах были следствием той же петли и исчезли. Цена — браузер поднимается на файл, а не
на сессию (единицы секунд на файл).

## Что НЕ делалось
Адаптивный enforcement не включался (#314), сервис не рестартовался, `uvicorn` не поднимался,
живая БД не менялась (все пробы — на копии).

## Требуется рестарт
Python-часть (маршрут, карта в снимке, полоса в гейте, миграция) доедет только рестартом.
JS/CSS отдаются из главного чекаута и работают сразу после мержа — на старом бэкенде в
деградированном, честном виде.

## Скриншоты
- `docs/tasks/318/screenshots/live-numbers.png` — панель на ЖИВЫХ числах (Claude 7d 9% / 5h 58%,
  Codex 99% → Sol и Luna блок, Spark 39%, Grok вне политики), карта посчитана офлайн тем же
  `build_quota_map()` из ответа живого `/api/usage`.
- `docs/tasks/318/screenshots/fixture-1600.png`, `fixture-900.png` — фикстурные числа, две ширины.
- `docs/tasks/318/screenshots/live-degraded.png` — как панель выглядит на живом :8888 ДО рестарта.

# V-1210 — model-picker CI regression

Исправлены причины падений после V-1205 и обнаруженный дефект восстановления
выбора. Полная интеграционная приёмка в этой worker-copy **заблокирована**;
дополнительные browser-прогоны ниже не заменяют её.

## Причины и изменения

- `tests/test_orchestrator_defaults_v1156.py` извлекал `_renderModels` без новой
  `_isModelChoiceHidden`: воспроизведён `ReferenceError`. Harness теперь загружает
  настоящую функцию видимости из того же production-файла. Все прежние ожидания
  default, ручного выбора, удаления/возврата модели и единственного listener сохранены.
- Три параметра `test_model_picker_preserves_same_runtime_dialog_and_surfaces_transfer_result`
  загружали только тело picker и reason-helper. На каждом воспроизведён
  `ReferenceError: _closeModelPicker is not defined`. Harness теперь подключает
  production-helper block перед picker (состояние, видимость, группы,
  позиционирование, context hint, reason и history transfer) и `theme.js`.
  Поведенческие guards и точный API payload сохранены. Дополнительно проверяются
  реальный status-диспетчер переноса, обновление выбранной модели, reload и закрытие.
- В `app/static/js/app.js` восстановление `<select>` проверяло полный каталог,
  хотя options уже исключали GigaChat. Присваивание скрытого default или сохранённой
  модели обнуляло выбор. Все три соответствующие browser-проверки сначала упали.
  Проверка явного выбора и default теперь использует тот же список видимых choices,
  что и options. Полный `_MODELS` сохраняется для существующих сессий и подписей.
- Две source-string проверки нового selector заменены поведением настоящего DOM:
  восемь комбинаций default/сохранённого выбора, скрытие по provider и регистронезависимому
  id, refresh с исчезновением и возвращением выбора, отсутствие видимых choices
  и восстановление каталога. Остальные popover-тесты сохранены. Новых проверок
  UI-фраз нет. Changelog добавлен только для исправленного product-поведения.

## Что запущено

В каждом shell использован provisioned `uv 0.11.28`, `uv run --frozen`, default
`.venv`, исходный `uv.lock` (Playwright 1.60.0). `TMPDIR`, pytest basetemp/cache
направлены в ignored `raw/` этой задачи. Импортирован локальный `app/__init__.py`;
его абсолютный `app.__file__` сохранён в ignored `raw/runtime.log`.

1. До правок: обязательный Node + три исходных browser cases + V-1205 module:
   **1 failed, 1 passed, 12 errors**. Node воспроизвёл известный ReferenceError;
   browser cases остановились на setup (ниже). Лог: `raw/red.log`.
2. Дополнительный запуск **исходных трёх test body**, без dashboard fixture,
   через installed Chromium revision **1248 / 156.0.8078.4**: **3 failed** с
   `_closeModelPicker is not defined`, после исправления **3 passed**.
   Параметры: own Sonnet, hub Sol, hub Sonnet с reason.
   Логи: `raw/browser-body-red.log`, `raw/browser-body-green.log`.
3. После исправления Node harness, до product-fix: Node + расширенный
   `tests/test_model_picker_v1205.py` через тот же Chromium 1248:
   **3 failed, 17 passed**. Лог: `raw/product-red.log`.
4. После product-fix: оба Node selector tests + весь V-1205 module:
   **21 passed** (19 browser cases и 2 Node). Лог: `raw/green.log`.
5. Регрессии: весь `tests/test_orchestrator_defaults_v1156.py`,
   `tests/test_hub_model_reason_frontend.py::test_reason_stays_in_info_only_and_claude_selection_requires_input`,
   весь `tests/test_change_model_unloaded.py`: **26 passed**.
   Проверены default manifest/registry, reason gate, загрузка сессии, scope и
   отказ API без ложного успеха. Лог: `raw/regression.log`.

Дополнительные browser-запуски используют существующий opt-in `MODEL_PICKER_CHROME`.
Сетевых provider-вызовов и боевой DB не было. Настройки глобального Git,
зависимости, lock и dashboard fixture не менялись.
Diff всех пяти изменённых исходных файлов просмотрен; `node --check` прошёл,
изменённые Python-тесты разбираются AST, добавленные строки прошли проверку
пробелов и `app.secret_mask.mask_secrets` без обнаруженных значений секретов.

## Follow-up: убрать проверки wording

По запросу оркестратора из указанного `test_frontend` удалены девять буквальных
asserts по исходному JS. Все проверки API payload/reason, status-диспетчера,
выбранной модели, reload и закрытия сохранены. AST-сравнение подтвердило, что
остальной тестовый модуль не изменён; SHA-256 подтвердил неизменность product-файла
относительно состояния перед этим follow-up. Соседние тесты не правились.

Повторная проверка тем же provisioned uv/default `.venv`: три test body на Chromium
1248 — **3 passed** (`raw/browser-body-wording-cleanup.log`). Обязательный pytest
с исходной dashboard fixture — **3 setup errors**, прежний `Author identity unknown`
(`raw/full-wording-cleanup.log`). Это не заменяет полную pinned-browser приёмку.

## Follow-up: core guard после отказа merge gate

После `tests_not_guarding_source` у merge
`a4103950-e982-4eed-a340-a7b1c3d313c4` расширен существующий **nonbrowser**
`test_picker_tracks_automatic_default_but_keeps_explicit_user_selection`.
Он исполняет production `_isModelChoiceHidden` и `_renderModels` через Node,
без проверок текста JS. Прежние ожидания сохранены.

Добавлены скрытый GigaChat default, сохранённый скрытый выбор, скрытие по provider
и id, разрешённый явный выбор при скрытом default, переход visible → hidden → visible,
пустой список choices и восстановление, сохранность полного `_MODELS`, сброс
invalid `userSelectedModel`. Fake select теперь, как DOM, сбрасывает `.value` в
пустую строку при присваивании отсутствующего option: простое свойство скрывало
точный симптом браузера.

Проверено provisioned uv 0.11.28/default `.venv`, без браузера и с явным
`-m 'not browser'`:

- Baseline расширенного Node-теста: **1 passed**, `raw/core-baseline.log`.
- Затем временно установлен **точный исходный `app.js` до product-fix**:
  откат всего `_renderModels`, включая три места `choices → models` и прежний
  skip скрытых options. Остальной файл совпадал с baseline. Тот же неизменённый
  core-тест получил **1 failed**, именно `AssertionError` по результату выбора
  и сохранённому invalid selection, а не setup/import failure.
  Например, `hiddenExplicit` вернул `{value: '', saved: 'GigaChat-2-Max'}` вместо
  `{value: 'terra', saved: null}`. Лог: `raw/core-rollback.log`.
- Product-файл восстановлен в `finally` и проверен байт-в-байт / SHA-256.
  После восстановления весь `tests/test_orchestrator_defaults_v1156.py`,
  reason Node guard и `tests/test_change_model_unloaded.py`:
  **26 passed**, `raw/core-restored.log`.

AST-сравнение подтвердило, что в этом follow-up изменён только целевой Node-тест;
product и соседние тесты остались прежними. Добавления прошли publication filter.
Терминальный merge не повторялся. Новый HEAD создаёт платформа при импорте;
приёмку/merge нужно начинать уже для него. Полная browser-приёмка остаётся
ограниченной указанными ниже блокерами.

## Что остаётся непроверенным

- Locked Playwright требует `chromium-1223` / `chromium_headless_shell-1223`;
  они отсутствуют. Доступен только revision 1248. Его результаты выше —
  дополнительные, **это не pinned-browser acceptance**.
- Полный исходный `dashboard_browser` останавливается до открытия страницы:
  тестовый task-store в lifespan пытается создать свой первый Git-коммит и получает
  `TaskConflict: Author identity unknown`. После исправлений обязательные три
  cases повторно запрошены с неизменённой fixture: **3 setup errors**,
  тот же `Author identity unknown`; лог `raw/full-final.log`.
  Для полного прогона нужен runner с корректно настроенным тестовым Git identity
  и Chromium revision 1223. Обхода startup или ослабления fixture в patch нет.
- Full suite / CI run 41387761950 не проверены; здесь нет `.git`/remote и
  `scripts/run_tests.py`. В исходном полном checkout необходим прогон:

  ```sh
  uv run --frozen python -m pytest tests/test_orchestrator_defaults_v1156.py tests/test_frontend.py::test_model_picker_preserves_same_runtime_dialog_and_surfaces_transfer_result tests/test_model_picker_v1205.py -q
  ```

Raw-логи, временные DB и исходные копии лежат в `raw/`, закрытом собственным
`.gitignore`; в коммит идёт этот переносимый отчёт и ignore-файл, не raw.
Worker не выполняет commit/push: импорт в `task-V-1210/fix-model-picker-ci`
и коммит делает платформа после завершения turn.

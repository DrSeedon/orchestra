# V-1113 — снять гейт на час

Добавлена кнопка «снять гейт на час» (`lift gate for an hour`) рядом с выбором
даты, только при состоянии `on`. Отправляет POST `/api/usage/quota-override`
с телом ровно `{minutes: 60}`. Общий обработчик сохраняет ошибки в
`#quota-gate-error` и повторно загружает серверное состояние. Выбор даты
и возврат гейта (`minutes: 0`) сохранены. Добавлена строка CHANGELOG.

Браузерные проверки покрывают точный запрос без заполнения даты, RU/EN,
состояния on/override/off/nodata, отсутствие оптимистического переключения,
ошибку и повторную попытку. Старый скриншот V-862 перенесён в `tmp_path`:
трековые PNG не перезаписывались.

Проверено provisioned uv 0.11.28, стандартная `.venv`, lock не менялся:

- Обязательная команда `uv run --frozen python -m pytest
  tests/test_t344_quota_lines_browser.py tests/test_quota_map_api.py -q`:
  **не выполнена успешно**, collection error `No module named 'app.db'`.
  Отдельный штатный запуск браузерного файла также блокируется общей
  conftest-фикстурой: `No module named 'app.task_refs'`.
- В копии отсутствует Playwright Chromium headless shell revision 1223.
  Fallback на установленный Chrome, без общего conftest:
  `uv run --frozen python .orchestra/tasks/V-1113/check_browser.py` —
  **35 passed in 38.14s** (`browser-isolated.log`). Это отдельная проверка,
  не замена обязательному прогону/API-тестам.
- Тот же fallback с `--mutate-hour` подменяет 60 на 61 только в скрипте,
  загружаемом в браузер: **2 failed, 33 deselected**, обе ошибки на
  сравнении `{'minutes': 61} != {'minutes': 60}` (`mutation.log`).
- `nodejs --check` для обоих изменённых JS — успешно.

Для всех Python-команд PATH начинался с
`$HOME/.local/share/orchestra/tools/uv/0.11.28/bin`.
Для Chrome нужен относительный `TMPDIR=.orchestra/tasks/V-1113/tmp`
(предварительно `mkdir -p`): абсолютный путь этой копии превышает предел
Unix-сокета Chrome. Все временные файлы оставались внутри проекта.
Импортированный `app` — namespace package (`app.__file__ is None`), путь:
`<hub-workspace>/app`.

Остаётся обязательный прогон в полной копии с нужными исходниками и Chromium.
Git в копии отсутствует; коммит в `task-V-1113/fix-gate-hour` выполняет
платформа после возврата результата. Сервисы не запускались и не менялись.

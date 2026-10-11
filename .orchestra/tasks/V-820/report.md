# V-820: статус скрытых оркестраторов

Меню `👁` теперь показывает каждому скрытому оркестратору его статусный значок, имя и cache pill. Меню использует `_paintStatusDot`, `_orchState` и общий cache pill builder `_orchCachePill`, который теперь применяется и к закреплённым вкладкам. Поэтому running/waiting/idle в обоих местах читаются из одного объекта `orchData`; ожидание отображается как 📆. Открытое меню перерисовывается вместе с обновлением вкладок и `updateOrchTabDots`, а существующий 30-секундный countdown обновляет cache pills в меню тем же `_renderCachePill`.

Playwright открыл живой dashboard на `127.0.0.1:8888` с текущими данными `/api/orchestrators`; маршрут `app.js` был подменён на версию из этого worktree, чтобы проверить незамерженную правку без рестарта. В отдельном браузерном localStorage выбрал 7 текущих имён скрытыми и снял [.orchestra/tasks/V-820/after.png](after.png). Это состояние затронуло только браузерный контекст.

Browser regression test `test_hidden_orchestrator_list_reuses_tab_status_and_cache` сравнивает status/cache поля скрытого пункта и закреплённой вкладки для running, waiting и idle, затем меняет состояние в источнике `orchData` и проверяет обновление уже открытого меню.

Merge gate выбирает тесты `tests/test_<stem>.py` для изменённых `app/*.py` модулей и изменённые тестовые файлы из diff. Затем `pytest_argv()` запускает `pytest -m "not live_probe and not browser"`. `tests/conftest.py` автоматически ставит маркер `browser` тестам, использующим фикстуры `browser` или `dashboard_browser`; поэтому Playwright проверка выше была исключена из блокирующего gate. Новая проверка не запрашивает браузерную фикстуру и остаётся в выборке.

Именно `tests/test_frontend.py` выбран из diff; `app/static/js/app.js` — изменённый source для mutation gate. `changed_test_nodes()` выбрал безопасный fallback всего тестового файла (`selected_nodes=[]`, `fallback_files=["tests/test_frontend.py"]`), поэтому после фильтра `browser` gate выполнил его non-browser тесты, включая новую проверку `test_hidden_orchestrator_menu_shares_tab_status_and_cache_builders`.

Проверка настоящим rollback выполнена через `evaluate_mutation_gate()` с target `main` (`8c00c71c72dbfc1ce83524c3085633895689d7f1`). Control tree использовал изменённый `app.js`, target tree — версию из `main`; в обоих деревьях были одинаковые тестовые файлы. Control прошёл 14 тестов, в том числе новый guard; с target source упал только этот guard. Результат mutation gate: `PASSED / guarded_source_change`, `mutation_failed_tests=["tests/test_frontend.py::test_hidden_orchestrator_menu_shares_tab_status_and_cache_builders"]`. Полный JSON сохранён в `mutation-gate.log`.

## Проверки

`uv run --frozen python -m pytest tests/test_frontend.py::test_hidden_orchestrator_menu_shares_tab_status_and_cache_builders -q` — 1 passed; эта non-browser проверка входит в mutation gate.

`uv run --frozen python -m pytest tests/test_frontend.py::test_hidden_orchestrator_list_reuses_tab_status_and_cache -q` — 1 passed. `node --check app/static/js/app.js` и `git diff --check` прошли.

`uv run --frozen python -m pytest tests/test_frontend.py -q` — 120 passed, 1 skipped in 117.67s. Полный вывод сохранён в `frontend-tests.log`.

JS/CSS подхватываются без рестарта; рестарт не выполнялся.

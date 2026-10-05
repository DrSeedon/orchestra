# V-700 — CI, i18n и dashboard

| Пункт | Исход | Доказательство |
|---|---|---|
| T001 | Исправлено | `.github/workflows/ci.yml` переключён на `actions/checkout@v5` и `astral-sh/setup-uv@v7` в обеих job. В метаданных upstream `action.yml` обеих версий указано `using: node24` (проверено `curl` и страницы репозиториев GitHub); в workflow больше нет ссылок на v4/Node 20. |
| T002 | Исправлено | API-метка полосы Claude стала нейтральной `Claude workers`; `quota-lines.js` переводит её на стороне клиента во всех выводах панели. `test_claude_lane_label_follows_dashboard_language` проходит. Mutation: возврат непереведённого `_qlLaneLabel` уронил committed test: gate pill показал `Claude workers` вместо `Claude-воркеры`. |
| T003 | Исправлено | `analytics.js` форматирует суммы, числа и даты с локалью `orchLang()`, `usage.js` так же форматирует дату сброса и сохраняет часовой пояс Asia/Krasnoyarsk. `test_dashboard_numbers_and_dates_follow_the_selected_language` прошёл в en/ru. Mutation: принудительный `ru-RU` уронил committed test на английской сумме: `$212,8` вместо `$212.8`. |
| T054 | Исправлена проверка | Тест дожидается загрузки выбранного агента и проверяет, что динамический placeholder попал в набор проверяемых атрибутов; это исключает зелёный результат до появления значения, для которого нужен `{agent}`. `tests/test_i18n_dashboard.py::test_dictionary_reaches_marked_attributes` — 1 passed (после изменения). |
| T113 | Исправлено на бэке и фронте | `_usage_providers_from_row` и `_historyProviders` включают `utilization: 0` без `resets_at` для окон 5h и 7d; NULL по-прежнему исключён. Тесты backend (оба окна) — 2 passed; browser test обеих серий — 1 passed. Mutation старого truthy-фильтра отдельно на каждом слое уронила соответствующий committed test: API потерял `anthropic`, график вывел «This provider has no history». |
| T114 | Дефекта уже нет | Строки-оракула `expect(chat).to_contain_text("🟠 High")` нет ни в `tests/test_frontend.py` текущего дерева, ни в версии этого файла на `71a008fe`; проверено точным поиском. Исходный пункт TODO описывает несуществующий в зафиксированном исходнике ассерт. |
| T115 | Дефекта уже нет | `app/static/js/app.js::_refreshContextAfterTurn` удаляет кэш контекста на переходе running → завершённое состояние и повторно вызывает `fetchAgentContext` для выбранного агента. Уже имеющийся `tests/test_frontend_context_panel_468.py::test_live_stream_completion_refreshes_selected_agent_context` прошёл в парном запуске (2 passed вместе с T054). |

## Проверки

- `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_dashboard_i18n_formatting.py tests/test_usage_history_resolution.py::test_history_includes_a_real_zero_without_reset_metadata tests/test_usage_history_frontend.py::test_real_zero_without_reset_metadata_draws_a_chart tests/test_t344_quota_lines_browser.py::test_claude_lane_label_follows_dashboard_language -q` — 4 passed; затем расширенный backend-кейс отдельно — 2 passed, последняя версия browser-кейса — 1 passed, перевод gate pill — 1 passed.
- `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_i18n_dashboard.py::test_dictionary_reaches_marked_attributes -q` — 1 passed; вывод сохранён в `t054.log`.
- `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_i18n_dashboard.py::test_dictionary_reaches_marked_attributes tests/test_frontend_context_panel_468.py::test_live_stream_completion_refreshes_selected_agent_context -q` — 2 passed.
- Mutation checks: T002, T003 и оба слоя T113 временно возвращались к дефектному поведению; в каждом случае соответствующий committed test падал. Рабочий код восстановлен, финальные проверки зелёные.
- T001 runtime: upstream `action.yml` на ветках v5/v7 сообщает соответственно `using: node24` и `using: "node24"`; `.github/workflows/ci.yml` содержит только эти версии.
- `git diff --check` — без замечаний.
- Путь импорта тестов: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-dashboard/app/__init__.py`.

Перезапуск Orchestra не выполнялся. Изменений Python-кода требуют рестарта владельцем, чтобы попасть в живой процесс.

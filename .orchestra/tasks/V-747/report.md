# V-747 — форматирование процентов utilization

| Пункт | Исход | Доказательство |
|---|---|---|
| `28.999999999999996%` в usage strip | Исправлено на фронте общим форматтером | В `app/routes/system.py::_apply_claude_rate_limit_event` доля `0.29` умножается на 100; вызов функции вернул `28.999999999999996`. `/api/usage` возвращает актуальные данные без округления. До форматирования браузер напрямую интерполировал число в `_miniBar`. |
| Остальные отображения процентов из usage/quota payloads | Исправлены тем же форматтером | `_formatPercent` из `utils.js` используется в компактной полосе, деталях и истории usage, карточках и сводке analytics, а также подписях quota-lines. Округление utilization — целый процент; прогресс сброса оставляет 2 знака, cost share и quota tolerance — 1 знак. |
| Регрессия браузерного отображения | Добавлен committed test | `tests/test_quota_headroom_447.py::test_usage_bar_formats_fractional_provider_utilization` подаёт `28.999999999999996` для Claude и Codex, проверяет две видимые строки `29%` и отсутствие исходного float. Chromium: passed. |
| Небраузерная проверка для mutation gate | Добавлен test, который попадает в blocking selection | `test_usage_percent_formatter_guards_strip_without_browser` исполняет извлечённые production-функции `_formatPercent` и `_miniBar` через Node и проверяет HTML-вывод. Он не запрашивает Playwright-фикстуру, поэтому не получает маркер `browser`. |
| Артефакт браузерного теста | Восстановлен | После `tests/test_t344_quota_lines_browser.py` SHA-256 `.orchestra/tasks/V-652/quota-timeline.png` восстановлен к исходному `02c6b7c420b304eebca5766ce95f3d655c217b5d5b3db98f1bd93c9a7e6d461a`. |

Сила регрессионного теста проверена на закоммиченном тесте: временно восстановлены `utils.js` и `usage.js` из родительского коммита без V-747. Тест упал с `visible.count("29%") == 0`, а видимый текст содержал `28.999999999999996%` дважды. Файлы после проверки восстановлены к коммиту V-747; дерево чистое.

### Merge-gate selection

`app/merge_test_gate.py::pytest_argv` исключает `browser` через `-m "not live_probe and not browser"`; `tests/conftest.py` автоматически ставит этот marker тестам, запросившим фикстуру `browser` или `dashboard_browser`. Поэтому Chromium-тест остаётся обязательной ручной/CI-проверкой, но не блокирует merge gate. Новый Node-тест использует только файловые источники и `subprocess`, так что проходит обычный набор. При локальном gate-прогоне изменённый test-файл был выбран как `fallback_files` (добавленные импорты находятся вне функций), два browser-теста deselect, три обычных запускаются: **3 passed, 2 deselected**. На целевых исходниках до V-747 новый тест упал с `formatter is None`; мутационный gate вернул `passed / guarded_source_change` для target `af47aff79026c67aa04b108106bf878d40a50f45`. Изменения `app/merge_test_gate.py` и `tests/conftest.py` не нужны.

Production арифметика является источником дробного значения, а не JS: Python вычисляет `0.29 * 100 == 28.999999999999996`, и endpoint отдаёт это значение. Исправление оставлено на слое отображения; серверная точность остаётся доступной потребителям API.

Проверки через `/home/kesha/orchestra/.venv/bin/python -m pytest`:

- `tests/test_quota_headroom_447.py::test_usage_bar_formats_fractional_provider_utilization` — 1 passed.
- `tests/test_quota_headroom_447.py tests/test_usage_history_frontend.py` — 16 passed.
- `tests/test_usage_analytics_frontend.py` — 17 passed после финальной правки.
- `tests/test_t344_quota_lines_browser.py` — 27 passed.

Итого 60 уникальных browser tests passed. Импортированный модуль `utils.js` загружается перед usage, analytics и quota-lines в `dashboard.html`; все три поверхности используют одну функцию. Отчёт и CHANGELOG описывают отображение; тестовые скриншоты не оставлены в diff.

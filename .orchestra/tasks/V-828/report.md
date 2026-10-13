# V-828: publish_artifact скрывал причину отказа

## Диагноз и воспроизведение

Файл по указанному пути доступен локально: 147 174 байта, владелец `kesha`. Прочитал его через локальную копию; SSH reverse tunnel к laptop-access на `127.0.0.1:2222` вернул `Connection refused`. Исходник не менял. Копия для воспроизведения создавалась временно внутри `/home/kesha/projects/University`, чтобы путь оставался внутри корня University.

Из текущих session metadata `_allowed_roots()` получает для `University-orchestrator` только `/home/kesha/projects/University`. Для `kuzenkov` `cwd` и `worktree_path` оба равны `/home/kesha/orchestra/worktrees/home-kesha-projects-university/kuzenkov`, поэтому путь из основного checkout University для воркера вне зарегистрированного корня.

Сверил только безопасные artifact-параметры из systemd process environment и `/home/kesha/orchestra/.env`: `ARTIFACT_PUBLIC_LINKS_ENABLED`, `PUBLIC_BASE_URL` и `ARTIFACT_LINK_SECRET` не заданы; `ARTIFACT_MAX_BYTES` не задан и использует default 10 MiB. Значит, production `load_artifact_config()` выключает публикацию до проверки source path, а 147 174 байта ниже лимита.

На временной копии 147 174 байта в изолированной SQLite/state директории вызвал `publish_snapshot()` с обоими session `allowed_roots` и effective production artifact config. Оба вызова вернули `ValueError: artifact links are disabled`, так как эта проверка выполняется раньше авторизации пути. С включённой только в probe конфигурацией (test base URL и test secret, не production) тот же файл успешно публикуется с корнем University (`size=147174`, Unicode basename сохранён); для корня `kuzenkov` возвращается `ValueError: source path is outside registered roots`. SHA-256 исходного файла до/после воспроизведения совпал. Следовательно, расширять worker roots для этого исходного пути нельзя; при текущей конфигурации проблема, видимая обеими сессиями, — отключённые public artifact links, а не размер, HTML, base64 или кириллическое имя.

Переключение live конфигурации не выполнялось: в ней отсутствуют публичный base URL и secret. Изменение `.env` или включение внешних ссылок не входит в этот фикс.

## Исправление

`publish_artifact` теперь возвращает ожидаемые `ValueError`-причины от `publish_snapshot` (включая `artifact links are disabled`, `source path is outside registered roots` и `artifact exceeds configured size limit`) вместо общей фразы. Ошибки файловой системы записываются с безопасной причиной errno; неожиданное исключение логируется со stack trace и возвращает HTTP 500 с указанием проверить журнал. `mcp_stdio._api()` уже переносит строковый `error` из HTTP-ответа в `ApiToolError`, поэтому MCP caller теперь получает конкретный отказ.

## Регрессия и проверки

Новая параметризованная проверка вызывает route с тремя настоящими `publish_snapshot` отказами: отключённая функция, source вне roots и превышение лимита; для каждого проверяет HTTP message и запись причины в лог. Отдельная проверка подменяет snapshot storage на неожиданное исключение и требует лог с stack trace и HTTP 500. Перед исправлением все три case падали: route заменял ожидаемую причину на `artifact publication failed; use send_file(path, as_document=True)`.

`tests/test_mcp_stdio.py::test_publish_artifact_surfaces_api_rejection_reason` проверяет, что HTTP 400 body с причиной доходит до MCP `publish_artifact` как `ApiToolError`.

Mutation gate проверил committed тесты против `main` (`5a3c5949f21ed40bbdf4f3557a732442fa25e826`): control на текущем source прошёл все 152 выбранных теста; target-source вариант упал только на четырёх новых route regressions. Результат: `PASSED / guarded_source_change`, `unattributed_failed_tests=[]`. Изменённые тестовые файлы выбраны, но из-за неоднозначных добавленных строк `changed_test_nodes()` безопасно использовал file fallback для `tests/test_artifacts.py` и `tests/test_mcp_stdio.py`. Полный JSON: [mutation-gate.log](mutation-gate.log).

```text
uv run --frozen python -m pytest tests/test_artifacts.py tests/test_mcp_stdio.py -k 'artifact' -q
20 passed, 132 deselected in 7.37s
```

Полный вывод: [tests.log](tests.log). Точная копия воспроизведения и выводы по двум наборам roots: [artifact-repro.log](artifact-repro.log).

Изменён Python в `app/routes/artifacts.py`; для применения в работающем процессе нужен рестарт Orchestra. Рестарт не выполнялся.

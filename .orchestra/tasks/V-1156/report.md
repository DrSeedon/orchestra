# V-1156 — stage A complete; stage B prepared, not activated

Новое поручение владельца 2026-10-31 21:25 KRS заменяет прежнее ограничение на defaults **только для наших native orchestrators**: целевой default — Terra с явным High. Stage A ниже остаётся без изменений hot pipeline. Stage B подготовлен, но НЕ применён: `.orchestra/tasks/V-1156/private/stage-b/stage-b.patch`, candidate files и отдельные tests; порядок и границы — `private/stage-b/README.md`. Применять после доказанной активации Terra в registry живого Python, а не по наличию кода на диске. Перевод существующих сессий принадлежит отдельному protected rollout V-1163. Real bench V-1162 выполняется отдельно; model review остаётся frozen.

Stage B candidate: **8 passed / 0 skips**, 5.54 s; две мутации (High→Low и Terra→Sol default) пойманы ожидаемыми RC1 behavioral failures. Проверены оба role defaults, backend High без inference, старый registry unknown-model отказ, request omitted/explicit model, API visibility и Node picker behavior. Hash-проверка всех пяти затрагиваемых рабочих файлов подтвердила: stage B не применён. Patch parse (`git apply --numstat`) и AST кандидатов успешны. Файл stage-B tests временно исполнялся с repo fixtures и удалён; hot YAML/промпты/routes/JS не менялись. Host/browser acceptance и запуск tests против реально применённого stage B остаются после активации, не объявлены выполненными. Символы для координации с V-1160: `app.routes.system.list_models`, `CreateSessionRequest.validate_worktree`, JS `_renderModels`; патч следует перепроверить на актуальных hunks коллеги.

Добавлена native `gpt-6.1-terra` (GPT-6.1 Terra, OpenAI, Codex), aliases `terra`/`gpt6.1terra`, manual-only и API-equivalent Standard цены 1/0.05/1.25/5 за миллион input/cached/write30m/output. Общий каталог автоматически доставляет модель в UI; frontend-список и новые hub/API routes не требуются. Sol/Codex defaults, Luna protected exception, квотная и billing policy сохранены. Старый GPT-5.6 Terra восстанавливается под прежним exact id и ценами. CHANGELOG обновлён.

Контекст 258400 — только conservative fallback. Принятые родителем safe findings V-1157 подтверждают listing exact Terra на CLI 0.166.0, но не содержат runtime context metadata и не доказывают успешный inference. Публичное API-окно 1.05M не перенесено в CLI. Серверные effort low/medium/high/xhigh/max сохранены; generic default high не заменён provider default low, ultra/none не открыты.

Источники, отдельные contracts и сравнение: [research.md](research.md). AA Index — очки, не проценты интеллекта; matched effort Terra ниже Sol, а половинная цена токена не означает половинную цену задачи (AA Max $0.96/$1.27, Sol High $0.59). Plotly 40/43 против 43/43, $1.31/$2.61, 15/18 с — опубликованный чужой однократный прогон, не наш замер и не статистическая гарантия. AA/OpenAI Terminal-Bench используют разные harness и не смешаны. Платных evals не было.

## Фактические проверки

Runner: provisioned **uv 0.11.28**, `uv run --frozen python -m pytest`, default `.venv`; lock не менялся. `TMPDIR` для каждого запуска внутри task/private. Imported app:

`worker-copy/app/__init__.py`

1. Первый targeted: **94 passed, 4 failed**. Три ошибки нового теста: несуществующий `/unused` cwd; исправлен на fixture tmp_path. Один существующий lifespan-тест не смог инициализировать synthetic task-store без Git author identity. Повтору переданы только shell-local synthetic GIT_AUTHOR/COMMITTER_NAME/EMAIL, без изменения Git config.
2. Релевантный набор ниже: **322 passed, 1 setup error, 0 skipped**, 55.54 s. Единственная ошибка: `test_model_catalog_frontend.py::test_catalog_free_filter_and_admission_work_with_new_and_old_api_payloads` — отсутствует Playwright Chromium headless shell 1223. Это НЕ зелёный browser check. Установка браузера и полный suite не выполнялись. Статические frontend checks и каталог/API checks прошли.
3. `uv run --frozen python .orchestra/tasks/V-1156/mutation_check.py`: **6/6 пойманы**, каждый запуск с RC1 и ожидаемым behavioral FAILED; неверные alias/provider, снятие manual-only, API context вместо CLI fallback, неверные cached/write цены. Все изменённые байты восстановлены в finally.
4. После замены прямого присваивания context на настоящий `_record_token_usage` в тесте и после восстановления мутаций: `tests/test_terra_v1156.py` — **20 passed**, 8.34 s. Проверены aliases/request/backend/provider/context, dashboard hide/show, stored agents=true и billing denial, восстановленный thread и wire effort/model, цена каждого класса токенов, metadata cap/telemetry override и общий Sol quota pool с разрешающим и запрещающим плечом. Дополнительные existing tests проверяют spawn/model-change, Luna exception, registry rebuild, старые данные и recovery.

Релевантный command:

```sh
mkdir -p .orchestra/tasks/V-1156/private/tmp
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1156/private/tmp"
export GIT_AUTHOR_NAME=OrchestraTest GIT_COMMITTER_NAME=OrchestraTest
export GIT_AUTHOR_EMAIL=orchestra-test@example.invalid GIT_COMMITTER_EMAIL=orchestra-test@example.invalid
uv run --frozen python -m pytest tests/test_terra_v1156.py tests/test_models.py tests/test_model_gates.py tests/test_model_flags.py tests/test_model_registry_503.py tests/test_backend_routing.py tests/test_local_luna_route.py tests/test_backend_codex.py tests/test_codex_quota_gate_1121.py tests/test_catalog_api.py tests/test_model_catalog.py tests/test_model_catalog_frontend.py -q
```

Mutation и final shells дополнительно выставляли `UV_OFFLINE=1`, отдельный пустой task/private `CODEX_HOME`, снимали `NOTIFY_SOCKET`. Первый широкий запуск использовал существующие managed-home test fixtures; будущий host acceptance также должен явно задать synthetic CODEX_HOME.

## Артефакты и оставшиеся границы

Raw mechanical outputs находятся в `private/` и закрыты вложенным `.gitignore`: `targeted.log`, `relevant.log`, `final-terra.log`, `mutation-*.log`, `mutations.json`, `mutation-run.log`, `import-path.log`, `source-review.diff`. Временные synthetic test homes удалены после проверки. Scoped diff восстановлен из точных замен и просмотрен; это не Git diff с базовой веткой. AST parse изменённых Python и поиск форм ключей/токенов в изменённых source/tests/notes не нашли проблем.

В source-only копии нет `.git`: **коммит, clean Git WIP и branch diff здесь подтвердить нельзя**. Платформа переносит результат на `task-V-1156/feat-terra` и коммитит; parent должен проверить реальный diff/ignore, провести browser/full-host acceptance по необходимости, merge/push. Production restart/CLI upgrade/live session changes не выполнялись. Model review frozen; AGENTS не изменён. Не проверены реальный Terra inference, фактический runtime context и подписочная стоимость задачи.

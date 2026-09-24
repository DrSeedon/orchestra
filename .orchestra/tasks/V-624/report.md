# V-624: почему полный `pytest tests/` не доходил до конца

Итог: полный прогон проходит целиком и печатает сводку —
`full-final.log`: `= 115 failed, 3877 passed, 51 skipped, 4 deselected, 7 warnings in 722.31s (0:12:02) =`, EXIT=1.
Все прогоны — вне cgroup платформы (`ssh -o BatchMode=yes kesha@localhost`), в собственном `.venv`
worktree (`uv sync --frozen`), импортированный app:
`/home/kesha/orchestra/worktrees/home-kesha-orchestra/bench2-opus55/app/__init__.py` (Python 3.12.3).

Причин две, независимые. Память ни при чём: RSS pytest в умирающем прогоне ~345 МБ
(`proc-base.tsv`), `MemAvailable` 16–17 ГБ.

## Причина 1. rc=137 на ~35–38 % — SIGKILL от нашего же стража рестарта

**Механизм.** `app.routes.system._do_restart_service()` в конце зовёт `_arm_supervisor_exit_guard()`.
Без аргументов он поднимает настоящего помощника `python -m app.restart_guard --pid <os.getpid()>`,
который держит pidfd цели. Как только lifespan-teardown пишет фазу `application_teardown_complete`
(`app/main.py:373`), помощник ставит дедлайн 5 с, а по его истечении шлёт SIGKILL
(`app/restart_guard.py:393`). Тесты пути рестарта глушили `system.os.kill`, но не стража → помощник
взводился на сам процесс pytest и оставался взведённым. Первый же позднейший тест, прошедший вход/выход
`TestClient(app)`, писал маркер teardown, и через 5 с pytest умирал без сводки (обёртка uv — EXIT=137).

**Доказательства.**
- Базовый прогон: `full-base.log` обрывается на `test_logs_sync.py::TestRoute::test_endpoint_clamps_arguments`
  (тест с `TestClient`), `EXIT=137 elapsed=399s`; обёртка жива, убит только pytest.
- bpftrace на `signal:signal_generate` (`trace_run.sh`, `signals-trace1.log:2341`) называет отправителя:
  ```
  07:48:43 sig=9 sender_pid=692675 sender_comm=python3 -> target_pid=670924 target_comm=python3 res=0
    sender_cmd[692675]: …/.venv/bin/python3 -m app.restart_guard --pid 670924 --start-ticks 439315480 --progress-fd 13 --ready-fd 18 --post-cleanup-budget 5.0  ppid=670924
  ```
  670924 — это pytest, он же родитель помощника. Место смерти плавает (здесь `test_lifecycle_quarantine_499`,
  в базовом — `test_logs_sync`) — что и ожидается от «5 с после какого-то teardown», а не от дефекта теста.
- Шпион взвода (`armspy.py`, `armspy.tsv`): `target == self` взводят 5 тестов `test_hot_apply.py::test_t3_*`;
  дальше по алфавиту ещё 7 в `test_seamless_restart.py` и 1 в `test_system_restart.py` (их поймал новый
  предохранитель conftest в `full-fix1.log`).
- Минимальное воспроизведение на исходном коде: `pytest tests/test_hot_apply.py tests/test_logs_sync.py tests/test_manager.py`
  → `EXIT=137` через 12.5 с (`repro-before.log`); с фиксом та же команда доходит до сводки
  `1 failed, 222 passed`, EXIT=1 (`repro-after.log`; красный — посторонний, см. ниже). Без третьего файла
  процесс НЕ умирал: pytest успевал закончиться раньше 5 с.

**Исправление (только тесты).**
- `tests/conftest.py`: autouse `_forbid_restart_guard_on_test_runner` — `restart_guard.arm_guard(target_pid=os.getpid())`
  падает `AssertionError`. Тихая смерть всего прогона превращается в красный тест с именем нужной заглушки.
  Тесты, взводящие настоящего помощника на дочерний процесс (`test_restart_generation_liveness.py`), не затронуты.
- Общая фикстура `no_real_exit_guard`, подключена `pytestmark` в трёх файлах пути рестарта.
- Мутация: исходный `test_hot_apply.py` при новом conftest → ровно 5 `test_t3_*` красные
  (`mutation-guard.log`: `5 failed, 16 passed`).

## Причина 2. Зависание на ~85–88 % (набор V-610 из 23/24 файлов) — Playwright ждёт чужой цикл

**Механизм.** `test_tg_bridge.py::TestLimitsCommand` (`test_limits_uses_important_file_delivery_path`,
`test_limits_sends_explicit_error_when_image_delivery_fails`) зовёт `tb.handle_limits`, тот рендерит
настоящую карточку `/limits` — поднимает НАСТОЯЩИЙ Chromium и оставляет его в модульном синглтоне
`app.limits_card._renderer_browser`, привязанном к циклу событий этого теста. Позже `tests/test_api.py::client`
выходит из `TestClient(app)`; lifespan зовёт `_shutdown_runtime` → `limits_card.shutdown_renderer()` →
`browser.close()` на новом цикле. Ответ Playwright уходит в соединение старого, мёртвого цикла — future
не разрешается никогда, teardown ждёт вечно. Путь рендера этот случай знал (`_release_renderer_from_previous_loop`),
путь shutdown — нет.

**Доказательства.**
- Набор V-610 (`v610-files.txt`) с первым фиксом — старый симптом:
  `test_api.py::TestDashboard::test_root_returns_html PASSED [ 88%]`, затем faulthandler
  `Timeout (0:03:00)!`, в конце `EXIT=124 elapsed=1500s` (`v610set-fix.log`). Главный поток —
  `starlette/testclient.py:692 wait_shutdown` ← `tests/test_api.py:41 client`.
- Плагин `hangdump.py` распечатал await-цепочку работающего lifespan (`hangdump.txt`):
  `app/main.py:467 lifespan → app/main.py:364 _shutdown_runtime → app/limits_card.py:97 shutdown_renderer
  → :62 _close_renderer → :47 _close_renderer_resources → playwright/_impl/_browser.py:241 close
  → _connection.py:123 _inner_send → asyncio.wait`.
- Шпион `render_limits_card` в том же плагине — кто поднимает браузер:
  `RENDER_LIMITS_CARD by tests/test_tg_bridge.py::TestLimitsCommand::test_limits_uses_important_file_delivery_path`
  → `browser=<Browser … chromium-1223 … version=148.0.7778.96>`.
- Пара `test_session.py` + `test_api::…test_root_returns_html` сама по себе не виснет (`pair.log`, 246 passed) —
  нужен браузер из `test_tg_bridge`.

**Исправление (app).** `app/limits_card.py::shutdown_renderer`: если `_renderer_loop` — не текущий
работающий цикл, ресурсы отпускаются через `_release_renderer_from_previous_loop` без await. В проде цикл
один, эта ветка не срабатывает — поведение не меняется. Регрессионный тест
`tests/test_limits_card.py::test_shutdown_does_not_await_browser_of_another_loop` (браузер, чей `close()`
не завершается никогда): без фикса краснеет `TimeoutError` (проверено откатом диффа `app/limits_card.py`),
с фиксом — весь файл 17 passed.
Тот же набор V-610 с обоими фиксами: `1 failed, 1184 passed in 112.44s`, EXIT=1 (`v610set-fix2.log`)
вместо зависания на 25+ минут.

## Проверки

| Прогон | Итог | Файл |
|---|---|---|
| полный, исходный код | EXIT=137 на 38 %, сводки нет | full-base.log |
| полный, исходный + bpftrace | EXIT=137 на 36 %, отправитель — app.restart_guard | full-trace1.log, signals-trace1.log |
| набор V-610, только фикс 1 | зависание, EXIT=124 через 1500 с | v610set-fix.log |
| набор V-610, оба фикса | 1 failed, 1184 passed, 112 с | v610set-fix2.log |
| полный, оба фикса | 115 failed, 3877 passed, 51 skipped, 12:02 | full-final.log |
| узкие: hot_apply, seamless_restart, system_restart, restart_generation_liveness, logs_sync, manager | 257 passed, 1 failed (logs_sync, ниже) | — |
| test_limits_card.py | 17 passed | — |

После полного прогона `git status` без изменений трекнутых файлов: прежняя запись в TODO о том, что
прогон меняет `.orchestra/tasks/356/usage-bar-*.png`, не воспроизвелась.

## Известные красные, НЕ связанные с задачей (НЕ починены)

Каждый файл с красными из `full-final.log` перезапущен отдельным процессом pytest, только его красные
узлы, дважды: в чистом окружении ssh (`isolated-ssh.txt`) и в окружении платформы (`isolated-platform-env.txt`).

**101 — красные поодиночке в обоих окружениях** (от порядка и от V-624 не зависят):
- браузерные/фронт: test_frontend (31), test_usage_analytics_frontend (14), test_t344_quota_lines_browser (12),
  test_grok_usage_frontend (11), test_usage_history_frontend (11), test_connection_recovery (7),
  test_model_catalog_frontend, test_quota_headroom_447, test_send_file_open_button, test_system_chat_entry (по 1).
  Типовые ошибки `ReferenceError: T is not defined` (24) и
  `Cannot access '_analyticsPeriods' before initialization` (13) — это JS.
- test_mcp_codex_review (5), test_audit0901_sysquota::test_lane_label_prints_the_threshold_that_actually_gates_it,
  test_backend_codex::test_installed_codex_history_version_matches_pin, test_backend_routing::test_opus5_registry_and_aliases,
  test_initial_deliveries::test_t1_http_status_lookup_returns_the_same_committed_resource,
  test_logs_sync::TestRoute::test_chat_snapshot_is_never_served_from_http_cache (404 вместо 200),
  test_tailwind_css::test_committed_css_matches_current_sources (уже в TODO).

**13 — зависят от окружения**: красные без `DASHBOARD_*`/`ORCHESTRA_*` в окружении (ssh), зелёные в
окружении платформы: test_work_review_jobs (5), test_message_delivery_receipts_380 (3),
test_work_acceptance (1), test_message_provenance_review_433 (1), test_codex_writer_conflict_536 (1),
test_manager::TestIdentityRefreshOnRename::test_rebuilds_config_and_defers_restart_to_turn_boundary (1),
test_mcp_codex_review::…resume_command_passes_usage_arguments (1). Типовой симптом `assert 403 == 202`.
На исходном коде (фикс откачен) в окружении платформы тот же небраузерный поднабор даёт то же
`10 failed, 13 passed` (`head-nonbrowser.txt`) — V-624 их не добавил.

**1 — зависит от порядка**: `test_i18n_dashboard.py::test_dictionary_reaches_marked_attributes` красный
в `full-final`, зелёный отдельно и в `full-fix1`.

## Ограничения и follow-up
- `TestLimitsCommand` по-прежнему поднимает настоящий Chromium в юнит-тесте без маркера `browser`;
  после фикса teardown не виснет, но процесс Chromium живёт до конца pytest → TODO.md.
- Причину зависимости 13 тестов от переменных окружения запускающего не разбирал (вне задачи).
- Диагностические плагины (`armspy.py`, `hangdump.py`) и скрипты (`run_full.sh`, `trace_run.sh`, `isolate.sh`)
  оставлены здесь для воспроизведения; в тестовый набор не входят.

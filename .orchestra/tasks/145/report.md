# #145 — 16 браузерных проверок не исполнялись при живом auth

## Цифра, подтверждённая своей командой

`pytest tests/test_frontend.py -q -p no:randomly -rs` на этой машине ДО правки:

```
....sssss..s...sss..s.ssssss                                             [100%]
SKIPPED [1] tests/test_frontend.py:124: на http://localhost:8888 нет #agent-list — вероятно включён auth …
SKIPPED [1] tests/test_frontend.py:128: …
SKIPPED [1] tests/test_frontend.py:133: …
SKIPPED [1] tests/test_frontend.py:139: …
SKIPPED [1] tests/test_frontend.py:145: …
SKIPPED [1] tests/test_frontend.py:361: …
SKIPPED [1] tests/test_frontend.py:626: …
SKIPPED [1] tests/test_frontend.py:635: …
SKIPPED [7] tests/test_frontend.py:83: на http://localhost:8888 нет #agent-list — вероятно включён auth …
SKIPPED [1] tests/test_frontend.py:801: http://localhost:8888/api/tm/tasks/112 ответил HTTP 401 (нужен стенд без auth с этой задачей)
13 passed, 16 skipped in 13.34s
```

**16 из 29** — то есть 55% файла, а не 32%: цифра аудита (16 из 50) считала долю от всех
браузерных тестов проекта, здесь же знаменатель — сам файл. Пропускались (все 16 поимённо):

`test_dashboard_loads`, `test_sidebar_agents_visible`, `test_chat_input_exists`,
`test_send_button_exists`, `test_usage_bar_visible`, `test_header_has_orch_tabs`,
`test_left_panel_has_tabs`, `test_agent_info_panel_exists`, `test_no_js_errors`,
`test_task_card_uses_real_long_description_and_shared_expandable_body`,
`test_codex_successful_mcp_startup_status_is_hidden`,
`test_native_codex_compact_renders_one_result_badge`,
`test_codex_web_search_renders_queries_without_transport_json`,
`test_codex_spawn_worker_renders_task_model_and_completion`,
`test_codex_file_change_renders_structured_kind`, `test_codex_view_image_loads_eagerly`.

## Решение: логиниться, а не поднимать стенд

Выбран логин кредами из окружения. Второй вариант — свой сервер без auth — тянет за собой
БД: `app.db.DB_PATH` вычисляется на импорте модуля, поэтому поднятый в общем прогоне
инстанс работал бы по БОЕВОЙ базе (это уже записано в докстринге фикстуры). Пришлось бы
городить отдельную базу, свой порт и lifespan — ради того, чтобы обойти форму из двух полей.
Логин же добавляет 6 строк и заодно проверяет реальный путь юзера.

Пароля в коде нет: `_ENV_DASHBOARD_AUTH` — снимок `os.environ` на импорте модуля,
`dotenv_values()` (не `load_dotenv`, чтобы не мутировать окружение) — запасной источник для
ручного прогона без systemd.

**Грабля, стоившая отдельного прогона.** Первая версия читала `os.environ` внутри теста и
всё равно скипалась: автоюзная фикстура `_hermetic_dashboard_env` (`tests/conftest.py:44`)
НАМЕРЕННО стирает `DASHBOARD_*` и глушит `load_dotenv`, чтобы внутрипроцессные тесты не
подцепили auth хозяина машины. Снимок на импорте снимается ДО фикстур, поэтому обе цели
уживаются: in-process тесты по-прежнему герметичны, браузерные логинятся на внешний сервер.

Тест задачи-карточки чинился отдельно: он тянул задачу `112` в scope `/mnt/data/Projects/…`
— путь ноутбука, на этой машине такой задачи нет ни в одном scope (проверено запросом с
cookie: 404 и для `/mnt/data/…`, и для `/home/kesha/orchestra`). Теперь берётся любая живая
задача с описанием длиннее 180 символов из scope этого репозитория (`_repo_scope()` считает
его от `git --git-common-dir`, потому что из worktree путь рабочей копии не равен scope).
Приоритет и исполнитель тест задаёт сам — у случайной задачи они любые.

## Стало

```
.............................                                            [100%]
29 passed in 20.24s
```

**16 скипов → 0; исполняются все 29.**

## Мутации: тесты действительно исполняются и различают исход

**A. Ломаем логин** (`_dashboard_credentials` возвращает неверный пароль) — красными
становятся ровно те 16:

```
8 failed, 13 passed, 8 errors in 197.19s
FAILED test_no_js_errors                                    ERROR test_dashboard_loads
FAILED test_task_card_uses_real_long_description_…          ERROR test_sidebar_agents_visible
FAILED test_codex_successful_mcp_startup_status_is_hidden   ERROR test_chat_input_exists
FAILED test_native_codex_compact_renders_one_result_badge   ERROR test_send_button_exists
FAILED test_codex_web_search_renders_queries_…              ERROR test_usage_bar_visible
FAILED test_codex_spawn_worker_renders_task_model_…         ERROR test_header_has_orch_tabs
FAILED test_codex_file_change_renders_structured_kind       ERROR test_left_panel_has_tabs
FAILED test_codex_view_image_loads_eagerly                  ERROR test_agent_info_panel_exists
```

Это доказывает, что скипы не превратились в пассы «мимо тела»: без успешного логина ни один
из 16 пройти не может.

**B. Ломаем продуктовый код**, который читает тест карточки (`_TASK_PRIORITY_META[1]`,
иконка `🟠` → `🟣` в `app/static/js/app.js`):
`AssertionError: Locator expected to contain text '🟠 High' … unexpected value "… Priority: 🟣 High …"`.

**C. Ломаем вход живой страницы** (второй `compact done` в
`test_native_codex_compact_renders_one_result_badge`):
`AssertionError: Locator expected to have count '1' - unexpected value "2"` — тест реально
считает то, что нарисовал ЖИВОЙ `app.js` сервера, а не заглушку.

Все три мутации откачены обратной точечной заменой, `grep -c MUTANT` = 0 в обоих файлах.

## Что попутно видно, но не чинил (вне объёма)

`expect(chat).to_contain_text("🟠 High")` — подстрочное сравнение: мутация `High` → `Highest`
его НЕ роняет (прогон был зелёным), поймала только замена иконки. Ассерт стоит сделать
точным, но это правка чужой проверки, не моей задачи.

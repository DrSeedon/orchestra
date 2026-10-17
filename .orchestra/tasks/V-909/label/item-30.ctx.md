# Context for item-30

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/docs/tasks/145/report.md b/docs/tasks/145/report.md
new file mode 100644
index 000000000..58cb6ff9c
--- /dev/null
+++ b/docs/tasks/145/report.md
@@ -0,0 +1,104 @@
+# #145 — 16 браузерных проверок не исполнялись при живом auth
+
+## Цифра, подтверждённая своей командой
+
+`pytest tests/test_frontend.py -q -p no:randomly -rs` на этой машине ДО правки:
+
+```
+....sssss..s...sss..s.ssssss                                             [100%]
+SKIPPED [1] tests/test_frontend.py:124: на http://localhost:8888 нет #agent-list — вероятно включён auth …
+SKIPPED [1] tests/test_frontend.py:128: …
+SKIPPED [1] tests/test_frontend.py:133: …
+SKIPPED [1] tests/test_frontend.py:139: …
+SKIPPED [1] tests/test_frontend.py:145: …
+SKIPPED [1] tests/test_frontend.py:361: …
+SKIPPED [1] tests/test_frontend.py:626: …
+SKIPPED [1] tests/test_frontend.py:635: …
+SKIPPED [7] tests/test_frontend.py:83: на http://localhost:8888 нет #agent-list — вероятно включён auth …
+SKIPPED [1] tests/test_frontend.py:801: http://localhost:8888/api/tm/tasks/112 ответил HTTP 401 (нужен стенд без auth с этой задачей)
+13 passed, 16 skipped in 13.34s
+```
+
+**16 из 29** — то есть 55% файла, а не 32%: цифра аудита (16 из 50) считала долю от всех
+браузерных тестов проекта, здесь же знаменатель — сам файл. Пропускались (все 16 поимённо):
+
+`test_dashboard_loads`, `test_sidebar_agents_visible`, `test_chat_input_exists`,
+`test_send_button_exists`, `test_usage_bar_visible`, `test_header_has_orch_tabs`,
+`test_left_panel_has_tabs`, `test_agent_info_panel_exists`, `test_no_js_errors`,
+`test_task_card_uses_real_long_description_and_shared_expandable_body`,
+`test_codex_successful_mcp_startup_status_is_hidden`,
+`test_native_codex_compact_renders_one_result_badge`,
+`test_codex_web_search_renders_queries_without_transport_json`,
+`test_codex_spawn_worker_renders_task_model_and_completion`,
+`test_codex_file_change_renders_structured_kind`, `test_codex_view_image_loads_eagerly`.
+
+## Решение: логиниться, а не поднимать стенд
+
+Выбран логин кредами из окружения. Второй вариант — свой сервер без auth — тянет за собой
+БД: `app.db.DB_PATH` вычисляется на импорте модуля, поэтому поднятый в общем прогоне
+инстанс работал бы по БОЕВОЙ базе (это уже записано в докстринге фикстуры). Пришлось бы
+городить отдельную базу, свой порт и lifespan — ради того, чтобы обойти форму из двух полей.
+Логин же добавляет 6 строк и заодно проверяет реальный путь юзера.
+
+Пароля в коде нет: `_ENV_DASHBOARD_AUTH` — снимок `os.environ` на импорте модуля,
+`dotenv_values()` (не `load_dotenv`, чтобы не мутировать окружение) — запасной источник для
+ручного прогона без systemd.
+
+**Грабля, стоившая отдельного прогона.** Первая версия читала `os.environ` внутри теста и
+всё равно скипалась: автоюзная фикстура `_hermetic_dashboard_env` (`tests/conftest.py:44`)
+НАМЕРЕННО стирает `DASHBOARD_*` и глушит `load_dotenv`, чтобы внутрипроцессные тесты не
+подцепили auth хозяина машины. Снимок на импорте снимается ДО фикстур, поэтому обе цели
+уживаются: in-process тесты по-прежнему герметичны, браузерные логинятся на внешний сервер.
+
+Тест задачи-карточки чинился отдельно: он тянул задачу `112` в scope `/mnt/data/Projects/…`
+— путь ноутбука, на этой машине такой задачи нет ни в одном scope (проверено запросом с
+cookie: 404 и для `/mnt/data/…`, и для `/home/kesha/orchestra`). Теперь берётся любая живая
+задача с описанием длиннее 180 символов из scope этого репозитория (`_repo_scope()` считает
+его от `git --git-common-dir`, потому что из worktree путь рабочей копии не равен scope).
+Приоритет и исполнитель тест задаёт сам — у случайной задачи они любые.
+
+## Стало
+
+```
+.............................                                            [100%]
+29 passed in 20.24s
+```
+
+**16 скипов → 0; исполняются все 29.**
+
+## Мутации: тесты действительно исполняются и различают исход
+
+**A. Ломаем логин** (`_dashboard_credentials` возвращает неверный пароль) — красными
+становятся ровно те 16:
+
+```
+8 failed, 13 passed, 8 errors in 197.19s
+FAILED test_no_js_errors                                    ERROR test_dashboard_loads
+FAILED test_task_card_uses_real_long_description_…          ERROR test_sidebar_agents_visible
+FAILED test_codex_successful_mcp_startup_status_is_hidden   ERROR test_chat_input_exists
+FAILED test_native_codex_compact_renders_one_result_badge   ERROR test_send_button_exists
+FAILED test_codex_web_search_renders_queries_…              ERROR test_usage_bar_visible
+FAILED test_codex_spawn_worker_renders_task_model_…         ERROR test_header_has_orch_tabs
+FAILED test_codex_file_change_renders_structured_kind       ERROR test_left_panel_has_tabs
+FAILED test_codex_view_image_loads_eagerly                  ERROR test_agent_info_panel_exists
+```
+
+Это доказывает, что скипы не превратились в пассы «мимо тела»: без успешного логина ни один
+из 16 пройти не может.
+
+**B. Ломаем продуктовый код**, который читает тест карточки (`_TASK_PRIORITY_META[1]`,
+иконка `🟠` → `🟣` в `app/static/js/app.js`):
+`AssertionError: Locator expected to contain text '🟠 High' … unexpected value "… Priority: 🟣 High …"`.
+
+**C. Ломаем вход живой страницы** (второй `compact done` в
+`test_native_codex_compact_renders_one_result_badge`):
+`AssertionError: Locator expected to have count '1' - unexpected value "2"` — тест реально
+считает то, что нарисовал ЖИВОЙ `app.js` сервера, а не заглушку.
+
+Все три мутации откачены обратной точечной заменой, `grep -c MUTANT` = 0 в обоих файлах.
+
+## Что попутно видно, но не чинил (вне объёма)
+
+`expect(chat).to_contain_text("🟠 High")` — подстрочное сравнение: мутация `High` → `Highest`
+его НЕ роняет (прогон был зелёным), поймала только замена иконки. Ассерт стоит сделать
+точным, но это правка чужой проверки, не моей задачи.
diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index b62d8295d..de8f458f7 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -45,20 +45,22 @@
 - Проверяешь что-то про ЦВЕТ агента — бери сообщение ОТ ВОРКЕРА: у оркестраторов `color=""` (`app/manager.py:621`), их подпись серая всегда, и правильный фикс выглядит как «не работает» (потерял на этом прогон в #68). Палитра к тому же переиспользуется — `#818cf8` сейчас у пятерых живых агентов, так что «цвета совпали» само по себе ничего не доказывает: сверяй с полем `color` из `/api/sessions`.
 - Гонку «данные пришли позже, чем отрисовали» воспроизводить не задержкой, а ВЫРЕЗАНИЕМ поля из ответа на первые N секунд (`route.fetch()` → `s.pop("color")` → `fulfill`): страница живёт нормально, окно управляемое, и `time.sleep` в обработчике route не блокирует остальные перехваты. НО в sync-API он блокирует мои же `page.keyboard.type`/`evaluate` — они ждут того же питоновского потока. Сценарий «юзер печатает, ПОКА летит запрос» так не собрать: ввод приезжает после fulfill, и получается обратный порядок (#94, полчаса на ложные FAIL). Проверять состояние ДО и ПОСЛЕ ответа отдельными шагами, а не пытаться попасть в окно.
 - Добавил в шаблон/JS НОВЫЙ класс Tailwind → `bash scripts/build-tailwind.sh` (собранный `app/static/css/vendor/tailwind.css` коммитится). Play-CDN больше нет с #64: класса нет в сборке — стиля нет вообще, а элемент при этом отрисуется. Страж — `tests/test_tailwind_css.py`.
 - Любой временный элемент интерфейса, который снимается «успехом», надо привязывать к КОНКРЕТНОМУ пути/сущности: круг опроса раз в 3 с гонит десяток успешных мелких запросов и стирает сообщение за миллисекунды. В #70 баннер об оборванном `/api/sessions` не доживал до конца 12-секундного окна — снимался ответом соседнего эндпоинта.
 - Режешь размер ответа — сперва пережми ЖИВОЙ ответ вариантами (выброс поля, потолок content, срез строк) и напечатай вклад каждого куска: в #72 это за один прогон показало, что 114 из 123 КБ — тела сообщений, и сэкономило день на правках полей. Локальный `gzip -6` НЕ равен проводу: nginx жмёт слабее, коэффициент ×1.18 (123.1 локально против 145.5 по проводу на одном ответе) — приводить к проводу или мерить через домен.
 - Порцию сетевого ответа ограничивать И строками, И БАЙТАМИ: 25 строк лога в разных чатах дают от 5.2 до 46.6 КБ, размер сообщения гуляет на три порядка. И прогонять оценку по ВСЕМ сессиям живой БД, а не по пяти знакомым: хвост (`seo-cro` 1261.9 КБ на страницу) виден только в полном прогоне.
 - Убираешь предзагрузку/кеш, который наполнял зеркало, — найди ВСЕХ, кто на него молча опирался: строки из `_fetchHistory` в зеркало не писались, потому что свежий кусок привозила холодная синхронизация. Признак дыры: данные старше watermark, которые инкремент не принесёт никогда.
 - Мутация НЕ покраснела ≠ код верен: у функции с fallback'ом (основной признак + запасной) ломаешь первую ветку, а тесты держатся на второй и остаются зелёными. В #153 так прошла подмена `"type=local_bash" in content` → `if False`, потому что все фикстуры ловились запасной проверкой по форме id. Значит на КАЖДЫЙ признак нужен случай, где остальные признаки помочь не могут; иначе мутация проверяет не то, что кажется.
 - Таблица БД и `logs` расходятся по заполненности одного и того же поля: в `subagents` `task_type` был непустым у всех 3284 строк, а в `logs` у части `subagent_end` он пуст. Классификатор, проверенный по таблице, на логах молча промахивается — прогоняй его по РЕАЛЬНЫМ строкам того источника, из которого он будет читать.
 - Считая «сколько строк попадает в окно», бери окно ИЗ КОДА (`_calendar_since(7)` = `-6 days`, сегодня включительно), а не пиши `-7 days` от руки: получишь расхождение 1612 против 1542 и полчаса на поиск несуществующего бага в своей же правке.
 - Мутация покраснела — прочитай, ПОЧЕМУ. В #154 подмена `AbortSignal.any` на `opts.signal || timeout` роняла тест через 32 с сообщением «Execution context was destroyed» вместо «таймаут съеден»: тест ждал вечно висящий запрос. Красный по негодной причине бесполезен в бою — на зависание нужен СВОЙ потолок (`Promise.race` с маркером `HUNG`), тогда мутация печатает диагноз, а не смерть контекста.
 - Красный тест приколочен к ДОСЛОВНОМУ argv/тексту/имени вызова → сперва `git log -S"<строка>"` и вопрос «поведение изменилось или только форма?»; если форма — переписать тест на ПОВЕДЕНЧЕСКИЙ, не подгонять строку. Подгонка дешевле на один ход и оставляет тест таким же хрупким до следующего рефакторинга. Замер #154: тест требовал `AbortSignal.timeout(30000)` внутри `_sparkFetch`, а #58 перевёл бюджет в параметр `api(url, {timeoutMs})` — поведение сохранилось, красным был только матчер. *(на триаже у оркестратора, метит в CLAUDE.md, парой к правилу про мутацию с fallback)*
 - `test_tg_bridge.py::TestTgSendSafe::test_serializes_concurrent_group_sends` — ИЗВЕСТНЫЙ флак по wall-clock (`docs/tasks/17/report.md`). Упал одиночно при LA > 5 → повторить прогон 3 раза и посмотреть туда, а не искать причину в своей правке. `test_frontend.py::test_chat_drop_...` из этого списка ВЫЧЕРКНУТ: починен в #107 — ждал 100 мс, теперь ждёт условие «каждый файл дал путь ИЛИ назван в ошибке», 10/10 зелёных при LA до 6.8.
 - Чинишь флак «не дождались» — условие писать как «каждый ожидаемый элемент дал СВОЙ наблюдаемый исход» (путь в поле ИЛИ имя в строке ошибки), а не «внутренняя очередь пуста»: очередь пуста и ДО старта, и между двумя последовательными аплоадами. Дедлайн оставлять, но только как страховку от зависания. Проверять двумя мутациями: сломать сборку данных (тест обязан упасть сразу) И убрать поздний элемент (тест обязан упасть по дедлайну) — вторая доказывает, что ожидание не проглатывает потерю. Доказывать «красное не моё» надо ЧЕРЕДУЯ прогоны base/main в двух скретч-worktree на явных SHA (`git worktree add --detach /tmp/wt-base <sha>`, гонять венвом `/home/kesha/orchestra/.venv/bin/python -m pytest`): серия за серией меряет ещё и разную нагрузку машины, а чередование даёт обеим одну. #105: база 3 красных из 9, main 1 из 9, форма падения одна — «из пачки файлов потерян путь позднего аплоада».
 - Меряешь «худший ответ» по журналу — иди по ВСЕЙ истории сессии, а не по последней сотне строк: жирные строки лежат где угодно, юзер доходит до них кнопкой «ещё». На снимке 04.08 блоб seo-cro на 651 КБ уже выпал из последних 100, и «до» выглядело бы как безобидные 8.8 КБ.
 - Про сжатие: base64 не сжимается вообще. Бюджет ответа в СЫРЫХ байтах для такого содержимого почти равен размеру по проводу — 24 КБ сырых дали 19 КБ gzip. Если нужен потолок по проводу, бюджет ставить примерно равным ему, а не рассчитывать на ×4.
 - Время на этом VPS мерить БРАУЗЕРНЫМИ часами, а не хостовым секундомером: при LA 8 хостовой дал ветке 6.25 с против 4.30 у main — шум больше эффекта и с обратным знаком. Рабочий приём: `page.add_init_script` с обёрткой над `fetch` (start/end по `performance.now()`) + опрос раз в 30 мс для отметки первого экрана, 3 прогона и медиана. Отметку перед чтением ДОЖИДАТЬСЯ (`wait_for_function`), иначе тик не успевает и замер молча теряется. `MutationObserver.observe(document.documentElement)` в init-скрипте падает — DOM ещё не создан, поэтому опрос.
 - Обрезанный `tool_result` рисуется СВОИМ узлом-плашкой (`🖼 [Image result]` + маркер), а загруженный целиком вливается в карточку инструмента и своего узла с `data-chat-log-id` НЕ создаёт. Зонд, который ищет узел по id после «загрузить целиком», вернёт `None` и это выглядит как провал — картинки считать по всему `#chat` (`img`, `naturalWidth`), а не по узлу.
 - `light-dark(<светлое>, <тёмное>)` — ПЕРВЫЙ аргумент для СВЕТЛОЙ схемы (MDN: «used when color-scheme is light or if no preference is set»). Проверяется за один прогон: `browser.new_page(color_scheme="light"|"dark")` + `getComputedStyle(...).backgroundColor`. Перепутанный порядок не падает и не подсвечивается — артефакт просто рисуется наоборот (#124).
 - Любой круг `JSON.parse` → `JSON.stringify` теряет целые больше 2^53 (`…147` → `…200`) и нормализует литералы (`1.0` → `1`, `A` → `A`). Если задача — ПОКАЗАТЬ файл, форматируй ТЕКСТ (`_prettyJsonText` в `utils.js`: сканер с учётом строк и экранирования), а `JSON.parse` оставляй только проверкой валидности. Замер #136: на 171 json репозитория раскладка не изменилась ни в одном, разошлись 46 — и все ровно на литерале числа.
+- Браузерные тесты в `tests/test_frontend.py` бьют по ЖИВОМУ :8888 и логинятся сами: креды снимаются в `_ENV_DASHBOARD_AUTH` НА ИМПОРТЕ модуля, потому что автоюзная `_hermetic_dashboard_env` (`tests/conftest.py:44`) стирает `DASHBOARD_*` из `os.environ` и глушит `load_dotenv` ради герметичности внутрипроцессных тестов. Читать креды внутри теста бесполезно — увидишь пустоту и решишь, что их нет в окружении (#145, потерянный прогон). Запасной источник — `dotenv_values()`, он не мутирует окружение.
+- Тест «не исполняется ли он вхолостую» проверяется мутацией НЕ его ассерта, а его предусловия: сломал логин → 16 тестов из скипов стали 8 failed + 8 errors. Мутация ассерта доказывает только, что строка сравнения жива.
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 7b3ec6401..e49b6103c 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -1,28 +1,29 @@
 """Playwright smoke tests for Orchestra dashboard.
 
 Requires: Orchestra running on localhost:8888 (no auth).
 Run: pytest tests/test_frontend.py -v
 """
 
 import os
 import re
+import subprocess
 from pathlib import Path
 
 import pytest
 from playwright.sync_api import Browser, Page, expect, sync_playwright
 
 BASE = os.environ.get("ORCHESTRA_TEST_BASE", "http://localhost:8888")
 HTML_ARTIFACT_CSP = (
     "sandbox allow-scripts; "
     "default-src 'unsafe-inline' 'unsafe-eval' data: blob:; "
     "connect-src 'none'"
 )
 
 
 def test_html_preview_uses_protected_raw_url_and_opaque_origin_sandbox():
     source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
     html_branch = source.split("if (/\\.html?$/i.test(path)) {", 1)[1].split(
         "return;", 1,
     )[0]
     match = re.search(r'<iframe[^`]+sandbox="([^"]+)"', html_branch)
 
@@ -42,102 +43,140 @@ async def test_raw_html_response_has_sandbox_csp(tmp_path, monkeypatch, suffix):
     monkeypatch.setattr(system, "_ALLOWED_ROOTS", [str(tmp_path)])
 
     response = await system.get_file_raw(str(target))
 
     assert response.headers["content-security-policy"] == HTML_ARTIFACT_CSP
 
 
 @pytest.mark.asyncio
 async def test_raw_non_html_response_has_no_artifact_csp(tmp_path, monkeypatch):
     from app.routes import system
 
     target = tmp_path / "notes.txt"
     target.write_text("safe text")
     monkeypatch.setattr(system, "_ALLOWED_ROOTS", [str(tmp_path)])
 
     response = await system.get_file_raw(str(target))
 
     assert "content-security-policy" not in response.headers
 
 
+# Снимок ДО автоюзной `_hermetic_dashboard_env` (tests/conftest.py:44): она стирает
+# DASHBOARD_* из os.environ, чтобы ВНУТРИПРОЦЕССНЫЕ тесты не подцепили auth хозяина
+# машины. Здесь задача обратная — залогиниться на ВНЕШНЕМ сервере, поэтому креды
+# читаем на импорте модуля, до фикстур. В коде их нет, только имена переменных.
+_ENV_DASHBOARD_AUTH = (os.environ.get("DASHBOARD_USER"),
+                       os.environ.get("DASHBOARD_PASSWORD"))
+
+
+def _dashboard_credentials():
+    """Логин/пароль из окружения; ручной прогон без юнита — из `.env` рядом."""
+    user, password = _ENV_DASHBOARD_AUTH
+    if password:
+        return user, password
+    try:
+        from dotenv import dotenv_values   # не трогает os.environ, в отличие от load_dotenv
+    except ImportError:
+        return None, None
+    values = dotenv_values()
+    return values.get("DASHBOARD_USER"), values.get("DASHBOARD_PASSWORD")
+
+
 def _goto_dashboard_or_skip(page: Page):
-    """Открыть развёрнутый дашборд или пропустить тест, назвав причину.
+    """Открыть развёрнутый дашборд, при живом auth — залогиниться.
 
-    Эти проверки требуют РАЗВЁРНУТОГО дашборда без auth (см. докстринг модуля),
-    и до сих пор они об этом молчали: на CI по ``BASE`` нет никого → ERROR на
-    setup, у владельца там живой сервис с включённым auth → отдаётся страница
-    логина. Отсюда красный CI с 9 июня — со дня появления этих тестов.
+    Раньше включённый auth означал скип: на боевой машине он включён всегда,
+    и 16 браузерных проверок печатались зелёными, ничего не проверив (#145).
+    Логинимся кредами из окружения; их нет — скип с этой причиной, а не с общей.
 
     Поднять инстанс прямо здесь нельзя: ``app.db.DB_PATH`` вычисляется на
     импорте модуля, поэтому в общем прогоне такой сервер работал бы по БОЕВОЙ
     базе. Адрес стенда задаётся через ``ORCHESTRA_TEST_BASE``.
     """
     try:
         resp = page.goto(BASE, wait_until="domcontentloaded")
     except Exception as exc:
         pytest.skip(f"дашборд на {BASE} недоступен ({type(exc).__name__}); "
-                    "укажи ORCHESTRA_TEST_BASE на развёрнутый стенд без auth")
+                    "укажи ORCHESTRA_TEST_BASE на развёрнутый стенд")
     if resp is None or resp.status != 200:
         status = "нет ответа" if resp is None else f"HTTP {resp.status}"
         pytest.skip(f"дашборд на {BASE} ответил {status}")
     if page.locator("#agent-list").count() == 0:
-        pytest.skip(f"на {BASE} нет #agent-list — вероятно включён auth и отдаётся "
-                    "страница логина; этим тестам нужен стенд без auth")
+        if page.locator('input[name="password"]').count() == 0:
+            pytest.skip(f"на {BASE} нет ни #agent-list, ни формы логина — "
+                        "по этому адресу отвечает не дашборд")
+        user, password = _dashboard_credentials()
+        if not user or not password:
+            pytest.skip(f"на {BASE} включён auth, а DASHBOARD_USER/DASHBOARD_PASSWORD "
+                        "нет в окружении — экспортируй их или положи рядом .env")
+        page.fill('input[name="username"]', user)
+        page.fill('input[name="password"]', password)
+        page.click('button[type="submit"]')
+        page.wait_for_selector("#agent-list", timeout=20000)
     return resp
 
 
 @pytest.fixture(scope="module")
 def dashboard_browser():
     with sync_playwright() as playwright:
         try:
             browser = playwright.chromium.launch()
         except Exception as exc:
             # `uv sync` ставит пакет playwright, но НЕ бинарники браузеров:
             # без явного `playwright install` фикстура падала с ERROR, а не
             # говорила, чего не хватает.
             pytest.skip(f"chromium недоступен ({type(exc).__name__}); "
                         "поставь его: playwright install --with-deps chromium")
         yield browser
         browser.close()
 
 
 @pytest.fixture(scope="module")
 def dashboard_page(dashboard_browser: Browser):
     """Требует РАЗВЁРНУТЫЙ дашборд без auth (см. докстринг модуля).
 
     Без развёртывания эти проверки невыполнимы, и до сих пор они этого не
     говорили: на CI по ``BASE`` никого нет → 8 ERROR на setup, у владельца там
     живой сервис с включённым auth → отдаётся страница логина и `#agent-list`
     не находится. Итог — красный CI с 9 июня и «сломанные» тесты, которые на
     деле просто не могли выполниться. Пропуск с внятной причиной честнее.
 
     Поднимать инстанс прямо здесь нельзя: ``app.db.DB_PATH`` вычисляется на
     импорте, поэтому в общем прогоне сервер работал бы по БОЕВОЙ базе.
     Задать адрес развёрнутого стенда — ``ORCHESTRA_TEST_BASE``.
     """
     page = dashboard_browser.new_page()
     _goto_dashboard_or_skip(page)
     expect(page.locator("#agent-list")).to_be_visible()
     yield page
     page.close()
 
 
+def _repo_scope():
+    """Scope сервера — путь РЕПОЗИТОРИЯ, а не рабочей копии: из worktree они разные."""
+    common = subprocess.run(
+        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
+        cwd=Path(__file__).parent, capture_output=True, text=True, check=True,
+    ).stdout.strip()
+    return str(Path(common).parent)
+
+
 def test_dashboard_loads(dashboard_page: Page):
     expect(dashboard_page).to_have_title("🎼 Orchestra")
 
 
 def test_sidebar_agents_visible(dashboard_page: Page):
     agent_list = dashboard_page.locator("#agent-list")
     expect(agent_list).to_be_visible()
 
 
 def test_chat_input_exists(dashboard_page: Page):
     chat_input = dashboard_page.locator("#chat-input")
     expect(chat_input).to_be_visible()
     expect(chat_input).to_be_enabled()
 
 
 def test_send_button_exists(dashboard_page: Page):
     send_btn = dashboard_page.locator("#send-btn")
     expect(send_btn).to_be_visible()
     expect(send_btn).to_have_text("Send")
 
@@ -768,59 +807,64 @@ def _open_tool_fixture_page(browser: Browser) -> Page:
             eventSource = null;
         }
         window.compactMode = false;
         document.querySelector('#chat').innerHTML = '';
     }""")
     return page
 
 
 def test_task_card_uses_real_long_description_and_shared_expandable_body(
     dashboard_browser: Browser,
 ):
     root = Path(__file__).parent.parent
     source = (root / "app/static/js/app.js").read_text()
     helper_code = (
         "const _TASK_PRIORITY_META"
         + source.split("const _TASK_PRIORITY_META", 1)[1].split(
             "// Central renderer", 1,
         )[0]
     )
     api_page = dashboard_browser.new_page()
-    # Тянет РЕАЛЬНУЮ задачу с развёрнутого сервера, да ещё по пути ноутбука.
-    # Держится на трёх внешних условиях сразу: сервис поднят, auth выключен,
-    # задача 112 существует именно в этом scope. Нет их — это не провал кода.
-    try:
-        response = api_page.request.get(
-            f"{BASE}/api/tm/tasks/112",
-            params={"scope": "/mnt/data/Projects/Python/orchestra"},
-        )
-    except Exception as exc:
-        api_page.close()
-        pytest.skip(f"API на {BASE} недоступен ({type(exc).__name__})")
-    if response.status != 200:
+    # Нужен РЕАЛЬНЫЙ длинный текст, а не выдуманный. Раньше тест держался на
+    # задаче 112 в scope ноутбука — на другой машине её нет никогда. Берём любую
+    # длинную из scope этого репозитория, залогинившись как обычный юзер.
+    _goto_dashboard_or_skip(api_page)   # заодно кладёт cookie сессии в контекст
+    scope = _repo_scope()
+    listing = api_page.request.get(f"{BASE}/api/tm/tasks", params={"scope": scope})
+    if listing.status != 200:
         api_page.close()
-        pytest.skip(f"{BASE}/api/tm/tasks/112 ответил HTTP {response.status} "
-                    "(нужен стенд без auth с этой задачей)")
-    task = response.json()
+        pytest.skip(f"{BASE}/api/tm/tasks?scope={scope} ответил HTTP {listing.status}")
+    task = None
+    for item in listing.json()["tasks"][:25]:
+        detail = api_page.request.get(f"{BASE}/api/tm/tasks/{item['par']}",
+                                      params={"scope": scope})
+        if detail.status == 200 and len(detail.json().get("description") or "") > 180:
+            task = detail.json()
+            break
     api_page.close()
+    if task is None:
+        pytest.skip(f"в scope {scope} нет задачи с описанием длиннее 180 символов — "
+                    "тесту нужен реальный длинный текст")
     assert len(task["description"]) > 180
-    task.update({"assignee": "frontend", "task_id": 987})
+    # Из сервера берём только длинное описание; остальные поля задаём сами —
+    # приоритет и исполнитель у случайной живой задачи любые
+    task.update({"assignee": "frontend", "task_id": 987, "priority": 1})
 
     page = dashboard_browser.new_page(viewport={"width": 1440, "height": 900})
     page.set_content(
         '<body style="background:#0a0e17;color:#e2e8f0">'
         '<style>#chat-card,#panel-card,#xss-card{width:420px}</style>'
         '<div id="chat-card"></div><div id="panel-card"></div><div id="xss-card"></div>'
         '</body>'
     )
     page.add_style_tag(path=str(root / "app/static/css/style.css"))
     page.add_script_tag(path=str(root / "app/static/css/vendor/marked.min.js"))
     page.add_script_tag(path=str(root / "app/static/css/vendor/purify.min.js"))
     page.add_script_tag(content="const CUR = '₽';\n" + helper_code)
     page.evaluate(
         """task => {
             document.querySelector('#chat-card').innerHTML = _taskCardBodyHtml(task);
             document.querySelector('#panel-card').innerHTML = _taskCardBodyHtml(task);
             document.querySelector('#xss-card').innerHTML = _taskCardBodyHtml({
                 description: '<img src=x onerror="window.taskXss=1"><script>window.taskXss=1</script>',
             });
         }""",


## Later history of the touched files on main (after this commit)

91 later commits touch these paths; the first 40 (oldest first):
e25ca71e4 2026-08-07 #150: #150: null в five_hour_pct/seven_day_pct — дыра в графике, а не ноль
ad423c58f 2026-08-11 #185: #185: add chat event timeline navigation
6c501b822 2026-08-11 #174: WIP #174: add native history canary and diagnose Claude collector
8b0735950 2026-08-12 #212: #212: restore truncated Read images from full log
21ead017a 2026-08-13 #245: #245: add dashboard voice input
ba10d0dcb 2026-08-13 #163: #163: keep usage controls visible on narrow desktops
d894fc6e4 2026-08-13 #259: #259: audit dashboard clarity and propose UX
173f2d863 2026-08-13 #260: #260: correlate parallel tool results by id
3c5fa59a2 2026-08-13 #260: #260: pair tool results without exact id and adopt late calls
74f2b6b6d 2026-08-13 #241: #241: highlight notify_user calls and make them navigable
244bcb093 2026-08-13 #268: уведомление браузера о зове оркестратора
85c8254d7 2026-08-13 #270: #270: дашборд показывает перезапуск Orchestra и возвращается сам
42dc9aa62 2026-08-14 #266: #266: make load-more append history without trimming new cards
ad6f5d69f 2026-08-14 #274: #274: три макета картинки /limits в HTML (фаза 1)
6e7fcc230 2026-08-14 #197: #197: pin orch tabs test to fixture, not live header
740d749a2 2026-08-14 #242, #278: #242: recount live-state tests — 70 DB_PATH sites in 56 files
4f0c87aa3 2026-08-14 #282: #282: wait for notify card and reconnect, not a 5s sleep
fc191b4fe 2026-08-16 #295: #295: hide silent turn marker in dashboard
e25a6b178 2026-08-16 #301: #301: visibility-aware dashboard polling
b739cec2a 2026-08-17 #307: WIP #307: add russian task tool labels and focused frontend tests
a497a12fa 2026-08-17 #312: #312: restore system chat dashboard helper seam
3c037bdb8 2026-08-18 #290: cross-runtime handoff + канареечный скип по продовому предикату (scratch/290, вердикт #328)
24d6308d4 2026-08-20 #197: #197: кеш последнего успешного ответа, джиттер ретраев, негативный кеш провайдера
5165bcc02 2026-08-21 чат открывается на последних сообщениях и не ждёт зеркало
fa3e993db 2026-08-23 Allow fresh model switches without handoff
1f0a526d3 2026-08-23 #225: group chat photo batches into compact galleries
e7d521de5 2026-08-24 fix: preserve generated images across chat switches
e26dcde85 2026-08-24 fix: switch Codex models in place
33660cfd5 2026-08-25 #397: add final answer timeline navigation
382bd22e8 2026-08-25 #364: freeze red oracle
589528d1a 2026-08-26 Improve Orchestra runtime stability and live status
bd3d4cbf0 2026-08-27 убрать два теста паузы ввода при рестарте: поведение отменено решением юзера 26.08
f77e06cee 2026-08-27 #403: render send_files batches in dashboard
937ea8486 2026-08-27 пометить тест голосового ввода как устаревший: контракт заменён в #365
ad76ba42e 2026-08-27 #411: freeze reliable restart oracles
a06fcc500 2026-08-27 #404: add mirror freshness regression oracles
07f97eeff 2026-08-27 Merge remote-tracking branch 'origin/main'
99fa70980 2026-08-27 #405: add upload size and progress oracles
735cf14e5 2026-08-28 чат берётся из сети, зеркало логов в IndexedDB удалено
16f85b462 2026-08-28 Restore one-shot previous chat history loading

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### e25ca71e4 #150: #150: null в five_hour_pct/seven_day_pct — дыра в графике, а не ноль

diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index de8f458f7..301bd1364 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -62,5 +62,6 @@
 - Обрезанный `tool_result` рисуется СВОИМ узлом-плашкой (`🖼 [Image result]` + маркер), а загруженный целиком вливается в карточку инструмента и своего узла с `data-chat-log-id` НЕ создаёт. Зонд, который ищет узел по id после «загрузить целиком», вернёт `None` и это выглядит как провал — картинки считать по всему `#chat` (`img`, `naturalWidth`), а не по узлу.
 - `light-dark(<светлое>, <тёмное>)` — ПЕРВЫЙ аргумент для СВЕТЛОЙ схемы (MDN: «used when color-scheme is light or if no preference is set»). Проверяется за один прогон: `browser.new_page(color_scheme="light"|"dark")` + `getComputedStyle(...).backgroundColor`. Перепутанный порядок не падает и не подсвечивается — артефакт просто рисуется наоборот (#124).
 - Любой круг `JSON.parse` → `JSON.stringify` теряет целые больше 2^53 (`…147` → `…200`) и нормализует литералы (`1.0` → `1`, `A` → `A`). Если задача — ПОКАЗАТЬ файл, форматируй ТЕКСТ (`_prettyJsonText` в `utils.js`: сканер с учётом строк и экранирования), а `JSON.parse` оставляй только проверкой валидности. Замер #136: на 171 json репозитория раскладка не изменилась ни в одном, разошлись 46 — и все ровно на литерале числа.
 - Браузерные тесты в `tests/test_frontend.py` бьют по ЖИВОМУ :8888 и логинятся сами: креды снимаются в `_ENV_DASHBOARD_AUTH` НА ИМПОРТЕ модуля, потому что автоюзная `_hermetic_dashboard_env` (`tests/conftest.py:44`) стирает `DASHBOARD_*` из `os.environ` и глушит `load_dotenv` ради герметичности внутрипроцессных тестов. Читать креды внутри теста бесполезно — увидишь пустоту и решишь, что их нет в окружении (#145, потерянный прогон). Запасной источник — `dotenv_values()`, он не мутирует окружение.
 - Тест «не исполняется ли он вхолостую» проверяется мутацией НЕ его ассерта, а его предусловия: сломал логин → 16 тестов из скипов стали 8 failed + 8 errors. Мутация ассерта доказывает только, что строка сравнения жива.
+- Сравнивать ДВА рендера спарклайна целиком нельзя: метка сброса (`resets_at`) считается от `Date.now()` в момент прогона, и одинаковые по смыслу картинки расходятся на доли пикселя (`x1="179.0156"` против `178.86`). Сравнивать только линии данных: `re.findall(r'points="([^"]+)" fill="none" stroke="#38bdf8"', html)`. Точки самих данных стабильны — их x считается от диапазона ряда, а не от часов.
### ad423c58f #185: #185: add chat event timeline navigation

diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index 301bd1364..cf8e83e50 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -63,5 +63,6 @@
 - `light-dark(<светлое>, <тёмное>)` — ПЕРВЫЙ аргумент для СВЕТЛОЙ схемы (MDN: «used when color-scheme is light or if no preference is set»). Проверяется за один прогон: `browser.new_page(color_scheme="light"|"dark")` + `getComputedStyle(...).backgroundColor`. Перепутанный порядок не падает и не подсвечивается — артефакт просто рисуется наоборот (#124).
 - Любой круг `JSON.parse` → `JSON.stringify` теряет целые больше 2^53 (`…147` → `…200`) и нормализует литералы (`1.0` → `1`, `A` → `A`). Если задача — ПОКАЗАТЬ файл, форматируй ТЕКСТ (`_prettyJsonText` в `utils.js`: сканер с учётом строк и экранирования), а `JSON.parse` оставляй только проверкой валидности. Замер #136: на 171 json репозитория раскладка не изменилась ни в одном, разошлись 46 — и все ровно на литерале числа.
 - Браузерные тесты в `tests/test_frontend.py` бьют по ЖИВОМУ :8888 и логинятся сами: креды снимаются в `_ENV_DASHBOARD_AUTH` НА ИМПОРТЕ модуля, потому что автоюзная `_hermetic_dashboard_env` (`tests/conftest.py:44`) стирает `DASHBOARD_*` из `os.environ` и глушит `load_dotenv` ради герметичности внутрипроцессных тестов. Читать креды внутри теста бесполезно — увидишь пустоту и решишь, что их нет в окружении (#145, потерянный прогон). Запасной источник — `dotenv_values()`, он не мутирует окружение.
 - Тест «не исполняется ли он вхолостую» проверяется мутацией НЕ его ассерта, а его предусловия: сломал логин → 16 тестов из скипов стали 8 failed + 8 errors. Мутация ассерта доказывает только, что строка сравнения жива.
 - Сравнивать ДВА рендера спарклайна целиком нельзя: метка сброса (`resets_at`) считается от `Date.now()` в момент прогона, и одинаковые по смыслу картинки расходятся на доли пикселя (`x1="179.0156"` против `178.86`). Сравнивать только линии данных: `re.findall(r'points="([^"]+)" fill="none" stroke="#38bdf8"', html)`. Точки самих данных стабильны — их x считается от диапазона ряда, а не от часов.
+- Любая новая прямая навигация по чату должна отменять `_scrollResetTimer`, сбрасывать `_pendingChatRestore` и снимать `scrollAfterLoad`: иначе `_scheduleChatInitialSettle()` через 500 мс молча перетянет чат обратно поверх клика. В #185 живой клик был верным первые 450 мс и уже к проверке снова оказывался вне вьюпорта.
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index e49b6103c..dd094d44b 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -1060,10 +1060,111 @@ def test_chat_restores_last_read_boundary_only_when_unread(
     assert "localStorage" not in code_without_comments
     assert "sessionStorage" in helper_code
     page.close()
 
 
+def test_chat_timeline_navigates_events_and_cycles_user_messages(
+    dashboard_browser: Browser,
+):
+    root = Path(__file__).parent.parent
+    source = (root / "app/static/js/app.js").read_text()
+    timeline_code = (
+        "let _chatTimelineObserver"
+        + source.split("let _chatTimelineObserver", 1)[1].split(
+            "function _prepareChatAnchorRestore", 1,
+        )[0]
+    )
+    page = dashboard_browser.new_page(viewport={"width": 900, "height": 700})
+    page.set_content(
+        """
+        <div style="position:relative;width:520px;height:260px">
+          <div id="chat" style="height:100%;overflow-y:auto"></div>
+          <aside id="chat-timeline" class="chat-timeline">
+            <div class="chat-timeline-user-nav">
+              <button id="chat-user-prev">↑</button><span id="chat-user-count"></span>
+              <button id="chat-user-next">↓</button>
+            </div>
+            <div id="chat-timeline-track" class="chat-timeline-track"></div>
+          </aside>
+          <button id="chat-jump-latest"></button>
+        </div>
+        """
+    )
+    page.add_style_tag(path=str(root / "app/static/css/style.css"))
+    page.add_script_tag(
+        content="""
+        const $ = selector => document.querySelector(selector);
+        let _chatFollow = true;
+        let scrollAfterLoad = true;
+        let _pendingChatRestore = null;
+        const _syncChatJumpButton = () => {};
+        """
+        + timeline_code
+        + """
+        window.addTimelineEntry = (type, label, from = '') => {
+            const node = document.createElement('div');
+            node.style.height = '90px';
+            node.style.flex = '0 0 90px';
+            node.dataset.testLabel = label;
+            if (from) node.dataset.from = from;
+            node.textContent = label;
+            _tagChatTimelineNode(node, type, '2026-08-11T10:00:00Z');
+            $('#chat').appendChild(node);
+            return node;
+        };
+        addTimelineEntry('assistant', 'agent-1');
+        addTimelineEntry('user_message', 'mine-1');
+        addTimelineEntry('tool', 'tool-1');
+        addTimelineEntry('user_message', 'worker-1', 'worker');
+        addTimelineEntry('assistant', 'agent-2');
+        addTimelineEntry('user_message', 'mine-2');
+        initChatTimeline();
+        """,
+    )
+
+    expect(page.locator("#chat-timeline-track .chat-timeline-marker")).to_have_count(6)
+    expect(page.locator("#chat-timeline-track .is-user")).to_have_count(2)
+    expect(page.locator("#chat-timeline-track .is-worker")).to_have_count(1)
+    expect(page.locator("#chat-user-count")).to_have_text("Я 2")
+
+    page.locator("#chat-timeline-track .is-tool").click()
+    page.wait_for_timeout(400)
+    assert page.evaluate(
+        """() => {
+            const chat = $('#chat');
+            const node = chat.querySelector('[data-test-label="tool-1"]');
+            const chatCenter = chat.getBoundingClientRect().top + chat.clientHeight / 2;
+            const nodeCenter = node.getBoundingClientRect().top + node.offsetHeight / 2;
+            return Math.abs(chatCenter - nodeCenter) < 3;
+        }"""
+    )
+
+    page.locator("#chat-user-prev").click()
+    page.wait_for_timeout(400)
+    assert page.evaluate(
+        """() => {
+            const users = [...document.querySelectorAll('#chat-timeline-track .is-user')];
+            return $('#chat-timeline-track .is-active') === users.at(-1);
+        }"""
+    )
+    page.locator("#chat-user-prev").click()
+    page.wait_for_timeout(400)
+    assert page.evaluate(
+        """() => {
+            const users = [...document.querySelectorAll('#chat-timeline-track .is-user')];
+            return $('#chat-timeline-track .is-active') === users[0];
+        }"""
+    )
+
+    page.evaluate("() => addTimelineEntry('user_message', 'mine-3')")
+    expect(page.locator("#chat-user-count")).to_have_text("Я 3")
+    page.evaluate("() => $('#chat [data-test-label=\"mine-3\"]').remove()")
+    expect(page.locator("#chat-user-count")).to_have_text("Я 2")
+    assert "_tagChatTimelineNode(el, type, ts);" in source
+    page.close()
+
+
 def test_codex_successful_mcp_startup_status_is_hidden(
     dashboard_browser: Browser,
 ):
     page = _open_tool_fixture_page(dashboard_browser)
     page.evaluate("""() => {
### 6c501b822 #174: WIP #174: add native history canary and diagnose Claude collector

diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index dd094d44b..53bf9c68e 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -31,10 +31,24 @@ def test_html_preview_uses_protected_raw_url_and_opaque_origin_sandbox():
     assert "openBtn.href = rawUrl;" in html_branch
     assert set(match.group(1).split()) == {"allow-scripts"}
     assert "allow-same-origin" not in match.group(1)
 
 
+def test_model_picker_surfaces_native_history_result_and_fallback():
+    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
+    helper = source.split("function _historyTransferMessage", 1)[1].split(
+        "async function _showModelPicker", 1,
+    )[0]
+    picker = source.split("async function _showModelPicker", 1)[1].split(
+        "function updateAgentInfo", 1,
+    )[0]
+
+    assert "reasoning omitted=${transfer.reasoning_omitted}" in helper
+    assert "summary fallback active" in helper
+    assert "_showHistoryTransfer(resp.history_transfer);" in picker
+
+
 @pytest.mark.asyncio
 @pytest.mark.parametrize("suffix", [".html", ".HTM"])
 async def test_raw_html_response_has_sandbox_csp(tmp_path, monkeypatch, suffix):
     from app.routes import system
 
### 8b0735950 #212: #212: restore truncated Read images from full log

diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index cf8e83e50..50329185f 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -64,5 +64,6 @@
 - Любой круг `JSON.parse` → `JSON.stringify` теряет целые больше 2^53 (`…147` → `…200`) и нормализует литералы (`1.0` → `1`, `A` → `A`). Если задача — ПОКАЗАТЬ файл, форматируй ТЕКСТ (`_prettyJsonText` в `utils.js`: сканер с учётом строк и экранирования), а `JSON.parse` оставляй только проверкой валидности. Замер #136: на 171 json репозитория раскладка не изменилась ни в одном, разошлись 46 — и все ровно на литерале числа.
 - Браузерные тесты в `tests/test_frontend.py` бьют по ЖИВОМУ :8888 и логинятся сами: креды снимаются в `_ENV_DASHBOARD_AUTH` НА ИМПОРТЕ модуля, потому что автоюзная `_hermetic_dashboard_env` (`tests/conftest.py:44`) стирает `DASHBOARD_*` из `os.environ` и глушит `load_dotenv` ради герметичности внутрипроцессных тестов. Читать креды внутри теста бесполезно — увидишь пустоту и решишь, что их нет в окружении (#145, потерянный прогон). Запасной источник — `dotenv_values()`, он не мутирует окружение.
 - Тест «не исполняется ли он вхолостую» проверяется мутацией НЕ его ассерта, а его предусловия: сломал логин → 16 тестов из скипов стали 8 failed + 8 errors. Мутация ассерта доказывает только, что строка сравнения жива.
 - Сравнивать ДВА рендера спарклайна целиком нельзя: метка сброса (`resets_at`) считается от `Date.now()` в момент прогона, и одинаковые по смыслу картинки расходятся на доли пикселя (`x1="179.0156"` против `178.86`). Сравнивать только линии данных: `re.findall(r'points="([^"]+)" fill="none" stroke="#38bdf8"', html)`. Точки самих данных стабильны — их x считается от диапазона ряда, а не от часов.
 - Любая новая прямая навигация по чату должна отменять `_scrollResetTimer`, сбрасывать `_pendingChatRestore` и снимать `scrollAfterLoad`: иначе `_scheduleChatInitialSettle()` через 500 мс молча перетянет чат обратно поверх клика. В #185 живой клик был верным первые 450 мс и уже к проверке снова оказывался вне вьюпорта.
+- Картинка из `Read` имеет три источника разной живучести: временный `file_path`, base64 в обрезанной истории и полная durable-строка `GET /api/logs/{id}`. Для проверки fallback принудительно отвечай 404 на исходный путь и подавай ровно обрезанный payload; существующий файл иначе маскирует поломку восстановления из журнала.
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 53bf9c68e..2021b65d5 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -1382,5 +1382,129 @@ def test_codex_view_image_loads_eagerly(
     )
     assert image.evaluate("(img) => img.naturalWidth") == 2800
     assert requests == 2
     expect(image).not_to_have_class("codex-tool-image-error")
     page.close()
+
+
+def test_truncated_read_image_restores_full_log_when_source_file_is_gone(
+    dashboard_browser: Browser,
+):
+    root = Path(__file__).parent.parent
+    source = (root / "app/static/js/app.js").read_text()
+    page = dashboard_browser.new_page()
+    png = (
+        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
+        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
+    )
+    requests = {"file": 0, "log": []}
+
+    def missing_source(route):
+        requests["file"] += 1
+        route.fulfill(status=404)
+
+    def full_log(route):
+        log_id = int(route.request.url.rsplit("/", 1)[-1])
+        requests["log"].append(log_id)
+        image_data = png + " " * 20 if log_id == 42 else "A" * 120
+        route.fulfill(
+            status=200,
+            content_type="application/json",
+            json={
+                "id": log_id,
+                "type": "tool_result",
+                "content": (
+                    "{'type': 'image', 'source': {'type': 'base64', 'data': '"
+                    + image_data
+                    + "', 'media_type': 'image/png'}}"
+                ),
+            },
+        )
+
+    page.route("**/api/files/raw?**", missing_source)
+    page.route(re.compile(r".*/api/logs/\d+$"), full_log)
+    page.route(
+        "**/static/js/app.js*",
+        lambda route: route.fulfill(
+            status=200, content_type="text/javascript", body=source,
+        ),
+    )
+    _goto_dashboard_or_skip(page)
+    page.wait_for_function("() => typeof _restoreToolResultImage === 'function'")
+    page.wait_for_function(
+        "() => typeof selectedAgent !== 'undefined' && selectedAgent !== null"
+    )
+    page.evaluate(
+        """() => {
+            selectedAgent = null;
+            if (eventSource) {
+                eventSource.close();
+                eventSource = null;
+            }
+            window.compactMode = false;
+            document.querySelector('#chat').innerHTML = '';
+            addChatEntry(
+                'tool',
+                'Read: {"file_path":"/tmp/already-gone.png"}',
+                null, null, {tool_use_id: 'read-1'}
+            );
+            addChatEntry(
+                'tool_result',
+                "{'type': 'image', 'source': {'type': 'base64', 'data': 'cut",
+                null, null,
+                {id: 42, trunc: 50000, tool_use_id: 'read-1'}
+            );
+        }"""
+    )
+
+    page.wait_for_timeout(1000)
+    state = page.evaluate(
+        """() => ({
+            html: $('#chat').innerHTML,
+            src: $('#chat img')?.src,
+            width: $('#chat img')?.naturalWidth,
+        })"""
+    )
+    image = page.locator("#chat img")
+    assert state["width"] == 1, (state, requests)
+    assert image.evaluate("img => [img.naturalWidth, img.naturalHeight]") == [1, 1]
+    expect(page.locator("#chat")).not_to_contain_text("[Image result]")
+    assert requests == {"file": 1, "log": [42]}
+
+    page.evaluate(
+        """() => {
+            document.querySelector('#chat').innerHTML = '';
+            addChatEntry(
+                'tool',
+                'Read: {"file_path":"/tmp/already-gone.png"}',
+                null, null, {tool_use_id: 'read-2'}
+            );
+            addChatEntry(
+                'tool_result',
+                "{'type': 'image', 'source': {'type': 'base64', 'data': '"
+                    + 'A'.repeat(120) + "', 'media_type': 'image/png'}}",
+                null, null, {id: 42, tool_use_id: 'read-2'}
+            );
+        }"""
+    )
+    page.wait_for_function("() => $('#chat img')?.naturalWidth === 1")
+    assert requests == {"file": 2, "log": [42, 42]}
+
+    page.evaluate(
+        """() => {
+            document.querySelector('#chat').innerHTML = '';
+            addChatEntry(
+                'tool',
+                'Read: {"file_path":"/tmp/already-gone.png"}',
+                null, null, {tool_use_id: 'read-3'}
+            );
+            addChatEntry(
+                'tool_result',
+                "{'type': 'image', 'source': {'type': 'base64', 'data': 'cut",
+                null, null, {id: 43, trunc: 50000, tool_use_id: 'read-3'}
+            );
+        }"""
+    )
+    expect(page.locator("#chat")).to_contain_text("Image unavailable")
+    assert page.locator("#chat img").count() == 0
+    assert requests == {"file": 3, "log": [42, 42, 43]}
+    page.close()
### 21ead017a #245: #245: add dashboard voice input

diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index 50329185f..3529d0402 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -65,5 +65,6 @@
 - Браузерные тесты в `tests/test_frontend.py` бьют по ЖИВОМУ :8888 и логинятся сами: креды снимаются в `_ENV_DASHBOARD_AUTH` НА ИМПОРТЕ модуля, потому что автоюзная `_hermetic_dashboard_env` (`tests/conftest.py:44`) стирает `DASHBOARD_*` из `os.environ` и глушит `load_dotenv` ради герметичности внутрипроцессных тестов. Читать креды внутри теста бесполезно — увидишь пустоту и решишь, что их нет в окружении (#145, потерянный прогон). Запасной источник — `dotenv_values()`, он не мутирует окружение.
 - Тест «не исполняется ли он вхолостую» проверяется мутацией НЕ его ассерта, а его предусловия: сломал логин → 16 тестов из скипов стали 8 failed + 8 errors. Мутация ассерта доказывает только, что строка сравнения жива.
 - Сравнивать ДВА рендера спарклайна целиком нельзя: метка сброса (`resets_at`) считается от `Date.now()` в момент прогона, и одинаковые по смыслу картинки расходятся на доли пикселя (`x1="179.0156"` против `178.86`). Сравнивать только линии данных: `re.findall(r'points="([^"]+)" fill="none" stroke="#38bdf8"', html)`. Точки самих данных стабильны — их x считается от диапазона ряда, а не от часов.
 - Любая новая прямая навигация по чату должна отменять `_scrollResetTimer`, сбрасывать `_pendingChatRestore` и снимать `scrollAfterLoad`: иначе `_scheduleChatInitialSettle()` через 500 мс молча перетянет чат обратно поверх клика. В #185 живой клик был верным первые 450 мс и уже к проверке снова оказывался вне вьюпорта.
 - Картинка из `Read` имеет три источника разной живучести: временный `file_path`, base64 в обрезанной истории и полная durable-строка `GET /api/logs/{id}`. Для проверки fallback принудительно отвечай 404 на исходный путь и подавай ровно обрезанный payload; существующий файл иначе маскирует поломку восстановления из журнала.
+- Кросс-браузерную запись проверяй двумя независимыми плечами: Chromium с настоящим fake audio device упражняет реальные `getUserMedia`/`MediaRecorder`/`AnalyserNode` и multipart, а capability-fake отдельно заставляет выбрать Safari `audio/mp4`. Одно плечо не доказывает второе.
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 2021b65d5..afaccc890 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -1506,5 +1506,139 @@ def test_truncated_read_image_restores_full_log_when_source_file_is_gone(
     )
     expect(page.locator("#chat")).to_contain_text("Image unavailable")
     assert page.locator("#chat img").count() == 0
     assert requests == {"file": 3, "log": [42, 42, 43]}
     page.close()
+
+
+def test_mobile_voice_input_records_transcribes_and_cancels(dashboard_browser: Browser):
+    root = Path(__file__).parent.parent
+    app_source = (root / "app/static/js/app.js").read_text()
+    css_source = (root / "app/static/css/style.css").read_text()
+    context = dashboard_browser.new_context(
+        viewport={"width": 390, "height": 844},
+        is_mobile=True,
+        has_touch=True,
+        device_scale_factor=3,
+    )
+    page = context.new_page()
+    page_errors = []
+    page.on("pageerror", lambda error: page_errors.append(str(error)))
+    requests = {"transcribe": 0, "send": 0, "body": b"", "content_type": ""}
+    fake_media_script = """() => {
+            window.__voiceTrackStops = 0;
+            window.__voiceGetUserMediaCalls = 0;
+            Object.defineProperty(navigator, 'mediaDevices', {
+                configurable: true,
+                value: {getUserMedia: async () => {
+                    window.__voiceGetUserMediaCalls++;
+                    return {getTracks: () => [{stop: () => window.__voiceTrackStops++}]};
+                }},
+            });
+            class FakeRecorder {
+                static isTypeSupported(type) {
+                    return type === 'audio/mp4;codecs=mp4a.40.2';
+                }
+                constructor(_stream, options = {}) {
+                    this.mimeType = options.mimeType || 'audio/mp4';
+                    this.state = 'inactive';
+                    this.listeners = {};
+                    window.__voiceChosenMime = this.mimeType;
+                }
+                addEventListener(type, callback) { this.listeners[type] = callback; }
+                start() { this.state = 'recording'; }
+                stop() {
+                    this.state = 'inactive';
+                    setTimeout(() => {
+                        this.listeners.dataavailable?.({data: new Blob(['recorded'], {type: this.mimeType})});
+                        this.listeners.stop?.();
+                    }, 80);
+                }
+            }
+            class FakeAudioContext {
+                createMediaStreamSource() { return {connect: () => {}}; }
+                createAnalyser() {
+                    return {
+                        fftSize: 256,
+                        getByteTimeDomainData: values => {
+                            values.fill(128);
+                            values[0] = 255;
+                        },
+                    };
+                }
+                close() { return Promise.resolve(); }
+            }
+            Object.defineProperty(window, 'MediaRecorder', {configurable: true, value: FakeRecorder});
+            Object.defineProperty(window, 'AudioContext', {configurable: true, value: FakeAudioContext});
+        }"""
+
+    def transcribe(route):
+        requests["transcribe"] += 1
+        requests["body"] = route.request.post_data_buffer or b""
+        requests["content_type"] = route.request.headers.get("content-type", "")
+        route.fulfill(
+            status=200,
+            content_type="application/json",
+            json={"text": "Надиктованный текст"},
+        )
+
+    def unexpected_send(route):
+        requests["send"] += 1
+        route.fulfill(status=500, content_type="application/json", json={"error": "unexpected"})
+
+    page.route("**/api/transcribe", transcribe)
+    page.route("**/api/sessions/*/send", unexpected_send)
+    page.route(
+        "**/static/js/app.js*",
+        lambda route: route.fulfill(
+            status=200, content_type="text/javascript", body=app_source,
+        ),
+    )
+    page.route(
+        "**/static/css/style.css*",
+        lambda route: route.fulfill(
+            status=200, content_type="text/css", body=css_source,
+        ),
+    )
+    _goto_dashboard_or_skip(page)
+    page.wait_for_function("() => typeof initVoiceInput === 'function'")
+    page.evaluate(fake_media_script)
+    expect(page.locator("#voice-btn")).to_be_visible()
+
+    page.locator("#voice-btn").click()
+    page.wait_for_timeout(500)
+    state = page.locator("#voice-controls").get_attribute("data-state")
+    assert state == "recording", (state, page.locator("#voice-error").text_content(), page_errors)
+    page.wait_for_timeout(1100)
+    minutes, seconds = map(int, page.locator("#voice-timer").text_content().split(":"))
+    assert 1 <= minutes * 60 + seconds < 10
+    assert float(page.locator("#voice-level").evaluate(
+        "node => node.style.getPropertyValue('--voice-level')"
+    )) > 1
+    assert page.evaluate("window.__voiceChosenMime") == "audio/mp4;codecs=mp4a.40.2"
+
+    page.evaluate("() => { $('#voice-btn').click(); startVoiceInput(); }")
+    page.wait_for_function("() => $('#chat-input').value === 'Надиктованный текст'")
+    assert page.evaluate("window.__voiceGetUserMediaCalls") == 1
+    assert requests["transcribe"] == 1
+    assert requests["send"] == 0
+    assert "multipart/form-data; boundary=" in requests["content_type"]
+    assert b'filename="voice.m4a"' in requests["body"]
+    assert page.evaluate("window.__voiceTrackStops") == 1
+
+    page.locator("#voice-btn").click()
+    page.wait_for_function("() => $('#voice-controls')?.dataset.state === 'recording'")
+    page.locator("#voice-cancel-btn").click()
+    page.wait_for_function("() => $('#voice-controls')?.dataset.state === 'idle'")
+    assert requests["transcribe"] == 1
+    assert page.locator("#chat-input").input_value() == "Надиктованный текст"
+    assert page.evaluate("window.__voiceTrackStops") == 2
+
+    page.evaluate(
+        """() => Object.defineProperty(navigator, 'mediaDevices', {
### ba10d0dcb #163: #163: keep usage controls visible on narrow desktops

diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index 3529d0402..8880e15b5 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -66,5 +66,6 @@
 - Тест «не исполняется ли он вхолостую» проверяется мутацией НЕ его ассерта, а его предусловия: сломал логин → 16 тестов из скипов стали 8 failed + 8 errors. Мутация ассерта доказывает только, что строка сравнения жива.
 - Сравнивать ДВА рендера спарклайна целиком нельзя: метка сброса (`resets_at`) считается от `Date.now()` в момент прогона, и одинаковые по смыслу картинки расходятся на доли пикселя (`x1="179.0156"` против `178.86`). Сравнивать только линии данных: `re.findall(r'points="([^"]+)" fill="none" stroke="#38bdf8"', html)`. Точки самих данных стабильны — их x считается от диапазона ряда, а не от часов.
 - Любая новая прямая навигация по чату должна отменять `_scrollResetTimer`, сбрасывать `_pendingChatRestore` и снимать `scrollAfterLoad`: иначе `_scheduleChatInitialSettle()` через 500 мс молча перетянет чат обратно поверх клика. В #185 живой клик был верным первые 450 мс и уже к проверке снова оказывался вне вьюпорта.
 - Картинка из `Read` имеет три источника разной живучести: временный `file_path`, base64 в обрезанной истории и полная durable-строка `GET /api/logs/{id}`. Для проверки fallback принудительно отвечай 404 на исходный путь и подавай ровно обрезанный payload; существующий файл иначе маскирует поломку восстановления из журнала.
 - Кросс-браузерную запись проверяй двумя независимыми плечами: Chromium с настоящим fake audio device упражняет реальные `getUserMedia`/`MediaRecorder`/`AnalyserNode` и multipart, а capability-fake отдельно заставляет выбрать Safari `audio/mp4`. Одно плечо не доказывает второе.
+- В верхней части дашборда два элемента с графиками: `#usage-info-btn` (`ⓘ`) открывает usage control со спарклайнами в верхнем usage-баре, `#analytics-btn` (`📊`) — отдельную analytics modal в header. При жалобе «кнопка графиков срезана» мерь rect обоих: в #163 второй был виден, за экраном лежал первый.
### d894fc6e4 #259: #259: audit dashboard clarity and propose UX

diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index 8880e15b5..549755eeb 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -65,7 +65,8 @@
 - Браузерные тесты в `tests/test_frontend.py` бьют по ЖИВОМУ :8888 и логинятся сами: креды снимаются в `_ENV_DASHBOARD_AUTH` НА ИМПОРТЕ модуля, потому что автоюзная `_hermetic_dashboard_env` (`tests/conftest.py:44`) стирает `DASHBOARD_*` из `os.environ` и глушит `load_dotenv` ради герметичности внутрипроцессных тестов. Читать креды внутри теста бесполезно — увидишь пустоту и решишь, что их нет в окружении (#145, потерянный прогон). Запасной источник — `dotenv_values()`, он не мутирует окружение.
 - Тест «не исполняется ли он вхолостую» проверяется мутацией НЕ его ассерта, а его предусловия: сломал логин → 16 тестов из скипов стали 8 failed + 8 errors. Мутация ассерта доказывает только, что строка сравнения жива.
 - Сравнивать ДВА рендера спарклайна целиком нельзя: метка сброса (`resets_at`) считается от `Date.now()` в момент прогона, и одинаковые по смыслу картинки расходятся на доли пикселя (`x1="179.0156"` против `178.86`). Сравнивать только линии данных: `re.findall(r'points="([^"]+)" fill="none" stroke="#38bdf8"', html)`. Точки самих данных стабильны — их x считается от диапазона ряда, а не от часов.
 - Любая новая прямая навигация по чату должна отменять `_scrollResetTimer`, сбрасывать `_pendingChatRestore` и снимать `scrollAfterLoad`: иначе `_scheduleChatInitialSettle()` через 500 мс молча перетянет чат обратно поверх клика. В #185 живой клик был верным первые 450 мс и уже к проверке снова оказывался вне вьюпорта.
 - Картинка из `Read` имеет три источника разной живучести: временный `file_path`, base64 в обрезанной истории и полная durable-строка `GET /api/logs/{id}`. Для проверки fallback принудительно отвечай 404 на исходный путь и подавай ровно обрезанный payload; существующий файл иначе маскирует поломку восстановления из журнала.
+- Compact mode чата — отдельный ранний renderer (`app.js` около ветки `window.compactMode`), который обходит обычные semantic tool-карточки. Любую правку tool result проверять в ОБОИХ режимах и параллельным сценарием A/B → result A/result B: привязка только по `tool_use_id`, «последний tool» перекрещивает результаты.
 - Кросс-браузерную запись проверяй двумя независимыми плечами: Chromium с настоящим fake audio device упражняет реальные `getUserMedia`/`MediaRecorder`/`AnalyserNode` и multipart, а capability-fake отдельно заставляет выбрать Safari `audio/mp4`. Одно плечо не доказывает второе.
 - В верхней части дашборда два элемента с графиками: `#usage-info-btn` (`ⓘ`) открывает usage control со спарклайнами в верхнем usage-баре, `#analytics-btn` (`📊`) — отдельную analytics modal в header. При жалобе «кнопка графиков срезана» мерь rect обоих: в #163 второй был виден, за экраном лежал первый.
### 173f2d863 #260: #260: correlate parallel tool results by id

diff --git a/docs/workers/frontend.md b/docs/workers/frontend.md
index 549755eeb..c0760edd9 100644
--- a/docs/workers/frontend.md
+++ b/docs/workers/frontend.md
@@ -65,8 +65,8 @@
 - Браузерные тесты в `tests/test_frontend.py` бьют по ЖИВОМУ :8888 и логинятся сами: креды снимаются в `_ENV_DASHBOARD_AUTH` НА ИМПОРТЕ модуля, потому что автоюзная `_hermetic_dashboard_env` (`tests/conftest.py:44`) стирает `DASHBOARD_*` из `os.environ` и глушит `load_dotenv` ради герметичности внутрипроцессных тестов. Читать креды внутри теста бесполезно — увидишь пустоту и решишь, что их нет в окружении (#145, потерянный прогон). Запасной источник — `dotenv_values()`, он не мутирует окружение.
 - Тест «не исполняется ли он вхолостую» проверяется мутацией НЕ его ассерта, а его предусловия: сломал логин → 16 тестов из скипов стали 8 failed + 8 errors. Мутация ассерта доказывает только, что строка сравнения жива.
 - Сравнивать ДВА рендера спарклайна целиком нельзя: метка сброса (`resets_at`) считается от `Date.now()` в момент прогона, и одинаковые по смыслу картинки расходятся на доли пикселя (`x1="179.0156"` против `178.86`). Сравнивать только линии данных: `re.findall(r'points="([^"]+)" fill="none" stroke="#38bdf8"', html)`. Точки самих данных стабильны — их x считается от диапазона ряда, а не от часов.
 - Любая новая прямая навигация по чату должна отменять `_scrollResetTimer`, сбрасывать `_pendingChatRestore` и снимать `scrollAfterLoad`: иначе `_scheduleChatInitialSettle()` через 500 мс молча перетянет чат обратно поверх клика. В #185 живой клик был верным первые 450 мс и уже к проверке снова оказывался вне вьюпорта.
 - Картинка из `Read` имеет три источника разной живучести: временный `file_path`, base64 в обрезанной истории и полная durable-строка `GET /api/logs/{id}`. Для проверки fallback принудительно отвечай 404 на исходный путь и подавай ровно обрезанный payload; существующий файл иначе маскирует поломку восстановления из журнала.
-- Compact mode чата — отдельный ранний renderer (`app.js` около ветки `window.compactMode`), который обходит обычные semantic tool-карточки. Любую правку tool result проверять в ОБОИХ режимах и параллельным сценарием A/B → result A/result B: привязка только по `tool_use_id`, «последний tool» перекрещивает результаты.
+- Compact mode чата — отдельный ранний renderer (`app.js` около ветки `window.compactMode`), который обходит обычные semantic tool-карточки. Любую правку tool result проверять в ОБОИХ режимах и параллельным сценарием A/B → result A/result B. Канонический id Claude/MCP — `payload.tool_use_id`, `_codex_item_id` только fallback нативного Codex; каждый replay/prepend обязан передавать в `addChatEntry` полную строку. Результат ищет только exact id, «последний tool» перекрещивает параллельные ответы, а missing match надо показывать отдельным orphan, не глотать.
 - Кросс-браузерную запись проверяй двумя независимыми плечами: Chromium с настоящим fake audio device упражняет реальные `getUserMedia`/`MediaRecorder`/`AnalyserNode` и multipart, а capability-fake отдельно заставляет выбрать Safari `audio/mp4`. Одно плечо не доказывает второе.
 - В верхней части дашборда два элемента с графиками: `#usage-info-btn` (`ⓘ`) открывает usage control со спарклайнами в верхнем usage-баре, `#analytics-btn` (`📊`) — отдельную analytics modal в header. При жалобе «кнопка графиков срезана» мерь rect обоих: в #163 второй был виден, за экраном лежал первый.
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index afaccc890..adf01ac66 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -2,10 +2,11 @@
 
 Requires: Orchestra running on localhost:8888 (no auth).
 Run: pytest tests/test_frontend.py -v
 """
 
+import json
 import os
 import re
 import subprocess
 from pathlib import Path
 
@@ -824,10 +825,353 @@ def _open_tool_fixture_page(browser: Browser) -> Page:
         document.querySelector('#chat').innerHTML = '';
     }""")
     return page
 
 
+def _open_tool_correlation_page(
+    browser: Browser,
+    compact_mode: bool,
+    source_path: Path | None = None,
+) -> Page:
+    page = browser.new_page()
+    source = (
+        source_path or Path(__file__).parent.parent / "app/static/js/app.js"
+    ).read_text()
+    page.route(
+        "**/static/js/app.js*",
+        lambda route: route.fulfill(
+            status=200,
+            content_type="application/javascript",
+            body=source,
+        ),
+    )
+    _goto_dashboard_or_skip(page)
+    page.wait_for_function("() => typeof addChatEntry === 'function'")
+    page.evaluate("""compactMode => {
+        selectedAgent = null;
+        if (eventSource) {
+            eventSource.close();
+            eventSource = null;
+        }
+        window.compactMode = compactMode;
+        document.querySelector('#chat').innerHTML = '';
+    }""", compact_mode)
+    return page
+
+
+@pytest.mark.parametrize("compact_mode", [False, True], ids=["normal", "compact"])
+def test_parallel_tool_results_follow_tool_use_id_in_both_renderers(
+    dashboard_browser: Browser,
+    compact_mode: bool,
+):
+    source_override = os.environ.get("ORCHESTRA_TOOL_CORRELATION_SOURCE")
+    source_path = Path(source_override) if source_override else None
+    page = _open_tool_correlation_page(dashboard_browser, compact_mode, source_path)
+    result_by_id = page.evaluate("""() => {
+        const calls = [
+            ['mcp__orchestra__task_create', {title:'CALL-A'} , 'parallel-a', 26001],
+            ['mcp__orchestra__list_agents', {}, 'parallel-b', 26002],
+            ['mcp__orchestra__worker_wip', {name:'CALL-C'}, 'parallel-c', 26003],
+        ];
+        for (const [name, args, toolUseId, id] of calls) {
+            addChatEntry('tool', `${name}: ${JSON.stringify(args)}`, null, null,
+                {id, tool_use_id:toolUseId});
+        }
+
+        // A real parallel block logs every call before any result. Results may
+        // then finish in a different order; each marker deliberately differs.
+        for (const [toolUseId, marker, id] of [
+            ['parallel-c', 'RESULT-ONLY-C', 26006],
+            ['parallel-a', 'RESULT-ONLY-A', 26004],
+            ['parallel-b', 'RESULT-ONLY-B', 26005],
+        ]) {
+            addChatEntry('tool_result', marker, null, null, {id, tool_use_id:toolUseId});
+        }
+        const selector = window.compactMode ? '[data-compact-tool]' : '[data-tool-use-id]:not([data-compact-tool])';
+        return Object.fromEntries([...document.querySelectorAll(`#chat ${selector}`)]
+            .map(card => [
+                card.dataset.toolUseId,
+                window.compactMode ? card.dataset.resultContent || '' : card.innerText,
+            ]));
+    }""")
+    page.close()
+
+    assert set(result_by_id) == {"parallel-a", "parallel-b", "parallel-c"}
+    for tool_use_id, marker in {
+        "parallel-a": "RESULT-ONLY-A",
+        "parallel-b": "RESULT-ONLY-B",
+        "parallel-c": "RESULT-ONLY-C",
+    }.items():
+        assert marker in result_by_id[tool_use_id]
+        assert not any(
+            other in result_by_id[tool_use_id]
+            for other in {"RESULT-ONLY-A", "RESULT-ONLY-B", "RESULT-ONLY-C"}
+            if other != marker
+        )
+
+
+@pytest.mark.parametrize("compact_mode", [False, True], ids=["normal", "compact"])
+def test_unmatched_tool_result_is_visible_and_never_attaches_to_another_call(
+    dashboard_browser: Browser,
+    compact_mode: bool,
+):
+    page = _open_tool_correlation_page(dashboard_browser, compact_mode)
+    rendered = page.evaluate("""() => {
+        addChatEntry(
+            'tool',
+            'mcp__orchestra__task_create: {"title":"DO-NOT-ATTACH"}',
+            null,
+            null,
+            {id:26011, tool_use_id:'known-call'},
+        );
+        addChatEntry(
+            'tool_result',
+            'ORPHAN-RESULT-MARKER',
+            null,
+            null,
+            {id:26012, tool_use_id:'missing-call'},
+        );
+        const call = document.querySelector('[data-tool-use-id="known-call"]');
+        const orphan = document.querySelector('[data-unmatched-tool-result]');
+        return {
+            callText: call?.innerText || '',
+            orphanText: orphan?.innerText || '',
+            orphanCount: document.querySelectorAll('[data-unmatched-tool-result]').length,
+        };
+    }""")
+    page.close()
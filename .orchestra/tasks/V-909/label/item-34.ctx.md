# Context for item-34

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 14b5ae3a6..f8b5c2c9c 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -1,41 +1,63 @@
 # Changelog
 
 > **Two environments merged, 04.08.2026.** Before this date, the laptop and VPS maintained
 > their CHANGELOGs independently, so versions 2.31.0-2.33.0 were used TWICE for different
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
 ### Fixed
+- 🧭 **Допуск харнес-маршрута решается по живому каталогу OpenRouter, а не по нашей
+  записи о нём** (`app/models.py` — `validate_harness_model_spec`, из
+  `SELECTABLE_MODEL_SPECS` убраны оба зашитых харнес-маршрута; `app/model_catalog.py` —
+  `live_catalog_entry`, `harness_capable` вместо приватного `_cached_harness_eligible`).
+  Отказ наступает, когда провайдер говорит «нет tools» или маршрут исчез из каталога,
+  даже если наше поле `supported_parameters` утверждает обратное. Состав харнес-маршрутов
+  теперь приходит ТОЛЬКО из каталога. *Triggered case:* замер 16.09.2026 (#V-581) показал,
+  что мертвы оба зашитых: `z-ai/glm-5.2:free` в живом каталоге отдаёт `tools=False` и
+  `ctx=32768` против наших 256000, а `nvidia/nemotron-3-ultra-550b-a55b:free` вызывает
+  инструмент и игнорирует его результат. До правки это узнавалось только сожжённым ходом
+  воркера. *Known tradeoff:* с пустым кешем каталога ни один харнес-маршрут не проходит
+  допуск — выбрано осознанно (fail-closed), каталог подтягивается обновлением на экране
+  моделей.
 - 🏷 **Окна квоты Codex подписаны своей длительностью, а не позицией в ответе**
   (`app/static/js/utils.js` — новый общий `windowLabel`, `_PROVIDER_META.codex.windows`;
   `app/static/js/analytics.js` — подписи окон Spark). Панель аналитики печатала
   «Основной» и «Вторичный», что ничего не сообщало о том, какой лимит упёрся.
   Заодно снята вторая копия этой логики: ярлык считался ещё и в `app/static/js/usage.js`
   (`_codexWindowLabel`), теперь владелец один. *Triggered case:* 17.09.2026 аккаунт
   перешёл с free на Plus, и у Codex вместо одного 30-дневного окна стало два — 5 часов
   и неделя; на панели они назывались «Основной/Вторичный», хотя у Claude рядом
   честно стоят 5h и 7d.
 
 
 ### Added
+- 🔬 **`scripts/probe_free_models.py` — проба `:free` маршрутов на полный протокол
+  инструментов** (`--out` с машиночитаемым JSON, `--model`, `--limit`,
+  `--requests-per-route`, `--budget-seconds`). Маршрут засчитывается пройденным, только
+  если он вызвал инструмент, передал осмысленный аргумент И ответил ПО РЕЗУЛЬТАТУ
+  инструмента; вызов с игнорированием ответа — `result_ignored`, то есть непрошедший.
+  Ошибки провайдера (`rate_limited`, `http_403`, `timeout`) отделены от отказов самой
+  модели, а маршруты, до которых не дошёл бюджет, помечаются `not_probed`, а не молча
+  выпадают. *Triggered case:* проба жила разовым скриптом в `.orchestra/tasks/V-581/`,
+  и проверять протухание маршрутов было нечем.
 - 🔓 **Кнопка «снять гейт на время» на панели квот** (`app/quota_gate.py`:
   `set_gate_override`/`clear_gate_override`/`gate_override_remaining`, `POST
   /api/usage/quota-override`, индикатор и кнопка в `app/static/js/quota-lines.js`).
   Пока снятие действует, полоса не держится диагональю, а потолок полосы (`sol` 95%)
   заменяется общим; **жёсткий стоп не снимается никогда** — за ним стоит предел
   провайдера, и пропуск туда обменял бы наш отказ на 429 у провайдера. Снятие живёт в
   памяти процесса и гаснет при рестарте: это выбрано намеренно, потому что забытое
   бессрочное снятие уже стоило трёх суток снятого гейта (`QUOTA_GATED_LANES=` с 12.09
   по 15.09.2026), а потеря снятия отказывает в безопасную сторону. Потолок одного
   нажатия — 6 часов. Агентам выключатель не выдан: ни MCP-тула, ни параметра спавна.
   *Known tradeoff:* снятие общее, а не по полосам — снять только Claude, оставив Sol,
   сейчас нельзя. *Triggered case:* 16.09.2026 спавн воркера отбит нашей же линией на
   0.4 п.п. (23% против 22.61%) в начале недельного окна, при том что пул был свободен.
 
 ### Fixed
 - 🚦 **`lanes[].gated` в карте квот берётся из вердикта гейта, а не из состава
   `policy.gated_lanes`** (`app/routes/system.py`). При временном снятии полоса остаётся
   в списке гейтящихся, но прямо сейчас не держит — панель рисовала бы её держащей.
 
 ### Changed
diff --git a/TODO.md b/TODO.md
index d569e08f4..1b7b540d5 100644
--- a/TODO.md
+++ b/TODO.md
@@ -66,41 +66,41 @@
 - [ ] **Идея на A/B, не на внедрение: единый вычислительный namespace («контекст как переменная»).** Единственное, чего у нас объективно нет: мы храним диалог и файлы, но не живое вычислительное состояние модели. Применимость узкая — большие входы, которые перечитываются много раз. Цена высокая (kernel manager, снимки, сборка мусора, учёт рекурсии), поэтому только замер на нашей задаче, а не стройка.
 ## Квота: перестать выбрасывать точные числа (по итогам #440)
 
 - [ ] **Ловить `rate_limit_event` и сохранять НЕокруглённую `utilization`.** CLI 2.1.258 её присылает, SDK 0.2.114 разбирает в `RateLimitInfo` вместе с `raw`, а `ClaudeBackend` (`app/backend_claude.py:17-35,1398-1444`) не импортирует событие и не имеет ветки в диспетчере — данные теряются до БД. Даёт точный потолок аккаунта, окончательный ответ про режим промо (83.3 / 104.2 / 125 млн) и цену задачи в кредитах ДО запуска вместо процентов постфактум. Ждёт слова юзера. На VPS сперва обновить CLI: там 2.1.205, разбивки по окнам ещё нет.
 
 ## Красные тесты на main
 - [ ] **`tests/test_api.py::TestTaskProjectIdentity` — два теста красные с 28.08.** `test_create_defaults_to_callers_mapped_scope` и `test_create_accepts_registered_scope_as_explicit_project`, обе `400 {"error":"create_task cannot allocate a task number: call api_create_task…"}`. Причина: `a10f1451` («номер задачи выдаёт только один владелец») добавил fail-loud в `app/tm.py:create_task`, приехал со СВОИМ тестом `test_task_par_collision_406.py`, а `test_api.py` не поправили. **Прод верный, чинить тест.** Очевидная починка не работает: переписал сид на `api_create_task` → стало 8 падений вместо 2 (семь тестов класса зависят от сырого INSERT). Нужен canonical-контекст в тестовой среде либо явный тестовый режим выдачи номера. В merge-gate не входит, мержи не блокирует.
 - [ ] **`tests/test_tailwind_css.py::test_committed_css_matches_current_sources` красный на main.** Утилита `mr-auto` используется в `app/templates/dashboard.html:161`, но отсутствует в собранном `app/static/css/vendor/tailwind.css` — CSS не пересобрали после правки шаблона. Чинится пересборкой Tailwind; собранный файл последний раз менялся в `87fd4679`. Пока красный — бесполезен как защита.
 
 ## Дефекты платформы (репорты от других проектов + свои)
 - [ ] **P1. Сообщение, влитое в идущий ход Codex, НЕ переживает обрыв этого хода — и теряется именно тогда, когда оно срочное.** Доказано на живом инциденте 12.09 (`painter-astra`, экспонат не реагировал на касания): в 16:55:26 оркестратор влил срочное «ЭКСПОНАТ НЕ РЕАГИРУЕТ НА КАСАНИЯ» (`message steered into active Codex turn`), после чего ход шесть минут не делал НИ ОДНОГО действия и в 17:01:32 был прерван вручную — `turn ended (interrupted, 0 turns, $7.43 turn)` и `turn FAILED: error`. После рестарта хода агент ответил на СТАРУЮ тему («На связи. Ночная выкладка…») и про касания не сказал ничего, так что оркестратору пришлось повторять сообщение дословно в 17:02:21. То есть содержимое steered-сообщения не попало ни в контекст нового хода, ни в durable-очередь. Владелец описал это как «зависает, приходится стопать и писать, и не видит последнее сообщение».
   Частота: 2 мёртвых хода на 922 steering за 7 суток (0.2%), оба в ЭТОЙ сессии и оба сегодня, при `ctx:53%` и в момент, когда в тот же ход уже вливался результат фонового задания. То есть общей поломки steering нет — ломается редкий сценарий, но ровно самый дорогой. Лечение не в отказе от steering, а в долговечности: влитое сообщение обязано лежать в mailbox и переезжать в следующий ход, если текущий умер. Механизм уже есть — очередь #V-556 (`app/mailbox.py`), её надо распространить на steering, а не только на кнопку «после хода».
 - [ ] **Нет единого события приёмки, поэтому спор «какая модель лучше» решается памятью, а не числом.** Установлено #V-561 (12.09): сравнить модели по красным тестам НЕВОЗМОЖНО — в журнале в одну кучу попадают намеренно красные мутационные контроли, отсутствие браузера, таймауты инструментов и настоящие продуктовые падения, общего типа события нет. Из-за этого пришлось объявить сравнение неидентифицируемым, хотя данных за месяц много. Нужен один нормализованный факт приёмки с полями: `task_id`, модель ФАКТИЧЕСКОГО хода (а не `sessions.model` — он меняется внутри сессии), тип проверки (`product_test` / `mutation_expected_red` / `environment`), вердикт и замороженный знаменатель задач. Пока его нет, любые выводы о качестве моделей опираются на свежесть воспоминания: в том же замере Opus сделал 295 ходов за 10–12.09 против 34 у Astra, и именно эти дни владелец помнил как «Opus наговнокодил».
 - [ ] **Привязка задачи не встаёт при спавне роли `sub-orchestrator`, и мерж потом отбивается.** 12.09: `spawn_worker(name='bench-master', role='sub-orchestrator', task_id='V-558')` вернул `Task: #V-558 [new]` вместо `[in_progress]`, задача осталась без assignee, и `merge_worker` отказал с `task 'V-558' is not bound to session <id>`. Для ролей `worker` и `full-cycle` в тот же день привязка вставала нормально (#V-543, #V-546, #V-547, #V-555, #V-556). Обход применён: результат скопирован в main отдельным коммитом, воркер оставлен живым (он persistent и в RESEARCH DONE). Чинить в сторону «планируемый спавн связывает канонической задачей ДО доставки, независимо от роли» — сейчас это описано в модуле задач как гарантия, но для одной роли не выполняется.
 - [ ] **Подпроцессы MCP не наследовали выбор состояния — ПОЧИНЕНО `e86fc63f`, ждёт рестарта.** 08.09 живой процесс перевели на другую БД и другое хранилище задач переменными окружения, но `MCP_BASE_ENV` пробрасывал только PYTHONPATH, прокси и токен. Любой подпроцесс открывал дефолтную `data/orchestra.db` (непустая, `user_version=0`) и падал на стороже схемы `app/db.py:73` с текстом про офлайн-миграцию. Три дня это выглядело как отказ `codex_review` во всех проектах и как следствие ждущей миграции #V-545 — к ней отношения не имеет. Регрессия `tests/test_runtime_env_propagation.py`, мутация красит 2 из 3.
 - [ ] **Нет проверки, что дашборд вообще инициализируется.** 12.09 правка разметки кнопок (#V-556) сломала `initVoiceInput` (`insertBefore` на узле, переставшем быть прямым потомком) — и ошибка убивала весь скрипт чата, то есть «фронт не грузился». Тесты покрывали почтовый ящик и маршруты, но не факт, что страница ожила. Починено `de54f88d` устойчивым поиском опоры, однако сам пробел остался: нужна проверка «чат инициализировался без исключений».
 - [ ] **`merge_worker` в состоянии PENDING читается агентами как провал, потому что объяснение уходит в поле, которого рантайм не показывает.** 12.09 оркестратор портфеля отрапортовал «❌ merge worker failed» на мерже, который через секунды пришёл `SUCCEEDED`. Платформа ведёт себя правильно: `PENDING` + `completion.job_id` означает «принято, идёт в фоне, выполнится и разбудит», и с 05.09 (`b0f32897`) для этого случая формируется прямой текст «STILL PENDING — NOT a failure… Do not poll or call merge_worker again». Дефект в доставке этого текста: `mcp_tool_result` кладёт его в `content[].text`, а рядом отдаёт `structuredContent` с сырым результатом — и Claude-рантайм показывает агенту ИМЕННО структуру. Я сам за сегодня сделал больше десяти мержей и ни разу не увидел этой строки, только JSON с `operation_state: PENDING`. Отсюда и повторяющаяся ошибка: агент видит «не SUCCEEDED» и называет это провалом. Чинить надо в структуре, а не в тексте: нетерминальное состояние обязано читаться из самого объекта (например, явным полем вида «это не отказ, исход придёт фоновым событием»), иначе следующий агент прочитает так же. Комментарий в коде `app/mcp_stdio.py` про прошлый заход подтверждает, что правка формулировки уже делалась и проблему не сняла.
 - [x] **`merge_worker` отбивал 409 SESSION_IDENTITY_CHANGED в цикле, из которого нет выхода предписанным способом — ПОЧИНЕНО #V-575, ждёт рестарта владельца** (`.orchestra/tasks/V-575/report.md`). При расхождении спрашивается git: совпал с закреплённой веткой И HEAD → `sessions.branch` приводится в соответствие и мерж идёт; иначе отказ, называющий все три стороны и рабочий выход. `next_action` стал `INSPECT_WORKER_THEN_NEW_OPERATION`. Первопричина (обнуление `task_id` с уходом ветки в `adhoc-<ts>/<имя>`) НЕ чинилась и остаётся отдельной работой. Исходный разбор: Репорт seedon-orchestrator 15.09 (запись `20260915T101900...`, проект seedon): пять операций на одном готовом результате, из них три FAILED с одним и тем же текстом. Разобрал по коду: сравниваются ДВЕ ЗАПИСИ ПЛАТФОРМЫ, git не спрашивают вовсе — `app/routes/sessions.py:2054` сверяет `expected_branch` операции (`task-256/...`, закреплён при приёме) с `row_branch`, то есть колонкой `sessions.branch` (`adhoc-<ts>/...`). Предписанный `next_action` REFRESH_WORKER_THEN_NEW_OPERATION зовёт `worker_wip`, а тот ходит в `/api/sessions/{name}/wip` → `branch_wip_status`, который ТОЛЬКО читает git и ничего не пишет в `sessions.branch` (`app/routes/sessions.py:3113`). Обе стороны сравнения после «починки» те же — отказ воспроизводится побайтово, сколько ни повторяй. Побочный эффект: оркестратор со стороны подгоняет git под устаревшую строку БД (`git branch -f adhoc-...`), то есть чинит правильное состояние по неправильному. Второй слой: сверка ветки с РЕАЛЬНЫМ worktree (`app/routes/sessions.py:2158-2176`) выполняется только когда `expected_head` НЕ передан — аккуратный вызывающий получает менее согласованный путь, чем небрежный. Замер 15.09 по живой БД (`ORCHESTRA_DB_PATH` MainPID 1016880, read-only, 58 неархивных сессий): расхождений `sessions.branch` ↔ фактическая ветка worktree сейчас **ноль**, но это НЕ здоровье популяции — обе пострадавшие сессии seedon к моменту замера уже подогнали руками под запись БД. Предложенный репортёром детектор «`branch LIKE 'adhoc-%'` при наличии привязанной задачи» не находит ничего и находить не может: дефект обнуляет `task_id`. Рабочий признак — `branch LIKE 'adhoc-%' AND task_id=''`: таких сессий **10**, из них **7 в одном seedon** (`marketer`, `seo-cro`, `sales`, `designer`, `direct-research`, `accountant`, `demand-audit`), остальные в dnd-game-master, katya-work, comfy-image-pipeline. Каждая из них воспроизведёт тот же 409 при первом мерже с ожиданием task-ветки. Чинить в сторону «git — источник правды о ветке»: при расхождении спросить worktree, и если он совпал с закреплённой веткой и `expected_head`, привести `sessions.branch` в порядок и продолжить; иначе отказывать СИНХРОННО, называя, какая сторона из БД, а какая из git, и предлагая существующий инструмент ремонта.
 - [ ] **Красный на main, не связан с правками фронта: `tests/test_frontend.py::test_photo_batch_renders_as_compact_expandable_gallery`.** Проверено 17.09 на чистом main (без правок #V-584): падает так же, ошибка приходит из `playwright/_impl/_connection.py:559`. Остальные 129 браузерных тестов зелёные. При прогоне фронта не принимать за свою регрессию; чинить отдельно, начиная с того, что именно роняет соединение Playwright в этом тесте.
 - [ ] **`__pycache__` под `.orchestra/` не игнорируется: правило-исключение перебивает общий шаблон.** Проверено 17.09 самостоятельно: `git check-ignore -v .orchestra/tasks/V-583/__pycache__/probe.pyc` отвечает `.gitignore:26:!.orchestra/**`, то есть негативное правило для `.orchestra/**` сильнее `__pycache__/` из первой строки. Практическое следствие: любой скрипт под `.orchestra/`, который импортирует соседний модуль, оставляет неотслеженный каталог, а тот отбивает мерж воркера с `WORKER_DIRTY` — так на #V-583 сгорела целая операция и лишний ход воркера. Лечится одной строкой `.orchestra/**/__pycache__/` после 26-й; это общий конфиг, поэтому отдельным решением, а не внутри чужой задачи.
-- [ ] **Оба зашитых харнес-маршрута мертвы, и наш валидатор этого не видит.** Замер 16.09 (`.orchestra/tasks/V-581/probe.log`, две попытки на маршрут): `z-ai/glm-5.2:free` в живом каталоге OpenRouter отдаёт `tools=False` и `ctx=32768` против наших 256000, а `nvidia/nemotron-3-ultra-550b-a55b:free` вызывает инструмент, но ИГНОРИРУЕТ его результат — воркером быть не может. Корень: `validate_harness_model_spec` (`app/models.py:364-381`) проверяет НАШЕ статическое поле `supports_tools`, а не живые данные провайдера, поэтому протухание маршрута незаметно до сожжённого хода. Из 18 `:free` маршрутов с заявленным `tools` полный протокол (вызов → результат → ответ по результату) прошли 9: nemotron-3.5-lightning (1M), dots-3-note-preview (512k), ling-3.0-flash-sante, ling-3.0-flash-fin, nemotron-3-super-120b, cohere/north-mini-code, liquid/lfm-2.5-2.6b, gemma-4-26b и nex-n2.5-pro (последние два — со второй попытки). Отдельный класс: `thinkingmachines/inkling*` (1M) отдают 403 «only available on agentic harnesses» — нужна регистрация приложения, обычный ключ не пускают.
+- [x] **Оба зашитых харнес-маршрута мертвы, и наш валидатор этого не видит — ПОЧИНЕНО #V-582, ждёт рестарта владельца** (`.orchestra/tasks/V-582/report.md`). Харнес-маршруты убраны из `SELECTABLE_MODEL_SPECS` и приходят только из живого каталога; `validate_harness_model_spec` решает по записи провайдера (`live_catalog_entry`/`harness_capable` в `app/model_catalog.py`), а не по нашему `supported_parameters`. Проба стала инструментом — `scripts/probe_free_models.py`. ОСТАЛОСЬ ОТДЕЛЬНО: `thinkingmachines/inkling*:free` (1M) отдают 403 «only available on agentic harnesses» — нужна регистрация приложения в OpenRouter, обычный ключ не пускают. Замер 17.09 показал и второе: состав прошедших маршрутов переворачивается за сутки (nemotron-3-ultra 16.09 игнорировал результат инструмента, 17.09 прошёл за 4.5 с; nemotron-3.5-lightning наоборот), то есть разовая проба — снимок, а не приговор. Исходный разбор: **Оба зашитых харнес-маршрута мертвы, и наш валидатор этого не видит.** Замер 16.09 (`.orchestra/tasks/V-581/probe.log`, две попытки на маршрут): `z-ai/glm-5.2:free` в живом каталоге OpenRouter отдаёт `tools=False` и `ctx=32768` против наших 256000, а `nvidia/nemotron-3-ultra-550b-a55b:free` вызывает инструмент, но ИГНОРИРУЕТ его результат — воркером быть не может. Корень: `validate_harness_model_spec` (`app/models.py:364-381`) проверяет НАШЕ статическое поле `supports_tools`, а не живые данные провайдера, поэтому протухание маршрута незаметно до сожжённого хода. Из 18 `:free` маршрутов с заявленным `tools` полный протокол (вызов → результат → ответ по результату) прошли 9: nemotron-3.5-lightning (1M), dots-3-note-preview (512k), ling-3.0-flash-sante, ling-3.0-flash-fin, nemotron-3-super-120b, cohere/north-mini-code, liquid/lfm-2.5-2.6b, gemma-4-26b и nex-n2.5-pro (последние два — со второй попытки). Отдельный класс: `thinkingmachines/inkling*` (1M) отдают 403 «only available on agentic harnesses» — нужна регистрация приложения, обычный ключ не пускают.
 - [ ] **`merge_worker(task_outcome="continue")` — ловушка: прогон задачи остаётся открытым, а закрыть его нечем, если мержить больше нечего.** Репорт cog-second-brain-orchestrator 16.09 (воркер `balatro-vps`, task_run `ce47fdb1`, операции `0e7acb97` и `894b296c` обе FAILED). Механизм подтверждён по коду: у сессии допускается РОВНО ОДИН открытый `task_run` (`review_receipts`, `subject_kind='task_run'`, `status='requested'`), и `task_run_receipt_open` (`app/db.py:1331-1381`) отказывает `ValueError: open task run conflicts with current assignment provenance`, когда открывают прогон другой задачи. Закрывается прогон единственным путём — `_finish_task_run_for_task` (`app/tm.py:735-760`) на успешном мерже с `complete`. Отсюда тупик: после `continue` ветка воркера и main стоят на одном коммите, `merge_worker(complete)` отбивается `NO_COMMITS_MERGED` ДО закрытия прогона, а `switch_worker_branch` откатывается на той же ValueError, причём `force=True` не помогает — отказ приходит из слоя квитанций, а не из слоя веток. Штатного выхода нет; чужой оркестратор вышел через `send_message` с новым task_id и получил расщеплённое состояние: `get_worker_info` отдаёт старую задачу и старую ветку, `list_agents` показывает три задачи `in_progress`, коммиты новой задачи идут в ветку старой. Чинить одним из двух: либо `switch_worker_branch` закрывает предыдущий прогон как `superseded`, либо `complete` закрывает прогон и тогда, когда коммитов нет (пустой мерж — законный способ снять задачу с воркера). Обход, который работает уже сейчас и его стоит назвать в тексте отказа: дать воркеру доделать и закоммитить, тогда мерж с `complete` проходит и закрывает прогон.
 - [ ] **Astra недоступна нашему аккаунту, но остаётся маршрутом по умолчанию для сложных задач.** 16.09 спавн воркера на `gpt-6-astra` сжёг ход и умер до первой строки: провайдер ответил 400 `The 'gpt-6-astra' model is not supported when using Codex with a ChatGPT account` (дважды, затем `turn FAILED: error`). Задание до воркера не доехало вообще. При этом модуль model-routing объявляет Astra классом сложности, а каталог моделей её показывает — то есть платформа предлагает агенту модель, которой у аккаунта нет, и узнаётся это только сожжённым ходом. Смежное: два живых воркера (`bench-master`, `prompt-engineer`) сидят на этой же модели и при первом же сообщении получат то же самое. Чинить в сторону «каталог знает, что доступно аккаунту»: либо проверка при спавне с внятным отказом, либо снятие Astra из маршрутизации до выяснения. ПРИЧИНА УСТАНОВЛЕНА В ТОТ ЖЕ ДЕНЬ: подписка Codex отменена владельцем намеренно («чтобы за доллары потом оплатить»), и телеметрия провайдера показывает переход `plan_type` pro → free в 11:03 UTC 16.09; окно стало 30-дневным (43200 мин, сброс 16.10), Astra на free не поддерживается вовсе. То есть это не дефект каталога сам по себе, а отсутствие проверки «доступна ли модель этому плану»: узнаётся только сожжённым ходом. Масштаб free-окна для планирования: один ход Luna (8.03М входных токенов) дал 10% окна. Отдельно проверить, не то же ли это, что #520.
 - [ ] **ЖДЁТ РЕСТАРТА ВЛАДЕЛЬЦА — семь готовых правок и два мёртвых воркера (на 12.09.2026).** Всё смержено в main и проверено, но Python в живом процессе не меняется: (1) офлайн-миграция БД под #V-544, отдельная задача #V-545 с командами; (2) #V-543 утечка pidfd; (3) `bec4f378` отказ merge_worker на переименованиях; (4) #V-546 потолок полос sol=95; (5) #V-540 стабильный системный промпт; (6) `QUOTA_GATED_LANES=claude,sol` — 15.09 владелец дословно сказал «включай общий гейт снова на лимиты», `.env` поправлен, но живой процесс стартовал с пустым значением и до рестарта гейт остаётся снятым со всех полос; (7) #V-547 индикатор состояния гейта — до рестарта панель честно пишет «гейт: нет данных». Воркеры `fix-stuck-writer` и `fix-prompt-cache` висят `broken` («Codex thread already has an active writer») — их работа смержена, но сессии оживит только рестарт.
 - [ ] **Тест-гейт мержа гоняет тесты в ВЕТКЕ ВОРКЕРА, а исправление красноты лежит в main — ветка чинится только подтягиванием main.** 11.09: мерж #V-546 отбит трижды. Первые два раза — по чужим дефектам (запись «upper» в боевом хранилище задач; протёкший `QUOTA_GATED_LANES=` плюс снапшот маршрутов, отставший от `f5713f4d`). Я починил оба в main коммитом `52f7c97d` и повторил мерж — гейт выдал ТЕ ЖЕ 16 красных, потому что тестирует он ветку, где `tests/conftest.py` старый. Практический вывод: **когда гейт краснеет на чужом дефекте, чинить надо не только main — воркеру нужно отдельно подтянуть main к себе**, иначе цикл «починил → отбито → починил» повторяется. Стоит проверить, не должен ли гейт тестировать РЕЗУЛЬТАТ слияния, а не голую ветку: сейчас он отвечает на вопрос «зелена ли ветка», а решение принимается о том, «зелен ли main после мержа», и это разные вопросы.
 - [x] **Горячая правка `.env` для квоты в боевом процессе НЕ работала — ИСПРАВЛЕНО `fbc9e40d`, ждёт рестарта.** Ключ, чьё стартовое значение совпало со снимком файла, теперь принадлежит файлу (`_dotenv_owned_names`), внешний оверрайд по-прежнему держится. Заодно `a76cfe5e` убрал мерцание теста перечитки: две записи в один тик часов давали одинаковый mtime, и перечитка не срабатывала (~1 прогон из 15, воспроизведено и до правки). Исходный разбор: `quota_policy()` обещает в докстроке «including edits made to `.env` live», но `_live_quota_env` (`app/quota_gate.py:191`) отдаёт `_startup_quota_env[name]`, если оно не `None`, а systemd кладёт весь `.env` в окружение процесса (`EnvironmentFile=/home/kesha/orchestra/.env`). Пустая строка тоже «не None», поэтому она побеждает. Проверено 15.09 на рантайме: с `QUOTA_GATED_LANES=` в окружении политика даёт `[]` при `claude,sol` в файле; без переменной в окружении — `['claude','sol']`. Практический вывод: любая правка квотных `QUOTA_*` в `.env` вступает в силу только рестартом, а обещание горячего применения вводит в заблуждение. Чинить либо приоритетом (файл важнее унаследованного стартового значения для тех ключей, что пришли из этого же файла), либо честной докстрокой.
 - [ ] **Квотные переменные оператора надо гасить ДО импорта `app`, а не в фикстуре.** `app.quota_gate` читает `QUOTA_*` на уровне модуля (`HARD_STOP_PCT`, `_startup_quota_env`), поэтому `monkeypatch.delenv` внутри autouse-фикстуры опаздывает: модуль уже импортирован с чужим значением. Закрыто в `tests/conftest.py` (`52f7c97d`) списком на уровне модуля. Тот же класс ошибки, что `ORCHESTRA_TASK_PREFIX` (08.09) и `ORCHESTRA_TASK_REPOSITORY` (11.09) — **третий случай за неделю**: всё, что живой процесс получает из `.env` через `EnvironmentFile`, протекает в прогон тестов и в гейт мержа.
 - [x] **merge_worker падал «cannot derive target-relative merge paths» из-за детектора переименований git — ИСПРАВЛЕНО `bec4f378`, ждёт рестарта.** Репорт comfy-image-orchestrator-vps 11.09, три потерянные операции подряд, `waive_diff_budget` не помогал. Замер мой, на их живом worktree `task-56/voice-astra` (2402 файла, ~1900 изображений, 60 переименований): `git diff --name-only main...HEAD` — **37.0 с**, та же команда с `-c diff.renames=false` — **0.026 с**. Таймаут `_git` был 15 с (`app/merge_test_gate.py`), при превышении helper отдаёт `None`, и `merge_operations.py:864` печатает про поломку оракула — сообщение врёт и отправляет чинить не то. Фикс: `--no-renames` в запросе путей плюс таймаут 60 с; `--no-renames` ещё и точнее, потому что гейту нужны обе стороны переименования. Регрессия `test_renamed_file_reports_both_sides_so_the_gate_sees_the_removal`, мутацию ловит. **Остаётся несделанным:** текст ошибки по-прежнему не различает «git не смог» и «git не успел» — следующий такой отказ снова пошлёт агента чинить оракул.
 - [ ] **Красный на main, не связан с #V-546: `tests/test_merge_test_gate.py::test_browser_inventory_is_explicit`.** Проверил на чистом main через `git stash` — падает и без моих правок (`tests/test_merge_test_gate.py:629`). При прогоне гейта не принимать за свою регрессию. **15.09, V-575:** причина найдена — инвентарь ждёт 102 браузерных узла в `tests/test_frontend.py`, а их 104 с коммита `6a6c9e9b` (V-564, 13.09, «render send_chart results in dashboard»): два браузерных теста добавили, строку инвентаря не обновили. Чинится вписыванием 104 с пометкой откуда — ровно то, что сам тест и требует в тексте отказа.
 - [ ] **`tests/test_work_acceptance.py::test_failed_acceptance_still_blocks_new_work_without_review` красный на main из-за `python` на PATH.** Оракул в тесте задан буквально как `python -c "raise SystemExit(1)"`, а в рантайме `/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python` голого `python` на PATH нет — команда не стартует, приёмка выходит `inconclusive` вместо `failed`, и тест проверяет не то плечо, ради которого написан. Воспроизведено 15.09 на базовом `ce49eeba` в отдельном worktree. Чинить `sys.executable` вместо литерала.
 - [x] **P1. Картинка тяжелее 10 МБ не доходит в Telegram и роняет весь альбом — ПОЧИНЕНА в коде (#V-544, ветка `task-V-544/fix-tg-file-limits`), в живом процессе применится после рестарта владельцем И офлайн-миграции БД.** Вид вложения теперь выбирает `send_as_photo(name, size, as_document)` по расширению И размеру на всех трёх путях (пакетный, одиночный durable, легаси `send_file_to_tg`): свыше 10 485 760 байт картинка планируется документом и уезжает отдельной группой, лёгкие фото остаются альбомом. Детерминированный отказ провайдера (400/403) теперь состояние `FAILED` / `PROVIDER_REJECTED` с дословной причиной, а не `UNKNOWN`. Подробности и мутационная проверка — `.orchestra/tasks/V-544/report.md`.
 - [ ] **P1 (остаток от #V-544). `PHOTO_INVALID_DIMENSIONS` размером не ловится.** В живой БД такой отказ есть: `lesson-1-sample-contact.png`, 3.2 МБ, 25.08 — режет геометрия (у Telegram сумма сторон ≤ 10000 и отношение ≤ 20), а не байты. Сейчас такая картинка хотя бы падает терминально с причиной вместо `UNKNOWN`, но всё ещё не доходит. Починка — проверять размеры перед выбором `photo` (нужен ли ради этого Pillow в обязательных зависимостях — отдельный вопрос).
 - [ ] **#V-544 ждёт офлайн-миграции живой БД (действие владельца).** До неё заявленные в описаниях инструментов 2000 МБ не заработают: `CHECK(size_bytes <= 52428800)` отобьёт любую доставку крупнее 50 МБ, а `CHECK(state IN …)` — запись `FAILED`. Скрипт и порядок: `scripts/migrate_tg_file_limits_v544.py`, проверен на копии со старой схемой.
 - [x] **Потолок документа через локальный Bot API ИЗМЕРЕН (#V-544, 11.09.2026):** документ 209 715 200 байт ушёл `sendDocument`'ом на `localhost:8081` за 18.8 с, HTTP 200, `message_id=199221` (~11.2 МБ/с). То есть 200 МБ проходят; 2000 МБ не опровергнуты и не подтверждены, константа оставлена. Описания `send_file`/`send_files` теперь называют эти числа, чтобы агент не подставлял публичные 50 МБ. Сырой ответ — `.orchestra/tasks/V-544/control-run-200mb.txt`.
 - [x] **P1. Утечка pidfd — ПОЧИНЕНА в коде (#V-543, коммит `180a5a4f`), в живом процессе применится только после рестарта владельцем.** Найдены и закрыты три разрыва владения собственным fd: `_run_command_watch` не звал `_kill_proc` в `finally`; `_recv_pidfd` терял fd, если отмена приходила после получения SCM_RIGHTS; двойная отмена spawn оставляла процесс без владельца (общий `_await_owned_spawn`). Красное плечо доказано `tests/test_pidfd_leaks.py`: 7 из 9 сценариев давали ровно `delta=12` на 12 итераций, контроли (обычный bash, повторный cleanup) были зелёными и до фикса. Мутационную проверку провёл сам на смерженном main — снял `await _kill_proc(proc)` из command-watch, покраснели ровно 3 сценария (`match`, `repeat`, `cancel`), вернул — 9 passed. **Осталось незакрытым и намеренно не объявлено закрытым:** доля исторических 933 fd по конкретным путям не установлена; `restart_guard.open_verified_pidfd` счётным регрессом не покрыт; аварийное закрытие event loop и массовая отмена supervised-задач при завершении интерпретатора не воспроизводились. Изменение поведения: command-watch теперь чистит свою группу после каждой команды, как file/ssh/cron watchers.
   Исходные факты замера (нужны, если утечка вернётся другим путём): 1019 из 1024 fd занято, **933 — `anon_inode:[pidfd]`**, и все они мёртвые — проверил `Pid:` в `/proc/<pid>/fdinfo/<fd>` для 400 дескрипторов, 400 из 400 дали `Pid: -1`. Накопились за ~37.6 ч аптайма ≈ 25/час, но рост не равномерный: за контрольные 45 с не прибавилось ни одного, значит утечка привязана к событиям (спавн/убийство/мерж воркеров), а не к таймеру. Последствие — `merge_worker` падает `OSError [Errno 24] Too many open files` на снимке ветки. Обход применён репортёром: `prlimit --pid 2015748 --nofile=131072:524288` на живом процессе, запас при текущем темпе ~220 суток, рестарт обнулит и вернёт стену через ~40 ч. **Локализация не закончена:** обычный `asyncio.create_subprocess_exec` + `communicate()` НЕ течёт (проверил изолированной пробой на том же интерпретаторе, 3.12.3, watcher `PidfdChildWatcher`, 60 запусков — прирост 0), значит источник в одном из наших нестандартных путей: `_spawn_bg_process`/`_kill_proc` (`app/bg_jobs.py:170-256`), `harness.bash` (`app/harness/tools.py:119-195`), `restart_guard.open_verified_pidfd`. Ставить `LimitNOFILE` в юните — обезболивание, а не лечение, и требует владельца.
   **Известная нестабильность рядом:** `tests/test_harness_tools.py::test_t1_grep_perf_repo_tree` — перф-тест с порогом времени; под нагрузкой машины упал (набор шёл 42.8 с), в одиночку и на повторе прошёл (набор 21.3 с, 82 passed). К #V-543 отношения не имеет, но при красном прогоне не принимать за регрессию.
   **Вторая половина репорта ОПРОВЕРГНУТА:** «юнит объявляет 524288, а процесс живёт с 1024, вероятно стартовал не из юнита» — неверно. `LimitNOFILE` в юните не задан вообще, `systemctl show` печатает системные дефолты (`DefaultLimitNOFILE=524288`, `DefaultLimitNOFILESoft=1024`), и контрольная проверка другого юнита на этой машине даёт те же два числа. Различитель на будущее: сравнивать надо `LimitNOFILESoft`, а не `LimitNOFILE`, и проверять контрольным юнитом.
 - [ ] **P2. Бакет `anthropic_fable` собирается, но недостижим — Fable-воркеры гейтятся по чужому пулу** (`app/quota_gate.py:288`, аудит 01.09). `_model_target` отдаёт `"anthropic"` для любой claude-модели, поэтому ветки под `anthropic_fable` (309, 381) — мёртвый код, хотя телеметрия публикуется (`routes/system.py:791`). **Прямолинейный фикс ОТКАЧЕН 01.09 как регрессия:** живой `weekly_scoped` лимит Fable приходит с `resets_at: None`, поэтому бакет появился бы БЕЗ разбираемого окна — диагональ к нему не применилась бы вовсе, и Fable остался бы только под жёстким стопом 99%, то есть гейт стал бы слабее нынешнего. Чинить надо вместе с продюсером (`_provider_usage_snapshot`): пока у бакета нет `resets_at`, он не годится как основание допуска.
 - [ ] **`merge_worker` рапортует `SUCCEEDED` при мерже ветки В САМУ СЕБЯ и нулевом переносе коммитов** (katya-work, операция `ab606af9`). `commits_merged: 0`, `target_before == target_after`, при этом успех; работы в main нет. Причина цели: после оборванного switch базой осталась адхок-ветка (`_session_base_branch`, `app/routes/sessions.py:113`). Обход: `merge_worker(target="main")`. Приёмка: (1) цель == ветка воркера → отказ; (2) `commits_merged: 0` при неизменной цели не может быть успехом; (3) ложный успех ещё и ТРАТИТ привязку при `task_outcome=complete`.
 - [ ] **`switch_worker_branch` не атомарен: ветку переключает, привязку теряет** (katya-work, `russian-soul-luna`). Корень (`KeyError: 'stable_id'` из canonical CAS) закрыт аудитом 01.09, но САМА неатомарность остаётся: если шаг привязки падает по другой причине, сессия остаётся `task_id=''` + `needs_switch=1` и сама из тупика не выходит. Приёмка: инъекцией исключения в шаг привязки доказать, что сессия не остаётся в тупике.
diff --git a/app/model_catalog.py b/app/model_catalog.py
index 7adf3e442..cb2320cf0 100644
--- a/app/model_catalog.py
+++ b/app/model_catalog.py
@@ -83,69 +83,77 @@ def catalog_cache_payload() -> dict:
 
     try:
         data = json.loads(kv_get(CATALOG_KV_KEY, "{}"))
     except json.JSONDecodeError:
         data = {}
     except sqlite3.OperationalError:
         return {"fetched_at": None, "models": []}
     if not isinstance(data, dict):
         data = {}
     models = data.get("models")
     return {
         "fetched_at": data.get("fetched_at"),
         "models": models if isinstance(models, list) else [],
     }
 
 
 def cached_catalog() -> list[dict]:
     return catalog_cache_payload()["models"]
 
 
-def _cached_harness_eligible(model: dict) -> bool:
+def live_catalog_entry(model_id: str) -> dict | None:
+    """The provider's own record for a route — the source admission decides on."""
+    for entry in cached_catalog():
+        if entry.get("id") == model_id:
+            return entry
+    return None
+
+
+def harness_capable(model: dict) -> bool:
     """Read both the current cache schema and the pre-hardening schema safely.
 
     Old rows did not persist output modalities or the eligibility bit. They came from
     OpenRouter's text catalog, so exact `:free` + advertised tools is the conservative
     migration; optional request parameters stay disabled until a fresh catalog arrives.
     """
     if "harness_eligible" in model:
         return model.get("harness_eligible") is True
     return (
         str(model.get("id") or "").endswith(":free")
         and model.get("supports_tools") is True
         and "text" in (model.get("input_modalities") or [])
     )
 
 
 def apply_model_catalog() -> int:
     """Register every cached catalog model into the shared registry.
 
     Idempotent: already-registered ids are refreshed in place, including live
     capabilities/context for manifest fallbacks. Returns registrations this run;
     per-model failures are counted in `_LAST_APPLY_STATS['dropped']`.
     """
     from app.models import MODEL_SPECS, ModelSpec, SELECTABLE_MODEL_SPECS, register_model
 
     manifest = {spec.id: spec for spec in SELECTABLE_MODEL_SPECS}
     eligible = {
         norm["id"]: norm for norm in cached_catalog()
-        if _cached_harness_eligible(norm)
+        if harness_capable(norm)
     }
     registered = dropped = 0
     for norm in eligible.values():
         declared = manifest.get(norm["id"])
         spec = ModelSpec(
             id=norm["id"],
             name=norm["name"],
             runtime="harness",
             provider="openrouter",
             context_length=int(norm["context_length"]),
             price_input=float(norm["price_prompt"]),
             price_output=float(norm["price_completion"]),
             supported_parameters=tuple(
                 norm.get("supported_parameters")
                 or (declared.supported_parameters if declared else ("tools",))
             ),
             default_dashboard=(declared.default_dashboard if declared else False),
             default_agents=(declared.default_agents if declared else False),
             available=bool(norm.get("available", True)),
         )
@@ -179,41 +187,41 @@ async def refresh_catalog() -> dict:
             resp = await client.get(OPENROUTER_MODELS_URL, headers=headers)
             resp.raise_for_status()
             data = resp.json()
     except Exception as exc:
         logger.warning("OpenRouter catalog fetch failed: %s", exc)
         raise ValueError(f"catalog fetch failed: {exc}") from exc
 
     normalized: list[dict] = []
     seen: set[str] = set()
     for raw in data.get("data") or []:
         entry = normalize_catalog_model(raw if isinstance(raw, dict) else {})
         if entry is not None and entry["id"] not in seen:
             seen.add(entry["id"])
             normalized.append(entry)
 
     # Keep structurally valid routes that vanished as unavailable compatibility records.
     # A persisted session can then open and switch away, while admission rejects new work.
     active_ids = {entry["id"] for entry in normalized}
     retained_stale: list[dict] = []
     for old in cached_catalog():
-        if old.get("id") in active_ids or not _cached_harness_eligible(old):
+        if old.get("id") in active_ids or not harness_capable(old):
             continue
         stale = dict(old)
         stale["available"] = False
         retained_stale.append(stale)
 
     from app.db import kv_set
 
     kv_set(CATALOG_KV_KEY, json.dumps({
         "fetched_at": time.time(), "models": normalized + retained_stale,
     }))
     registered = apply_model_catalog()
     result = {
         "fetched": len(normalized),
         "eligible": _LAST_APPLY_STATS["eligible"],
         "available": _LAST_APPLY_STATS["available"],
         "registered": registered,
         "retained_stale": _LAST_APPLY_STATS["retained_stale"],
         "dropped": _LAST_APPLY_STATS["dropped"],
     }
     logger.info(
diff --git a/app/models.py b/app/models.py
index 4ecc09de2..001805e88 100644
--- a/app/models.py
+++ b/app/models.py
@@ -104,61 +104,44 @@ SELECTABLE_MODEL_SPECS: tuple[ModelSpec, ...] = (
         runtime="codex", provider="openai", context_length=258400,
     ),
     ModelSpec(
         id="gpt-5.6-luna", name="GPT-5.6 Luna",
         runtime="codex", provider="openai", context_length=258400,
     ),
     ModelSpec(
         id="gpt-5.5", name="GPT-5.5",
         runtime="codex", provider="openai", context_length=258400,
     ),
     # Reported by the Grok runtime itself (initialize + session/new agree). The bundled
     # vendor README disagrees with the runtime on other numbers, so the runtime wins.
     ModelSpec(
         id="grok-4.6", name="Grok 4.6",
         runtime="grok", provider="x-ai", context_length=500000,
     ),
     ModelSpec(
         id="grok-4.5", name="Grok 4.5",
         runtime="grok", provider="x-ai", context_length=500000,
     ),
-    # OpenRouter through Orchestra's own harness. Admission is exact and fail-closed:
-    # only `:free` routes that advertise tools may reach the HTTP client. These two
-    # entries are offline fallbacks for a cold catalog; they start disabled until a user
-    # intentionally qualifies and enables them. Request-count quota lives outside prices.
-    ModelSpec(
-        id="z-ai/glm-5.2:free", name="GLM 5.2 (free)",
-        runtime="harness", provider="openrouter", context_length=256000,
-        price_input=0.0, price_output=0.0,
-        supported_parameters=(
-            "reasoning", "reasoning_effort", "response_format", "structured_outputs",
-            "tool_choice", "tools",
-        ),
-        default_dashboard=False, default_agents=False,
-    ),
-    ModelSpec(
-        id="nvidia/nemotron-3-ultra-550b-a55b:free", name="Nemotron 3 Ultra (free)",
-        runtime="harness", provider="openrouter", context_length=1000000,
-        price_input=0.0, price_output=0.0,
-        supported_parameters=("reasoning", "reasoning_effort", "tool_choice", "tools"),
-        default_dashboard=False, default_agents=False,
-    ),
+    # Harness (OpenRouter) routes are NOT declared here: they come from the live
+    # provider catalog via app.model_catalog. A hardcoded copy of someone else's
+    # catalog goes stale silently — both entries kept here until 17.09.2026 were
+    # dead (#V-581), and our record still claimed tools and a 256k window.
 )
 
 # Derived views. They stay plain dicts with the same contract because callers
 # import them by name and fetch_models_from_proxy() mutates them in place;
 # _rebuild_derived_views() below is the only writer at import time.
 MODELS: dict[str, str] = {}
 CONTEXT_LIMITS: dict[str, int] = {}
 
 # Short aliases let agents use "opus", "sonnet" etc. in spawn_worker without
 # knowing the exact versioned model ID — reduces prompt brittleness on model upgrades
 ALIASES = {
     "fable": "claude-fable-5-1[1m]",
     "fable5": "claude-fable-5-1[1m]",
     "fable5.1": "claude-fable-5-1[1m]",
     "claude-fable-5-1": "claude-fable-5-1[1m]",
     "claude-fable-5-1-1m": "claude-fable-5-1[1m]",
     "mythos": "claude-fable-5-1[1m]",
     "opus": "claude-opus-5[1m]",
     "opus5": "claude-opus-5[1m]",
     "claude-opus-5": "claude-opus-5[1m]",
@@ -347,54 +330,68 @@ def register_model(spec: ModelSpec, *, replace: bool = False) -> None:
     get_runtime(spec.runtime)
     if spec.runtime not in PROVIDER_METADATA:
         raise ValueError(
             f"model '{spec.id}' uses runtime '{spec.runtime}' without provider metadata"
         )
     if spec.provider not in PROVIDER_METADATA[spec.runtime].model_providers:
         allowed = ", ".join(PROVIDER_METADATA[spec.runtime].model_providers) or "(none)"
         raise ValueError(
             f"model '{spec.id}' provider '{spec.provider}' is not registered for "
             f"runtime '{spec.runtime}'; registered providers: {allowed}"
         )
     if spec.id in MODEL_SPECS and not replace:
         raise ValueError(f"model '{spec.id}' is already registered")
     MODEL_SPECS[spec.id] = spec
     _apply_derived_views(spec)
 
 
 def validate_harness_model_spec(spec: ModelSpec) -> None:
     """Production admission for Orchestra's OpenRouter runtime.
 
+    Decided on the provider's own catalog record, never on our copy of it: a route that
+    lost tool support or vanished upstream must be refused even while our spec still
+    claims otherwise, or the staleness is only discovered by a burnt worker turn (#V-581).
     Zero token prices are not proof of a free route: request/song/image prices can live
     outside those fields. The `:free` suffix is the provider's explicit routing contract.
     Tool support is mandatory because Harness is an agent runtime, not a chat wrapper.
     """
     if spec.runtime != "harness":
         raise ValueError(f"model '{spec.id}' is not a harness model")
     if not spec.id.endswith(":free"):
         raise ValueError(
             f"harness model '{spec.id}' is not an exact :free route; "
             "unsuffixed previews and paid routes are blocked"
         )
-    if "tools" not in spec.supported_parameters:
-        raise ValueError(f"harness model '{spec.id}' does not advertise tool support")
-    if not spec.available:
+    from app.model_catalog import harness_capable, live_catalog_entry
+
+    live = live_catalog_entry(spec.id)
+    if live is None:
+        raise ValueError(
+            f"harness model '{spec.id}' is not in the OpenRouter catalog we fetched; "
+            "refresh the Models catalog screen"
+        )
+    if not harness_capable(live):
+        raise ValueError(
+            f"harness model '{spec.id}' does not advertise tool support "
+            "in OpenRouter's own catalog"
+        )
+    if not live.get("available", True):
         raise ValueError(f"harness model '{spec.id}' is no longer available on OpenRouter")
 
 
 def unregister_model(model_id: str) -> None:
     MODEL_SPECS.pop(model_id, None)
     MODELS.pop(model_id, None)
     CONTEXT_LIMITS.pop(model_id, None)
     BACKENDS.pop(model_id, None)
     MODEL_PROVIDERS.pop(model_id, None)
     TOKEN_PRICES.pop(model_id, None)
 
 
 def get_model_spec(model_id: str) -> ModelSpec:
     """Return an explicit selectable or persisted-session compatibility route."""
     if model_id in MODEL_SPECS:
         return MODEL_SPECS[model_id]
     if model_id in COMPAT_MODEL_SPECS:
         return COMPAT_MODEL_SPECS[model_id]
     registered = ", ".join(sorted(MODEL_SPECS)) or "(none)"
     compatibility = ", ".join(sorted(COMPAT_MODEL_SPECS))
diff --git a/scripts/probe_free_models.py b/scripts/probe_free_models.py
new file mode 100644
index 000000000..956e43994
--- /dev/null
+++ b/scripts/probe_free_models.py
@@ -0,0 +1,226 @@
+#!/usr/bin/env python3
+"""Probe OpenRouter `:free` routes for real tool-protocol capability (#V-581, #V-582).
+
+What the catalog advertises and what a route actually does are different things. A route
+passes here only if it walks the WHOLE protocol Orchestra's harness needs: call the tool,
+pass a sane argument, then answer FROM the tool's result. A model that calls the tool and
+then ignores what came back is a failure — that is exactly how
+`nvidia/nemotron-3-ultra-550b-a55b:free` was dead while advertising tools.
+
+Spend is bounded before the first call: `--requests-per-route` (default 2, the protocol
+minimum) and `--budget-seconds`. Routes left unprobed when the budget runs out are
+reported as `not_probed`, never silently dropped.
+
+    python scripts/probe_free_models.py --out probe.json
+    python scripts/probe_free_models.py --model cohere/north-mini-code:free
+"""
+
+from __future__ import annotations
+
+import argparse
+import json
+import os
+import sys
+import time
+import urllib.error
+import urllib.request
+
+API = "https://openrouter.ai/api/v1"
+MARKER = 4242  # the tool's answer; the final text must contain it
+TOOLS = [{
+    "type": "function",
+    "function": {
+        "name": "line_count",
+        "description": "Return the number of lines in a repository file.",
+        "parameters": {
+            "type": "object",
+            "properties": {"path": {"type": "string", "description": "Repo-relative path"}},
+            "required": ["path"],
+        },
+    },
+}]
+ASK = ("Use the line_count tool for the file app/quota_gate.py, then reply with the "
+       "number it returned and nothing else.")
+
+
+def _api_key() -> str:
+    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_KEY", "")
+    if not key:
+        raise SystemExit("no API key: set OPENROUTER_API_KEY (or OPENROUTER_KEY)")
+    return key
+
+
+def _post(key: str, model: str, messages: list, timeout: int) -> tuple[int, dict, float]:
+    body = json.dumps({"model": model, "messages": messages, "tools": TOOLS,
+                       "tool_choice": "auto", "max_tokens": 700}).encode()
+    req = urllib.request.Request(
+        f"{API}/chat/completions", data=body,
+        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
+    )
+    started = time.time()
+    try:
+        with urllib.request.urlopen(req, timeout=timeout) as resp:
+            return resp.status, json.loads(resp.read()), time.time() - started
+    except urllib.error.HTTPError as error:
+        raw = error.read().decode("utf-8", "replace")[:400]
+        try:
+            payload = json.loads(raw)
+        except ValueError:
+            payload = {"error": {"message": raw}}
+        return error.code, payload, time.time() - started
+    except Exception as error:  # a timeout or a dropped connection is also a result
+        return 0, {"error": {"message": f"{type(error).__name__}: {error}"}}, time.time() - started
+
+
+def _error_text(payload: dict) -> str:
+    return str((payload.get("error") or {}).get("message", ""))[:200]
+
+
+def probe(key: str, model: str, *, timeout: int, max_requests: int) -> dict:
+    """Run the tool protocol against one route and classify the outcome."""
+    out = {"model": model, "status": "", "seconds": 0.0, "requests": 0,
+           "tool_call": False, "argument_ok": False, "used_result": False, "detail": ""}
+    messages = [{"role": "user", "content": ASK}]
+    spent = 0.0
+
+    code, data, took = _post(key, model, messages, timeout)
+    out["requests"] += 1
+    spent += took
+    while code == 429 and out["requests"] < max_requests - 1:
+        time.sleep(20)
+        code, data, took = _post(key, model, messages, timeout)
+        out["requests"] += 1
+        spent += took
+    out["seconds"] = round(spent, 1)
+    if code != 200:
+        out["status"] = "rate_limited" if code == 429 else (
+            "timeout" if code == 0 else f"http_{code}"
+        )
+        out["detail"] = _error_text(data)
+        return out
+
+    message = ((data.get("choices") or [{}])[0].get("message") or {})
+    calls = message.get("tool_calls") or []
+    if not calls:
+        out["status"] = "no_tool_call"
+        out["detail"] = str(message.get("content", ""))[:200]
+        return out
+    out["tool_call"] = True
+    function = calls[0].get("function") or {}
+    try:
+        args = json.loads(function.get("arguments") or "{}")
+    except ValueError:
+        args = {}
+    out["argument_ok"] = (
+        function.get("name") == "line_count" and "quota_gate" in str(args.get("path", ""))
+    )
+
+    if out["requests"] >= max_requests:
+        out["status"] = "budget_exhausted"
+        out["detail"] = f"tool call made, no request left for round 2 (max {max_requests})"
+        return out
+
+    messages += [
+        {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls},
+        {"role": "tool", "tool_call_id": calls[0].get("id", "call_1"),
+         "name": "line_count", "content": str(MARKER)},
+    ]
+    code, data, took = _post(key, model, messages, timeout)
+    out["requests"] += 1
+    spent += took
+    out["seconds"] = round(spent, 1)
+    if code != 200:
+        out["status"] = "rate_limited" if code == 429 else (
+            "timeout" if code == 0 else f"http_{code}"
+        )
+        out["detail"] = _error_text(data)
+        return out
+
+    text = str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
+    out["used_result"] = str(MARKER) in text
+    out["detail"] = text.strip().replace("\n", " ")[:200]
+    if not out["used_result"]:
+        out["status"] = "result_ignored"
+    elif not out["argument_ok"]:
+        out["status"] = "wrong_argument"
+    else:
+        out["status"] = "ok"
+    return out
+
+
+def free_tool_routes(timeout: int) -> list[dict]:
+    """Live catalog, narrowed to exact `:free` routes that advertise tools."""
+    with urllib.request.urlopen(f"{API}/models", timeout=timeout) as resp:
+        catalog = json.loads(resp.read())["data"]
+    routes = [entry for entry in catalog
+              if str(entry.get("id", "")).endswith(":free")
+              and "tools" in (entry.get("supported_parameters") or [])]
+    routes.sort(key=lambda entry: -(entry.get("context_length") or 0))
+    return routes
+
+
+def main(argv: list[str] | None = None) -> int:
+    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
+    parser.add_argument("--out", help="write the JSON report here instead of stdout")
+    parser.add_argument("--model", action="append", default=[],
+                        help="probe only this route (repeatable)")
+    parser.add_argument("--limit", type=int, default=0, help="probe at most N routes")
+    parser.add_argument("--requests-per-route", type=int, default=2,
+                        help="hard per-route request ceiling; 2 is the protocol minimum")
+    parser.add_argument("--budget-seconds", type=float, default=1200.0,
+                        help="stop probing after this much wall time")
+    parser.add_argument("--timeout", type=int, default=90, help="per-request timeout")
+    args = parser.parse_args(argv)
+
+    if args.requests_per_route < 2:
+        parser.error("--requests-per-route must be at least 2: the protocol needs two calls")
+
+    key = _api_key()
+    started = time.time()
+    deadline = started + args.budget_seconds
+    catalog = free_tool_routes(args.timeout)
+    if args.model:
+        wanted = set(args.model)
+        known = {entry["id"]: entry for entry in catalog}
+        catalog = [known.get(mid, {"id": mid, "context_length": None}) for mid in wanted]
+    if args.limit:
+        catalog = catalog[:args.limit]
+
+    results = []
+    for entry in catalog:
+        if time.time() >= deadline:
+            results.append({"model": entry["id"], "status": "not_probed", "seconds": 0.0,
+                            "requests": 0, "tool_call": False, "argument_ok": False,
+                            "used_result": False, "detail": "time budget exhausted",
+                            "context_length": entry.get("context_length")})
+            continue
+        row = probe(key, entry["id"], timeout=args.timeout,
+                    max_requests=args.requests_per_route)
+        row["context_length"] = entry.get("context_length")
+        results.append(row)
+        print(f"{row['status']:<16} {row['model']:<50} {row['seconds']:>6}s "
+              f"req={row['requests']} call={row['tool_call']} arg={row['argument_ok']} "
+              f"used={row['used_result']} | {row['detail'][:100]}",
+              file=sys.stderr, flush=True)
+
+    report = {
+        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
+        "seconds": round(time.time() - started, 1),
+        "requests_per_route": args.requests_per_route,
+        "candidates": len(catalog),
+        "passed": [row["model"] for row in results if row["status"] == "ok"],
+        "results": results,
+    }
+    payload = json.dumps(report, ensure_ascii=False, indent=2)
+    if args.out:
+        with open(args.out, "w", encoding="utf-8") as handle:
+            handle.write(payload + "\n")
+        print(f"\nполный протокол прошли {len(report['passed'])} из {len(results)} "
+              f"→ {args.out}", file=sys.stderr)
+    else:
+        print(payload)
+    return 0 if report["passed"] else 1
+
+
+if __name__ == "__main__":
+    raise SystemExit(main())
diff --git a/tests/conftest.py b/tests/conftest.py
index 01bee474c..38e4c46e2 100644
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -385,20 +385,74 @@ def _isolated_git_task_owner(tmp_path, monkeypatch):
     from app.task_refs import new_task_prefix
     runtimes = {}
 
     def runtime():
         if task_runtime._ACTIVE is not None:
             return task_runtime._ACTIVE
         path = Path(db.DB_PATH).resolve()
         if path not in runtimes:
             root = tmp_path / f'git-tasks-{len(runtimes)}'
             subprocess.run(['git', 'init', '--initial-branch=main', str(root)], check=True, capture_output=True)
             subprocess.run(['git', '-C', str(root), 'config', 'user.name', 'Task Test'], check=True)
             subprocess.run(['git', '-C', str(root), 'config', 'user.email', 'test@example.invalid'], check=True)
             store = TaskStore(root, origin=new_task_prefix())
             store.initialize()
             runtimes[path] = task_runtime.TaskRuntime(store, path)
         runtimes[path].store.origin = new_task_prefix()
         return runtimes[path]
 
     monkeypatch.setattr(tm, 'active_runtime', runtime)
     monkeypatch.setattr(task_runtime, 'active_runtime', runtime)
+
+
+@pytest.fixture
+def live_harness_route():
+    """Substitute OpenRouter's live catalog for one route and register it.
+
+    Harness admission decides on the provider's record, so a test that needs a usable
+    (or deliberately stale) harness model seeds that record instead of a ModelSpec.
+    """
+    import json as _json
+
+    seeded: list[str] = []
+
+    def seed(model_id, *, tools=True, available=True, context_length=128000,
+             parameters=None):
+        from app.db import init_db, kv_set
+        from app.model_catalog import (
+            CATALOG_KV_KEY, apply_model_catalog, cached_catalog,
+        )
+
+        init_db()
+
+        params = sorted(parameters) if parameters is not None else (
+            ["tool_choice", "tools"] if tools else ["temperature"]
+        )
+        supports_tools = "tools" in params
+        entry = {
+            "id": model_id,
+            "name": model_id,
+            "context_length": context_length,
+            "price_prompt": 0.0,
+            "price_completion": 0.0,
+            "input_modalities": ["text"],
+            "output_modalities": ["text"],
+            "supports_tools": supports_tools,
+            "supported_parameters": params,
+            "is_free": model_id.endswith(":free"),
+            "harness_eligible": supports_tools and model_id.endswith(":free"),
+            "available": available,
+        }
+        models = [row for row in cached_catalog() if row.get("id") != model_id]
+        kv_set(CATALOG_KV_KEY, _json.dumps({
+            "fetched_at": 1726500000.0, "models": models + [entry],
+        }))
+        apply_model_catalog()
+        seeded.append(model_id)
+        return entry
+
+    yield seed
+
+    from app.models import unregister_model
+
+    for model_id in seeded:
+        unregister_model(model_id)
diff --git a/tests/test_harness_inject.py b/tests/test_harness_inject.py
index 37b8915c6..404658823 100644
--- a/tests/test_harness_inject.py
+++ b/tests/test_harness_inject.py
@@ -21,59 +21,63 @@ def test_runtime_declares_mid_turn_inject():
 
 
 def test_send_during_active_turn_queues_instead_of_raising():
     b = HarnessBackend(model="nvidia/nemotron-3-ultra-550b-a55b:free", cwd="/tmp")
     b._llm = object()          # connect() not needed: send() only checks it is set
     b._turn_active = True
 
     asyncio.run(b.send("stop what you are doing, the spec changed"))
 
     assert b._injected == ["stop what you are doing, the spec changed"]
 
 
 def test_drain_hands_over_once_and_forgets():
     b = HarnessBackend(model="nvidia/nemotron-3-ultra-550b-a55b:free", cwd="/tmp")
     b._injected = ["first", "second"]
 
     assert b._drain_injected() == ["first", "second"]
     assert b._drain_injected() == []      # a second round must not replay them
 
 
-def test_retarget_model_keeps_history_and_session_store():
+def test_retarget_model_keeps_history_and_session_store(live_harness_route):
+    live_harness_route("vendor/from:free")
+    live_harness_route(
+        "vendor/to:free", parameters=["structured_outputs", "tool_choice", "tools"],
+    )
     b = HarnessBackend(
-        model="nvidia/nemotron-3-ultra-550b-a55b:free",
+        model="vendor/from:free",
         cwd="/tmp",
         resume_session_id="native-harness-session",
     )
     b._llm = OpenRouterClient(
         api_key="test",
-        model="nvidia/nemotron-3-ultra-550b-a55b:free",
+        model="vendor/from:free",
         supported_parameters=("tools", "tool_choice", "reasoning", "reasoning_effort"),
     )
     b._history = [{"role": "user", "content": "keep me"}]
     store = object()
     b._store = store
 
-    b.retarget_model("z-ai/glm-5.2:free")
+    b.retarget_model("vendor/to:free")
 
-    assert b.model == "z-ai/glm-5.2:free"
-    assert b._llm.model == "z-ai/glm-5.2:free"
+    assert b.model == "vendor/to:free"
+    assert b._llm.model == "vendor/to:free"
     assert "structured_outputs" in b._llm.supported_parameters
     assert b._history == [{"role": "user", "content": "keep me"}]
     assert b._store is store
 
 
 @pytest.mark.asyncio
 async def test_injected_message_enters_history_before_the_next_round():
     """The loop appends steering as a user message at the TOP of a round — after the
     previous round's tool results are already in place, so the request stays well-formed."""
     history: list[dict] = []
     rounds: list[list[dict]] = []
     queue = [["the spec changed: keep claude models too"]]
 
     loop = AgentLoop(
         llm=None, mcp=None, cwd="/tmp", history=history, tool_schemas=[],
         max_context=100000, drain_injected=lambda: queue.pop(0) if queue else [],
     )
 
     async def fake_round(assistant_msg):
         rounds.append(list(history))          # snapshot of what the model would have seen
diff --git a/tests/test_model_catalog.py b/tests/test_model_catalog.py
index c026a39c9..9235a2f22 100644
--- a/tests/test_model_catalog.py
+++ b/tests/test_model_catalog.py
@@ -233,20 +233,58 @@ async def test_t2_refresh_retains_vanished_route_for_resume_but_marks_it_unavail
             pass
 
         async def __aenter__(self):
             return self
 
         async def __aexit__(self, *args):
             return False
 
         async def get(self, url, headers=None):
             return Response()
 
     catalog = _catalog_module()
     _seed_cache()
     monkeypatch.setattr(catalog.httpx, "AsyncClient", Client)
 
     result = await catalog.refresh_catalog()
 
     cached = catalog.cached_catalog()
     assert result["retained_stale"] == 1
     assert cached == [{**NORMALIZED, "available": False}]
+
+
+def test_t2_admission_refuses_route_the_live_catalog_no_longer_backs():
+    """#V-582: our own record is not evidence — the provider's catalog decides.
+
+    Both hardcoded harness routes were dead while our spec still claimed tools, and
+    nothing noticed until a worker burned a turn on them.
+    """
+    import app.models as registry
+
+    stale_spec = registry.ModelSpec(
+        id="vendor/model-x:free", name="Vendor: Model X", runtime="harness",
+        provider="openrouter", context_length=128000,
+        price_input=0.0, price_output=0.0,
+        supported_parameters=("tool_choice", "tools"),
+    )
+
+    db.kv_set(CATALOG_KV_KEY, json.dumps({"fetched_at": 1726500000.0, "models": [{
+        **NORMALIZED,
+        "supports_tools": False,
+        "supported_parameters": ["temperature"],
+        "harness_eligible": False,
+    }]}))
+    with pytest.raises(ValueError, match="tool support"):
+        registry.validate_harness_model_spec(stale_spec)
+
+    db.kv_set(CATALOG_KV_KEY, json.dumps({"fetched_at": 1726500000.0, "models": []}))
+    with pytest.raises(ValueError, match="not in the OpenRouter catalog"):
+        registry.validate_harness_model_spec(stale_spec)
+
+
+def test_t2_admission_passes_route_the_live_catalog_still_backs():
+    import app.models as registry
+
+    _seed_cache()
+    assert _catalog_module().apply_model_catalog() == 1
+
+    registry.validate_harness_model_spec(registry.MODEL_SPECS["vendor/model-x:free"])
diff --git a/tests/test_model_flags.py b/tests/test_model_flags.py
index 37d9d52c6..4c2707a94 100644
--- a/tests/test_model_flags.py
+++ b/tests/test_model_flags.py
@@ -32,47 +32,40 @@ def _registry_snapshot():
         d.update(snap[n])
 
 
 
 def test_t1_kv_set_and_delete_roundtrip():
     db.kv_set("t1-key", "v1")
     assert db.kv_get("t1-key") == "v1"
     db.kv_set("t1-key", "v2")
     assert db.kv_get("t1-key") == "v2"
     db.kv_delete("t1-key")
     assert db.kv_get("t1-key", "gone") == "gone"
 
 
 def test_t1_manifest_models_default_to_visible_and_allowed():
     assert registry.get_model_flags("claude-haiku-4-5") == {
         "dashboard": True,
         "agents": True,
     }
 
 
-def test_t1_manifest_harness_models_start_fail_closed():
-    assert registry.get_model_flags("z-ai/glm-5.2:free") == {
-        "dashboard": False,
-        "agents": False,
-    }
-
-
 def test_t1_registered_catalog_model_defaults_to_hidden_and_forbidden():
     from app.models import ModelSpec
 
     spec = ModelSpec(
         id="test/vendor-x:free", name="Vendor X", runtime="harness",
         provider="openrouter", context_length=128000,
         price_input=0.0, price_output=0.0, supported_parameters=("tools",),
     )
     registry.register_model(spec)
     try:
         assert registry.get_model_flags("test/vendor-x:free") == {
             "dashboard": False,
             "agents": False,
         }
     finally:
         registry.unregister_model("test/vendor-x:free")
 
 
 def test_t1_set_flags_roundtrip_and_unknown_rejected():
     with pytest.raises(ValueError):
diff --git a/tests/test_model_gates.py b/tests/test_model_gates.py
index f24842051..0b631ae83 100644
--- a/tests/test_model_gates.py
+++ b/tests/test_model_gates.py
@@ -1,69 +1,63 @@
 """#366 T3 — enforcement of the two availability levels.
 
 
 dashboard flag → what the dashboard shows (/api/models) and what user actions accept;
 agents flag  → what agents may use (spawn prompt block, worker spawn, MCP change-model).
 Internal routes (codex_review model resolution) are deliberately NOT gated.
 """
 
 import pytest
 
 
 @pytest.fixture(autouse=True)
 def _init_db():
     from app.db import init_db
 
     init_db()
 
 import app.models as registry
-from app.models import ModelSpec
 
 
 @pytest.fixture(autouse=True)
 def _registry_snapshot():
     """Registry dicts are module-global and mutated in place: hand them back to
     the next test exactly as received (kv state is per-test via conftest DB)."""
     import copy
 
     import app.models as registry
 
     names = ("MODELS", "BACKENDS", "CONTEXT_LIMITS", "MODEL_PROVIDERS",
              "TOKEN_PRICES", "MODEL_SPECS", "ALIASES")
     snap = {n: copy.deepcopy(getattr(registry, n)) for n in names}
     yield
     for n in names:
         d = getattr(registry, n)
         d.clear()
         d.update(snap[n])
 
 
 
 @pytest.fixture()
-def vendor_model():
-    spec = ModelSpec(
-        id="test/vendor-x:free", name="Vendor X", runtime="harness",
-        provider="openrouter", context_length=128000,
-        price_input=0.0, price_output=0.0, supported_parameters=("tools",),
-    )
-    registry.register_model(spec)
-    yield spec
+def vendor_model(live_harness_route):
+    live_harness_route("test/vendor-x:free")
+    yield registry.get_model_spec("test/vendor-x:free")
     registry.unregister_model("test/vendor-x:free")
 
 
 def test_t3_api_models_hides_dashboard_off(vendor_model, monkeypatch):
     from fastapi.testclient import TestClient
 
     registry.set_model_flags("test/vendor-x:free", dashboard=False)
     from app.main import app, manager
 
     manager.sessions.clear()
     with TestClient(app) as client:
         ids = {m["id"] for m in client.get("/api/models").json()["models"]}
     assert "test/vendor-x:free" not in ids
     assert "claude-haiku-4-5" in ids
 
     registry.set_model_flags("test/vendor-x:free", dashboard=True)
     with TestClient(app) as client:
         ids = {m["id"] for m in client.get("/api/models").json()["models"]}
     assert "test/vendor-x:free" in ids
 
diff --git a/tests/test_probe_free_models.py b/tests/test_probe_free_models.py
new file mode 100644
index 000000000..43c3ee349
--- /dev/null
+++ b/tests/test_probe_free_models.py
@@ -0,0 +1,93 @@
+"""#V-582 — the probe's verdict, with no network involved.
+
+The whole point of the tool is that advertising tools is not passing: a route that calls
+the tool and then answers without its result must be classified as a failure. That is the
+exact defect that kept `nvidia/nemotron-3-ultra-550b-a55b:free` in our catalog.
+"""
+
+import json
+
+from scripts import probe_free_models as probe_tool
+
+TOOL_CALL = {
+    "id": "call_1",
+    "function": {"name": "line_count", "arguments": json.dumps({"path": "app/quota_gate.py"})},
+}
+
+
+def _responses(monkeypatch, *rounds):
+    calls = []
+
+    def fake_post(key, model, messages, timeout):
+        calls.append(messages)
+        return rounds[len(calls) - 1]
+
+    monkeypatch.setattr(probe_tool, "_post", fake_post)
+    return calls
+
+
+def test_route_answering_from_the_tool_result_passes(monkeypatch):
+    _responses(
+        monkeypatch,
+        (200, {"choices": [{"message": {"tool_calls": [TOOL_CALL]}}]}, 1.0),
+        (200, {"choices": [{"message": {"content": "4242"}}]}, 0.5),
+    )
+
+    row = probe_tool.probe("k", "vendor/good:free", timeout=10, max_requests=2)
+
+    assert row["status"] == "ok"
+    assert (row["tool_call"], row["argument_ok"], row["used_result"]) == (True, True, True)
+    assert row["requests"] == 2
+    assert row["seconds"] == 1.5
+
+
+def test_route_ignoring_the_tool_result_fails(monkeypatch):
+    _responses(
+        monkeypatch,
+        (200, {"choices": [{"message": {"tool_calls": [TOOL_CALL]}}]}, 1.0),
+        (200, {"choices": [{"message": {"content": "I cannot read files."}}]}, 0.5),
+    )
+
+    row = probe_tool.probe("k", "vendor/ignores:free", timeout=10, max_requests=2)
+
+    assert row["status"] == "result_ignored"
+    assert row["tool_call"] is True and row["used_result"] is False
+
+
+def test_route_never_calling_the_tool_fails_after_one_request(monkeypatch):
+    _responses(
+        monkeypatch,
+        (200, {"choices": [{"message": {"content": "sure, 12 lines"}}]}, 0.3),
+    )
+
+    row = probe_tool.probe("k", "vendor/chat:free", timeout=10, max_requests=2)
+
+    assert row["status"] == "no_tool_call"
+    assert row["requests"] == 1
+
+
+def test_provider_error_is_reported_apart_from_a_model_failure(monkeypatch):
+    _responses(
+        monkeypatch,
+        (429, {"error": {"message": "temporarily rate-limited upstream"}}, 0.2),
+    )
+
+    row = probe_tool.probe("k", "vendor/busy:free", timeout=10, max_requests=2)
+
+    assert row["status"] == "rate_limited"
+    assert "rate-limited" in row["detail"]
+
+
+def test_request_ceiling_is_never_exceeded(monkeypatch):
+    calls = _responses(
+        monkeypatch,
+        (429, {"error": {"message": "busy"}}, 0.1),
+        (200, {"choices": [{"message": {"tool_calls": [TOOL_CALL]}}]}, 1.0),
+        (200, {"choices": [{"message": {"content": "4242"}}]}, 0.5),
+    )
+    monkeypatch.setattr(probe_tool.time, "sleep", lambda _seconds: None)
+
+    row = probe_tool.probe("k", "vendor/busy:free", timeout=10, max_requests=3)
+
+    assert len(calls) == 3 and row["requests"] == 3
+    assert row["status"] == "ok"
diff --git a/tests/test_session.py b/tests/test_session.py
index 59a882c96..00829af39 100644
--- a/tests/test_session.py
+++ b/tests/test_session.py
@@ -4701,46 +4701,49 @@ class TestRuntimeCapabilities:
 
         result = await session.change_model("gpt-5.6-sol")
 
         assert result["runtime_changed"] is False
         assert result["native_session_reset"] is False
         assert session.session_id == "codex-native-session"
         assert session.runtime_handoff == ""
         assert session.session_id_history == []
         assert session._backend is source
         assert session.model == "gpt-5.6-sol"
         assert result["history_transfer"] == {"mode": "native_in_place"}
         source.retarget_model.assert_called_once_with("gpt-5.6-sol")
         session._prepare_runtime_handoff.assert_not_awaited()
         session._make_backend.assert_not_called()
         save.assert_called_once()
 
     @pytest.mark.asyncio
     @pytest.mark.parametrize(("runtime", "old_model", "new_model"), [
         ("claude", "claude-sonnet-5[1m]", "claude-opus-5[1m]"),
         ("grok", "grok-4.5", "grok-4.6"),
-        ("harness", "nvidia/nemotron-3-ultra-550b-a55b:free", "z-ai/glm-5.2:free"),
+        ("harness", "vendor/from:free", "vendor/to:free"),
     ])
     async def test_other_builtin_model_switches_retarget_in_place(
-            self, session, monkeypatch, runtime, old_model, new_model):
+            self, session, monkeypatch, live_harness_route, runtime, old_model, new_model):
         from app.session import AgentStatus
 
+        if runtime == "harness":
+            live_harness_route(old_model, context_length=1_000_000)
+            live_harness_route(new_model, context_length=1_000_000)
         session.model = old_model
         session.backend_type = runtime
         session.session_id = f"native-{runtime}-session"
         session.status = AgentStatus.IDLE
         source = SimpleNamespace(
             active_turn_id=None,
             _events_active=False,
             _turn_active=False,
             retarget_model=AsyncMock(),
         )
         session._backend = source
         session._log = MagicMock()
         session._last_context = {
             "percentage": 1, "total_tokens": 1_000, "max_tokens": 1_000_000,
         }
         session._prepare_runtime_handoff = AsyncMock(
             side_effect=AssertionError("same native session needs no handoff"),
         )
         session._make_backend = MagicMock(
             side_effect=AssertionError("same native session needs no replacement backend"),
@@ -4748,46 +4751,49 @@ class TestRuntimeCapabilities:
         save = MagicMock()
         monkeypatch.setattr("app.session.save_session", save)
 
         result = await session.change_model(new_model)
 
         assert result["ok"] is True
         assert result["runtime_changed"] is False
         assert result["native_session_reset"] is False
         assert result["history_transfer"] == {"mode": "native_in_place"}
         assert session.model == new_model
         assert session.session_id == f"native-{runtime}-session"
         assert session._backend is source
         source.retarget_model.assert_awaited_once_with(new_model)
         session._prepare_runtime_handoff.assert_not_awaited()
         session._make_backend.assert_not_called()
         save.assert_called_once()
 
     @pytest.mark.asyncio
     @pytest.mark.parametrize(("runtime", "old_model", "new_model"), [
         ("claude", "claude-opus-5[1m]", "claude-haiku-4-5"),
-        ("harness", "nvidia/nemotron-3-ultra-550b-a55b:free", "z-ai/glm-5.2:free"),
+        ("harness", "vendor/wide:free", "vendor/narrow:free"),
     ])
     async def test_in_place_switch_refuses_context_that_target_cannot_fit(
-            self, session, monkeypatch, runtime, old_model, new_model):
+            self, session, monkeypatch, live_harness_route, runtime, old_model, new_model):
         from app.session import AgentStatus
 
+        if runtime == "harness":
+            live_harness_route(old_model, context_length=1_000_000)
+            live_harness_route(new_model, context_length=256_000)
         session.model = old_model
         session.backend_type = runtime
         session.session_id = f"native-{runtime}-session"
         session.status = AgentStatus.IDLE
         session._last_context = {
             "percentage": 30,
             "total_tokens": 300_000,
             "max_tokens": 1_000_000,
         }
         source = SimpleNamespace(
             active_turn_id=None,
             _events_active=False,
             _turn_active=False,
             retarget_model=AsyncMock(),
         )
         session._backend = source
         save = MagicMock()
         monkeypatch.setattr("app.session.save_session", save)
 
         result = await session.change_model(new_model)
diff --git a/tests/test_wf_run.py b/tests/test_wf_run.py
index 999111ca5..3aa2dcce6 100644
--- a/tests/test_wf_run.py
+++ b/tests/test_wf_run.py
@@ -520,143 +520,150 @@ async def test_usage_is_persisted_for_full_and_restricted_capabilities(tmp_path)
         "usage-capabilities", tmp_path, budget_usd=1,
         adapter=adapter, usage_writer=usage_writer,
     )
     await engine.agent("full", model="luna")
     await engine.agent(
         "restricted", model="luna", tools="read",
         capability_reason="read-only audit",
     )
     assert len(receipts) == 2
     assert all(row["result"].cost_usd == 0.01 for row in receipts)
 
 
 @pytest.mark.asyncio
 async def test_restricted_capabilities_require_an_inline_reason(tmp_path):
     engine = _engine("restriction-reason", tmp_path, budget_usd=1, adapter=lambda: None)
     with pytest.raises(ValueError, match="capability_reason"):
         await engine.agent("work", model="luna", tools="read")
 
 
 @pytest.mark.asyncio
-async def test_harness_read_capability_rejects_a_hallucinated_write(tmp_path, monkeypatch):
+async def test_harness_read_capability_rejects_a_hallucinated_write(
+    tmp_path, monkeypatch, live_harness_route,
+):
     from app.harness.llm import LLMEvent
     from app.harness.oneshot import run_oneshot
 
     monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
+    live_harness_route("vendor/free-x:free")
 
     class FakeLLM:
         def __init__(self):
             self.round = 0
             self.saw_refusal = False
 
         async def stream(self, history, _schemas, **_kwargs):
             self.round += 1
             if self.round == 1:
                 yield LLMEvent(
                     "tool_call_done",
                     tool_id="write-1",
                     tool_name="write",
                     arguments=json.dumps({"path": "forbidden.txt", "content": "bad"}),
                 )
                 yield LLMEvent("final", finish_reason="tool_calls", usage={})
                 return
             self.saw_refusal = any(
                 "[read-only]" in str(item.get("content")) for item in history
                 if item.get("role") == "tool"
             )
             yield LLMEvent("text_delta", text="done")
             yield LLMEvent("final", finish_reason="stop", usage={})
 
         async def aclose(self):
             return None
 
     llm = FakeLLM()
     row = await run_oneshot(
         prompt="try to write",
-        model="z-ai/glm-5.2:free",
+        model="vendor/free-x:free",
         cwd=tmp_path,
         tools_level="read",
         network=True,
         mcp=False,
         system_prompt="",
         llm=llm,
     )
     assert row["ok"] is True
     assert llm.saw_refusal is True
     assert not (tmp_path / "forbidden.txt").exists()
 
 
 @pytest.mark.asyncio
-async def test_standalone_harness_default_is_not_writable(tmp_path, monkeypatch):
+async def test_standalone_harness_default_is_not_writable(
+    tmp_path, monkeypatch, live_harness_route,
+):
     from app.harness.llm import LLMEvent
     from app.harness.oneshot import run_oneshot
 
     monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
+    live_harness_route("vendor/free-x:free")
 
     class FakeLLM:
         def __init__(self):
             self.round = 0
 
         async def stream(self, _history, _schemas, **_kwargs):
             self.round += 1
             if self.round == 1:
                 yield LLMEvent(
                     "tool_call_done", tool_id="write-1", tool_name="write",
                     arguments=json.dumps({"path": "escaped.txt", "content": "bad"}),
                 )
                 yield LLMEvent("final", finish_reason="tool_calls", usage={})
                 return
             yield LLMEvent("text_delta", text="done")
             yield LLMEvent("final", finish_reason="stop", usage={})
 
         async def aclose(self):
             return None
 
     row = await run_oneshot(
-        prompt="write", model="z-ai/glm-5.2:free", cwd=tmp_path,
+        prompt="write", model="vendor/free-x:free", cwd=tmp_path,
         network=True, mcp=False, system_prompt="", llm=FakeLLM(),
     )
     assert row["ok"] is True
     assert not (tmp_path / "escaped.txt").exists()
 
 
 @pytest.mark.asyncio
-async def test_free_output_requires_a_verify_step_before_synthesis(tmp_path):
+async def test_free_output_requires_a_verify_step_before_synthesis(tmp_path, live_harness_route):
+    live_harness_route("vendor/free-x:free")
     calls = []
 
     async def adapter(prompt, model, **_kwargs):
         calls.append((prompt, model))
         runtime = "harness" if model.endswith(":free") else "codex"
         return _result('{"ok": true}', runtime=runtime, model=model)
 
     engine = _engine("free-gate", tmp_path, budget_usd=2, adapter=adapter)
     with pytest.raises(ValueError, match="loss_tolerant"):
-        await engine.agent("unsafe draft", model="z-ai/glm-5.2:free")
+        await engine.agent("unsafe draft", model="vendor/free-x:free")
     free = await engine.agent(
-        "draft", model="z-ai/glm-5.2:free", loss_tolerant=True,
+        "draft", model="vendor/free-x:free", loss_tolerant=True,
     )
     with pytest.raises(ValueError, match="non-free"):
         await engine.agent(
             "self check",
             purpose="verify",
             inputs=[free],
-            model="z-ai/glm-5.2:free",
+            model="vendor/free-x:free",
             loss_tolerant=True,
         )
     with pytest.raises(ValueError, match="verify"):
         await engine.agent("synthesize", purpose="synthesis", inputs=[free])
 
     checked = await engine.agent("check", purpose="verify", inputs=[free], model="luna")
     final = await engine.agent(
         "synthesize", purpose="synthesis", inputs=[free, checked], model="luna",
     )
     assert final is not None
     assert len(calls) == 3
 
 
 @pytest.mark.asyncio
 async def test_dispatched_without_terminal_event_resumes_as_unknown_not_a_second_charge(tmp_path):
     async def interrupted(_prompt, **_kwargs):
         raise RuntimeError("simulated process loss")
 
     first = _engine("unknown-call", tmp_path, budget_usd=2, adapter=interrupted)
     with pytest.raises(RuntimeError, match="process loss"):


## Later history of the touched files on main (after this commit)

260 later commits touch these paths; the first 40 (oldest first):
0fc5abfe9 2026-09-17 V-584: #V-584: русский интерфейс дашборда и переключатель RU/EN
cf0ca23ba 2026-09-17 TODO: выгрести правила из истории мержей — первый проход с числами
957a4c69b 2026-09-17 TODO: ресерч по переносу Dream-RSI на нашу историю попыток
20036a865 2026-09-17 TODO: изучить два приёма приёмки из security-audit-skill Cloudflare
75cd5bec4 2026-09-17 #V-592: changelog
67ee5df03 2026-09-17 #V-593: блокировка бесплатных маршрутов, отказавших в нашей пробе
ddfde793a 2026-09-17 #V-593: changelog
e0b09617a 2026-09-17 #V-596: changelog
5806e5349 2026-09-18 TODO: значок темы TG залипает на ⚡ после рестарта
7bf8ebfed 2026-09-18 KB+TODO: Inspo MCP и lite-профиль инструментов по ролям
755e4c14d 2026-09-19 TODO: ресерч харнеса MiniMax — сторож зацикливания и динамический бюджет вывода
5956add85 2026-09-19 TODO: на изучение — разделение кликов и рассуждений в браузерной автоматизации (ссылка из поста мертва)
30e44e979 2026-09-19 TODO: на изучение — Ouroboros, маршрутизация моделей текстом и контракт рантайма
4dd81e7e3 2026-09-19 #V-600: корневые правила — один AGENTS.md, дубль CLAUDE.md запрещён
75a8fbb36 2026-09-19 Revert "#V-600: корневые правила — один AGENTS.md, дубль CLAUDE.md запрещён"
19ded26ad 2026-09-19 #V-601: CLAUDE.md — симлинк на AGENTS.md вместо копии
74331413a 2026-09-19 #V-602: харнес берёт ступень рассуждения из манифеста, регулярка удалена
9234cb571 2026-09-19 TODO: где применим Jev с ценой по нашим объёмам; поправка к замеру серий одинаковых вызовов
902e86597 2026-09-19 #V-603: отказ привязки задачи объясняет причину, описание spawn_worker — правила
f0bcc34a4 2026-09-20 TODO: ресёрч SoL-Pi — автоподбор обвязки агента и заявленные −45% токенов
f6d969c1c 2026-09-20 V-602: update MCP descriptions and parallelize agent listing
4bd1a5365 2026-09-21 V-603: clarify worker refusals and background receipts
be8fd2938 2026-09-21 TODO: ресёрч Laya — локальный классификатор решений как альтернатива Jev
7f291ae99 2026-09-21 V-606: #V-606: compact idle sessions before cache expiry
d607f5fc7 2026-09-21 V-607: #V-607: add mutation test gate for worker merges
2dcbfba99 2026-09-22 V-609: #V-609: persist provider cost baseline across restart
1755b18b9 2026-09-22 TODO: repair-подсказка LAYOUT_MISSING указывает на worktree вместо базового чекаута
425b83eeb 2026-09-22 V-611: repair-подсказка LAYOUT_MISSING указывает на базовый чекаут, а не на worktree
bbfd3641c 2026-09-22 V-585: WIP V-585: GigaChat харнес-маршрут, незавершённая работа до смены модели
a6fe16bfc 2026-09-22 V-614: тень-гейт «DONE без прошедшей проверки после последней правки»
8941811c9 2026-09-22 V-610: rewrite third-party code in app/ with own implementation
de5d62a52 2026-09-22 V-576: #V-576: каталог проектов файлом и теги задач вместо второй сущности проекта
8f087294f 2026-09-22 TODO: гейт мутации пропускает проверку на удалённых тест-файлах; зависание прогона не связано с V-610
f20796d3e 2026-09-23 Каталог моделей: Opus 5.5, GPT-6 Luna и Sol; opus → 5.5
0f973de21 2026-09-23 V-620: switch_worker_branch releases a worker left bound after merge(continue)
628ac2058 2026-09-23 Маршрут по умолчанию: luna → GPT-6 Luna, sol → GPT-6 Sol (Sol закрыт для агентов)
f4470decc 2026-09-23 Opus 5.5 на medium; общее правило «продолжай сам, останавливайся перед необратимым»
9c5e64087 2026-09-23 V-621: WIP #V-621: каталог проектов — файл на каждый scope вместо одного общего
5313e27a5 2026-09-23 TODO: импорт истории Codex закреплён на 0.153.4, установлен 0.156.1
6cfb55e08 2026-09-23 Отчёт о сжатии: контекст одного обращения вместо суммы за ход

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 0fc5abfe9 V-584: #V-584: русский интерфейс дашборда и переключатель RU/EN

diff --git a/CHANGELOG.md b/CHANGELOG.md
index f8b5c2c9c..850d50e09 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -4,10 +4,34 @@
 > their CHANGELOGs independently, so versions 2.31.0-2.33.0 were used TWICE for different
 > content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.
 
 ## Unreleased
 
+### Added
+- 🇷🇺 **Русский интерфейс дашборда и переключатель RU/EN** (`app/static/js/i18n.js` —
+  новый файл: словарь, `T()`, применение к разметке и сам переключатель; отметки
+  `data-i18n*` в `app/templates/{login,dashboard}.html`; вызовы `T()` в `app.js`,
+  `chat.js`, `usage.js`, `analytics.js`, `tool-renderers.js`, `connection.js`).
+  Русский — язык по умолчанию, выбор хранится в `localStorage['orch_lang']` и
+  переживает перезагрузку, переключатель доступен со страницы входа, до логина.
+  Ключ словаря — сама английская строка, поэтому английская локаль работает без
+  словаря и осталась дословно прежней. Механизм целиком клиентский: шаблоны и JS
+  дашборд читает с диска живьём, а Python живёт в памяти до рестарта, так что
+  серверный перевод доехал бы до экрана только после ручного перезапуска.
+  *Triggered case:* продукт подаётся в реестр российского ПО, подп. «л» п. 5 Правил
+  (ПП РФ от 16.11.2015 № 1236) требует русский графический интерфейс, а проверяет его
+  живой эксперт по экранам — «перевели строки в исходниках» приёмкой не является.
+  Приёмка снята прогоном по 41 отрисованному экрану (`.orchestra/tasks/V-584/audit_screens.py`):
+  ноль находок латиницы, отрицательный контроль сработал на каждом экране, обратный
+  контроль на английской локали — 1564 находки на 41 экране из 41.
+  *Known tradeoff:* словарь по английскому ключу молча роняет перевод в английский,
+  если надпись в коде переименуют; ловится только тем же прогоном по экранам, поэтому
+  его надо звать руками после заметных правок интерфейса. Старый браузерный набор
+  (`tests/test_frontend.py`, `tests/test_t344_quota_lines_browser.py`) проверяет
+  английские подписи и пришпилен к английской локали через `window.__ORCH_LANG__` —
+  его ожидания остались дословно прежними.
+
 ### Fixed
 - 🧭 **Допуск харнес-маршрута решается по живому каталогу OpenRouter, а не по нашей
   записи о нём** (`app/models.py` — `validate_harness_model_spec`, из
   `SELECTABLE_MODEL_SPECS` убраны оба зашитых харнес-маршрута; `app/model_catalog.py` —
   `live_catalog_entry`, `harness_capable` вместо приватного `_cached_harness_eligible`).
### cf0ca23ba TODO: выгрести правила из истории мержей — первый проход с числами

diff --git a/TODO.md b/TODO.md
index 1b7b540d5..e5eeec504 100644
--- a/TODO.md
+++ b/TODO.md
@@ -82,10 +82,11 @@
 - [ ] **`merge_worker` в состоянии PENDING читается агентами как провал, потому что объяснение уходит в поле, которого рантайм не показывает.** 12.09 оркестратор портфеля отрапортовал «❌ merge worker failed» на мерже, который через секунды пришёл `SUCCEEDED`. Платформа ведёт себя правильно: `PENDING` + `completion.job_id` означает «принято, идёт в фоне, выполнится и разбудит», и с 05.09 (`b0f32897`) для этого случая формируется прямой текст «STILL PENDING — NOT a failure… Do not poll or call merge_worker again». Дефект в доставке этого текста: `mcp_tool_result` кладёт его в `content[].text`, а рядом отдаёт `structuredContent` с сырым результатом — и Claude-рантайм показывает агенту ИМЕННО структуру. Я сам за сегодня сделал больше десяти мержей и ни разу не увидел этой строки, только JSON с `operation_state: PENDING`. Отсюда и повторяющаяся ошибка: агент видит «не SUCCEEDED» и называет это провалом. Чинить надо в структуре, а не в тексте: нетерминальное состояние обязано читаться из самого объекта (например, явным полем вида «это не отказ, исход придёт фоновым событием»), иначе следующий агент прочитает так же. Комментарий в коде `app/mcp_stdio.py` про прошлый заход подтверждает, что правка формулировки уже делалась и проблему не сняла.
 - [x] **`merge_worker` отбивал 409 SESSION_IDENTITY_CHANGED в цикле, из которого нет выхода предписанным способом — ПОЧИНЕНО #V-575, ждёт рестарта владельца** (`.orchestra/tasks/V-575/report.md`). При расхождении спрашивается git: совпал с закреплённой веткой И HEAD → `sessions.branch` приводится в соответствие и мерж идёт; иначе отказ, называющий все три стороны и рабочий выход. `next_action` стал `INSPECT_WORKER_THEN_NEW_OPERATION`. Первопричина (обнуление `task_id` с уходом ветки в `adhoc-<ts>/<имя>`) НЕ чинилась и остаётся отдельной работой. Исходный разбор: Репорт seedon-orchestrator 15.09 (запись `20260915T101900...`, проект seedon): пять операций на одном готовом результате, из них три FAILED с одним и тем же текстом. Разобрал по коду: сравниваются ДВЕ ЗАПИСИ ПЛАТФОРМЫ, git не спрашивают вовсе — `app/routes/sessions.py:2054` сверяет `expected_branch` операции (`task-256/...`, закреплён при приёме) с `row_branch`, то есть колонкой `sessions.branch` (`adhoc-<ts>/...`). Предписанный `next_action` REFRESH_WORKER_THEN_NEW_OPERATION зовёт `worker_wip`, а тот ходит в `/api/sessions/{name}/wip` → `branch_wip_status`, который ТОЛЬКО читает git и ничего не пишет в `sessions.branch` (`app/routes/sessions.py:3113`). Обе стороны сравнения после «починки» те же — отказ воспроизводится побайтово, сколько ни повторяй. Побочный эффект: оркестратор со стороны подгоняет git под устаревшую строку БД (`git branch -f adhoc-...`), то есть чинит правильное состояние по неправильному. Второй слой: сверка ветки с РЕАЛЬНЫМ worktree (`app/routes/sessions.py:2158-2176`) выполняется только когда `expected_head` НЕ передан — аккуратный вызывающий получает менее согласованный путь, чем небрежный. Замер 15.09 по живой БД (`ORCHESTRA_DB_PATH` MainPID 1016880, read-only, 58 неархивных сессий): расхождений `sessions.branch` ↔ фактическая ветка worktree сейчас **ноль**, но это НЕ здоровье популяции — обе пострадавшие сессии seedon к моменту замера уже подогнали руками под запись БД. Предложенный репортёром детектор «`branch LIKE 'adhoc-%'` при наличии привязанной задачи» не находит ничего и находить не может: дефект обнуляет `task_id`. Рабочий признак — `branch LIKE 'adhoc-%' AND task_id=''`: таких сессий **10**, из них **7 в одном seedon** (`marketer`, `seo-cro`, `sales`, `designer`, `direct-research`, `accountant`, `demand-audit`), остальные в dnd-game-master, katya-work, comfy-image-pipeline. Каждая из них воспроизведёт тот же 409 при первом мерже с ожиданием task-ветки. Чинить в сторону «git — источник правды о ветке»: при расхождении спросить worktree, и если он совпал с закреплённой веткой и `expected_head`, привести `sessions.branch` в порядок и продолжить; иначе отказывать СИНХРОННО, называя, какая сторона из БД, а какая из git, и предлагая существующий инструмент ремонта.
 - [ ] **Красный на main, не связан с правками фронта: `tests/test_frontend.py::test_photo_batch_renders_as_compact_expandable_gallery`.** Проверено 17.09 на чистом main (без правок #V-584): падает так же, ошибка приходит из `playwright/_impl/_connection.py:559`. Остальные 129 браузерных тестов зелёные. При прогоне фронта не принимать за свою регрессию; чинить отдельно, начиная с того, что именно роняет соединение Playwright в этом тесте.
 - [ ] **`__pycache__` под `.orchestra/` не игнорируется: правило-исключение перебивает общий шаблон.** Проверено 17.09 самостоятельно: `git check-ignore -v .orchestra/tasks/V-583/__pycache__/probe.pyc` отвечает `.gitignore:26:!.orchestra/**`, то есть негативное правило для `.orchestra/**` сильнее `__pycache__/` из первой строки. Практическое следствие: любой скрипт под `.orchestra/`, который импортирует соседний модуль, оставляет неотслеженный каталог, а тот отбивает мерж воркера с `WORKER_DIRTY` — так на #V-583 сгорела целая операция и лишний ход воркера. Лечится одной строкой `.orchestra/**/__pycache__/` после 26-й; это общий конфиг, поэтому отдельным решением, а не внутри чужой задачи.
 - [x] **Оба зашитых харнес-маршрута мертвы, и наш валидатор этого не видит — ПОЧИНЕНО #V-582, ждёт рестарта владельца** (`.orchestra/tasks/V-582/report.md`). Харнес-маршруты убраны из `SELECTABLE_MODEL_SPECS` и приходят только из живого каталога; `validate_harness_model_spec` решает по записи провайдера (`live_catalog_entry`/`harness_capable` в `app/model_catalog.py`), а не по нашему `supported_parameters`. Проба стала инструментом — `scripts/probe_free_models.py`. ОСТАЛОСЬ ОТДЕЛЬНО: `thinkingmachines/inkling*:free` (1M) отдают 403 «only available on agentic harnesses» — нужна регистрация приложения в OpenRouter, обычный ключ не пускают. Замер 17.09 показал и второе: состав прошедших маршрутов переворачивается за сутки (nemotron-3-ultra 16.09 игнорировал результат инструмента, 17.09 прошёл за 4.5 с; nemotron-3.5-lightning наоборот), то есть разовая проба — снимок, а не приговор. Исходный разбор: **Оба зашитых харнес-маршрута мертвы, и наш валидатор этого не видит.** Замер 16.09 (`.orchestra/tasks/V-581/probe.log`, две попытки на маршрут): `z-ai/glm-5.2:free` в живом каталоге OpenRouter отдаёт `tools=False` и `ctx=32768` против наших 256000, а `nvidia/nemotron-3-ultra-550b-a55b:free` вызывает инструмент, но ИГНОРИРУЕТ его результат — воркером быть не может. Корень: `validate_harness_model_spec` (`app/models.py:364-381`) проверяет НАШЕ статическое поле `supports_tools`, а не живые данные провайдера, поэтому протухание маршрута незаметно до сожжённого хода. Из 18 `:free` маршрутов с заявленным `tools` полный протокол (вызов → результат → ответ по результату) прошли 9: nemotron-3.5-lightning (1M), dots-3-note-preview (512k), ling-3.0-flash-sante, ling-3.0-flash-fin, nemotron-3-super-120b, cohere/north-mini-code, liquid/lfm-2.5-2.6b, gemma-4-26b и nex-n2.5-pro (последние два — со второй попытки). Отдельный класс: `thinkingmachines/inkling*` (1M) отдают 403 «only available on agentic harnesses» — нужна регистрация приложения, обычный ключ не пускают.
+- [ ] **Наша история мержей — готовый источник правил для промптов, и мы его ни разу не выгребали.** Подсказал подход пост DevFM 17.09: они собрали замечания из старых пиаров и чатов с агентами и превратили в AGENTS.md и скиллы. Первый проход по нашим данным сделан в тот же день: из 1571 операции мержа 410 несут код ошибки, и это не разовые случаи, а повторяющиеся грабли. Разбивка: `session has no bound task` 57 (с 25.08), `DIFF TOO LARGE` 52 (с 16.08), `WAITING` 57, `CONFLICT` 55, `TEST_GATE_FAILED` 40, `TARGET_DIRTY` 32, `NO_COMMITS_MERGED` 30, `TEST_GATE_INCONCLUSIVE` 24, `WORKER_DIRTY` 21, `SESSION_IDENTITY_CHANGED` 13, `POST_COMMIT_PARTIAL` 9. Каждая строка — кандидат в правило, которое сейчас живёт в голове оркестратора и повторяется в каждой постановке руками: сегодня я трижды писал воркерам «дерево должно быть чистым» и «мутация обязана краснить ровно нужный тест». Что делать: (1) по каждому коду решить, чинится он ПРАВИЛОМ в промпте, ТЕКСТОМ отказа или КОДОМ платформы — `WORKER_DIRTY` и `DIFF TOO LARGE` явно первое, `session has no bound task` и `SESSION_IDENTITY_CHANGED` явно третье; (2) правила, которые останутся, класть в существующие модули, а не плодить новый файл; (3) не превращать это в предписание маршрута — измерено V-548/V-550, что предписанный способ дороже в 7.5–8.8 раза. Данные берутся одним запросом к `merge_operations.result_json`; повторить перед правкой, числа устаревают.
 - [ ] **`merge_worker(task_outcome="continue")` — ловушка: прогон задачи остаётся открытым, а закрыть его нечем, если мержить больше нечего.** Репорт cog-second-brain-orchestrator 16.09 (воркер `balatro-vps`, task_run `ce47fdb1`, операции `0e7acb97` и `894b296c` обе FAILED). Механизм подтверждён по коду: у сессии допускается РОВНО ОДИН открытый `task_run` (`review_receipts`, `subject_kind='task_run'`, `status='requested'`), и `task_run_receipt_open` (`app/db.py:1331-1381`) отказывает `ValueError: open task run conflicts with current assignment provenance`, когда открывают прогон другой задачи. Закрывается прогон единственным путём — `_finish_task_run_for_task` (`app/tm.py:735-760`) на успешном мерже с `complete`. Отсюда тупик: после `continue` ветка воркера и main стоят на одном коммите, `merge_worker(complete)` отбивается `NO_COMMITS_MERGED` ДО закрытия прогона, а `switch_worker_branch` откатывается на той же ValueError, причём `force=True` не помогает — отказ приходит из слоя квитанций, а не из слоя веток. Штатного выхода нет; чужой оркестратор вышел через `send_message` с новым task_id и получил расщеплённое состояние: `get_worker_info` отдаёт старую задачу и старую ветку, `list_agents` показывает три задачи `in_progress`, коммиты новой задачи идут в ветку старой. Чинить одним из двух: либо `switch_worker_branch` закрывает предыдущий прогон как `superseded`, либо `complete` закрывает прогон и тогда, когда коммитов нет (пустой мерж — законный способ снять задачу с воркера). Обход, который работает уже сейчас и его стоит назвать в тексте отказа: дать воркеру доделать и закоммитить, тогда мерж с `complete` проходит и закрывает прогон.
 - [ ] **Astra недоступна нашему аккаунту, но остаётся маршрутом по умолчанию для сложных задач.** 16.09 спавн воркера на `gpt-6-astra` сжёг ход и умер до первой строки: провайдер ответил 400 `The 'gpt-6-astra' model is not supported when using Codex with a ChatGPT account` (дважды, затем `turn FAILED: error`). Задание до воркера не доехало вообще. При этом модуль model-routing объявляет Astra классом сложности, а каталог моделей её показывает — то есть платформа предлагает агенту модель, которой у аккаунта нет, и узнаётся это только сожжённым ходом. Смежное: два живых воркера (`bench-master`, `prompt-engineer`) сидят на этой же модели и при первом же сообщении получат то же самое. Чинить в сторону «каталог знает, что доступно аккаунту»: либо проверка при спавне с внятным отказом, либо снятие Astra из маршрутизации до выяснения. ПРИЧИНА УСТАНОВЛЕНА В ТОТ ЖЕ ДЕНЬ: подписка Codex отменена владельцем намеренно («чтобы за доллары потом оплатить»), и телеметрия провайдера показывает переход `plan_type` pro → free в 11:03 UTC 16.09; окно стало 30-дневным (43200 мин, сброс 16.10), Astra на free не поддерживается вовсе. То есть это не дефект каталога сам по себе, а отсутствие проверки «доступна ли модель этому плану»: узнаётся только сожжённым ходом. Масштаб free-окна для планирования: один ход Luna (8.03М входных токенов) дал 10% окна. Отдельно проверить, не то же ли это, что #520.
 - [ ] **ЖДЁТ РЕСТАРТА ВЛАДЕЛЬЦА — семь готовых правок и два мёртвых воркера (на 12.09.2026).** Всё смержено в main и проверено, но Python в живом процессе не меняется: (1) офлайн-миграция БД под #V-544, отдельная задача #V-545 с командами; (2) #V-543 утечка pidfd; (3) `bec4f378` отказ merge_worker на переименованиях; (4) #V-546 потолок полос sol=95; (5) #V-540 стабильный системный промпт; (6) `QUOTA_GATED_LANES=claude,sol` — 15.09 владелец дословно сказал «включай общий гейт снова на лимиты», `.env` поправлен, но живой процесс стартовал с пустым значением и до рестарта гейт остаётся снятым со всех полос; (7) #V-547 индикатор состояния гейта — до рестарта панель честно пишет «гейт: нет данных». Воркеры `fix-stuck-writer` и `fix-prompt-cache` висят `broken` («Codex thread already has an active writer») — их работа смержена, но сессии оживит только рестарт.
 - [ ] **Тест-гейт мержа гоняет тесты в ВЕТКЕ ВОРКЕРА, а исправление красноты лежит в main — ветка чинится только подтягиванием main.** 11.09: мерж #V-546 отбит трижды. Первые два раза — по чужим дефектам (запись «upper» в боевом хранилище задач; протёкший `QUOTA_GATED_LANES=` плюс снапшот маршрутов, отставший от `f5713f4d`). Я починил оба в main коммитом `52f7c97d` и повторил мерж — гейт выдал ТЕ ЖЕ 16 красных, потому что тестирует он ветку, где `tests/conftest.py` старый. Практический вывод: **когда гейт краснеет на чужом дефекте, чинить надо не только main — воркеру нужно отдельно подтянуть main к себе**, иначе цикл «починил → отбито → починил» повторяется. Стоит проверить, не должен ли гейт тестировать РЕЗУЛЬТАТ слияния, а не голую ветку: сейчас он отвечает на вопрос «зелена ли ветка», а решение принимается о том, «зелен ли main после мержа», и это разные вопросы.
 - [x] **Горячая правка `.env` для квоты в боевом процессе НЕ работала — ИСПРАВЛЕНО `fbc9e40d`, ждёт рестарта.** Ключ, чьё стартовое значение совпало со снимком файла, теперь принадлежит файлу (`_dotenv_owned_names`), внешний оверрайд по-прежнему держится. Заодно `a76cfe5e` убрал мерцание теста перечитки: две записи в один тик часов давали одинаковый mtime, и перечитка не срабатывала (~1 прогон из 15, воспроизведено и до правки). Исходный разбор: `quota_policy()` обещает в докстроке «including edits made to `.env` live», но `_live_quota_env` (`app/quota_gate.py:191`) отдаёт `_startup_quota_env[name]`, если оно не `None`, а systemd кладёт весь `.env` в окружение процесса (`EnvironmentFile=/home/kesha/orchestra/.env`). Пустая строка тоже «не None», поэтому она побеждает. Проверено 15.09 на рантайме: с `QUOTA_GATED_LANES=` в окружении политика даёт `[]` при `claude,sol` в файле; без переменной в окружении — `['claude','sol']`. Практический вывод: любая правка квотных `QUOTA_*` в `.env` вступает в силу только рестартом, а обещание горячего применения вводит в заблуждение. Чинить либо приоритетом (файл важнее унаследованного стартового значения для тех ключей, что пришли из этого же файла), либо честной докстрокой.
### 957a4c69b TODO: ресерч по переносу Dream-RSI на нашу историю попыток

diff --git a/TODO.md b/TODO.md
index e5eeec504..fd7759db2 100644
--- a/TODO.md
+++ b/TODO.md
@@ -82,10 +82,11 @@
 - [ ] **`merge_worker` в состоянии PENDING читается агентами как провал, потому что объяснение уходит в поле, которого рантайм не показывает.** 12.09 оркестратор портфеля отрапортовал «❌ merge worker failed» на мерже, который через секунды пришёл `SUCCEEDED`. Платформа ведёт себя правильно: `PENDING` + `completion.job_id` означает «принято, идёт в фоне, выполнится и разбудит», и с 05.09 (`b0f32897`) для этого случая формируется прямой текст «STILL PENDING — NOT a failure… Do not poll or call merge_worker again». Дефект в доставке этого текста: `mcp_tool_result` кладёт его в `content[].text`, а рядом отдаёт `structuredContent` с сырым результатом — и Claude-рантайм показывает агенту ИМЕННО структуру. Я сам за сегодня сделал больше десяти мержей и ни разу не увидел этой строки, только JSON с `operation_state: PENDING`. Отсюда и повторяющаяся ошибка: агент видит «не SUCCEEDED» и называет это провалом. Чинить надо в структуре, а не в тексте: нетерминальное состояние обязано читаться из самого объекта (например, явным полем вида «это не отказ, исход придёт фоновым событием»), иначе следующий агент прочитает так же. Комментарий в коде `app/mcp_stdio.py` про прошлый заход подтверждает, что правка формулировки уже делалась и проблему не сняла.
 - [x] **`merge_worker` отбивал 409 SESSION_IDENTITY_CHANGED в цикле, из которого нет выхода предписанным способом — ПОЧИНЕНО #V-575, ждёт рестарта владельца** (`.orchestra/tasks/V-575/report.md`). При расхождении спрашивается git: совпал с закреплённой веткой И HEAD → `sessions.branch` приводится в соответствие и мерж идёт; иначе отказ, называющий все три стороны и рабочий выход. `next_action` стал `INSPECT_WORKER_THEN_NEW_OPERATION`. Первопричина (обнуление `task_id` с уходом ветки в `adhoc-<ts>/<имя>`) НЕ чинилась и остаётся отдельной работой. Исходный разбор: Репорт seedon-orchestrator 15.09 (запись `20260915T101900...`, проект seedon): пять операций на одном готовом результате, из них три FAILED с одним и тем же текстом. Разобрал по коду: сравниваются ДВЕ ЗАПИСИ ПЛАТФОРМЫ, git не спрашивают вовсе — `app/routes/sessions.py:2054` сверяет `expected_branch` операции (`task-256/...`, закреплён при приёме) с `row_branch`, то есть колонкой `sessions.branch` (`adhoc-<ts>/...`). Предписанный `next_action` REFRESH_WORKER_THEN_NEW_OPERATION зовёт `worker_wip`, а тот ходит в `/api/sessions/{name}/wip` → `branch_wip_status`, который ТОЛЬКО читает git и ничего не пишет в `sessions.branch` (`app/routes/sessions.py:3113`). Обе стороны сравнения после «починки» те же — отказ воспроизводится побайтово, сколько ни повторяй. Побочный эффект: оркестратор со стороны подгоняет git под устаревшую строку БД (`git branch -f adhoc-...`), то есть чинит правильное состояние по неправильному. Второй слой: сверка ветки с РЕАЛЬНЫМ worktree (`app/routes/sessions.py:2158-2176`) выполняется только когда `expected_head` НЕ передан — аккуратный вызывающий получает менее согласованный путь, чем небрежный. Замер 15.09 по живой БД (`ORCHESTRA_DB_PATH` MainPID 1016880, read-only, 58 неархивных сессий): расхождений `sessions.branch` ↔ фактическая ветка worktree сейчас **ноль**, но это НЕ здоровье популяции — обе пострадавшие сессии seedon к моменту замера уже подогнали руками под запись БД. Предложенный репортёром детектор «`branch LIKE 'adhoc-%'` при наличии привязанной задачи» не находит ничего и находить не может: дефект обнуляет `task_id`. Рабочий признак — `branch LIKE 'adhoc-%' AND task_id=''`: таких сессий **10**, из них **7 в одном seedon** (`marketer`, `seo-cro`, `sales`, `designer`, `direct-research`, `accountant`, `demand-audit`), остальные в dnd-game-master, katya-work, comfy-image-pipeline. Каждая из них воспроизведёт тот же 409 при первом мерже с ожиданием task-ветки. Чинить в сторону «git — источник правды о ветке»: при расхождении спросить worktree, и если он совпал с закреплённой веткой и `expected_head`, привести `sessions.branch` в порядок и продолжить; иначе отказывать СИНХРОННО, называя, какая сторона из БД, а какая из git, и предлагая существующий инструмент ремонта.
 - [ ] **Красный на main, не связан с правками фронта: `tests/test_frontend.py::test_photo_batch_renders_as_compact_expandable_gallery`.** Проверено 17.09 на чистом main (без правок #V-584): падает так же, ошибка приходит из `playwright/_impl/_connection.py:559`. Остальные 129 браузерных тестов зелёные. При прогоне фронта не принимать за свою регрессию; чинить отдельно, начиная с того, что именно роняет соединение Playwright в этом тесте.
 - [ ] **`__pycache__` под `.orchestra/` не игнорируется: правило-исключение перебивает общий шаблон.** Проверено 17.09 самостоятельно: `git check-ignore -v .orchestra/tasks/V-583/__pycache__/probe.pyc` отвечает `.gitignore:26:!.orchestra/**`, то есть негативное правило для `.orchestra/**` сильнее `__pycache__/` из первой строки. Практическое следствие: любой скрипт под `.orchestra/`, который импортирует соседний модуль, оставляет неотслеженный каталог, а тот отбивает мерж воркера с `WORKER_DIRTY` — так на #V-583 сгорела целая операция и лишний ход воркера. Лечится одной строкой `.orchestra/**/__pycache__/` после 26-й; это общий конфиг, поэтому отдельным решением, а не внутри чужой задачи.
 - [x] **Оба зашитых харнес-маршрута мертвы, и наш валидатор этого не видит — ПОЧИНЕНО #V-582, ждёт рестарта владельца** (`.orchestra/tasks/V-582/report.md`). Харнес-маршруты убраны из `SELECTABLE_MODEL_SPECS` и приходят только из живого каталога; `validate_harness_model_spec` решает по записи провайдера (`live_catalog_entry`/`harness_capable` в `app/model_catalog.py`), а не по нашему `supported_parameters`. Проба стала инструментом — `scripts/probe_free_models.py`. ОСТАЛОСЬ ОТДЕЛЬНО: `thinkingmachines/inkling*:free` (1M) отдают 403 «only available on agentic harnesses» — нужна регистрация приложения в OpenRouter, обычный ключ не пускают. Замер 17.09 показал и второе: состав прошедших маршрутов переворачивается за сутки (nemotron-3-ultra 16.09 игнорировал результат инструмента, 17.09 прошёл за 4.5 с; nemotron-3.5-lightning наоборот), то есть разовая проба — снимок, а не приговор. Исходный разбор: **Оба зашитых харнес-маршрута мертвы, и наш валидатор этого не видит.** Замер 16.09 (`.orchestra/tasks/V-581/probe.log`, две попытки на маршрут): `z-ai/glm-5.2:free` в живом каталоге OpenRouter отдаёт `tools=False` и `ctx=32768` против наших 256000, а `nvidia/nemotron-3-ultra-550b-a55b:free` вызывает инструмент, но ИГНОРИРУЕТ его результат — воркером быть не может. Корень: `validate_harness_model_spec` (`app/models.py:364-381`) проверяет НАШЕ статическое поле `supports_tools`, а не живые данные провайдера, поэтому протухание маршрута незаметно до сожжённого хода. Из 18 `:free` маршрутов с заявленным `tools` полный протокол (вызов → результат → ответ по результату) прошли 9: nemotron-3.5-lightning (1M), dots-3-note-preview (512k), ling-3.0-flash-sante, ling-3.0-flash-fin, nemotron-3-super-120b, cohere/north-mini-code, liquid/lfm-2.5-2.6b, gemma-4-26b и nex-n2.5-pro (последние два — со второй попытки). Отдельный класс: `thinkingmachines/inkling*` (1M) отдают 403 «only available on agentic harnesses» — нужна регистрация приложения, обычный ключ не пускают.
+- [ ] **РЕСЕРЧ: можно ли перебирать стратегии оркестрации по своей истории, как Dream-RSI (arXiv 2609.14858).** Идея: дерево уже выполненных попыток с записанными исходами превращается в бесплатный симулятор — новые стратегии («сколько попыток, когда останавливаться, кого звать») гоняются по нему без единого нового вызова модели. Разбор статьи сделал Кеша 17.09 (`/opt/cog-second-brain/05-knowledge/2026-09-17-dream-rsi-google.md`), и его поправка существенна: заявленные «162×» получены против заведомо расточительного бейзлайна, честная цифра против вменяемого — 1.7×; раздела ограничений в статье нет вовсе. Что я проверил по НАШИМ данным в тот же день: задач с записанными операциями мержа 370, из них с двумя и более попытками 164, с разными воркерами на одной задаче 87; исходов 1134 успешных против 408 отказов. Вывод двойной. Применимо к выбору момента остановки и числа повторов при мерже — там дерево «попытка → исход» настоящее и достаточно большое. НЕ применимо к выбору модели и маршрута: у 206 задач из 370 ровно одна попытка, ветвиться нечем, а редкие настоящие ветвления (V-548/V-550 — пять моделей на одной задаче) единичны. Ограничение метода, названное в самой статье («no outcomes beyond T_i are generated»), бьёт по нам прямо: стратегия, уводящая в неисследованное, на реплее выглядит хуже, чем она есть, поэтому метод будет уверенно улучшать то, как мы уже работаем, и слеп к тому, чего мы не пробовали. Дешёвый первый шаг, если браться: не строить симулятор, а начать СОХРАНЯТЬ дерево — задача, попытка, модель, исход, цена; половина полей уже пишется в `merge_operations` и квитанциях приёмки, не хватает связки «альтернативная попытка того же результата». Честная оценка ценности сейчас: наше узкое место — квота, а не стратегия поиска; 17.09 три задачи ждали часами не из-за плохого выбора ветки, а из-за исчерпанного пула.
 - [ ] **Наша история мержей — готовый источник правил для промптов, и мы его ни разу не выгребали.** Подсказал подход пост DevFM 17.09: они собрали замечания из старых пиаров и чатов с агентами и превратили в AGENTS.md и скиллы. Первый проход по нашим данным сделан в тот же день: из 1571 операции мержа 410 несут код ошибки, и это не разовые случаи, а повторяющиеся грабли. Разбивка: `session has no bound task` 57 (с 25.08), `DIFF TOO LARGE` 52 (с 16.08), `WAITING` 57, `CONFLICT` 55, `TEST_GATE_FAILED` 40, `TARGET_DIRTY` 32, `NO_COMMITS_MERGED` 30, `TEST_GATE_INCONCLUSIVE` 24, `WORKER_DIRTY` 21, `SESSION_IDENTITY_CHANGED` 13, `POST_COMMIT_PARTIAL` 9. Каждая строка — кандидат в правило, которое сейчас живёт в голове оркестратора и повторяется в каждой постановке руками: сегодня я трижды писал воркерам «дерево должно быть чистым» и «мутация обязана краснить ровно нужный тест». Что делать: (1) по каждому коду решить, чинится он ПРАВИЛОМ в промпте, ТЕКСТОМ отказа или КОДОМ платформы — `WORKER_DIRTY` и `DIFF TOO LARGE` явно первое, `session has no bound task` и `SESSION_IDENTITY_CHANGED` явно третье; (2) правила, которые останутся, класть в существующие модули, а не плодить новый файл; (3) не превращать это в предписание маршрута — измерено V-548/V-550, что предписанный способ дороже в 7.5–8.8 раза. Данные берутся одним запросом к `merge_operations.result_json`; повторить перед правкой, числа устаревают.
 - [ ] **`merge_worker(task_outcome="continue")` — ловушка: прогон задачи остаётся открытым, а закрыть его нечем, если мержить больше нечего.** Репорт cog-second-brain-orchestrator 16.09 (воркер `balatro-vps`, task_run `ce47fdb1`, операции `0e7acb97` и `894b296c` обе FAILED). Механизм подтверждён по коду: у сессии допускается РОВНО ОДИН открытый `task_run` (`review_receipts`, `subject_kind='task_run'`, `status='requested'`), и `task_run_receipt_open` (`app/db.py:1331-1381`) отказывает `ValueError: open task run conflicts with current assignment provenance`, когда открывают прогон другой задачи. Закрывается прогон единственным путём — `_finish_task_run_for_task` (`app/tm.py:735-760`) на успешном мерже с `complete`. Отсюда тупик: после `continue` ветка воркера и main стоят на одном коммите, `merge_worker(complete)` отбивается `NO_COMMITS_MERGED` ДО закрытия прогона, а `switch_worker_branch` откатывается на той же ValueError, причём `force=True` не помогает — отказ приходит из слоя квитанций, а не из слоя веток. Штатного выхода нет; чужой оркестратор вышел через `send_message` с новым task_id и получил расщеплённое состояние: `get_worker_info` отдаёт старую задачу и старую ветку, `list_agents` показывает три задачи `in_progress`, коммиты новой задачи идут в ветку старой. Чинить одним из двух: либо `switch_worker_branch` закрывает предыдущий прогон как `superseded`, либо `complete` закрывает прогон и тогда, когда коммитов нет (пустой мерж — законный способ снять задачу с воркера). Обход, который работает уже сейчас и его стоит назвать в тексте отказа: дать воркеру доделать и закоммитить, тогда мерж с `complete` проходит и закрывает прогон.
 - [ ] **Astra недоступна нашему аккаунту, но остаётся маршрутом по умолчанию для сложных задач.** 16.09 спавн воркера на `gpt-6-astra` сжёг ход и умер до первой строки: провайдер ответил 400 `The 'gpt-6-astra' model is not supported when using Codex with a ChatGPT account` (дважды, затем `turn FAILED: error`). Задание до воркера не доехало вообще. При этом модуль model-routing объявляет Astra классом сложности, а каталог моделей её показывает — то есть платформа предлагает агенту модель, которой у аккаунта нет, и узнаётся это только сожжённым ходом. Смежное: два живых воркера (`bench-master`, `prompt-engineer`) сидят на этой же модели и при первом же сообщении получат то же самое. Чинить в сторону «каталог знает, что доступно аккаунту»: либо проверка при спавне с внятным отказом, либо снятие Astra из маршрутизации до выяснения. ПРИЧИНА УСТАНОВЛЕНА В ТОТ ЖЕ ДЕНЬ: подписка Codex отменена владельцем намеренно («чтобы за доллары потом оплатить»), и телеметрия провайдера показывает переход `plan_type` pro → free в 11:03 UTC 16.09; окно стало 30-дневным (43200 мин, сброс 16.10), Astra на free не поддерживается вовсе. То есть это не дефект каталога сам по себе, а отсутствие проверки «доступна ли модель этому плану»: узнаётся только сожжённым ходом. Масштаб free-окна для планирования: один ход Luna (8.03М входных токенов) дал 10% окна. Отдельно проверить, не то же ли это, что #520.
 - [ ] **ЖДЁТ РЕСТАРТА ВЛАДЕЛЬЦА — семь готовых правок и два мёртвых воркера (на 12.09.2026).** Всё смержено в main и проверено, но Python в живом процессе не меняется: (1) офлайн-миграция БД под #V-544, отдельная задача #V-545 с командами; (2) #V-543 утечка pidfd; (3) `bec4f378` отказ merge_worker на переименованиях; (4) #V-546 потолок полос sol=95; (5) #V-540 стабильный системный промпт; (6) `QUOTA_GATED_LANES=claude,sol` — 15.09 владелец дословно сказал «включай общий гейт снова на лимиты», `.env` поправлен, но живой процесс стартовал с пустым значением и до рестарта гейт остаётся снятым со всех полос; (7) #V-547 индикатор состояния гейта — до рестарта панель честно пишет «гейт: нет данных». Воркеры `fix-stuck-writer` и `fix-prompt-cache` висят `broken` («Codex thread already has an active writer») — их работа смержена, но сессии оживит только рестарт.
 - [ ] **Тест-гейт мержа гоняет тесты в ВЕТКЕ ВОРКЕРА, а исправление красноты лежит в main — ветка чинится только подтягиванием main.** 11.09: мерж #V-546 отбит трижды. Первые два раза — по чужим дефектам (запись «upper» в боевом хранилище задач; протёкший `QUOTA_GATED_LANES=` плюс снапшот маршрутов, отставший от `f5713f4d`). Я починил оба в main коммитом `52f7c97d` и повторил мерж — гейт выдал ТЕ ЖЕ 16 красных, потому что тестирует он ветку, где `tests/conftest.py` старый. Практический вывод: **когда гейт краснеет на чужом дефекте, чинить надо не только main — воркеру нужно отдельно подтянуть main к себе**, иначе цикл «починил → отбито → починил» повторяется. Стоит проверить, не должен ли гейт тестировать РЕЗУЛЬТАТ слияния, а не голую ветку: сейчас он отвечает на вопрос «зелена ли ветка», а решение принимается о том, «зелен ли main после мержа», и это разные вопросы.
### 20036a865 TODO: изучить два приёма приёмки из security-audit-skill Cloudflare

diff --git a/TODO.md b/TODO.md
index fd7759db2..8fa757905 100644
--- a/TODO.md
+++ b/TODO.md
@@ -82,10 +82,11 @@
 - [ ] **`merge_worker` в состоянии PENDING читается агентами как провал, потому что объяснение уходит в поле, которого рантайм не показывает.** 12.09 оркестратор портфеля отрапортовал «❌ merge worker failed» на мерже, который через секунды пришёл `SUCCEEDED`. Платформа ведёт себя правильно: `PENDING` + `completion.job_id` означает «принято, идёт в фоне, выполнится и разбудит», и с 05.09 (`b0f32897`) для этого случая формируется прямой текст «STILL PENDING — NOT a failure… Do not poll or call merge_worker again». Дефект в доставке этого текста: `mcp_tool_result` кладёт его в `content[].text`, а рядом отдаёт `structuredContent` с сырым результатом — и Claude-рантайм показывает агенту ИМЕННО структуру. Я сам за сегодня сделал больше десяти мержей и ни разу не увидел этой строки, только JSON с `operation_state: PENDING`. Отсюда и повторяющаяся ошибка: агент видит «не SUCCEEDED» и называет это провалом. Чинить надо в структуре, а не в тексте: нетерминальное состояние обязано читаться из самого объекта (например, явным полем вида «это не отказ, исход придёт фоновым событием»), иначе следующий агент прочитает так же. Комментарий в коде `app/mcp_stdio.py` про прошлый заход подтверждает, что правка формулировки уже делалась и проблему не сняла.
 - [x] **`merge_worker` отбивал 409 SESSION_IDENTITY_CHANGED в цикле, из которого нет выхода предписанным способом — ПОЧИНЕНО #V-575, ждёт рестарта владельца** (`.orchestra/tasks/V-575/report.md`). При расхождении спрашивается git: совпал с закреплённой веткой И HEAD → `sessions.branch` приводится в соответствие и мерж идёт; иначе отказ, называющий все три стороны и рабочий выход. `next_action` стал `INSPECT_WORKER_THEN_NEW_OPERATION`. Первопричина (обнуление `task_id` с уходом ветки в `adhoc-<ts>/<имя>`) НЕ чинилась и остаётся отдельной работой. Исходный разбор: Репорт seedon-orchestrator 15.09 (запись `20260915T101900...`, проект seedon): пять операций на одном готовом результате, из них три FAILED с одним и тем же текстом. Разобрал по коду: сравниваются ДВЕ ЗАПИСИ ПЛАТФОРМЫ, git не спрашивают вовсе — `app/routes/sessions.py:2054` сверяет `expected_branch` операции (`task-256/...`, закреплён при приёме) с `row_branch`, то есть колонкой `sessions.branch` (`adhoc-<ts>/...`). Предписанный `next_action` REFRESH_WORKER_THEN_NEW_OPERATION зовёт `worker_wip`, а тот ходит в `/api/sessions/{name}/wip` → `branch_wip_status`, который ТОЛЬКО читает git и ничего не пишет в `sessions.branch` (`app/routes/sessions.py:3113`). Обе стороны сравнения после «починки» те же — отказ воспроизводится побайтово, сколько ни повторяй. Побочный эффект: оркестратор со стороны подгоняет git под устаревшую строку БД (`git branch -f adhoc-...`), то есть чинит правильное состояние по неправильному. Второй слой: сверка ветки с РЕАЛЬНЫМ worktree (`app/routes/sessions.py:2158-2176`) выполняется только когда `expected_head` НЕ передан — аккуратный вызывающий получает менее согласованный путь, чем небрежный. Замер 15.09 по живой БД (`ORCHESTRA_DB_PATH` MainPID 1016880, read-only, 58 неархивных сессий): расхождений `sessions.branch` ↔ фактическая ветка worktree сейчас **ноль**, но это НЕ здоровье популяции — обе пострадавшие сессии seedon к моменту замера уже подогнали руками под запись БД. Предложенный репортёром детектор «`branch LIKE 'adhoc-%'` при наличии привязанной задачи» не находит ничего и находить не может: дефект обнуляет `task_id`. Рабочий признак — `branch LIKE 'adhoc-%' AND task_id=''`: таких сессий **10**, из них **7 в одном seedon** (`marketer`, `seo-cro`, `sales`, `designer`, `direct-research`, `accountant`, `demand-audit`), остальные в dnd-game-master, katya-work, comfy-image-pipeline. Каждая из них воспроизведёт тот же 409 при первом мерже с ожиданием task-ветки. Чинить в сторону «git — источник правды о ветке»: при расхождении спросить worktree, и если он совпал с закреплённой веткой и `expected_head`, привести `sessions.branch` в порядок и продолжить; иначе отказывать СИНХРОННО, называя, какая сторона из БД, а какая из git, и предлагая существующий инструмент ремонта.
 - [ ] **Красный на main, не связан с правками фронта: `tests/test_frontend.py::test_photo_batch_renders_as_compact_expandable_gallery`.** Проверено 17.09 на чистом main (без правок #V-584): падает так же, ошибка приходит из `playwright/_impl/_connection.py:559`. Остальные 129 браузерных тестов зелёные. При прогоне фронта не принимать за свою регрессию; чинить отдельно, начиная с того, что именно роняет соединение Playwright в этом тесте.
 - [ ] **`__pycache__` под `.orchestra/` не игнорируется: правило-исключение перебивает общий шаблон.** Проверено 17.09 самостоятельно: `git check-ignore -v .orchestra/tasks/V-583/__pycache__/probe.pyc` отвечает `.gitignore:26:!.orchestra/**`, то есть негативное правило для `.orchestra/**` сильнее `__pycache__/` из первой строки. Практическое следствие: любой скрипт под `.orchestra/`, который импортирует соседний модуль, оставляет неотслеженный каталог, а тот отбивает мерж воркера с `WORKER_DIRTY` — так на #V-583 сгорела целая операция и лишний ход воркера. Лечится одной строкой `.orchestra/**/__pycache__/` после 26-й; это общий конфиг, поэтому отдельным решением, а не внутри чужой задачи.
 - [x] **Оба зашитых харнес-маршрута мертвы, и наш валидатор этого не видит — ПОЧИНЕНО #V-582, ждёт рестарта владельца** (`.orchestra/tasks/V-582/report.md`). Харнес-маршруты убраны из `SELECTABLE_MODEL_SPECS` и приходят только из живого каталога; `validate_harness_model_spec` решает по записи провайдера (`live_catalog_entry`/`harness_capable` в `app/model_catalog.py`), а не по нашему `supported_parameters`. Проба стала инструментом — `scripts/probe_free_models.py`. ОСТАЛОСЬ ОТДЕЛЬНО: `thinkingmachines/inkling*:free` (1M) отдают 403 «only available on agentic harnesses» — нужна регистрация приложения в OpenRouter, обычный ключ не пускают. Замер 17.09 показал и второе: состав прошедших маршрутов переворачивается за сутки (nemotron-3-ultra 16.09 игнорировал результат инструмента, 17.09 прошёл за 4.5 с; nemotron-3.5-lightning наоборот), то есть разовая проба — снимок, а не приговор. Исходный разбор: **Оба зашитых харнес-маршрута мертвы, и наш валидатор этого не видит.** Замер 16.09 (`.orchestra/tasks/V-581/probe.log`, две попытки на маршрут): `z-ai/glm-5.2:free` в живом каталоге OpenRouter отдаёт `tools=False` и `ctx=32768` против наших 256000, а `nvidia/nemotron-3-ultra-550b-a55b:free` вызывает инструмент, но ИГНОРИРУЕТ его результат — воркером быть не может. Корень: `validate_harness_model_spec` (`app/models.py:364-381`) проверяет НАШЕ статическое поле `supports_tools`, а не живые данные провайдера, поэтому протухание маршрута незаметно до сожжённого хода. Из 18 `:free` маршрутов с заявленным `tools` полный протокол (вызов → результат → ответ по результату) прошли 9: nemotron-3.5-lightning (1M), dots-3-note-preview (512k), ling-3.0-flash-sante, ling-3.0-flash-fin, nemotron-3-super-120b, cohere/north-mini-code, liquid/lfm-2.5-2.6b, gemma-4-26b и nex-n2.5-pro (последние два — со второй попытки). Отдельный класс: `thinkingmachines/inkling*` (1M) отдают 403 «only available on agentic harnesses» — нужна регистрация приложения, обычный ключ не пускают.
+- [ ] **ИЗУЧИТЬ: два приёма приёмки из `cloudflare/security-audit-skill` — годятся ли они нам вне безопасности.** Скилл сам по себе нам не нужен (полный аудит чужой системы, 12 доменных гайдов, требование OS-песочницы с отключённой сетью, параллельные субагенты), но внутри лежат два правила приёмки, которые сильнее наших и к безопасности отношения не имеют. Первое: **подтверждает находку не тот, кто её нашёл** — у них проверяющий агент отдельный от обнаружившего. У нас наоборот: исполнитель сам себе автор и проверяющий, а ловит расхождение только оркестратор на приёмке мутацией. Второе: **жёсткое определение «подтверждено»** — полная трасса от источника до эффекта плюс наблюдаемый результат; всё остальное уходит в `needs_validation` БЕЗ присвоения серьёзности. У нас в отчётах регулярно появляется «я проверил» без артефакта, и это ловится вручную. Третьим идёт их честная оговорка, которой у нас нет нигде: один прогон находит примерно половину того, что находят повторные прогоны суммарно — у нас любой единичный прогон по умолчанию считается исчерпывающим. Что именно изучить, прежде чем тащить: цена. Отдельный проверяющий агент — это целый ход, а наше узкое место сейчас квота, а не качество проверки (17.09 три задачи ждали часами из-за исчерпанного пула). Возможный дешёвый вариант — не второй агент, а требование к ФОРМЕ доказательства в отчёте, которое проверяю я на приёмке. Источник: https://github.com/cloudflare/security-audit-skill, изучено по README 17.09.2026.
 - [ ] **РЕСЕРЧ: можно ли перебирать стратегии оркестрации по своей истории, как Dream-RSI (arXiv 2609.14858).** Идея: дерево уже выполненных попыток с записанными исходами превращается в бесплатный симулятор — новые стратегии («сколько попыток, когда останавливаться, кого звать») гоняются по нему без единого нового вызова модели. Разбор статьи сделал Кеша 17.09 (`/opt/cog-second-brain/05-knowledge/2026-09-17-dream-rsi-google.md`), и его поправка существенна: заявленные «162×» получены против заведомо расточительного бейзлайна, честная цифра против вменяемого — 1.7×; раздела ограничений в статье нет вовсе. Что я проверил по НАШИМ данным в тот же день: задач с записанными операциями мержа 370, из них с двумя и более попытками 164, с разными воркерами на одной задаче 87; исходов 1134 успешных против 408 отказов. Вывод двойной. Применимо к выбору момента остановки и числа повторов при мерже — там дерево «попытка → исход» настоящее и достаточно большое. НЕ применимо к выбору модели и маршрута: у 206 задач из 370 ровно одна попытка, ветвиться нечем, а редкие настоящие ветвления (V-548/V-550 — пять моделей на одной задаче) единичны. Ограничение метода, названное в самой статье («no outcomes beyond T_i are generated»), бьёт по нам прямо: стратегия, уводящая в неисследованное, на реплее выглядит хуже, чем она есть, поэтому метод будет уверенно улучшать то, как мы уже работаем, и слеп к тому, чего мы не пробовали. Дешёвый первый шаг, если браться: не строить симулятор, а начать СОХРАНЯТЬ дерево — задача, попытка, модель, исход, цена; половина полей уже пишется в `merge_operations` и квитанциях приёмки, не хватает связки «альтернативная попытка того же результата». Честная оценка ценности сейчас: наше узкое место — квота, а не стратегия поиска; 17.09 три задачи ждали часами не из-за плохого выбора ветки, а из-за исчерпанного пула.
 - [ ] **Наша история мержей — готовый источник правил для промптов, и мы его ни разу не выгребали.** Подсказал подход пост DevFM 17.09: они собрали замечания из старых пиаров и чатов с агентами и превратили в AGENTS.md и скиллы. Первый проход по нашим данным сделан в тот же день: из 1571 операции мержа 410 несут код ошибки, и это не разовые случаи, а повторяющиеся грабли. Разбивка: `session has no bound task` 57 (с 25.08), `DIFF TOO LARGE` 52 (с 16.08), `WAITING` 57, `CONFLICT` 55, `TEST_GATE_FAILED` 40, `TARGET_DIRTY` 32, `NO_COMMITS_MERGED` 30, `TEST_GATE_INCONCLUSIVE` 24, `WORKER_DIRTY` 21, `SESSION_IDENTITY_CHANGED` 13, `POST_COMMIT_PARTIAL` 9. Каждая строка — кандидат в правило, которое сейчас живёт в голове оркестратора и повторяется в каждой постановке руками: сегодня я трижды писал воркерам «дерево должно быть чистым» и «мутация обязана краснить ровно нужный тест». Что делать: (1) по каждому коду решить, чинится он ПРАВИЛОМ в промпте, ТЕКСТОМ отказа или КОДОМ платформы — `WORKER_DIRTY` и `DIFF TOO LARGE` явно первое, `session has no bound task` и `SESSION_IDENTITY_CHANGED` явно третье; (2) правила, которые останутся, класть в существующие модули, а не плодить новый файл; (3) не превращать это в предписание маршрута — измерено V-548/V-550, что предписанный способ дороже в 7.5–8.8 раза. Данные берутся одним запросом к `merge_operations.result_json`; повторить перед правкой, числа устаревают.
 - [ ] **`merge_worker(task_outcome="continue")` — ловушка: прогон задачи остаётся открытым, а закрыть его нечем, если мержить больше нечего.** Репорт cog-second-brain-orchestrator 16.09 (воркер `balatro-vps`, task_run `ce47fdb1`, операции `0e7acb97` и `894b296c` обе FAILED). Механизм подтверждён по коду: у сессии допускается РОВНО ОДИН открытый `task_run` (`review_receipts`, `subject_kind='task_run'`, `status='requested'`), и `task_run_receipt_open` (`app/db.py:1331-1381`) отказывает `ValueError: open task run conflicts with current assignment provenance`, когда открывают прогон другой задачи. Закрывается прогон единственным путём — `_finish_task_run_for_task` (`app/tm.py:735-760`) на успешном мерже с `complete`. Отсюда тупик: после `continue` ветка воркера и main стоят на одном коммите, `merge_worker(complete)` отбивается `NO_COMMITS_MERGED` ДО закрытия прогона, а `switch_worker_branch` откатывается на той же ValueError, причём `force=True` не помогает — отказ приходит из слоя квитанций, а не из слоя веток. Штатного выхода нет; чужой оркестратор вышел через `send_message` с новым task_id и получил расщеплённое состояние: `get_worker_info` отдаёт старую задачу и старую ветку, `list_agents` показывает три задачи `in_progress`, коммиты новой задачи идут в ветку старой. Чинить одним из двух: либо `switch_worker_branch` закрывает предыдущий прогон как `superseded`, либо `complete` закрывает прогон и тогда, когда коммитов нет (пустой мерж — законный способ снять задачу с воркера). Обход, который работает уже сейчас и его стоит назвать в тексте отказа: дать воркеру доделать и закоммитить, тогда мерж с `complete` проходит и закрывает прогон.
 - [ ] **Astra недоступна нашему аккаунту, но остаётся маршрутом по умолчанию для сложных задач.** 16.09 спавн воркера на `gpt-6-astra` сжёг ход и умер до первой строки: провайдер ответил 400 `The 'gpt-6-astra' model is not supported when using Codex with a ChatGPT account` (дважды, затем `turn FAILED: error`). Задание до воркера не доехало вообще. При этом модуль model-routing объявляет Astra классом сложности, а каталог моделей её показывает — то есть платформа предлагает агенту модель, которой у аккаунта нет, и узнаётся это только сожжённым ходом. Смежное: два живых воркера (`bench-master`, `prompt-engineer`) сидят на этой же модели и при первом же сообщении получат то же самое. Чинить в сторону «каталог знает, что доступно аккаунту»: либо проверка при спавне с внятным отказом, либо снятие Astra из маршрутизации до выяснения. ПРИЧИНА УСТАНОВЛЕНА В ТОТ ЖЕ ДЕНЬ: подписка Codex отменена владельцем намеренно («чтобы за доллары потом оплатить»), и телеметрия провайдера показывает переход `plan_type` pro → free в 11:03 UTC 16.09; окно стало 30-дневным (43200 мин, сброс 16.10), Astra на free не поддерживается вовсе. То есть это не дефект каталога сам по себе, а отсутствие проверки «доступна ли модель этому плану»: узнаётся только сожжённым ходом. Масштаб free-окна для планирования: один ход Luna (8.03М входных токенов) дал 10% окна. Отдельно проверить, не то же ли это, что #520.
 - [ ] **ЖДЁТ РЕСТАРТА ВЛАДЕЛЬЦА — семь готовых правок и два мёртвых воркера (на 12.09.2026).** Всё смержено в main и проверено, но Python в живом процессе не меняется: (1) офлайн-миграция БД под #V-544, отдельная задача #V-545 с командами; (2) #V-543 утечка pidfd; (3) `bec4f378` отказ merge_worker на переименованиях; (4) #V-546 потолок полос sol=95; (5) #V-540 стабильный системный промпт; (6) `QUOTA_GATED_LANES=claude,sol` — 15.09 владелец дословно сказал «включай общий гейт снова на лимиты», `.env` поправлен, но живой процесс стартовал с пустым значением и до рестарта гейт остаётся снятым со всех полос; (7) #V-547 индикатор состояния гейта — до рестарта панель честно пишет «гейт: нет данных». Воркеры `fix-stuck-writer` и `fix-prompt-cache` висят `broken` («Codex thread already has an active writer») — их работа смержена, но сессии оживит только рестарт.
### 75cd5bec4 #V-592: changelog

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 850d50e09..e1bf29835 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -29,10 +29,23 @@
   (`tests/test_frontend.py`, `tests/test_t344_quota_lines_browser.py`) проверяет
   английские подписи и пришпилен к английской локали через `window.__ORCH_LANG__` —
   его ожидания остались дословно прежними.
 
 ### Fixed
+- 🔁 **Временная перегрузка провайдера больше не убивает ход воркера целиком**
+  (`app/harness/llm.py` — `_StreamError` и ветка повтора в `OpenRouterClient.stream`).
+  OpenRouter отдаёт перегрузку апстрима не статусом, а обычным SSE-чанком с полем
+  `error` уже при 200 OK («Upstream error from Nvidia: Service temporarily overloaded»,
+  «Upstream idle timeout exceeded»), поэтому прежний ретрай по 429/5xx её не видел.
+  Повтор разрешён ровно до первого отданного события и только для заведомо временных
+  ошибок (код 5xx/408/409/429 либо текст про перегрузку, таймаут, недоступность);
+  отданное событие или нетранзиентная ошибка вроде исчерпанных кредитов — честный отказ.
+  *Triggered case:* вечером 17.09 пять воркеров на бесплатном маршруте
+  `nvidia/nemotron-3-ultra-550b-a55b:free` потеряли так 13 ходов, каждый раз вместе
+  с несохранённой работой; ошибок 429 при этом не было ни одной.
+  *Known tradeoff:* повтор не спасает, если модель успела отдать текст или вызов
+  инструмента — дублировать побочные действия опаснее, чем потерять ход.
 - 🧭 **Допуск харнес-маршрута решается по живому каталогу OpenRouter, а не по нашей
   записи о нём** (`app/models.py` — `validate_harness_model_spec`, из
   `SELECTABLE_MODEL_SPECS` убраны оба зашитых харнес-маршрута; `app/model_catalog.py` —
   `live_catalog_entry`, `harness_capable` вместо приватного `_cached_harness_eligible`).
   Отказ наступает, когда провайдер говорит «нет tools» или маршрут исчез из каталога,
### 67ee5df03 #V-593: блокировка бесплатных маршрутов, отказавших в нашей пробе

diff --git a/app/model_catalog.py b/app/model_catalog.py
index cb2320cf0..1f9b55e49 100644
--- a/app/model_catalog.py
+++ b/app/model_catalog.py
@@ -131,14 +131,18 @@ def apply_model_catalog() -> int:
     capabilities/context for manifest fallbacks. Returns registrations this run;
     per-model failures are counted in `_LAST_APPLY_STATS['dropped']`.
     """
     from app.models import MODEL_SPECS, ModelSpec, SELECTABLE_MODEL_SPECS, register_model
 
+    from app.models import BLOCKED_HARNESS_ROUTES
+
     manifest = {spec.id: spec for spec in SELECTABLE_MODEL_SPECS}
+    # Отказавший в пробе маршрут не доходит и до выбора: иначе его видно в списке моделей,
+    # и отказ наступает только на спавне, уже потратив ход.
     eligible = {
         norm["id"]: norm for norm in cached_catalog()
-        if harness_capable(norm)
+        if harness_capable(norm) and norm.get("id") not in BLOCKED_HARNESS_ROUTES
     }
     registered = dropped = 0
     for norm in eligible.values():
         declared = manifest.get(norm["id"])
         spec = ModelSpec(
diff --git a/app/models.py b/app/models.py
index 001805e88..b82e7604d 100644
--- a/app/models.py
+++ b/app/models.py
@@ -342,10 +342,25 @@ def register_model(spec: ModelSpec, *, replace: bool = False) -> None:
         raise ValueError(f"model '{spec.id}' is already registered")
     MODEL_SPECS[spec.id] = spec
     _apply_derived_views(spec)
 
 
+# Маршруты, отказавшие в НАШЕЙ пробе (#V-581, повторный прогон 17.09.2026): каталог
+# провайдера продолжает обещать инструменты, но воркер на них не работает. Каждая строка —
+# наблюдение, а не мнение; появится противоположный замер — снимать по одной, не списком.
+BLOCKED_HARNESS_ROUTES: dict[str, str] = {
+    "thinkingmachines/inkling:free": "HTTP 403: маршрут открыт только в харнесах провайдера",
+    "thinkingmachines/inkling-small:free": "HTTP 403: маршрут открыт только в харнесах провайдера",
+    "poolside/laguna-s-2.1:free": "HTTP 429 в обоих прогонах пробы",
+    "poolside/laguna-xs-2.1:free": "HTTP 429 в обоих прогонах пробы",
+    "google/gemma-4-31b-it:free": "HTTP 429 в обоих прогонах пробы",
+    "nex-agi/nex-n2.5-mini:free": "таймаут чтения 90 с в обоих прогонах",
+    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": "инструмент не вызывается вовсе",
+    "inclusionai/ling-3.0-flash-vl:free": "вызывает инструмент и игнорирует его результат",
+}
+
+
 def validate_harness_model_spec(spec: ModelSpec) -> None:
     """Production admission for Orchestra's OpenRouter runtime.
 
     Decided on the provider's own catalog record, never on our copy of it: a route that
     lost tool support or vanished upstream must be refused even while our spec still
@@ -354,10 +369,15 @@ def validate_harness_model_spec(spec: ModelSpec) -> None:
     outside those fields. The `:free` suffix is the provider's explicit routing contract.
     Tool support is mandatory because Harness is an agent runtime, not a chat wrapper.
     """
     if spec.runtime != "harness":
         raise ValueError(f"model '{spec.id}' is not a harness model")
+    if spec.id in BLOCKED_HARNESS_ROUTES:
+        raise ValueError(
+            f"harness model '{spec.id}' заблокирован по результатам нашей пробы: "
+            f"{BLOCKED_HARNESS_ROUTES[spec.id]}"
+        )
     if not spec.id.endswith(":free"):
         raise ValueError(
             f"harness model '{spec.id}' is not an exact :free route; "
             "unsuffixed previews and paid routes are blocked"
         )
diff --git a/tests/test_model_catalog.py b/tests/test_model_catalog.py
index 9235a2f22..f2226a791 100644
--- a/tests/test_model_catalog.py
+++ b/tests/test_model_catalog.py
@@ -286,5 +286,28 @@ def test_t2_admission_passes_route_the_live_catalog_still_backs():
 
     _seed_cache()
     assert _catalog_module().apply_model_catalog() == 1
 
     registry.validate_harness_model_spec(registry.MODEL_SPECS["vendor/model-x:free"])
+
+
+def test_blocked_route_is_refused_and_never_registered():
+    """#V-593: маршрут, отказавший в нашей пробе, каталог провайдера по-прежнему
+    рекламирует как рабочий. Он не должен ни попадать в выбор, ни проходить спавн."""
+    import app.models as registry
+    from app.model_catalog import apply_model_catalog
+
+    blocked_id = next(iter(registry.BLOCKED_HARNESS_ROUTES))
+    blocked_row = {**NORMALIZED, "id": blocked_id, "name": "Blocked Route"}
+    db.kv_set(CATALOG_KV_KEY, json.dumps(
+        {"fetched_at": 1726500000.0, "models": [blocked_row, NORMALIZED]}))
+
+    apply_model_catalog()
+    assert blocked_id not in registry.MODEL_SPECS, "заблокированный маршрут попал в выбор"
+    assert NORMALIZED["id"] in registry.MODEL_SPECS, "здоровый маршрут потерян вместе с ним"
+
+    spec = registry.ModelSpec(
+        id=blocked_id, name="Blocked Route", runtime="harness", provider="openrouter",
+        context_length=128000, price_input=0.0, price_output=0.0,
+        supported_parameters=("tool_choice", "tools"))
+    with pytest.raises(ValueError, match="заблокирован"):
+        registry.validate_harness_model_spec(spec)
### ddfde793a #V-593: changelog

diff --git a/CHANGELOG.md b/CHANGELOG.md
index e1bf29835..6d37037f2 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -29,10 +29,24 @@
   (`tests/test_frontend.py`, `tests/test_t344_quota_lines_browser.py`) проверяет
   английские подписи и пришпилен к английской локали через `window.__ORCH_LANG__` —
   его ожидания остались дословно прежними.
 
 ### Fixed
+- 🚫 **Бесплатные маршруты, отказавшие в нашей пробе, больше не предлагаются и не
+  проходят спавн** (`app/models.py` — `BLOCKED_HARNESS_ROUTES` и проверка в
+  `validate_harness_model_spec`; `app/model_catalog.py` — фильтр в `apply_model_catalog`).
+  Каталог OpenRouter продолжает рекламировать у них поддержку инструментов, поэтому
+  допуск по живому каталогу (#V-582) их пропускал. Заблокированы восемь: `inkling`
+  и `inkling-small` (HTTP 403 — открыты только в харнесах провайдера), `laguna-s-2.1`,
+  `laguna-xs-2.1`, `gemma-4-31b-it` (HTTP 429 в обоих прогонах), `nex-n2.5-mini`
+  (таймаут чтения 90 с), `nemotron-3-nano-omni-...-reasoning` (инструмент не вызывается),
+  `ling-3.0-flash-vl` (вызывает и игнорирует результат).
+  *Triggered case:* проба #V-581 и повторный прогон 17.09.2026; отказ наступал только
+  на спавне, уже потратив ход воркера.
+  *Reasoning:* блок стоит в двух точках, потому что одной регистрации мало — маршрут
+  может прийти из сохранённой сессии, минуя выбор моделей. Снимается по одной строке
+  при обратном замере, не списком.
 - 🔁 **Временная перегрузка провайдера больше не убивает ход воркера целиком**
   (`app/harness/llm.py` — `_StreamError` и ветка повтора в `OpenRouterClient.stream`).
   OpenRouter отдаёт перегрузку апстрима не статусом, а обычным SSE-чанком с полем
   `error` уже при 200 OK («Upstream error from Nvidia: Service temporarily overloaded»,
   «Upstream idle timeout exceeded»), поэтому прежний ретрай по 429/5xx её не видел.
### e0b09617a #V-596: changelog

diff --git a/CHANGELOG.md b/CHANGELOG.md
index 6d37037f2..7c64a5170 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -29,10 +29,20 @@
   (`tests/test_frontend.py`, `tests/test_t344_quota_lines_browser.py`) проверяет
   английские подписи и пришпилен к английской локали через `window.__ORCH_LANG__` —
   его ожидания остались дословно прежними.
 
 ### Fixed
+- 🧯 **Один кривой вызов инструмента больше не убивает остаток сессии воркера**
+  (`app/harness/loop.py` — `_sanitize_tool_args`, вызывается после диспетча раунда).
+  Ассистентский месседж с `tool_calls` уезжает в КАЖДЫЙ следующий запрос, а строгий
+  провайдер отвергает весь запрос, если аргументы хоть одного вызова — не строка-объект
+  JSON: Cohere отвечает `invalid tool call provided in messages[42].tool_calls[0]: tool
+  arguments must be a stringified JSON object`. Разбор и сообщение об ошибке уже
+  происходят при вызове инструмента, поэтому в истории негодное значение заменяется
+  на `{}`; валидный объект не переформатируется — он уезжает рядом с подписью рассуждений.
+  *Triggered case:* 17.09.2026 воркер на `cohere/north-mini-code:free` после одного
+  такого вызова не смог сделать больше ни одного хода.
 - 🚫 **Бесплатные маршруты, отказавшие в нашей пробе, больше не предлагаются и не
   проходят спавн** (`app/models.py` — `BLOCKED_HARNESS_ROUTES` и проверка в
   `validate_harness_model_spec`; `app/model_catalog.py` — фильтр в `apply_model_catalog`).
   Каталог OpenRouter продолжает рекламировать у них поддержку инструментов, поэтому
   допуск по живому каталогу (#V-582) их пропускал. Заблокированы восемь: `inkling`
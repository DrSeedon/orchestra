# #367 — План: починка тулов harness + экономия раундов

## Подход

Два корня у почти всех дефектов: (1) grep-тул — два внешних движка с разной семантикой,
выбираемые молча по `shutil.which` (D1–D3); (2) синхронные тулы, исполняемые прямо на
event loop сервера (D6). Лечим сведением grep к ОДНОМУ детерминированному питоновскому
движку и выносом синхронной работы в `asyncio.to_thread`. Read чинится точечно
(D4/D5/D7/D9/D10 — один файл, одна функция). Потолок раундов: 200 + wind-down-предупреждения.
Экономия запросов: флаг `parallel_tool_calls` (безвредный), ОДНА лёгкая фраза в промпте
(агрессивная проверена — ломает аргументы), главный числовой рычаг — сами фиксы тулов,
каждый «лжец» сегодня стоит лишних раундов на перепроверку.

## Что НЕ трогаем

- bash (проверен корректным), синтаксис-гард write/edit, атомарность записи,
  path-policy, READONLY_NAMES/reviewer-механику, REVIEW_MAX_ROUNDS=15, steering
  (e7dfa77d, только что влит).
- `app/backend_harness.py` — не наш файл.

## Порядок работ (утверждён оркестратором, 22.08)

1. **Группа A — дефекты-лжецы**: T1 (grep: D1–D3, C2, C5), T2 (read: D4, D5, D7, D9, D10).
2. **Группа B — event loop**: T5 (D6).
3. **Группа C — батчинг**: T7 (parallel_tool_calls + фраза) → T8 (замер «было N — стало M»).
4. **Группа D — потолок**: T6 (wind-down механизм сразу; ЧИСЛО выводится заново из
   распределения раундов ПОСЛЕ батчинга — медиана 19 намерена на однотуловой механике).
5. **T9** — наблюдаемость усечения истории `_fit_context` (новый тикет, находка фазы 1:
   тихая деградация контекста хуже громкого обрыва).
6. **T3 (D8 права файлов) — НА СОГЛАСОВАНИИ**, не чинить до одобрения оркестратором.
7. T4 (схема glob) — едет вместе с группой C.

## Tickets

### T1 — grep: один питоновский движок (D1, D2, D3, C2-контекст, C5-limit)
- Files: `app/harness/tools.py` (функция `grep`, схема в `tool_schemas`)
- Test: `tests/test_harness_tools.py::test_t1_*` — committed RED в этом же коммите, что и план
- AC: `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_harness_tools.py -k t1 -q` green:
  - `a|b` находит совпадения (сегодня: «(no matches)»);
  - `glob_filter="app/models.py"` возвращает ТОЛЬКО этот файл (сегодня: любые);
  - паттерн `-x` даёт `[grep error] ...`, а не «(no matches)»;
  - совпадение в non-UTF-8 текстовом файле либо показано, либо в ответе есть явная строка
    «skipped N non-UTF-8/binary files» (сегодня: молча исчезает);
  - `context=1` отдаёт по строке контекста вокруг совпадения;
  - `limit` в схеме и работает;
  - производительность: grep по дереву этого репозитория < 10 с (замер в тесте, потолок щедрый).
- Движок: `os.walk` + `re`; синтаксис паттерна — Python `re` (ЯВНО в описании схемы;
  BRE-привычка `a\|b` при переезде означает литерал `a|b` — поправить строку в KB после
  деплоя). Исключённые каталоги константой: `.git, __pycache__, node_modules, .venv, venv,
  dist, build, .mypy_cache, .ruff_cache, .pytest_cache, .tox, target, vendor`; файлы-бинарики
  (NUL в первых 8 КиБ) и >1 МиБ — пропускаются С ПОДСЧЁТОМ в хвосте ответа. Внешние rg/grep
  больше не вызываются никогда.
- Бюджет обхода 25 с по wall-clock: по истечении — частичная выдача + явная строка «search
  budget exhausted» (наследник старого timeout=30 внешних движков).
- `glob_filter` — сегментный матчинг якорем от cwd (Path.match): `app/*.py` НЕ матчит
  `app/sub/deep.py`.
- dispatch передаёт в grep новые параметры `context` и `limit` (иначе модель ставит их
  в схеме, а цикл молча режет до дефолтов).
- Мутационная проверка приёмки: вернуть внешний fallback одной правкой → тест t1 снова
  красный → откат.
- blocked-by: none

### T2 — read: честный (D4, D5, D7, D9, D10)
- Files: `app/harness/tools.py` (`read`, схема)
- Test: `tests/test_harness_tools.py::test_t2_*`
- AC: pytest -k t2 green:
  - UTF-8 файл, разрезанный байтовым потолком посимвольно, читается текстом, не «[binary]»;
  - файл >256 КиБ отдаётся с явной пометкой «truncated … of N bytes»;
  - `offset` = номер строки В ВЫДАЧЕ (1-based): offset=5 начинается со строки с меткой 5;
  - offset за EOF → `[read error] offset 100 past EOF (file has 5 lines)`, не «(empty)»;
  - FIFO/спецфайл → мгновенная ошибка «not a regular file», не блокировка;
  - из файла читается не более CAP+1 байт (проверка: 10 МиБ файл читается < 0.5 с).
- Бинарик определяется NUL-байтом в первых 8 КиБ (до декодирования), дальше decode
  с errors="replace".
- offset=0 — явный сентинел «с начала», задокументирован в схеме (старые 0-based вызовы
  не зависают неоднозначно); offset за пределами ОКНА усечённого файла пишет «truncated at
  N bytes; M lines in shown portion», а не «past EOF (file has N lines)» по окну.
- blocked-by: none

### T3 — write/edit: права и обратная связь (D8, C3)
- Files: `app/harness/tools.py` (`write`, `edit`)
- Test: `tests/test_harness_tools.py::test_t3_*`
- AC: pytest -k t3 green:
  - edit файла с mode 0755 сохраняет 0755 (сегодня: 0600);
  - новый файл создаётся с 0644;
  - успешный edit отвечает «replaced 1× in <path>» / «replaced 3× in <path> (replace_all)»,
    а не «wrote N chars».
- blocked-by: none

### T4 — glob: схема без капкана (C1, C5)
- Files: `app/harness/tools.py` (схема glob; поведение не менять)
- Test: `tests/test_harness_tools.py::test_t4_glob_schema_documents_recursion`
- AC: описание glob в схеме содержит якорь «**» с указанием, что `*.py` не рекурсивен;
  `limit` добавлен в схему и передаётся из dispatch.
- blocked-by: none

### T5 — dispatch: синхронные тула́ уходят с event loop (D6)
- Files: `app/harness/tools.py` (`dispatch`)
- Test: `tests/test_harness_tools.py::test_t5_dispatch_does_not_block_loop`
- AC: пока dispatch исполняет синхронный тул ~1 с, конкурентный `asyncio.sleep(0.01)` в том
  же цикле длится < 300 мс (сегодня: 2008 мс). bash не регрессирует (его тесты зелёные).
- Реализация: каждый sync-тул через `await asyncio.to_thread(...)`; bash как был.
- Гонка записи после распараллеливания: write/edit сериализуются общим `asyncio.Lock`
  в dispatch (сегодня inline-исполнение давало им атомарность относительно других сессий;
  bash остаётся вне лока — его гонки существовали и раньше, класс не новый).
- blocked-by: none

### T6 — wind-down механизм + потолок (ЧИСЛО — ПОСЛЕ батчинга, группа D)
- Files: `app/harness/loop.py` (`MAX_TOOL_ROUNDS`, `AgentLoop.run`)
- Test: `tests/test_harness_tools.py::test_t6_*`
- AC: pytest -k t6 green:
  - FakeLLM с бесконечными tool_calls, max_rounds=12: ровно 2 AgentEvent("warning")
    (при остатке 10 и 3), текст содержит число оставшихся и «wrap up»;
  - предупреждение живёт ТОЛЬКО внутри хода: после завершения run() в history НЕТ ни одного
    injected-сообщения (навсегда прилипший «осталось 3 раунда» в общей истории сессии —
    та же ложь «почти упёрся», которую ловим);
  - терминал `max_turns` по-прежнему ok=False после исчерпания.
- Текст предупреждения (VERBATIM): `[round guard] {n} tool rounds remain THIS TURN — wrap up
  and report your findings now.` Вставляется role="user", удаляется в finally по выходе из run().
- Значение MAX_TOOL_ROUNDS: НЕ фиксировать сейчас. После группы C вывести заново из
  распределения раундов на батчинг-механике и записать в report.md (было: 50, паритетный
  якорь 200 признан неподходящим порядком выбора).
- blocked-by: T8 (для числа; сам механизм — none)

### T9 — наблюдаемость усечения истории `_fit_context` (находка аддендума)
- Files: `app/harness/loop.py` (`_fit_context`), схема событий не меняется
- Test: `tests/test_harness_tools.py::test_t9_truncation_is_visible`
- AC: pytest -k t9 green: когда `_fit_context` реально режет историю (история > guard),
  цикл выдаёт AgentEvent("warning") с числом удалённых сообщений и это событие доезжает
  до статуса хода; когда усечения не было — события нет (негативная ветвь).
- Минимум по решению оркестратора: факт усечения видим снаружи. Вопрос «не теряет ли агент
  половину задания молча» остаётся открытым в docs/kb/harness-tools.md (Пробелы).
- blocked-by: none

### T7 — экономия запросов: флаг + одна фраза (пункт 2 юзера)
- Files: `app/harness/llm.py` (`_build_body`), `app/harness/prompts.py` (`_TOOL_GUIDELINES`)
- Test: `tests/test_harness_tools.py::test_t7_*`
- AC: pytest -k t7 green:
  - body с tools содержит `parallel_tool_calls: True` (без tools — не содержит);
  - `_TOOL_GUIDELINES` содержит якорь «independent» и «one reply».
- Фраза (VERBATIM): `Independent tool calls (several reads, several greps) go in ONE reply —
  each reply costs one API request.` Агрессивную форму («ALL in one response, in parallel»)
  НЕ применять: замер показал битые аргументы `{"path":"a.py","path":"b.py"}`.
- Страховка от привередливых провайдеров: 400 с упоминанием parallel_tool_calls в detail →
  один ретрай без ключа (llm.py уже ретраит 429/5xx — расширяем ту же точку).
- Для честности метрики: батчинг сокращает ЧИСЛО ЗАПРОСОВ, диспетчер исполняет вызовы
  раунда по-прежнему последовательно (loop.py `for tc in tool_calls`).
- blocked-by: none

### T8 — числовая приёмка экономии (не юнит-тест)
- Files: `docs/tasks/367/report.md`
- AC: в report.md записаны числа: раунды до/после на одном наборе задач (A/B/A/B,
  интерливинг), плюс батч-ставка «вызовов на раунд» по боевым сессиям до/после деплоя
  (сейчас 1.24). Оракул — число, не впечатление.
- blocked-by: T1, T2, T3, T4, T5, T6, T7

## Красные тесты

Коммитятся вместе с этим планом (`tests/test_harness_tools.py`), все падают по ПОВЕДЕНИЮ
(не ImportError). Первый падающий ассерт каждого тикета — в его Test-строке файла тестов.

## Риски

- Питоновский grep медленнее внешнего на огромных деревьях — потолок 10 с в AC T1,
  ранний выход после limit×4 совпадений.
- Смена семантики offset (T2) — ломает существующие вызовы с 0-based привычкой; схема
  обновляется синхронно, в бою харнесу меньше суток.
- parallel_tool_calls у части провайдеров может игнорироваться — флаг безвреден, замер A/B
  уже показал отсутствие регресса (3,3 против 4,3).

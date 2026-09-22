# V-614 — тень-гейт «DONE без прошедшей проверки после последней правки»

Реализация предложения из `.orchestra/tasks/V-613/research.md` §2.1, одобренного владельцем
(«да делай»). Только тень: вердикт пишется, доставка и поведение воркера не меняются.

## Добор: вердикт не должен светиться в пользовательском канале

Оркестратор указал дыру: строка `logs` (`type='done_gate_verdict'`) пишется в сессию ВОРКЕРА,
а `/api/sessions/<name>/logs` (`app/db.get_logs`) отдаёт все типы без фильтра — после рестарта
сырой JSON вердикта мог бы отрисоваться в чате воркера как обычная строка. Проверено два пути:

1. **Фронт** (`app/static/js/chat.js:3896` `addChatEntry`, единая точка рендера для всех вызовов
   `/api/sessions/<name>/logs` — `app.js:1200/1203/1307/2359`, `chat.js:1294`) — добавлена ранняя
   отсечка `if (type === 'done_gate_verdict') return;` сразу за уже существующей для
   `provider_limit` (та же природа: служебная телеметрия, не для чата). `node --check` — синтаксис
   ок. Отдельного браузерного (Playwright) теста не добавлял: правка симметрична уже принятому
   паттерну `provider_limit`, у которого своего теста в `tests/test_frontend.py` тоже нет —
   дешевле и надёжнее закрыть вопрос там, где уже есть готовый, быстрый (не-браузерный) гарнесс.
2. **Мост Telegram** (`app/tg_bridge.py::stream_logs`) — читает через `db.get_logs` без фильтра
   типов, но диспетчер там — явная `if/elif`-цепочка (`user_message`/`text`/`tool`/`tool_result`/
   `error`/`status`/`subagent_end`) с `else: continue` в конце. Неизвестный тип уже сейчас падает в
   этот catch-all и никуда не уходит — новый тип `done_gate_verdict` не требует правки кода моста,
   он уже безопасен по конструкции (тот же путь, что и для `provider_limit`, у которого тоже нет
   явной ветки). Добавлен тест
   `tests/test_tg_bridge.py::TestTurnEndMention::test_done_gate_verdict_never_reaches_telegram`,
   который прогоняет РЕАЛЬНЫЙ `tb.stream_logs()` со строкой `type='done_gate_verdict'` через
   существующий harness `TestTurnEndMention._run` и проверяет `sent == [] and mirrored == []`.
   Мутационная проверка: временно добавил explicit-ветку `elif t == "done_gate_verdict": text =
   f"gate: {c}"` перед `subagent_end` — тест покраснел (`assert [...] == []` упал, увидел бы
   реальный текст вердикта в TG), убрал ветку — тест снова зелёный.

Тесты: `uv run --frozen python -m pytest tests/test_tg_bridge.py tests/test_done_gate_v614.py -q`
→ 208 passed (в т.ч. 194 уже существовавших в `test_tg_bridge.py` — без регрессии).

## Что сделано

- `app/done_gate.py` — новый модуль. `evaluate(session_id, scope)` реплеит `logs` этой сессии
  (`type IN ('tool','tool_result')`, последние 4000 строк) и находит последнюю правку кодового
  файла и была ли после неё успешная строгая проверка. Логика — то же, что в
  `.orchestra/tasks/V-613/done_gate_probe.py`, но по живым логам одной сессии, а не по снимку БД.
  `record_verdict(...)` вызывает `evaluate` и пишет один JSON в `logs` (`type='done_gate_verdict'`,
  `origin='platform'`), `maybe_record(...)` — точка входа: пропускает не-DONE-сообщения и
  сессии-оркестраторы (`db.get_session(...).is_orchestrator`/`role`). Все три функции ловят любое
  исключение сами и возвращают `None` вместо падения.
- Хук — `app/message_deliveries.py::accept_message_delivery`, сразу после `ensure_target_runner`,
  внутри уже существующего `if wake_runner:` (это ветка «дедупликация не сработала», то есть
  сообщение реально новое или ретраится после `FAILED_BEFORE_SUBMIT» — на чистый повтор с тем же
  `delivery_id` вердикт не пишется второй раз). Вызов обёрнут в свой `try/except`, отдельно от
  `ensure_target_runner`, чтобы ошибка гейта никогда не трогала ни `wake`, ни возврат `202`.
- Настраиваемость (критерий 2): что считается кодом (`code_ext`, `edit_tools`, `ignored_prefixes`)
  и что считается проверкой (`check_pattern`, `non_strict_pattern`) хранится как `DoneGateConfig`
  с разумным умолчанием из probe V-613 и может быть переопределено на уровне `scope` через уже
  существующую таблицу `kv` (`done_gate.set_config_override(scope, {...})`, ключ
  `done_gate_config:<scope>`) — новой таблицы/миграции не потребовалось. По умолчанию правки
  только в `.orchestra/` или `docs/` не считаются кодом (проверяется по вхождению `/.orchestra/`
  или `/docs/` в путь, либо префиксу пути). Строгость проверки — как у Canny:
  `| tail`/`| head`/`| grep`, `|| true`, `; echo` не признаются проверкой, даже при успехе.
- `scripts/done_gate_weekly_report.py` (критерий 3) — read-only скрипт по `sqlite3`, считает
  вердикты `done_gate_verdict` за N дней (по умолчанию 7), группирует флаги по scope/воркеру и
  сверяет сессии с флагом против `merge_operations`, где `result_json` содержит
  `TEST_GATE_FAILED`/`TEST_GATE_INCONCLUSIVE` в том же окне. Запуск:
  `python scripts/done_gate_weekly_report.py --db data/orchestra.db --days 7`
  (безопаснее — на копии через `sqlite3.Connection.backup()`, как делают другие
  `scripts/migrate_*`, но чтение WAL допускает и прямой путь).

## Проверено

- `.orchestra/tasks/V-614/report.md` (этот файл) + `tests/test_done_gate_v614.py` — 14 тестов,
  обе ветки из критерия 4:
  - правка → DONE без проверки ⇒ `flag=True` (`test_edit_then_done_without_check_is_flagged`,
    и через полный путь `accept_message_delivery` —
    `test_accept_message_delivery_records_shadow_verdict`);
  - правка → успешная строгая проверка → DONE ⇒ `flag=False`
    (`test_edit_then_passing_strict_check_clears_flag`);
  - падающая проверка не снимает флаг (`test_failing_check_does_not_clear_flag`);
  - нестрогая проверка (`| tail`) не считается (`test_non_strict_check_does_not_clear_flag`);
  - правки только в `.orchestra/`/`docs/` не считаются кодом (2 теста);
  - оркестраторы не проверяются (`test_maybe_record_skips_orchestrator`);
  - не-DONE сообщение гейт не трогает (`test_maybe_record_skips_non_done_message`);
  - ошибка внутри `evaluate`/`db.add_log` не выходит наружу
    (`test_record_verdict_swallows_db_write_failure`,
    `test_record_verdict_swallows_evaluate_failure`);
  - ошибка внутри `maybe_record` не ломает `accept_message_delivery`, `send_message` всё равно
    получает `202/ACCEPTED` (`test_accept_message_delivery_survives_gate_exception`);
  - per-scope переопределение через `kv` реально меняет решение (`test_config_override_via_kv`).
- Прогон: `uv run --frozen python -m pytest tests/test_done_gate_v614.py -q` — 14 passed.
  Импортированный модуль — `/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-jev/app/done_gate.py`
  (подтверждено `python -c "import app.done_gate as m; print(m.__file__)"`).
- Регрессия на соседях (не полный сьют, целевой набор всех тестов, трогающих
  `message_deliveries`/`done_gate`, 18 файлов):
  `uv run --frozen python -m pytest tests/test_audit0901_delivery.py tests/test_audit0901_mcp.py
  tests/test_codex_writer_conflict_536.py tests/test_compact_pending_ack_467.py
  tests/test_delivery_head_of_line_block.py tests/test_done_gate_v614.py
  tests/test_durable_steering_562.py tests/test_fan_barrier_intercept.py
  tests/test_fan_completion_modes_407.py tests/test_idle_watch.py
  tests/test_lifecycle_quarantine_499.py tests/test_message_delivery_receipts_380.py
  tests/test_message_provenance_migration_433.py tests/test_message_provenance_review_433.py
  tests/test_portfolio_watchdog_418.py tests/test_project_roadmap_backend_425.py
  tests/test_restart_durable_transfer.py tests/test_restart_inbox.py -q` — 129 passed.
- `scripts/done_gate_weekly_report.py` smoke-прогон на синтетической БД (один вердикт,
  `flag=False`) — печатает корректный JSON, ноль исключений.
- Мутационная проверка (обязательна по правилам проекта): выключил хук в
  `accept_message_delivery` (закомментировал вызов `maybe_record`) — тест
  `test_accept_message_delivery_records_shadow_verdict` из моего диффа покраснел
  (`AssertionError: assert 0 == 1` — вердикт не записался), затем вернул код обратно.

## Ограничения и то, что НЕ входит в этот тик

- Живой прод не увидит гейт до рестарта: изменение чисто в Python-коде
  (`app/message_deliveries.py`, `app/done_gate.py`), а Python у сервисов Orchestra не
  подхватывается на лету. Рестарт по правилам инициирует только владелец — этой задачей не
  делался и не запрашивался; строка «нужен рестарт» — здесь, одной строкой, как и просят правила.
- Хранилище вердиктов — существующая таблица `logs`, без новой таблицы и без миграции схемы
  (`SCHEMA_VERSION` не менялся). Плюс: ноль риска для офлайн-миграции живой БД. Минус: агрегация
  идёт через `json_extract`/парсинг JSON, а не отдельные колонки — для еженедельного отчёта это
  уже покрыто скриптом, для более тяжёлой аналитики в будущем может понадобиться настоящая таблица.
- Точность самой эвристики (что считается «кодом» и «проверкой») не размечена вручную на живых
  данных в этой задаче — она унаследована от probe V-613, где ручная проверка 41 случая показала
  невысокую точность до сужения на `.orchestra/`/`docs/`. Это тень: расхождения собираются
  `done_gate_weekly_report.py`, решение о видимости воркеру — отдельный шаг, не в этом тике.
- Хук стоит только в keyed-пути `accept_message_delivery` (delivery_id всегда есть у MCP
  `send_message`, поэтому все DONE от воркеров идут через него); non-keyed/dashboard-ветка
  `routes/sessions.py` не тронута — туда воркер-DONE не приходит.

## Файлы

- `app/done_gate.py` — новый (+247 строк)
- `app/message_deliveries.py` — хук в `accept_message_delivery` (+13 строк)
- `scripts/done_gate_weekly_report.py` — новый (+87 строк)
- `tests/test_done_gate_v614.py` — новый (+280 строк)
- `app/static/js/chat.js` — не рендерить `done_gate_verdict` (+1 строка)
- `tests/test_tg_bridge.py` — тест, что вердикт не доходит до Telegram (+22 строки)
- `CHANGELOG.md` — запись Added
- `.orchestra/tasks/V-614/report.md` — этот файл

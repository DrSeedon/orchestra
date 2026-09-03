## Summary

План в целом попадает в правильные зоны, но P1 и P3 сейчас опасны: `loaded`-hydration меняет response shape для DB-only session и не покрывает один live-only call-site, а callback-инверсия YouGile может незаметно отключить fire-and-forget sync. Для MVP это не требует усложнения архитектуры, но требует более точных guard-ов и тестов на DB-only/live-only поведение.

## Findings

- blocking, `docs/tasks/refactor-ecs/plan.md:63` — P1 "dict never escapes" ломает `GET /api/sessions/{name}` для DB-only сессий: сейчас `app/main.py:509` возвращает raw DB row, а detached `AgentSession.to_dict()` из `app/session.py:1084` обрежет `system_prompt` и потеряет поля вроде `cwd`, `session_id`, `worktree_path`, `context_tokens` → зафиксировать отдельный row-shaped response для `not loaded` или сделать явный `to_db_response()`; добавить тест на DB-only endpoint до/после.
- blocking, `docs/tasks/refactor-ecs/plan.md:77` — список P1 call-sites пропускает live-only `app/manager.py:653`: после hydration `isinstance(session, AgentSession)` станет true и `change_orchestrator_scope()` начнет работать с detached session, хотя сейчас DB-only orchestrator получает "not loaded" → заменить на `if not session or not session.loaded` и покрыть DB-only тестом.
- blocking, `docs/tasks/refactor-ecs/plan.md:85` — миграция `progress_pct/progress_status` в `update_session_fields()` меняет поведение `app/main.py:1008`: сейчас progress update для DB-only сессии возвращает 404, потому что ищется только live session; direct DB update сделает операцию успешной → оставить progress live-only или явно вынести как запрещенное изменение поведения.
- blocking, `docs/tasks/refactor-ecs/plan.md:139` — P3 callback slots для `tm.py` будут работать только если `tm_yougile.py` гарантированно импортирован до `_fire_sync()` из `app/tm.py:782,827,924`; формулировка `routes/tm.py:170 lazy import — stays/lift` неоднозначна, и при буквальном удалении lazy import sync станет no-op → добавить явный startup/top-level import registration и тест, что `api_create_task()` вызывает зарегистрированный callback.
- suggestion, `docs/tasks/refactor-ecs/plan.md:37` — P0 говорит вынести "transaction blocks" в `to_thread`, но в `app/tm_yougile.py:105`, `:156`, `:234` есть DB reads/connection lifetime вне этих блоков и рядом с `await` HTTP → вынести все SQLite access в sync helpers, создавая connection внутри helper; SQLite connection не должен пересекать thread/await границы.
- suggestion, `docs/tasks/refactor-ecs/plan.md:89` — grep gate для P1 не ловит `isinstance(a, dict)` / `isinstance(b, dict)` в `app/main.py:992` и не проверяет все `get_by_name()` call-sites (`app/manager.py:500,653`) → заменить на широкий `rg "get_by_name\\(|isinstance\\([^)]*, dict\\)" app/` с ручной классификацией не-session dict cases.
- suggestion, `docs/tasks/refactor-ecs/plan.md:169` — P4 переносит `_did_report` в `TurnManager`, но `app/session.py:475` оставляет `_handle_event()` в `AgentSession`, где меняются `_turn_logs`, `_did_report` и `total_tool_calls`; без явных shims/properties авто-репорт после `send_message` может снова срабатывать ошибочно → описать ownership `_turn_logs/_did_report` и сохранить тесты `tests/test_session.py:263` и `:685`.
- suggestion, `docs/tasks/refactor-ecs/plan.md:173` — `HibernateManager` владеет `_hibernate_task/_hibernated`, но эти поля используются не только в hibernate methods: `app/session.py:304`, `:988`, `:1013`, `:1099`, а тесты патчат `_heartbeat_loop` (`tests/test_session.py:744`) → оставить facade-shims/properties на `AgentSession` или обновить все внутренние обращения в том же коммите.
- nit, `docs/tasks/refactor-ecs/plan.md:11` — test gate запускает `tests/test_default_equals_upstream.py`, хотя строкой выше план говорит про его известный pre-existing fail; "tests green after each" станет невыполнимым условием → оформить как expected known failure или отдельную диагностическую команду, не gate.

## Verdict

Не готов к исполнению как strict behavior-preserving plan. Исправить blocking пункты по P1 response/live-only semantics и P3 YouGile registration; остальные замечания можно внести как уточнения в план перед стартом рефакторинга.

## Round 2 — 2026-06-11T12:10:49+07:00

### Re-review

- B1 response shape `GET /api/sessions/{name}`: FIXED — detached `AgentSession` хранит `db_row`, handler для `not loaded` возвращает raw row, добавлен тест на DB-only response shape.
- B2 `change_orchestrator_scope` live-only guard: FIXED — план явно заменяет inverted `isinstance` на `not session or not session.loaded` и требует DB-only тест.
- B3 progress DB-only 404: FIXED — `progress` исключён из `update_session_fields`, остаётся live-only и сохраняет 404 для detached session.
- B4 YouGile callback registration: FIXED для исходного замечания — план добавляет гарантированный import `tm_yougile` через startup/top-level route import и тест на регистрацию hook-а.
- S1 SQLite reads in async YouGile paths: FIXED — план требует вынести все SQLite reads/writes в sync helpers с connection внутри helper.
- S2 grep gate coverage: FIXED — grep расширен до `get_by_name\(|isinstance\([^)]*, dict\)` с ручной классификацией.
- S3 `_did_report`/turn state ownership: FIXED — все state fields остаются на `AgentSession`, subsystems только stateless method-holders.
- S4 hibernate state ownership/shims: FIXED — `_hibernate_task`/`_hibernated` остаются на `AgentSession`, plan требует shims или обновление patch targets.
- N1 test gate vs known polluter: FIXED — full-suite green gate отделён от диагностического запуска `test_default_equals_upstream.py`.

### Новые замечания

- blocking, `docs/tasks/refactor-ecs/plan.md:38` / `app/tm.py:687-718` — P0 переводит `_tm.api_*` из `routes/tm.py` в `asyncio.to_thread`, но `_fire_sync()` и `_fire_journal_sync()` планируют YouGile work через `asyncio.get_event_loop().create_task()` в текущем потоке. В worker thread на Python 3.12 это даёт `RuntimeError`, который текущий код ловит как "No event loop for sync, skipping", то есть создание/обновление задач и payment через HTTP начнут молча пропускать YouGile sync уже после P0. P3 callback-версия сохранит тот же класс бага, если `_fire_async()` тоже ищет loop в текущем thread. Нужно явно зафиксировать scheduling contract: либо sync helper возвращает "sync intents", а route создаёт task на running loop после `to_thread`, либо `tm` получает/captures main event loop и использует `run_coroutine_threadsafe`. Добавить тест: `routes/tm.py` create/update/payment после `to_thread` вызывает stubbed hook для `yougile_enabled` project.
- blocking, `docs/tasks/refactor-ecs/plan.md:123-127` — предложенный module-level код `on_scope_idle: Callable[[AgentSession], Awaitable[None]] | None = None` в текущем `app/session.py` будет исполняться до объявления `AgentSession`, а `from __future__ import annotations` там нет. При буквальной реализации импорт `app.session` падает на `NameError`. Нужно либо добавить postponed annotations в начало файла, либо писать `Callable[["AgentSession"], Awaitable[None]]` / `TYPE_CHECKING`-вариант и явно импортировать `Callable`, `Awaitable`.

### Вердикт раунда

Требует ещё фиксов. Все Round 1 замечания закрыты, но новый P0/P3 thread-loop разрыв ломает YouGile sync в обычных TM HTTP flows, а P3 hook type hints могут уронить import при прямой реализации плана.

## Round 3 — 2026-06-11T12:13:27+07:00

### Re-review

- R2-B1 thread→loop scheduling: FIXED — фикс перенесён в P0, `tm._MAIN_LOOP` выставляется из lifespan через `tm.set_main_loop(asyncio.get_running_loop())`, а fire-helpers при отсутствии running loop в worker thread планируют coroutine на captured main loop через `asyncio.run_coroutine_threadsafe`. Тест `api_create_task` из `asyncio.to_thread` с stubbed sync coro покрывает именно прежний silent skip.
- R2-B2 module-level hook annotations: FIXED — hook-слоты объявляются после `class AgentSession`, `AgentSession` внутри аннотаций строковый, `Callable`/`Awaitable` импортируются из `collections.abc`, плюс добавлен import smoke test `python -c "import app.session"`.

### Новые замечания

Нет blocking замечаний по изменённым секциям P0 0.2 и P3 3.1.

### Вердикт раунда

APPROVED

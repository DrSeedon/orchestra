---
slug: plan-review
topic: Plan review for architecture refactoring
created: 2026-06-02
model: gpt-5.5
---

## Round 1

`blocking:` Запрошенный артефакт `docs/tasks/debate-test/plan.md` отсутствует в текущем worktree. В `docs/tasks/debate-test/` есть только `codex_architecture.md`; ниже я сверяю плановый раздел из него с текущими файлами. Перед имплементацией нужно либо добавить настоящий `plan.md`, либо явно зафиксировать, что источником плана является `codex_architecture.md`.

### Step 1: prompting.py — needs fixes

`suggestion:` Направление соответствует консенсусу: допустим маленький `app/prompting.py` для file/template helpers, без разрезания `AgentSession` и без `PromptBuilder`-класса. Это совпадает с финальным ограничением: переносить только prompt helpers и проверять imports.

`blocking:` В плане недостаточно явно описан import-cycle risk. Сейчас `manager.py` импортирует `is_orchestrator_role` из `session.py` на верхнем уровне (`app/manager.py:14`), а `session.py` лениво импортирует `_prompt_template_hash` из `manager.py` (`app/session.py:251`). Если новый `app.prompting` начнет импортировать `is_orchestrator_role` из `app.session`, а `session.py` начнет импортировать `_prompt_template_hash` из `app.prompting`, получится цикл `session -> prompting -> session`. Role predicate/constant нужно вынести в независимый модуль или держать внутри `prompting.py` без импорта `session.py`.

`blocking:` План перечисляет `_parse_role_frontmatter`, `_load_modules`, `_role_prompt_file`, `_skills_catalog`, `_roles_catalog`, `_prompt_template_hash`, но пропускает зависимости, которые останутся в `manager.py`: `_read_prompt` (`app/manager.py:49`), `_PROMPTS_DIR` (`app/manager.py:39`), `_SKILLS_DIR` (`app/manager.py:149`), `get_role_icons()` (`app/manager.py:187`) и `_inject_skills_to_worktree()` (`app/manager.py:270`). Если `_parse_role_frontmatter` и prompt dirs переедут, эти функции должны либо импортировать их из `app.prompting`, либо получить отдельные helper API. Иначе перенос будет неполным или создаст дублирование констант путей.

`blocking:` Нельзя переносить dynamic blocks в `app.prompting` без dependency injection. `ROLE_SYSTEM_PROMPT()` сейчас добавляет `_other_orchestrators_block()` и `_workers_block()`, которые читают DB через `get_all_sessions()` (`app/manager.py:54`, `app/manager.py:75`, `app/manager.py:232`). Консенсус был оставить dynamic DB-зависимые части в `manager.py` или передавать их явно, а не превращать `prompting.py` во второй manager.

`nit:` Номера строк из дебата уже сдвинулись. Актуальные ориентиры: lazy import `_prompt_template_hash` — `app/session.py:251`, `_prompt_template_hash` — `app/manager.py:258`, prompt endpoint — `app/main.py:435`.

### Step 2: backend_protocol.py — approved with fixes

`suggestion:` Шаг соответствует консенсусу, если это именно `typing.Protocol`, а не ABC, не factory hierarchy и не runtime enforcement. Общий контракт реально есть: `session_id`, `connect`, `send`, `events`, `interrupt`, `disconnect` у `ClaudeBackend` (`app/backend_claude.py:99`, `app/backend_claude.py:137`) и `CodexBackend` (`app/backend_codex.py:48`, `app/backend_codex.py:52`).

`blocking:` `app/backend_protocol.py` должен импортировать только `Protocol`, `AsyncIterator` и `AgentEvent`. Он не должен импортировать `ClaudeBackend`, `CodexBackend`, `AgentSession` или `SessionManager`; иначе появится новый backend/session import coupling.

`blocking:` Не включать `reconnect()` и `context_usage()` в базовый `BackendLike`. Они есть у `ClaudeBackend` (`app/backend_claude.py:173`, `app/backend_claude.py:192`), но отсутствуют у `CodexBackend` (`app/backend_codex.py:32-238`). Текущий код вызывает `context_usage` через `hasattr` (`app/session.py:812`) и вызывает `reconnect` только в Claude ветках (`app/session.py:350`, `app/session.py:646`). Для type checking лучше добавить отдельные optional protocols вроде `SupportsReconnect`/`SupportsContextUsage`, либо оставить локальные `hasattr`.

`suggestion:` `_backend: Optional[object]` на `app/session.py:109` можно заменить на `BackendLike | None`, а `_make_backend()` (`app/session.py:145`) аннотировать как возвращающий `BackendLike`. Runtime-поведение при этом не должно измениться.

### Step 3: _handle_turn_end — needs fixes

`suggestion:` Шаг соответствует консенсусу только в форме private helper methods внутри `AgentSession`. Новых сервисов/объектов для event processing быть не должно.

`blocking:` Сохранить early return для `max_turns` до обычного завершения. Сейчас при `sr in ("error_max_turns", "max_turns") and ok` код логирует auto-continue, запускает `_auto_continue()` и возвращается (`app/session.py:509-512`). Он намеренно не ставит `IDLE/WAITING`, не делает auto-report, не flush'ит pending messages и не hibernate'ит.

`blocking:` Сохранить ordering invariant: статус `WAITING/IDLE` выставляется, затем сразу вызывается `_persist()` (`app/session.py:519-525`), и только после этого идут compact ack, scope idle notification, auto-compact, auto-report, pending flush и hibernate (`app/session.py:527-542`). Helper `_finish_turn_status()` должен содержать status update + `_persist()`, а `_after_turn_idle_actions()` должен вызываться строго после него.

`blocking:` `_after_turn_idle_actions(live_pct)` должен сохранить текущую развилку pending messages: если `self._pending_messages`, запустить `_flush_pending()` и вернуть, не вызывая `_schedule_hibernate()` (`app/session.py:538-542`). Иначе queued message может получить лишнюю hibernate/disconnect гонку.

`suggestion:` `_apply_turn_result(meta)` должен сохранить порядок session id и cost deltas: сначала сбросить `_last_cost/_last_cost_cached`, если пришел новый `session_id`, потом назначить `self.session_id`, потом считать delta cost (`app/session.py:476-487`). Это легко сломать при "чистом" extract-method.

`thought:` `_spawn_bg(self._refresh_context_from_api())` сейчас происходит до обработки ошибок и до `max_turns` early return (`app/session.py:502`). Если план переносит context refresh в after-turn actions, поведение для `max_turns` изменится.

### Step 4: main.py split — needs fixes

`suggestion:` Шаг соответствует консенсусу, если первый split ограничен `deps.py`, `tm_routes.py` и `bg_routes.py`. Session/SSE/workspace routes пока лучше оставить в `main.py`.

`blocking:` Routers не должны импортировать `manager` из `app.main`. Нужен общий singleton в `app/deps.py`; иначе получится зависимость `router -> main`, а при `include_router` легко получить import-time side effects. Текущий singleton находится в `app/main.py:29`, lifespan использует его в `app/main.py:38-53`.

`blocking:` При переносе `_tm` из `main.py` нельзя сломать session merge/switch endpoints. Они пока остаются в `main.py`, но используют `_tm.link_commits_to_task()` и `_tm.api_update_task()` (`app/main.py:759`, `app/main.py:803`). Если `_tm` полностью уедет в `tm_routes.py`, эти endpoints получат `NameError`. Нужно брать тот же модуль из `app.deps`.

`blocking:` `bg_routes.py` для `POST /api/bg/jobs` нуждается и в `bg_manager`, и в том же `manager` singleton для lookup session (`app/main.py:1463-1481`). Импорт `bg_manager` лучше оставить lazy через `get_bg_manager()`, как в консенсусе, потому что lifespan тоже связывает `bg_manager` с `manager` (`app/main.py:40-42`).

`suggestion:` Актуальные line ranges в текущем файле корректны для этого шага: `/api/tm/*` — `app/main.py:1316-1449`, `/api/bg/jobs` — `app/main.py:1463-1496`. Но smoke checks должны включать не только `py_compile`, а минимум `python -c "import app.main"` после `include_router`, чтобы поймать циклы и missing imports.

### Overall Verdict

needs fixes

План в целом совпадает с финальным консенсусом: не резать core lifecycle на сервисы, добавить небольшой prompt module, Protocol для backend'ов, private helper extraction в `_handle_turn_end`, и осторожный первый split `main.py`. Блокеры не в направлении, а в деталях исполнения: отсутствующий `plan.md`, риск import cycle вокруг `prompting.py`, пропущенные prompt dependencies, optional backend methods и критичный ordering в `_handle_turn_end`.

## Round 2 — 2026-06-02

### Re-review

`blocking:` `docs/tasks/debate-test/plan.md` всё ещё отсутствует в моём текущем checkout, поэтому я не могу локально сверить таблицу плана. Ниже оцениваю уточнения из ответа Claude/Opus как содержание плана.

`FIXED:` Step 1 import cycle. Перенос `_ORCHESTRATOR_ROLES` и `is_orchestrator_role()` в `app.prompting` закрывает риск `session -> prompting -> session`, если `prompting.py` не импортирует `session.py`/`manager.py`. После такого разреза зависимости становятся корректными: `session.py -> prompting.py`, `manager.py -> prompting.py`.

`FIXED:` Step 1 пропущенные prompt dependencies. Если таблица плана действительно переносит `_read_prompt`, `_PROMPTS_DIR`, `_MODULES_DIR`, `_SKILLS_DIR`, `_IDENTITY_PLACEHOLDERS`, `_safe_format_prompt`, `_inject_skills_to_worktree` и `get_role_icons`, мой Round 1 blocking по неполному переносу закрыт. Важно сохранить один источник путей/констант, без дублирования в `manager.py`.

`FIXED:` Step 1 dynamic blocks. Если `_other_orchestrators_block()`, `_workers_block()`, `ROLE_SYSTEM_PROMPT()`, `ORCHESTRATOR_SYSTEM_PROMPT()` и `WORKER_SYSTEM_PROMPT()` остаются в `manager.py`, это соответствует консенсусу: DB/runtime-зависимый prompt assembly не переезжает в `prompting.py`.

`FIXED:` Step 2 backend protocol. Принятые ограничения закрывают блокеры: `BackendLike` остается typing-only Protocol, `backend_protocol.py` не импортирует backend/session/manager, а `reconnect()` и `context_usage()` не попадают в базовый контракт.

`FIXED:` Step 3 max_turns early return. Псевдокод сохраняет early return до `_finish_turn_status()`, значит обычные `IDLE/WAITING`, auto-report, pending flush и hibernate не запускаются при `max_turns`.

`FIXED:` Step 3 `_persist()` before after-turn actions. Псевдокод сохраняет `status + _persist()` внутри `_finish_turn_status()` до `_after_turn_idle_actions()`. Это закрывает главный ordering invariant.

`FIXED:` Step 3 pending before hibernate. Если `_after_turn_idle_actions()` делает pending check с `return` перед `_schedule_hibernate()`, текущая развилка сохранена.

`FIXED:` Step 3 context refresh placement. Оставить `_spawn_bg(self._refresh_context_from_api())` в `_handle_turn_end()` между `_update_context_from_turn(meta)` и error/max_turns checks правильно. Это сохраняет поведение текущего кода.

`FIXED:` Step 3 session id/cost order. Порядок `session_id reset -> cost delta -> totals` в `_apply_turn_result(meta)` соответствует текущему инварианту.

`FIXED:` Step 4 `_tm` dependency. Общий `_tm`/`tm` через `deps.py` для `tm_routes.py` и оставшихся session merge/switch endpoints закрывает риск `NameError` и дублирующих imports.

`thought:` Остается обычный implementation risk: после переноса нужны smoke checks `python -m py_compile app/*.py app/routes/*.py` и `python -c "import app.main"`, потому что основные риски теперь import-level.

### Verdict

APPROVED

С учетом уточнений все технические blocking'и Round 1 закрыты. Единственная оговорка: я всё еще не вижу сам `plan.md` в текущем checkout, поэтому approval относится к описанному плану/уточнениям, а не к локально прочитанному `docs/tasks/debate-test/plan.md`.

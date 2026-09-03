## Tests
Не применимо: это ревью спеки. Тесты не запускались; единственный `test_agent_notify.py` является live SDK smoke-test с внешним Claude SDK и hardcoded cwd.

## Summary
Спека правильно убивает дублирование `Worker`/`Orchestrator`, но пока заменяет две кривые системы одной глобально кривой: `name` остается главным идентификатором в памяти, filesystem и API. Самая опасная дыра — lifecycle `ClaudeSDKClient`: `query()`, `receive_messages()` и повторный `send()` описаны так, что легко получить два concurrent consumer'а или потерянный ResultMessage. SQLite-схема лучше текущей, но не готова к async нагрузке, auto-resume и нескольким scope без нормальных индексов, lock policy и UUID. Dashboard-часть избавляется от callbacks, но не фиксирует polling races, XSS-контракт и cursor-based догрузку логов.

## Замечания
blocking: docs/SPEC_v1.md:183 + docs/SPEC_v1.md:204 + docs/SPEC_v1.md:216 — `sessions: dict[str, AgentSession]` и `get(name)` ломают заявленные multiple orchestrators: один `worker-1` в двух `scope` перетрёт другой, а orchestrator и worker с одинаковым `name` станут одной сущностью. Фикс: ключ в памяти и API должен быть `(scope, name)` или `session_uuid`; все `send/interrupt/stop/remove/get` принимают scope явно.

blocking: docs/SPEC_v1.md:78 + docs/SPEC_v1.md:89 + docs/SPEC_v1.md:94 — lifecycle SDK не определяет единственного владельца `receive_messages()`. В текущем коде уже есть этот класс бага: `app/orchestrator.py:140` и `app/orchestrator.py:193` создают новые listeners поверх того же клиента. Фикс: на сессию ровно один receive-consumer, `query()` идет через per-session `asyncio.Lock`/очередь, listener стартует до первого query или query/listen порядок документируется по SDK.

blocking: docs/SPEC_v1.md:85 + docs/SPEC_v1.md:87 + docs/SPEC_v1.md:96 — `send()` разрешен в `RUNNING`, значит второй запрос может уйти пока первый turn еще стримится. Это не "реюз worker", это гонка protocol state. Фикс: либо `RUNNING` rejects/queues messages, либо вводится mailbox и один background loop последовательно делает `query -> drain ResultMessage`.

blocking: docs/SPEC_v1.md:96 + docs/SPEC_v1.md:89 — после `ResultMessage` loop делает `break`, а потом idle-session "re-starts `_listen_loop()`". Спека не доказывает, что SDK разрешает повторно итерировать `receive_messages()` на том же клиенте после завершенного turn. Фикс: выбрать один контракт: persistent receiver без break или `disconnect()` на idle и новый `ClaudeSDKClient(options.resume=session_id)` на следующий send.

blocking: docs/SPEC_v1.md:17 + docs/SPEC_v1.md:115 — `permission_mode="default"` плюс unconditional `PermissionResultAllow` фактически является bypass с другим названием. Любой prompt-injected агент получает auto-approved Bash/Edit/Write. Фикс: deny/allow policy по tool_name, cwd, path traversal, protected files, destructive git commands; каждый auto-approve логировать как audit entry.

blocking: docs/SPEC_v1.md:138 + docs/SPEC_v1.md:139 — worktree path и branch строятся только из `name`; одинаковое имя в разных `scope` конфликтует в `/worktrees/{name}`, а `feat/{name}` может уже существовать от старой сессии. Фикс: использовать `session_uuid` или slug от `(scope, name, created_at)`, хранить owner в DB, не полагаться на display name.

blocking: docs/SPEC_v1.md:141 + docs/SPEC_v1.md:158 — `create_worktree()` сначала force-remove существующий path, потом пробует создать новый. Если `git worktree add` ломается, старый worktree уже уничтожен, а remove errors проглочены. Фикс: не удалять чужой/старый worktree без owner-check; создавать в новом уникальном path; все `subprocess.run` с `check`/stderr; cleanup только созданных ресурсов.

blocking: docs/SPEC_v1.md:75 + docs/SPEC_v1.md:292 — нет валидации `cwd`/`repo_path`. Несуществующий cwd даст SDK error после записи `starting`, а несуществующий repo_path в worktree даст `FileNotFoundError` вне нормального session log. Фикс: Pydantic request models, `Path.resolve()`, `exists/is_dir`, `git rev-parse --show-toplevel`, нормальный 4xx до создания сессии.

suggestion: docs/SPEC_v1.md:234 + docs/SPEC_v1.md:260 + docs/SPEC_v1.md:270 — SQLite описан как sync helper под async FastAPI: много коротких connections, нет `busy_timeout`, нет транзакционной политики, `INSERT OR REPLACE` делает delete+insert semantics. Фикс: `PRAGMA busy_timeout`, WAL один раз при init, `ON CONFLICT(name, scope) DO UPDATE`, DB calls через `asyncio.to_thread`/`aiosqlite`, индексы `logs(session_scope, session_name, id DESC)` и `sessions(scope, is_orchestrator, status)`.

blocking: docs/SPEC_v1.md:252 + docs/SPEC_v1.md:265 — schema-комментарий разрешает только `text|tool|error|status|user_message`, но архитектура говорит, что notifications тоже log entry. Фикс: явно добавить `notification` в enum/type contract и описать, как dashboard отличает orchestrator chat, worker logs и task notifications.

blocking: docs/SPEC_v1.md:219 + docs/SPEC_v1.md:221 — `auto_resume_orchestrators()` берет `status != "stopped"`, значит будет оживлять `error`, stale `running` после crash и potentially orphaned cwd. Фикс: resume only `is_orchestrator=1 AND session_id IS NOT NULL AND status IN ('running','idle')`, валидировать cwd, на startup переводить stale non-orchestrator `running` в `error/stopped`.

question: docs/SPEC_v1.md:13 + docs/SPEC_v1.md:16 + docs/SPEC_v1.md:121 — спека одновременно говорит "SDK handles discovery natively", "worktree driven by `.md` frontmatter" и "AgentSession does NOT parse `.md`; manager parses". Это три источника правды. Фикс: либо manager официально парсит frontmatter (`isolation`, `model`, `max_turns`) и передает config, либо worktree выбирается только API-параметром; без гибрида.

suggestion: docs/SPEC_v1.md:337 + docs/SPEC_v1.md:345 — "one polling loop" недостаточно. Без cursor `last_log_id` UI будет перерисовывать историю, терять scroll state, дублировать сообщения при overlapping refresh и съедать память на длинных логах. Фикс: `/api/sessions/{id}/logs?after_id=...`, AbortController/sequence id для refresh, no overlapping interval, bounded DOM nodes.

blocking: docs/SPEC_v1.md:337 + app/templates/dashboard.html:330 — dashboard должен иметь явный XSS-контракт. Текущий код местами строит `innerHTML` из данных и даже вставляет escaped name в JS string внутри `onclick`, что ломается на кавычках и не является безопасным JS escaping. Фикс: render через DOM APIs/textContent или `<template>` + dataset, никакого inline JS с server/model-controlled strings.

suggestion: docs/SPEC_v1.md:358 — "rename DB, history is in git" неверно: runtime logs, cost, session_id и worktree metadata не в git. Фикс: либо честно назвать это destructive migration с backup path и UI/CLI подтверждением, либо написать минимальную migration из `workers/logs` в `sessions/logs`.

## Open Questions (ответы на 4 вопроса из спеки)
1. `(name, scope)` не должен быть primary key. Нужен `session_uuid` как PK, плюс `UNIQUE(scope, name)` для активных/display sessions, если имя должно быть человекочитаемым.

2. `_listen_loop` должен делать bounded reconnect только для явно transient transport errors. Protocol errors, permission denials и invalid cwd должны ставить `ERROR`; во время retry нужен отдельный статус вроде `reconnecting` или `running` с log entry.

3. На `IDLE` безопаснее пересоздавать SDK client с `options.resume=session_id`, пока не доказано официальным SDK-контрактом, что reuse после `ResultMessage` поддержан. Держать "почти живой" client без активного receive loop — рецепт для висящих сессий.

4. Да, race есть. `send()` во время `_listen_loop` может пересечься с текущим turn, создать второй query до `ResultMessage` и сломать ordering логов/status; нужен per-session lock/queue и ровно один receive consumer.

## Вердикт
Идея refactor правильная, но эту спеку нельзя имплементить как есть: сначала зафиксировать идентичность сессии, SDK concurrency contract, worktree ownership и DB/polling contracts.

## Round 2

### Tests
Не запускались: задача снова review-only по `docs/SPEC_v1.md`.

### Original Blocking Findings
Note: в Round 1 было 11 строк `blocking:`, не 9. Проверяю все 11, чтобы не пропустить старые риски.

1. **Session identity / collisions** — **FIXED**. `sessions.id` как UUID PK, in-memory dict by UUID и `UNIQUE(name, scope)` закрывают конфликт одинаковых names между scope. `get_by_name(name, scope)` для display/API lookup нормален.

2. **Single receive consumer / SDK lifecycle** — **STILL BROKEN**. `send()` path стал лучше, но `start(initial_message)` все еще делает `client.query(initial_message)` до `_listen_loop()` (`docs/SPEC_v1.md:111-112`), хотя concurrency sequence требует listener ownership around query. Плюс `_listen_loop()` "releases `_lock`" (`docs/SPEC_v1.md:131`) после того, как lock acquired in `send()`; это допустимо технически для `asyncio.Lock`, но brittle: если `client.query()` падает до старта listener, release path не описан. Фикс: один helper `_run_turn(message)` с `try/finally`, который owns lock, starts listener deterministically, and releases on every pre-listener failure.

3. **`send()` while RUNNING / concurrent query race** — **FIXED** for explicit `send()`. `RUNNING` теперь возвращает 409/`RuntimeError("session busy")` (`docs/SPEC_v1.md:118`, `docs/SPEC_v1.md:413-416`), и это закрывает two in-flight queries через API.

4. **IDLE client reuse after `ResultMessage`** — **FIXED**. IDLE path explicitly disconnects and creates a new `ClaudeSDKClient(options.resume=self.session_id)` (`docs/SPEC_v1.md:95-100`). Это убирает недоказанное re-iteration of `receive_messages()`.

5. **Unconditional auto-approve** — **STILL BROKEN**. Audit log (`docs/SPEC_v1.md:151-157`) не является control. Если threat model действительно "local dev, full autonomy, prompt injection accepted", это сознательно принятый риск, но исходная проблема не исправлена: malicious prompt все еще получает approved tools. Фикс только один: deny/allow policy или честно убрать это из списка исправленных security findings.

6. **Worktree name/path collision** — **STILL BROKEN**. Scope directory fixed (`worktrees/{scope_slug}/{name}`), но branch still `feat/{name}` (`docs/SPEC_v1.md:187-188`), so same worker name in the same repo across old/deleted sessions can attach to an old branch via fallback (`docs/SPEC_v1.md:200-205`). `_slugify(scope)` also has unspecified collision behavior. Фикс: include UUID in path and branch, e.g. `worktrees/{scope_slug}/{name}-{id[:8]}` and `feat/{name}-{id[:8]}`.

7. **Destructive worktree create / silent remove errors** — **FIXED** for create. Existing worktree now raises instead of force-removing (`docs/SPEC_v1.md:190-194`), and create failure raises with stderr (`docs/SPEC_v1.md:206-207`). `remove_worktree()` still uses `--force`, but that is explicit remove path, not pre-create destruction.

8. **`cwd` / `repo_path` validation** — **FIXED**. Pydantic request validation, `cwd` existence, `repo_path` git repo validation and 422 are now specified (`docs/SPEC_v1.md:406-411`).

9. **Missing `notification` log type** — **FIXED**. Schema comment includes `notification` (`docs/SPEC_v1.md:339`), and dashboard treats notifications as logs (`docs/SPEC_v1.md:459`).

10. **Auto-resume filter revives bad sessions** — **FIXED**. Filter is now `is_orchestrator=1 AND session_id IS NOT NULL AND status IN ('running', 'idle')`, validates cwd, and marks stale non-orchestrator running sessions as error (`docs/SPEC_v1.md:289-294`).

11. **Dashboard XSS / polling race** — **FIXED** at spec level. DOM API/no inline handlers (`docs/SPEC_v1.md:446-450`), cursor loading, AbortController, bounded DOM and single notification channel (`docs/SPEC_v1.md:452-459`) address the original class of bugs.

### New Issues
blocking: docs/SPEC_v1.md:110-112 — `start()` sets status `RUNNING` even when `initial_message` is absent. Auto-started orchestrator can become permanently busy with no query in flight, and `send()` will 409 forever. Фикс: `start(None)` should connect and set `IDLE` or a separate `CONNECTED` status; only `start(initial_message)` enters `RUNNING`.

blocking: docs/SPEC_v1.md:281-287 — `create_session()` creates worktree and starts SDK before storing/persisting the session. If `session.start()` fails after worktree creation, DB has no owner record and remove cannot clean it. Фикс: persist `STARTING` with UUID and worktree_path before SDK connect, then cleanup on failure in `except`.

blocking: docs/SPEC_v1.md:313-314 + docs/SPEC_v1.md:354 — `busy_timeout` is per SQLite connection, not a one-time database setting. If helper functions open new connections, setting it only in `init_db()` does nothing for later writes. Фикс: configure `PRAGMA busy_timeout=5000` in every `_conn()` or use a managed connection pool.

blocking: docs/SPEC_v1.md:341 — SQLite foreign keys are off unless `PRAGMA foreign_keys=ON` is set per connection. The FK is decorative as written, and if enabled later, `delete_session()` will fail unless logs are deleted first or `ON DELETE CASCADE` is added. Фикс: set `foreign_keys=ON` per connection and add `ON DELETE CASCADE`, or explicitly document manual delete order.

blocking: docs/SPEC_v1.md:396 + docs/SPEC_v1.md:454 — API contract is inconsistent: endpoint list has `GET /api/sessions/{name}?scope=...` with logs, but dashboard calls `GET /api/sessions/{orchestrator}/logs?after_id=...`. Фикс: add explicit `GET /api/sessions/{name}/logs?scope=...&after_id=...` or change dashboard polling to the declared detail endpoint.

suggestion: docs/SPEC_v1.md:373-379 — UPSERT only updates `status`, `session_id`, `cost_usd`, `finished_at`. If `worktree_path`, `branch`, `cwd`, `model` or `system_prompt` are populated/changed after initial insert, DB can go stale. Фикс: either make sessions immutable after create and persist all fields before start, or update every mutable field explicitly.

suggestion: docs/SPEC_v1.md:176-188 — `name` validation allows hyphens but not enough for safe branch/path semantics over time. Even with max 50, reserved names and case-insensitive filesystem collisions are not covered. UUID suffix solves this with less policy.

## Round 3

### Tests
Не запускались: review-only по `docs/SPEC_v1.md` v3.

### Round 2 Findings

1. **Session identity / collisions** — **FIXED**. UUID remains internal PK and dict key; name+scope is only display/API lookup.

2. **Single receive consumer / SDK lifecycle** — **FIXED** for query/listen ownership. `_run_turn()` is now the single path for `query()` + `_listen_loop()` and owns `_lock` via `async with` (`docs/SPEC_v1.md:76-99`).

3. **`send()` while RUNNING / concurrent query race** — **FIXED** for already-running sessions. `_lock.locked()` maps busy turns to 409 (`docs/SPEC_v1.md:124-128`). See new issue below for simultaneous sends when idle.

4. **IDLE client reuse after `ResultMessage`** — **FIXED** in intent. IDLE creates a fresh resumed client (`docs/SPEC_v1.md:101-108`). See new issue below: connect step is inconsistent.

5. **Unconditional auto-approve** — **STILL BROKEN**, but accepted by product scope. The spec now states this as explicit accepted risk (`docs/SPEC_v1.md:17`, `docs/SPEC_v1.md:502-508`). That is a valid product decision for a local dev tool, but it is not a technical fix.

6. **Worktree name/path/branch collision** — **STILL BROKEN**. Branch is now scoped (`feat/{scope_slug}/{name}`), which fixes cross-scope collision, but reuse after delete still attaches to an existing old branch through the fallback path (`docs/SPEC_v1.md:198-205`), and `_slugify(scope)` collision behavior is unspecified. UUID suffix is still the clean fix if every session must be isolated.

7. **Destructive worktree create / silent remove errors** — **FIXED**. Existing path raises; create failure raises; no pre-create force removal (`docs/SPEC_v1.md:190-205`).

8. **`cwd` / `repo_path` validation** — **FIXED**. Validation contract remains explicit (`docs/SPEC_v1.md:424-429`).

9. **Missing `notification` log type** — **FIXED**. Schema includes `notification` (`docs/SPEC_v1.md:351`).

10. **Auto-resume filter revives bad sessions** — **FIXED**. Resume filter and stale marking remain correct (`docs/SPEC_v1.md:287-292`).

11. **Dashboard XSS / polling race** — **FIXED** at spec level. DOM-only rendering and cursor/AbortController polling are specified (`docs/SPEC_v1.md:464-477`).

12. **`start(None)` goes RUNNING forever** — **FIXED**. `start(None)` now connects and persists `IDLE`; only `start(message)` enters `_run_turn()` (`docs/SPEC_v1.md:113-121`).

13. **Orphan worktree on failed start** — **FIXED**. `create_session()` persists `STARTING` before worktree/SDK and cleans up on failure (`docs/SPEC_v1.md:278-285`).

14. **SQLite PRAGMAs per connection** — **FIXED**. `_conn()` sets WAL, busy timeout and foreign keys on every connection (`docs/SPEC_v1.md:312-323`).

15. **FK cascade / delete semantics** — **FIXED**. Logs FK is `ON DELETE CASCADE`, with foreign keys enabled per connection (`docs/SPEC_v1.md:347-361`).

16. **Missing `/logs` endpoint** — **FIXED**. API now declares `GET /api/sessions/{name}/logs?scope=...&after_id=0`, and dashboard polls the same shape (`docs/SPEC_v1.md:407-422`, `docs/SPEC_v1.md:470-477`).

17. **UPSERT mutable fields stale** — **FIXED**. `save_session` updates status, SDK session_id, cost, worktree_path, branch, cwd and finished_at (`docs/SPEC_v1.md:380-395`).

18. **Name validation / path semantics** — **STILL BROKEN** as a low-severity design issue. Regex validation is better (`docs/SPEC_v1.md:428`), but branch/path uniqueness is still display-name based rather than session-id based.

### New Issues

blocking: docs/SPEC_v1.md:124-128 — `send()` checks `_lock.locked()` and then spawns `_run_turn()` later; that check is not atomic. Two simultaneous sends on an IDLE session can both see unlocked, both return success, and then the second `_run_turn()` silently waits on the lock, violating "No queuing" and the promised 409. Фикс: guard turn creation with a separate state mutex or `_turn_task` compare/set before returning; set busy synchronously in `send()` before scheduling the background task.

blocking: docs/SPEC_v1.md:68 + docs/SPEC_v1.md:119 + docs/SPEC_v1.md:128 + docs/SPEC_v1.md:148 — `_listen_task` still exists and `stop()` cancels it, but `start()`/`send()` only say "spawn `_run_turn()` as background task"; they do not assign that task to `_listen_task`. Active turns can survive `stop()`/shutdown. Фикс: rename to `_turn_task` and always store the created task; `stop()` cancels/awaits that task before disconnect.

blocking: docs/SPEC_v1.md:103-107 + docs/SPEC_v1.md:79-87 — IDLE resume says "Call `_run_turn(message)` — which connects", but `_run_turn()` pseudocode does not connect. If reconnect is not done before `_run_turn`, `client.query()` runs on a disconnected fresh client. Фикс: either explicitly `await self._client.connect()` in the IDLE resume path before `_run_turn()`, or put `_ensure_connected()` at the top of `_run_turn()`.

### Verdict
No-go for implementation until the three new concurrency/lifecycle blockers are fixed. After that, remaining risk is mostly intentional auto-approve plus non-UUID branch reuse.

## Round 4

### Tests
Не запускались: final review-only по `docs/SPEC_v1.md` v4.

### Round 3 Findings

1. **TOCTOU in `send()`** — **FIXED**. `send()` now transitions to `RUNNING` synchronously before scheduling `_run_turn`, so the second concurrent send sees busy state and returns 409 (`docs/SPEC_v1.md:128-133`).

2. **Orphaned turn task / `_listen_task` mismatch** — **FIXED**. `_listen_task` is gone, `_turn_task` is the tracked background task, and `stop()` cancels + awaits it before disconnect (`docs/SPEC_v1.md:67-69`, `docs/SPEC_v1.md:151-156`).

3. **IDLE resume queries disconnected client** — **FIXED**. `_run_turn()` checks `_client_connected()` and calls `connect()` inside the lock before `query()` (`docs/SPEC_v1.md:79-88`, `docs/SPEC_v1.md:104-110`).

### New Issues
No new blockers.

nit: docs/SPEC_v1.md:97 + docs/SPEC_v1.md:124 — text says `_run_turn()` is the only path that calls `client.connect()`, but `start(None)` explicitly connects outside `_run_turn`. This is harmless for the current startup flow, but the wording should say "only turn path" or note the idle-start exception.

### Verdict
merge-ready. Remaining risks are accepted product choices: unconditional auto-approve for local autonomy and display-name-based branch reuse after deleted sessions.

## Round 5 — Code Review

### Tests
`UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/ -v` не завершился: завис на первом `tests/test_api.py::TestDashboard::test_root_returns_html`. Повтор `tests/test_db.py tests/test_workspace.py tests/test_session.py tests/test_manager.py -v` дошел до `tests/test_manager.py::TestCreateSession::test_returns_session` и был убит по `timeout 60s`; до этого `test_db.py`, `test_workspace.py`, `test_session.py` прошли.

### Findings

blocking: tests/test_api.py:21 + tests/test_api.py:27 — API tests hang in `TestClient(app).__enter__`, before the first request assertion. This means the advertised 97-test suite is not runnable. Fix the lifespan/TestClient fixture first; add a short timeout or isolate startup so a broken lifespan cannot freeze the whole run.

blocking: tests/test_manager.py:31 + app/manager.py:9 — manager tests patch `app.manager._create_client`, but `SessionManager` never uses that imported symbol; `AgentSession.start()` calls `app.session._create_client`. The first manager test therefore can hit the real SDK and hangs. Patch `app.session._create_client` or inject a client factory into `AgentSession`/manager.

blocking: app/session.py:150 + app/manager.py:93 — removing/stopping a worktree session never removes the worktree. `AgentSession.stop()` only disconnects and persists `STOPPED`; `manager.remove()` only calls `stop()` for `RUNNING/STARTING`, then deletes the DB row. An idle worker with `worktree_path` leaves a registered git worktree and directory behind forever. Fix: call `remove_worktree(repo_path, worktree_path)` on every remove/stop path that owns a worktree, before deleting the DB owner record.

blocking: app/db.py:23 + app/session.py:46 + app/main.py:33 — `max_turns` from the spec is missing end-to-end: no DB column, no `AgentSession` field, no request model field, and `_create_client()` never passes `max_turns` into `ClaudeAgentOptions`. This silently changes runtime behavior from the spec. Add `max_turns` everywhere or delete it from the spec.

blocking: app/main.py:33 + app/main.py:77 + app/manager.py:56 + app/workspace.py:28 — `use_worktree=True` does not require or validate `repo_path`; if it is omitted, manager silently creates a non-worktree session. If `repo_path` exists but is not a git repo, the error becomes a late `RuntimeError`/500 or a `ValueError` mapped to 409. Spec says repo_path must be a git repo and invalid input is 422. Add Pydantic validation for required `repo_path` and `git rev-parse --show-toplevel`; reserve 409 for duplicate/busy.

blocking: app/manager.py:37 + app/manager.py:53 + app/main.py:92 — duplicate name handling is race-prone and leaks DB exceptions. Two concurrent creates can both pass `get_session_by_name`; one `save_session()` then raises `sqlite3.IntegrityError`, which API does not catch because it only catches `ValueError`. Fix by treating the DB unique constraint as source of truth and mapping `IntegrityError` to 409.

blocking: app/session.py:168 + app/session.py:171 + app/manager.py:37 + app/main.py:72 — DB calls are synchronous in async request/session paths, despite the spec saying manager wraps DB functions in `asyncio.to_thread()`. A locked SQLite write can block the event loop for up to `busy_timeout=5000`. Wrap DB access in thread offload or move DB operations out of the event loop.

blocking: app/session.py:89 + app/session.py:112 + app/session.py:123 — `_run_turn()` exceptions are raised inside background tasks that production code never awaits. Tests manually await `_turn_task`, but API calls return immediately, so query/listen failures become unobserved task exceptions after the client already got `{"ok": true}`. Add a done callback that consumes/logs exceptions and persists final state, or make send/start await enough of the turn to report immediate SDK failures.

suggestion: app/session.py:165 — `_client_connected()` depends on private SDK state `_connected`. If the SDK changes that private attribute, the wrapper will double-connect or mis-detect connection state. Track connection state in `AgentSession` around successful `connect()/disconnect()` instead of introspecting the SDK object.

suggestion: app/manager.py:127 — auto-resume reconstructs orchestrators without `worktree_path`, `branch`, or `created_at`. Today orchestrators probably do not use worktrees, but the DB row is richer than the restored object. Rehydrate all persisted fields consistently or explicitly assert orchestrators cannot have worktrees.

suggestion: app/static/js/app.js:136 + app/session.py:118 — chat user messages are rendered optimistically in the browser and also logged server-side as `user_message`, so polling will render the same user message again. Either do not optimistically append, or tag local optimistic messages and reconcile when the log arrives.

suggestion: app/static/js/app.js:263 — expanded worker logs append forever and are not bounded like chat logs. A long-running worker can leak DOM nodes and degrade the dashboard. Apply the same max-node pruning used for chat.

suggestion: app/manager.py:23 — the implemented manager only accepts flat API params; there is no `.md` agent definition/frontmatter resolution from the spec. If `.claude/agents/*.md` remains a core decision, add parser tests for `model` and `isolation: worktree`; otherwise remove that promise from `docs/SPEC_v1.md`.

nit: tests/test_api.py:113 — `assert r.status_code in (200, 409)` makes the send endpoint test almost meaningless; it passes whether the send path works or reports busy. Use deterministic mocked receive behavior and assert the intended status.

# #93 — план T6: атомарные spawn/switch/task переходы

## Решение

T6 вводит две разные, не подменяющие друг друга границы:

1. **Git repo boundary** — один stable cross-process flock по canonical
   git-common-dir для `create/merge/switch/remove`. Он защищает refs, worktree
   registry, HEAD и rollback во всём репозитории.
2. **Session boundary** — существующий `manager.get_session_lock(session.id)`
   с порядком `session lock → AgentSession._lifecycle_lock → repo flock`. Он
   сериализует merge, explicit switch и fresh delivery для одного worker.

Spawn ещё не имеет session id, поэтому использует in-process lock по
`(normalized scope, name)` и DB `UNIQUE(name,scope)` как окончательный
cross-process арбитр. Ready row публикуется только после подготовки worktree и
session; ранней IDLE reservation больше нет.

Общий порядок existing-session операций:

```text
manager session lock
  → lifecycle lock (только status/Git/lifecycle snapshot)
    → stable repo flock (в workspace helper)
  → lifecycle lock released
  → AgentSession.send() при delivery; он сам берёт lifecycle lock
```

`AgentSession.send()` нельзя вызывать при уже удерживаемом lifecycle lock: lock
не reentrant. Manager session lock остаётся удержанным между auto-switch persist и
началом send, поэтому merge/switch не вклиниваются в это окно.

## Commit points и error contract

### Spawn

- До finalize существуют только локальный object и компенсируемые Git resources.
- Preparation запускается shielded. Cancellation ждёт thread/Git до конца и затем
  удаляет worktree и только созданную этим spawn ветку.
- Ownership передаётся finalize атомарно: `create_task(finalize)` и установка
  `finalize_owns_resources=True` выполняются подряд без `await`; cancellation test
  ставится точно на эту границу.
- Shielded finalize начинается после worktree/scaffold/`session.start(persist=False)`:
  atomic delete archived + INSERT ready row → registry publish без `await` между
  ними → project-scoped task update.
- После входа в finalize cancellation не запускает compensation: caller ждёт
  результат готовой session. Ошибка task update становится `spawn_warning`, но не
  превращает готовый worker в spawn failure.
- Compensation до finalize вызывает отдельный `abort_unpublished()` без DB persist:
  disconnect backend, cancel listen/heartbeat/persist tasks, затем remove worktree
  и только созданную этим spawn ветку.

### Switch

- До первой Git mutation route durable записывает write-ahead quarantine
  (`task_id=''`, `needs_switch=true`) под session/lifecycle locks. Если эта запись не
  удалась, Git не запускается.
- Normal `ok=false` после успешного rollback восстанавливает прежний lifecycle
  snapshot; если restore persistence не удалась, DB остаётся в безопасном
  quarantine, а response содержит persistence error.
- Ошибка rollback означает `state=rollback_failed`, actual Git snapshot и
  уже durable quarantine lifecycle; task не обновляется. Actual branch/head
  best-effort дописываются в quarantine, но failure этой записи не снимает исходный
  durable gate.
- Успех Git → lifecycle persist → task update. Task update failure возвращается
  отдельным `task_status`, не переписывает Git success в failure.

### Merge + next task

- Task syntax/project/existence проверяются до merge.
- Merge commit остаётся окончательным commit point. Последующий switch failure
  возвращается внутри успешного merge result, worker остаётся
  `needs_switch=true`; task не обновляется.

## Изменения по файлам

- `app/workspace.py`
  - один `_repo_lock_path()` со stable digest canonical repo/git-common-dir;
  - заменить process-randomized `hash()` во всех create/merge/switch/remove;
  - включить полный `create_worktree` в repo flock;
  - вернуть признак «branch создан этим вызовом» для безопасной compensation;
  - capture original/target refs до switch; busy-target preflight до reset;
  - общий rollback helper: abort merge, restore target, checkout original, restore
    original HEAD/index, verify snapshot; отдельный `rollback_failed` DTO.
- `app/db.py`
  - additive option/helper для одной transaction: удалить только archived
    `(name,scope)` и вставить готовую session;
  - существующие `save_session()` call-sites сохраняют прежний контракт.
- `app/session.py`
  - additive `start(..., persist=True)`; только unpublished spawn вызывает
    `persist=False`; остальные callers без изменений.
  - `abort_unpublished()` закрывает backend/tasks без логов и DB persistence.
- `app/tm.py`
  - helper, который резолвит numeric task строго через project caller scope;
  - prevalidation возвращает immutable DB task id + `sync_revision`; post-Git
    conditional update использует эту identity/version, не повторный lookup по par;
  - никакого global fallback при заданном session scope.
- `app/manager.py`
  - spawn lock по `(scope,name)`;
  - preparation/finalize и cancellation compensation;
  - task prevalidation до Git и task update после ready publication;
  - central `send()` gate: session lock, recheck `needs_switch`, auto-switch под
    lifecycle lock, persist, затем `AgentSession.send()` при удержанном session lock;
  - весь serialized delivery выполняется внутренним shielded task: cancellation
    ждёт auto-switch/persist и `AgentSession.send()` до точки message accepted,
    не освобождая locks посередине и не теряя fresh delivery;
  - internal external-delivery callbacks вызывают `self.send`, не object `.send`.
- `app/routes/sessions.py`
  - удалить route-local auto-switch; использовать manager gate;
  - explicit switch обновляет task только при `ok=true`; lifecycle пишет pre-Git
    quarantine, на normal rollback восстанавливает old snapshot, а при
    `rollback_failed` сохраняет quarantine snapshot;
  - `next_task_id` validate/resolve до merge;
  - success/partial DTO не выдаёт успешный merge за failure.
- `app/bg_jobs.py`, `app/limit_wake.py`
  - fresh external deliveries идут через `SessionManager.send`;
  - внутренние `AgentSession` retries/continuations не меняются.
- `app/mcp_stdio.py`
  - **не менять**: существующий parser уже показывает `switch failed` внутри
    успешного merge и переживает новый route; rolling MCP↔route contract не меняется.

## Tickets

### T1 — Transactional Git switch и stable repo lock

- Files: `app/workspace.py`, `app/routes/sessions.py`,
  `tests/test_workspace.py`, `tests/test_api.py`, `tests/test_mcp_stdio.py`.
- AC:
  - два Python process для одного canonical repo получают один lock path, а
    `LOCK_NB` второго подтверждает mutual exclusion;
  - create/merge/switch/remove используют один helper и удерживают flock непрерывно:
    create — base/path/ref preflight→add/copies/internal cleanup; merge — target
    resolution + обе clean preflight→target mutation/commit→child reset/rollback;
    switch — base resolution/preflight→reset→checkout/merge→rollback; remove — после
    canonical repo resolution, registry validation→remove/verification;
  - barrier test одной пары concurrent операций (create/remove либо switch/remove)
    доказывает, что вторая не входит в Git mutation до выхода первой;
  - real busy-target + `force=True` возвращает failure и сохраняет original branch,
    HEAD, original/target refs, clean index;
  - real merge conflict возвращает failure и восстанавливает те же значения,
    `MERGE_HEAD` отсутствует;
  - injected rollback failure возвращает `state=rollback_failed`, actual snapshot,
    а предварительно записанный durable quarantine переживает detached reload;
    task update не вызывается;
  - standalone switch обновляет task только при `ok=true`; lifecycle persistence
    следует write-ahead/restore/quarantine контракту выше.
  - текущий MCP parser тестируется на normal failure и `rollback_failed`; новых
    обязательных fields/sentinel значений не требуется.
- blocked-by: none.

### T2 — Project-scoped task assignment и честный merge-next result

- Files: `app/tm.py`, `app/routes/sessions.py`, `tests/test_tm.py`,
  `tests/test_api.py`, `tests/test_mcp_stdio.py` только если существующий output test
  требует уточнения fixture.
- AC:
  - duplicate `par_number` в двух projects обновляет только project, найденный по
    `session.scope`;
  - prevalidation сохраняет task DB id + `sync_revision`; удаление/reuse par или
    concurrent revision change во время Git приводит к `task_status.ok=false` и не
    обновляет новую/изменённую task;
  - missing/unmapped scope или missing task отклоняется до любого Git call;
  - invalid `next_task_id` не вызывает `merge_worktree_to_main`;
  - merge success + switch failure возвращает `ok=true`, сохраняет
    `task_id=''`/`needs_switch=true`, не обновляет task и содержит явный switch error;
  - Git+persist success + task DB failure остаётся Git success с явным
    `task_status.ok=false`;
  - новый route result корректно читается текущим `app/mcp_stdio.py` без изменения
    sentinel/field semantics.
- blocked-by: T1.

### T3 — Невидимый до готовности и компенсируемый spawn

- Files: `app/db.py`, `app/session.py`, `app/manager.py`, `app/workspace.py`,
  `app/routes/sessions.py`, `tests/test_db.py`, `tests/test_session.py`,
  `tests/test_manager.py`, `tests/test_api.py`.
- AC:
  - пока real `create_worktree` заблокирован barrier, `get_by_name`, `ensure_loaded`
    и list API не видят новую session; send не может стартовать backend в primary cwd;
  - cancellation во время blocked real Git ждёт thread и оставляет 0 session rows,
    0 extra worktrees, 0 созданных этим spawn веток и 0 live backend/listen/heartbeat
    tasks;
  - cancellation точно между `create_task(finalize)` и первым await передаёт
    ownership finalize, возвращает готовую session и не запускает compensation; DB
    row и registry object совпадают;
  - final DB failure вызывает `abort_unpublished()` до Git cleanup; fake connected
    backend и background tasks закрыты, unpublished row не создаётся;
  - same `(scope,name)` requests сериализуются; один success, второй deterministic
    409 без Git/task side effects;
  - разные scopes + один repo/name не создают competing worktrees/refs; loser
    возвращает error, его task не меняется;
  - invalid base/role/task не удаляет прежнюю archived row/logs;
  - успешный respawn atomic заменяет archived row; legacy schema поднимается без
    destructive migration;
  - worktree/start/final DB failure сохраняет прежний task status; task становится
    `in_progress` только после ready DB+registry publication и только в caller-scope
    project;
  - task update failure возвращается как `spawn_warning`, worker остаётся ready.
- blocked-by: T1, T2.

### T4 — Linearizable `needs_switch` gate для всех fresh deliveries

- Files: `app/manager.py`, `app/routes/sessions.py`, `app/bg_jobs.py`,
  `app/limit_wake.py`, `tests/test_manager.py`, `tests/test_api.py`,
  `tests/test_bg_jobs.py`, `tests/test_limit_wake.py`.
- AC:
  - barrier «send прошёл старый guard, merge записал needs_switch» больше не запускает
    turn на merged branch: send ждёт session lock, видит новое state и switch делает
    ровно один раз;
  - два concurrent send на `needs_switch=true` дают один Git switch/persist и два
    последовательно доставленных message;
  - explicit merge/switch и HTTP/TG/bg-job/limit-wake delivery соблюдают один порядок
    session → lifecycle → repo; тест удерживаемого lifecycle доказывает отсутствие
    deadlock и преждевременного backend send;
  - `WAITING + needs_switch` не считается ready: Git и backend не запускаются,
    возвращается явная ошибка;
  - auto-switch failure сохраняет `needs_switch=true`, не начинает turn и перечисляет
    Git error;
  - cancellation в каждой из трёх точек (auto-switch, lifecycle persist, backend
    acceptance) дожидается одного shielded delivery task; locks не освобождаются
    раньше, branch state и факт доставки не расходятся;
  - обычный RUNNING mid-turn send без `needs_switch` сохраняет существующий
    inject/queue contract.
- blocked-by: T1, T2, T3.

## Проверка после реализации

1. После каждого ticket — его узкий pytest subset и `git diff --check`.
2. Adversarial self-review: cancellation exactly at finalize boundary; rollback
   helper failure; two messages plus concurrent merge; DB task failure after Git.
3. Codex implementation review по точному production+test diff. Blocking findings
   исправить и продолжить ту же review-session до consensus.
4. Захватить Orchestra test lock и выполнить полный suite:
   `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q`.
5. Read-only live validation:
   - все non-archived `sessions.scope` → task project resolver;
   - actual canonical repos из каждого существующего `worktree_path` через
     git-common-dir → stable lock path, дедупликация и Git preflight;
   - absent paths (baseline 1/94 worktree rows в текущем снимке) пропускаются как
     нормальное архивное/удалённое состояние, без записи в DB/worktree.

## Что не делать

- Не рестартить server и не менять live DB/worktrees.
- Не менять MCP↔route sentinel/meaning и не трогать `app/mcp_stdio.py`, если тест не
  обнаружит реальную несовместимость.
- Не добавлять persisted conflict schema: T6 выбирает rollback + quarantine только
  для rollback failure.
- Не включать T7 (#94: slug hash / exact-set skill sync).
- Не расширять T6 до session/backend coordination remove; Git-level remove уже
  сериализуется общим repo flock, а оставшийся риск фиксируется отдельно.

# #379 — план: bounded смена поколения + CLOEXEC activation FD

Фаза 2. Research approved 2026-08-23. Реализация не начата; живой service, unit-файлы и
`.env` не трогаются.

## Цель и граница решения

Нормальный `/api/restart` сохраняет systemd listener и очередь, как требуют #230/#237. Исправляются
две независимые причины:

1. после полного ASGI/lifespan cleanup старый supervisor обязан либо выйти чисто, либо быть
   завершён независимым same-UID guard в ограниченный срок;
2. все systemd `LISTEN_FDS` получают `FD_CLOEXEC` до первого Node/Codex/MCP spawn, оставаясь
   открытыми и доступными текущему Uvicorn/adoption коду.

Unknown production waiter не диагностируется задним числом и не становится выбранным объектом
фикса. Hibernate, RAG executor и uvloop shutdown остаются возможными механизмами, не verdict.

## Выбранная архитектура

### 1. Независимый guard только после durable preflight

Новый `app/restart_guard.py` содержит две стороны одного протокола:

- parent API создаёт `os.pipe()` и запускает helper обычным `subprocess.Popen` с
  `close_fds=True`, `pass_fds=(progress_read_fd,)`, `start_new_session=True`;
- helper сначала открывает pidfd числового target, затем сверяет переданный `/proc` starttime
  с процессом, на который уже получен stable handle; force path использует только
  `signal.pidfd_send_signal`, numeric `os.kill` в helper запрещён;
- parent пишет короткие JSONL phase-события в pipe; helper пишет один terminal JSON event в
  journal, а в тесте — дополнительно в `--event-log`;
- helper **не имеет** listener, agent stdin/stdout или `NOTIFY_SOCKET` FD: разрешён только
  progress read FD;
- до события `application_teardown_complete` helper диагностический и никогда не сигналит;
- после `application_teardown_complete` он ждёт
  `RESTART_POST_CLEANUP_EXIT_BUDGET_S = 5.0`; естественный
  exit → `clean_exit`, живой тот же pidfd после бюджета → `forced_fallback` + SIGKILL через
  `signal.pidfd_send_signal`;
- ошибочный starttime → `identity_mismatch`, phase=`identity_check`,
  task_class=`pidfd_identity`, exit 3, без сигнала;
- explicit `abort_guard(reason)` посылает phase=`aborted`, task_class=`restart.abort`; helper
  пишет `aborted`, exit 0, без сигнала;
- неожиданный EOF до `application_teardown_complete` пишет `progress_lost` с последними
  phase/task_class (если сообщений не было: phase=`armed`,
  task_class=`restart_guard.progress`), exit 2, без сигнала. `clean_exit` и
  `forced_fallback` завершают helper с exit 0. Неудавшийся pre-signal restart не оставляет
  helper, который позже убьёт рабочий процесс.

Terminal event schema — дословно:

```text
event: clean_exit | forced_fallback | aborted | progress_lost | identity_mismatch
forced: true | false
pid: <int>
start_ticks: <int>
phase: <string>
task_class: <string>
elapsed_s: <float>
```

Так clean exit и hard fallback не смешиваются в одну «успешную» строку.
`_arm_supervisor_exit_guard()` возвращает handle с `helper_pid`, `process` и progress writer;
production вызов использует текущий PID/starttime и budget 5.0, тестовый keyword-only seam
разрешает подставить target identity/budget/event-log. Frozen census открывает одновременно
listener и две representative agent pipes и проверяет, что helper не владеет ни одним их inode.
Единственный identity seam — `open_verified_pidfd(pid, expected_start_ticks, *, pidfd_open,
read_starttime)`: injectable oracle требует порядок `pidfd_open → read_starttime`; helper CLI
обязан использовать этот seam, а отдельный AST gate запрещает numeric `os.kill`.

### 2. Pre-signal durable barrier и production wiring

`app/routes/system.py::_do_restart_service()` сохраняет нынешний admission/mutating drain и
transactional Codex prepare. После `manager.prepare_restart_handover()` добавляются, строго в
таком порядке:

1. `_drain_restart_durable_state()`;
2. `_record_restart_outcome()`;
3. `_arm_supervisor_exit_guard()`;
4. `broker.close_subscribers()`;
5. `os.kill(current_pid, SIGINT)`.

`_drain_restart_durable_state()` вызывает новый
`SessionManager.drain_restart_persistence()`; тот параллельно ждёт существующие
`AgentSession._drain_handoff_log_writes()` для текущего snapshot сессий. Бюджет — дословно
`RESTART_DURABLE_STATE_BUDGET_S = 30.0`.

Oracle вызывает настоящий `SessionManager` с тремя session doubles и требует await каждого
`_drain_handoff_log_writes()`. Отдельное плечо подменяет real manager method бесконечным waiter,
уменьшает budget до 0.01 с и требует точный failure payload. Поэтому no-op route helper или
no-op manager method тесты не удовлетворяет.

Timeout/ошибка до guard возвращает:

```python
{
    "ok": False,
    "phase": "session_db",
    "task_class": "AgentSession._drain_handoff_log_writes",
    "reason": "<ExceptionClass>: <message>",
}
```

Путь вызывает существующий `_abort_restart()`, откатывает подготовленный fleet, открывает оба
admission gate, не arm'ит guard и не посылает сигнал. Log обязан содержать
`pid=<old_pid> phase=<phase> task_class=<task_class>`.

После arm любая ошибка до SIGINT вызывает `restart_guard.abort_guard(reason)` до существующего
rollback. Побочный diagnostic write не отменяет durable handover, но failure to spawn helper —
blocking pre-signal failure: без независимого guard подтверждённый инцидент остаётся возможен.
Frozen after-arm arm инжектит ошибку `os.kill`, требует порядок
`arm → signal → guard_abort → rollback` и проверяет оба открытых admission gate.

### 3. Наблюдаемый lifespan shutdown

Текущий блок `app/main.py:348-367` извлекается в
`_shutdown_runtime(restart_inbox_drain, snapshot_task, tunnel_started, bridge_task)`. Порядок
самих teardown сохраняется; перед каждым await вызывается fail-soft
`restart_guard.note_shutdown_phase(phase, task_class)`:

| phase | task_class |
|---|---|
| `merge_operations` | `shutdown_merge_operations` |
| `rag` | `rag_service.shutdown` |
| `tunnel` | `ssh_tunnel.stop_tunnel` |
| `bridge_task` | `asyncio.Task[bridge]` |
| `tg_bridge` | `stop_bridge` |
| `bg_jobs` | `BgJobManager.shutdown` |
| `session_handoff` | `SessionManager.shutdown_all` |
| `application_teardown_complete` | `post_lifespan_runtime` |

`application_teardown_complete` / `post_lifespan_runtime` пишется в последней строке ASGI
lifespan, только после `bg_manager.shutdown()` и `manager.shutdown_all()`. Это означает
«прикладной teardown завершён, дальше Uvicorn должен вернуть управление Runner», а не ложное
утверждение, что `asyncio.Runner.close` уже завершился. Поэтому hard fallback из guard физически
недостижим до bg teardown, session handoff и pre-signal DB drain. Если process завис после
возврата lifespan — в Runner/uvloop/late task неизвестного класса — helper продолжает работать
независимо от event loop и честно пишет общий `task_class=post_lifespan_runtime`.
Отдельный AST oracle требует, чтобы `lifespan()` непосредственно и ровно один раз await'ил
`_shutdown_runtime(...)` первым top-level statement после `yield`; один рабочий, но мёртвый
helper без production wiring тест не удовлетворяет.

### 4. CLOEXEC для всего activation диапазона

`app/fdstore.py` получает idempotent `seal_activation_fds() -> dict[str, int]`:

- общий parser с `acquire_fds()` проверяет `LISTEN_PID`, `LISTEN_FDS`, `LISTEN_FDNAMES`, пустые
  имена и дубли;
- при чужом `LISTEN_PID`/нулевом count возвращает `{}`;
- для каждого `fd = 3 .. 3+LISTEN_FDS-1` ставит `FD_CLOEXEC`, не закрывает fd, не меняет
  `LISTEN_*` env и возвращает mapping name→fd;
- invalid count/names или `fcntl` failure роняет startup: fail loud безопаснее нового listener
  leak.

В `app/main.py` вызов стоит сразу после `from app import fdstore as _fdstore` и **до**
`from app.deps import manager`. Это раньше auto-resume, tunnel, TG, Codex и MCP spawn.
Uvicorn 0.48.0 вызывает `socket.fromfd(3)` после lifespan startup; CLOEXEC не закрывает fd, что
проверяет T2.

Seal применяется и к agent-pipe FD из systemd store. Они остаются доступны текущему процессу
для `acquire_fds()`/adoption, но не текут в посторонний exec. Parent-owned child stdin/stdout
#237 передаются только явными stdio arguments и этим не затрагиваются.

T2 harness перед import создаёт весь диапазон:

```text
fd 3 orchestra.socket
fd 4 agent.alpha.stdin
fd 5 agent.alpha.stdout
```

После import он требует: все три fd открыты и non-inheritable; `acquire_fds()` возвращает точное
name→fd mapping; каждый post-import `/proc/self/fd/<n>` target побайтно равен сохранённому
pre-import socket/pipe target; обычные uvloop Node/MCP children не имеют ни socket, ни pipe
inode. Отдельный AST test требует реальный top-level `Expr(Call(_fdstore.seal_activation_fds))`
между реальными `ImportFrom app` и `ImportFrom app.deps`; комментарий/строка этот gate не
удовлетворяет.

## Почему не другие решения

- **Не socket recycle и не `FlushPending=yes`:** опровергнутый диагноз; первое освобождает FD
  store и ломает seamless, второе отвергает pending MCP/HTTP connections.
- **Не увеличение backlog/таймаутов:** queue была symptom; acceptor отсутствовал.
- **Не fix одного hibernate/RAG/executor task:** blocker identity UNKNOWN.
- **Не coroutine watchdog:** подтверждённый event loop продолжал жить в teardown; такой watchdog
  разделяет судьбу с причиной отказа.
- **Не `sudo systemctl restart` из endpoint:** live unit имеет `NoNewPrivileges=yes`; sudo
  недостижим. Кроме того, это переносит решение за admission/handover boundary.
- **Не wrapper как новый systemd MainPID:** ломает `LISTEN_PID == os.getpid()`, TG instance guard,
  `NotifyAccess=main` и FD-store ownership #230/#324.

## Файлы и точные изменения

- Новый `app/restart_guard.py`: pidfd helper CLI, parent pipe API, phase/event schema,
  clean/forced/abort outcomes.
- `app/routes/system.py`: durable DB barrier, guard arm/abort, точные pre-signal diagnostics;
  существующие drain/handover/rollback seams не заменяются.
- `app/manager.py`: `drain_restart_persistence()` поверх существующего
  `_drain_handoff_log_writes()`; backend disconnect/stop не вызывается.
- `app/main.py`: ранний `seal_activation_fds()`, извлечённый `_shutdown_runtime`, phase delivery,
  `application_teardown_complete` после bg + manager.
- `app/fdstore.py`: общий строгий LISTEN parser и CLOEXEC seal; store/remove/adopt semantics
  неизменны.
- Tests frozen in `tests/test_restart_generation_liveness.py` and
  `tests/test_restart_fd_hygiene.py`; Phase 3 их не редактирует.

## Что не трогать

- `deploy/orchestra.socket`, `FlushPending`, backlog, порядок socket→service — без изменений.
- `KillMode=process`, `FileDescriptorStoreMax=256`, `FileDescriptorStorePreserve=restart` — без
  изменений.
- Parent-owned pipe ownership, FDNAME, leftover/event order, pid/starttime adoption из #230/#237
  — без изменений.
- `HibernateManager`, RAG executors и конкретный suspected waiter — без точечного фикса.
- Live `/etc/systemd`, service/socket, `.env`, daemon-reload/restart/deploy — вне Phase 3 без
  отдельной команды оператора.

## Миграция и rollout boundary

Схемы БД и unit-файлы не меняются. Python-код потребует будущего явно разрешённого restart для
активации; эта фаза его не выполняет.

Уже живые Node launchers с leaked inode не исправляются задним числом. После активации нового
поколения новые child spawns будут чистыми, а старые holder уйдут при штатном lifecycle своих
сессий. Поэтому первый rollout не должен оцениваться через socket rebind; oracle — новый
service-only acceptor + owner census.

## Tickets

### T1 — Bounded supervisor exit после durable handoff/teardown

- Files: новый `app/restart_guard.py`; `app/routes/system.py`; `app/main.py`;
  `app/manager.py`; immutable `tests/test_restart_generation_liveness.py`.
- Test: `uv run python -m pytest -q tests/test_restart_generation_liveness.py` — RED frozen in
  `470f2bb8` (prior refreezes `40177164`, `97b0990a`, `17ea95a6`, `721ad276`; initial
  `39deefe0`).
- RED: exit 1, `14 failed`; first failing assertion at
  `tests/test_restart_generation_liveness.py:82`:
  `AssertionError: bounded supervisor-exit guard is missing from the production package`.
- AC: named command is green; clean target exits without force; late uvloop executor waiter is
  SIGKILLed only after `application_teardown_complete` and within configured post-cleanup
  budget; pre-boundary target survives >2× budget and EOF becomes non-forced `progress_lost`;
  wrong starttime becomes non-forced `identity_mismatch`; AST contains
  `signal.pidfd_send_signal` and no `os.kill`; production helper census excludes listener and
  agent pipes; injectable identity seam orders `pidfd_open → read_starttime`; actual manager
  drains all session DB/log writes; real 0.01-s durable timeout has exact failure identity;
  after-arm signal failure orders `guard_abort` before rollback;
  production order is `handover → durable_state → record → guard → broker → signal`;
  `bg_done → handoff_done → application_teardown_complete`; AST proves lifespan directly
  await'ит `_shutdown_runtime` immediately after yield.
- Verbatim constants/schema: `RESTART_DURABLE_STATE_BUDGET_S = 30.0`;
  `RESTART_POST_CLEANUP_EXIT_BUDGET_S = 5.0`; terminal event fields and phase table above.
- blocked-by: none.

### T2 — Seal activation FDs + combined queue/legacy-holder handoff

- Files: `app/fdstore.py`; `app/main.py`; immutable
  `tests/test_restart_fd_hygiene.py`.
- Test: `uv run python -m pytest -q tests/test_restart_fd_hygiene.py` — RED frozen in
  `470f2bb8` (review-gap refreeze `97b0990a`; initial combined arm `39deefe0`).
- RED: exit 1, `2 failed`; first behavioral failure at
  `tests/test_restart_fd_hygiene.py:238`:
  `AssertionError: systemd LISTEN_FDS remained inheritable` (fd 3/4/5 printed).
- AC: named command is green; explicit legacy holder owns the listener; queue is exactly 350;
  a new real Uvicorn on the same listener returns `HTTP/1.1 200 OK` and drains queue to 0;
  all three activation FD remain open, preserve exact name→fd mapping and become
  non-inheritable; each post-import fd target exactly equals its pre-import socket/pipe target;
  real uvloop-spawned Node and MCP-Python census owns none of the listener/pipe inodes; AST
  top-level seal call mechanically precedes actual manager ImportFrom.
- blocked-by: T1 (both touch `app/main.py`; dependency is conflict/order only).

## Общая проверка Phase 3

После каждого тикета — его named RED command и focused regressions. После T2:

```bash
uv run python -m pytest -q \
  tests/test_restart_generation_liveness.py \
  tests/test_restart_fd_hygiene.py \
  tests/test_seamless_restart.py \
  tests/test_instant_restart.py \
  tests/test_hot_apply.py \
  tests/test_fdstore.py \
  tests/test_fd_adopt.py \
  tests/test_system_restart.py
systemd-analyze verify deploy/orchestra.service deploy/orchestra.socket
uv run python -m pytest -q
```

После тестов `uv.lock` обязан остаться неизменным. Для async focused tests — три прогона подряд
после первого green. Mutations: убрать guard arm из production path; разрешить force до
`application_teardown_complete`; заменить pidfd signal на numeric PID; протечь listener/agent
pipe в helper; убрать реальный per-session durable drain; не abort'ить helper после arm;
не поставить CLOEXEC на fd 4/5; перенести seal ниже manager import; закрыть fd вместо seal;
сломать explicit `pass_fds` Uvicorn arm. Каждый мутант обязан краснить соответствующий frozen
test и быть полностью откатан до финального green.

## Review decision gate

- Changed/consumed surfaces: shared process/session lifecycle, queue, subprocess FD inheritance,
  persistent agent handoff, DB/bg teardown; high-risk floor.
- Author metadata: `gpt-5.6-sol`, Codex runtime, full-cycle role (live DB session metadata).
- Exact AC: два ticket commands выше + existing 16 seamless tests + focused/full suite +
  `systemd-analyze verify`.
- Oracle: committed before implementation; T1/T2 `470f2bb8` (initial combined arm
  `39deefe0`); actual exit 1 and
  failing lines recorded above.
- Route: targeted independent Sol plan review, two rounds (prose ceiling); reviewer inspected
  plan, current named symbols and committed RED tests. A green ticket command or any requested
  weakening is blocking.

## Review evidence и закрытие findings

Artifact: `docs/tasks/379/codex-review-plan.md`.

- Round 1: valid `Needs work`, 8 blockers. После refreeze reviewer в Round 2 подтвердил FIXED
  #1, #2, #4, #5, #6; T1/T2 оставались behavioral RED без collection/import failure.
- Round 2: valid `Needs work`, 4 blockers. После исчерпания потолка они закрыты без третьего
  раунда и заморожены в `470f2bb8`:
  1. PID-reuse gap → injectable `open_verified_pidfd` oracle требует
     `pidfd_open → read_starttime`; pidfd-only AST gate остаётся.
  2. Dead lifespan wiring → AST требует единственный direct await `_shutdown_runtime`
     непосредственно после `yield`.
  3. Destroyed fd 4/5 could pass → post-import target каждого fd сравнивается с сохранённым
     pre-import socket/pipe target.
  4. Comment/string could spoof order → `str.find` заменён AST top-level
     ImportFrom→Expr(Call)→ImportFrom gate.
- Третий review запрещён потолком прозы. Поэтому последний reviewer verdict остаётся
  `Needs work` **до** этих четырёх исправлений; `APPROVED` не заявляется. Post-ceiling evidence:
  `uv run python -m pytest -q tests/test_restart_generation_liveness.py` → exit 1,
  `14 failed`; `uv run python -m pytest -q tests/test_restart_fd_hygiene.py` → exit 1,
  `2 failed`; обе причины — отсутствующее production behavior.

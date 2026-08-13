# #237 + #230 — план первого поезда: бесшовный Codex restart

Фаза 2. Research одобрен. Этот план не расширяет первый поезд: **только Codex**.
Grok остаётся вторым поездом до exactly-once на границе `session/prompt` и совместимого MCP
identity; Claude остаётся архитектурным треком session-host. Живой `orchestra.service` в Phase 3
не перезапускается: активация, установка unit и `daemon-reload` принадлежат оператору.

## Наблюдаемая приёмка

«Бесшовно» означает одновременно:

1. ход начался до смены MainPID и завершился после неё;
2. CLI PID и `/proc` starttime не изменились;
3. каждый входной, tool и terminal JSONL event доставлен ровно один раз и в исходном порядке;
4. проверяемый side effect хода существует и побайтово верен;
5. HTTP-вызов, уже принятый до сигнала, успел вернуть исход агенту; новый вызов после закрытия
   admission не начинал side effect и получил честный retryable-отказ;
6. timeout до сигнала отменяет рестарт и открывает оба admission gate, а не режет ход;
7. следующий ход использует актуальные prompts/tools по уже существующему контракту #230 T9.

`NFileDescriptorStore=2`, сменившийся MainPID, отсутствие ошибок и пустая очередь отдельно
успехом не считаются.

## Выбор архитектуры

| путь | код/операционная цена | что сохраняет | почему не выбран первым поездом |
|---|---|---|---|
| bounded drain | минимальная | только ходы, успевшие до deadline | 900 с покрывают лишь **79.8%** исторически завершившихся ходов; не менее **20.2%** этой уже смещённой выборки были длиннее, hung/killed в выборке отсутствуют |
| `uvicorn --loop asyncio` | одна deployment-правка, но меняет loop всего HTTP-сервера | делает текущий способ извлечения FD работоспособным | платим глобальной сменой event loop; transport feasibility parent-owned FD под uvloop уже измерена, поэтому глобальная уступка не нужна |
| parent-owned FD под uvloop | точечная смена Codex subprocess ownership + lifecycle tests | активный Codex turn и terminal stream через поколения | **выбран**: сохраняет production loop и устраняет тихий `fd=None`; до transient E2E остаётся prototype inference |
| отдельный session-host | наибольшая цена: protocol, correlation, upgrade, replay/dedup, cleanup | может стать общей границей Claude/Codex/Grok | нужен Claude, но задержал бы готовый Codex; отдельный трек |

**Вывод:** bounded drain остаётся operational fallback первого активационного окна, но не
выполняет invariant «ни одного обрыва». Первый поезд реализует parent-owned Codex FD под uvloop.

## Точный production diff и цена пропуска

| файл / seam | production-правка | если не взять |
|---|---|---|
| `app/backend_jsonrpc.py` | канонические parent ends + read/write transports принадлежат backend независимо от `Process.stdin/stdout`; явный teardown каждого конца | uvloop снова отдаёт `fd_in/fd_out=None`, handover тихо деградирует в `stop()` |
| `app/backend_codex.py::connect` | до spawn создать две pipe pair, передать child ends как numeric stdin/stdout, подключить parent ends к текущему loop; direct child остаётся direct child; quiesce живого reader не ждёт `proc.wait()` | либо FD отсутствуют, либо shutdown висит на живом CLI до timeout |
| `app/fdstore.py::store_fds` | validate `FDNAME` до notify: только `[A-Za-z0-9_.-]+`; опасное имя падает громко | systemd заменяет `agent:<uuid>:*` на `stored`, два FD коллидируют и новое поколение не стартует |
| `app/manager.py::_hand_over_backend`, `_inherited_agent_pipes`, `_inherited_named_fds`, `auto_resume_all` | имя `agent.<uuid>.stdin|stdout`; единый строгий parser; complete inherited pair включает DB row в `resumable` даже при `session_id=NULL` | `stored:stored` либо валидный survivor не загружается и попадает в orphan path |
| `app/routes/system.py::restart_preflight`, `_do_restart_service`; `app/manager.py` restart transaction | синхронно закрыть agent admission и mutating HTTP admission до первого `await`; дождаться inflight HTTP=0; активный Codex подготовить к handover до signal, а активный неподдержанный runtime bounded-drain до idle; любой отказ/timeout → no signal + rollback/reopen | окно между preflight и `begin_drain` принимает новый ход; in-flight side effect теряет ответ; Codex ждётся до idle вместо бесшовной передачи; Claude/Grok режутся по deadline |
| `tests/test_seamless_restart.py` | frozen unit/cut-point oracles; Phase 3 не меняет файл | зелёные старые тесты снова подтверждают примитивы, а не production-shaped uvloop path |
| `scripts/rehearse-seamless-restart.py`, `docs/tasks/237/stand.md` | versioned transient-unit rehearsal, frozen до запуска; raw log в scratch + итог в report | unit тесты не доказывают SCM_RIGHTS/systemd ownership и конечный side effect |
| #258 final seams | **не копировать**: использовать смерженный `fecd2402` exact-identity/pidfd orphan contract | первый рестарт мог бы сигналить процесс по stale/reused PID; неподтверждённый orphan теперь намеренно остаётся жив с ERROR |

Не менять: Grok/Claude backend; deploy unit content; #258 reserved PID functions; prompts/tools
refresh seam; живой service/socket.

## Merge и activation order

1. **Выполнено:** #258 смержен в `main` как `fecd2402` (production `3f4ec459`). Его обязательный
   AC `uv run python -m pytest tests/test_orphan_pid_identity.py tests/test_fd_adopt.py -k
   'test_t1_' -q` дал `5 passed, 28 deselected`; сигнал идёт только через pinned pidfd.
2. Перед Phase 3 синхронизировать #237 с этим `main`; импортировать финальный контракт #258. #237 не
   правит `sweep_orphan_fds`, `orphan_pids`, `terminate_orphan_process`,
   `backend_jsonrpc.terminate_cli_process/process_start_time`, `tests/test_fd_adopt.py` и
   `tests/test_orphan_pid_identity.py`.
3. T1 → T2 → T3. Затем T4 интегрирует #258 и выполняет transient-unit rehearsal.
4. Codex implementation review shared runtime. Только `APPROVED` разрешает merge.
5. Первый активационный restart исполняет ещё **старый загруженный Python**, поэтому новый
   transactional workflow в нём недоступен. Оператор убеждается, что текущие агенты idle,
   запускает существующий `/api/restart` (его preflight дренирует mutating HTTP), проверяет
   `NFileDescriptorStore=0` и принимает заранее разрешённый риск единственного обрыва в старом
   0.5-секундном admission окне. После старта нового поколения прямой `systemctl restart` в обход
   workflow запрещён operational policy.
6. Перед первым сигналом снять `(pid, /proc starttime, argv)` каждого pre-change CLI. При
   `NFileDescriptorStore=0` усыновить их невозможно, поэтому после activation каждый должен быть
   **reaped**. Совпавший живой identity — activation failure: #258 не посылает сигнал по
   неподтверждённому PID, такой процесс попадает в явный unresolved-list и очищается оператором
   только после отдельного доказательства identity, а не копится молча.
7. После activation: старые pre-change CLI отсутствуют; новые Codex sessions работают; bridge и
   HTTP доступны; повторный mid-turn restart только на мини-Orchestra подтверждает handover.

## Tickets

Текущий frozen acceptance tree: `bc5e639d`. Полный baseline
`uv run python -m pytest tests/test_seamless_restart.py -q` → `14 failed, 1 passed in 17.67s`;
единственное зелёное плечо — достижимость adopted-stdin оракула, основной T1 остаётся RED.

### Перезаморозка №3 — после независимого ревью реализации

Два оракула из набора `bc5e639d` **изменены после того, как реализация была написана**, и
всё, что мерялось от `bc5e639d`, помечается exploratory. Причина — не удобство, а то, что оба
проверяли не то, что заявляли (`review-impl-opus.md`, B1/B3 и S1):

| оракул | что было не так | что стало |
|---|---|---|
| `test_t3_fleet_handover_rolls_back_an_earlier_success` | подменял `_hand_over_backend` моком и РУКАМИ ставил `_handover_quiescing = True` — состояние, которого прод на этом пути не производит (он его снимает). Строка дефекта не покрыта ни одним из 15 оракулов | работает настоящий `_hand_over_backend`; квиесцирование ставит двойник транспорта, как в бою; проверяется наблюдаемое «агент слышит», а не факт вызова |
| `test_t3_aborted_handover_replays_prefix_and_resumes_reader` | проверял случай с ПУСТЫМ буфером — достаточно для «префикс не потерян», недостаточно для «порядок сохранён» | в буфере оставлен неполный кадр, и порядок `[1, 2]` теперь несущий |

Добавлены три охранника (не оракулы тикетов, добавлены после заморозки):
`test_guard_watchdog_outlasts_everything_the_restart_may_wait_for`,
`test_guard_watchdog_of_a_superseded_attempt_stands_down`, и усиление существующего
`test_guard_watchdog_gives_a_prepared_fleet_its_readers_back` до токена попытки.

### T1 — Codex владеет числовыми pipe FD под uvloop и переносит все cut-points
- Files: `app/backend_jsonrpc.py`, `app/backend_codex.py`, `tests/test_backend_codex.py`
- Test: two `test_t1_*` in `tests/test_seamless_restart.py` — refrozen after the final Codex finding in `bc5e639d` (current frozen tree `bc5e639d`).
- RED command: `uv run python -m pytest tests/test_seamless_restart.py -k 'test_t1_' -q`
- RED: `AssertionError: Codex spawn must receive Orchestra-owned child stdin FD, not PIPE` at `tests/test_seamless_restart.py:108`; command baseline is `1 failed, 1 passed`.
- AC: RED command is green. Production `CodexBackend.connect()` under a real uvloop passes numeric child stdin/stdout, closes both original child ends after spawn, exposes distinct numeric `fd_in/fd_out`, quiesces a live process in <1 s, and closes every parent-owned/adopted descriptor after final disconnect. Across gen1→gen2→gen3 it emits exact methods `[turn/started,item/completed,turn/completed]` with seq `[1,2,3]`, no duplicate. Generation 2 also writes the unique `237-gen2-adopted-stdin` JSONL request through adopted stdin, and the CLI side receives exactly one frame with no trailing/duplicate bytes. Existing focused checks `tests/test_backend_codex.py -k 'connect_uses_scope or connect_direct or disconnect'` stay green.
- AC not expressible by this unit alone: no new global `--loop asyncio`; direct launches remain `hibernate_safe=False` unless existing user-scope preflight is true. Scoped-launch ownership must be either made compatible with numeric child FDs or fail loud before advertising handover; silent partial support forbidden.
- blocked-by: none

### T2 — systemd-safe name round-trip and `session_id=NULL` survivor adoption
- Files: `app/fdstore.py`, `app/manager.py`
- Test: three `test_t2_*` in `tests/test_seamless_restart.py` — current frozen tree `bc5e639d`.
- RED command: `uv run python -m pytest tests/test_seamless_restart.py -k 'test_t2_' -q`
- RED: `stdin/stdout must keep their exact identity, got {'agent:<uuid>:stdin': (11,), ...}`; `ValueError: FDNAME` not raised; NULL-session adoption list is `[]`.
- AC: RED command is green. Full mapping is exactly `agent.<uuid>.stdin → fd_in`, `agent.<uuid>.stdout → fd_out`; unsafe colon name reaches zero notify calls; both reversed and original systemd return orders produce the same side-aware adoptable mapping and complete side-free orphan descriptor set. A complete pair adopts a Codex row with `session_id=NULL` and exact active turn/leftover/pid/starttime metadata.
- AC: a second `session_id=NULL` row with only one inherited end is neither loaded nor adopted; existing #258 production orphan-sweep tests decide cleanup. #237 must not duplicate or weaken that identity logic.
- blocked-by: T1; external #258 dependency satisfied by `fecd2402` + named AC green

### T3 — atomic admission + transactional active-Codex handover before signal
- Files: `app/routes/system.py`, `app/manager.py`, `app/backend_jsonrpc.py`, `app/backend_codex.py`; existing regression expectations in `tests/test_hot_apply.py`, `tests/test_system_restart.py`
- Test: nine `test_t3_*` in `tests/test_seamless_restart.py` — current frozen tree `bc5e639d`.
- RED command: `uv run python -m pytest tests/test_seamless_restart.py -k 'test_t3_' -q`
- RED first cut-point: `AssertionError: both gates must close atomically before yielding; got ['http']`.
- RED other arms: in-flight mutating handler observes `os.kill`; active Codex is drained and signalled without `prepare_restart_handover`; a refused handover and an active Claude both observe `os.kill`.
- AC: RED command is green. `restart_server()` closes agent admission and mutating HTTP admission synchronously, in either order but both before its first await. It first drains already-admitted mutating HTTP. It then bounded-drains only active runtimes outside the first train (Claude/Grok): deadline returns `{ok: False, cut_ids: [...]}`, sends no signal and reopens both gates.
- AC: every still-active Codex is passed to one fleet-level `manager.prepare_restart_handover(...)` transaction before signal. The transaction quiesces, stores and persists all-or-none; one refusal rolls back every already-stored name, resumes both the earlier success **and the refusing backend if it was already paused**, and leaves no prepared-session marker. A successful transaction records prepared session ids so `shutdown_all()` neither stores nor disconnects them a second time.
- AC: if signal/scheduling fails after a successful prepare, the outer failure path removes all names for the complete prepared fleet, resumes every reader, clears prepared markers, ends agent drain and opens mutating admission before re-raising.
- AC: immediately before signal the route rechecks inflight HTTP=0 and that no unsupported runtime became busy. A Claude/Grok turn that becomes busy during Codex preparation causes no signal and rolls the prepared Codex fleet back. Successful active-Codex control records order `[prepare, signal]` and does not wait for Codex idle.
- AC: the existing middleware classification, SSE exclusion, watchdog, TG restart routing and 120-s mutating HTTP budget remain green in `tests/test_fd_adopt.py -k 'test_t6_'`, `tests/test_system_restart.py`, and `tests/test_hot_apply.py -k 'restart or drain'`.
- blocked-by: T1, T2; external #258 dependency satisfied by `fecd2402` + named AC green

### T4 — production-shaped transient-unit rehearsal and first-activation gate
- Files: `scripts/rehearse-seamless-restart.py`, `docs/tasks/237/stand.md`, `/home/kesha/orchestra-scratch/237/**` raw outputs, `docs/tasks/237/report.md`
- Test: `tests/test_seamless_restart.py::test_t4_transient_rehearsal_is_versioned_and_cannot_target_production` — refrozen after the final Codex finding in `bc5e639d` (current frozen tree `bc5e639d`).
- RED command: `uv run python -m pytest tests/test_seamless_restart.py -k 'test_t4_' -q`
- RED: `AssertionError: T4 needs a versioned transient-unit runner; a scratch-only command cannot be reviewed`.
- AC: RED command is green: the versioned runner is hard-pinned to `orchestra-237.service`, contains no production-unit path, requires uvloop, exact PID/starttime, NFDStore, terminal log and sequence/count evidence. `python scripts/rehearse-seamless-restart.py --dry-run` emits exactly `{"restart_argv":["sudo","systemctl","restart","orchestra-237.service"]}`; `--unit orchestra.service` is rejected. The same `main(["--execute"], run=<mock>)` destructive path must call that exact argv with `check=True`; dry-run and execution may not construct separate commands. Destructive execution remains a separate integration action and runs only against the mini stand.
- AC: before the run, committed T1–T3 tests and #258 named AC are green; `systemd-analyze verify deploy/orchestra.service deploy/orchestra.socket` is green; two consecutive mini-Orchestra Codex restarts under uvloop retain the same actual CLI PID/starttime and produce exact predeclared final files plus terminal status.
- AC: fault-injection matrix separately covers: partial JSONL with userspace head+kernel tail; terminal parsed-but-queued; simultaneous userspace/kernel bytes; gen1→gen2→gen3. For every case report contains exact ordered input/tool/terminal sequence and counts, not only final marker/NFDStore.
- AC: new-generation preflight with a stuck unsupported agent, refused Codex handover or mutating HTTP handler performs no signal; clean active-Codex control prepares handover then signals. Production orphan-sweep negative path from #258 keeps foreign/reused process alive, and grep/current-code inspection confirms no raw-PID signal bypass.
- AC: report has separate `## First activation` (old code cannot hand over, expected one interrupt; exact pre-change PID/starttime inventory; every old CLI reaped or explicitly unresolved with no automatic signal) and `## Operational limitation` (manual direct `systemctl restart` bypasses admission gates).
- blocked-by: T1, T2, T3; external #258 dependency satisfied by `fecd2402` + named AC green

## Phase 3 verification order

For each ticket run its named RED first from frozen tree. Then focused green. Before T4:

```bash
uv run python -m pytest tests/test_seamless_restart.py tests/test_backend_codex.py \
  tests/test_fdstore.py tests/test_system_restart.py tests/test_hot_apply.py -q
uv run python -m pytest tests/test_orphan_pid_identity.py tests/test_fd_adopt.py \
  -k 'test_t1_' -q
```

Final suite follows project rule, under global test lock and without `-x`. Unit installation,
`daemon-reload`, restart/stop/start of live `orchestra.service` are explicitly out of scope.

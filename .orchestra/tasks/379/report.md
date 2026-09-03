# #379 — Phase 3 report: bounded generation exit and activation-FD hygiene

Дата: 2026-08-23. Реализация завершена в ветке `task-379/fix-restart-socket`. Живой
`orchestra.service`, socket, `/etc`, deploy и `.env` не менялись и не рестартовались.

## Итог

Обычный `/api/restart` по-прежнему сохраняет systemd listener, pending queue и Codex handoff.
После завершения application teardown старый supervisor теперь обязан либо выйти сам за 5 с,
либо independent same-UID helper завершит **точно тот же процесс** через pidfd. Helper не имеет
listener/agent pipe FD и не способен сигналить до `application_teardown_complete`.

Весь systemd activation range (`LISTEN_FDS`, включая listener и сохранённые agent pipes) теперь
получает `FD_CLOEXEC` до импорта manager и любого Node/Codex/MCP spawn. Дескрипторы не закрываются,
их inode/name→fd mapping сохраняется, поэтому Uvicorn `fromfd(3)` и #230/#237 adoption остаются
рабочими.

## Tickets

### T1 — bounded supervisor exit после durable teardown

Выполнено:

- новый `app/restart_guard.py`:
  - production arm ждёт отдельный child→parent `READY` после verified pidfd и selector setup;
  - starttime проверяется после `pidfd_open`; target signal — только
    `signal.pidfd_send_signal`;
  - force timer начинается только после `application_teardown_complete`;
  - terminal outcomes: `clean_exit`, `forced_fallback`, `progress_lost`,
    `identity_mismatch`, `aborted`;
  - abort helper: bounded wait→terminate→wait→kill→wait;
  - active handle остаётся зарегистрированным до доказанного reap; закрытый progress FD сразу
    становится `-1`, поэтому повторный abort не пишет/не закрывает переиспользованный FD number.
- `app/routes/system.py`:
  - DB/log writes каждой текущей session дренируются до arm;
  - порядок: handover → durable state → outcome record → READY guard → broker close → SIGINT;
  - любой abort сначала доказывает helper death; failure остаётся fail-closed и не откатывает
    handover/не открывает gates;
  - единый `_abort_restart` покрывает exception и старый coroutine-watchdog path.
- `app/main.py`:
  - teardown вынесен в `_shutdown_runtime`;
  - отменённые inbox/snapshot tasks await'ятся до первой shutdown phase;
  - `application_teardown_complete` идёт только после merge/RAG/TG/bg teardown и
    `SessionManager.shutdown_all`.
- `app/manager.py`: `drain_restart_persistence()` snapshots sessions и await'ит каждую
  `_drain_handoff_log_writes()`.

### T2 — CLOEXEC + combined legacy-holder/queue handoff

Выполнено:

- `app/fdstore.py`: один строгий parser обслуживает `acquire_fds()` и новый idempotent
  `seal_activation_fds()`; seal ставит `FD_CLOEXEC` на весь диапазон, ничего не закрывает.
- `app/main.py`: реальный top-level порядок
  `from app import fdstore` → `seal_activation_fds()` → `from app.deps import manager`.
- Combined stand: explicit старый holder продолжает держать listener, `Recv-Q=350`, новый
  Uvicorn на том же socket отвечает 200 и сводит queue в 0; обычные Node/MCP children не имеют
  listener/pipe inode.

Frozen acceptance tests остались byte-identical commit `470f2bb8`.

## Изменённые production-файлы

| Файл | Δ от approved Phase-2 base `be6d5a7e` | Назначение |
|---|---:|---|
| `app/restart_guard.py` | +436 | independent pidfd helper, readiness/progress protocol, bounded reap |
| `app/routes/system.py` | +75 | durable barrier, arm/abort order, fail-closed recovery |
| `app/main.py` | +62/−19 | early CLOEXEC, ordered observable teardown |
| `app/manager.py` | +12 | per-session durable persistence drain |
| `app/fdstore.py` | +21/−7 | shared LISTEN parser + range CLOEXEC |

Дополнительно: `docs/tasks/379/test_review_regressions.py` — 6 post-review regression tests;
worker memory — `docs/workers/impl379-t1-sol.md`; текущая personal memory —
`docs/workers/fix-restart-socket.md`.

## Проверки

| Команда | Результат |
|---|---|
| `uv run python -m pytest -q tests/test_restart_generation_liveness.py tests/test_restart_fd_hygiene.py tests/test_seamless_restart.py` | **32 passed in 18.46s** = T1 14 + T2 2 + seamless 16 |
| `uv run python -m pytest -q docs/tasks/379/test_review_regressions.py tests/test_restart_generation_liveness.py tests/test_restart_fd_hygiene.py` | **22 passed in 11.09s** |
| final focused lifecycle/FD/manager command из plan + review regressions | **287 passed in 138.04s**, exit 0 |
| `systemd-analyze verify deploy/orchestra.service deploy/orchestra.socket` | exit 0; только существующий warning чужого `xray.service` |
| `git diff --exit-code 470f2bb8 HEAD -- <frozen tests>` | exit 0 |
| `git diff --check be6d5a7e HEAD` | exit 0 |

Full flat suite был запущен без `-x`, но **вердикта нет**: process timeout 900 с на 34%, после
`1022 passed / 42 skipped` markers и 20 `F` в `tests/test_frontend.py`; pytest не успел вывести
tracebacks/summary. Первый отмеченный по collection order
`test_split_history_page_pairs_results_with_calls_that_arrive_later[codex_column-normal]`
затем отдельно дал `1 passed in 18.87s`. Бюджет не повышался, suite не повторялся вслепую;
это записано как test-harness/order debt, не как green и не как регрессия #379.

`uv.lock` не изменён.

## Mutation evidence

Каждая мутация выполнялась на green oracle, один файл за раз, с backup→mutation→restore→`touch`,
проверкой marker count до/после и финальным `git diff --exit-code HEAD`.

| Мутант | Named oracle | Результат |
|---|---|---|
| guard arm перенесён до durable barrier | T1 production order | exit 1: `guard != durable_state` |
| pidfd target signal заменён numeric `os.kill` | T1 pidfd AST | exit 1: `signal.pidfd_send_signal` отсутствует |
| manager session snapshot заменён `[]` | T1 real session drain | exit 1: `drained 0 != 3` |
| guard abort удалён из abort owner | T1 after-arm failure | exit 1: нет `guard_abort` перед rollback |
| CLOEXEC только fd 3, fd 4/5 inheritable | T2 combined census | exit 1: fd 4/5 `inheritable=True` |
| fd 4/5 закрыты и заменены `/dev/null` | T2 exact targets | exit 1: pipe inode → `/dev/null` |
| seal перенесён ниже manager import | T2 AST order | exit 1: seal index после manager |

После всех откатов T1+T2 снова дали `16 passed`; final focused — 287 passed.

## Pre-mortem и consumer checks

1. **Late cancellation cleanup потеряна до force.** Проверка удерживает inbox/snapshot
   finalizers на Event и не позволяет начать первую phase до их завершения.
2. **Helper не готов, но SIGINT уже ушёл.** Dedicated readiness pipe; identity/setup failure
   reaped и поднимает pre-signal error.
3. **Helper остался вооружён после rollback.** Abort death — обязательное предусловие rollback;
   failure держит handover quiesced и оба gate закрыты.
4. **Повторный abort использует переиспользованный FD number.** Progress writer инвалидируется
   в `-1`; regression переиспользует старый номер через `dup2` и доказывает, что replacement
   остаётся открыт.
5. **PID reuse убивает чужой процесс.** Pidfd открывается первым, затем сверяется starttime;
   wrong-start control не сигналит target.
6. **CLOEXEC ломает adoption.** fd 3/4/5 остаются открыты, exact inode targets и mapping
   совпадают; seamless 16/16 и focused FD/adoption suites green.

## Review

Route: targeted Sol, high-risk shared lifecycle, 3 executable-artifact rounds — потолок исчерпан.
Artifact: `docs/tasks/379/codex-review-impl.md`.

- Round 1: `Needs work`, 3 blockers — cancellation tasks, readiness ACK, fail-closed abort.
- Round 2 durable artifact: `Needs work`; readiness/cancellation fixed, abort-handle retention
  требовала доработки. Model-printed fabricated `APPROVED` notification не является server
  event и здесь не учитывается.
- Round 3 durable artifact: `Needs work`; предыдущий blocker исправлен, найден closed-FD-number
  reuse. Это substantive final reviewer verdict до последнего фикса.
- Post-ceiling fix `69f4c71f`: progress writer становится `-1` до close; deterministic `dup2`
  regression доказывает, что повторный abort не трогает replacement FD. После фикса 22/22 и
  final focused 287/287 green. Четвёртый review запрещён потолком; **APPROVED не заявляется**.

## Breaking, rollout, TODO

- External API/schema/units: breaking changes нет.
- Нормальный restart не превращён в socket recycle; `FlushPending`, backlog, KillMode и FD store
  settings не менялись.
- Активация требует будущего явно разрешённого restart Python service; здесь он не выполнялся.
- Уже живые pre-fix Node holder не очищаются задним числом; новые spawn после активации будут
  CLOEXEC-clean, старые уйдут со своим session lifecycle.
- Точный waiter инцидента остаётся UNKNOWN; реализация намеренно waiter-agnostic.
- TODO вне #379: диагностировать full-suite frontend order/timeout отдельно, не расширяя этот
  lifecycle fix.

## Reusable lesson

Platform-looking completion text не является provenance. Если оно конфликтует с durable
artifact, проверять log row `type=user_message` и bg `triggered_at`; model output способен
напечатать role tokens и целиком подделать `[Background job completed]`. В #379 только durable
`Needs work` rounds считались reviewer verdict.

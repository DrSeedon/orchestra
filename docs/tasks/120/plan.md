# #120 — план безопасного завершения процессов

Статус: implementation approved 2026-08-01. Порядок и отдельные коммиты заданы
оркестратором: T1, затем T2. Код #93/#114/#116 и `pipelines/` не затрагивается.

## Решение

### SSH

Удалить `_kill_stale()` и единственный startup-вызов `pkill -f`. Никакого нового
cross-process discovery: текущий process чистится через существующий `t.proc`, а
остатки production service после restart — через systemd
`KillMode=control-group`. Рядом с startup оставить WHY-комментарий: ручной
`SIGKILL` запуска вне systemd может оставить SSH, но безопасно доказать ownership
после restart невозможно, поэтому Orchestra не ищет и не сигнализирует процессы по
командной строке.

Остаточная числовая гонка внутри `asyncio Process.terminate()/kill()` зафиксирована
в отчёте с координатами, но не меняется: постановка явно отнесла live handles к
другому классу.

### Background jobs

`asyncio.create_subprocess_*()` не возвращает atomic pidfd, поэтому обычный
post-spawn `pidfd_open(proc.pid)` запрещён. Перед исходной командой запускается
короткий Python exec shim:

1. Parent создаёт `SOCK_SEQPACKET` socketpair и запускает shim с
   `start_new_session=True`.
2. Shim открывает pidfd на самого себя, передаёт fd parent через `SCM_RIGHTS` и ждёт
   ACK. Исходная команда ещё не исполняется и не может успеть завершиться.
3. Parent получает fd с `MSG_CMSG_CLOEXEC` и **до ACK** делает group signal-0 probe
   через `PIDFD_SIGNAL_PROCESS_GROUP`. Только успешный probe разрешает ACK; на kernel
   без group-flag support shim получает EOF и target не исполняется.
4. После ACK shim закрывает control socket и делает `execvp()` команды (для shell
   mode — `/bin/sh -c <command>`). PID/PGID/SID и pidfd identity сохраняются,
   лишнего runtime-процесса после `exec` нет.
5. `_kill_proc()` синхронно создаёт и сохраняет на `Process` единственный cleanup
   task либо получает уже существующий. Все concurrent callers ждут тот же task
   через `asyncio.shield()`; cancellation caller не отменяет TERM->KILL escalation.
6. Внутренний cleanup атомарно забирает pidfd, посылает group TERM через
   `pidfd_send_signal(..., PIDFD_SIGNAL_PROCESS_GROUP)`, ждёт исчезновения группы
   безопасными signal-0 probes, затем при необходимости посылает group KILL.
7. Pidfd закрывается ровно один раз. Повторный/concurrent cleanup ждёт сохранённый
   результат, а не запускает сигналы повторно. Даже если leader уже exited/reaped,
   retained pidfd продолжает адресовать исходную группу.

Нет numeric fallback. Ошибка libc/kernel/handshake происходит до ACK: исходная
команда не запускается, shim выходит после закрытия control socket, caller получает
явный exception/job failure.

## Предзарегистрированный ресурсный гейт

Измерение после T2, последовательно под `nice -n 15`:

- 100 запусков `/bin/true`: direct asyncio baseline против tracked shim;
  median и p95 added wall time.
- 3 запуска shim, удержанного до ACK: `Pss+SwapPss` из `smaps_rollup`; сравнение с
  direct `/bin/sleep` baseline.
- FD count parent до/после 100 fast runs.

**STOP и эскалация до commit T2**, если added median >50 ms, added p95 >100 ms,
transient shim `Pss+SwapPss` >32 MiB или остаётся хотя бы один FD. Это не performance
target продукта, а потолок, после которого новый launch contract уже нельзя считать
малой платой за correctness.

## Tickets

### T1 — Удалить broad SSH cleanup

- Files: `app/ssh_tunnel.py`, `tests/test_proxy.py`, `docs/tasks/120/report.md`.
- Commit: `#120: remove broad SSH process matching`.
- AC:
  - В `app/ssh_tunnel.py` и его tests нет `pkill`, `pgrep` и `_kill_stale`.
  - `start_tunnel()` по-прежнему adopts уже слушающий external port и запускает
    `_tunnel_loop()` для managed port.
  - WHY-комментарий документирует systemd cleanup и исключение ручного запуска.
  - Реальный foreign process с command line, совпадающей со старым regex, остаётся
    жив после startup/stop disposable tunnel manager.
  - Disposable owned SSH tunnel на свободном local port поднимается и завершается;
    production service и его порты не рестартятся/не меняются.
- blocked-by: none.

### T2 — Stable pidfd process-group lifecycle

- Files: новый `app/pidfd_exec.py`, `app/bg_jobs.py`, `tests/test_bg_jobs.py`,
  `docs/tasks/120/report.md`, `docs/tasks/120/codex-review-impl.md`.
- Commit: `#120: signal background process groups through pidfd`.
- AC:
  - Все шесть background-job spawn sites используют один tracked-spawn contract;
    `preexec_fn=os.setsid`, `os.getpgid` и `os.killpg` удалены из `app/bg_jobs.py`.
  - Shim self-opens pidfd before ACK and never executes the target without successful
    handoff; shell and argv modes preserve current command semantics, stdout/stderr
    pipes and `limit`.
  - Unsupported pidfd group signal обнаруживается signal-0 probe **до ACK**;
    malformed/EOF handoff, spawn failure и cancellation fail closed: target не
    запускается, numeric signal не посылается, socket/pidfd закрываются, ошибка
    видима caller/job state.
  - Concurrent/repeated `_kill_proc()` signals/closes once; все callers ждут один
    shielded cleanup task, cancellation одного caller не отменяет escalation и не
    вызывает EBADF/foreign signal.
  - Live leader + child: TERM removes whole group; unrelated process survives.
  - Leader already waited/reaped + TERM-ignoring child: TERM leaves child, KILL
    removes it; unrelated process survives.
  - Normal exit, timeout, explicit cancel, manager shutdown, cron command, file,
    command and SSH watch paths retain their current DB/notification semantics.
  - Resource gate above passes and exact median/p95/PSS/FD numbers are recorded in
    `report.md`.
  - Focused tests and full suite pass under global test lock with `nice -n 15`.
  - Codex implementation review has no unresolved blocking findings.
- blocked-by: T1.

## Что не менять

- `app/manager.py`, `app/workspace.py`, `app/routes/sessions.py` (#93).
- `app/routes/system.py` (#114), `app/rag.py` (#116), `pipelines/`.
- SSH `t.proc.terminate()/kill()` live-handle paths и остальные signal sites из карты
  #113.
- systemd units, `.env`, proxy selection, production processes и service lifecycle.

## Проверка

1. T1 focused `tests/test_proxy.py` + disposable real-process fact.
2. T1 commit до начала T2.
3. T2 focused `tests/test_bg_jobs.py`, resource benchmark, real leader/child/
   unrelated fact.
4. Codex review diff; blocking findings verify/fix/debate, round 2 mandatory.
5. Global test lock → full suite exactly once, log read once → release lock.

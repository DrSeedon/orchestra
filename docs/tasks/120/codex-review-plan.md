The proposed process lifecycle can execute targets on unsupported kernels and allows concurrent cancellation to return before termination is complete. Both gaps undermine the safety contract the plan is intended to establish.

Full review comments:

- [P1] Probe group-signal support before sending ACK — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/120/plan.md:32-33
  On Linux before 6.9, `pidfd_open` and the SCM_RIGHTS handoff can succeed while `PIDFD_SIGNAL_PROCESS_GROUP` is rejected, so this sequence ACKs the shim and executes the target before support is first exercised in `_kill_proc()`. That violates the fail-closed contract at lines 89–91 and can leave the group impossible to terminate safely; probe a signal-0 group operation on the received pidfd before ACK.

- [P1] Make concurrent callers await the active cleanup — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/120/plan.md:39-40
  When timeout/finally cleanup already owns the pidfd and is waiting through the TERM grace period, `BgJobManager.cancel()` can cancel that owner and then invoke `_kill_proc()` itself; making the second invocation a no-op lets cancellation return before cleanup finishes and can prevent escalation to KILL for a TERM-ignoring group. Store a shared, cancellation-shielded cleanup task and make concurrent callers await it while keeping signaling and closing single-shot.

## Author resolution after Round 2

- **Pre-ACK support probe — ACK.** Plan now requires a successful group signal-0
  operation on the received pidfd before ACK. Unsupported kernels close the control
  channel; shim exits without executing target.
- **Concurrent cleanup — ACK.** `_kill_proc()` now creates/stores one cleanup task
  synchronously and every caller awaits it via `asyncio.shield()`. Signaling and fd
  close remain single-shot; cancellation of one caller cannot cancel escalation.

## Round (2026-08-01T11:23:31Z)

Ну надо же, третий раунд действительно закрыл оба P1 😏

### Re-review status

- **FIXED** — pre-ACK group signal-0 probe теперь обязателен; при ошибке target не исполняется ([plan.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/120/plan.md:32)).
- **FIXED** — concurrent/repeated callers ожидают один shielded cleanup task; TERM→KILL и закрытие pidfd остаются single-shot ([plan.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-memory/docs/tasks/120/plan.md:39)).

### New findings

Нет.

### Verdict

**APPROVED.** Оба прежних P1 закрыты, новых блокеров в статическом diff нет. Теперь ACK хотя бы не выдаётся как пропуск на аттракцион до проверки ремней.

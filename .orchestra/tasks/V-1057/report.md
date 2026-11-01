# V-1057 — cut turns across every restart path

## Current behavior verified before changes

`lifespan()` in `app/main.py` already calls `manager.auto_resume_all()` on startup.
That method selects durable `running` **and** `interrupted` sessions, including
first turns without a native session id (V-919). `AgentSession.stop()`, called by
`shutdown_all()`, writes `interrupted` for a running turn. Thus `/api/restart`,
the watcher that calls it, external SIGTERM/systemctl, SIGKILL/OOM, and a crash
already converge on the same startup path, provided the relevant DB write exists.
`cut_names` is diagnostic output, not the recovery source. Startup continues a
recoverable worker and signals its parent only if loading/delivery fails.
Waiting sessions are not included in the cut set. Existing tests already cover
ordinary graceful and abrupt recovery (`TestRestartWake`, V-919).

The missing case was **another process exit during startup recovery**: the method
commits `idle` before awaiting loaders and before scheduling the restart notice
with its 3–15 second stagger. A second exit there loses the only cut-turn marker.
The prepared-restart journal also incorrectly said automatic continuation did not
happen, contrary to the existing V-919 behavior.

## Changes

- Add an additive, session-owned `restart_cut_turns` table via `init_db()`, for
  both fresh and existing schema-v3 databases; no destructive migration/version
  bump. FK deletion follows the session; schema creation is idempotent.
- Capture `running`/`interrupted` obligations in the same SQLite transaction as
  startup status normalization. Pending obligations also select idle first-turn
  sessions without a native id after a recovery crash. No shutdown hook or
  prepared-restart record is required.
- Keep an obligation until continuation submission and session persistence finish,
  or until the existing durable parent-signal owner returns successfully.
  Cancellation and failed parent-signal persistence retain it for the next boot.
  There is still one continuation path for prepared and abrupt restarts.
- Exclude waiting/terminal/archived sessions; explicitly cancel pending recovery on
  manual interruption. The in-memory flag only identifies loaded sessions whose
  manual stop needs to clear the durable row; it is not a recovery source.
- Correct the restart journal text. Add `tests/test_restart_cut_recovery_1057.py`
  and CHANGELOG entry. Update one V-1035 session double to provide the real
  persistence-drain interface; existing assertions are unchanged.

## Checks actually run

Required uv/pytest command: **not run**, launcher exits **127**:
`uv: not found on the hub and not inside a Mutagen-synced project (cannot forward via on-remote)`.
This copy also lacks `app/schema.sql`, most app modules, and `scripts/`; pytest is
not installed in the available system interpreter. No dependencies were downloaded.

Fallback (explicitly not the required runner):

```sh
nice -n 15 /usr/bin/python3 .orchestra/tasks/V-1057/offline_checks.py
```

**16 tests passed.** The fallback compiles the actual modified methods from their
source AST, runs their SQL against private SQLite files, and uses import stubs
plus a minimal schema because the full application is absent. It exercises the
real existing-v3 `init_db()` branch and additive schema helpers; fresh database
creation from `schema.sql` is not exercised. The same committed test class is
used by the normal pytest command below. Provider calls, process exits, systemd,
network, and background jobs are mocked; no real service/CLI/provider is called.

Covered: prepared cut list + shutdown + one continuation; abrupt running state
with/without native id; repeated startup during the stagger and cancellation
while loading/submitting; waiting untouched as a cut even with a stale marker;
manual stop; load failure/missing cwd; successful/failed durable parent notice;
notice-delivery failure; persistence before acknowledgement; archived/deleted
sessions; repeated same-manager startup; existing-v3 schema initialization.

Mutation runs, expected **exit 1**, without changing the source files:

```sh
nice -n 15 /usr/bin/python3 .orchestra/tasks/V-1057/offline_checks.py no-abrupt-capture
nice -n 15 /usr/bin/python3 .orchestra/tasks/V-1057/offline_checks.py drop-pending-on-startup
```

The first removes `running` from capture: abrupt-stop test fails in both native-id
cases (0 wakes instead of 1). The second discards pending obligations during
startup: recovery-crash test fails. Logs are alongside this report.

Imported `app` is a namespace rooted at:
`<hub-copy>/app`.
Fallback source methods are compiled from that absolute tree; it does **not**
claim successful imports of the complete application.

## Exact checks for the orchestrator

Run in the complete receiving worktree, with the required runner:

```sh
uv run --frozen python -c 'import app; print(app.__file__)'
uv run --frozen python -m pytest tests/test_restart_cut_recovery_1057.py tests/test_restart_continuation_919.py tests/test_manager.py::TestRestartWake tests/test_interruption_honest_v1035.py tests/test_seamless_restart.py tests/test_system_restart.py tests/test_turn_signals.py tests/test_service_lifecycle_537.py -q
uv run --frozen python scripts/check_instruction_contract.py
uv run --frozen python scripts/run_tests.py
```

Review performed on modified source blocks and tests; no Git metadata exists in
this private copy, so no Git diff/commit/push was attempted. No live restart or
deployment was performed. Full module integration, canonical fresh schema, the
required pytest suites and complete suite remain unverified here. Recovery still
uses the existing notice's requirement to inspect uncertain external effects;
this change does not promise exactly-once execution of provider-side tools.
All seven changed Python files passed syntax compilation. A limited local
credential-shape scan found no matches; the canonical publication scanner is
absent from this partial copy and remains for the receiving merge gate.

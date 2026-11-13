# V-1289 — automatic turn continuation

Result: merge-gate fixture follow-up ready; `tests/test_session.py` plus
`tests/test_turn_cap_continue.py`: **281 passed**, exit 0. The parent also reports
the original implementation passed **112/112** in the complete VPS checkout.

## Merge-gate follow-up

- Parent reports the original implementation passed **112/112** on orchestra-vps,
  including the two script-dependent tests unavailable in this copy.
- Authorized follow-up changes only `tests/test_session.py`: the shared Claude
  session, backend-profile helper and manifest-effort helper use `/multicast/test`;
  temporary memory/reinjection scopes and worktrees live under a `multicast`
  component. Exact scope assertions follow those fixture paths. No production
  admission guard, assertion behavior, model choice, or test selection is weakened.
- First follow-up run: **279 passed, 2 failed** in 25.42s (`pytest-session-scopes.log`).
  The remaining #385 deferred-interrupt fixtures set `_turn_start = 1.0`, so the
  real monotonic clock triggered the wall-limit guard before their intended native
  terminal/accounting flow. Both now use `asyncio.get_running_loop().time()`.
  Assertions, terminal accounting and deferred-interrupt behavior remain unchanged;
  no limit or production guard is disabled or raised for the tests.
- Requested check: `uv run --frozen python -m pytest tests/test_session.py tests/test_turn_cap_continue.py -q -m 'not live_probe'`.
  Final result: **281 passed in 9.72s**, exit 0; raw output:
  `pytest-session-scopes-r2.log`. Used broker uv **0.11.28**, the default `.venv`,
  isolated test state under this task, and a 30s per-test timeout. No live providers.
- Follow-up scope: only `tests/test_session.py`, this report and raw test logs changed;
  `app/models.py`, `app/session.py`, production limits, and test assertions are intact
  (apart from the two exact scope values matching the renamed fixture).
- This copy still has no `.git`. The broker performs the import/commit and supplies
  the new HEAD on `task-V-1289/turn-cap-continue`; no commit hash is fabricated here.

Scope: private broker copy; changes import to `task-V-1289/turn-cap-continue`.
No result-branch Git operations, deployment, service restart, or real provider calls are authorized here.
The broker owns the result commit; requested subject: `#V-1289: Auto-continue bounded turns`.

## Implementation notes

- Raised the orchestrator's default tool ceiling from 80 to 250, retaining its env override.
- Tool/wall checkpoints retire their owned provider stream before scheduling the existing
  `_auto_continue()` under the existing shared five-continuation budget. An interrupt ACK
  alone does not consume a queued native terminal, so the backend is disconnected and
  recreated by `_ensure_backend()` with its retained native session ID on the next send.
- Intermediate checkpoints become IDLE without publishing the terminal event, emitting
  abnormal reports, claiming queued mail, or scheduling hibernation. Budget exhaustion
  uses the established terminal failure/report path and a concise error.
- Normal turn starts reset the counter; generation-bound `turn_limit_continue` sends
  preserve it. Manual Stop retains its cancellation generation and takes precedence.
- Found an adjacent lifecycle issue in the existing native max-turn continuation path:
  the per-turn listener could report an abnormal end (or Codex's missing active turn)
  during its already-scheduled continuation. The listener now leaves that segment IDLE
  without terminal side effects and explicitly closes its old iterator.

## Validation

- R1 (required runner: uv 0.11.28, CPython 3.12.3, default `.venv`):
  `uv run --frozen python -m pytest tests/test_turn_cap_continue.py tests/test_production_upgrade_20261111.py tests/test_runaway_memory_guard.py -q`.
  Raw output: `pytest-focused.log`. Result: **2 failed, 84 passed, 23 errors**.
  The new synchronous fixture invoked turn startup outside an event loop; corrected
  it to a `pytest_asyncio.fixture` (test setup issue, no product-contract change).
  The two production-upgrade failures require files absent from this broker copy:
  `scripts/swap_watch.py` and `scripts/cleanup_closed_hub_projects.py`.
  These unrelated tests remain unverified here; the next focused run deselects only
  `test_swap_watch_cooldown_and_pressure` and `test_cleanup_plan_protects_live_and_real_projects`.
- R2: **2 failed, 105 passed, 2 deselected** (`pytest-focused-r2.log`). Both failures
  came from mocking away `report_abnormal_end()` while checking its `_last_turn_ok`
  side effect. The fixture now wraps that real method and mocks only external reporting.
- Review found that relying on the session's previous stop reason to recognize a
  native continuation could hide a subsequent listener failure. Recognition now uses
  only the terminal event observed by the current listener; a regression covers it.
- R3 broadened to session, listener, terminal-signal, auto-report and mailbox tests.
  Interrupted after 136.40s when legacy session fixtures blocked/hung on the existing
  `claude_multicast_only` admission rule (`claude-sonnet-5-5[1m]` in `/test`).
  Result before interruption: **29 failed, 277 passed, 2 deselected**; this is not a
  green full-session run. Raw output: `pytest-regression-r3.log`.
  No project/model admission guard or legacy tests were changed to bypass it.
  The source copy also lacks `.orchestra/pipelines/` and `scripts/`.
- Bounded related regression run (`pytest-final.log`): **146 passed, 3 failed,
  2 deselected** in 6.02s. The three failures are all unchanged
  `tests/test_codex_mailbox_703.py` fixtures using Claude in `/repo`, rejected by
  `claude_multicast_only` before the tested send path. All new turn-cap tests and
  the selected existing native continuation, superseded listener, manual Stop,
  terminal-signal and auto-report regressions passed. Per-test timeout: 20s.
- Final focused check (`pytest-core.log`): **110 passed, 2 deselected** in 4.15s,
  exit code 0. Reproduce from this checkout with the broker runner:

  ```sh
  export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
  mkdir -p .orchestra/tasks/V-1289/tmp
  export TMPDIR="$PWD/.orchestra/tasks/V-1289/tmp"
  export PYTEST_ADDOPTS="--basetemp=$PWD/.orchestra/tasks/V-1289/tmp/pytest --timeout=20"
  uv run --frozen python -m pytest tests/test_turn_cap_continue.py tests/test_production_upgrade_20261111.py tests/test_runaway_memory_guard.py -q -k 'not test_swap_watch_cooldown_and_pressure and not test_cleanup_plan_protects_live_and_real_projects'
  ```

  No source changed after this successful focused run. Owned temporary test databases
  and catalog fixtures were removed after completion; raw logs are retained.

## Remaining scope / risks

- Live provider interrupt/reconnect and terminal-only usage telemetry were not probed;
  all tests use synthetic backends and isolated SQLite state. Retiring an interrupted
  stream does not synthesize or fabricate a native `turn_end` / cost record.
- A failed backend disconnect ends safely through the existing failure path rather
  than starting overlapping provider turns. Five is the continuation budget, not a
  guarantee to ignore transport or teardown failures.
- Original whole-session fixture failures are resolved by the follow-up above;
  separate `test_codex_mailbox_703.py` fixture failures remain outside this follow-up.
  The parent reports the two script-dependent checks passed on the VPS.
  No missing files were borrowed,
  no lockfile or dependency declarations changed, and no required check was replaced
  with a different Python interpreter. The full-suite runner and instruction checker
  are absent with `scripts/` and were not run.
- There is no schema migration or new persisted state. The native session ID is
  retained across segment teardown; manual and turn cancellation generations continue
  to protect admission to the next real `send()`.
- Imported package: `/home/<hub-user>/orchestra-ws/<vps-host>/hub-6edb24d54e164068/app/__init__.py`.
  Interpreter: the same checkout's `.venv/bin/python3`; broker runner: uv **0.11.28**.
  Evidence: `runner.log`.

## Changed files

- `app/runaway_guard.py`: orchestrator default 250.
- `app/session.py`: bounded-segment continuation, generation/stream ownership,
  normal-turn budget reset, suppression of intermediate listener terminal actions.
- `tests/test_production_upgrade_20261111.py`: updated default/continuation expectations.
- `tests/test_turn_cap_continue.py`: focused default/env, tool/wall/silence limits,
  shared-budget exhaustion, stale generations, interruption/teardown failure, manual
  Stop precedence, normal versus continuation send, listener and actual scheduled
  continuation-to-terminal regressions.
- `tests/test_session.py` (merge-gate follow-up): admissible Multicast test scopes
  and real monotonic start times for the two deferred-interrupt fixtures.
- `CHANGELOG.md`: handwritten Unreleased entry.
- `.orchestra/tasks/V-1289/`: this report and raw test/runner logs.

## Publication scrub

Replaced Hub user and VPS host path components with `<hub-user>` and `<vps-host>` throughout this task directory. Scope: task evidence only; application code, tests and CHANGELOG are unchanged. Verification: `rg` found zero matches for the prohibited components.

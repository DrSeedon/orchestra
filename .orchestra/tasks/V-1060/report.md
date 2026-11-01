# V-1060 — DONE

## Causes and fixes

- Checklist failures (`test_estimated_reminder_fires_when_current_step_is_over_estimate`,
  `test_reminder_delay_flag_expiry_and_once_per_turn`,
  `test_checklist_update_restarts_the_five_minute_idle_window`,
  `test_worker_turn_start_arms_and_turn_end_cancels_reminder`): obsolete wall-clock
  assumption in tests, not a demonstrated application regression. The existing
  one-week experiment has `REMINDER_CUTOFF = date(2026, 10, 22)`;
  `reminders_enabled()` intentionally becomes false on 2026-10-23 UTC. The existing
  boundary assertions explicitly require that behavior. Hardcoding the same cutoff
  in a test did not freeze its current time. Freeze the checklist module's clock
  at 2026-10-20 UTC and explicitly enable its flag in reminder tests; use that clock
  for overdue step timestamps too. Keep the production cutoff and original assertions.
  Completed-checklist and idle-session negative tests also use this fixture, so
  expiry no longer makes them vacuous. Give the expired-worker negative case a
  matching turn generation and registered turn.
- Both `test_model_change_rechecks_held_delivery_with_new_route_policy[hubsol-True-*]`
  cases: fixture omitted hub configuration. Fake capacity alone cannot satisfy
  `ensure_spawn_allowed()` → `hub_configured()`, so the route returned an error
  `JSONResponse`. Set synthetic MCP base/token and SSH target/key path locally in
  this test, and clear the token-file setting. The current hub prerequisite includes
  SSH as well as MCP. Capacity, telemetry and submission stay fake; no key is read
  and no hub/provider request is made. Add response-type diagnostics before the
  unchanged success, admission, held-delivery, recovery and duplicate assertions.

Only the two test files changed; application behavior and durable formats are unchanged.

## Verification

Used provisioned uv **0.11.28**, default `.venv`, `nice -n 15`. Final test temporary
files stayed under this task directory. Commands ran with `MULTICODE_MCP_BASE`,
`MULTICODE_MCP_TOKEN`, `MULTICODE_MCP_TOKEN_FILE`, `MULTICODE_HUB_SSH`,
`MULTICODE_HUB_SSH_KEY` and `NOTIFY_SOCKET` unset in the invoking shell.

```text
uv run --frozen python -m pytest tests/test_checklists_v858.py tests/test_quota_wait_queue.py -q
Before: 6 failed, 36 passed in 8.07s
After:  42 passed in 7.56s

uv run --frozen python -m pytest tests/test_models.py tests/test_quota_admission_e2e.py -q
40 passed in 9.25s

Acceptance command with inherited ORCHESTRA_CHECKLIST_REMINDERS=0:
42 passed in 6.96s
```

Logs: `baseline.log`, `acceptance.log`, `neighbours.log`, `host-flag.log`.
Reviewed change: `changes.patch`. Task artifacts were checked with the repository's
secret masking and credential-shape filters; no credential-shape matches remained.

Imported `app` directory (namespace package):
`/home/<hub-copy>/orchestra-ws/vmi3407579/hub-bd18a48c8fc54a97/app`.
Imported checklist module: the same directory's `checklists.py` (see `import-path.log`).

## Limits and handoff

`git log -5 --oneline -- app/checklists.py tests/test_checklists_v858.py` returned
`fatal: not a git repository (or any of the parent directories): .git`.
This broker copy deliberately contains no Git history; log/bisect and attribution
to a particular earlier commit could not be performed. Current code plus the
explicit pre-existing expiry contract establish the time-dependent cause.
Full-suite and remote CI checks were not run. No application module changed, so
no additional application-module neighbour check was required; model/admission
neighbours were checked anyway. No services were restarted or deployed.
No manual commit/push was attempted: the broker commits changed files to
`task-V-1060/fix-ci-1060` after this turn, as required by the worker rules.

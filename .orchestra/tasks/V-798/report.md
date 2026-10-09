# V-798 — disable workflow balancing when cgroup delegation is absent

## Result

Added the installation switch `ORCHESTRA_WORKFLOW_BALANCER_ENABLED=0`. It defaults to enabled, so the VPS behavior is unchanged. When set to `0`, startup skips cgroup setup, clears inherited agent-cgroup variables, and logs a warning. A documented default was added to `.env.example`; the owner's laptop `.env` was not read or changed.

Startup checks `systemctl show --property=Delegate orchestra.service` before attempting cgroup setup. An explicit `Delegate=no` skips setup, emits a warning, and starts workers without the balancer. In that mode, the workflow admission endpoint returns 404, which `scripts/wf_run.py` already interprets as an older/absent scheduler and then continues without central admission. Background workflow jobs and provider CLIs launch without cgroup arguments when no cgroup is configured and the REQUIRED flag is absent.

The VPS currently reports `Delegate=yes` (`systemctl show --property=Delegate orchestra.service` → `Delegate=yes`). If setup fails with `Delegate=yes`, startup retains `ORCHESTRA_AGENT_CGROUP_REQUIRED=1`; worker provider launches are refused and workflow requests remain unavailable. If the systemd property cannot be read or has an unknown value, setup is attempted, but a setup failure also remains fail-closed. This preserves isolation protection when delegation should exist but is broken or cannot be verified.

## Verification

From `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-spawn`:

```text
uv run --frozen python -m pytest tests/test_workflow_scheduler.py tests/test_bg_jobs.py tests/test_wf_run.py tests/test_dynamic_workflows.py -q
153 passed, 1 skipped in 18.75s
```

The committed tests cover explicit disablement (cgroup setup is never called), no delegation (setup skipped, worker launch without cgroup, scheduler 404), and configured delegation with failed setup (provider launch still refuses). Raw pytest output: `final.log`. Imported module path: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-spawn/app/agent_cgroups.py`.

## Mutation proof

Both acceptance tests were committed before mutation. With `_balancer_enabled()` temporarily changed to always return `True`, `test_workflow_balancer_can_be_disabled_without_blocking_workers` failed at the setup stub (`AssertionError: cgroup setup must be skipped`), 1 failed. With the `Delegate=no` early-return condition temporarily disabled, `test_missing_systemd_delegation_skips_setup_but_delegate_failure_stays_required` failed at its setup stub (`AssertionError: setup must be skipped without Delegate=yes`), 1 failed. Restored production code matches the committed version; red outputs are in `mutation-disabled.log` and `mutation-no-delegate.log`.

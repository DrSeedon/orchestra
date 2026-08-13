The policy decisions and compatibility plumbing are otherwise coherent, but the telemetry path lacks the explicitly required timeout boundary. A stalled usage refresh can therefore prevent worker admission instead of failing open.

Review comment:

- [P1] blocking: Bound the telemetry lookup with a timeout — /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-model-gate/app/manager.py:548-548
  When `/api/usage` stalls while refreshing any provider, this await can block worker creation indefinitely rather than fulfilling the required fail-open-on-timeout behavior. `_get_usage_data()` also refreshes unrelated Grok telemetry and provides no overall deadline here, so wrap the policy lookup in a bounded timeout and treat `TimeoutError` through the existing loud fail-open branch.

> ⚠ Codex usage unaccounted: ValueError: Codex completed turn reported zero tokens

## Round (2026-08-13T05:50:24Z)

Re-review status: **FIXED**. Telemetry lookup is bounded at 12 seconds, and `TimeoutError` reaches the existing loud fail-open path.

New findings: None.

Verdict: **APPROVED**

Test: `uv run pytest -q tests/test_worker_model_policy.py::test_balance_telemetry_timeout_is_fail_open_and_loud`

Output: `1 passed in 5.73s`

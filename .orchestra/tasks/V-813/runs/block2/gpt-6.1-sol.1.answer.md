Read-only findings from the current checkout; no files changed.

**1. Call path to durable `WAITING_QUOTA`**

For a new, authenticated MCP delivery:

1. `send_message()` creates/preserves a UUID and posts the message: [app/mcp_stdio.py:1323](/tmp/v813-wt/app/mcp_stdio.py:1323).
2. `_api()` sends HTTP POST: [app/mcp_stdio.py:508](/tmp/v813-wt/app/mcp_stdio.py:508).
3. Routes `send_message()` authenticates, resolves the target, and takes its session lock: [app/routes/sessions.py:857](/tmp/v813-wt/app/routes/sessions.py:857).
4. `_preflight_or_quota_wait()` invokes manager preflight: [app/routes/sessions.py:844](/tmp/v813-wt/app/routes/sessions.py:844).
5. `preflight_message_delivery()` calls `_auto_switch_before_delivery()`, then session admission: [app/manager.py:1067](/tmp/v813-wt/app/manager.py:1067).
6. `preflight_delivery_admission()` calls `_worker_admission()`; running/compacting targets and orchestrator targets bypass this check: [app/session.py:1080](/tmp/v813-wt/app/session.py:1080).
7. `_worker_admission()` calls `get_worker_admission()`: [app/session.py:1058](/tmp/v813-wt/app/session.py:1058).
8. `get_worker_admission()` obtains `current_quota_observation()`, then calls `evaluate_worker_admission()`: [app/quota_gate.py:1089](/tmp/v813-wt/app/quota_gate.py:1089), [app/routes/system.py:1465](/tmp/v813-wt/app/routes/system.py:1465).
9. `evaluate_worker_admission()` returns the decision: [app/quota_gate.py:922](/tmp/v813-wt/app/quota_gate.py:922).
10. `require_worker_admission()` raises `QuotaGateError` for `state == "blocked"`; step 4 catches it and returns `error.decision`: [app/quota_gate.py:1120](/tmp/v813-wt/app/quota_gate.py:1120).
11. Routes pass that decision as `quota_wait` into `accept_message_delivery()`: [app/routes/sessions.py:1052](/tmp/v813-wt/app/routes/sessions.py:1052).
12. `accept_message_delivery()` uses `BEGIN IMMEDIATE`, inserts `state="WAITING_QUOTA"` with `wait_error(quota_wait)`, commits, and suppresses runner wake: [app/message_deliveries.py:288](/tmp/v813-wt/app/message_deliveries.py:288).

**2. Exact opening condition**

For valid telemetry:

```text
gated = lane in policy.gated_lanes and not override_left
hard_stop = policy.hard_stop_pct if override_left else policy.hard_stop_for(lane)
open = utilization < hard_stop and (limit is None or utilization <= limit)
```

`limit=None` when `progress is None` or `not gated`. Unknown/missing/stale telemetry also passes. [app/quota_gate.py:934](/tmp/v813-wt/app/quota_gate.py:934), [app/quota_gate.py:1021](/tmp/v813-wt/app/quota_gate.py:1021).

Claude requires the 10,080-minute weekly window; Codex selects the longest supplied window. `span=window_minutes*60`, `start=reset_at-span`, `progress=min(1,max(0,(now-start)/span))`. [app/quota_gate.py:866](/tmp/v813-wt/app/quota_gate.py:866).

For the ordinary line:

```text
tolerance_pp(progress) =
  policy.tolerance_start_pp +
  (policy.tolerance_end_pp-policy.tolerance_start_pp)*progress
limit = min(policy.hard_stop_for(lane),
            norm*100 + tolerance_pp(line_progress))
```

`norm=line_progress`, or `line_progress**(1/policy.curve_exponent)` for curved lanes. Claude’s legacy `line_progress=progress+policy.claude_weekly_shift_hours*60/10080`; others use `progress`. [app/quota_gate.py:431](/tmp/v813-wt/app/quota_gate.py:431), [app/quota_gate.py:535](/tmp/v813-wt/app/quota_gate.py:535).

Current Claude day/night logic replaces that line:

```text
rise=max(0,policy.hard_stop_for("claude")-policy.tolerance_start_pp)
day_rate=rise*day_weight/weight_total/total_day_hours
night_rate=rise*night_weight/weight_total/total_night_hours
headroom=(100+policy.tolerance_end_pp-policy.tolerance_start_pp)*
         policy.claude_weekly_shift_hours/span_hours
raw=policy.tolerance_start_pp + day_rate*elapsed_day_hours +
    night_rate*elapsed_night_hours + headroom
```

Weights are `1-night_share` and `night_share`, normalized by `weight_total`; absent periods have zero rate. Defaults: Krasnoyarsk day 08:00–24:00, night share `.057`, shift eight hours. The result is capped by the lane stop, then maximized against eligible policy-history lines within this window. [app/quota_gate.py:465](/tmp/v813-wt/app/quota_gate.py:465), [app/quota_gate.py:554](/tmp/v813-wt/app/quota_gate.py:554).

**3. Release and delivery**

Startup launches `quota_release_loop()`: sweep immediately, then sleep 60 seconds **after each sweep**. ETA is descriptive, not a timer. Owner override invokes an immediate sweep. [app/main.py:550](/tmp/v813-wt/app/main.py:550), [app/quota_queue.py:259](/tmp/v813-wt/app/quota_queue.py:259), [app/routes/system.py:1758](/tmp/v813-wt/app/routes/system.py:1758).

`release_waiting()` checks the **current DB model**, releases initial tasks first, skips direct messages while an initial delivery remains open, conditionally updates `WAITING_QUOTA→QUEUED`, and wakes runners. Actual direct-message order is per-target `accept_seq`. [app/quota_queue.py:205](/tmp/v813-wt/app/quota_queue.py:205), [app/message_deliveries.py:803](/tmp/v813-wt/app/message_deliveries.py:803).

Runner → `run_message_delivery()` → manager `send_message_delivery()` → session `send()` → provider send → `SUBMITTED`. Admission is checked again; another quota refusal reparks the row. [app/message_deliveries.py:819](/tmp/v813-wt/app/message_deliveries.py:819), [app/session.py:1533](/tmp/v813-wt/app/session.py:1533).

Successful `change_worker_model` with `changed=True` immediately awaits a sweep using the new model; unchanged/refused changes do not. [app/routes/sessions.py:1824](/tmp/v813-wt/app/routes/sessions.py:1824).

**4. Two edge cases**

- **Late:** an initial task is released, but remains open when direct rows are examined. They are skipped and can wait another sweep after it completes. [app/quota_queue.py:230](/tmp/v813-wt/app/quota_queue.py:230).
- **Never automatically delivered:** task/branch/`needs_switch` changes during the hold. Release succeeds, but the frozen `target_generation` mismatches; delivery becomes `FAILED_BEFORE_SUBMIT` with nonretryable `TARGET_TASK_CHANGED`. [app/manager.py:1047](/tmp/v813-wt/app/manager.py:1047), [app/message_deliveries.py:514](/tmp/v813-wt/app/message_deliveries.py:514).
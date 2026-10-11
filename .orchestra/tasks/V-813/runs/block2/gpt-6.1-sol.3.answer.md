The hold is durable; release depends on a fresh admission check, not the stored ETA. No files were modified.

**1. Call path to `WAITING_QUOTA`**

1. `send_message()` generates/preserves a UUID and POSTs the payload: [app/mcp_stdio.py:1323](/tmp/v813-wt/app/mcp_stdio.py:1323).
2. `_api()` performs the HTTP request: [app/mcp_stdio.py:508](/tmp/v813-wt/app/mcp_stdio.py:508).
3. Routes `send_message()` authenticates the keyed request, resolves the target, and holds its session lock: [app/routes/sessions.py:857](/tmp/v813-wt/app/routes/sessions.py:857), [1045](/tmp/v813-wt/app/routes/sessions.py:1045).
4. `_preflight_or_quota_wait()` calls manager preflight: [app/routes/sessions.py:844](/tmp/v813-wt/app/routes/sessions.py:844).
5. `SessionManager.preflight_message_delivery()` → `AgentSession.preflight_delivery_admission()`: [app/manager.py:1067](/tmp/v813-wt/app/manager.py:1067), [app/session.py:1080](/tmp/v813-wt/app/session.py:1080).
6. `_worker_admission()` → `get_worker_admission()` → `current_quota_observation()` → `evaluate_worker_admission()`: [app/session.py:1058](/tmp/v813-wt/app/session.py:1058), [app/quota_gate.py:1089](/tmp/v813-wt/app/quota_gate.py:1089), [app/routes/system.py:1465](/tmp/v813-wt/app/routes/system.py:1465), [app/quota_gate.py:922](/tmp/v813-wt/app/quota_gate.py:922).
7. `require_worker_admission()` raises `QuotaGateError` only for `decision.state == "blocked"`: [app/quota_gate.py:1120](/tmp/v813-wt/app/quota_gate.py:1120).
8. `_preflight_or_quota_wait()` catches that exception and returns `error.decision`; routes `send_message()` passes it as `quota_wait`: [app/routes/sessions.py:851](/tmp/v813-wt/app/routes/sessions.py:851), [1052](/tmp/v813-wt/app/routes/sessions.py:1052).
9. `accept_message_delivery()` inserts `state="WAITING_QUOTA"` plus `wait_error(quota_wait)` into `message_deliveries`, commits, and suppresses runner wake: [app/message_deliveries.py:238](/tmp/v813-wt/app/message_deliveries.py:238), [321](/tmp/v813-wt/app/message_deliveries.py:321), [346](/tmp/v813-wt/app/message_deliveries.py:346).

Running/compacting targets bypass preflight quota admission ([app/session.py:1098](/tmp/v813-wt/app/session.py:1098)). If admission closes after acceptance, `run_message_delivery()` catches the later rejection and `mark_message_delivery_waiting_quota()` changes `PREPARING → WAITING_QUOTA`: [app/message_deliveries.py:879](/tmp/v813-wt/app/message_deliveries.py:879), [542](/tmp/v813-wt/app/message_deliveries.py:542).

**2. Exact gate condition**

For valid telemetry:

```text
gated = lane in policy.gated_lanes and not override_left
hard_stop = policy.hard_stop_pct if override_left else policy.hard_stop_for(lane)
open = utilization < hard_stop and (limit is None or utilization <= limit)
```

Missing/stale telemetry returns `unknown`, which passes admission. Evidence: [app/quota_gate.py:934](/tmp/v813-wt/app/quota_gate.py:934), [986](/tmp/v813-wt/app/quota_gate.py:986), [1039](/tmp/v813-wt/app/quota_gate.py:1039), [1120](/tmp/v813-wt/app/quota_gate.py:1120).

Claude requires the 10,080-minute weekly window; Codex uses the longest supplied window. `span=window_minutes*60`, `start=reset_at-span`, `progress=min(1,max(0,(now-start)/span))`: [app/quota_gate.py:866](/tmp/v813-wt/app/quota_gate.py:866), [902](/tmp/v813-wt/app/quota_gate.py:902).

Ordinary line:

```text
line_progress = progress + policy.claude_weekly_shift_hours*60/10080  # Claude only
norm = line_progress ** (1/policy.curve_exponent)  # curved lane, positive progress
norm = line_progress                             # otherwise
tolerance_pp(p) = policy.tolerance_start_pp
                  + (policy.tolerance_end_pp-policy.tolerance_start_pp)*p
limit = min(policy.hard_stop_for(lane),
            100*norm + tolerance_pp(line_progress))
```

[app/quota_gate.py:431](/tmp/v813-wt/app/quota_gate.py:431), [535](/tmp/v813-wt/app/quota_gate.py:535).

Claude’s default day/night branch replaces that line. Krasnoyarsk day is 08:00–24:00; night is 00:00–08:00. With `rise=max(0,hard_stop_for("claude")-tolerance_start_pp)`, day/night weights are `1-night_share`/`night_share`, normalized by `weight_total`; each rate divides its weighted rise by its total hours:

```text
raw = policy.tolerance_start_pp
      + day_rate*elapsed_day_hours + night_rate*elapsed_night_hours
      + (100+policy.tolerance_end_pp-policy.tolerance_start_pp)
        *policy.claude_weekly_shift_hours/span_hours
```

Defaults: shift 8 hours, `night_share=.057`. Claude’s final `limit` is the maximum of capped active and eligible historical policy lines: [app/quota_gate.py:191](/tmp/v813-wt/app/quota_gate.py:191), [465](/tmp/v813-wt/app/quota_gate.py:465), [554](/tmp/v813-wt/app/quota_gate.py:554).

**3. Release and delivery**

Startup launches `quota_release_loop()`; it sweeps immediately, then sleeps 60 seconds **after each sweep**. Owner override also calls `release_waiting()` immediately: [app/main.py:550](/tmp/v813-wt/app/main.py:550), [app/quota_queue.py:259](/tmp/v813-wt/app/quota_queue.py:259), [app/routes/system.py:1759](/tmp/v813-wt/app/routes/system.py:1759).

The sweep reads each target’s current DB model, rechecks admission, releases initial tasks first, then eligible direct messages via conditional `WAITING_QUOTA → QUEUED` updates. Direct runners send per-target `accept_seq` order: `run_target_message_deliveries → run_message_delivery → manager.send_message_delivery → session.send`; admission is rechecked, then `DISPATCHING → provider send → SUBMITTED`: [app/quota_queue.py:205](/tmp/v813-wt/app/quota_queue.py:205), [app/message_deliveries.py:803](/tmp/v813-wt/app/message_deliveries.py:803), [993](/tmp/v813-wt/app/message_deliveries.py:993), [app/session.py:1538](/tmp/v813-wt/app/session.py:1538).

After `change_worker_model`, a successful `changed=True` response triggers an immediate global sweep using current DB models; unchanged/refused changes do not: [app/routes/sessions.py:1824](/tmp/v813-wt/app/routes/sessions.py:1824).

**4. Two edge cases**

- **Late:** releasing an initial task still leaves it `QUEUED` during that sweep, so `_has_open_initial()` skips held direct messages. They wait for another sweep: [app/quota_queue.py:195](/tmp/v813-wt/app/quota_queue.py:195), [231](/tmp/v813-wt/app/quota_queue.py:231), [240](/tmp/v813-wt/app/quota_queue.py:240).
- **Never delivered:** task/branch/`needs_switch` changes during the hold invalidate stored `target_generation`. Release succeeds, but delivery raises `TargetTaskChangedError` and becomes `FAILED_BEFORE_SUBMIT`: [app/manager.py:1047](/tmp/v813-wt/app/manager.py:1047), [app/message_deliveries.py:885](/tmp/v813-wt/app/message_deliveries.py:885).
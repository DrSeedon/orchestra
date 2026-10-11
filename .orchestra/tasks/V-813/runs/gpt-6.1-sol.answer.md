Read-only investigation; no files changed.

**1. Call path to the durable hold**

For an idle worker; running/compacting workers bypass new-turn admission ([app/session.py:1098](/tmp/v813-wt/app/session.py:1098)).

1. `send_message` creates/preserves `delivery_id`, posts `/api/sessions/{to}/send` — [app/mcp_stdio.py:1323](/tmp/v813-wt/app/mcp_stdio.py:1323).
2. `_api` performs HTTP POST — [app/mcp_stdio.py:508](/tmp/v813-wt/app/mcp_stdio.py:508).
3. Route `send_message` authenticates keyed ingress, resolves target, takes its session lock — [app/routes/sessions.py:857](/tmp/v813-wt/app/routes/sessions.py:857).
4. `_preflight_or_quota_wait` calls manager preflight — [app/routes/sessions.py:844](/tmp/v813-wt/app/routes/sessions.py:844).
5. `preflight_message_delivery` calls `_auto_switch_before_delivery`, then session admission — [app/manager.py:1067](/tmp/v813-wt/app/manager.py:1067), [app/manager.py:852](/tmp/v813-wt/app/manager.py:852).
6. `preflight_delivery_admission` obtains a decision and checks freshness/model stability — [app/session.py:1080](/tmp/v813-wt/app/session.py:1080).
7. `_worker_admission` — [app/session.py:1058](/tmp/v813-wt/app/session.py:1058).
8. `get_worker_admission` — [app/quota_gate.py:1089](/tmp/v813-wt/app/quota_gate.py:1089).
9. `current_quota_observation` loads/refreshes provider telemetry — [app/routes/system.py:1465](/tmp/v813-wt/app/routes/system.py:1465).
10. `evaluate_worker_admission` computes the decision — [app/quota_gate.py:922](/tmp/v813-wt/app/quota_gate.py:922).
11. `require_worker_admission` raises `QuotaGateError` for `state == "blocked"`; step 4 catches it and returns `error.decision` — [app/quota_gate.py:1120](/tmp/v813-wt/app/quota_gate.py:1120).
12. `accept_message_delivery(..., quota_wait=quota_wait)` uses `BEGIN IMMEDIATE`, inserts `WAITING_QUOTA` with `wait_error(decision)`, commits, and suppresses runner wake — [app/routes/sessions.py:1052](/tmp/v813-wt/app/routes/sessions.py:1052), [app/message_deliveries.py:238](/tmp/v813-wt/app/message_deliveries.py:238), [app/quota_queue.py:45](/tmp/v813-wt/app/quota_queue.py:45).

**2. Exact admission condition**

With valid telemetry:

```python
gated = lane in policy.gated_lanes and not override_left
hard_stop = (policy.hard_stop_pct if override_left
             else policy.hard_stop_for(lane))
open = utilization < hard_stop and (limit is None or utilization <= limit)
```

Missing/stale data produces `unknown`, which passes. Equality blocks at `hard_stop`, but passes at `limit`. [app/quota_gate.py:934](/tmp/v813-wt/app/quota_gate.py:934), [app/quota_gate.py:1039](/tmp/v813-wt/app/quota_gate.py:1039).

Claude requires the 10,080-minute weekly window; Codex selects the longest supplied window. `progress = clamp((checked_at - start)/span, 0, 1)`, where `span=window_minutes*60`, `start=reset_at-span`. [app/quota_gate.py:866](/tmp/v813-wt/app/quota_gate.py:866).

The ordinary line is:

```python
line_progress = progress  # Claude legacy: + shift_hours*60/10080
norm = line_progress ** (1/policy.curve_exponent)  # curved lanes
# otherwise norm = line_progress
tolerance_pp = policy.tolerance_start_pp + (
    policy.tolerance_end_pp-policy.tolerance_start_pp)*line_progress
limit = min(policy.hard_stop_for(lane), norm*100 + tolerance_pp)
```

[app/quota_gate.py:431](/tmp/v813-wt/app/quota_gate.py:431), [app/quota_gate.py:535](/tmp/v813-wt/app/quota_gate.py:535).

Claude’s default day/night branch instead computes:

```python
rise = max(0, policy.hard_stop_for("claude")-policy.tolerance_start_pp)
day_rate = rise*day_weight/weight_total/total_day_hours
night_rate = rise*night_weight/weight_total/total_night_hours
headroom = (100+policy.tolerance_end_pp-policy.tolerance_start_pp
            )*policy.claude_weekly_shift_hours/span_hours
raw = policy.tolerance_start_pp + day_rate*elapsed_day_hours \
      + night_rate*elapsed_night_hours + headroom
```

Zero-length periods get zero weight/rate; `day_weight=1-night_share`, `night_weight=night_share`. Hours use Krasnoyarsk time: day starts at 08:00, night at midnight; default `night_share=.057`, shift=8 hours. The active threshold is `min(hard_stop,raw)`; Claude’s final `limit` is the maximum over active and eligible historical policy lines. [app/quota_gate.py:465](/tmp/v813-wt/app/quota_gate.py:465), [app/quota_gate.py:554](/tmp/v813-wt/app/quota_gate.py:554).

**3. Release and delivery**

Startup launches `quota_release_loop`: sweep immediately, then sleep 60 seconds. Owner override also sweeps immediately. ETA does not schedule delivery. [app/main.py:550](/tmp/v813-wt/app/main.py:550), [app/quota_queue.py:259](/tmp/v813-wt/app/quota_queue.py:259), [app/routes/system.py:1758](/tmp/v813-wt/app/routes/system.py:1758).

`release_waiting` evaluates each target’s **current DB model**, releases initial tasks first, then direct messages without an open initial task. Conditional updates change `WAITING_QUOTA → QUEUED` and wake runners. Actual direct-message order is per-target `accept_seq`, not sweep `created_at`. [app/quota_queue.py:205](/tmp/v813-wt/app/quota_queue.py:205), [app/message_deliveries.py:803](/tmp/v813-wt/app/message_deliveries.py:803).

Runner → `run_message_delivery` → manager `send_message_delivery` → session `send` rechecks admission. A renewed block re-parks the message; otherwise provider send transitions through `DISPATCHING` to `SUBMITTED`. [app/message_deliveries.py:819](/tmp/v813-wt/app/message_deliveries.py:819), [app/session.py:1533](/tmp/v813-wt/app/session.py:1533).

`change_worker_model` → route `change_model` → session `change_model`; successful `changed=True` immediately sweeps all holds using current models. Unchanged/refused changes do not. [app/mcp_stdio.py:2216](/tmp/v813-wt/app/mcp_stdio.py:2216), [app/routes/sessions.py:1824](/tmp/v813-wt/app/routes/sessions.py:1824).

**4. Concrete edge cases**

- **Late:** gate opens while the worker’s initial delivery remains `QUEUED/PREPARING/DISPATCHING`. Direct holds are skipped until a later sweep after that barrier clears. [app/quota_queue.py:195](/tmp/v813-wt/app/quota_queue.py:195), [app/quota_queue.py:240](/tmp/v813-wt/app/quota_queue.py:240).
- **Never automatically delivered:** task/branch/`needs_switch` changes during the hold. Dispatch rejects the captured `target_generation`; runner marks `FAILED_BEFORE_SUBMIT` and notifies the sender, rather than automatically retrying. [app/manager.py:1047](/tmp/v813-wt/app/manager.py:1047), [app/message_deliveries.py:884](/tmp/v813-wt/app/message_deliveries.py:884).
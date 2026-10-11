Read-only inspection; no files changed. This describes the checked-out code.

**1. Call path to the durable row**

1. `send_message()` creates/reuses a delivery UUID and calls POST `/api/sessions/{to}/send` — [app/mcp_stdio.py:1323](/tmp/v813-wt/app/mcp_stdio.py:1323).
2. `_api()` performs that HTTP request — [app/mcp_stdio.py:508](/tmp/v813-wt/app/mcp_stdio.py:508).
3. Route `send_message()` authenticates the sender, resolves the target, and takes its session lock — [app/routes/sessions.py:857](/tmp/v813-wt/app/routes/sessions.py:857).
4. `_preflight_or_quota_wait()` calls preflight and catches `QuotaGateError`, returning `error.decision` — [app/routes/sessions.py:844](/tmp/v813-wt/app/routes/sessions.py:844).
5. `preflight_message_delivery()` hydrates the target, calls `_auto_switch_before_delivery()`, then target preflight — [app/manager.py:1067](/tmp/v813-wt/app/manager.py:1067).
6. `preflight_delivery_admission()` calls `_worker_admission()`; running, compacting, or orchestrator **targets bypass** this check — [app/session.py:1080](/tmp/v813-wt/app/session.py:1080).
7. `_worker_admission()` calls `get_worker_admission()` — [app/session.py:1058](/tmp/v813-wt/app/session.py:1058).
8. `get_worker_admission()` obtains `current_quota_observation()` and calls `evaluate_worker_admission()` — [app/quota_gate.py:1089](/tmp/v813-wt/app/quota_gate.py:1089).
9. Back in preflight, `require_worker_admission()` raises only for `decision.state == "blocked"` — [app/quota_gate.py:1120](/tmp/v813-wt/app/quota_gate.py:1120).
10. After the catch, `accept_message_delivery(quota_wait=decision)` executes `BEGIN IMMEDIATE`, inserts `state="WAITING_QUOTA"` with `wait_error(decision)` metadata, and commits. It does not wake a runner — [app/message_deliveries.py:238](/tmp/v813-wt/app/message_deliveries.py:238), [insertion/commit:320](/tmp/v813-wt/app/message_deliveries.py:320).

**2. Exact opening condition**

For valid telemetry:

```python
utilization < hard_stop and (limit is None or utilization <= limit)
```

Here `gated = lane in policy.gated_lanes and not override_left`; `hard_stop = policy.hard_stop_pct if override_left else policy.hard_stop_for(lane)`. Unknown telemetry permits admission. [app/quota_gate.py:922](/tmp/v813-wt/app/quota_gate.py:922)

Claude requires the 10,080-minute weekly window; Codex selects the longest supplied window. `progress = min(1, max(0, (now-start)/span))`, with `span=window_minutes*60`, `start=reset_at-span`. [app/quota_gate.py:866](/tmp/v813-wt/app/quota_gate.py:866), [902](/tmp/v813-wt/app/quota_gate.py:902)

When gated, `limit=line_limit(...)`. The ordinary line is:

```python
tolerance_pp(p) = policy.tolerance_start_pp + (
    policy.tolerance_end_pp-policy.tolerance_start_pp)*p
limit = min(policy.hard_stop_for(lane), norm*100+tolerance_pp(line_progress))
```

`norm=line_progress`, or `line_progress**(1/policy.curve_exponent)` for curved lanes. Claude’s legacy `line_progress=progress+claude_weekly_shift_hours*60/10080`; others use `progress`. Defaults: tolerance 10→1 pp, Sol exponent 2.5, Sol stop 95%, general stop 99%; environment overrides apply. [app/quota_gate.py:101](/tmp/v813-wt/app/quota_gate.py:101), [431](/tmp/v813-wt/app/quota_gate.py:431), [535](/tmp/v813-wt/app/quota_gate.py:535)

Claude normally uses day/night logic: Krasnoyarsk day 08:00–24:00; `night_share=.057`, shift 8 hours. With `rise=max(0,hard_stop_for("claude")-tolerance_start_pp)`, weights `day_weight=1-night_share`, `night_weight=night_share` for existing periods:

```python
day_rate = rise*day_weight/weight_total/total_day_hours
night_rate = rise*night_weight/weight_total/total_night_hours
headroom = (100+tolerance_end_pp-tolerance_start_pp)*claude_weekly_shift_hours/span_hours
raw = tolerance_start_pp + day_rate*elapsed_day_hours + night_rate*elapsed_night_hours + headroom
```

Absent-period rates are zero. The threshold caps `raw` at Claude’s stop, then takes the maximum with applicable historical policy lines from this weekly window. [app/quota_gate.py:465](/tmp/v813-wt/app/quota_gate.py:465), [554](/tmp/v813-wt/app/quota_gate.py:554)

**3. Release and delivery**

Startup launches `quota_release_loop()`: sweep immediately, then sleep 60 seconds after each sweep. ETA does not schedule delivery. Positive owner override invokes a sweep immediately. [app/main.py:550](/tmp/v813-wt/app/main.py:550), [app/quota_queue.py:259](/tmp/v813-wt/app/quota_queue.py:259), [app/routes/system.py:1758](/tmp/v813-wt/app/routes/system.py:1758)

`release_waiting()` rereads each target’s durable model, caches verdicts per model, releases initial tasks first, and skips direct messages while an initial delivery remains open. It conditionally updates `WAITING_QUOTA→QUEUED`, then wakes runners. [app/quota_queue.py:205](/tmp/v813-wt/app/quota_queue.py:205)

Direct deliveries execute by `accept_seq`: runner → `run_message_delivery()` → manager `send_message_delivery()` → session `send()` → provider send → `SUBMITTED`. A renewed quota refusal reparks them. [app/message_deliveries.py:803](/tmp/v813-wt/app/message_deliveries.py:803), [819](/tmp/v813-wt/app/message_deliveries.py:819), [app/session.py:1533](/tmp/v813-wt/app/session.py:1533)

Successful `change_worker_model` with `changed=True` immediately calls the same global sweep against updated models; unchanged/failed changes do not. [app/routes/sessions.py:1824](/tmp/v813-wt/app/routes/sessions.py:1824)

**4. Two edge cases**

- An earlier `DELIVERY_UNKNOWN` blocks a released message indefinitely pending resolution: it remains nonterminal, and runners stop at a non-`QUEUED`/`PREPARING` head. [app/message_deliveries.py:719](/tmp/v813-wt/app/message_deliveries.py:719), [993](/tmp/v813-wt/app/message_deliveries.py:993).
- Task/branch/`needs_switch` changes while held invalidate `target_generation`; release then fails before submission, requiring explicit retry. [app/manager.py:1047](/tmp/v813-wt/app/manager.py:1047), [app/message_deliveries.py:884](/tmp/v813-wt/app/message_deliveries.py:884).
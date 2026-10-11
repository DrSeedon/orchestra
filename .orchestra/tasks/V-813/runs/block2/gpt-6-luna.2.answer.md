### 1. From `send_message` to the durable row

1. `mcp_stdio.send_message` assigns or validates a `delivery_id`, then POSTs to `/api/sessions/{to}/send`. [`app/mcp_stdio.py:1322-1364`](app/mcp_stdio.py:1322)
2. The keyed send route validates the caller and resolves the target. Under the target’s session lock, it calls `_preflight_or_quota_wait`, then `accept_message_delivery` with the resulting `quota_wait`. [`app/routes/sessions.py:856-872`](app/routes/sessions.py:856), [`app/routes/sessions.py:1045-1070`](app/routes/sessions.py:1045)
3. `_preflight_or_quota_wait` calls `manager.preflight_message_delivery`; it catches `QuotaGateError` and returns its decision instead of rejecting the message. [`app/routes/sessions.py:844-853`](app/routes/sessions.py:844)
4. `preflight_message_delivery` checks the target’s admission; `preflight_delivery_admission` calls `_worker_admission` → `get_worker_admission` → `evaluate_worker_admission` → `require_worker_admission`. A blocked decision raises `QuotaGateError`. [`app/manager.py:1067-1076`](app/manager.py:1067), [`app/session.py:1080-1124`](app/session.py:1080), [`app/quota_gate.py:1089-1123`](app/quota_gate.py:1089)
5. `accept_message_delivery` inserts and commits the durable `message_deliveries` row directly as `WAITING_QUOTA`, with the wait decision in `error_json`. It does not wake the runner for that state. [`app/message_deliveries.py:257-262`](app/message_deliveries.py:257), [`app/message_deliveries.py:319-347`](app/message_deliveries.py:319)

If quota closes after preflight, the runner has a second check: a `QuotaGateError` before provider dispatch changes `PREPARING` to `WAITING_QUOTA`. [`app/message_deliveries.py:874-883`](app/message_deliveries.py:874), [`app/message_deliveries.py:542-554`](app/message_deliveries.py:542)

### 2. Gate condition

`evaluate_worker_admission` blocks when `utilization >= hard_stop`, or when `limit is not None and utilization > limit`; equality with the line is admitted. [`app/quota_gate.py:1039-1059`](app/quota_gate.py:1039)

For Codex, `deciding_window` chooses the longest window (normally weekly); for Claude it requires the exact 10,080-minute weekly window. `progress = clamp((checked_at - (reset_at - window_minutes*60)) / (window_minutes*60), 0, 1)`. [`app/quota_gate.py:866-899`](app/quota_gate.py:866), [`app/quota_gate.py:902-919`](app/quota_gate.py:902)

- **Codex `sol` lane:** `tolerance_pp = tolerance_start_pp + (tolerance_end_pp - tolerance_start_pp) * progress`; `norm = progress ** (1 / curve_exponent)` when the lane is curved; `limit = min(hard_stop_for(lane), norm*100 + tolerance_pp)`. Defaults: tolerance 10→1 pp, exponent 2.5, Sol stop 95%, common hard stop 99%. [`app/quota_gate.py:101-132`](app/quota_gate.py:101), [`app/quota_gate.py:431-440`](app/quota_gate.py:431), [`app/quota_gate.py:535-551`](app/quota_gate.py:535)
- **Claude:** the weekly line uses Krasnoyarsk day/night allocation (default day starts 08:00; 5.7% of quota is allocated to night), plus an 8-hour weekly shift headroom. In code: `raw = tolerance_start_pp + day_rate*elapsed_day_hours + night_rate*elapsed_night_hours + headroom`, capped at `hard_stop_for("claude")`; historical weekly policy lines are also considered by taking their maximum. [`app/quota_gate.py:191-194`](app/quota_gate.py:191), [`app/quota_gate.py:465-502`](app/quota_gate.py:465), [`app/quota_gate.py:571-596`](app/quota_gate.py:571)

### 3. Release and delivery

`quota_release_loop` calls `release_waiting()` every minute. It also runs immediately after a successful gate override and after a successful `change_worker_model`. [`app/main.py:548-551`](app/main.py:548), [`app/quota_queue.py:205-209`](app/quota_queue.py:205), [`app/routes/system.py:1758-1762`](app/routes/system.py:1758), [`app/routes/sessions.py:1824-1834`](app/routes/sessions.py:1824)

The sweep checks each target’s current model; if admission is not `blocked`, it conditionally moves eligible rows to `QUEUED` and wakes that target’s runner. Initial deliveries release first; direct messages wait behind any open initial delivery. [`app/quota_queue.py:127-138`](app/quota_queue.py:127), [`app/quota_queue.py:222-249`](app/quota_queue.py:222)

The runner processes each target in `accept_seq` order. It changes `QUEUED` to `PREPARING`, then dispatches through `manager.send_message_delivery`; a fresh quota refusal returns the row to `WAITING_QUOTA`. [`app/message_deliveries.py:803-817`](app/message_deliveries.py:803), [`app/message_deliveries.py:993-1015`](app/message_deliveries.py:993)

### 4. Edge cases

- **Late:** natural quota opening has no immediate event hook; absent an override or model change, release waits for the next minute sweep. [`app/quota_queue.py:205-209`](app/quota_queue.py:205), [`app/quota_queue.py:259-267`](app/quota_queue.py:259)
- **Never delivered to the accepted task:** if the target’s task generation changes while held, the runner rejects the frozen generation; the receipt becomes terminal `FAILED_BEFORE_SUBMIT` with `TARGET_TASK_CHANGED`. [`app/manager.py:1047-1056`](app/manager.py:1047), [`app/message_deliveries.py:509-539`](app/message_deliveries.py:509)
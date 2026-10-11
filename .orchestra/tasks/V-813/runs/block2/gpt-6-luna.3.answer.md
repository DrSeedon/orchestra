### 1. From `send_message` to durable `WAITING_QUOTA`

1. [`app/mcp_stdio.py:1322-1364`](/tmp/v813-wt/app/mcp_stdio.py:1322) — MCP `send_message` creates or validates a `delivery_id` and POSTs to `/api/sessions/{to}/send`.
2. [`app/routes/sessions.py:856-929`](/tmp/v813-wt/app/routes/sessions.py:856) — the keyed-ingress route authenticates the MCP caller and builds the message provenance.
3. [`app/routes/sessions.py:1045-1070`](/tmp/v813-wt/app/routes/sessions.py:1045) — under the target session lock, it calls `_preflight_or_quota_wait`, then passes the returned decision to `accept_message_delivery`.
4. [`app/routes/sessions.py:844-853`](/tmp/v813-wt/app/routes/sessions.py:844) → [`app/manager.py:1067-1076`](/tmp/v813-wt/app/manager.py:1067) → [`app/session.py:1080-1124`](/tmp/v813-wt/app/session.py:1080) — preflight checks admission for an idle worker’s new turn. A `QuotaGateError` becomes the `quota_wait` decision.
5. [`app/session.py:1058-1065`](/tmp/v813-wt/app/session.py:1058) → [`app/quota_gate.py:1089-1120`](/tmp/v813-wt/app/quota_gate.py:1089) → [`app/quota_gate.py:922-1045`](/tmp/v813-wt/app/quota_gate.py:922) — the session gets the admission decision; `require_worker_admission` raises when it is blocked.
6. [`app/message_deliveries.py:238-260`](/tmp/v813-wt/app/message_deliveries.py:238) and [`app/message_deliveries.py:321-339`](/tmp/v813-wt/app/message_deliveries.py:321) — `accept_message_delivery` commits the receipt and inserts a durable `message_deliveries` row directly as `WAITING_QUOTA`, with the reason and ETA in `error_json`. It does not wake the runner for that state.

If preflight passes but the gate closes before delivery, the runner can also transition `PREPARING → WAITING_QUOTA` via [`app/message_deliveries.py:874-883`](/tmp/v813-wt/app/message_deliveries.py:874).

### 2. Gate condition

Let `progress = clamp((now − (resets_at − window_minutes×60)) / (window_minutes×60), 0, 1)` ([`app/quota_gate.py:902-919`](/tmp/v813-wt/app/quota_gate.py:902)). The tolerance is:

` t = tolerance_start_pp + (tolerance_end_pp − tolerance_start_pp) × progress `

For ordinary lanes, `limit = min(hard_stop_for(lane), norm×100 + t)` ([`app/quota_gate.py:431-434, 535-551`](/tmp/v813-wt/app/quota_gate.py:431)). Codex Sol uses `norm = line_progress ** (1 / curve_exponent)`; other Codex lanes use `norm = line_progress`. Claude shifts `line_progress` by `claude_weekly_shift_hours×60/WEEKLY_WINDOW_MINUTES` ([`app/quota_gate.py:437-440`](/tmp/v813-wt/app/quota_gate.py:437)).

With day/night enabled, Claude instead uses a weekly window weighted by day and night hours: `raw = tolerance_start_pp + day_rate×elapsed_day_hours + night_rate×elapsed_night_hours + headroom`, capped at its hard stop. Defaults are an 8-hour weekly shift, day start at 08:00 Krasnoyarsk time, and a 5.7% night quota share ([`app/quota_gate.py:465-502, 191-193`](/tmp/v813-wt/app/quota_gate.py:465)).

Admission is **blocked** if `utilization >= hard_stop`, or if `limit` exists and `utilization > limit`; equality with the line passes. Otherwise it is available ([`app/quota_gate.py:1039-1071`](/tmp/v813-wt/app/quota_gate.py:1039)).

### 3. Release and delivery

`quota_release_loop` sweeps every 60 seconds ([`app/main.py:548-551`](/tmp/v813-wt/app/main.py:548), [`app/quota_queue.py:259-267`](/tmp/v813-wt/app/quota_queue.py:259)). Successful owner quota override and successful `change_worker_model` each call `release_waiting()` immediately ([`app/routes/system.py:1729-1762`](/tmp/v813-wt/app/routes/system.py:1729), [`app/routes/sessions.py:1802-1834`](/tmp/v813-wt/app/routes/sessions.py:1802)).

A release pass rechecks admission using each target’s **current** model, releases initial deliveries first, then direct messages, and wakes their runners ([`app/quota_queue.py:205-256`](/tmp/v813-wt/app/quota_queue.py:205)). The direct-message runner sends in `accept_seq` order per target ([`app/message_deliveries.py:803-816, 993-1025`](/tmp/v813-wt/app/message_deliveries.py:803)). After `change_worker_model`, the immediate pass releases only what the new model’s gate admits; otherwise the delivery stays waiting.

### 4. Edge cases

- **Late:** the ordinary sweep interval adds up to about 60 seconds before a newly open gate is noticed, plus time for the sweep to check waiting rows ([`app/quota_queue.py:28, 259-267`](/tmp/v813-wt/app/quota_queue.py:28)).
- **Held behind another delivery:** an earlier `DELIVERY_UNKNOWN` remains a deliberate queue barrier; if it is the target’s head, the runner stops and will not reach the released message ([`app/message_deliveries.py:706-718, 993-1024`](/tmp/v813-wt/app/message_deliveries.py:706)). Until that uncertainty is resolved, the held message can remain undelivered.
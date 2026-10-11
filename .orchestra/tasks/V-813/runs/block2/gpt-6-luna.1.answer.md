## 1. From `send_message` to durable `WAITING_QUOTA`

1. [`app/mcp_stdio.py:1322`]( /tmp/v813-wt/app/mcp_stdio.py:1322 ) `send_message` sends a keyed `POST /api/sessions/{to}/send` with a `delivery_id`.
2. [`app/routes/sessions.py:856`]( /tmp/v813-wt/app/routes/sessions.py:856 ) the route validates the request and, for a new target, calls `_preflight_or_quota_wait` under the target session lock at [`1045–1046`]( /tmp/v813-wt/app/routes/sessions.py:1045 ). That calls `manager.preflight_message_delivery`, which reaches `session.preflight_delivery_admission` ([`sessions.py:849–853`]( /tmp/v813-wt/app/routes/sessions.py:849 ), [`manager.py:1067–1076`]( /tmp/v813-wt/app/manager.py:1067 )).
3. The admission path is `preflight_delivery_admission` → `_worker_admission` → `get_worker_admission` → `evaluate_worker_admission` → `require_worker_admission` ([`session.py:1080–1124`]( /tmp/v813-wt/app/session.py:1080 ), [`session.py:1058–1069`]( /tmp/v813-wt/app/session.py:1058 ), [`quota_gate.py:1089–1123`]( /tmp/v813-wt/app/quota_gate.py:1089 )). `_preflight_or_quota_wait` catches `QuotaGateError` and returns its decision instead of rejecting the send.
4. The route passes that decision as `quota_wait` to `accept_message_delivery` ([`sessions.py:1052–1070`]( /tmp/v813-wt/app/routes/sessions.py:1052 )). In one SQLite transaction, [`message_deliveries.py:320–346`]( /tmp/v813-wt/app/message_deliveries.py:320 ) inserts the durable row with `state='WAITING_QUOTA'` and a `wait_error` in `error_json`; it does not wake the target runner ([`347–374`]( /tmp/v813-wt/app/message_deliveries.py:347 )).

There is also a race path: preflight may pass, creating `QUEUED`; if the later send-time gate rejects it, `run_message_delivery` catches `QuotaGateError` and `mark_message_delivery_waiting_quota` changes `PREPARING` to `WAITING_QUOTA` ([`message_deliveries.py:819–880`]( /tmp/v813-wt/app/message_deliveries.py:819 )).

## 2. Gate condition

Let `utilization` be from the deciding window, `progress` be `window_progress`, `gated` indicate whether the lane’s line applies, and `limit` be `line_limit(...)`. The gate blocks exactly when:

`utilization >= hard_stop OR (limit is not None AND utilization > limit)`

So it is open when neither condition holds; equality with `limit` passes. `require_worker_admission` raises only for `state == "blocked"`; unknown quota data is allowed ([`quota_gate.py:1039–1059`]( /tmp/v813-wt/app/quota_gate.py:1039 ), [`1120–1123`]( /tmp/v813-wt/app/quota_gate.py:1120 )).

The deciding window is weekly: Claude requires a 10,080-minute window; Codex uses its longest reported window ([`quota_gate.py:866–899`]( /tmp/v813-wt/app/quota_gate.py:866 )). For Codex’s `sol` lane, the line is `min(hard_stop_for(lane), norm * 100 + tolerance_pp(line_progress))`; `norm = progress ** (1 / CURVE_EXPONENT)` for curved lanes, and `tolerance_pp(p) = tolerance_start_pp + (tolerance_end_pp - tolerance_start_pp) * p` ([`quota_gate.py:431–440`]( /tmp/v813-wt/app/quota_gate.py:431 ), [`535–551`]( /tmp/v813-wt/app/quota_gate.py:535 )). Defaults are tolerance 10→1 pp, exponent 2.5, and `sol` hard stop 95% ([`quota_gate.py:101–132`]( /tmp/v813-wt/app/quota_gate.py:101 )).

Claude’s current line is day/night-based: it divides the increase above `tolerance_start_pp` between day and night hours in Krasnoyarsk, starting day at 08:00, with default `claude_night_quota_share = 0.057`; it adds weekly-shift headroom from `claude_weekly_shift_hours` (default 8 hours) and caps at the lane hard stop ([`quota_gate.py:465–502`]( /tmp/v813-wt/app/quota_gate.py:465 )). For Claude, `line_limit` also takes the maximum across applicable historical policy lines in that weekly window ([`quota_gate.py:554–595`]( /tmp/v813-wt/app/quota_gate.py:554 )).

## 3. Release and delivery

`quota_release_loop` runs `release_waiting()` every 60 seconds ([`main.py:550–551`]( /tmp/v813-wt/app/main.py:550 ), [`quota_queue.py:259–267`]( /tmp/v813-wt/app/quota_queue.py:259 )). The owner’s quota override also calls it immediately ([`routes/system.py:1758–1762`]( /tmp/v813-wt/app/routes/system.py:1758 )). A successful `change_worker_model` calls it immediately after the model changes ([`routes/sessions.py:1824–1834`]( /tmp/v813-wt/app/routes/sessions.py:1824 )).

The release pass checks initial deliveries first, then direct messages; it skips direct messages while that target has an open initial delivery. It changes eligible rows from `WAITING_QUOTA` to `QUEUED` and wakes their runners ([`quota_queue.py:222–249`]( /tmp/v813-wt/app/quota_queue.py:222 )). The runner processes the first nonterminal delivery by `accept_seq`, preserving target order ([`message_deliveries.py:803–816`]( /tmp/v813-wt/app/message_deliveries.py:803 ), [`993–1025`]( /tmp/v813-wt/app/message_deliveries.py:993 )). It prepares the row, then calls `manager.send_message_delivery` and `session.send` ([`message_deliveries.py:834–853`]( /tmp/v813-wt/app/message_deliveries.py:834 ), [`manager.py:1043–1065`]( /tmp/v813-wt/app/manager.py:1043 )).

## 4. Two delay or non-delivery cases

- **Late:** the 60-second sweep means a newly open gate may wait nearly a minute for release; direct messages can wait longer while an initial delivery remains open ([`quota_queue.py:28`]( /tmp/v813-wt/app/quota_queue.py:28 ), [`259–267`]( /tmp/v813-wt/app/quota_queue.py:259 ), [`195–202`]( /tmp/v813-wt/app/quota_queue.py:195 ), [`240–242`]( /tmp/v813-wt/app/quota_queue.py:240 )).
- **Never delivered automatically:** if an earlier delivery to the same target is `DELIVERY_UNKNOWN`, it remains the queue head. The runner stops on that non-queued head, so a released message behind it waits until the earlier outcome is resolved ([`message_deliveries.py:700–717`]( /tmp/v813-wt/app/message_deliveries.py:700 ), [`993–1014`]( /tmp/v813-wt/app/message_deliveries.py:993 )).
## 1. Send path to durable `WAITING_QUOTA`

1. MCP `send_message` posts to `/api/sessions/{to}/send` with a stable `delivery_id` — [app/mcp_stdio.py:1322–1364](/tmp/v813-wt/app/mcp_stdio.py:1322).
2. The route authenticates and resolves the target, takes its session lock, then calls `_preflight_or_quota_wait` — [app/routes/sessions.py:856–929](/tmp/v813-wt/app/routes/sessions.py:856), [app/routes/sessions.py:1045–1070](/tmp/v813-wt/app/routes/sessions.py:1045).
3. `_preflight_or_quota_wait` calls `manager.preflight_message_delivery`; the manager calls `session.preflight_delivery_admission` — [app/routes/sessions.py:844–853](/tmp/v813-wt/app/routes/sessions.py:844), [app/manager.py:1067–1076](/tmp/v813-wt/app/manager.py:1067).
4. For an idle, non-orchestrator target, `preflight_delivery_admission` gets an admission decision and calls `require_worker_admission`. A blocked decision raises `QuotaGateError`, which the route helper catches and returns as `quota_wait` — [app/session.py:1080–1124](/tmp/v813-wt/app/session.py:1080), [app/quota_gate.py:1120–1123](/tmp/v813-wt/app/quota_gate.py:1120).
5. `accept_message_delivery` inserts the row and `wait_error(quota_wait)` in one SQLite transaction, with `state='WAITING_QUOTA'`. It does not wake the target runner while quota is closed — [app/message_deliveries.py:257–262](/tmp/v813-wt/app/message_deliveries.py:257), [app/message_deliveries.py:319–347](/tmp/v813-wt/app/message_deliveries.py:319).

If the gate closes after preflight, the runner catches a pre-submit `QuotaGateError` and `mark_message_delivery_waiting_quota` transitions `PREPARING → WAITING_QUOTA` — [app/message_deliveries.py:819–895](/tmp/v813-wt/app/message_deliveries.py:819).

## 2. Gate condition

`require_worker_admission` raises only when `decision.state == "blocked"`; the decision is blocked iff:

`utilization >= hard_stop OR (limit is not None AND utilization > limit)` — [app/quota_gate.py:1039–1059](/tmp/v813-wt/app/quota_gate.py:1039), [app/quota_gate.py:1120–1123](/tmp/v813-wt/app/quota_gate.py:1120).

For the normal line, `tolerance_pp(progress) = tolerance_start_pp + (tolerance_end_pp - tolerance_start_pp) * progress`. The line is `min(hard_stop_for(lane), norm * 100 + tolerance_pp(line_progress))`; for curved lanes, `norm = line_progress ** (1 / curve_exponent)` — [app/quota_gate.py:431–440](/tmp/v813-wt/app/quota_gate.py:431), [app/quota_gate.py:535–551](/tmp/v813-wt/app/quota_gate.py:535). Defaults are 10→1 percentage points, hard stop 99%, and Codex `sol` hard stop 95% with exponent 2.5 — [app/quota_gate.py:101–132](/tmp/v813-wt/app/quota_gate.py:101).

Claude uses its 10,080-minute weekly window. Its usual weekly shift is 8 hours; with day/night enabled (`claude_night_quota_share`), the line instead allocates the rise above `tolerance_start_pp` by local day/night hours and night share, then adds `headroom = (100 + tolerance_end_pp - tolerance_start_pp) * claude_weekly_shift_hours / span_hours`. Historical Claude line limits can raise the active line via a maximum — [app/quota_gate.py:893–897](/tmp/v813-wt/app/quota_gate.py:893), [app/quota_gate.py:465–502](/tmp/v813-wt/app/quota_gate.py:465), [app/quota_gate.py:575–596](/tmp/v813-wt/app/quota_gate.py:575). A gate override disables the lane gate; the shared hard stop still applies — [app/quota_gate.py:932–939](/tmp/v813-wt/app/quota_gate.py:932).

## 3. Release and delivery

`quota_release_loop` runs at startup and sweeps every 60 seconds. `release_waiting` checks initial deliveries first, releases eligible rows to `QUEUED`, and starts their runners; then it checks direct messages and starts each target’s runner — [app/main.py:548–551](/tmp/v813-wt/app/main.py:548), [app/quota_queue.py:205–256](/tmp/v813-wt/app/quota_queue.py:205).

A successful `change_worker_model` API call invokes `release_waiting()` immediately. The recheck uses the target’s **current** model; if its gate remains blocked, the message stays held — [app/routes/sessions.py:1802–1834](/tmp/v813-wt/app/routes/sessions.py:1802). The MCP tool itself only calls that endpoint and returns its result — [app/mcp_stdio.py:2215–2236](/tmp/v813-wt/app/mcp_stdio.py:2215).

Direct messages are dispatched in per-target `accept_seq` order; the runner prepares and sends the queue head, preserving order — [app/message_deliveries.py:803–816](/tmp/v813-wt/app/message_deliveries.py:803), [app/message_deliveries.py:993–1025](/tmp/v813-wt/app/message_deliveries.py:993).

## 4. Edge cases

- **Delayed:** absent an immediate trigger, release waits for the next 60-second sweep — [app/quota_queue.py:28–31](/tmp/v813-wt/app/quota_queue.py:28), [app/quota_queue.py:259–267](/tmp/v813-wt/app/quota_queue.py:259).
- **Held indefinitely behind another delivery:** a preceding `DELIVERY_UNKNOWN` is intentionally nonterminal. It remains the queue head; `ensure_target_runner` starts only for `QUEUED`/`PREPARING`, so a released quota message behind it cannot run until that uncertainty is resolved or recovery settles it — [app/message_deliveries.py:706–720](/tmp/v813-wt/app/message_deliveries.py:706), [app/message_deliveries.py:803–816](/tmp/v813-wt/app/message_deliveries.py:803), [app/message_deliveries.py:1017–1025](/tmp/v813-wt/app/message_deliveries.py:1017).
## Background jobs & delivery queues

`bg_create` schemas document job types (`run`, timers, watchers, cron); keep these platform mechanics in mind:
- **Self-contained `message`**: write why the wakeup exists so a future compacted session understands the action immediately.
- **No retry timers for `WAITING_QUOTA`**: messages or spawns held by the quota gate sit in a durable FIFO queue that drains automatically across restarts. Use `list_pending_deliveries` to inspect or `cancel_message_delivery` to withdraw; repeat ambiguous calls with the same `delivery_id` for idempotency.
- **Cancel obsolete recurring jobs**: call `bg_cancel` as soon as a recurring job's purpose ends.
- **No worker watchdogs**: Orchestra emits one durable `[auto-report]` if a worker turn ends without `send_message` (crash, interrupt or restart). Treat `[auto-report]` as turn-end notice and inspect actual worktree/evidence state.

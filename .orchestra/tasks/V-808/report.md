# V-808 — Validate spawn delivery IDs before creating sessions

## Change

`spawn_worker` now trims the optional `delivery_id`, preserves the empty-value behavior by generating a UUID, and validates a supplied non-empty value before making the `/api/sessions` request. Invalid input returns `invalid_argument` with `delivery_id must be a UUID`. Its tool description states that `delivery_id` is a UUID.

The HTTP `/api/sessions` request model validates `initial_delivery_id` before the route calls `manager.create_session`. Thus an invalid ID cannot create a session or reach the later `record_spawn_intent` task-retry binding. Empty IDs remain accepted by HTTP as before.

## Verification

`uv run --frozen python -m pytest tests/test_spawn_resume_695.py tests/test_initial_deliveries.py -q` → **31 passed in 5.63s**. The tests cover MCP rejection before any API call, HTTP rejection without calling session creation or persisting a session, and valid UUID paths through both HTTP creation and the existing MCP spawn/delivery flow. The valid HTTP case also confirms that its spawn intent records the given UUID. The imported package is `app` from this worktree's `app/` directory.

No provider calls or service restarts were made. Python files under `app/` changed; Orchestra needs an owner initiated restart after merge for the running process to load them.

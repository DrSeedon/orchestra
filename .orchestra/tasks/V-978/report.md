# V-978 — Preserve OpenRouter per-turn cost across backend recreation

## Evidence and cause

The task's read-only live evidence identifies `turn_usage` row 28119 (`2026-10-19T10:50:19Z`, scope `/home/kesha/openrouter-lab`, model `deepseek/deepseek-v4.1-flash-1017`) with `billing_mode=openrouter_credit`, `cost_usd=0.0`, and `cost_unaccounted=0`. Its eight `source_records_json` usage records each report positive `usage.cost`; their sum is $0.04504706316. The accompanying session baseline is the same $0.04504706316. No historical row was changed.

The code path explains the zero: `HarnessBackend` adds request-level costs into a backend-lifetime accumulator starting at 0; `turn_end` emitted that sum as if it were a session-cumulative amount. After rehydration, `AgentSession` restores `provider_cost_baseline_usd` into `CostTracker._last_cost`; `apply_turn_result` subtracts it, so the backend's fresh $0.04504706316 total becomes a $0.00 turn delta. Recreating the backend for later turns repeats the mismatch. OpenRouter `usage.cost` is request-level evidence, not a cumulative session total, so it must be summed within the turn and emitted as a delta.

The orchestrator also reports an independent V-12 acceptance check of the same row in commit `8ca0c5a`, with A6 failing and the same eight-cost sum. That commit and `.orchestra/tasks/V-12/acceptance-plan.md` are not available in this checkout: [commit lookup](v12-commit-lookup.stdout) reports an invalid object and [main-path lookup](v12-main-path-lookup.stdout) reports the path absent. I record this as an attributed confirmation, not a locally inspected artifact.

## Fix

`HarnessBackend` now resets `_turn_cost_usd` at each `events()` start and accumulates the provider's cost for that turn's individual requests. Both success and error terminal events mark `cost_is_delta=true`; successful complete paid turns carry their exact request-cost sum, while a missing round cost or paid failure remains `cost_usd=NULL, cost_unaccounted=1`. `CostTracker` therefore adds the known sum once without subtracting the restored native cumulative baseline. Delta handling clears `_last_cost` to zero, so normal session persistence records no cumulative provider amount for this request-delta runtime; the existing atomic provider-baseline update remains for runtimes that emit session-cumulative values. No catalog price or missing amount is inferred.

## Verification

- `uv run --frozen python -m pytest tests/test_openrouter_usage.py -q`: 17 passed. Captured stdout: [restart-cost-regressions.stdout](restart-cost-regressions.stdout).
- `uv run --frozen python -m pytest tests/test_openrouter_usage.py tests/test_turn_usage.py tests/test_backend_harness_turn_usage_422.py tests/test_harness_production.py tests/test_p4_cost.py tests/test_cache_tokens.py tests/test_claude_api_credits.py tests/test_owner_mode.py tests/test_usage_history_resolution.py tests/test_routes_surface.py tests/test_catalog_migration_v621.py tests/test_message_provenance_migration_433.py tests/test_owned_dirs_migration_473.py tests/test_review_receipt_migration_436.py tests/test_startup_migration_v576.py tests/test_task_migration.py -q`: 191 passed. Captured stdout: [required-suites.stdout](required-suites.stdout).
- Imported `app`: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-harness-usage/app/__init__.py`. Captured output: [imported-app.stdout](imported-app.stdout).
- `test_recreated_harness_backend_persists_request_cost_delta_once` seeds a rehydrated session with the same $0.04504706316 prior baseline as the new eight-round request-cost sum, persists that turn sum exactly once, rehydrates again with a fresh backend, then persists a $0.01 next turn exactly once. Missing-cost and failure cases remain covered by the OpenRouter usage regressions.

Tests used isolated SQLite files. No live database, historical row, `.env`, paid API, or service was changed; restart/deployment remains for the owner-authorized post-merge procedure.

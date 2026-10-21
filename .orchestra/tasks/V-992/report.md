# V-992: Codex cache shown as non-expiring

Basis: Codex product lead's statement of 21.10.2026 (addendum in V-988 report): for logged-in Codex users the prompt cache is kept indefinitely. A public statement, not documentation. Our Codex runs only through app-server with ChatGPT login, so no API-key distinction was added.

## Change
`ProviderMetadata.cache_persistent` (default False) in `app/models.py`; codex: `cache_persistent=True`, `cache_ttl_seconds=0`, `approximate=False`. `cache_policy_for_runtime` and `provider_metadata_payload` expose it. Claude, Grok, harness, unknown unchanged.

## Consumers of the TTL (all found by `rg cache_ttl|cache_policy`)
- `app/manager.py:2250`, `app/routes/system.py:2675` — spread the policy into session/orchestrator rows → new key reaches the UI automatically.
- `app/mcp_stdio.py:_cache_pill` (list_agents `cache_status`): persistent → `🔥 hot` while running, `♾ cached` when idle after a turn, empty if no turn.
- `app/static/js/app.js:_cachePill`: persistent → `♾` pill (tier `persistent`), `🔥` running; never cold/unknown, no countdown.
- `app/usage_analytics.py:_cache_ttl_case`: persistent providers get an unreachable threshold (`_NEVER_COLD_SECONDS`), so cold_starts = 0 from elapsed time alone; policy and new key carried into the aggregate providers block.
- `app/static/js/analytics.js`: TTL label `∞` for persistent (two places).
- Untouched: compaction / worker-kill / cost (do not use the TTL, per V-988).

## Checks
`uv run --frozen python -m pytest tests/test_backend_routing.py tests/test_usage_analytics.py tests/test_api.py tests/test_manager.py tests/test_backend_grok.py tests/test_mcp_stdio.py tests/test_usage_analytics_frontend.py tests/test_frontend.py -k "cache or ttl or provider or analytics" -n 2` — 69 passed. New tests: `test_cache_pill_persistent_cache_is_never_cold` (also Claude still 🧊 cold), `test_persistent_cache_pill_never_goes_cold` (browser), and analytics test now expects Codex 0 cold starts with a 92-min gap while Claude still 1. Mutation: flipping codex `cache_persistent` to False reddens 3 tests (analytics ×2, policy).

Restart: needed (Python: models, mcp_stdio, usage_analytics). JS is hot; MCP processes need reconnect for the new `cache_status`.
Limit: the statement is not in OpenAI docs; effect of cache writes on quota is unpublished.

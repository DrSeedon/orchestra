# V-979 — OpenRouter cache warmth UI

The Info panel now requests `/api/usage/turns` for the selected Orchestra session. The optional `session_id` filter is scoped together with the already-authorized project scope; it limits the rows to successful Harness turns billed through OpenRouter (paid or free). The UI requests one row, which is therefore the latest successful OpenRouter turn for that session. The route also exposes whether the current OpenRouter provider order is configured so the UI can avoid implying sticky routing applies when a provider pin is active.

Measured cache share uses `cache_read_tokens / (input_tokens + cache_read_tokens)`. This matches Harness accounting: `input_tokens` contains only fresh prompt tokens, and cached prompt tokens are a subset of the provider's prompt total. The cost is unknown whenever `cost_unaccounted` is true or `cost_usd` is null. Provider/model are taken from the latest request source record, with the turn/session model as fallback.

The UI labels the ≤10 minute sticky-routing boundary, the empirically observed 10–30 minute cache behavior and the unknown state beyond 30 minutes. Each description states that these are not provider TTL guarantees. If provider order pinning is configured, the status is `provider-pin` regardless of elapsed time; the measured turn details remain visible, but no warm state is inferred from sticky-routing boundaries.

Checks: `uv run --frozen python -m pytest tests/test_openrouter_usage.py tests/test_usage_history_frontend.py -q` passed (31 tests). The API test verifies exact session isolation, ignores a newer failed turn, selects the latest successful record, and returns the pin flag. The frontend classification test verifies the 10/30 minute boundaries, the unknown state and pin precedence. `uv run --frozen python scripts/check_instruction_contract.py` passed. An initial test run caught a local-variable shadowing regression in the MCP auth path; renaming the local to `caller_session_id` restored the existing contract, and the full targeted set passed on rerun. No paid probes or routing changes were made.

The test environment imported `app` from `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-cache-warmth/app/__init__.py`.

The API filter is a Python change and needs an Orchestra restart after merge before the endpoint change is live.

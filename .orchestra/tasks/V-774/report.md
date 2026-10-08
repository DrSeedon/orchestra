# V-774: Claude API-credit fallback

## Billing route verified before implementation

The owner checked the linked Anthropic Console organization after a Sonnet 5.5 API-key call: the call reported about $0.288, while Console showed **Organization credits $199.72** and **Spend this month $0.29**. The organization has no other balance. This confirmed that the API key routes to the expiring Max 20x promotional credits, so implementation proceeded.

The first live Agent SDK check used the bundled CLI and returned `unrecognized_model` for Haiku. The configured worker CLI was then used instead (`/usr/bin/claude`, version `2.1.293`), matching `shutil.which('claude')` in workers. Two successful Sonnet 5.5 requests reported costs of $0.0191111 and $0.0215609. Their usage showed prompt caching working: first request cache creation 7,581 tokens and cache read 0; second request cache creation 388 and cache read 7,229. The earlier bundled-CLI probe reported $0.004424. These three costs total $0.045096.

## Implementation

`app/claude_api_credits.py` estimates the balance from the Console reading and recorded `turn_usage` costs for `billing_mode='api_credit'`. The baseline is $199.674904 at 2026-10-08 09:23:30 UTC: the Console's displayed $199.72 minus the three SDK-reported probe costs above. Console rounds its displayed balance to cents, so this is an estimate, not an exact ledger. Outside API use after that reading is not visible to Orchestra and can make the estimate too high. Any unpriced or unaccounted API-credit turn fails closed and disables further fallback. The owner-provided expiry is 2026-11-04 00:00 UTC; the fallback also fails closed after expiry or a provider credit-balance rejection.

Anthropic's [billing guidance](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage) directs customers to Console Billing for balance and credit usage. The official [Admin API documentation](https://platform.claude.com/docs/en/api/beta/organization/usage_report/retrieve_messages) documents usage reports (token usage by time bucket); I found no balance-reading endpoint in those billing and Admin API pages. Therefore this implementation uses Orchestra's local spend estimate instead of requiring an Admin API credential.

When subscription quota blocks a Claude worker, `app/quota_gate.py` changes its admission route to `api_credit` only while the feature flag, key, estimated balance, usage ledger, and expiry all permit it. Orchestrators remain on subscription. The API key is read only while constructing an API-credit Claude CLI child environment; subscription and orchestrator child environments explicitly clear both key variables. When the route returns to subscription or is blocked, the session disconnects any API-credit backend before continuing or waiting.

If the provider rejects an API-credit request for depleted balance, the failure latches the route unavailable and parks an already submitted delivery in `WAITING_QUOTA`, preserving normal queue ordering and retry behavior when the subscription gate opens. The dashboard's usage API exposes credit status only in owner mode. The displayed balance is the local estimate, tracked spend since baseline, estimate basis, and expiry. `CLAUDE_API_CREDIT_FALLBACK_ENABLED=0` disables the feature; the setting is re-read from `.env` so the owner can turn it off without restarting.

The live Agent SDK requests confirmed prompt-cache creation and cache reads on this API route.

## Verification

- After merging `main`, the `app/routes/system.py` conflict was resolved by keeping V-779's executor-backed analytics calculation and appending V-774's owner-only `claude_api_credits` field to its payload.
- `uv run --frozen python -m pytest tests/test_claude_api_credits.py tests/test_backend_claude.py tests/test_session.py tests/test_turn_usage.py tests/test_quota_gate.py tests/test_quota_wait_queue.py tests/test_quota_map_api.py tests/test_usage_analytics.py tests/test_usage_analytics_frontend.py tests/test_initial_deliveries.py tests/test_message_delivery_receipts_380.py tests/test_initial_delivery_review_regressions.py tests/test_message_delivery_failure_notices_741.py tests/test_db.py -q`: **623 passed in 32.15s** (`.orchestra/tasks/V-774/post-merge-tests.log`).
- `uv run --frozen python -m compileall -q app tests`, `node --check app/static/js/analytics.js`, and `git diff --check`: passed.
- Earlier failed and timed-out diagnostic logs remain in the task directory; the final post-merge run is green.

Python changes require an owner-initiated Orchestra restart to take effect. No restart was performed. Dashboard JavaScript and CSS are hot-loaded.

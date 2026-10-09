# V-800 — Claude API credits only for selected workflow tasks

## Result

Removed the automatic Claude API-credit fallback from session workers and orchestrators. Session admission now reflects the subscription quota only; session backend construction no longer accepts a billing route, and the Claude session backend always clears both `ANTHROPIC_API_KEY` and `ORCHESTRA_CLAUDE_CREDIT_API_KEY` for its CLI. Post-submit credit parking and session-side exhaustion handling were removed. The quota-map reports subscription admission independently of the API-credit balance.

`wf_run` now accepts `billing="api_credit"` on an `agent()` call, and dynamic-workflow task objects accept `billing: "api_credit"` (a stage may set the default for its tasks). The default remains `subscription`. Credit mode requires Claude model candidates and checks `credit_status()` before dispatch; unavailable, exhausted, unknown, and expired balances produce a completed task record with the reason and no subscription fallback. The adapter checks again immediately before launching the Claude CLI. It reads `ORCHESTRA_CLAUDE_CREDIT_API_KEY`, places the corresponding `ANTHROPIC_API_KEY` only in that selected Claude CLI's environment, and clears both key names from subscription Claude and Codex CLI environments. Workflow usage records retain `billing_mode` in `turn_usage`, so the existing balance estimate continues subtracting credit-routed workflow spend. If the provider reports an empty credit balance during a selected workflow task, the ledger is marked exhausted.

The dashboard now describes the balance as available for selected workflow tasks, rather than as a worker fallback. The example configuration documents `ORCHESTRA_CLAUDE_CREDIT_API_KEY`. The obsolete `CLAUDE_API_CREDIT_FALLBACK_ENABLED` variable is no longer read by source code; the laptop `.env` was not read or changed.

## Verification

No paid provider calls were made. Tests use isolated SQLite databases, fake credit status, and fake provider subprocesses.

Command from the worktree root:

```text
uv run --frozen python -m pytest tests/test_claude_api_credits.py tests/test_wf_run.py tests/test_dynamic_workflows.py tests/test_quota_gate.py tests/test_usage_readiness.py tests/test_quota_wait_queue.py tests/test_session.py tests/test_initial_deliveries.py tests/test_usage_analytics_frontend.py::test_overview_shows_estimated_claude_api_credit_balance_and_expiry -q
471 passed in 21.28s
```

Raw output: `final-tests.log`. The imported adapter path is `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-spawn/scripts/wf_adapters.py`.

## Mutation proof

Mutation proof against the already committed tests:

- Temporarily restored automatic Claude-credit admission for a blocked session; `test_session_admission_never_switches_to_api_credits` failed (`blocked` expected, `available` returned). Output: `mutation-session.log`.
- Temporarily forced the selected task's adapter billing mode to `subscription`; `test_api_credit_route_is_explicit_and_subscription_is_the_default` failed on the expected `api_credit` route. Output: `mutation-selection.log`.
- Temporarily bypassed the workflow credit availability check; `test_unavailable_credits_refuse_task_without_subscription_fallback` failed for both `expired` and `exhausted` because the fake provider ran and returned a value. Output: `mutation-unavailable.log`.

All source mutations were restored to the committed implementation before finalization.

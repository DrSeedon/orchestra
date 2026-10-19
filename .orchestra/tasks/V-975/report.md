# V-975 — OpenRouter usage and billing evidence

## Confirmed behavior

The four supplied bug reports identify missing billing classification, per-request provider metadata, and timing/reasoning persistence. Report 1's claim that Orchestra priced OpenRouter requests from the model catalog is not supported by the current path: `AgentLoop` retains each final event's full `usage` in `round_usages`; `HarnessBackend.events()` passes every round to `_accumulate`; `_accumulate` adds `usage.cost` when present. The aggregate comparison `$0.6859` against catalog reconstructions does not establish a discrepancy without the original per-request API records and applicable rates. No historical price was recalculated.

The other reported gaps reproduce from code. OpenRouter usage lacked provider and request metadata in `turn_end`; the terminal event omitted timing and reasoning fields; paid exact routes emitted the default `subscription` billing mode; and a paid response without `usage.cost` left the previous cumulative numeric value in the event without `cost_unaccounted`, so persistence could store a numeric zero. OpenRouter's usage response and generation records expose fields such as cost, provider name, request ID and token details when present ([OpenRouter generation record API](https://openrouter.ai/docs/api/api-reference/generations/get-generation)).

## Change

Each completed OpenRouter call now attaches a source record to its usage entry. The record retains the complete API `usage` object, endpoint URL, top-level response metadata, selected tracing/timing headers, and client-measured request duration. `HarnessBackend` keeps one record per round, sums measured API durations across completed rounds, sums reasoning-token counts only when every round reports them (otherwise the aggregate remains `NULL`), and measures turn wall time separately. Provider and request IDs stay per-round, so a tool turn may retain different providers without attributing all calls to the last one. No value is synthesized for an absent provider field, request identifier, duration, or reasoning count.

Paid routes listed in `PAID_HARNESS_ROUTES` use `billing_mode=openrouter_credit`; exact `:free` routes use `free`. A paid turn with any missing round cost, no usage record, or a failed request is persisted as `cost_usd=NULL, cost_unaccounted=1`. A free route remains a known zero under the existing exact `:free` zero-spend contract. `CostTracker` advances the known cumulative baseline on an unaccounted OpenRouter turn without adding an incomplete amount to session totals. A later reported round cost is added only to its own subsequent turn; the missing amount is neither presumed to be billed later nor reconstructed. If a session ends after a missing-cost turn, it remains unknown.

Added nullable-compatible `source_records_json` storage through the existing startup migration and `/api/usage/turns?scope=<project>` for project-scoped inspection. The endpoint requires a nonempty scope. A validated dashboard cookie can read a selected project only in owner mode; a shared internal token must also carry a valid MCP proof and session ID, and the requested scope must match that session's stored scope. The shared dashboard login and internal-token bypass authenticate the installation, not a project identity, so either credential alone would let callers supply another project's scope. Mismatched MCP scope returns 404. The query uses an exact bound scope predicate. This follows `/api/usage/history`'s owner-only dashboard behavior and the session APIs' required-scope and MCP-proof contract. Existing rows receive an empty source-record array; historical costs and timing values are not recalculated or rewritten.

The persisted endpoint is normalized from the configured base URL to scheme, host, path, and `/chat/completions`; userinfo, query, and fragment are removed before storage. The outgoing request still uses the configured URL. A regression with `https://user:secret@router.example:8443/custom/v1?api_key=private#fragment` confirms the source record contains only `https://router.example:8443/custom/v1/chat/completions`.

## Verification

- Focused harness, cost tracking, turn usage and migration command: 231 passed. Captured stdout: [focused-tests.stdout](focused-tests.stdout).
- OpenRouter regression module after restoring the mutation: 9 passed. Captured stdout: [post-mutation-tests.stdout](post-mutation-tests.stdout).
- Scope/auth regression, existing usage-history and route-surface checks: 39 passed. Captured stdout: [scope-access.stdout](scope-access.stdout).
- OpenRouter source-record suite after endpoint sanitization: 16 passed. Captured stdout: [endpoint-sanitization.stdout](endpoint-sanitization.stdout).
- Mutation: temporarily removed the missing-paid-round flagging in `_accumulate`; committed test `test_free_missing_cost_is_known_zero_but_paid_missing_cost_is_unknown` failed because the paid event exposed `0.0` rather than `None`. Captured stdout: [mutation.stdout](mutation.stdout).
- Imported `app`: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-harness-usage/app/__init__.py`. Captured output: [imported-app.stdout](imported-app.stdout).

All database tests used temporary SQLite files. No live database, `.env`, paid API, service process, or historical turn row was changed.

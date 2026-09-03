# #239 — nullable cost in usage analytics

## Response contract

- Every period/day/provider/model/agent aggregate exposes `priced_turns` and
  `unaccounted_turns`. The distinction is derived with `COUNT(cost_usd)`, not
  `SUM(cost_usd)`: a measured `0.0` is priced, SQL `NULL` is not.
- `cost_usd` is the observed subtotal when at least one priced turn exists. It is
  `null` when the group contains turns but none have a price. Therefore a mixed
  group remains useful without pretending the subtotal covers every turn.
- Agent `cost_per_turn` keeps its old all-turn meaning and becomes `null` for a
  partial group. The new `cost_per_priced_turn` divides only by `priced_turns`;
  the dashboard names that denominator explicitly and anomaly detection uses it.
- Linked-task cost is unavailable when any linked turn is unpriced. The response
  exposes `fully_costed_linked_tasks`, `linked_priced_turns`, and
  `linked_unaccounted_turns` instead of publishing a partial price as exact.

## Other nullable-to-zero seams

The targeted audit covered Python and JavaScript cost aggregation/rendering.
Remaining `COALESCE(SUM(cost_usd), 0)` calls in `usage_analytics.py` aggregate
`sessions.cost_usd` (the explicitly excluded lifetime/session total) or
`voice_costs.cost_usd` (non-null input), not nullable `turn_usage.cost_usd`.
The session-cost rendering in `app/static/js/app.js` belongs to the same excluded
numeric session total. The analytics chart now passes unknown daily values as
`null` instead of plotting them at zero.

## Verification

The pre-fix oracle failed with `observed_cost_usd = 0.0` and missing
`priced_turns`. After the fix, backend analytics passed 20 tests, frontend
analytics passed 17, and the four #226 producer/persistence oracles passed.
Mutation `COUNT(cost_usd) -> COUNT(*)` failed
`test_analytics_preserves_unknown_cost_in_every_rollup`; after rollback,
`touch`, and marker count `0`, the same test passed.

Codex review took two substantive rounds. Round 1 had no blockers and two
suggestions; both were applied. Round 2 reran the mixed-cost oracle plus the
frontend suite (`18 passed in 17.99s`), reported no new findings, and returned
`APPROVED`.

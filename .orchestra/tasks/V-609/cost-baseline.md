# V-609 — persistent provider cost baseline

## Decision

The provider result remains authoritative: Claude's `total_cost_usd` is cumulative
for the native session, and the per-turn price is its delta from the previous result.
`turn_usage.cost_usd` remains the local per-turn price. Reconstructing a baseline from
`turn_usage` is not reliable because that table intentionally stores only the delta and
does not retain the raw provider total.

The baseline is stored as `sessions.provider_cost_baseline_usd` next to `sessions.session_id`.
`SessionManager` restores it to `_last_cost`, and `_to_db_dict()` persists it. Terminal
usage insertion can also receive the raw native id and provider total; `turn_usage_add`
updates both baseline columns in the same SQLite transaction as the terminal usage row.
The native-id predicate rejects delayed writes from an older native session.

Schema version 2 adds the column with `REAL DEFAULT 0.0`. Existing databases require the
explicit offline migration `scripts/migrate_provider_cost_baseline_v609.py`; no historical
`turn_usage` or session rows are rewritten.

## Boundary cases

- Same native id after a process restart: restored baseline makes the first result
  `provider_total - baseline`, so it records the current turn only.
- Compact or fresh runtime/model switch: the new native id resets `_last_cost`; fresh
  switches persist an empty native id and zero baseline. In-place model switches retain
  both because the provider session is unchanged.
- Loss of the final `turn_usage` projection after the terminal transaction: the durable
  baseline still advances, so the next result cannot charge the old cumulative total a
  second time. A crash before that transaction commits is inherently indistinguishable
  from a provider result that was never recorded; that remaining window is documented.
- Parallel turns are excluded by `AgentSession._lifecycle_lock`; the SQL guard also prevents
  a delayed old event from overwriting a newer native id.

## Verification

With `/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python`, the required
affected suites plus `tests/test_session.py` passed: **350 passed**. `app` imported from
`/home/kesha/orchestra/worktrees/home-kesha-orchestra/cost-baseline/app/__init__.py`.
`compileall` and a dry-run/apply migration smoke test passed.

Mutation checks against committed tests:

1. Replacing manager baseline restoration with zero made the restart test fail (`0.17`
   charged instead of `0.02`).
2. Disabling the atomic baseline update made the atomic test fail (`0.15` persisted
   instead of `0.17`).
3. Removing native-session baseline reset made the session-id-change test fail (`0.20`
   total instead of `0.25`).

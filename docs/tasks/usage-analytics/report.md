# Usage Analytics v2 — implementation report

## Outcome

The accepted control-room artifact is implemented as a wide, responsive Usage Analytics modal backed by one coherent analytics snapshot. Claude and Codex have equal capacity visibility, provider-aware cache semantics, shared spend/efficiency views, agent drill-down, and an operational reliability view.

The production service was not restarted.

## Tickets

- **T1 — done:** Claude uses a 3600-second cache TTL; Codex uses an explicitly approximate 1800-second TTL. The legacy daily response remains additive and compatible.
- **T2 — done:** `GET /api/usage/analytics?days=N` returns capacity and all database aggregates from one explicit SQLite read transaction.
- **T3 — done:** the narrow modal was replaced with a `min(1600px, 96vw)` control room and a dedicated leaf module. The modal uses one request per period and remains usable at `390x844`.
- **T4 — done:** Overview, Agents, Efficiency, and Reliability views share one loaded snapshot; agent filters and drill-down do not refetch.
- **T5 — done:** normalized per-turn telemetry is stored idempotently by provider event ID. Event-time runtime, model, scope, and task linkage remain stable when a session changes later.
- **T6 — done:** explicit Claude and Codex tool failures are correlated by provider tool-use ID and stored idempotently.

## Main files

- `app/usage_analytics.py` — provider-aware aggregations, one observed-turn source, retention/coverage, tasks, models, agents, and reliability.
- `app/routes/system.py` — unified endpoint and independent Claude/Codex capacity fallback.
- `app/db.py` — migration-safe `turn_usage`, tool-error identity, and terminal-log event identity.
- `app/session.py`, `app/session_turns.py`, `app/backend_claude.py`, `app/backend_codex.py` — non-blocking normalized telemetry collection.
- `app/static/js/analytics.js`, `app/static/css/style.css`, `app/templates/dashboard.html` — control-room UI and responsive shell.
- `tests/test_usage_analytics.py`, `tests/test_usage_analytics_frontend.py`, `tests/test_turn_usage.py` — SQL contracts, rollout coverage, frontend behavior, and responsive checks.

## Correctness safeguards

- Matching structured events and legacy terminal logs are counted once; structured-only `max_turns` segments are not lost.
- Provider/model attribution comes from event-time telemetry, not mutable session state.
- Task cost is hidden when a task predates the structured collector; the UI reports partial coverage instead of publishing a low exact-looking KPI.
- Telemetry writes run through the dedicated DB executor and cannot abort a healthy model turn.
- Out-of-order period responses cannot overwrite the active analytics snapshot.
- Missing Claude capacity does not hide valid Codex capacity, or vice versa.

## Verification

- Focused aggregation/database/session suite: `180 passed`.
- Related analytics/provider/session/frontend suite: `167 passed`.
- Final analytics backend + Playwright suite: `21 passed`.
- Final complete suite: `847 passed, 20 skipped in 82.40s`.
- `git diff --check $(git merge-base main HEAD)..HEAD`: clean.
- Isolated visual checks: desktop `1600x1000` and mobile `390x844`; no document overflow or JavaScript errors.
- Codex implementation review: Round 3 **APPROVED** after all original findings and the rollout task-cost P2 were fixed. See `codex-review-impl.md`.

## Compatibility and rollout

- Existing usage endpoints remain available; the daily response only gains optional provider detail.
- Database changes are additive and migration-safe.
- The new Python endpoint and migrations become active only after a user-authorized Orchestra restart.
- Exact per-turn/model/cache history starts at collector rollout; older history remains explicitly partial and is never fabricated.

## Breaking changes

None.

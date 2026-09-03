# Usage Analytics v2 — implementation plan

Approved reference: `docs/artifacts/usage-analytics-v2.html`. Research: `docs/tasks/usage-analytics/research.md`.

## Outcome

Replace the narrow cost modal with a nearly-fullscreen Orchestra observability control room. The frontend makes one analytics request per selected period; the response contains one coherent snapshot of capacity, provider spend/cache, agent/model mix, task coverage and reliability rollups. Claude and Codex remain independent subscription pools and `$` remains explicitly virtual API-equivalent cost.

## Architecture

- Add `app/usage_analytics.py` as the read-only aggregation layer. SQL and metric semantics live there, not in rendering code.
- Run every multi-query aggregate inside one explicit read transaction on one connection, so summary and breakdown observe the same WAL snapshot.
- Keep `/api/usage`, `/api/usage/history`, `/api/usage/daily` and `/api/usage/daily/agents` compatible.
- Add `GET /api/usage/analytics?days=N` as the single modal payload. The route combines current capacity data with one SQLite analytics snapshot.
- Move the legacy modal code out of `app/static/js/app.js` into a dedicated `app/static/js/analytics.js`; load it before `app.js`, like `usage.js`.
- Add analytics-specific CSS to `app/static/css/style.css`; keep the accepted industrial control-room visual language.
- Add new collection only after the useful UI ships: structured per-turn usage rows and explicit tool-failure callers. Historical values are never guessed or backfilled.

## Response contract

The unified endpoint returns:

```text
generated_at
period: days, observed_from, observed_to, complete
capacity: anthropic, codex, orchestra, voice_cost_usd
summary: observed_cost_usd, agent_turns, completed_tasks,
         linked_completed_tasks, cost_per_linked_task, lifetime totals
providers: Claude/Codex totals + cache comparable/cold/hit_pct
daily: provider cost/turn/cache series
agents: model/provider/turns/cost/cost_per_turn/last_turn/anomaly
models: provider/turns/cost/share
reliability: subagents, tool_errors, voice, task_linkage, telemetry coverage
```

`period.complete=false` when retained turn telemetry begins after the requested range. Capacity is global even when a dashboard project is selected; the modal is fleet observability, not a misleading mixture of scoped stats and global spend.

## Tickets

### T1 — Fix provider-aware cache TTL in the existing daily slice

- Status: done
- Files: `app/usage_analytics.py` (new), `app/routes/system.py`, `tests/test_usage_analytics.py` (new)
- Change:
  - Extract daily cost/cache aggregation into a testable data-layer function.
  - Classify runtime from `sessions.backend_type`, with `gpt-*` fallback for legacy rows.
  - Apply `cache_policy_for_runtime()`: Claude `3600s`, Codex `1800s` approximate.
  - Preserve existing top-level `/api/usage/daily` fields; add per-provider daily details without breaking current consumers.
- AC:
  - A 31-minute gap is warm for Claude and cold for Codex.
  - A 61-minute gap is cold for both.
  - First observed turn for a session is excluded from comparable/hit/cold counts.
  - Aggregate hit rate is computed from all provider-aware comparable turns, not an average of percentages.
  - Existing `day` (`str`), `turns` (`int`), `cost_usd` (`float`), `cold_starts` (`int`) and `cache_hit_pct` (`int|null`) keys and types remain unchanged.
  - Provider details are an additive optional field; days without provider data return an empty provider object.
  - A regression test asserts the complete legacy field set and types, not only the new provider-aware path.
  - Tests create a temporary SQLite DB and fail against the old hardcoded-3600 SQL.
- blocked-by: none

### T2 — Ship one coherent analytics snapshot endpoint

- Status: done
- Files: `app/usage_analytics.py`, `app/routes/system.py`, `tests/test_usage_analytics.py`, `tests/test_codex_usage.py`
- Change:
  - Add the aggregate contract above and `GET /api/usage/analytics?days=N`.
  - Reuse current Claude/Codex capacity retrieval server-side; the browser does not call four endpoints.
  - Aggregate provider/daily/model/agent rankings, median-based cost/turn anomaly, retention, task linkage coverage, native subagents, voice and tool-error state from one DB snapshot.
  - Start an explicit SQLite read transaction before the first aggregate query and commit/close only after the payload is complete.
  - Return `collector_ready=false` for tool errors until T6; zero rows are not rendered as zero operational errors.
- AC:
  - One endpoint response contains all fields required by the accepted artifact.
  - `days` is clamped to `1..9999`; SQL parameters remain bound.
  - Provider totals exactly equal the sum of daily provider rows for the requested retained period.
  - Model and agent cost shares are based on the same observed turn set.
  - Cost/task is `null` when no completed linked tasks exist or a linked task predates structured collection; the response includes linkage and exact-observation coverage.
  - `period.complete` and `observed_from` expose retained-log truncation.
  - Missing Claude or Codex capacity fails soft per provider and does not break database analytics.
  - Invalid optional analytics rows fail soft and are reported through coverage; opening the DB or executing required SQL fails loudly with a logged 5xx.
  - Existing usage endpoints keep their response contracts.
- blocked-by: T1

### T3 — Replace the narrow modal with the capacity-first control room

- Status: done
- Files: `app/templates/dashboard.html`, `app/static/css/style.css`, `app/static/js/analytics.js` (new), `app/static/js/app.js`, `tests/test_usage_analytics_frontend.py` (new), `tests/test_frontend.py`
- Change:
  - Replace `max-w-3xl` shell with `min(1600px, 96vw)` / `92vh` desktop layout and responsive mobile shell.
  - Remove the legacy analytics renderer from `app.js`; expose the same global `openAnalyticsModal()` / `closeAnalyticsModal()` entry points from `analytics.js`.
  - Render period controls, equal Claude/Codex/Spark capacity cards, routing signal, provider-filterable spend chart, KPI rail and retention/virtual-cost labels from one endpoint call.
- AC:
  - Opening or changing period makes exactly one `/api/usage/analytics` call and no `/api/stats`, `/api/usage/daily`, `/api/usage/daily/agents` or `/api/usage` calls from modal code.
  - Desktop shell is wider than the old `max-w-3xl` modal and does not exceed the viewport.
  - At `390x844`, the document has no horizontal overflow; modal content remains scrollable and controls remain reachable.
  - Claude and Codex capacity cards have equal visual weight; absent provider windows are omitted rather than fabricated.
  - Today/7d/30d/all controls update all overview values from the returned snapshot.
  - Loading, empty, partial-retention and provider-fetch-failure states render without JS errors.
  - Escape, backdrop click and close button destroy Chart.js instances/listeners.
- blocked-by: T2

### T4 — Add agent drill-down, efficiency and reliability views

- Status: done
- Files: `app/static/js/analytics.js`, `app/static/css/style.css`, `tests/test_usage_analytics_frontend.py`
- Change:
  - Add Agents, Efficiency and Reliability tabs from the approved artifact.
  - Add provider/anomaly filters and agent drill-down.
  - Add provider-aware cache comparison, model mix, native subagent/voice/task coverage and data-collection gaps.
  - Reuse the already loaded endpoint payload; tab switches do not fetch.
- AC:
  - Agent table filters All/Claude/Codex/Anomalies and drill-down shows model, provider, turns, virtual cost, cost/turn and last turn.
  - Anomaly means `cost_per_turn >= 4 × median` with at least two turns; UI calls it a signal, not a verdict.
  - Cache cards display provider TTL semantics and comparable-turn denominator.
  - Model/provider percentages sum to 100% within rounding tolerance.
  - Reliability never reports `0 tool errors` while `collector_ready=false`.
  - Task cost always displays linkage coverage; native subagents are labelled Claude-only.
  - Tabs perform zero additional network requests.
- blocked-by: T3

### T5 — Start structured per-turn usage collection

- Status: done
- Files: `app/db.py`, `app/session_turns.py`, `tests/test_turn_usage.py` (new), `app/usage_analytics.py`
- Change:
  - Add a `turn_usage` table and migration-safe CRUD for session, timestamp, runtime, model, success/stop reason, virtual turn cost, input/output/cache-read/cache-create tokens.
  - Carry the providers' durable event identity into `turn_end`: Claude `ResultMessage.uuid`, Codex `turn.id`.
  - Persist one row from `TurnManager.handle_turn_end()` after `CostTracker.apply_turn_result()` so Claude cumulative cost and Codex delta cost both become one normalized turn row.
  - Enforce `UNIQUE(event_id)` in SQLite and write atomically with `INSERT OR IGNORE`; no in-memory deduplication or preflight `SELECT`.
  - Expose structured-telemetry coverage in analytics; do not backfill or replace retained log totals until coverage is complete.
- AC:
  - One terminal `turn_end` produces one row with current runtime/model and per-turn normalized cost/tokens.
  - Repeated delivery of the same Claude UUID or Codex turn ID, including after reconnect, leaves exactly one row.
  - A terminal event without a provider event ID is not persisted as structured telemetry and is surfaced as unknown coverage; no random ID weakens durable idempotency.
  - Claude cumulative SDK cost is stored as the calculated delta; Codex delta metadata is stored unchanged.
  - Migration preserves existing databases.
  - Analytics reports collected row count and collection start; historical missing rows remain explicitly unknown.
- blocked-by: T4

### T6 — Collect real tool failures from both runtimes

- Status: done
- Files: `app/backend_claude.py`, `app/backend_codex.py`, `app/session.py`, `app/db.py`, `app/usage_analytics.py`, `tests/test_backend_claude.py`, `tests/test_backend_codex.py`, `tests/test_usage_analytics.py`
- Change:
  - Preserve tool name/use id and explicit failure metadata on Claude tool-result blocks and Codex MCP/command/dynamic-tool results.
  - Correlate results to the originating `tool_use` by stable provider tool-use ID; keep the source tool name recorded at start.
  - Extend tool-error storage with stable `tool_use_id`/runtime identity and atomic deduplication; call `tool_error_add()` only for explicit tool failures. Model/rate-limit errors remain separate.
  - Switch analytics `collector_ready` to true and aggregate ranked tool failures.
- AC:
  - Claude `ToolResultBlock(is_error=True)` records one failure with the originating tool name.
  - Codex MCP error, failed dynamic tool and non-zero command exit record failures with stable tool names.
  - Successful tool results never create rows.
  - Duplicate lifecycle notifications for one tool use create at most one row.
  - Deduplication uses provider tool-use ID, never timestamp/input text; historical rows without identity remain `unknown`.
  - Error text is bounded before persistence and rendered escaped.
  - Reliability view shows ranked failures only after collector readiness is true.
- blocked-by: T5

## Verification

After every ticket, run its focused tests. Before review:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q
```

Frontend validation uses isolated Playwright for the worktree assets, including `1600x1000` and `390x844`; it does not depend on restarting the currently running Orchestra service.

Then run Codex review on the complete diff, resolve every blocking finding through fix or debate, rerun tests, write `report.md` and signal-anchored `retro.md` if required.

## Migration and compatibility

- New tables/columns are additive through `init_db()` / `_migrate()`.
- No historical structured telemetry is invented.
- Existing `/api/usage*` consumers remain functional.
- `openAnalyticsModal()` remains the template entry point.
- No server restart or VPS deployment in this task.

## Explicit non-goals

- Real subscription billing: virtual `$` remains API-equivalent only.
- Automatic runtime/model switching from the dashboard.
- A universal anomaly score or automatic agent punishment.
- Backfilling exact cache tax from text logs.
- Comparing Claude native subagents directly to Codex worker sessions before a shared delegation contract exists.

## Codex plan review resolution

- Accepted blocking T5 finding: durable provider event IDs, `UNIQUE(event_id)` and atomic `INSERT OR IGNORE` are now explicit AC, including reconnect/replay tests.
- Accepted snapshot, compatibility, strict-DB-failure and tool-use correlation suggestions.
- Kept T1 as a separate ticket intentionally: the user explicitly required the provider-TTL bug to be independently testable before the unified endpoint. T1 still ships a verifiable API behavior and backward-compatibility test; T2–T4 then form backend and UI vertical slices.

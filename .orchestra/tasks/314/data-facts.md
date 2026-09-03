# #314 live shadow-data facts

Measured before implementation on 2026-08-17 against the read-only live database
`/home/kesha/orchestra/data/orchestra.db` and the live-shaped application path. No
production process, database, or systemd unit was changed.

## Controller telemetry

The database is 481,193,984 bytes. A read-only SQLite catalog query returned no
`quota_controller_*` objects; each of the five #291 controller tables returned
`no such table`. Therefore the old live data cannot answer any of these questions:

- counts of `would_hold`, `would_allow`, or `indeterminate` decisions;
- latest binding constraint or reason;
- whether today's Codex wave would have been held.

The UI must represent this as unavailable shadow telemetry, not as zero decisions
or an inferred allow. Existing live tables contain 321 sessions, 157,884 logs, and
4,442 `turn_usage` rows. The collector timestamps are
`2026-08-03T06:29:02.255305+00:00` for turn usage and tool errors.

## Analytics endpoint diagnosis

Three sequential read-only requests to
`GET http://127.0.0.1:8888/api/usage/analytics?days=7` all returned HTTP 200 with
145,823 bytes and 2,824 agent turns. Elapsed times were 2.612 s, 1.756 s, and
2.199 s. `app/static/js/app.js` applies a 2,000 ms default timeout and retries GETs;
`app/static/js/analytics.js` called `api()` without an override. Thus the endpoint
does return data, while the browser can time out and render `нет данных` for the
same successful response. A 15,000 ms analytics-specific timeout is the conservative
fix for the measured path.

A SQLite `Connection.backup` of the live database, with the application DB path
monkeypatched to that copy, produced `build_usage_analytics(days=7)` with 2,820
agent turns, providers `claude`, `codex`, `grok`, seven daily rows, and
`period_complete=true`. The route returned summary `observed_cost_usd=5564.2739`,
`priced_turns=2809`, `unaccounted_turns=11`. This proves the route/aggregation path
is data-bearing; the defect is client timeout, not an empty source database.

## Release interpretation

Until controller tables are deployed and populated, adaptive enforcement must
fall back to the existing static gate. The analytics response must expose the gap
(`no_shadow_telemetry`) and leave today's Codex-wave classification explicitly
unknown.

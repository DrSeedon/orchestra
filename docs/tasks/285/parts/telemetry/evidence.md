# #285 telemetry evidence slice

All timestamps are UTC. This file contains source rows and measurements only.

## Contour inventory

- Host: `vmi3407579`; contour label: `local VPS checkout`.
- Live SQLite source resolved to `/home/kesha/orchestra/data/orchestra.db` on `ext4` (`310095872` bytes at stat time).
- Frozen backup: SQLite `backup()` from URI `mode=ro`; `PRAGMA quick_check=ok`; SHA-256 `4ecc963b6779402af4f8d08dbdf499ec19dc1adfc780ccb7fb992a7d8b01fed6`.
- `usage_snapshots`: 10219 rows, 2026-07-05T05:19:58.635440+00:00 to 2026-08-16T08:45:35.224799+00:00.
- `turn_usage`: 3451 rows, 2026-08-03T06:33:39.118015+00:00 to 2026-08-16T08:45:22.873498+00:00.

## Quota observations

| source | provider | window | utilization | resets_at | plan | row/time |
|---|---|---|---:|---|---|---|
| frozen SQLite | anthropic | five_hour | 0.0 | None | None | 10219 / 2026-08-16T08:45:35.224799+00:00 |
| frozen SQLite | anthropic | seven_day | 100.0 | 2026-08-18T06:59:59.811436+00:00 | None | 10219 / 2026-08-16T08:45:35.224799+00:00 |
| frozen SQLite | codex | primary | 2.0 | 2026-08-23T07:26:39Z | pro | 10219 / 2026-08-16T08:45:35.224799+00:00 |
| frozen SQLite | codex_spark | primary | 0.0 | 2026-08-23T08:45:34Z | pro | 10219 / 2026-08-16T08:45:35.224799+00:00 |
| frozen SQLite | grok | primary | 79.0 | 2026-08-16T19:51:48.358179Z | None | 9725 / 2026-08-14T15:23:53.726776+00:00 |
| authenticated GET /api/usage | anthropic | five_hour | 0.0 | None | None | response completed 2026-08-16T08:58:33.249016+00:00 |
| authenticated GET /api/usage | anthropic | seven_day | 100.0 | 2026-08-18T06:59:59.683732+00:00 | None | response completed 2026-08-16T08:58:33.249016+00:00 |
| authenticated GET /api/usage | codex | primary | 4 | 2026-08-23T07:26:39Z | pro | response completed 2026-08-16T08:58:33.249016+00:00 |
| authenticated GET /api/usage | codex_spark | primary | 0 | 2026-08-23T08:54:22Z | pro | response completed 2026-08-16T08:58:33.249016+00:00 |

## Claude weekly-all and scoped Fable evidence

- Live `weekly_all`: `{"group": "weekly", "is_active": true, "kind": "weekly_all", "percent": 100, "resets_at": "2026-08-18T06:59:59.683732+00:00", "scope_model_display_name": null, "scope_model_id_is_null": null, "scope_surface": null, "severity": "critical"}`.
- Live `weekly_scoped`: `{"group": "weekly", "is_active": false, "kind": "weekly_scoped", "percent": 0, "resets_at": "2026-08-18T06:59:59.683927+00:00", "scope_model_display_name": "Fable", "scope_model_id_is_null": true, "scope_surface": null, "severity": "normal"}`.
- 2026-08-15 UTC completed Claude Fable rows: 0; Opus rows: 4.
- Persisted normalized `weekly_scoped` observations: 0; recent persisted `weekly_all >=100` intervals: 4.
- Frozen backup running/starting session groups: `[{"active_turn_id_nonempty": 0, "backend_type": "codex", "model": "gpt-5.6-sol", "rows": 8, "status": "running"}]`.
- Turn quota-sample age rows: `[{"age_seconds_max": 299.96296, "age_seconds_median": 150.189951, "age_seconds_min": 0.230783, "age_seconds_p95": 282.066399, "five_hour_pct_nonnull": 2552, "negative_age_rows": 0, "primary_pct_nonnull": 0, "quota_sampled_at_nonnull": 2552, "quota_sampled_at_null": 26, "rows": 2578, "runtime": "claude", "seven_day_pct_nonnull": 2552}, {"age_seconds_max": 298.739391, "age_seconds_median": 151.936181, "age_seconds_min": 1.349949, "age_seconds_p95": 288.717357, "five_hour_pct_nonnull": 0, "negative_age_rows": 0, "primary_pct_nonnull": 754, "quota_sampled_at_nonnull": 754, "quota_sampled_at_null": 119, "rows": 873, "runtime": "codex", "seven_day_pct_nonnull": 0}]`.
- Live endpoint cache TTL in `app/routes/system.py`: 300 seconds; live response exposes `observed_at`: False.
- Persisted utilization precision counts: `{"legacy_columns": {"five_hour_pct": {"fractional": 0, "integer_valued": 9684, "nonnull": 9684, "null": 535, "zero": 2178}, "seven_day_pct": {"fractional": 0, "integer_valued": 9684, "nonnull": 9684, "null": 535, "zero": 188}}, "normalized_provider_windows": {"fractional": 0, "integer_valued": 26885, "observations": 26885, "zero": 3464}}`.
- Sanitized credit states: `{"anthropic_extra_usage": {"is_enabled": false, "monthly_limit_present": true, "monthly_limit_value_omitted": true, "spend_limit_reached": true, "used_credits": 0.0, "utilization": 0.0}, "codex_credits": {"balance_is_null": false, "balance_value_omitted": true, "has_credits": false, "unlimited": false}, "codex_reset_credits": 0}`.

## Codex prolite to pro source rows

First `pro` row after `prolite`: id `10200`, timestamp `2026-08-16T07:15:41.615352+00:00`.

| id | ts | main plan/util/reset | Spark plan/util/reset |
|---:|---|---|---|
| 10197 | 2026-08-16T07:00:36.449813+00:00 | prolite / 97 / 2026-08-20T03:56:54Z | prolite / 9 / 2026-08-20T05:48:52Z |
| 10198 | 2026-08-16T07:05:37.987098+00:00 | prolite / 97 / 2026-08-20T03:56:54Z | prolite / 9 / 2026-08-20T05:48:52Z |
| 10199 | 2026-08-16T07:10:39.764982+00:00 | prolite / 97 / 2026-08-20T03:56:54Z | prolite / 9 / 2026-08-20T05:48:52Z |
| 10200 | 2026-08-16T07:15:41.615352+00:00 | pro / 24 / 2026-08-20T03:56:54Z | pro / 9 / 2026-08-20T05:48:52Z |
| 10201 | 2026-08-16T07:20:43.838690+00:00 | pro / 0 / 2026-08-23T07:20:43Z | pro / 0 / 2026-08-23T07:20:43Z |
| 10202 | 2026-08-16T07:25:45.741752+00:00 | pro / 0 / 2026-08-23T07:25:45Z | pro / 0 / 2026-08-23T07:25:45Z |
| 10203 | 2026-08-16T07:30:47.494296+00:00 | pro / 0 / 2026-08-23T07:26:39Z | pro / 0 / 2026-08-23T07:30:47Z |

## Reset/drop events

Candidate rule: adjacent drop >=20 pp OR canonical reset cycle change. Counts: `[{"drop_gte_20pp": 94, "events": 201, "provider": "anthropic", "reset_cycle_changed": 140, "window_id": "five_hour"}, {"drop_gte_20pp": 10, "events": 12, "provider": "anthropic", "reset_cycle_changed": 6, "window_id": "seven_day"}, {"drop_gte_20pp": 6, "events": 7, "provider": "codex", "reset_cycle_changed": 5, "window_id": "primary"}, {"drop_gte_20pp": 0, "events": 6, "provider": "codex_spark", "reset_cycle_changed": 6, "window_id": "primary"}]`.
Raw source rows for every candidate are in `evidence.json`.

## Threshold intervals

Step convention: observation `i` applies on `[ts_i, ts_(i+1))`; intervals break rather than carry across gaps >900 seconds; no duration is extrapolated after the final observation.

| provider/window | threshold | intervals | observed seconds |
|---|---:|---:|---:|
| anthropic/five_hour | 80 | 34 | 195597.611735 |
| anthropic/five_hour | 90 | 30 | 144751.626263 |
| anthropic/five_hour | 95 | 27 | 125809.493418 |
| anthropic/five_hour | 100 | 26 | 103787.982728 |
| anthropic/seven_day | 80 | 20 | 610010.500115 |
| anthropic/seven_day | 90 | 13 | 456212.012964 |
| anthropic/seven_day | 95 | 13 | 424669.383519 |
| anthropic/seven_day | 100 | 8 | 190644.292006 |
| codex/primary | 80 | 5 | 790850.865686 |
| codex/primary | 90 | 4 | 729270.231764 |
| codex/primary | 95 | 3 | 679099.998668 |
| codex/primary | 100 | 1 | 427999.212782 |

## Turn aggregates

The production predicate is `NOT (scope = '/test' OR session_id LIKE 'test-%')`.

| period | runtime | model | rows | ok | cost USD | input | output | cache read | cache create |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| all frozen | claude | claude-haiku-4-5 | 2 | 2 | 0.157423 | 27 | 658 | 82572 | 72572 |
| all frozen | claude | claude-opus-5[1m] | 2576 | 2503 | 4863.481233 | 4271951 | 21772302 | 7226900634 | 151459356 |
| all frozen | codex | gpt-5.3-codex-spark | 4 | 4 | 0 | 22448134 | 174876 | 21747712 | 0 |
| all frozen | codex | gpt-5.6-luna | 61 | 58 | 4.527579 | 117346305 | 569451 | 110132736 | 0 |
| all frozen | codex | gpt-5.6-sol | 807 | 797 | 1632.036738 | 2195596686 | 7695554 | 2128180736 | 0 |
| all frozen | codex | gpt-5.6-terra | 1 | 1 | 0.375354 | 1012208 | 5311 | 951552 | 0 |
| 2026-08-15 UTC | claude | claude-opus-5[1m] | 4 | 4 | 15.3332 | 346 | 19791 | 7128850 | 1127227 |

## Coverage, cadence, gaps, filtering

- All-snapshot cadence: median 300.673809 s, p95 302.847297 s, max 33052.356865 s; >900 s gaps: 54.
- Test-row filter measurement: `{"excluded_union_rows": 0, "predicate": "scope = '/test' OR session_id LIKE 'test-%'", "retained_rows": 3451, "scope_test_rows": 0, "session_id_test_rows": 0, "total_rows": 3451}`.
- Event-id duplicate measurement: 0 duplicate ids.
- Per-window cadence, largest source-row gaps, NULL/zero counts, all threshold intervals, all reset candidates, and transition-adjacent turn rows are in `evidence.json`.

## Reproduction commands

```bash
python3 - <<'PY'  # WAL-safe backup; exact body is below
import sqlite3
src = sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro', uri=True)
dst = sqlite3.connect('docs/tasks/285/parts/telemetry/.scratch-live.db')
src.backup(dst)
dst.close(); src.close()
PY
python3 docs/tasks/285/parts/telemetry/collect.py --db docs/tasks/285/parts/telemetry/.scratch-live.db --source-path /home/kesha/orchestra/data/orchestra.db --output-json docs/tasks/285/parts/telemetry/evidence.json --output-md docs/tasks/285/parts/telemetry/evidence.md --live-url http://127.0.0.1:8888/api/usage
rm -- docs/tasks/285/parts/telemetry/.scratch-live.db
```

The collector reads the auth token only from `INTERNAL_TOKEN`, sanitizes the live response in memory, omits subscription cost and account/payment fields, and never writes the raw endpoint response.

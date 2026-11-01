# V-1108 report

Chart curve (JS, _qlResetCycles) vs gate (window_progress + line_limit), Sol lane, live usage_snapshots read-only (mode=ro), script reconcile.py:

| snapshot (UTC) | resets_at then | gate progress | gate limit % | chart progress | chart limit % |
|---|---|---|---|---|---|
| 2026-10-23T10:13 | 2026-10-29T18:30:02Z | 0.0936 | 47.92 | 0.0936 | 47.92 |
| 2026-10-24T03:19 | 2026-10-30T17:43:00Z | 0.0571 | 41.31 | 0.0571 | 41.31 |
| 2026-10-24T20:31 | 2026-10-30T17:43:00Z | 0.1596 | 56.56 | 0.1596 | 56.56 |
| 2026-10-25T13:45 | 2026-11-01T06:26:27Z | 0.0436 | 38.17 | 0.0436 | 38.17 |
| 2026-10-26T06:52 | 2026-11-02T06:10:32Z | 0.0041 | 21.07 | 0.0041 | 21.07 |
| 2026-10-27T00:02 | 2026-11-02T06:10:33Z | 0.1063 | 49.84 | 0.1063 | 49.84 |

Screenshot: quota-chart-fixed.png (shot.py; live snapshots 22-27.10; past curves end at ~62% and ~55% at the early resets, not at the ceiling). Limitation: both sides use the current policy (no sol policy change in the range). Tests: tests/test_t344_quota_lines_browser.py + test_quota_reset_restart_1105.py 36 passed; new test fails on the old code.

# V-818 — Codex threshold window boundaries

## Finding

The previous Codex threshold was wrong. The timeline used `current resets_at - 7 days` to infer the prior window start, which ignored the provider's early weekly reset. In read-only `usage_snapshots` data inspected from 2026-09-20 through 2026-10-12 (6,093 Codex weekly samples), utilization fell from 92% at 2026-10-11 03:54:55.247 UTC to 0% at 03:59:56.775 UTC; the reset schedule advanced to 2026-10-18 04:09 UTC. The prior observed Codex period began at the preceding early reset, 2026-10-07 03:31:57.514 UTC.

At the chart's left edge, 2026-10-07 21:05:54 UTC, the actual period had elapsed 18.21% of its 4d 28m duration. The Sol threshold there is approximately 58.96%, not the 82.77% produced by the synthetic Oct 4 start (52.94% elapsed). The nearly straight-looking 83%→95% line therefore was not the tail of the intended early-reset period; it was plotted against the wrong seven-day span.

The browser fetches the existing `/api/usage/history?hours=252&step_minutes=30` read endpoint, caches the result for five minutes, and detects reset boundaries from a contiguous positive-utilization → zero-utilization sample where `resets_at` advances. The API is sampled at 30-minute intervals, so a displayed historical boundary can lag the raw transition by up to roughly one sample interval. Current period end still comes from the live quota map. If no reset is observed for a pool, the chart keeps that pool's scheduled-boundary fallback; otherwise its empty event list hid Claude's line in the first live screenshot.

The gray steady-burn diagonal and its legend key were removed from the quota timeline; the separate window-share chart retains its diagonal. This prevents it from being confused with pool-colored actuals and thresholds.

## Verification

- Browser regression `test_codex_threshold_uses_observed_boundaries_after_early_reset` checks the plotted Codex window starts and ends at observed reset events, and that the left-edge threshold is computed from that span rather than a seven-day subtraction.
- Live data was viewed at `http://127.0.0.1:8888/` through Playwright with the worktree's updated JS/CSS. The screenshot shows the historical threshold near 59%, no steady-burn diagonal on the timeline, and the window-share chart's diagonal intact.
- Screenshot: `quotas-after.png`.
- Follow-up: the same regression verifies every gated pool has a timeline threshold and Claude has both a bright active segment and a dim projected segment. A fresh live screenshot confirms the orange Claude threshold and its right-edge label are restored: `quotas-after-2.png`.

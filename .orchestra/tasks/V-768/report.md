# V-768: monotone Claude quota threshold within a weekly window

## Screenshot and history analysis

The screenshot's time axis is the ±84-hour quota timeline. The relevant saved events are `id=2` (2026-09-29 00:00 UTC, baseline), `id=3` (2026-10-06 04:43 UTC, shifted straight line) and `id=1` (2026-10-07 10:42:41 UTC, day/night line). The Claude weekly reset is Tuesday 07:00 UTC; the active window at the last event started 2026-10-06 07:00 UTC.

| Point | Rule / event | Before (%) | After (%) | Difference |
|---|---|---:|---:|---:|
| 2026-10-06 04:43 UTC | `id=2` baseline → `id=3` +8 h, in the prior week's final 2 h 17 min | 99.000 | 99.000 | 0.000 p.p. |
| 2026-10-06 07:00 UTC | weekly reset; prior window → new window under `id=3` | 99.000 | 14.333 | −84.667 p.p. |
| 2026-10-07 10:42:41 UTC | `id=3` shifted straight line → `id=1` day/night | 29.344 | 29.829 | +0.485 p.p. |
| 90 h into the 2026-10-06 window | `id=1` day/night versus the prior shifted curve continued at the same point | 63.083 | 60.694 | −2.389 p.p. |

The only actual rule transition inside the active week rose at its effective instant. Its new curve later fell below the preceding rule's continuation, which matches the screenshot's lower orange line. The earlier `id=3` transition happened just before the weekly reset; both curves were already capped at 99%, so it did not lower the threshold. The large 84.667 p.p. drop is the weekly reset, where progress starts a new window; it is not a same-window rule change. `id=2` predates the screenshot's 84-hour lookback.

## Change

Claude's effective threshold is now the maximum of the active policy curve and all Claude-gated policy curves recorded from the start of the same weekly window through the evaluated instant. Each constituent curve is nondecreasing, so their maximum cannot decrease; retaining a prior curve also prevents a later rule from moving the threshold below the rule already governing that quota window. The next weekly window starts with only its own history. This intentionally allows an earlier, more restrictive curve to govern until the new curve catches up. Other lanes and periods without a usable weekly start keep their existing calculation.

The gate uses the stored policy history and adds the live policy in case a `.env` edit has been read before the quota-map endpoint has persisted its snapshot. Release-time inversion uses the same envelope. The dashboard applies the same maximum while drawing both the time timeline and current-week chart; it consumes the existing API `rule_history`, whose old rows remain unchanged.

## Verification

Focused gate, API, and browser regression tests passed. The full required suites also passed: `uv run --frozen python -m pytest tests/test_quota_gate.py tests/test_quota_map_api.py tests/test_t344_quota_lines_browser.py -q` → 146 passed in 68.96s (raw output: `pytest.log`). The committed regression history uses the three production policy shapes/timestamps above. At 90 hours, the old rule gives 63.083 p.p. while the day/night curve gives 60.694 p.p.; the gate and graph retain 63.083 p.p. A Claude admission at 62% therefore remains available. Tests sample the whole week and assert the threshold never decreases in both API-backed chart data and the browser's shared line calculation.

No production quota history rows were edited. No restart was performed. The Python gate requires the owner's restart; the dashboard JavaScript is hot-loaded.

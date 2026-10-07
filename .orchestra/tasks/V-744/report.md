# V-744: day/night-shaped Claude weekly line

## Line definition

For the Anthropic weekly window, the base rises from `tolerance_start_pp` (10%) to the Claude hard stop (99%). The policy's `claude_night_quota_share=0.057` assigns 5.7% of that rise to local 00:00–08:00 hours and the remaining 94.3% to 08:00–24:00 hours. `claude_day_start_hour=8` identifies the boundary. Rates are derived from actual window duration and the daytime/nighttime hours inside that window; they are not fixed to a 168-hour window. The window start's `Asia/Krasnoyarsk` local time determines which intervals accrue at each rate.

The existing eight-hour headroom is added as a constant `old_line_slope × 8 / window_hours`, which is `91 × 8 / 168 = 4.333333…` p.p. for the current week. Clock phases are evaluated from the unshifted window start. The result is capped at the same Claude hard stop of 99%. Other lanes and calls without a lane retain their prior formula. `line_release_progress` now bisects the same shaped line using the same window start and length, so `opens_in` counts correctly across day/night transitions.

The full `QuotaPolicy` snapshot in V-743 history carries the new profile fields. Older snapshots with no `claude_night_quota_share` (or a `null` value) continue to describe the V-732 straight line; current/future segments use the profile from the live rule. On startup the policy change is appended as a new epoch, so historical points keep their previous shape.

## Comparison table

Elapsed hours are measured from Tuesday 06.10.2026 14:00 Krasnoyarsk. “Old” is V-732's straight line `min(99, 10 + 91 × (elapsed + 8) / 168)`; “new” is the integrated day/night line plus the same eight-hour headroom.

| Window day | Krasnoyarsk time | Old V-732 (%) | New day/night (%) |
|---|---:|---:|---:|
| 1 | 14:00 (start) | 14.33 | 14.33 |
| 1 | 00:00 | 19.75 | 21.83 |
| 1 | 08:00 | 24.08 | 22.55 |
| 4 | 14:00 | 53.33 | 52.48 |
| 4 | 00:00 | 58.75 | 59.97 |
| 4 | 08:00 | 63.08 | 60.69 |
| 7 | 14:00 | 92.33 | 90.62 |
| 7 | 00:00 | 97.75 | 98.11 |
| 7 | 08:00 | 99.00 | 98.84 |

The old and new rules meet at the window start, as both receive the same `+4.333` p.p. headroom. The new line rises more on a daytime interval and less overnight; the fixed displacement does not change the phase boundaries.

## Verification

`uv run --frozen python -m pytest tests/test_quota_gate.py tests/test_quota_admission_e2e.py tests/test_quota_wait_queue.py tests/test_quota_map_api.py tests/test_quota_headroom_447.py tests/test_usage_readiness.py -q` → 142 passed.

`uv run --frozen python -m pytest tests/test_t344_quota_lines_browser.py tests/test_audit0901_sysquota.py tests/test_mcp_quota_gate.py tests/test_codex_quota_103.py tests/test_model_gates.py tests/test_turn_ended_no_quota_suffix.py -q` → 60 passed.

The committed tests cover the daytime and nighttime rates, both clock boundaries, eight-hour offset, 99% cap, Sol/no-lane behavior, a 240-hour window using derived rates, and inverse/opens_in across midnight. Mutating the backend to use the straight line failed the rate test (`0.541667` p.p./h instead of `0.749348`); disabling the browser profile produced `19.7933%` instead of `21.8341%` at the tested current-week point. Total: 202 passed.

Imported `app.quota_gate` path: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-ratelimit/app/quota_gate.py`. `git diff --check` passed. The browser suite rewrote `.orchestra/tasks/V-652/quota-timeline.png`; it was restored to its tracked content after testing.

No restart was performed. The Python gate and rule-history startup need the owner's restart; browser JavaScript hot-loads once the rule payload is available.

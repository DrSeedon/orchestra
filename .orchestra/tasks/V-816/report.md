# V-816 — quota chart readability

## Change

The timeline uses the pool colors for both actual usage and the associated thresholds: solid traces show history, Claude thresholds are orange dashes, and Sol thresholds are pink dash-dot lines. The gray even-burn line has a separate dash pattern. Future segments are dimmed after now; duplicate global hard-stop lines are drawn once per policy interval, and the right edge labels the active thresholds and stops. Low-usage labels alternate to the sides and sit above their markers to clear the X axis.

The window-share chart uses short line labels: stop 99%, stop Sol 95%, orchestrator ∞, and threshold Claude/Sol. Full explanations are available from SVG title tooltips. Actual use is next to the pool marker; pace and any applicable limit are on the adjacent line. Chart formulas and returned values are unchanged. Added the Russian translation for the `Claude workers` label so the existing localized quota test remains green.

## Live screenshots

All screenshots were taken with Playwright at `http://127.0.0.1:8888/` using the live quota API. The baseline loaded the deployed assets before editing. After captures routed only `quota-lines.js`, `i18n.js`, and `style.css` from this worktree; page data still came from the live service.

- Before: [quotas-before.png](quotas-before.png)
- First pass: [quotas-after.png](quotas-after.png)
- Owner follow-up: [quotas-after-2.png](quotas-after-2.png)

The final capture rendered one timeline, two charts, three labeled current lane points, six visible threshold segments, four right-edge labels, and four hard-stop policy intervals. Live pool labels are `Sol 9%`, `Luna 9%`, and `Claude workers 91%`; adjacent details show pace, and the lane limits remain plotted separately.

## Verification

`uv run --frozen python -m pytest tests/test_t344_quota_lines_browser.py tests/test_audit0901_sysquota.py -q` — 31 passed. `node --check app/static/js/quota-lines.js`, `node --check app/static/js/i18n.js`, and `git diff --check` passed.

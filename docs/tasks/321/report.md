# #321 — quota runway visual

## Outcome

Replaced the rejected spreadsheet-like controller artifact with a chart-first explanation at
`docs/artifacts/quota-runway-controller.html`.

The artifact separates three truths:

1. live post-restart state: Codex primary 96%, Luna available below 98%, Sol blocked from 95%;
2. the next hot-config layer, which is not implemented by this artifact;
3. the calibrated sliding-window design, which remains indeterminate while `q95(next_turn)` is unknown.

The live snapshot and its source endpoints are preserved in `source.json`. The artifact never
uses the illustrative calibrated curve as live telemetry.

## Visual structure

- large time-to-reset chart with three explanatory scenarios;
- direct 95/98/99 threshold rail;
- separate Luna and Sol lanes;
- visual decomposition of `u_eff + q95 + guard <= 99 - reserve`;
- explicit current / next / calibrated boundary cards.

## Verification

- headless Chromium, light desktop: rendered, non-empty, no console/page errors;
- headless Chromium, dark desktop: rendered, non-empty, no console/page errors;
- headless Chromium, 390 px mobile: rendered with no horizontal overflow;
- all three scenario controls were activated in every viewport;
- JS syntax: `node --check` passed;
- source JSON: `python3 -m json.tool` passed;
- `git diff --check` passed.

Rendered evidence: `/tmp/quota-runway-light.png`, `/tmp/quota-runway-dark.png`,
`/tmp/quota-runway-mobile.png`.

# #321 — quota runway visual

## Outcome

Replaced both rejected static/explainer revisions with an interactive decision map at
`docs/artifacts/quota-runway-controller.html`.

The artifact keeps the live/static and adaptive-preview contracts separate:

1. live post-restart state: Codex primary 96%, Luna available below 98%, Sol blocked from 95%;
2. exact static boundaries at 95% and 98%;
3. a clearly labelled adaptive preview whose q95 inputs remain illustrative until calibration.

The live snapshot and its source endpoints are preserved in `source.json`. The artifact never
uses the illustrative calibrated curve as live telemetry.

## Interactive structure

- percentage slider from 0% to 100%, with a large live value;
- hours-to-reset slider from 0h to 168h, with a large live value;
- two-axis map: X is utilization, Y is remaining runway;
- colored all-model / Luna-only / Codex-primary-hold regions;
- model and current-state points plotted directly on the map;
- switch between adaptive preview and today's exact static thresholds;
- cards and headroom/rate readouts recomputed on every input event.

## Verification

- headless Chromium, light desktop: rendered, non-empty, no console/page errors;
- headless Chromium, dark desktop: rendered, non-empty, no console/page errors;
- headless Chromium, 390 px mobile: rendered with no horizontal overflow;
- slider edges 0/100% and 0/168h were exercised, with exact output values asserted;
- model states were checked at 94%, 96%, 97%, and 99%;
- static mode was checked for exact 95.0%/98.0% boundaries;
- JS syntax: `node --check` passed;
- source JSON: `python3 -m json.tool` passed;
- `git diff --check` passed.

Rendered evidence: `/tmp/quota-runway-light.png`, `/tmp/quota-runway-dark.png`,
`/tmp/quota-runway-mobile.png`.

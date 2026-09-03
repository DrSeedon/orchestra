# Codex review — #239

- Attempt 1: succeeded; substantive review with test evidence and verdict.
- Resume attempt: rejected before launch because PROJECT CONTEXT was incomplete; no reviewer output.

## Round 1

## Summary

Implementation correctly preserves `NULL` versus measured `0.0`, handles mixed groups, names the priced-turn denominator explicitly, and keeps the hot-loaded frontend compatible with the old API shape.

Focused tests passed:

`uv run pytest -q tests/test_usage_analytics.py tests/test_usage_analytics_frontend.py`

`37 passed in 25.38s`

## Findings

**suggestion — app/static/js/analytics.js:463**

The model-mix heading still says “доли virtual cost,” although the values now represent observed priced subtotals and can exclude unaccounted turns. Rename it to something like “доли observed cost” to avoid presenting partial cost coverage as total virtual cost.

**suggestion — tests/test_usage_analytics.py:620**

The mixed priced/unpriced oracle validates only the agent and summary aggregates. Add assertions for the mixed day, nested provider, top-level provider, and model rows. Those are separate aggregation seams, and the existing all-unpriced/zero-only tests would not catch a regression that converts only mixed groups to false zero or miscounts their coverage.

## Verdict

APPROVED — no blocking findings. The suggestions improve labeling accuracy and regression coverage but do not prevent merge.

## Round (2026-08-13T05:52:32Z)

## Round 2

### Re-review status

- FIXED — `app/static/js/analytics.js:463`: model mix now says “доли observed cost.”
- FIXED — `tests/test_usage_analytics.py:625`: mixed groups now verify day, nested provider, top-level provider, and model aggregates.

### New findings

None.

### Verdict

APPROVED.

`uv run pytest -q tests/test_usage_analytics.py::test_cost_average_uses_only_priced_turns_and_marks_partial_group tests/test_usage_analytics_frontend.py`

`18 passed in 17.99s`

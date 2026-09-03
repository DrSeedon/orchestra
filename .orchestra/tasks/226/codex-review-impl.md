## Summary

Terminal `turn_end`, token metadata, and warning events now survive `_codex_cost` failures. Priced-model behavior remains covered and unchanged. However, the accounting consumer still records and displays the failed calculation as a real `$0.00` cost.

Test run: `uv run pytest -q tests/test_backend_codex.py -k 't1_unpriced or t2_unpriced or t3_priced'`
Result: `3 passed, 71 deselected in 4.82s`

## Findings

- **blocking:** `cost = 0.0` — The producer adds `cost_unaccounted`, but the primary consumer in `session_turns.py` does not honor it. `handle_turn_end()` passes `cost_usd=0.0` through `apply_turn_result`, writes that zero to `turn_usage_add`, and emits a terminal status reporting `$0.00 turn`. Thus the persistent accounting record and user-visible turn summary falsely describe paid usage as free, despite the separate warning. The cost/write seam must preserve an explicit unaccounted state rather than committing zero as an accounted value.

## Verdict

CHANGES REQUESTED — one blocking false-zero accounting defect remains. Terminal delivery and token retention are preserved, but the unpriced turn is still persisted and summarized as costing zero.

## Round (2026-08-13T04:28:04Z)

## Summary

The Round 1 blocker is fixed. Unpriced turns now preserve terminal delivery and tokens, emit a warning, persist `cost_usd` as SQL `NULL` with `cost_unaccounted=1`, and avoid a false `$0.00` terminal message. The migration preserves existing rows and recreates the table’s indexes. Priced behavior remains unchanged.

Test run: `uv run pytest -q tests/test_backend_codex.py`
Result: `77 passed in 7.52s`

## Findings

No blocking or suggestion findings.

- **Round 1 blocking — FIXED:** The consumer now propagates the marker and writes `NULL` instead of numeric zero: `None if cost_unaccounted else max(0.0, float(cost_usd or 0)),`
- **New bugs:** None found within the bounded review scope.

## Verdict

APPROVED — no blockers.

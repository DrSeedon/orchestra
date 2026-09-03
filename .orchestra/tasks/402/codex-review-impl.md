<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The batch flow is generally coherent: partitioning, ordering, atomic admission, group claiming, timeout handling, and mirror delivery are implemented consistently.

## Findings

### blocking

- `blocking: app/tg_file_deliveries.py:670-679 — an existing event ID that belongs to a legacy single-file delivery, or to another batch’s child, enters `_retry_failed_batch()`, which finds no rows and raises `RuntimeError`; the route does not catch it, producing a 500 instead of an idempotency conflict → detect any existing row whose `batch_id != batch_id` and return `IDEMPOTENCY_CONFLICT` (409).`

## Verdict

Needs work. No files were edited.

## Round (2026-08-26T09:45:36Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The prior blocking issue is fixed. Root collisions with legacy deliveries or another batch child now return deterministic `IDEMPOTENCY_CONFLICT` 409 responses while preserving principal checks.

## Findings

### blocking

- Prior finding: **FIXED**. `_commit_batch_acceptance` now routes differing existing `batch_id` values through `_same_batch_response`; no new blocker introduced.

### suggestion

- None.

### question

- None.

## Verdict

APPROVED

Exact diff line: `return _same_batch_response(`

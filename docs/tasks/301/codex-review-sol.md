## Summary

The per-poller in-flight guard is correctly implemented: `_pollSchedule` uses the stable `poller:${key}` key, and repeated visibility/online wakeups cannot start a second underlying callback while the first remains pending.

File requests correctly pass `pollKey: 'files'`, and HTTP 5xx responses increment the file poller’s failure count. Exact reviewed line: `const requestKey = \`poller:${key}\`;`

## Findings

### Blocking

1. The file-failure browser oracle does not verify preservation of the existing UI fallback.

   `treeStillPresent: Boolean(document.querySelector('#file-tree'))` only proves that the static container remains in the DOM. It would still pass if `_refreshContainer` erased the existing file entries, replaced them with a broken state, or removed the fallback behavior entirely.

   The test should establish visible file-tree content before the failure, force the failed refresh, and assert that the previous content or exact fallback UI remains visible afterward.

2. The requested timeout path is not tested.

   The oracle only returns HTTP 503. Timeout handling follows a different branch through `AbortSignal.timeout`, retry attempts, and the final catch. A hanging `/api/files` route should verify that:

   - retries eventually terminate;
   - `_pollFailures.get('files')` increases;
   - the actual next scheduled cadence exceeds 10 seconds;
   - existing file-tree content/fallback survives.

3. Backoff scheduling is only tested as a pure calculation, not as coordinator behavior.

   `nextDelay: _pollDelay('files', 10000)` proves the helper computes a larger number, but not that `_pollSchedule` uses that delay after the failed callback. The test could remain green if scheduling were accidentally changed back to the base cadence. Observe or instrument the scheduled timeout/tick and assert the coordinator itself schedules above 10 seconds.

### Suggestion

The scheduler coalescing oracle is non-vacuous and appropriately holds the callback unresolved while dispatching repeated wake events. Consider also asserting that exactly one subsequent scheduled call occurs after releasing it, which would cover failure to resume after coalescing.

## Verdict

**CHANGES REQUIRED**

The production changes appear to address both Luna findings, but the file timeout, fallback preservation, and actual post-failure scheduling guarantees are not yet covered by the required non-vacuous browser oracles.

## Round (2026-08-16T18:50:12Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Re-review status

- Pending scheduler coalescing: **FIXED** in production code, but the claimed post-release “exactly one subsequent call” assertion is absent.
- UI fallback oracle: **STILL BROKEN** — it only asserts `Boolean(document.querySelector('#file-tree'))`, not preservation of `ok.txt`.
- Timeout oracle: **STILL BROKEN** — current artifact tests only HTTP 503.
- Actual scheduled backoff oracle: **STILL BROKEN** — it checks `_pollDelay()` directly, not the captured `setTimeout` delay.

Exact current line: `treeStillPresent: Boolean(document.querySelector('#file-tree')),`

## New findings

The working tree has no uncommitted diff, and `/tmp/301-sol.diff` still contains the prior oracle rather than the fixes described in the caller context. Therefore the claimed new evidence cannot be verified against the supplied artifact.

## Verdict

**CHANGES REQUIRED** — provide the updated diff containing the described timeout, content-preservation, actual scheduling, and post-release scheduler assertions.

## Round (2026-08-16T18:51:03Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Re-review status

- Pending scheduler callback coalescing: **FIXED**.
- Exactly one subsequent call after release: **FIXED**.
- Preserve visible file content across HTTP 503 and timeout: **FIXED**.
- Exercise real timeout/retry path: **FIXED**.
- Verify actual coordinator delay above base cadence: **FIXED**.

Exact current line: `assert "ok.txt" in timeout_state["treeText"]`

## New findings

None.

## Verdict

**APPROVED**

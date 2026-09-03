<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The stale-page path is mostly correct, but the freshness comparison incorrectly uses a global watermark for a session-local mirror.

## Findings

- suggestion: `app/static/js/app.js:2721-2727` — `_storeWatermark()` returns the global maximum log ID, while `mirrorTop` belongs to only the selected session. Activity in another session can make every otherwise-fresh mirror appear stale, causing an unnecessary history request on each open. Track per-session maxima or use a session-scoped freshness marker.

- suggestion: `tests/test_frontend.py:4070-4200` — freshness tests stub `_storeRead`, `_storeWatermark`, and `_storeSessionId`, so they do not exercise actual IndexedDB transactions, missing metadata, concurrent sync, or read failures. Add at least one browser test using the real IndexedDB store.

- suggestion: `tests/test_frontend.py:4110-4150` — the stale fixture has a 160-ID gap, while the intended case is approximately 100 newer rows, and no boundary test covers gaps of 20 versus 21. The threshold behavior is therefore only tested far from its decision boundary.

## Verdict

No blocking findings. Needs the session-scoped watermark fix before merge.

## Round (2026-08-27T09:00:19Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The session-scoped watermark fixes the prior global-watermark bug, and the real IndexedDB test is useful. One regression remains in fresh-store initialization.

## Findings

- suggestion: `app/static/js/app.js:912-923` — missing `watermark` now becomes `undefined` instead of `0`, producing `/api/logs/sync?after_id=undefined` on a fresh database. The failed response disables the store. Preserve the previous fallback with `w.result || 0` (and similarly default `knownSessions`).

- suggestion: `app/static/js/app.js:912-991, 2655-2682` — `_storeSync` reads `sessionWatermarks`, waits for the network, then later writes the stale snapshot. A concurrent `_storePut` can update a session marker that `_storeSync` subsequently overwrites, causing unnecessary history fetches. Merge the latest marker inside the write transaction or otherwise serialize the read-modify-write.

- suggestion: `tests/test_frontend.py:4070-4255` — the new real IndexedDB test validates lookup scoping, but not fresh-database sync defaults or the `_storeSync`/`_storePut` interleaving above. Add coverage for both.

- suggestion: `tests/test_frontend.py:4110-4155` — the stale fixture now has the requested 100 newer IDs, but the `20`/`21` threshold boundary remains untested.

## Verdict

Prior global-watermark finding: fixed. Prior IndexedDB-test and fixture concerns: addressed. Needs work for the fresh-store `undefined` watermark regression; no blocking findings.

## Round (2026-08-27T09:11:49Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Prior findings are addressed: fresh-store defaults are restored, sync writes merge current IndexedDB markers, and the stale fixture uses a 100-row gap. No blocking correctness or concurrency issue found.

## Findings

- suggestion: `app/static/js/app.js:909-1005` — existing schema-epoch-2 databases have mirror rows but no `session_watermarks`. `_storeSync` writes an empty marker map without backfilling it, so each previously cached session incurs one history request after deployment. Add a metadata migration/backfill or explicitly invalidate legacy mirrors once.

- suggestion: `tests/test_frontend.py:4110-4155` — the `20`/`21` threshold boundary is still untested. Add cases proving gap 20 may use the mirror and gap 21 rejects it.

## Verdict

Prior findings: fixed. No blocking findings; mergeable with the migration and boundary-test suggestions.

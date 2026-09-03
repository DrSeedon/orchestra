<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Reviewed `/tmp/codex405.diff` and changed-scope files only. No blocking security, crash, or data-loss issues found.

Relevant check: `3 passed, 92 deselected in 22.44s`; `node --check app/static/js/app.js` passed.

## Findings

### suggestion

- `app/static/js/app.js:4007-4015` — completion switches only the download link to the server URL; image cards keep the revoked object URL in `img.src`, which can leave the preview broken or race with image loading. Retain the image element and update its `src` to `url` before revoking the object URL.

### suggestion

- `app/static/js/app.js:4001, 3877-3879` — clicking `×` during an active upload removes the card but does not cancel or invalidate the XHR. When it completes, it still inserts the server path into the chat input. Track cancellation and abort/ignore completion for removed cards.

### suggestion

- `app/tg_file_deliveries.py:417` — the limit is shared, but the error text still hardcodes `50MB`. Use `MAX_UPLOAD_MB` here too so the message cannot drift if the shared limit changes.

## Verdict

Needs work: 3 suggestions, 0 blocking findings.

## Round (2026-08-27T12:35:50Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Re-review completed. All three prior findings are addressed. Focused checks pass: `4 passed, 92 deselected`; JS syntax check passes.

## Findings

### blocking

- `app/static/js/app.js:3850-3873` — cancelling calls `xhr.abort()`, but the Promise listens only for `load`, `error`, and `timeout`. Real XHR cancellation emits `abort`, so `_uploadToChat()` can remain pending indefinitely and keep `sendChat` waiting. The new test masks this by making its fake `abort()` invoke `error`. Add an `abort` handler and ensure the cancelled path settles.

### suggestion

- `app/static/js/app.js:3926-3929` — paste cards are always named `*.png`, even when compression sends a `*.webp` file. Update the card filename once the actual upload extension is known.

## Verdict

Needs work: 1 blocking finding, 1 suggestion.

## Round (2026-08-27T12:42:03Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Prior blocking and suggestion are fixed:

- Native XHR `abort` now settles the promise.
- Paste cards update to the actual compressed filename.
- Preview URL switching and shared limit formatting remain correct.
- Reported tests pass: frontend 94 passed; upload tests 2 passed.

## Findings

### suggestion

- `app/static/js/app.js:3927-3929` — cancelling a paste card while `_compressScreenshot()` is still running marks the card cancelled, but the later continuation still starts the XHR. Completion is ignored, but bandwidth and server work are still consumed. Add a cancellation check after compression before calling `_uploadToChat()`.

## Verdict

No blocking findings. Approved with one non-blocking suggestion.

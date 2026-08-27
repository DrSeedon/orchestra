<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The removed restart tests cover the obsolete #269/#270 restart-blocking UI. The voice test still checks codec selection, recorder MIME capture, transcription request, cancellation, and stream cleanup, but its synchronization and assertions are weakened.

## Findings

- suggestion: `tests/test_frontend.py:4396-4397` — `page.wait_for_timeout(200)` is a fixed-delay wait and may be flaky under slower CI; wait for a specific transcription completion/state instead.

- suggestion: `tests/test_frontend.py:4413` — removing the chat-input assertion means the test no longer verifies that the transcription response is applied to the UI; a request alone does not prove transcription handling succeeded.

## Verdict

Needs work: address the fixed wait and restore an assertion on the transcription result.

## Round (2026-08-27T07:51:16Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Both prior suggestions are fixed:

- Fixed wait replaced with `expect_response`.
- Transcription handling is verified through HTTP status and JSON response; the removed input assertion is appropriate for current production behavior.

## Findings

No new findings. No blockers remain.

## Verdict

ACK — approved.

`assert response.status == 200`

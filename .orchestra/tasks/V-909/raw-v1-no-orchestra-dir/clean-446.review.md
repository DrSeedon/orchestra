## Summary

Reviewed the complete diff from `494a54315f21b38fbf5c9a35a16e85db9620c797` to `9727d23df221caebf909cecaa149128e2a4009b7`. The change keeps raw telemetry in persisted logs and suppresses matching status events in the chat renderer and Telegram stream.

## Findings

### Suggestion

`/api/logs/sync` returns log rows without the `status_hidden` annotation. The route describes this endpoint as a browser log mirror, so its consumers receive raw telemetry without the suppression metadata used by session SSE and history responses. Consider applying the same classification there.

## Verdict

APPROVED — the reviewed session chat and Telegram paths suppress the raw telemetry while retaining it in logs. The sync endpoint gap is a suggested improvement.
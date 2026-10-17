## Summary

Reviewed the complete diff between the pinned commits. The negative Grok cache and retry jitter look consistent with the task. I found one issue in the usage snapshot path.

## Findings

### suggestion

[usage.js](/home/kesha/v909-work/v909-clean-197-y52ovpbg/app/static/js/usage.js:770): When `/api/usage` fails, `Promise.allSettled` still fulfills, so execution never reaches the catch that restores the saved snapshot. Instead, this code sets `_usageData` to `null` and saves that null over the last successful snapshot. The UI then shows “Usage unavailable,” and the cached data is lost. Preserve existing data and only update `_usageLastSuccessAt` and the snapshot after a successful usage response.

## Verdict

NEEDS WORK
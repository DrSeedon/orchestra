# item-38

Commit under review (in /home/kesha/orchestra, read-only): `24d6308d4fabe61cbbe497d8e9e750e304e500db`
Subject / date:
#197: #197: кеш последнего успешного ответа, джиттер ретраев, негативный кеш провайдера
2026-08-20

The diff reviewed is `git -C /home/kesha/orchestra show 24d6308d4fabe61cbbe497d8e9e750e304e500db -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff between the pinned commits. The negative Grok cache and retry jitter look consistent with the task. I found one issue in the usage snapshot path.

## Findings

### suggestion

[usage.js](app/static/js/usage.js:770): When `/api/usage` fails, `Promise.allSettled` still fulfills, so execution never reaches the catch that restores the saved snapshot. Instead, this code sets `_usageData` to `null` and saves that null over the last successful snapshot. The UI then shows “Usage unavailable,” and the cached data is lost. Preserve existing data and only update `_usageLastSuccessAt` and the snapshot after a successful usage response.

## Verdict

NEEDS WORK

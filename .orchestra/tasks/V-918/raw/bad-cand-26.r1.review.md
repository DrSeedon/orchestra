## Summary

Reviewed the complete diff between the specified commits. The new buttons link directly to `/api/files/raw`, while the previous button used `/api/open-file`, which checks `ALLOW_OPEN_FOLDER`.

## Findings

### Suggestion

When `ALLOW_OPEN_FOLDER` is unset, the UI still shows Download and Preview. Those actions call `/api/files/raw`, which does not check that setting, so they remain available instead of showing “Disabled on server.” If the task is to preserve that server-disabled behavior, the new buttons should be gated on the server setting or use an endpoint that reports it.

## Verdict

NEEDS WORK
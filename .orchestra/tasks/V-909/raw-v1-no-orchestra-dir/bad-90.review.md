## Summary

Reviewed the complete diff from `da98620643f6e9b5883282aed6400159259f7311` to `347fa038119a99aa96e7ad37965068c800591cd6`. No files were changed.

## Findings

### Suggestion

- [app.js](/home/kesha/v909-work/v909-bad-90-hzce67ee/app/static/js/app.js:1266): An inline prompt fetch can finish after the operator selects another agent or scope, then render the old prompt in the current preview. Capture the agent and scope when starting the request and discard the result if either has changed.

- [app.js](/home/kesha/v909-work/v909-bad-90-hzce67ee/app/static/js/app.js:1265): The cache guard only skips fetching when the content has more than one child. “No system prompt” and error states have one child, so polling can repeatedly request them; while a request is pending, repeated updates can also start duplicate requests. Track the loading/completed state per agent and scope.

## Verdict

NEEDS WORK — fix the stale prompt display and avoid repeated or overlapping prompt fetches.
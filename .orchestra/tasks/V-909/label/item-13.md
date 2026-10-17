# item-13

Commit under review (in /home/kesha/orchestra, read-only): `58155da638ebdd1c4f87f2f331ecdd7b6166aad6`
Subject / date:
#112: #112: refresh stale usage on demand
2026-08-01

The diff reviewed is `git -C /home/kesha/orchestra show 58155da638ebdd1c4f87f2f331ecdd7b6166aad6 -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff from `c84e15c53eef0f9fe02884dbab31f03d58043bf0` to `7993b763e0476bdc3aa4363e263acccfcc84697b`. No blocking correctness, data integrity, or security issue found.

## Findings

### Suggestion

Clicking the ⓘ help icon also bubbles to the usage bar’s click handler and starts a refresh. Since the icon already has its own help interaction, clicking it can unexpectedly trigger an API request. Consider stopping propagation on that icon. See [usage.js](app/static/js/usage.js:208) and [usage.js](app/static/js/usage.js:571).

## Verdict

APPROVED — the refresh behavior is otherwise sound: in-flight requests are shared, repeated visibility events do not start a request storm, and failed refreshes preserve the last successful data.

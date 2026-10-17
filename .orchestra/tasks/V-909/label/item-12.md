# item-12

Commit under review (in /home/kesha/orchestra, read-only): `e3e180c113a78b6195151017abae2f605372031b`
Subject / date:
#90: dashboard UX — expand all sections, show role/model/prompt upfront
2026-06-13

The diff reviewed is `git -C /home/kesha/orchestra show e3e180c113a78b6195151017abae2f605372031b -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff from `61149d3c914ceff1b33d8ce625e474b46d96ef97` to `f1206e8967a500aa4fb7a719ba247e68fb7e6658`, including the prompt-block endpoint and the dashboard refresh path. No files were changed.

## Findings

### Suggestion

- In [`app/static/js/app.js`](app/static/js/app.js:1264), the cache guard checks `content.children.length > 1`. The “No system prompt” and error states each leave a single child, so each three-second session refresh triggers another prompt request for those agents. Track the request/result state explicitly so empty and failed responses don’t cause repeated fetches.

- In [`app/static/js/app.js`](app/static/js/app.js:1268), an in-flight request can finish after the user switches agents and overwrite the newly selected agent’s preview. Check that the requested agent and scope still match the current selection before rendering the response.

## Verdict

NEEDS WORK

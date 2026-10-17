# item-40

Commit under review (in /home/kesha/orchestra, read-only): `b68ace2194ece85d754b1ad578e85651c92b9dd9`
Subject / date:
#202: бабл веб-поиска показывает запрос и результат
2026-08-20

The diff reviewed is `git -C /home/kesha/orchestra show b68ace2194ece85d754b1ad578e85651c92b9dd9 -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff between the pinned commits. It changes web search card classification and result handling in `app/static/js/app.js`.

## Findings

### Suggestion

[app.js](app/static/js/app.js:5727): `codexWebSearchSpec()` returns a spec for any JSON object, even when it has no search action or query. As a result, a structured MCP result such as `{ "result": "...", "citations": [...] }` still takes the early return: the card shows a generic “Waiting for query details…” activity and drops the result body. That undermines the change’s goal of displaying search results. Only treat a payload as an activity spec when it contains recognizable activity fields; otherwise let it reach the normal result renderer.

## Verdict

NEEDS WORK.

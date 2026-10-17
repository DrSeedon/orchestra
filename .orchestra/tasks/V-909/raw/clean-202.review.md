## Summary

Reviewed the complete diff between the pinned commits. It changes web search card classification and result handling in `app/static/js/app.js`.

## Findings

### Suggestion

[app.js](/home/kesha/v909-work/v909-clean-202-b7884ooc/app/static/js/app.js:5727): `codexWebSearchSpec()` returns a spec for any JSON object, even when it has no search action or query. As a result, a structured MCP result such as `{ "result": "...", "citations": [...] }` still takes the early return: the card shows a generic “Waiting for query details…” activity and drops the result body. That undermines the change’s goal of displaying search results. Only treat a payload as an activity spec when it contains recognizable activity fields; otherwise let it reach the normal result renderer.

## Verdict

NEEDS WORK.
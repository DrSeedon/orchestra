## Summary

Reviewed the complete diff from `c2a9f4bf9d0bdec867487bd632e0bcd68efe3158` to `0b6d935ca39d9450478b6fac424295b61fc9a89b`. The change stops using recent selections to order tabs and uses them only to choose a default orchestrator when there is no saved selection.

## Findings

### Suggestion

- [app/static/js/app.js](/home/kesha/v909-work/v909-clean-V-607-1p4_kmw9/app/static/js/app.js:1818): Recent selections store only orchestrator names, but the database allows the same name in different scopes (`UNIQUE(name, scope)`). If the saved selection is unavailable and a recent name matches multiple orchestrators, this lookup may choose the wrong scope. Store and match scope alongside name in recent selections.

## Verdict

APPROVED — the tab ordering change is sound. The duplicate-name case is a non-blocking improvement.
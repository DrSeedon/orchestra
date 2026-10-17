# item-02

Commit under review (in /home/kesha/orchestra, read-only): `2bdb6742f57db6cb0262dd700fd4a824af88fdfe`
Subject / date:
#V-607: порядок вкладок оркестраторов больше не пляшет от того, кого открывали последним
2026-09-21

The diff reviewed is `git -C /home/kesha/orchestra show 2bdb6742f57db6cb0262dd700fd4a824af88fdfe -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff from `c2a9f4bf9d0bdec867487bd632e0bcd68efe3158` to `0b6d935ca39d9450478b6fac424295b61fc9a89b`. The change stops using recent selections to order tabs and uses them only to choose a default orchestrator when there is no saved selection.

## Findings

### Suggestion

- [app/static/js/app.js](app/static/js/app.js:1818): Recent selections store only orchestrator names, but the database allows the same name in different scopes (`UNIQUE(name, scope)`). If the saved selection is unavailable and a recent name matches multiple orchestrators, this lookup may choose the wrong scope. Store and match scope alongside name in recent selections.

## Verdict

APPROVED — the tab ordering change is sound. The duplicate-name case is a non-blocking improvement.

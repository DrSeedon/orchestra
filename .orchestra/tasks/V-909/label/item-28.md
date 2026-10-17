# item-28

Commit under review (in /home/kesha/orchestra, read-only): `34fb2350a8224f2991dbe722afc29070daf02bee`
Subject / date:
#355: #355: add verified merge receipts
2026-08-25

The diff reviewed is `git -C /home/kesha/orchestra show 34fb2350a8224f2991dbe722afc29070daf02bee -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff between the pinned commits. No files were changed.

## Findings

### Suggestion

`merge_receipt_mode()` is never called in the application. As a result, `merge_receipt_configured()` remains false during merge execution: receipts are not created, finalization does not require them, and successful operation records are not checked against durable receipts. The new receipt flow is therefore inactive on the application’s merge path. Wire the mode into that path with the canonical store and resolvers. ([merge_receipts.py](app/ia/merge_receipts.py:90), [sessions.py](app/routes/sessions.py:1800))

## Verdict

NEEDS WORK — verified merge receipts are not active in the application.

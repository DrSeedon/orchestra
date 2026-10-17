# item-29

Commit under review (in /home/kesha/orchestra, read-only): `18d8061390dcdf2fce8b777d94079ab2438a35c0`
Subject / date:
#4: #proxy-fix: force stable id='direct' for direct proxy
2026-07-01

The diff reviewed is `git -C /home/kesha/orchestra show 18d8061390dcdf2fce8b777d94079ab2438a35c0 -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff between the specified commits. The direct proxy now gets the stable `id="direct"` when its URL is exactly `"direct"`, and the added test covers a name containing Cyrillic characters and punctuation.

## Findings (blocking/suggestion/question)

None.

## Verdict

APPROVED — no actionable issues found. I did not run tests.

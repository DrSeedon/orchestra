# item-36

Commit under review (in /home/kesha/orchestra, read-only): `4dd81e7e3a18b4527c3875a9772d5afdcc23237a`
Subject / date:
#V-600: корневые правила — один AGENTS.md, дубль CLAUDE.md запрещён
2026-09-19

The diff reviewed is `git -C /home/kesha/orchestra show 4dd81e7e3a18b4527c3875a9772d5afdcc23237a -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff between the specified commits. The change removes the root `CLAUDE.md` mirror, makes the instruction checker reject its return, and adds `AGENTS.md` to the default worktree copy list.

## Findings

### Blocking

None.

### Suggestion

None.

### Question

None.

## Verdict

APPROVED — the implementation matches the task: the repository has one root rules file, and the contract checker rejects a `CLAUDE.md` duplicate. I did not run tests.

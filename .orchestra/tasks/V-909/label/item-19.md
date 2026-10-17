# item-19

Commit under review (in /home/kesha/orchestra, read-only): `6c95039bcf352184d92bcd47df940e0b8da8f5bb`
Subject / date:
#149: #149: research — скиллы не доезжают до живых агентов (22 протухших копии, 16 оркестраторов без доставки)
2026-08-05

The diff reviewed is `git -C /home/kesha/orchestra show 6c95039bcf352184d92bcd47df940e0b8da8f5bb -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff between the pinned commits, including the runtime changes, tests, and task documents. Found one security issue in the new write path.

## Findings

### Blocking

- [app/prompting.py](app/prompting.py:165): The symlink guard checks only whether the final `SKILL.md` is a symlink. An untracked `.claude`, `skills`, or skill-name directory can itself be a symlink, so the subsequent `mkdir`/`cp`/`mv` follows it and may write or replace a file outside the repository. This path now runs in an agent’s ordinary user `cwd`. Reject symlinks in every destination path component or perform the install using directory-relative operations that cannot follow them.

## Verdict

NEEDS WORK — the new injection path can write outside the intended repository through a symlinked parent directory.

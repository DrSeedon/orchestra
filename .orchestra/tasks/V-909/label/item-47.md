# item-47

Commit under review (in /home/kesha/orchestra, read-only): `67ee5df0385b4dfec19052c8658447c76d6e4a4c`
Subject / date:
#V-593: блокировка бесплатных маршрутов, отказавших в нашей пробе
2026-09-17

The diff reviewed is `git -C /home/kesha/orchestra show 67ee5df0385b4dfec19052c8658447c76d6e4a4c -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff between `16057e339bc1aeed01b7af14dc0365c8bebbb1bb` and `a59895dbe1bb8d02ed48cc9cebdbbe7ed2bfc86e`. It adds a blocklist for routes that failed the probe, excludes them from catalog registration, and rejects them at harness admission.

## Findings

None.

## Verdict

APPROVED.

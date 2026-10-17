# item-14

Commit under review (in /home/kesha/orchestra, read-only): `ccc55e9cf76b50c54fa6ed2d2c3c991a2efe8641`
Subject / date:
#88: auto-bootstrap — ensure workspace + default orchestrator on startup
2026-06-12

The diff reviewed is `git -C /home/kesha/orchestra show ccc55e9cf76b50c54fa6ed2d2c3c991a2efe8641 -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff from `0bc5a7e7c82ed3878ea86e40c8812e8b678a1c44` to `a98c3185401756828938856fd01e2c83176a2ca0`. I found a startup crash path when the default orchestrator’s name and scope already belong to an archived session.

## Findings

### Blocking

- [app/bootstrap.py](app/bootstrap.py:59): `get_all_sessions()` excludes archived sessions by default. If an archived session has the configured bootstrap name and `/workspace/project` scope, bootstrap misses it and tries to insert a new row. The sessions table has a unique constraint on `(name, scope)`, so `save_session()` raises `sqlite3.IntegrityError` and aborts application startup. Include archived sessions in the existence check and handle the existing row, or otherwise avoid the conflicting insert.

## Verdict

NEEDS WORK

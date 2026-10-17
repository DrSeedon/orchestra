# item-21

Commit under review (in /home/kesha/orchestra, read-only): `71240bd4f2d629ad259fbb1949fd3819827c0e1f`
Subject / date:
#446: suppress raw telemetry from user channels
2026-09-03

The diff reviewed is `git -C /home/kesha/orchestra show 71240bd4f2d629ad259fbb1949fd3819827c0e1f -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff between the specified commits and traced the status events through the browser chat and Telegram delivery paths. The implementation marks matching telemetry in session history and SSE, hides it from chat rendering, and skips it in Telegram delivery. Persisted logs remain unchanged.

## Findings

None.

## Verdict

APPROVED

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Reviewed the complete diff from `8209b2b...` to pinned HEAD `50825db...`. Focused tests pass: 7/7.

Admission behavior is correct: detached conflicts return HTTP 409 before quota/admission, queued races become `FAILED_BEFORE_SUBMIT`, attached writers remain usable, and lock files are never deleted.

## Findings

### suggestion — `/proc/locks` is scanned twice per loaded session projection

`app/session.py:5318-5329` and `app/session.py:5336` both call `_writer_health_error()`, which performs `stat()` plus a full synchronous `/proc/locks` scan via `app/backend_codex.py:467-486`.

Thus each `to_dict()` performs two scans. `manager.list_sessions()` invokes this for every loaded session, and the dashboard polls every three seconds. With dozens of sessions this creates unnecessary repeated filesystem parsing and can produce a transient mismatch if the lock releases between scans: `status` may say `idle` while `runtime_connection` still says `writer_conflict`, or vice versa.

This is a performance/observability improvement, not an admission blocker. The retained diagnostic after lock release is intentional and correctly remains until successful reconnect.

## Verdict

APPROVED — no blocking findings.

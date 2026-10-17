## Summary

Reviewed the complete diff between the specified commits. The context menu calls the new endpoint, but that endpoint fails when it tries to persist the toggle.

## Findings

### Blocking

- [app/routes/sessions.py](/home/kesha/v918-work/v918-bad-cand-58.r1-1bc45nxs/app/routes/sessions.py:707): `save_session(found.to_dict())` passes a dictionary missing fields required by `save_session`’s SQL statement, including `cwd` and `session_id`. Toggling TG Topic therefore raises a SQLite binding error and returns a 500; the UI catches the error, so the toggle never takes effect. Use the existing `manager.update_session_fields(name, scope, tg_topic=enabled)` path, which already handles live and detached sessions.

## Verdict

NEEDS WORK
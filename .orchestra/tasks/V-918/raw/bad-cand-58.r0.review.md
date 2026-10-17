## Summary

Reviewed the complete diff between the requested commits. The new menu calls the new PATCH endpoint, but that endpoint’s persistence call fails.

## Findings

### Blocking

- [app/routes/sessions.py](/home/kesha/v918-work/v918-bad-cand-58.r0-nspk0jqp/app/routes/sessions.py:707): `found.to_dict()` omits fields required by `save_session()`, including `cwd` and `session_id`. `save_session()` uses those keys in its SQL parameters, so toggling the topic raises `KeyError` and returns HTTP 500. Use the existing `manager.update_session_fields(name, scope, tg_topic=enabled)` path, which handles live and detached sessions.

## Verdict

NEEDS WORK — the context-menu toggle cannot persist its change.
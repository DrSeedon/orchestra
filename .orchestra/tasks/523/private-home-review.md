<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Reviewed the exact pinned diff `109f027...18c1ffb9` in full.

- Confirmed seed helpers and #520 selector are removed with no remaining references.
- Confirmed new homes use private `sessions/` and do not read/clone shared SQLite state.
- Confirmed existing session symlinks, including broken ones, remain untouched.
- Confirmed native history import version validation and reconnect behavior remain covered.
- Confirmed connect remains protected by async and file locks.
- Focused tests: `152 passed in 16.11s`.
- `codex_review` unavailable; Luna review was not executed.
- `git diff --check` reports whitespace only in added evidence logs; skipped as nit.

Verbatim reviewed line: `if not sessions.exists() and not sessions.is_symlink():` (`app/backend_codex.py:2402`).

## Findings (blocking/suggestion/question)

None.

## Verdict

Approve.

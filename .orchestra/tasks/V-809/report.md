# V-809 — scope the known pytest error series

The V-783 signature was normalized from message text alone, while `collect_db_events` omitted its originating session scope. As a result, a same-text error from seedon's `tender-triage` session entered the Orchestra baseline and post-fix count.

Database error events now carry `sessions.scope` and session name. Journal messages inherit scope only when the current log window maps that session name to exactly one scope. The V-783 known-series count and post-fix verdict accept only the repository root resolved from `Path(__file__).resolve().parents[1]`, so the rule follows the checkout on VPS and laptop. Other and unresolved scopes are classified as `pytest missing outside Orchestra scope`; this class is reported at one event, independently of the recurrence threshold, and appears in `noise_by_class`. Other known signatures retain their prior behavior.

Verification confirmed log 633488 (`2026-10-10T08:45:59.586234+00:00`) belongs to session `tender-triage` with scope `/home/kesha/projects/seedon`. `uv run --frozen python -m pytest tests/test_error_watch.py` passed: 14 tests. This includes the in-scope/out-of-scope aggregate split, V-783 baseline and post-fix filtering, visible `noise_by_class`, and the database session-scope join. The imported module was `/home/kesha/orchestra/worktrees/home-kesha-orchestra/todo-triage/app/error_watch.py`.

`TODO.md` was not changed. No detector run, `record-fix`, or restart was performed.

## Follow-up before merge

Replaced the VPS-specific scope constant with `str(Path(__file__).resolve().parents[1])`. The tests derive Orchestra scope from the module location and use a temporary path for the foreign project. Re-ran `uv run --frozen python -m pytest tests/test_error_watch.py`: 14 passed.

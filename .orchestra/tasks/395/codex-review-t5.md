<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

The frozen acceptance tests pass, but canonical task creation can leave durable reservations permanently pending after a pre-commit failure, breaking retries with the same key.

Review comment:

- [P1] Clear reservations when canonical creation fails — /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-tm-hang/app/tm.py:2047-2060
  When `store.task_create()` fails before committing a canonical task, the SQLite receipt remains `PENDING`. Every retry then finds that receipt, fails to find a canonical task, and returns `IDEMPOTENCY_REQUEST_PENDING` forever, so a transient pre-commit failure permanently prevents the caller from retrying with the same durable key.

> ⚠ Codex usage unaccounted: ValueError: Codex completed turn reported zero tokens

## Round (2026-08-28T08:26:38Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Verdict

Re-review status: approved.

- Prior P1: FIXED. The exception path performs canonical lookup, deletes only a matching `PENDING` receipt when no task exists (`app/tm.py:2091–2097`), and retries can proceed.
- New blocking bugs: none found.
- Acceptance: `8 passed in 12.68s`.
- `git diff --check`: clean.

Evidence: `app/ia/task_store.py:1161` — `if request_key:` (changed line not included in the prompt).

Review route: self-review; Codex reviewer unavailable.

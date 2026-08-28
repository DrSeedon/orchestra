<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

The patch correctly catches the normal successful no-op path, but still allows a contradictory zero-commit result to be normalized as Git success when the upstream ok flag is false.

Review comment:

- [P1] Reject zero-commit no-ops regardless of the ok flag — /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-delivery-visibility/app/merge_operations.py:1023-1027
  When a resumed or legacy result has `commits_merged=0` and equal target snapshots but `ok` is false, this guard is skipped; if its `commit_point` is `target_committed`, the later normalization still reports `git.status` as `SUCCEEDED`. The no-op invariant must be enforced independently of the upstream `ok` value so such results cannot appear successful or trigger lifecycle handling.

> ⚠ Codex usage unaccounted: ValueError: Codex completed turn reported zero tokens

## Round (2026-08-28T07:26:13Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Re-review status: FIXED

New findings: none.

Verdict: APPROVED

Evidence:

- `git diff --check` — passed.
- Changed files: only `app/merge_operations.py` and `app/workspace.py`; `sessions.py` untouched.
- Tested:

  `uv run pytest -q ...`

  Output: `4 passed in 8.28s`

Changed production line: `raw = {` (in `normalize_merge_result`).

Review route: none — Codex unavailable.

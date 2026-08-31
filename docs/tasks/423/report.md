# #423 — merge conflict report

## Result

`merge_worktree_to_main` now reports conflict paths from the target merge worktree with
`ok: false` and `merge conflict in N file(s): ...` (first 10 paths plus `… and K more`).
The normalizer preserves the raw path-bearing message, emits `CONFLICT`, and points the
caller to `RESOLVE_ON_WORKER_THEN_NEW_OPERATION`. A no-op squash with no conflicts keeps
the existing `NO_COMMITS_MERGED` behavior.

## Verification

- `uv run python -m pytest -q tests/test_merge_conflict_report_423.py` → `3 passed`.
- `uv run python -m pytest -q tests/test_merge_reason_preservation_416.py` → `3 passed`.
- `uv run python -m pytest -q tests/test_merge_operations.py tests/test_workspace.py` → `153 passed`.
- The test creates only temporary Git repositories and does not call `app.db.init_db()`.

Mutation of the committed production fix changed `_merge_conflict_result` to return
`ok: true` without conflicts. The acceptance test then returned `1 failed, 2 passed`.
The production `"state": "conflict"` marker was `1` before mutation, `0` in the mutant,
and `1` after restoring `app/workspace.py` with `mv` plus `touch`; the restored acceptance
run returned `3 passed`.

## Review gate

- Changed files and consumers: `app/workspace.py` (`merge_worktree_to_main`, consumed by
  session merge route), `app/merge_operations.py` (`normalize_merge_result`, consumed by
  merge operation responses), `tests/test_merge_conflict_report_423.py`, and this report.
- Author metadata: `gpt-5.6-luna`, Codex runtime, session
  `6534abe8-ea8d-4f00-a312-0c9f59f82769`.
- Exact AC: conflict result carries paths and a path-bearing error; normalized conflict is
  not `NO_COMMITS_MERGED` and points to resolution; conflict-free empty squash keeps the
  old no-commit result; both named acceptance commands pass.
- Named commands and observed output: the two acceptance commands above (`2 passed`,
  `3 passed`), plus merge/workspace coverage (`153 passed`).
- Route: one fresh Luna implementation review; no Sol review (not authorized). The reviewer
  produced a verdict with evidence (`tests/test_merge_conflict_report_423.py` — `2 passed`,
  `tests/test_merge_reason_preservation_416.py` — `3 passed`, and
  `tests/test_merge_operations.py tests/test_workspace.py` — `153 passed`) and identified
  P2: newline-containing Git paths were parsed with `splitlines()` in the fallback.
  Fixed by using `git diff --name-only --diff-filter=U -z` and splitting on NUL; the added
  temporary-repository test now passes for `line\nbreak.txt`. No follow-up round was run:
  the finding was non-blocking and the review artifact was not otherwise changed.

## Pre-mortem

- A conflict with unchanged target could be rewritten as `NO_COMMITS_MERGED` → the new
  conflict test asserts normalized `CONFLICT` and its resolution action.
- A clean empty squash could be reclassified as a conflict → the no-op test asserts the
  existing `NO_COMMITS_MERGED` result and empty conflicts list.
- More than ten paths could produce an unbounded error → the formatter is bounded by
  `conflicts[:10]`; a direct helper probe with 11 paths was run before handoff.
- A real `git merge` failure could lose paths during `reset --merge` → the path query is
  executed before reset; the same command is used in the merge worktree.
- Normalization could regress the adjacent raw-error contract →
  `tests/test_merge_reason_preservation_416.py` remains green (`3 passed`).

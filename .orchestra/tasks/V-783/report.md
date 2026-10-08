# V-783 — test invocation and known error growth

## Changes

`AGENTS.md` now directs workers to run `uv run --frozen python -m pytest` from the worktree root. This keeps module imports tied to the worktree's selected environment and tells workers that `uv` creates `.venv` on first use.

`app/error_watch.py` records two known normalized signatures and task references: `<PATH>: No module named pytest` → V-783; `transport_timeout: Message delivery outcome is ambiguous: ReadTimeout` → V-778 and V-782. Each has a baseline count of ten in the rolling window. The detector stays quiet for unchanged or falling counts, and alerts only when a count rises above ten and above the count seen on the previous scan. It keeps the observed count even below the regular alert threshold, so a later rise can be detected after old events age out.

## Verification

The current worktree passed `uv run --frozen python -m pytest tests/test_error_watch.py -q`: 12 passed in 11.70s. It had no `.venv` before the command; `uv` 0.11.28 created one with CPython 3.12.3 and installed 76 packages in 149ms. The imported test module resolved to `/home/kesha/orchestra/worktrees/home-kesha-orchestra/todo-triage/app/error_watch.py`; the full output is in `current-worktree-uv.log`. `uv run --frozen python scripts/check_instruction_contract.py` reported `Instruction contract OK`, including the AGENTS.md size limit and CLAUDE.md symlink.

The exact `uv run --frozen python -m pytest tests/test_error_watch.py -q` command returned 0 in all five existing affected worktrees. The first harness failed while saving its stdout because the task report directory had not yet been created; it reached the save operation only after all five test and import subprocesses returned 0. To retain environment evidence, `worktree-check.log` records `uv` 0.11.28, pytest 9.0.3, successful `app.error_watch` imports and their absolute paths, and `.venv` presence before and after. All five already had `.venv`; none was created during verification.

Three of the eight worktrees associated with the pytest errors no longer exist: `feat-kesha-alert`, `feat-live-limits`, and `feat-video-player`. The other five were checked. A read-only exact-text query of `tool_errors` for Oct 4–8 found 11 `/usr/bin/python: No module named pytest` rows across the same eight sessions; the task's initial tally was 10, so the additional row is above the configured baseline and should cause one growth alert on the next scan. The exact transport-timeout text had 10 rows in the query window. This baseline lets the detector report a continuing increase once, then suppress the unchanged count.

`TODO.md` was not changed. No live detector run or `record-fix` was performed; the owner said to run `python -m app.error_watch record-fix` after merge.

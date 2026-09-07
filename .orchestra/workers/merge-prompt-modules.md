# merge-prompt-modules — personal notes

## Orchestra prompt assembly (learned on #490/#520)

- The prompt an agent actually sees is `app.pipeline.build_system_prompt("default", role)`
  (`app/pipeline.py:583`). Reproduce it exactly for before/after evidence; do not concatenate
  files by hand.
- Order: `prompt_layers` first (`base.md`, then `roles/{role}.md`), **then** the `modules:` list in
  manifest order. Moving a block from `base.md` into a module therefore also moves it from the top
  of the prompt to the bottom.
- `modules:` is per-role in `.orchestra/pipelines/default/pipeline.yaml`. `reducer` had
  `modules: []` — any block moved out of `base.md` silently vanishes from the reducer unless the
  module is added there too. Always check all five roles, reducer last and hardest.
- Nothing is cached across a turn: module files are read uncached in `build_prompt_modules`, and
  `_load_pipeline_cached` keys on `(mtime_ns, st_size)`. Prompt edits reach live agents on the next
  turn without a restart.
- `tests/test_default_pipeline.py::test_modules_resolve_from_manifest` hardcodes each role's
  module list — editing `pipeline.yaml` always means editing that test.

## `scripts/check_pipeline_manifest.py` gotcha

It requires a source marker (`#123`, `source:`, a URL, or `.orchestra/tasks/`) on the **same
physical line** as a measured number. Wrapping `median 3.3 h, p75` onto one line and `#220` onto
the next fails the check with "measured numeric claim lacks inline source marker". Keep the number
and its marker together when reflowing prose in `prompts/`.

## Pre-existing red in the suite (as of 06.09.2026)

`tests/test_task_tracker_integration.py::test_t3_merge_operation_replay_does_not_repeat_git_or_lose_task_outcome`
fails (`PARTIAL` vs `FAILED`) on clean `main` too. Verify against a detached worktree at `HEAD`
before spending time on it: `git worktree add --detach /tmp/pristine HEAD`.

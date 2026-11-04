# sanitized-publication-copy
# Private originals: private/tasks/V-1273/originals/ (root-held SHA-256/bytes manifest; not accessed here).

# V-1273 — initial findings

- Scope: private Hub copy only. No `.git` or source history is supplied; historical evidence is CHANGELOG V-1008/V-1062/V-1213 and their current tests. No live recovery, imports, sessions, credentials or other worktrees inspected.
- Defect: commit refusal leaves newly imported additions staged. A later import deletes one of those additions. `git add -A` removes it from the index, but `commit_sync` passes the original path to `git commit --only`; a never-committed path is now unknown and aborts the whole commit.
- Existing tests cover HEAD-tracked deletion with an already staged deletion, ignored or missing changed paths and unrelated index preservation; none covers a deleted staged addition after a scanner refusal.
- Regression uses actual production pre-commit/scanner sources, a missing scanner refusal, two fake-Hub turns with real tar import/state/commit, mixed tracked deletion and changed output. No scanner bypass.

## Test-first result
- Initial run: 7 failures, including a test fixture typo (`backend.paths` instead of `_paths`). Fixed only the test typo, reran against unchanged production source.
- Corrected RED: 7 failed in 26.81s. Integration fails at second turn with changed 2, deleted 2, NOT COMMITTED and exact synthetic `duplicate.txt` pathspec. Raw output: red.txt.
- Fix inspects index + cached diff after staging; a deleted path absent from both and disk is removed from commit candidates and staging-refusal diagnostics. Cached diff uses `--no-renames` so a HEAD-tracked deletion remains commit-worthy. Git inspection failure raises visibly. It never changes scanner, import, ownership, privacy or recovery policies.

## Supplied-copy limitations discovered during verification
- The existing scanner-suite negative controls reference two files not supplied to this private copy: `.orchestra/tasks/315/acceptance/fixtures/t5_recovery_records.json` and `.orchestra/kb/runtimes.md`. Their existence assertions cannot pass here; do not synthesize replacements or weaken the tests. The broad run is retained as-is so actual failures are visible.
- Broad run shows a failure before scanner negative controls; final traceback is not yet emitted. Preserve full raw run and identify its cause before completion. New 9-test block has passed in that run so far.
- Before running the required mutation alongside the single-process broad suite: cgroup memory 38,950,305,792 / 52,755,525,632 bytes; host available 77 GiB, CPU limit 8. Two lightweight pytest processes fit the resource margin; no browsers/build farms. Both nice=10 and oom_score_adj=1000. Separate pytest tmp roots; same frozen .venv.

## Mutation result
- `uv run --frozen python .orchestra/tasks/V-1273/mutate.py`: expected exit 1, **1 failed in 36.58s**. Actual second-turn failure matches the original: changed 2/deleted 2, NOT COMMITTED, `duplicate.txt` unknown to Git. Old function restored only in test-process memory; working source stays fixed. Raw output: mutation.txt.

## Broad verification interruption
- The 9-module pytest process ended with exit 143 before printing a summary (tool session 28319); no explicit stop was issued by this worker. Its partial raw output is retained in green-suite.txt. This run is NOT a passing suite and its observed failure remains unclassified until a focused reproduction. Required checks must be rerun in bounded smaller groups.
- Focused reproduction identifies the broad run's failure: `test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools`, expected worker identity absent from prompt. `hub_preamble` falls back to PREAMBLE_BASE when `.orchestra/pipelines/default/prompts/hub/worker.md` is missing (not supplied in this copy). Raw prompt-control.txt: 1 failed in 16.88s. It is outside commit_sync; baseline-control run pending.
- Resource check before bounded groups: cgroup 36,224,061,440 / 52,755,525,632 bytes, host available 77 GiB, CPU 8. Use at most 2 xdist workers per group, two groups (4 workers plus light masters), comfortably below memory/CPU limits. No browser or provider.
- Confirmed prompt template absent with a direct local path check. Baseline control using original commit_sync has the identical failure (1 failed in 22.54s), proving it is not introduced by this patch. Raw prompt-baseline.txt.

## Completed guard group
- `tests/test_hub_file_policy_v1073.py tests/test_secret_commit_gate.py -q -ra -n 2`: **99 passed, 5 failed in 70.92s**, no skips. All five failures are supplied-copy constraints: three missing-file controls (315 fixture, CLAUDE.md, KB runtimes.md), scanner mention test reusing missing 315 fixture, and repository-level check-ignore requiring absent source `.git`. Raw guards.txt. None calls the changed commit_sync; no fixture or guard changed to conceal these failures.

## Completed core group
- **105 passed in 264.30s**, exit 0, no skips; all 9 new regressions, existing commit/deletion/WIP and V-1213 recovery + V-1062/V-1063 inputs passed. Raw green-core.txt, exact command core-command.txt.
- Original interrupted broad log has no remaining file holders (fuser available; no PID returned). All test sessions are terminal; no browser/server was started.

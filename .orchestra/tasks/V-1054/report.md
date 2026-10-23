# V-1054 — prompt edits and measurement design

DONE: the approved prompt changes and evaluation package are prepared. Their
effect on model findings is not yet measured; model runs belong to the
orchestrator. Owner decision: 2026-10-23.

## Changes and reading order

1. `.orchestra/pipelines/default/prompts/roles/worker.md`: expands the existing
   pre-mortem, only where relevant, with the prior contract (including unchanged
   callers/config/hooks), failure, repeated calls, old data and rollback. Claims
   that a risk is covered need evidence; otherwise they remain unverified.
   Existing proportionality and the prohibition on scenario quotas remain.
2. `.orchestra/pipelines/default/prompts/modules/report-format.md`: adds a short
   reading order (central files, then relevant unchanged consumers, with a reason)
   and must-fix / optional / open question findings. Uncertainty alone does not
   make a serious risk optional. Empty finding categories may be omitted.
3. `.orchestra/pipelines/default/prompts/roles/orchestrator.md`: after the verdict
   for a merged change, asks for why → changed behaviour → actual check →
   unverified remainder. Existing verdict-first and number-table rules remain.
4. Read the unchanged consumers/context next: `tests/test_default_pipeline.py`
   covers prompt assembly and role/module delivery. `roles/full-cycle.md` and
   `hub/worker.md` contain their own pre-mortems; they were not edited. Actual
   assembly code and the pipeline manifest were not supplied, so delivery across
   these variants is not established by this source inspection.
5. `eval/README.md`, `eval/prompt_before.md`, `eval/prompt_after.md`, then
   `eval/cases.json` describe the isolated comparison and its inputs.

Source diff: `prompt-edits.diff`, three files, +16/-4 lines. All additions to
prompts are English and record the owner decision. No tests, model-review
policy, merge API, runtime code, TUI or quiz were added or changed.

## Evaluation package

The before/after files contain the exact old/new worker pre-mortem bullet plus
the identical requested wrapper. They are extracted self-check instructions,
not whole system prompts. `cases.json` contains only the paths of the four
supplied diffs. I did not inspect their contents or infer a defect key.

The protocol recommends three fresh runs per case per arm (24 scheduled runs),
identical settings, randomized/interleaved order, no cross-run context or access
to task notes, and preserved raw findings and failures. Hidden-key scoring
matches file and faulty mechanism, deduplicates per run, records control false
alarms, and retains ambiguous/unmatched findings for adjudication. It reports
individual runs and variation without generalizing from four fixed cases.

This comparison isolates the self-check text; it cannot demonstrate the value
of the report layout or owner-facing retelling. Those effects and actual
self-check on a model's own authored change remain unmeasured.

## Checks actually run

- Read V-1053's complete report, including the decision table and limitations.
- `patch --reverse --dry-run -p1 < .orchestra/tasks/V-1054/prompt-edits.diff`:
  passed for all three source files. No reverse patch was applied.
- Offline standard-library `python3` artifact checks: passed. Reconstructed
  original source from the saved diff; checked unchanged structural tags,
  placeholders and fence counts; verified exact before/after extraction and
  identical wrappers; parsed the four unique existing paths. Source/case hashes
  are in `prompt-integrity.json`; summary in `artifact-check.output.txt`.
  These are artifact-integrity checks, not project tests or tests that pin
  prompt wording. No new tests were written.
- `uv run --frozen python -m pytest tests/test_default_pipeline.py -q`: could
  not run, exit 127. The installed shim reports that `uv` is absent and cannot
  forward from this hub copy; see `required-check.output.txt`. System Python
  was used only for editing/validating artifacts, not as a substitute runner.
- The full `uv run --frozen python scripts/run_tests.py` suite and instruction
  contract check remain unrun: `uv`, `scripts/` and `app/` are unavailable here.
  No `app` was imported. Its expected local path is
  `<hub-copy>/app`,
  which does not exist in this supplied copy.
- Final source diff was inspected. The secret-shape scan of edited prompts and
  generated task artifacts is recorded in `secret-shape-scan.output.txt`.

## Findings and remaining work

Must-fix: none established by the checks available in this copy.

Open question: does the changed self-check improve defect detection without
increasing control false alarms? The orchestrator must run and score the saved
experiment. There is no measured benefit to claim yet.

Open question: runtime prompt assembly/delivery is unverified because the
required runner and application sources are missing. Run the existing prompt
mechanics checks on the full checkout. No live service was inspected, restarted
or deployed. Old data and rollback add no storage migration here; the changes
are prompt text and task-local artifacts only.

No local Git commit was made: this hub copy has no `.git`, and its critical
rules assign the commit to the platform. Requested platform commit:
`#V-1054: add relevant self-check risks and prepare before-after evaluation`.
Expected result branch: `task-V-1054/prompt-difftour`.

## Measurement (orchestrator, 23.10, Luna, hidden answer key)

Hidden key (kept outside git): v1050 — archive scanning not wired into the pre-push hook `scripts/secret_scan.py` (unchanged caller); v1052 — `scan_tree` diffs from the target tip instead of the merge-base, and no test covers the `merge_worktree_to_main` wiring; v1051 — hub paths in task artifacts (not visible: case diffs were cut to app/scripts/tests, so this case is invalid); v1049 — control.

| Run | Access | Case | before: key found | after: key found |
|---|---|---|--:|--:|
| 1 | — | all | invalid (my prompt used a literal `ARM.md` placeholder; 22/24 runs found no file) | — |
| 2 | diff only | v1050 | 0/3 | 0/3 |
| 2 | diff only | v1052 | 0/3 | 0/3 |
| 2 | diff only | v1049 control, runs with ≥1 claim | 1/3 (2 claims) | 2/3 (9 claims) |
| 3 | full repo at the worker's commit | v1050 | 0/3 | **1/3** (named `scripts/secret_scan.py` never calling the archive scanner) |
| 3 | full repo at the worker's commit | v1052 | 0/3 | 0/3 (one run found a different plausible issue: guard scans `_build_squash_message` while the commit may use `prepared_squash_message`) |

Verdict: **no reliable effect measured** (1/6 vs 0/6 on keyed defects with repo access; 2 cases × 3 runs cannot separate the arms). The one hit is exactly the mechanism the new question targets (unchanged caller), so the direction is plausible, not proven. Diff-only review cannot test the main new question at all. More claims on the control in the after arm (diff-only) — noise-level, worth watching. Raw answers: `eval/results/`. Spend: run 2 $0.07; run 3 similar.

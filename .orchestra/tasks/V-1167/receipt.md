# V-1167 — V-1160 host QA receipt

## Result

**STOPPED — two deterministic recovery-safety counterexamples reproduced.** The source was not patched. The full `scripts/run_tests.py` suite was not run after these probes, as permitted by the task. The existing focused recovery tests passed but do not cover the first counterexample.

The authorized integration is a true graph merge: source `fix-harness-flow` now has merge commit `703cce38771ace81c936d24767362dcee2ee7c3a`, with parents original V-1160 HEAD `2ce3d01fcadb87cd75c86b6460bb8adf9a0f989e` and accepted main `58d1fcc4caff9407b79f5a48ba2e5649d274b2d8`. No conflicts; only a two-parent merge commit was created, no rebase or source-code edits. The integrated source worktree is clean, and its V-1160 feature diff against main remains 14 paths. The future manifest-only patch is not applied. The checked-in default remains Opus.

## Deterministic probes

1. **Well-formed facts-note collision loses a distinct queued steer.** A temporary rollout contained the turn’s initial input and then a user-role native message whose exact body was a valid `facts_note(..., "да")`. A separate owner delivery with body `да` was `SUBMITTED` for that turn but absent from the rollout. The actual `recorded_turn_user_inputs` returned the note; `TurnManager.recover_failed_turn_steers` then treated its stripped body as evidence for the separate delivery. Probe RC 0 asserted the observed result: recovery count 0, receipt remained `SUBMITTED`, mailbox pending count 0, and recovery logged the delivery as already present. This is a false acknowledgement of a distinct event. `tests/test_v1160_steer_recovery.py::test_only_a_well_formed_facts_note_may_precede_the_message` passes because it asserts that a well-formed wrapper matches; it does not test user-authored wrapper content colliding with a separate queued event.

2. **The 32 MiB scan limit can be exceeded after `stat`.** A process-local probe (RC 0) made `Path.stat()` return a tail size of 138 bytes, then appended 33,554,463 bytes before the reader opened the file. The reader iterated 33,554,601 bytes to EOF and returned a known list instead of `None`; configured bound is 33,554,432 bytes. Existing tests cover a file already over the bound, wrong thread/inode, truncation and initial-input scoping, but not growth between `stat` and read. This demonstrates the pre-read size check does not cap concurrent growth.

Additional controls passed: an initial-input-only record did not confirm a steer, and arbitrary prefix-plus-delimiter text did not pass the facts-note parser. All probe databases/files were temporary; source files were not changed.

Probe setup attempts: the first `uv` invocation resolved `app` through the shared private symlink into the main checkout (RC 1 import error); explicit source `--project`/`PYTHONPATH` corrected it. The first private probe draft also had a `PosixPath + str` error (RC 1), then ran successfully after the path expression was corrected. An early focused runner selected a Python environment without pytest (`No module named pytest`, RC 1); using the existing `feat-terra` locked environment through `UV_PROJECT_ENVIRONMENT` produced the 61-pass result. These were harness setup errors, not source test failures; exact outputs/RCs are in private evidence.

## Host checks

| Check | Result |
|---|---|
| Source identity | HEAD above; Git metadata present; `main...HEAD` shows the 14 V-1160 feature paths; source worktree clean. Merge-tree RC 0/no conflict; merge commit parent order is original feature HEAD then accepted main |
| Source hashes | `source-feature-before-after.json` records SHA-256 before/after for all 14 feature paths. Eleven remain byte-identical; `CHANGELOG.md`, `app/backend_codex.py`, and `app/routes/sessions.py` incorporate the accepted-main contribution from the clean graph merge |
| Integration scope | QA made no product implementation edits. The graph merge carries accepted-main catalog/pricing/default-source contributions; hot pipeline/model-routing remain unchanged. Backend source combines the original V-1160 changes with accepted-main contributions, not a claim of whole-file identity to both parents |
| Instruction contract | RC 0; app import path resolves to `fix-harness-flow/app/__init__.py` |
| Focused recovery subset | RC 0: 61 passed, 0 failed, 6.63 s, including V-1160 steer/restart, durable steering, V-966 waiting delivery and V-1150 compact/manual-stop guards |
| Full suite | Skipped after the deterministic unsafe findings; no provider or native CLI call was made |

The remote source copy and the managed local worktree are different environments. The former lacks Git metadata; the latter has it. This receipt uses the actual managed worktree HEAD and Git diff.

## Evidence

Raw probe scripts, exact stdout/stderr/RC, focused test logs, source hashes and merge receipts are local under `.orchestra/private/V-1167/`; `artifact-manifest.txt` lists them. The full output is in `facts-note-collision.json` and `rollout-growth-after-stat.json`. The committed source diff and this QA receipt are the only repository changes in their respective worktrees.

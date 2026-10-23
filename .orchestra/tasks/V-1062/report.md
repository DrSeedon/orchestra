# V-1062 — untracked hub input files and output merges

> Publication-redacted evidence: remote installation prefixes are represented by `/remote/workspace`; derived installation slugs and pytest account labels are neutralized. Source-relative paths, synthetic test suffixes, fingerprints and original result lines are preserved. The app import path below is consequently a redacted absolute path.

## Cause

The broker intentionally uploads checked-out tracked files plus untracked, non-ignored files (`plan_upload`). On return, unchanged uploaded files never enter `SyncResult.changed`, so `commit_sync` correctly commits only outputs. Merge's `_clean_worktree_error`, however, refused every untracked file. Thus an input-only upload could complete and commit its outputs but could never pass merge preflight. This was a structured refusal before the commit point, not a merge exception. The supplied live trace reported 994 untracked originals; no live worker, live repository, raw originals or owner-provided assertion results were accessed or independently verified here.

## Mechanism

Use the existing broker-owned workspace JSON, outside Git, as provenance. An optional `input_manifest` freezes the exact paths and SHA-256 values of upload-origin files absent from the Git index, excluding known hub-made outputs. It is independent of the mutable upload/sync manifest, so refreshing an upload cannot authorize an edited original. No directory exemptions, ignores, raw-input commits, project-specific names, external API or new service are introduced.

Before merge, verify all registered inputs are still regular, direct files with the original bytes; missing, changed and symlinked originals refuse even when Git status omits them. Inspect both worker and target trees for exact, ancestor and descendant path collisions before the worker's existing `reset --hard`. Only the exact `??` status entries covered by validated provenance are allowed. Tracked modifications, staged additions/modifications and unrelated/new untracked output files retain the ordinary refusal. Target cleanliness, identity pinning, publication scan, diff budget and task lifecycle remain on their existing paths.

Sync-back treats these originals as read-only: hub modifications, deletion attempts and colliding output paths are rejected while valid sibling outputs remain importable and committable. Merge still squashes only Git objects. Local original bytes are preserved by merge/reset and by post-merge cleanup (which already refuses a worktree containing untracked originals). Hub release deletes the existing remote workspace/state, not the local original files. The next turn creates its normal fresh workspace and uploads the original local files through the same security checks.

## Existing workers and recovery

Missing `input_manifest` means the pre-upgrade schema. On the first merge, upload refresh or sync-back, derive the map from the existing manifest minus index-tracked and `hub_made` paths. Migration before an upload refresh prevents replacing the evidence first; merge persists it without requiring a new provider turn. Existing unchanged untracked originals therefore need no Git commit, ignore change, file deletion, worker replacement or new external command. A state without provenance does not exempt arbitrary untracked files.

Legacy provenance can establish the bytes in the last recorded upload/sync manifest, not reconstruct an earlier original if old code had already refreshed or imported it before this upgrade. No history beyond existing metadata is invented. Previously committed raw inputs likewise cannot be distinguished from ordinary tracked files solely from a legacy record. Newly created local files after a workspace's initial capture receive no automatic exemption on an incremental upload; finish/commit outputs or establish a fresh workspace for a new input set. Multiple surviving records with contradictory input fingerprints refuse conservatively.

## Validation

Actual results and exact commands are recorded below. All new fixtures are synthetic. Provisioned uv 0.11.28 is used with the existing frozen lock and default `.venv`. Test scratch files live below this task directory and are removed before delivery. No model review, real provider CLI, deployment, restart or production database is used.

The initial focused run found an incomplete cleanup transport stub: it attempted a request to the synthetic `http://x` test endpoint and failed with ConnectError. The stub was corrected to use the in-memory fake client throughout cleanup. This was not a live-service check. Initial output is retained as `targeted.txt`; final verification is recorded separately.

## Delivery and deployment limits

Changes are made in place in the provided private hub copy. It contains no Git metadata/remotes; commit/push/merge of the delivery is left to the platform as instructed. Changed code on disk does not change the running broker. The fix becomes available when the orchestrator imports it and the normal authorized service lifecycle loads the new Python. No restart or deployment was attempted, and the reported Seedon operation was not retried here. No changes were made in Seedon and no real raw inputs were deleted, published or committed.

## Further lifecycle finding

A real `execute_merge_session(..., merge_schema_version=2, task_outcome="continue")` test exposed the second refusal: `apply_merge_finalization` calls `switch_worktree_branch`, whose separate strict dirty check quarantined the successfully merged worker with `needs_switch=1`. The fix applies the same exact-path/hash provenance and tree-collision checks to branch switching and its final/rollback status checks. Existing branch ownership, force semantics and rollback rules remain intact. The full test checks the task binding, `needs_switch=0`, hub cleanup and subsequent upload using the real Git and task finalization paths.

Rejected hub rewrites/deletions now invalidate only the mutable remote baseline for that exact input, causing the next normal upload to resend the preserved local original. The immutable input fingerprint remains. The existing truncated-snapshot heuristic still counts all missing files, including protected inputs, so read-only input preservation does not authorize otherwise suspicious output deletions.

Legacy migration waits for a clean index, rather than freezing a staged original as "already tracked" and losing its exemption permanently. Staging refuses; unstaging and retrying recovers. The optional state field is appended after the existing dataclass fields to preserve positional caller compatibility.

## Verification environment limitations

The first complete relevant run (`regression.txt`) executed all requested selected files without exclusions: **404 passed, 3 failed** in 320.63 s. Two failures (`test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools`, `test_hub_prompt_has_no_outbox_section_when_nothing_can_run_it`) require `.orchestra/pipelines/default/prompts/hub/worker.md`; the supplied copy has no `.orchestra/pipelines/default/prompts/` directory. `hub_preamble` therefore takes its existing generic fallback. That template was not invented or copied from outside the authorized directory.

`TestCreateWorktree.test_different_repos_no_collision` fails because the unchanged `_slugify` truncates an absolute repository path to its first 80 characters, and the authorized task-local TMPDIR is already longer than that before the fixture's `repo`/`other-repo` suffix. Both synthetic repositories therefore get the same slug. The task prohibits temporary files outside this copy. No unrelated worktree-naming change or test weakening was made to conceal this existing path-length issue. The runner is present and imports work; these are copied-source/environment limitations rather than a missing uv runner.

A complete repository test run is not claimed. No native Git diff/commit is available in the no-.git delivery copy; changed sections and synthetic repository behavior were reviewed directly. The platform owns the final diff and delivery commit.

## Budget and path-alias boundaries

The existing merge budget also counted untracked input lines. Seedon's task-directory inputs were already classified as evidence by that budget, but generic input locations could still hit the 2,000-line ceiling. Merge now validates provenance before measurement and passes only those exact paths to the budget's optional internal input set. Committed/staged output diffs are never excluded, no budget is waived, and all existing WIP callers retain their original default of counting every untracked file. A 2,500-line synthetic input plus one committed output line checks the default WIP count (2,501), successful merge count (1), and no waiver.

Sync-back also checks the resolved destination before writes/deletions. This closes an alias through a local parent symlink and an older sync manifest that could otherwise make an output path overwrite or delete an original under a different name. Exact, ancestor and descendant collisions remain checked lexically too. Synthetic write/delete alias cases cover this boundary without real personal data.

## Recorded commands

Each test shell exports:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1062/tmp"
```

All executions use `nice -n 15`; checks run sequentially. The initial full selected run used:

```sh
uv run --frozen python -m pytest tests/test_hub_inputs_v1062.py tests/test_hub_workspace.py tests/test_backend_hub.py tests/test_workspace.py tests/test_merge_operations.py tests/test_merge_worker_v1034.py tests/test_merge_worker_lifecycle_702.py tests/test_merge_branch_drift.py tests/test_merge_recovery_wedge.py -q
```

The focused acceptance run (`acceptance.txt`) before the final budget/alias additions passed **36 tests**. The separate budget run (`budget.txt`) passed **6 tests**, including the existing diff-budget tests. Earlier intermediate focused logs contain fixture-development failures; they do not replace final acceptance evidence. In particular, the complete continuation test uncovered and then covered the real branch-switch blocker, rather than dropping its assertion.

The mutation command is:

```sh
uv run --frozen python .orchestra/tasks/V-1062/mutation_check.py
```

It invokes the same versioned uv/frozen pytest runner for each mutant and restores source in `finally`. One mutant reinstates the original blanket untracked refusal; the other removes the immutable input digest comparison. Expected evidence is a behavioral assertion failure in each case, not import/setup failure. Individual raw outputs and the summary are stored alongside this report.

## Supported workflow

Keep non-publishable originals untracked and non-ignored in the worker's selected upload scope. The first successful upload establishes their read-only fingerprints; already-live workers use their existing upload record. The remote worker writes derived outputs at distinct paths. Normal sync-back commits only imported output changes. A local caller committing output manually must select output paths explicitly; staging originals is refused, not silently repaired.

Use the ordinary `merge_worker` acceptance/current-HEAD flow with `task_outcome="continue"`. The task retains its binding, the same input map protects branch continuation, remote release leaves local originals intact, and the next turn uploads them again through the unchanged upload validator. Restore the uploaded bytes after an accidental local edit; unstage an accidentally staged original before retrying. A previously failed operation stays terminal: after the new Python is loaded, use the normal new merge operation against the current worker HEAD. This task does not retry the live operation.


## Final verification result

Final command (same PATH/TMPDIR exports as above):

```sh
nice -n 15 uv run --frozen python -m pytest tests/test_hub_inputs_v1062.py tests/test_hub_workspace.py tests/test_backend_hub.py tests/test_workspace.py tests/test_merge_operations.py tests/test_merge_worker_v1034.py tests/test_merge_worker_lifecycle_702.py tests/test_merge_branch_drift.py tests/test_merge_recovery_wedge.py tests/test_diff_budget.py -q --tb=short
```

**424 passed, 3 failed, 2 warnings in 382.79 s.** All **39 V-1062 regressions passed** in that run. The same three copied-source/path-length failures listed above remain, with no exclusions or supplied-test edits. The two warnings are Python's existing multiprocessing fork-from-thread warning in merge-operation arbitration tests. Complete output: `regression-final.txt`.

**Mutation result: 2/2 killed by behavioral assertions.** The check command exited 0; each mutant's pytest invocation exited 1 with the intended assertion failure. Restored source was used for the final regression run. Outputs: `mutation-summary.txt`, `mutation-original_dirty_refusal.txt`, `mutation-ignore_input_digest.txt`.

Imported `app`: `/remote/workspace/app/__init__.py`. No alternate interpreter run is presented as the frozen-uv check. Static AST/whitespace checks and reviewed source fingerprints are in `static-review.txt`.

Remaining checks: the full repository suite and the three blocked cases in a complete checkout/shorter scratch environment; actual live worker acceptance after the normal service lifecycle loads this code. No live validation, deployment/restart, personal-data fixture or model review was performed. The broker's general pre-existing recovery/branch-ownership rules were preserved. CHANGELOG was updated.

Publication-boundary artifact audit: no redactions were needed, zero credential-shape findings in reviewed source, all six reviewed source hashes unchanged after final tests. Only task-owned synthetic scratch was removed. Evidence: `artifact-audit.txt`.

## Delivery follow-up requested by the orchestrator

All task artifacts were checked for the remote installation prefix and account-derived labels. Only those identifying prefixes/labels were neutralized; production source was unchanged. Historical run results above remain as actually recorded before this follow-up. The single specified test now checks absent outbox and delivered task text without asserting the exact git-instruction sentence. No other test assertion was changed. The host owns the dispatched 427-test run; no broad suite is rerun here.

Follow-up validation: the provisioned uv command `uv run --frozen python -m pytest tests/test_hub_workspace.py::test_hub_prompt_has_no_outbox_section_when_nothing_can_run_it -q` passed **1 test in 4.73 s** (`delivery-followup-test.txt`). Production source fingerprints remain unchanged (4/4); the other prompt-sentence assertion and all unrelated tests were retained. No broad suite, provider run or restart was launched. The original 424/3 result remains historical evidence from before this one-assertion delivery correction.

Delivery HEAD is assigned by the platform when it imports/commits this private copy; there is no `.git` here and that post-turn SHA cannot be read or fabricated by this worker. The orchestrator must report the imported branch HEAD from its host repository. Concise diff: neutralize remote installation/account prefixes in task artifacts, label redacted evidence, and remove only the specified exact-sentence assertion while retaining absent-outbox and task-delivery checks.

## Host acceptance — 2026-10-23

All 427 selected hub/workspace/merge/continuation/diff-budget tests passed on the VPS in 59.58 seconds. Imported app: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-hub-inputs/app/__init__.py`. My own two mutations each failed a committed behavioral test: restoring blanket dirty refusal; removing the input digest comparison. Source bytes were restored in finally. Detailed host logs are retained privately at `.orchestra/private/V-1062/host-tests.txt` and `host-mutation-*.txt`; they are not public fixtures. The follow-up changed no production source. The normal merge test and mutation gates also passed. No model review ran under the owner freeze.

Read-only check of the reported live worker metadata: one matching workspace record; all 994 untracked files were covered by its manifest, all 994 hashes matched, no unaccounted files. This verifies availability of migration provenance, not the actual live merge. No real originals were modified.

Merged into main. Pending: running Python must load the change via the existing authorized idle-restart watcher; then Seedon must verify a new merge operation against its current worker HEAD. Do not equate this merge with live restoration.

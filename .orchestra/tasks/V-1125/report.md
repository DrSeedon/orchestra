# V-1125 — follow-up inputs after hub merge/continue

## Result and established cause

Implemented in this worker copy; activation and full host validation remain with the parent.
No deployment, restart, service/environment change, real hub/model request, paid fallback,
reporter-project access, commit or push of task changes was performed. Git commits occurred only
in the synthetic local test repositories; the platform commits the worker result after DONE.

The synthetic reproduction establishes a stale **local worker checkout** as a sufficient cause.
It does not prove which state existed in the reporter's installation; no private evidence was used.
The delta algorithm already sends new checked-out paths correctly.

Current source contract traced:

1. `workspace.merge_worktree_to_main` resets the worker branch to the target snapshot at the
   successful merge, via `_reset_worktree_to_ref`.
2. `tm.prepare_merge_finalization` / `routes.sessions.apply_merge_finalization` keep the same
   task branch and `needs_switch=False` for schema-2 `continue`.
3. `SessionManager._auto_switch_before_delivery` returns when no switch is required. Neither
   that path nor the ordinary session/backend construction updates the branch for later base commits.
4. `HubBackend._run_turn` really does call `plan_upload` and `_provision` every turn.
   `prepare_scope`, `_git_files` and `plan_upload` inspect the worker's HEAD/index/disk, not a newer
   base tree. A new directory committed only on main is absent from that source. `local_delta`
   consequently has nothing new to send. Unchanged ownership of its existing parent does not help.
5. Separately, `_clean_worktree_after_merge` released the hub workspace for `continue`, removing
   the saved copy, provenance and thread history. Recreating a remote copy from the same stale
   local checkout cannot supply the new inputs.

## Exact offline reproduction and observed output

`tests/test_hub_followup_v1125.py` creates a local source-only Git repository (README and
`task/seed.txt`, no project `.orchestra`), linked worker worktree, isolated SQLite/task store,
and existing local fake SSH/MCP transport. It performs a first real hub backend turn and
`execute_merge_session(... merge_schema_version=2, task_outcome='continue')` with real Git merge,
checks preserved task binding and equality of worker/target HEAD, then commits 41 public synthetic
files under unchanged ownership `['task']`, at `task/new-inputs/public-00.txt` through `public-40.txt`.
The payload is 75,600 bytes per file, 3,099,600 bytes total, below the existing limits. The resumed
backend reads actual remote file bytes in its fake provider callback. No model is called.

Before changing production code, the two reproduction tests ran through the provisioned uv:

```
FAILED test_continue_cleanup_keeps_workspace_and_history
FAILED test_followup_refreshes_local_source_before_remote_delta
AssertionError: expected 41 files, got 0
2 failed in 9.03s
```

The cleanup test failed because its saved workspace record was removed. The source test explicitly
retained that record to isolate source freshness from remote release. It started the next turn
successfully with zero of the 41 new inputs, reproducing the silent failure independently of cleanup.
`before.txt` contains the explicitly marked, sanitized synthetic pytest output; its original-byte hash is recorded in `publication-audit.json`. The first test-fixture setup attempt used
an ordinary async fixture in strict mode and failed before reproduction; it was corrected to
`pytest_asyncio.fixture` without changing acceptance expectations.

After the first correction, the same two tests passed (`2 passed in 11.12s`). With the remote WIP
check added, the expanded first set passed (`17 passed in 37.62s`, `followup.txt`). These tests compare
all expected file bytes, branch identity and same workspace/thread use, including `t3_thread_send`
instead of a replacement launch.

The test enters at the backend after the accepted follow-up; the HTTP QUEUED receipt path and
provider quota admission are not replaced or simulated as freshness evidence. Existing queue,
message and ownership policies remain in their owners.

## Changed symbols

- `hub_outbox.Identity.base_branch`: optional internal identity field; default empty preserves
  direct/older bridge callers. No outbox API payload or prompt contract changed.
- `AgentSession._hub_bridge`: supplies `self.base_branch` through the existing live identity
  callback, like `branch`. This is the only `app/session.py` overlap with colleague V-1121;
  quota/admission code was neither changed nor reviewed as part of this task. `app/manager.py`
  is unchanged.
- `hub_workspace.refresh_source`: under the existing repository mutation lock, verifies worker
  branch, local declared-base ref and absence of active Git operations. An already-contained base
  leaves committed worker work alone. A clean behind-only worker fast-forwards to the pinned base
  SHA, using `--ff-only --no-overwrite-ignore`; divergence and WIP refuse explicitly. Existing
  `merge_inputs` and `_clean_worktree_error` validate frozen input hashes, index/WIP and target
  collisions. No stash/reset/rebase, branch rebinding, checkout from an unrelated root or fallback.
  Plain directories keep their prior behavior; broken Git metadata does not acquire that exemption.
- `HubBackend._run_turn`: invokes source refresh from the live worker binding before planning
  each upload. Ownership and all ordinary upload planning/data checks are retained.
- `hub_workspace.check_refresh` / `HubBackend._provision`: before a nonempty retained-copy delta,
  inspect the existing bounded return archive without applying it. Refuse remote WIP, deletions
  conflicting with new local versions, path obstructions and nonregular files before any upload
  or provider start. Old baseline or already delivered desired bytes allow idempotent retry.
  Existing immutable-input restoration remains allowed only for its exact original digest.
- `merge_operations._clean_worktree_after_merge`: schema-2 continue with a retained hub state
  skips disposal of both copies and history/provenance. Ordinary non-hub and completion cleanup
  keep their prior paths.
- `tests/test_hub_followup_v1125.py`: new behavioral regression tests; no supplied acceptance
  tests, model review or existing tests were weakened.
- `CHANGELOG.md`: user-visible entry and activation note.

## Validation

Runner in every test shell:

```
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1125/tmp"
uv run --frozen python -m pytest <paths> -q [ -n 2 ]
```

Verified actual runner output: `uv 0.11.28 (x86_64-unknown-linux-gnu)`.
Imported module, rendered relative to the repository for publication: `app/__init__.py`.
The original check used `uv run --frozen python -c 'import app; print(app.__file__)'`;
its absolute deployment path is intentionally omitted from the public result. A follow-up
check resolved `app.__file__` against the current repository root and verified the same relative path.
Default `.venv`, unchanged `uv.lock`, normal `tests/conftest.py`; tests themselves are offline.
TMPDIR is task-local so even conftest's temporary directories stay inside the worker copy.

Completed intermediate adjacent run (`targeted.txt`):

```
uv run --frozen python -m pytest tests/test_hub_followup_v1125.py tests/test_hub_workspace.py tests/test_hub_inputs_v1062.py tests/test_hub_inputs_v1063.py -q
1 failed, 213 passed in 147.31s
```

The failure is `test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools`: this copied source lacks
`.orchestra/pipelines/default/prompts/hub/worker.md`, so `hub_preamble` uses its existing fallback
and the original test cannot find its expected role text. No template was fabricated and no test
was skipped or weakened. The host must recheck this with the real copied dependency present.

Expanded adjacent run before the final cleanup-scope refinement (`final-targeted.txt`):

```
uv run --frozen python -m pytest tests/test_hub_followup_v1125.py tests/test_hub_workspace.py tests/test_hub_inputs_v1062.py tests/test_hub_inputs_v1063.py tests/test_hub_file_policy_v1073.py tests/test_hub_clean_start_v1083.py tests/test_hub_inputs_v1063.py tests/test_hub_message_v1066.py tests/test_worktree_cleanup_v1072.py tests/test_hub_uv.py -q -n 2
1 failed, 392 passed in 281.67s
```

The sole failure is the same missing-template test described above. The repeated v1063 argument
is shown exactly as invoked; it does not represent additional coverage.

Transport/backend/recovery run (`recovery.txt`):

```
uv run --frozen python -m pytest tests/test_hub_followup_v1125.py tests/test_hub_download_v1064.py tests/test_backend_hub.py -q -n 2
75 passed in 160.87s
```

Final focused run after limiting cleanup retention specifically to existing hub states
(`final-followup.txt`), including the ordinary-worker cleanup control:

```
uv run --frozen python -m pytest tests/test_hub_followup_v1125.py tests/test_worktree_cleanup_v1072.py -q -n 2
43 passed in 246.31s
```

This comprises all 22 new V-1125 cases and 21 existing cleanup cases. No debug prints or TODOs
were added. Modified blocks and test coverage were reviewed in place. Credential-shape scanning
of the changed source files and task reports/logs found no matches. Generated synthetic Git
repositories and temporary test files were removed from the task notes after the runners exited;
only this report, small pytest logs (with explicit publication-edit markers where needed)
and the publication audit remain.

## Safety, recovery and remaining limits

Coverage includes real input contents, unchanged owned dirs, retained history, persisted-state
reconnect, non-main live base selection, local tracked/staged/untracked WIP, ignored target
collisions, diverging committed work, active Git operations and changed branch binding; immutable
inputs surviving refresh or refusing edits/collisions; remote WIP/missing paths/symlinks and recovery
after explicit reconciliation; retry after lost upload acknowledgement; ownership/private-file
exclusions and total-upload limit refusal/retry. Existing hub, provenance, policy, transport,
message and cleanup tests provide adjacent coverage.

A retained-copy delta now needs one extra existing bounded return-archive read. No upload budget,
secret/data policy, download cap or input provenance exemption was relaxed. The check assumes the
normal single idle thread ownership of the remote copy; it is not a filesystem transaction against
an unrelated actor editing remote files between the read and upload. Existing per-worker turn and
repository locks remain the concurrency owners. A diverged local branch is refused rather than
automatically reconciled, even if a merge might be conflict-free. Upload-limit or remote-WIP failure
may leave the local branch safely advanced; retry continues from there without deleting remote work.

Activation requires the ordinary owner-controlled idle watcher/service lifecycle for these Python
changes and construction/reconnection of the backend with the new live base binding. No activation
was attempted. Existing persisted workspace schema needs no migration or thread reset; retained
records resume. A workspace/history already removed by old cleanup is not reconstructed, and lost
input provenance is not invented. The next safe fresh upload can work from a clean fast-forwardable
checkout; dirty originals without provenance require explicit reconciliation.

The full required `uv run --frozen python scripts/run_tests.py` is reserved for the host parent after
DONE, as requested. This private copy has no Git history, so historical symbol provenance and a
repository-wide Git diff cannot be independently checked here; changed blocks were reviewed in
place. No real hub, deployed process, concurrent external editor or private reporter artifact was
used as validation.


## Publication correction and audit

The original credential-shape-only scan missed deployment-identifying absolute paths. The
public report now identifies the imported module as repo-relative `app/__init__.py`, while
retaining the verification method and all test/activation limitations. No new production code
or tests were changed for this correction. In particular, the V-1121 integration in main is
not rolled back; the existing V-1125 `_hub_bridge` change is left intact for parent integration.

Three pytest logs contained private absolute paths or generated test-directory names encoding
those identities. Each edited log now starts with an explicit EDITED FOR PUBLICATION marker,
the SHA-256 of the original stdout bytes, and a statement that verdicts/timings are unchanged.
Other stdout logs remain byte-for-byte unchanged. Private original bytes are not retained in
the public deliverable; their hashes alone cannot reconstruct them. The parent has stated
that it will preserve the turn1 stdout from host Git in private evidence before merge. This is a limitation of
public evidence, not a claim that sanitized logs are raw stdout. Historical CHANGELOG entries are restored byte-for-byte to turn1, as requested;
only the new V-1125 entry remains relative to the task baseline. The restored document
matches the SHA-256 recorded before the publication correction. The historical lines were
recovered by a read-only public upstream lookup and accepted only when the complete
restored file matched that pre-existing hash. No historical path cleanup is part of V-1125.

`publication-audit.json` lists every changed source/document/task artifact available in this
Git-less worker copy, the log provenance hashes, unchanged-source hashes and audit categories.
The audit covers deployment-specific names/roots and generic absolute host-root patterns in
addition to credential shapes. Generic illustrative paths and loopback defaults in unchanged
source sections are classified separately from private deployment identities. Its zero-new-identity
result applies to V-1125 additions and task artifacts, not to the entire historical CHANGELOG.
The historical body was inspected and retained unchanged by the requested scope; it is not
claimed to contain zero absolute paths. The audit records the exact turn1 restoration hash. With no Git
metadata here, the parent must check the actual tracked diff/publication set after integration;
this worker does not claim an independently verified Git index inventory. No test rerun was
needed for these documentation-only follow-ups; production/test sources and the marked safe
stdout versions remain unchanged in this final correction; earlier results and the pending full host
runner remain as stated above. No live hub/model/paid call was made.

## Host acceptance after integration

The parent read the complete report, publication audit and final diff, then integrated the already accepted local Codex quota gate without conflicts. The required host `uv run --frozen python scripts/run_tests.py` completed: **6675 passed, 54 skipped**, 428.94 seconds. Real ownership checks unavailable without passwordless sudo remain explicit skips. The instruction contract passed; the actual imported module resolves to `app/__init__.py` in this task's complete host worktree.

Independent in-memory mutations against committed regressions each failed for the intended reason: disabling source refresh produced zero of the expected synthetic input files; restoring old continue cleanup removed persisted workspace/history; bypassing remote conflict checking allowed an unsynced rewrite to proceed. No source files were changed for these mutations. Generated test screenshots were preserved privately and restored.

All changed files passed secret-form, forbidden-string and private deployment-identity checks. Published log hashes match the audit; the three original worker stdout files were recovered from the initial host Git result and preserved privately with matching original hashes. Historical CHANGELOG edits are absent from the final diff. The result was accepted and merged, with a clean executor worktree; the temporary hub worker was archived. Model review remains frozen by owner policy.

Python activation is still pending the authorized idle watcher. Publication and remote CI are separate delivery checks; no manual restart, live provider request or reporter-project modification occurred.

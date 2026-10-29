# V-1129: optional hub source refresh and same-task continuation

## Change and operation boundaries

`app/hub_workspace.py::refresh_source` distinguishes an optional optimization
that cannot apply from an actual source/overwrite failure. A verified divergence
(both ancestry probes return 1) or verified dirty status skips the fast-forward.
The existing `app/backend_hub.py` status path already emits the returned note
before planning/uploading from the unchanged worker checkout; it needs no edit.
The note says `source refresh skipped`, `working on existing branch`, and
`base inputs not refreshed`. There is no promise that new base inputs arrived.

Input provenance is validated against the actual worker HEAD before permitting
a skip. Target-tree input collisions are checked when attempting the fast-forward,
because only that operation would install the target tree. A frozen input that
changed, disappeared, or became tracked in worker HEAD still refuses. A collision
only in the skipped base does not make the unchanged worker source unsafe.

The repository writer lock covers binding, operation/ancestry/status inspection,
and fast-forward. Missing/mismatched/detached bindings, invalid Git metadata,
uninspectable ancestry/status, active merge/cherry-pick/revert/rebase, and failed
fast-forwards remain errors. Git exit 1 from an ancestry predicate means false;
other exit codes and unavailable command results do not become skips.

Dirty tracked/staged/untracked paths are retained instead of reconciled. An
ignored obstruction invisible to ordinary status still makes an attempted
`--no-overwrite-ignore` fast-forward fail before upload. Upload size, ownership,
private-file, immutable-input and remote-baseline checks keep their owners and
remain mandatory after a skip. No merge/rebase/reset/stash or quota changes.

`CHANGELOG.md` adds the scoped V-1129 entry and corrects only the obsolete
divergence/WIP tradeoff in V-1125. `tests/test_hub_followup_v1125.py` replaces
that refusal expectation with explicit continuation and preservation assertions.

## Reproduction and checks

All provider/SSH interactions use the existing offline fake hub. Tests create
real local Git repositories/worktrees and actual local remote-copy directories,
and run production upload archives, refresh, sync-back, and commit paths. No
reporter-project data, model call, live hub, deploy, service action, or push.

The new regression cases on the unchanged production function failed as expected:
`before.log`: **6 failed, 18 deselected**, 24.19 s. These are two ready-unmerged
follow-ups (existing and reconnected backend) and four dirty-source variants.
The first post-fix run (`after.log`) passed the ready-unmerged cases and all
existing guards. Its four failures were a fixture expectation omitting the
already authorized public root README from remote contents; the assertion now
compares the complete local source snapshot, including README.

The reproduction starts with an initial hub turn producing one clean, unmerged
worker commit, independently advances main with new inputs and a conflicting
seed edit, then requests CHANGELOG in the same task. It verifies that the
provider sees the worker's original bytes and no new base inputs; source
branch/HEAD/index/status/refs/reflog/files match the snapshot before the follow-up
output; CHANGELOG sync-back produces a single-parent child of the ready commit;
the same workspace/thread and frozen provenance are retained. Reconnection is
included. Dirty-source cases preserve mixed staged/unstaged contents, untracked
files, and staged renames through a completed turn.

Additional negative cases cover all existing operation markers, branch mismatch,
detached HEAD, a real malformed Git index, missing base, ancestry command errors
and unavailable results, frozen-input changes/deletion/HEAD collision, ignored
overwrite obstruction, and remote WIP conflict/recovery after a skipped refresh.
The lock test holds the actual repository lock, observes the refresh reach its
acquisition point, proves identity inspection has not entered, releases the lock,
and verifies the clean-behind fast-forward completes. Existing V-1125 cases
verify all 41 new committed input files reach the hub, upload retries, limits,
private/unowned exclusions, and explicit continue cleanup/history retention.

Runner: provisioned uv **0.11.28**, `uv run --frozen`, default `.venv`, ordinary
`tests/conftest.py`. Temporary test data is directed inside this task directory.
The imported `app` must resolve to this copy's `app/__init__.py` (checked separately
without publishing the copy's absolute path). Logs are sanitized to relative
paths before handoff; no actual hub hostname, account ID, or root path is evidence.

Final results:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1129/tmp"
uv run --frozen python -m pytest tests/test_hub_followup_v1125.py -q
uv run --frozen python -m pytest tests/test_hub_workspace.py tests/test_backend_hub.py tests/test_hub_inputs_v1062.py tests/test_hub_inputs_v1063.py tests/test_hub_file_policy_v1073.py tests/test_hub_clean_start_v1083.py -q
```

- `followup.log`: **43 passed**, 150.22 s; required normal-conftest target passed.
- `related.log`: **326 passed, 1 failed**, 128.76 s. The failure is
  `tests/test_hub_workspace.py::test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools`.
  After its hub turn/prompt assertions, it requests the full native worker prompt
  through `ROLE_SYSTEM_PROMPT("default", "worker")`. This copy was not supplied
  `.orchestra/pipelines/default/pipeline.yaml`; `app/pipeline.py:474` raises
  `FileNotFoundError`, re-raised by `app/manager.py:294` as `ValueError`. This is a
  missing copied source dependency, not a missing runner. No substitute runner,
  synthetic pipeline, conftest bypass, deselection, or relaxed expectation was used.
  The full-pipeline comparison remains unverified until run in the parent copy
  with its real pipeline and prompt inputs.

`changes.patch` contains explicit raw edits to exactly three existing source
files: `app/hub_workspace.py`, `tests/test_hub_followup_v1125.py`, and
`CHANGELOG.md`. It is a relative-path patch reconstructed from the supplied
pre-edit text because this copy has no `.git`. No quota/routing file was edited.
Temporary repositories and dependency/runtime caches are not task evidence.
The task-owned temporary repositories were removed after the runs. A final
credential-shape scan (without reading credential inventories) and host/account
path check passed for the retained evidence files. Source hashes match
`source-sha256.json`; `git apply --check --reverse` accepts `changes.patch`
against the edited files. This was a read-only patch check in the Git-less copy.

## Remaining acceptance

Full host suite and parent mutation checks are intentionally left to the parent
after DONE, as requested. Real hub service/provider behavior is not exercised.
The Python code on disk requires the existing idle-watcher lifecycle to become
active; this worker does not deploy or restart anything. A skipped refresh keeps
the existing base inputs until an explicitly reconciled branch can safely advance.

## Host acceptance

The parent read the entire report and actual diff, verified the source hashes and publication scan, and ran the complete host follow-up module: **43 passed**, 37.47 s. An independent in-memory mutation restoring the previous `refresh_source` makes the six committed ready-unmerged/dirty-source regression cases fail. Required validation on the branch integrated with accepted V-1128: **6789 passed, 54 skipped**, 437.16 s; instruction contract passed, actual `app` import was from this complete task worktree. Missing real ownership prerequisites remain explicit skips. Generated test screenshots were retained privately and restored.

The correction was accepted and merged; its clean temporary hub worker was immediately archived. No runtime code was changed outside the task branch, and no reporter-project data or services were touched. Publication/CI and activation through the authorized idle watcher remain separate delivery steps; no manual restart was performed.

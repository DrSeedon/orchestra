# V-1072 — post-merge cleanup racing worker removal

## Scope and findings

The supplied incident identifies one confirmed cause: after a successful merge and
worker removal, post-merge cleanup attempts to start Git with a vanished worktree
as its current directory. The historical event count is not evidence that every
event had this cause. This copy has no host journal or source Git metadata; neither
the journal nor the supplied base revision was independently inspected here.

Current code confirms the ordering: `_run_operation` persists the terminal result
with `finish_operation` before awaiting `_clean_worktree_after_merge`. A caller can
therefore observe success and remove the worker while cleanup is pending. Both
`workspace._resolve_repo` and `worktree_cleanup._refusal` start Git inside that
directory and can raise `FileNotFoundError`. An existence check before Git would
leave the same race open.

The fix belongs to the optional post-merge lifecycle boundary. `clean_worktree`
continues to enforce its existing strict inspection and deletion policy, including
for other callers. No new deletion, source-input exemption or broad ignore rule
was introduced.

## Changes

- `app/merge_operations.py`: when optional cleanup raises `FileNotFoundError`,
  inspect the exact recorded worktree root using `Path.stat()`. Only another
  `FileNotFoundError` confirming absence turns the operation into an INFO-level
  `state=skipped reason=removed`. Existing roots retain the original error log.
  An unsuccessful verification, including permission failures, also retains the
  original error and traceback. Initializing the local path before session lookup
  preserves error reporting when lookup itself fails.
- Hub release still runs first, even when the local directory has already gone.
  Its existing separate warning and traceback remain visible. No hub workspace
  lifecycle code was changed.
- `tests/test_worktree_cleanup_v1072.py`: behavioral regression coverage, with real
  local Git repositories and a bounded event-based concurrency fixture. No new
  tests assert diagnostic wording.
- `CHANGELOG.md`: Unreleased fix entry and normal Python service-lifecycle note.

No changes were made to `worktree_cleanup.py`, raw-input provenance, validation,
publication/security rules, noise classification, hub transport, model routing,
dependency declarations or the lockfile. No existing source file or root
instruction was removed or replaced.

## Regression coverage

The concurrency fixture pauses between a successful root stat and an actual Git
subprocess. Another execution context renames the fixture worktree, then releases
the paused call. This produces the real subprocess `FileNotFoundError` with its
`filename` equal to the original cwd, without sleep/poll loops or fixture data loss.
The preserved directory and the target checkout are compared byte-for-byte.

Covered cases:

- Missing root before repository resolution and before cleanup inspection.
- Root disappearance before repository `rev-parse`, first cleanup `status`, ignored
  file enumeration, blob hashing, and the final pre-delete `status` recheck.
- Successful cleanup of existing recoverable outputs; unique files, planted files,
  environments and the target checkout survive.
- Existing empty and non-repository directories remain refused and untouched.
- Existing-root missing executable and missing input exceptions, permission errors,
  and other cleanup failures retain ERROR logs and original exception identities.
  The missing executable case also exercises an actual failing subprocess launch.
- A missing individual candidate file with the root still present remains an
  actionable cleanup error. Unverifiable absence preserves the original exception.
- Session lookup errors before a worktree is known remain visible.
- A failed hub release remains visible even when local removal is normal.
- The operation-runner test performs a real fixture target merge, then pauses
  cleanup after terminal persistence. It verifies `SUCCEEDED`, `REACHED`, target
  HEAD and merged contents both while cleanup is paused and after either root
  removal or a genuine permission failure. The stored result is unchanged.

The existing V-984 tests retain coverage for dirty/untracked paths, active users
of the directory, open files, changes between planning/deletion, main-checkout
refusal, dry runs and recoverability. The selected hub tests cover unpublished
raw-input preservation, strict provenance, release and continuation/recovery.

## Commands and evidence

Every Python shell used the broker runner and the default `.venv`:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1072/tmp"
```

`uv --version` reported `uv 0.11.28 (x86_64-unknown-linux-gnu)`.
`uv run --frozen python -c 'import app; print(app.__file__)'` imported:

```text
/home/<private-identifier>/orchestra-ws/vmi3407579/hub-6649f1d461d54a7d/app/__init__.py
```

Runner evidence is saved in `runner.txt`.

Required full command attempted:

```sh
uv run --frozen python scripts/run_tests.py
```

Result: exit 2 because `scripts/run_tests.py` is absent from the supplied copy.
Actual output is saved in `full-suite.txt`. No alternative interpreter was used or
presented as the required full runner. The full suite remains unrun; the bounded
selection below covers both the changed entry point and the required neighboring
merge, cleanup and hub lifecycle/provenance protections.

Before the production fix, the initial 17-case regression selection ran with:

```sh
nice -n 15 uv run --frozen python -m pytest tests/test_worktree_cleanup_v1072.py -q --basetemp=.orchestra/tasks/V-1072/test-tmp -o cache_dir=.orchestra/tasks/V-1072/pytest-cache
```

Result: **8 failed, 9 passed in 9.25s**, exit 1. All eight failures are the expected
false cleanup error on confirmed root removal; negative controls passed. Actual
output is saved in `regression-before.txt`. One earlier fixture calibration run
also exposed that `is_symlink()` calls `stat(follow_symlinks=False)`; the missing
candidate fixture was corrected to inject at the direct content inspection, then
the recorded baseline above was rerun before changing production code.

After the fix, the initial regression file plus all V-984 tests ran with:

```sh
nice -n 15 uv run --frozen python -m pytest tests/test_worktree_cleanup_v1072.py tests/test_worktree_cleanup_v984.py -q --basetemp=.orchestra/tasks/V-1072/test-tmp -o cache_dir=.orchestra/tasks/V-1072/pytest-cache
```

Result: **27 passed in 12.10s**, exit 0; actual output is in `cleanup-after.txt`.
The final regression file subsequently added repository-resolution race,
successful existing cleanup, real missing-executable and early lookup controls.

Final bounded selection, sequential with nice 15 and a 2 GiB address-space limit:

```sh
ulimit -v 2097152
nice -n 15 uv run --frozen python -m pytest tests/test_worktree_cleanup*.py tests/test_merge_operations.py tests/test_merge_worker_lifecycle_702.py tests/test_merge_worker_v1034.py tests/test_hub_inputs_v1062.py tests/test_hub_inputs_v1063.py tests/test_hub_workspace.py tests/test_hub_download_v1064.py tests/test_hub_message_v1066.py tests/test_optional_worker_memory_v1069.py tests/test_backend_hub.py tests/test_hub_switch_orphan.py -q --basetemp=.orchestra/tasks/V-1072/test-tmp -o cache_dir=.orchestra/tasks/V-1072/pytest-cache
```

Result: **434 passed, 1 failed, 2 subtests passed in 155.31s**, exit 1. Actual output
is saved in `neighbors.txt`. All 21 final V-1072 cases, all 10 V-984 cases, and all
selected merge, raw-input provenance, workspace release/recovery, V-1062/1063/
1064/1066/V-1069 tests passed. The shell limit is an address-space bound, not a
claim that a systemd MemoryMax unit was provisioned.

The sole failure is the existing
`tests/test_hub_workspace.py::test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools`.
The copied source dependency
`.orchestra/pipelines/default/prompts/hub/worker.md` is missing. Unchanged
`backend_hub.hub_preamble` catches its read error and uses `PREAMBLE_BASE`, which
lacks the worker/branch substitution expected by that test. This is outside the
post-merge path. The missing template was not fabricated and the test was not
weakened or excluded from the reported selection.

This was independently reproduced in isolation with:

```sh
nice -n 15 uv run --frozen python -m pytest tests/test_hub_workspace.py::test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools -q --basetemp=.orchestra/tasks/V-1072/prompt-test-tmp -o cache_dir=.orchestra/tasks/V-1072/pytest-cache
```

Result: **1 failed in 3.41s**, exit 1, at the same template-dependent assertion;
actual output is in `prompt-isolated.txt`. A read-only Python check of the runner
and canonical `prompt_path(DEFAULT_PIPELINE, 'hub/worker.md')` recorded both as
absent in `missing-fixtures.txt`. Thus the full runner and this template-dependent
check still need the complete checkout; there is no claim of an all-green suite.

Final inspection checked the narrow production diff and new tests for accidental
edits, debug output and weakened guards. Test scratch directories were removed;
only the report and textual evidence remain in this task directory. A local
publication-shape and masking scan of the changed code and textual task artifacts
is recorded in `publication-scan.txt`; no live secret inventory is consulted.

## Limits and handoff

The fix deliberately keeps a conservative error if the root reappears before
verification or absence cannot be proved. Git returning a nonzero exit status
instead of raising an exception follows the existing refusal path. File-specific
unlink handling and all original safety guards remain unchanged.

Only fixture directories were renamed or cleaned. No live deletion, provider
call, SSH, service action, restart, deployment, external review or additional
worker was used. No source Git commit/push was attempted: the broker imports and
commits the result on `task-V-1072/fix-merge-cleanup-race`. Root remains responsible
for independent mutation/review, the full runner, merge, push and CI. This is a
code/test result, not a claim that running service processes have changed.

## Host publication boundary
Root preserved original worker evidence privately. Public report/stdout copies replace forbidden runtime identifiers with `<private-identifier>`; these copies are redacted, not verbatim originals. Production code and test evidence assertions are unchanged.

## Host acceptance
Host selection identical to the worker bounded command passed435tests and2subtests in35.89seconds, including the hub-template dependency absent remotely. app imported from /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-merge-cleanup-race/app/__init__.py. Independent in-memory restoration of old error behavior made all5committed removal-race cases fail; production source was never edited. Raw host output and mutation trace are retained privately under this task. Required full runner was not rerun on host; broad bounded neighbors cover changed boundary, final CI remains a publication check.

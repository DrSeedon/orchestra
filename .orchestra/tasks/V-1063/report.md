# V-1063 — hub CI regression repair

Redaction: all recorded workspace/HOME prefixes and the remote username are
replaced with `/remote/workspace`, `/remote/workspaces`, `/remote/home` and
`remote-user`; the encoded workspace slug becomes `remote-workspace`.
The absolute imported application path below is redacted this way.
No credentials or service state were read.

## Contract and changes

`plan_upload` / `_git_files` deliberately support ordinary directories without
Git. V-1062 added unconditional Git-index inspection before provisioning, so all
six plain-directory backend provisioning cases failed before reaching their
actual uv/upload checks. Non-Git copies now freeze `input_manifest={}`. They
remain uploadable and gain no merge exemptions, including after subsequent Git
initialization. Fresh and legacy records follow the same rule.

An unsuccessful Git repository probe only selects this fallback when no `.git`
marker exists at the resolved root or any ancestor. Broken directories, gitfiles
and dangling `.git` links still refuse provenance capture. Missing Git commands,
failed index inspection and staged legacy migrations remain failures with the
record unset, permitting retry. Git-backed provenance still excludes tracked
files and hub-made outputs and retains exact paths and SHA-256 values.

The publication mutation fixture's merge case used a partial `app` copy missing
`hub_workspace` and its transitive runtime dependencies. It now copies real app
dependencies for that case, as the existing hub-planning mutant already did.
Each unmodified control must pass before mutation; each mutant must fail an
assertion without unittest import/setup errors. Minimal hook-import cases retain
their intentionally small dependency set. Bytecode caches are cleared before
running mutants so same-size edits cannot reuse the control's cached source.
No production import bypass or mutation removal was added.

Changed source: `app/hub_workspace.py`,
`tests/test_publication_gate_v1047.py`, new `tests/test_hub_inputs_v1063.py`,
and `CHANGELOG.md`. Existing V-1062 acceptance tests were not edited.

## Verification

Every test shell used:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
```

The broker's real uv 0.11.28 created the default `.venv` from the unchanged lock.
The artifact runner applies `UV_OFFLINE=1` and keeps temporary test data within
this task directory. Test commands run at nice 15. No real provider, deployment,
restart or live-service call was made.

- Baseline: `uv run --frozen python -m pytest tests/test_hub_uv.py tests/test_publication_gate_v1047.py -q`
  — **7 failed, 49 passed, 18 subtests passed**. Reproduced exactly the six
  provisioning failures plus the merge mutant's import/setup failure.
  Full redacted output: [baseline.txt](baseline.txt).
- Focused: `uv run --frozen python -m pytest tests/test_hub_uv.py tests/test_publication_gate_v1047.py tests/test_hub_inputs_v1062.py tests/test_hub_inputs_v1063.py -q`
  — **104 passed, 19 subtests passed**.
  Full output: [focused.txt](focused.txt).
- Regression: `uv run --frozen python -m pytest tests/test_hub_workspace.py tests/test_backend_hub.py tests/test_workspace.py tests/test_diff_budget.py tests/test_diff_budget_recovery_702.py tests/test_merge_worker_v1034.py tests/test_merge_worker_lifecycle_702.py -q`
  — **338 passed, 1 failed**.
  Full output: [regression.txt](regression.txt).
  The failure is `TestCreateWorktree.test_different_repos_no_collision`: the long
  hub TMPDIR makes the two repositories' `_slugify(path)[:80]` values identical,
  so creating the second `worker-1` worktree raises `worktree already exists`.
  This is the separate, anticipated issue explicitly excluded from V-1063;
  `app/workspace.py`, that test, and the slug algorithm remain unchanged. The
  failing case is included in the reported run, without an exclusion or xfail.
- Own mutation check: `uv run --frozen python .orchestra/tasks/V-1063/mutations.py`
  — **all three mutants killed**, production source restored in `finally`.
  Removing non-Git support makes both fresh/legacy behavioral cases fail;
  granting the plain manifest as exemptions fails both empty-manifest assertions;
  bypassing the metadata check fails all four expected-refusal cases. No import
  or collection error substitutes for these failures.
  Full output: [mutations.txt](mutations.txt).
- Post-mutation restoration: `uv run --frozen python -m pytest tests/test_hub_inputs_v1063.py -q`
  — **10 passed**. See [restored.txt](restored.txt).
- Final source/artifact publication scan: `uv run --frozen python .orchestra/tasks/V-1063/validate.py`
  — canonical `scripts.secret_scan.scan_text` reports no credential shapes in any
  changed source or task artifact; all text artifacts also pass the private-prefix
  and username check. See [validation.txt](validation.txt).

The unchanged V-1062 oracle verifies input edits/deletions, staged or committed
inputs, ignored changes, symlinks and parent symlinks, exact input/output path
collisions, ordinary dirty outputs, publication refusal, insertion budgets,
legacy migration recovery, branch-switch rollback, merge/continue and restoring
rejected remote input changes on the next upload. New tests verify plain upload
enumeration, empty provenance persistence, later Git initialization, Git failure
recovery and broken metadata at both the root and an ancestor.

Environment: imported `app` is **`/remote/workspace/app/__init__.py`**, using
`/remote/workspace/.venv/bin/python3`; the executable is
`/remote/home/.local/share/orchestra/tools/uv/0.11.28/bin/uv`.
See [environment.txt](environment.txt).

## Delivery limits

This private hub copy has no Git metadata, remote or credentials. The platform
imports changed files and commits them on `task-V-1063/fix-ci-hub-1063` after the
turn. No local commit, import, push or main CI result is claimed. Service Python
has not been restarted; only the code and offline test behavior were verified.
The complete repository suite and subsequent main CI run were not executed here.
The separate long-path slug collision remains unresolved by explicit task scope.
Changed hunks were reviewed, and temporary test repositories and imported
bytecode caches under this task's artifact directory were removed before handoff.

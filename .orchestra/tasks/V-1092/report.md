# V-1092 — partial hub-return Git commit

Implementation complete in the supplied copy; host acceptance remains required.
There is no `.git` here, so local HEAD cannot be verified. The task names base
`18fabf018` and destination branch `task-V-1092/fix-hub-partial-commit`; the platform
owns the resulting commit. No repository commit/push, service change, provider
call or live database/auth read was performed. Git commits below exist only in
disposable synthetic test repositories under the ignored task-private directory.

## Proven cause and fix

`HubBackend._sync_back` passes `apply_changes`' changed/deleted file lists directly
to `hub_workspace.commit_sync`. The existing function first runs a batch
`git add -A --sparse`, then retries every file individually if the batch fails.
Real Git returns 1 for an ignored new path **after staging supported edits and
deletions**. Retrying a staged deletion returns 128 (`pathspec ... did not match
any files`): the file is now absent from both index and working tree. The fallback
incorrectly reports this delivery deletion as refused, excludes it from
`git commit --only`, and leaves it staged against the next HEAD.

The fix reads NUL-delimited staged deletions, restricted to the returned deletion
paths, after a batch failure. It retains those paths in the selected commit and
retries the remaining paths as before. Failure to inspect the index raises
`HubWorkspaceError` rather than silently constructing an incomplete commit.
The successful batch path, sparse support, ignored-file policy, author selection
and `commit --only` isolation are retained. No force-add or index reset was added.
Production AST outside `commit_sync` is unchanged, including import validation,
read-only input provenance, private-company-file guards and publication rules.

Changed deliverables: `app/hub_workspace.py`, `tests/test_hub_workspace.py`,
`CHANGELOG.md`, this report, task `.gitignore`, and the raw evidence manifest.
Existing tests were retained; two regression tests were added (13 cases total).

## Checks actually run

Every Python shell used the broker runner:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
```

`uv --version` stdout: `uv 0.11.28 (x86_64-unknown-linux-gnu)`.
Frozen setup created the default `.venv` and installed 76 locked packages. Neither
`uv.lock` nor `pyproject.toml` was changed; no alternative interpreter was used.

1. Required initial command:

   ```sh
   uv run --frozen python -m pytest tests/test_hub_workspace.py -q -k 'commit or unstageable' --basetemp=.orchestra/tasks/V-1092/private/pytest
   ```

   Exit 2; collection stopped at `ModuleNotFoundError: No module named 'app.hub_outbox'`.

2. Synthetic real-Git diagnostic (before the fix):

   ```sh
   uv run --frozen python .orchestra/tasks/V-1092/private/reproduce.py
   ```

   Raw stdout records batch add exit 1, index `M edit.txt` / `D old.txt`, individual
   deletion retry exit 128, then a commit containing only `M edit.txt` with
   `D old.txt` still in the index. The diagnostic script was subsequently adjusted
   to reset the synthetic index before calling `commit_sync`, allowing its direct
   reproduction to start from unstaged delivery changes. No application import or
   validation result is inferred from this function-level diagnostic.

3. Final regression red/green comparison, executing the exact AST nodes of the
   production function and the committed Git test functions, with real subprocess
   Git and no mocked Git behavior:

   ```sh
   HUB_SOURCE=.orchestra/tasks/V-1092/private/hub_workspace.before.py uv run --frozen python -m pytest .orchestra/tasks/V-1092/private/test_source_slice.py -q --basetemp=.orchestra/tasks/V-1092/private/pytest-original-final
   uv run --frozen python -m pytest .orchestra/tasks/V-1092/private/test_source_slice.py -q --basetemp=.orchestra/tasks/V-1092/private/pytest-fixed-final
   ```

   Original exit 1: **8 failed, 7 passed in 7.01s**.
   Fixed exit 0: **15 passed in 9.30s**.
   This is explicitly a source-slice fallback, **not** successful normal module
   imports or a substitute for the required application suite.

   Coverage: deletion-only and mixed tracked modification/addition/deletion;
   success, ignored-path refusal and disappeared-path refusal; fresh and already
   staged delivery deletions; a move with identical old/new content; exact one
   additional commit; absence of delivery residue from status/index; refused-only
   retry without another commit; ignored bytes preserved and untracked. Unrelated
   native staged additions, modifications and deletions, including differing
   staged/unstaged bytes, are compared as exact binary diffs before/after.
   Three existing tests additionally cover ordinary isolated commits, additions
   outside the sparse cone and mixed ignored/allowed modifications.

4. Required final command:

   ```sh
   uv run --frozen python -m pytest tests/test_hub_workspace.py tests/test_backend_hub.py -q --basetemp=.orchestra/tasks/V-1092/private/pytest-required-final
   ```

   Exit 2: **2 errors during collection in 0.90s**, both caused by the same missing
   `app.hub_outbox`. No application test result is claimed.

5. Offline final checks:

   ```sh
   uv run --frozen python .orchestra/tasks/V-1092/private/verify.py
   ```

   Syntax checks for both changed Python files; AST comparison confirms production
   changes are confined to `commit_sync`; exact credential-shape text-scanner
   rules/helpers from `scripts/secret_scan.py` check the five text deliverables.
   This does not claim the full publication guard ran.

   Exit 0, stdout (private path lines omitted here):

   ```text
   Imported app __file__: None
   Syntax: 2 Python files OK
   Production AST outside commit_sync: unchanged
   Exact credential-shape text scanner AST: 0 findings in 5 delivery files
   ```

   Reviewed the textual production diff against the preserved original. No
   source changes outside the selected function, tests and changelog were made.

## Import paths and remaining host acceptance

The imported `app` is a namespace package (`app.__file__` is `None`) whose absolute
search location is recorded verbatim in ignored `private/verification.log`.
The normal `app.hub_workspace` import fails at its first copied-source dependency;
there is no successful imported production-module path to report. The AST fallback
executes the supplied `<checkout>/app/hub_workspace.py`, using its actual absolute
filename in compilation. Exact absolute namespace, source and interpreter paths
are retained privately; public text substitutes `<checkout>` for the private
workspace prefix. SHA-256 and byte counts identify every retained raw artifact in
`evidence-manifest.json`; raw logs were not overwritten by substitutions.

Exact absent direct dependencies visible in the copied source:

- `app/hub_outbox.py` and `app/publication_secrets.py` for `hub_workspace`;
- additionally `app/hub_activity.py`, `app/events.py`, `app/multicode_client.py`
  and `app/usage_contract.py` for `backend_hub` collection;
- `app/hub_pool.py` for the autouse test fixture.

Those modules' transitive dependencies must come from the canonical checkout,
not fabricated stubs. Broader existing tests also import session/manager/models
and other canonical modules absent here. The full runner
`scripts/run_tests.py` and publication dependency `app/forbidden_strings.py` are
also absent. Full suite, publication guard and normal imported-app tests remain
unrun and belong to host acceptance.

The added normal integration test exercises real `plan_upload` / `apply_changes`
and `commit_sync`: a returned new `.gitignore` ignores a sibling new file while
tracked edits/deletions are committed, then the identical snapshot creates no
second commit. It was syntax-checked but could not execute through the required
imports here. Existing security/provenance tests likewise remain unexecuted here;
their implementation and owning code were not modified.

Next host check: run the required targeted command above from the full checkout,
including the added integration case, then the host's normal full suite and
publication guard. No live-process behavior, restart, historical index cleanup or
recovery of already advanced sync manifests is claimed by this patch.

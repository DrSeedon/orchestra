# V-1031: private worktree links and ownership on model changes

## Changes

- `app/private_folder.py`: `ensure_private()` now attempts to ensure that both the main
  checkout's shared folder and each worktree's symlink are ignored. Existing
  ignore rules are reused. If necessary, an untracked `.orchestra/.gitignore`
  receives `/private` and `/.gitignore`; existing content is preserved and
  repeated calls do not append duplicate rules. Old symlinks are repaired too.
- Root `.gitignore` files are untouched. Tracked private paths and real folders
  with content retain their existing protection. A tracked or symlinked local
  ignore file that would need editing produces `logger.warning` with the private
  path and reason. Git, file-access and encoding errors in ignore setup are also
  warnings. The shared folder and symlink remain usable, so optional ignore
  metadata cannot roll back `workspace.create_worktree()`. Known tradeoff: when
  exclusion is impossible, the private path remains visible in Git status.
- `tests/test_seedon_v1031.py`: 21 offline cases, including the original two
  mutation checks and a mutation that restores the worktree-breaking exception.
- `CHANGELOG.md`: records both the root-negation fix and the warning fallback.

## Findings

Git resolves `git rev-parse --path-format=absolute --git-common-dir` from a linked
worktree to the main checkout's `.git`. Its `info/exclude` is shared, but has
lower precedence than root `.gitignore`. With `!.orchestra/**`, the winning
private-path rule after this fix is `.orchestra/.gitignore:1:/private`.
Tests verify the winning rule using `git check-ignore -v` and check completely
empty `git status --porcelain` output in both checkouts.

The orchestrator identified that `workspace.create_worktree()` rolls back on any
exception from `ensure_private()`. The initial tracked-ignore refusal therefore
prevented valid worker creation. That refusal has been corrected to a warning.
Tests exercise real worktree creation and branch retention, new and existing
links, unchanged tracked ignore files and a simulated `PermissionError` when
writing ignore metadata. These are usable but potentially dirty worktrees;
they are not claimed to have successful exclusion.

The supplied session code already preserves `owned_dirs`; no additional session
production change was justified. The public change-model route, real
`AgentSession.change_model()`, SQLite persistence, full manager recovery and
actual hub upload planning were exercised for native→hub, hub→native→hub,
hub Codex→hub Codex and hub Codex→hub Claude. Both nonempty and empty ownership
were checked. Existing hub threads survive the in-place changes, owned files
reach the next live/recovered turn, unrelated directories stay out, and empty
ownership stays refused for nonpersistent projects. A failed persistence step
also leaves the original model and ownership intact.

Current ownership chain: `AgentSession._to_db_dict()` → SQLite `owned_dirs` →
`SessionManager._load_from_db()` → `BackendBuildContext.owned_dirs_source` →
hub factory `paths_source` → `HubBackend._current_paths()`. A live-service
version mismatch or the original seedon session remains unverified; this
private copy has no live state. Do not claim this report proves the deployed
process has these semantics.

## Verification

Tests used a locally prepared uv environment from unchanged `uv.lock`; test
commands used `uv run --frozen --offline python -m pytest`, nice=15 and a 2 GiB
virtual-memory limit. Test temp files stayed under this task directory. SSH,
MultiCode, capacity checks and provider startup were replaced with offline
fixtures; no live DB, provider CLI or service was used. Setup required package
downloads because the supplied uv command and virtualenv were absent.

- Final warning-fallback regression run: **138 passed, 5 deselected**, covering
  all 21 current V-1031 cases, the hub workspace/model/effort suites below and
  the four existing private-folder tests. See `soft-ignore-regression.log`.
  The tracked-ignore test calls real `workspace.create_worktree()`, and the
  exception mutation proves that restoring the old refusal breaks that path.
- Before the warning-fallback correction: **130 passed, 5 deselected**, covering
  `tests/test_seedon_v1031.py`, `tests/test_hub_workspace.py`,
  `tests/test_change_model_unloaded.py`, `tests/test_hub_effort.py`.
  See `available-regression.log`.
- Initial targeted run: **21 passed, 7 deselected**, including the 17 cases then present
  cases and four existing private-folder tests from `test_publish_guard.py`.
  Four existing private cases therefore add coverage beyond the 130 above.
  See `final-targeted.log`.
- Before excluding unavailable-context tests, the broader run reported
  **128 passed, 5 failed**. All five require the omitted default pipeline or
  hub worker prompt, documented in `regression.log`. Existing tests were not
  changed or weakened. The omitted tests are
  `test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools`,
  `test_hub_prompt_has_no_outbox_section_when_nothing_can_run_it`,
  `test_retarget_resolves_target_policy_and_claude_option`, and the two
  `test_hub_policy_matches_native_claude` parameters.
- Private mutation: disabling `_ignore_private` makes the clean-worktree
  assertion fail under `!.orchestra/**`; the mutation test requires precisely
  that failure.
- Ownership mutation: replacing the serialized ownership field with an empty
  value makes the real model-switch test fail at `persisted owned_dirs lost`.
  The initial SQLite record still has nonempty ownership, proving the switch
  writes the loss. The mutation is scoped by pytest monkeypatch.
- Ignore-error mutation: changing the warning handler back to `raise` makes the
  real worktree-creation regression fail. The mutation test requires that
  exception; the unmodified regression also passes independently.
- Source syntax, whitespace and secret-shape checks passed; publication-bound
  logs were checked using `app.secret_mask.mask_secrets`. Review evidence:
  `review.log`, `private-folder.patch`. The actual absolute imported `app`
  filename is recorded in `import-path.log`; it belongs to this checkout.

Full-suite validation is unavailable: this supplied copy omits `scripts/` and
pipeline assets. Re-run the five context-dependent tests in a complete checkout.
The reported ownership loss was not reproduced in the supplied version.

No service restart, deployment, push or repository commit was performed. The
platform owns import/commit to `task-V-1031/fix-hub-seedon`; suggested header:
`V-1031: keep shared private paths clean and verify ownership across model changes`.

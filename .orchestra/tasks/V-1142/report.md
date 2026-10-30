# V-1142 report: main-checkout private folder under root negations

## Root cause (source evidence)
- `app/private_folder.py::ensure_private` / `_ignore_private` already handle root `!.orchestra/**`
  via `.orchestra/.gitignore` (`/private`, `/.gitignore`) and already work on a main checkout.
- Its only caller was `app/workspace.py::create_worktree` (~896), i.e. only when a *worker*
  worktree is made. The main orchestrator runs in the main checkout (`use_worktree=False`) and
  writes `.orchestra/private/...` itself, so nothing prepared the ignore rule first.

## Change
- `app/private_folder.py`: new `ensure_main_private(path)`; gate = current `.orchestra/layout.json`
  AND `has_worker_memory_project_state` (V1069/V1130: reports alone / source-only untouched,
  legacy pre-migration untouched, no blanket mkdir). Delegates to `ensure_private(main)`;
  OSError/RuntimeError/SubprocessError are logged and swallowed (optional metadata).
- `app/manager.py`: called for non-worktree sessions in `_create_session_locked.prepare()` and in
  `_load_from_db` (restart/resume) when there is no worker worktree.
- `app/orchestra_layout.py::migrate_registered_projects`: called after each successful project
  result at startup, so registered projects are fixed before any agent resumes.
- `CHANGELOG.md` entry.

## Tests (`tests/test_main_private_v1142.py`, synthetic real-git fixtures, offline)
Old path: `test_old_behavior_negation_exposes_private` shows `?? .orchestra/private/` without the call.
New: ignored + public `.orchestra/tasks` stays trackable and root `.gitignore` byte-identical;
linked worker still symlinked to the shared folder, both statuses clean; source-only / report-only /
legacy-docs / nonexistent untouched (no `.orchestra` created); tracked private content never
ignored or shadowed, tracked ignore file refused with visible warning and left byte-identical,
existing untracked ignore rules kept and idempotent; startup migration applies it and survives an
`ensure_private` failure.

Results: new file 7 passed. Neighbors: see summary below.

## Limits
- Manager create/load wiring is exercised only via the helper and the startup path; no live
  AgentSession was spawned (would need provider backends). No service restart/deploy done.
- Orchestrators whose cwd is a linked worktree of the project are not covered (unchanged behavior).

## Round 2 (parent correction)
- Added real-entrypoint tests to `tests/test_main_private_v1142.py`: `SessionManager.create_session`
  (main orchestrator, `use_worktree=False`) and `SessionManager._load_from_db` (DB reload),
  each with a managed-repo (root negations) case and a source-only control. Real git, real DB,
  real `ensure_main_private`; only `AgentSession.start` is stubbed, plus pipeline-manifest
  lookups (`get_active_pipeline`, `_role_is_orchestrator`, `validate_spawn`, `get_role`,
  `_scaffold_role_docs`, `assemble_prompt`, `prompt_template_hash`) because this copy has no
  `.orchestra/pipelines`. On the full host these stubs are still valid (they only bypass manifests).
- Mutation checks (hook line replaced by `pass`, restored afterwards, manager.py byte-identical
  to before): create hook removed -> only `test_manager_create_main_session_prepares_private`
  fails; reload hook removed -> only `test_manager_db_reload_prepares_private` fails.
  The reload test builds its row via create then deletes the ignore metadata, so it does not
  depend on the create hook.
- Replaced the pinned log-phrase assert with: a WARNING-level record mentioning the project path
  exists, and the tracked `.orchestra/.gitignore` bytes are unchanged.
- Import path: tests import `app` from the working copy
  `/home/<private-identifier>/orchestra-ws/vmi3407579/hub-6764abde157847fc/app`.

## Commands and results
`export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"`
- `uv run --frozen python -m pytest tests/test_main_private_v1142.py -q` -> 11 passed.
- Round 1 neighbors (`uv run --frozen python -m pytest tests/test_publish_guard.py
  tests/test_seedon_v1031.py tests/test_private_symlink_dirty_v1049.py
  tests/test_publish_guard_mutations.py tests/test_orchestra_layout_{fleet,dirty}_430.py
  tests/test_layout_batch_v704.py tests/test_worker_worktree_layout_v635.py -q`) passed.
- Failed in this copy: `test_orchestra_layout_430.py` (t3 `.orchestra/kb/README.md` missing;
  t5 "not a git repository") and `test_source_layout_spawn_v1130.py` (`pipeline 'default' not
  found` raised in `validate_spawn`, before the new hook). SUSPECTED to be caused by the
  partial copy (no kb, pipelines, .git); NOT checked on the original tree. Parent should run
  the full host suite.
- Not run: full suite.

Publication normalization by parent: deployed user/host identifiers in the import path are replaced with placeholders; original report retained privately. Source and test outcomes unchanged.

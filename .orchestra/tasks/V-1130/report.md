# V-1130 — source-only spawn layout

## Result and contract

Fixed a synthetic, real-Git reproduction without changing migration policy or MCP outcome rules. An entirely source-only repository starts with either hubsol or hubopus. Task reports alone must also work: `load_worker_memory(..., allow_absent_project=True)` already treats an empty `.orchestra` or `.orchestra/tasks` alone as optional memory (V-1069). `require_project_layout` remains strict and separate; its migration CLI still refuses genuinely absent managed state. No automatic migration was added.

The actual lifecycle defect was `create_worktree` calling `ensure_private` whenever the primary checkout had any `.orchestra` directory. With reports alone, this planted `.orchestra/private` and sometimes `.orchestra/.gitignore` into the primary checkout and worker. Those extra entries changed the memory predicate from absent to managed. Prompt assembly then raised `ORCHESTRA_LAYOUT_MISSING` after task/worktree preparation. Compensation could leave the generated primary-checkout metadata behind. `routes.sessions.create_session` mapped that RuntimeError subclass to 500, and MCP correctly classified a mutating 5xx as unknown.

The reported project was not inspected. These experiments establish a concrete source-layout cause and model parity, not the exact contents or event ordering of the reporter's repository. Model choice alone is not supported as the cause.

## Change

- `app/private_folder.py`: hosts the unchanged V-1069 state predicate as a lightweight shared helper. `app/prompting.py` retains its old private helper name through an import alias. This avoids making ordinary worktree creation depend on prompt/pipeline imports in standalone publication-guard contexts.
- `app/workspace.py`: worktree setup skips shared-private injection for source-only/report-only primary checkouts. Existing managed-state bootstrap and publication guards are retained.
- `app/workspace.py`, `app/manager.py`: a read-only layout preflight runs after existing role/quota/capacity/base checks and before task allocation, AgentSession construction or worktree creation. Only a definite missing-layout refusal becomes ValueError, using the existing HTTP 409 mapping. The existing message retains `ORCHESTRA_LAYOUT_MISSING` and the supported repair command. MCP needs no special message-based reclassification.
- The preflight inspects the selected or reusable branch before refusing: a branch carrying layout can still use the existing lifecycle independently of the checkout state. Branch naming is shared with `create_worktree`. Late layout changes, Git inspection failures and unrelated exceptions retain their original exception/outcome behavior. This is an early refusal check, not a filesystem snapshot or a new cross-process transaction.
- `tests/test_source_layout_spawn_v1130.py`: normal conftest, real synthetic Git repositories, real manager/HTTP/MCP error conversion, synthetic hub configuration, provider start replaced with an AsyncMock. No provider/model turn or network service was called.
- Scoped entry added to `CHANGELOG.md`.

Existing partial/unknown state is not deleted or repaired by preflight. Tests preserve source bytes, refs, worktree registry, stashes, task/reservation rows and ownership on refusal. Repeating the same delivery ID allocates no task, session, worktree or initial delivery. An explicit repair through the actual CLI then starts the worker and loads its original memory. Historical clean-branch migration and selected/reused layout branches remain covered.

## Verification

Broker-provisioned uv **0.11.28**, default `.venv`, `uv run --frozen python -m pytest`, normal `tests/conftest.py`. Imported `app` resolves to this copy's `app/__init__.py`; the resolved absolute path was checked in-process and is intentionally not published. No interpreter substitution or lock change.

Test shells set TMPDIR inside `.orchestra/tasks/V-1130/tmp` and synthetic GIT_AUTHOR/GIT_COMMITTER name/email variables. No global Git config was changed. Existing TestClient startup initially needed that Git identity; its eight setup errors disappeared on the corrected invocation.

1. **Before implementation**, the initial 13-case synthetic suite: **10 failed, 3 passed in 33.35 s**. Both clean source-only model controls passed; both reports-only controls failed with HTTP 500. All eight managed/legacy/journal/unknown-state cases failed the expected 409 assertion with 500. The unrelated/late-error control passed. These are behavioral RED cases, not import failures.
2. Final focused command:

   ```sh
   uv run --frozen python -m pytest tests/test_source_layout_spawn_v1130.py tests/test_optional_worker_memory_v1069.py tests/test_worker_worktree_layout_v635.py tests/test_spawn_resume_695.py tests/test_mcp_quota_gate.py tests/test_seedon_v1031.py tests/test_private_symlink_dirty_v1049.py -q --tb=short
   ```

   **120 passed, 2 subtests passed in 84.42 s**. Covers the defect, repeated and explicit-task refusals, exact repair CLI, memory/ownership, alternate/reused branches, old worktree recovery, spawn reconciliation, quota behavior and private-link status safety.
3. Expanded caller/security command:

   ```sh
   uv run --frozen python -m pytest tests/test_manager.py::TestCreateSession tests/test_manager.py::TestAtomicSpawnLifecycle tests/test_manager.py::TestWorktreeBaseBranch tests/test_workspace.py tests/test_mcp_stdio.py tests/test_publish_guard.py tests/test_hub_workspace.py::test_upload_excludes_credentials_by_name_and_by_value tests/test_hub_workspace.py::test_upload_paths_subset_and_no_escape tests/test_hub_workspace.py::test_sync_back_cannot_escape_the_worktree tests/test_hub_workspace.py::test_sync_back_rejects_credentials_the_hub_produced -q --tb=short
   ```

   **323 passed, 1 failed in 121.20 s**. The failure is `tests/test_workspace.py::TestCreateWorktree::test_different_repos_no_collision`: this source copy has a long common directory prefix; `_slugify` truncates to 80 characters before the distinct repository suffix, giving both repositories the same worktree path. That function is unchanged. The exact test also failed against all four original source files: **1 failed in 3.89 s**. Output is recorded in `verification.txt`; final source restoration is byte-checked. This separate path-collision defect is left for the parent, not hidden by changing the frozen caller test or writing temporary files outside the authorized copy.
4. After the original-source control restored all four final modules, reran `uv run --frozen python -m pytest tests/test_source_layout_spawn_v1130.py -q --tb=short`: **18 passed in 31.38 s**. Final source/context SHA-256 values and the actual imported `app` location were rechecked. The changed source, test, changelog and result artifacts passed the existing secret-shape scanner.

## Provenance, overlap, limits

`provenance.json` records before/after SHA-256 values for the four modified modules and hashes of unchanged layout, HTTP, MCP, hub transport and conftest context. `change.patch` has repository-relative paths. The copy has no `.git`, so commit/history provenance cannot be asserted. `verification.txt` is explicitly edited output: absolute paths and tracebacks are omitted; scalar outcomes are preserved. Raw private logs and temporary synthetic repositories are not result artifacts.

V-1128 overlaps only in `app/manager.py`: existing orchestrator quota exemptions and admission calls are unchanged; the new check follows them. Existing orchestrator-preflight tests passed. V-1129's hub refresh code (`app/hub_workspace.py`, `app/backend_hub.py`) was not edited; real refresh/host acceptance remains the parent's responsibility. Model-review code/tests are untouched. Upload, source-data and credential guards are unchanged; the selected offline upload and publication regressions passed.

One exploratory old-branch spawn without an existing canonical unignore block also exposed a migration/private-ignore interaction: migration installs `!.orchestra/**` after private setup, exposing the link and failing the migration's clean-tree postcheck; compensation preserves the advanced branch. The successful historical-branch regression uses the already supported pre-existing canonical ignore block, and the existing direct V-635 recovery suite passed. This additional combined-lifecycle condition was observed here, not fixed or proven against original bytes; it should not be presented as a solved layout case.

The full required host command `uv run --frozen python scripts/run_tests.py` was not run: the task assigns full host acceptance to the parent after DONE. No service, deployment, restart, reporter data, external project, credentials, paid route, real model, new dependency, push or root-repository commit was used. Python on disk is not claimed to be active in a service.

## Parent host acceptance

The parent read the complete report, all changed modules and committed regressions, verified source/context hashes and the publication scan, and integrated accepted main without conflicts. Required complete host runner: **6807 passed, 54 skipped**, 460.86 s; instruction contract passed and the imported app belongs to this task worktree. Missing real ownership prerequisites remain explicit skips. Independent in-memory mutations make eight committed pre-allocation refusal cases fail without the new preflight, and two reports-only model controls fail with the original worktree bootstrap. Generated screenshots were privately preserved and restored; WIP was clean.

The result was accepted and merged; the temporary hub worker was immediately archived. No reporter repository or live service was changed. The existing long-slug collision follow-up is already recorded in TODO; the additional migration/private-ignore condition remains a candidate requiring reproduction. Publication/remote CI and activation by the authorized idle watcher remain separate delivery steps; no manual restart was performed.

# V-1069 — optional worker memory

## Result and cause

The fix is confined to `app/prompting.py`, plus its regression tests and CHANGELOG.
No project initializer, migration exemption, binding rewrite or provider/auth change.

Cold lookup runs `SessionManager.ensure_loaded*` → `_load_from_db` →
`assemble_prompt` → `refresh_worker_memory(allow_absent_project=True)`.
`allow_missing_layout` remains false there. The former absent-project check treated
any `.orchestra` directory as managed state, including a worker branch containing
only task reports. `migrate_worker_worktree` cannot migrate that branch over a plain
base, and `migrate_project_layout(base, repair=True)` refuses genuinely missing state.
Repeating that repair cannot initialize this repository.

Warm `AgentSession.send` passes `allow_missing_layout=delivery is not None` during
re-injection. Thus a delivery can skip unavailable memory in an already loaded
session but cannot reach that code when cold hydration fails first. An ordinary
send does not have that delivery flag. The shared optional-absence classifier fixes
both paths without changing those caller policies.

## Boundary and preservation

Missing/empty `.orchestra`, or a real directory containing only a real `tasks/`
directory, can mean no project memory. This classification checks both the chosen
checkout and its Git base. Legacy managed paths, pipelines, workers/KB/archive,
layout/migration markers, unknown entries, files in place of directories and broken
links remain evidence of state. No task report is read as memory, altered or removed.
Existing worktree migration runs before absence classification. Strict default
memory lookup, `require_project_layout` and canonical migration are unchanged.
The pre-existing explicit `allow_missing_layout=True` policy was not widened.

Synthetic Git tests retain the two worker-only commits and an uncommitted report;
compare refs, status, worktree inventory, stashes and file bytes before/after; and
check session scope, cwd, worktree, branch, task, parent and native id bindings.
Personal memory still wins over role memory, updates are re-read, and parent
checkout memory is not substituted for the worker checkout's memory.

## Verification

Runner: provisioned uv 0.11.28, default `.venv`, `uv run --frozen python -m pytest`.
Python 3.12.3. Imported app: `/remote/workspace/app/__init__.py` (actual import
location, workspace prefix normalized for publication). Setup stdout is retained.
`TMPDIR` was inside this task directory; tests used synthetic repositories and
isolated SQLite. Native backend submission and delivery hooks were mocks; no real
SDK, provider, network login or production data was exercised. Pipeline/MCP input
boundaries in the hydration test are synthetic because this copy omits manifests.

- `tests/test_optional_worker_memory_v1069.py`: final 36 passed in 33.77s
  (initial narrower run: 32 passed). Actual stdout: `optional-memory.stdout`.
- Restoring the former decisive `any .orchestra means state` condition in memory
  makes the reports-only linked-worktree regression fail as expected; the source
  file is not modified. Actual stdout: `regression-proof.stdout`.
- `tests/test_worker_worktree_layout_v635.py`,
  `tests/test_orchestra_layout_repair_base_v611.py`,
  `tests/test_orchestra_layout_430.py`, and
  `tests/test_prompting.py::TestRefreshWorkerMemory`: 20 passed, 2 failed.
  Actual stdout: `layout-regressions.stdout`. Failures are the repository-content
  assertion `test_t3_repository_move_has_content_receipt_and_no_old_roots` (missing
  `.orchestra/kb/README.md`; pipeline manifest also omitted) and the Git-based audit
  `test_t5_classified_path_audit_is_clean_and_historical_evidence_resolves` (no `.git`
  in this intentionally private copy). Tests were neither weakened nor replaced.
- Full repository suite not run in this partial, non-Git copy. The required uv
  runner exists; another interpreter was not substituted. Whole-checkout audits
  remain for the orchestrator's complete checkout.
- Final source/artifact scan: zero secret-form or runtime/account path findings;
  both Python files parse. See `publication-check.stdout`. Stdout retains actual
  results with runtime/account prefixes normalized to `/remote/workspace` and
  synthetic pytest account names normalized to `worker`. Temporary test repositories
  and SQLite files were removed; only the reports/stdout remain in this directory.

## Existing public recovery path (documented only)

After the updated Python has entered the normal service lifecycle, the existing
authenticated `GET /api/sessions/{name}/session-history?scope=<exact stored scope>`
calls `manager.ensure_loaded(name, scope)` and therefore cold-hydrates the same DB
session. `AgentSession.start()` without an initial message persists idle state;
this route does not submit a provider message or create a replacement worker.
Evidence: `app/routes/sessions.py:session_history`, `app/manager.py:ensure_loaded`,
and `app/session.py:AgentSession.start`.

The existing authenticated `POST /api/sessions/{name}/send` with the exact stored
`scope`, an authorized `message`, and `wake: true` also lazy-loads via
`ensure_loaded` before normal delivery. It remains subject to existing quota,
receipt and task/auto-switch policies. This is a normal send, not a repair/replay
API. Check the stored binding and any existing delivery receipt before use; a
previously submitted or unknown delivery must not be blindly replayed. The
`spawn-resume` route is only a spawn retry verdict, not lazy hydration recovery.

Neither route was called. No live hot-code reload path is claimed. No Unity login
URL was generated, no service restarted/deployed, and no delivery replayed. The
running process and actual provider login recovery remain unverified. The platform
will import/commit the result to `task-V-1069/fix-optional-memory`; this worker did
not create a Git commit or push.

## Host acceptance, 2026-10-24

Read the full report, final source diff and all committed regression tests. Complete selected prompting/layout/parent/model-neighbour tests on VPS:108passed in17.35s; includes both remote-copy missing-resource cases. Imported app `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-optional-memory/app/__init__.py`. Two independent in-memory mutations: restoring the former any-.orchestra condition failed the linked-worktree reproduction; removing Git-base inspection failed all10base-state negative cases. Actual stdout is retained locally in `.orchestra/private/V-1069/host-tests.txt` and `host-mutation-*.txt`; source never edited by mutations.

Read-only verification of the real affected repository found no .orchestra in the base and only a real tasks directory in the linked worker. The patched optional lookup returned empty memory; both Git HEAD/status pairs were unchanged and no layout file was created. This is a code-on-disk read-only probe, not live session hydration/provider submission. All9changed files passed credential-shape and local literal/forbidden scans before this addition. No modelreview under ownerfreeze.

Unity login was separately restored by the native parent using the existing auth helper, confirmed by owner; that is not activation/build completion and is not attributed to this patch. Python must be loaded by the existing authorized idle watcher before ordinary worker recovery; no manual restart, fake initializer, binding rewrite or delivery replay performed.

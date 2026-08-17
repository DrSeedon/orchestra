# #303 incident-scoped implementation handoff

## Authority and supersession

This is the current product contract, approved for Phase 3 on 2026-08-17. No further plan approval is required before implementation. The V3–V12 controller/UID/broker/canary architecture and every associated activation oracle are superseded for this product scope. Their files, hashes, rejected findings, and approved historical reviews remain evidence only; they are not implementation acceptance criteria.

Phase 3 may change source, tests, unit templates, and install/build scripts. It must not write `/opt`, `/etc/systemd/system`, `/var/lib`, user/group state, live credentials, or the live repository runtime; it must not call `systemctl`, restart Orchestra, move secrets, or activate a release. It produces installable artifacts and green source-level acceptance only.

## Product contract

The release makes exactly three promises:

1. The Orchestra service starts Uvicorn with the direct Python interpreter in a concrete root-owned versioned directory `/opt/orchestra/runtimes/<release>`. Service start never runs `uv`, never synchronizes dependencies, and never executes either `/home/kesha/orchestra/.venv` or `/opt/orchestra/.venv`. `mcp_stdio.py` continues to launch with `sys.executable`, so it uses the same versioned service interpreter.
2. Every project-execution boundary removes `VIRTUAL_ENV` and `UV_PROJECT_ENVIRONMENT` after all service and project/MCP environment merging. A root-owned `uv` launcher placed first on project PATH resolves the current agent worktree and rejects an environment/project/venv target outside it before invoking real `uv`.
3. Replacing, deleting, or rebuilding `/home/kesha/orchestra/.venv` cannot change the already-running service or its Orchestra MCP processes. An attempted repeat of the exact incident command `UV_PROJECT_ENVIRONMENT=/home/kesha/orchestra/.venv uv run --frozen` from another agent worktree fails loudly.

The claimed threat model ends there. This release does not claim protection from a deliberately malicious process running as the same Unix UID, an absolute-path invocation that intentionally bypasses the PATH launcher, direct filesystem writes, credential confidentiality, provider isolation, or privilege separation. It does not add controller/executor UIDs, credential brokers, provider canaries, signed attestations, or four release tracks.

## Exact production files and seams

### Runtime delivery, not activation

- `deploy/orchestra.service` — replace its `ExecStart` with direct `/opt/orchestra/runtimes/<release>/bin/python -m uvicorn app.main:app --fd 3`; retain the socket/FD-store/handoff directives; add `UnsetEnvironment=VIRTUAL_ENV UV_PROJECT_ENVIRONMENT`; remove any service `uv run` or `.venv` dependency.
- `deploy/orchestra.service.template` — the installed equivalent with a concrete release substituted by the installer; remove `ExecStartPre=uv sync`, `.venv`, and mutable-runtime PATH; add the same `UnsetEnvironment` contract.
- `deploy/install.sh` — build a new release directory side by side, verify its Python 3.12 imports, install the project launcher alongside it, render the concrete unit source, and stop before copy-to-systemd/restart unless a later operator invocation explicitly selects activation. Never replace an existing runtime directory in place.
- `scripts/orchestra-project-launch.py` (new, executable) — installed into `<release>/project-bin/uv` and `<release>/project-bin/claude`; it dispatches from `argv[0]`, resolves the real executables from `ORCHESTRA_REAL_UV`/`ORCHESTRA_REAL_CLAUDE`, removes both activation keys, validates `uv` targets through `app.runtime_env.guard_uv_invocation`, then `execve`s the real executable. It is compatibility protection, not a same-UID security sandbox.

### One environment/guard owner

- `app/runtime_env.py` — sole owner of:
  - `build_project_env(source, *, worktree, guard_dir)`;
  - `sanitize_project_mcp_servers(servers)` without mutating the caller's mapping;
  - `guard_uv_invocation(command, *, environ, worktree)`;
  - `project_cli_path(name, *, guard_dir)`;
  - `canonical_project_worktree(session)` for background work.

Canonicalization resolves symlinks and non-existing leaves through their nearest existing parent. Allowed `uv` targets are the canonical worktree itself or descendants. The guard checks inherited/inline `UV_PROJECT_ENVIRONMENT` and `VIRTUAL_ENV`, `uv --project`, `uv --directory`, and the positional path of `uv venv`. A missing/deleted worktree, malformed shell command, unresolved target, or outside target raises `RuntimeError` containing `uv target outside canonical worktree`; it never silently drops or rewrites the target. Ordinary non-`uv` commands and in-worktree `uv run`, `uv --project .`, and `uv venv .venv` remain compatible.

### Every project-execution seam

- `app/runtime_registry.py:build_backend` — deep-copy and sanitize every custom, scope, user, and project MCP server environment before runtime dispatch. This prevents explicit MCP env from reintroducing either removed key.
- `app/backend_codex.py:_build_env` — call `build_project_env` after `_mcp_env` merge.
- `app/backend_grok.py:_build_env` — call `build_project_env` after `_mcp_env` and telemetry merge.
- `app/backend_opencode.py:_build_daemon_env` — call `build_project_env` after inline-config merge.
- `app/backend_claude.py:_make_client` — pass the sanitized environment and select the project `claude` launcher with `project_cli_path`. This wrapper is mandatory because the SDK merges `os.environ` back into `options.env`; merely omitting the keys from `ClaudeAgentOptions.env` does not remove them.
- Project MCP servers — no separate launcher change: their explicit configuration is sanitized in `build_backend`, and they inherit the already-sanitized CLI environment.
- `app/mcp_stdio.py:bg_create` — include the immutable `ORCHESTRA_SESSION_ID` as `created_by_session_id` for command/run/cron-command/SSH jobs.
- `app/routes/bg.py:bg_job_create` — resolve that session through the manager, derive its canonical `worktree_path or cwd`, reject missing/mismatched scope, and persist the resolved path in job config. Do not trust a caller-supplied path.
- `app/bg_jobs.py:_spawn_bg_process` and all its command/run/cron/SSH callers — require the persisted worktree, call the guard before spawn, pass `build_project_env(...)`, and use the worktree as local cwd. A deleted worktree fails the job loudly. The local SSH client is covered; the remote host remains outside this claim.
- `app/acceptance.py:run_command` — guard and sanitize using its existing `cwd` before `subprocess.run`.
- `app/merge_test_gate.py:run_pytest` — guard and sanitize using `worktree`; preserve its worktree `PYTHONPATH` after sanitization.

No other service-only subprocess (`ffmpeg`, transcription, Git housekeeping, proxy/tunnel maintenance, browser open) is a project execution seam for this incident and must not be refactored into this change.

## Frozen executable acceptance

The acceptance file is `docs/tasks/303/test_incident_scope_supersession.py`. It is immutable during Phase 3.

```bash
env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT PYTHONDONTWRITEBYTECODE=1 \
  UV_CACHE_DIR=/var/tmp/orchestra-task303-uv-cache-kesha \
  /home/kesha/.local/bin/uvx --from pytest==9.0.2 \
  python -m pytest -p no:cacheprovider -q \
  docs/tasks/303/test_incident_scope_supersession.py
```

Frozen RED result: `3 failed in 0.27s`. The failures are the three missing product behaviors, not collection or import errors:

- direct versioned service runtime is absent;
- the shared environment/uv guard helpers are absent;
- every enumerated project-execution seam bypasses the shared boundary.

Phase 3 acceptance is the exact command returning `3 passed`, plus existing focused tests for each changed production module. The implementer must mutation-check at least: restore `uv run` in the unit; stop stripping `UV_PROJECT_ENVIRONMENT`; remove one seam call; let the `escape -> outside` symlink pass. Each mutation must make the frozen test RED, followed by a clean green rerun after restoration.

The received acceptance test is immutable: NEVER edit, delete, rename, skip, xfail, or weaken it. Do not modify this test, any task-local oracle helper, or `docs/tasks/303/plan-baselines.json`; if the implementation exposes a false premise, report `WIP/STOP` with a reproducer.

## Vertical implementation order

### I1 — Side-by-side direct runtime artifacts

- Files: `deploy/orchestra.service`, `deploy/orchestra.service.template`, `deploy/install.sh`, `scripts/orchestra-project-launch.py`.
- AC: `test_incident_service_and_mcp_do_not_depend_on_repo_venv` is green; shell syntax checks for changed shell artifacts are green; no Phase 3 command writes a production path or invokes systemd.
- blocked-by: none.

### I2 — Strip and guard all project execution

- Files: `app/runtime_env.py`, `app/runtime_registry.py`, the four backend files, `app/mcp_stdio.py`, `app/routes/bg.py`, `app/bg_jobs.py`, `app/acceptance.py`, `app/merge_test_gate.py`, and focused `tests/` regressions.
- AC: the other two frozen tests are green; existing focused tests are green; four required mutations are demonstrated and restored.
- blocked-by: I1, because backend PATH and Claude's launcher must name the packaged project-bin directory.

## Rollback and later activation gate

Phase 3 rollback is `git revert` of its source commit; no live rollback exists because activation is forbidden in this phase.

For a later separately authorized operator activation:

1. Record the old unit bytes, old release path, MainPID, and active-turn count. Keep the old versioned runtime intact.
2. Wait for the authorized drain/handoff condition, install the new root-owned runtime and unit, then daemon-reload/restart once.
3. Verify service health, Orchestra MCP startup, one project-local `uv run`, the outside-target denial, and that changing a scratch copy of the repository `.venv` does not affect the running interpreter.
4. On any failure, restore the exact old unit bytes and old release path, daemon-reload/restart through the same handoff path, and retain both runtimes for diagnosis. Never repair either runtime in place and never delete the previous runtime during the activation window.

## Fresh implementer ownership

Use exactly these `owned_dirs` for a fresh implementation worker:

```json
[
  "app/",
  "deploy/",
  "scripts/",
  "tests/",
  "docs/tasks/303-implementation/",
  "docs/workers/impl-303-incident-scope.md/"
]
```

The frozen acceptance file under `docs/tasks/303/` is deliberately outside implementer ownership and read-only. The implementation report belongs in `docs/tasks/303-implementation/report.md`.

## Review decision record

- Changed in this supersession: task-local handoff, frozen test, RED output, machine registry, and a supersession banner in the historical plan. Consumers: the fresh Phase 3 implementer and the operator of the later activation window.
- Author model/runtime: `gpt-5.6-sol` / Codex, from current session metadata.
- Exact AC and command: the frozen command above, observed `3 failed in 0.27s`; Phase 3 target `3 passed` with all four mutations caught.
- Review route: no new model review was run. The orchestrator explicitly ordered a short executable supersession, forbade another oracle carousel, superseded V3–V12, and already approved Phase 3 for this scope. This is an explicit task instruction overriding the normal shared-runtime Sol floor, not a claim that review was unnecessary. Historical review artifacts remain evidence only. `cross-family verdict unavailable`.

# V-1048 — superseded hub workspace cleanup

Implemented; no push, deployment, or restart performed. **An Orchestra restart is needed for the Python changes to go live**, after integration and the owner's explicit restart authorization.

Changes:

- `app/backend_hub.py`: whenever `_run_turn` allocates a replacement workspace, release previous records for the same canonical worktree through `release_workspace`. Exclude the replacement ID and reuse the backend's MCP/SSH transports without closing them. Cleanup failure logs a warning, retains the failed record, and allows the new turn to proceed.
- `app/session.py`: hub-to-local runtime changes release the former hub copies only after saving the successful switch. Failed persistence preserves the former workspace; failed cleanup does not reject the switch.
- `app/manager.py`: periodic sweep supplies current workspace IDs from session rows, overridden by loaded sessions and active backend IDs. This protects a new workspace before its first turn result persists the ID and handles a switched runtime whose DB snapshot is older.
- `sweep_orphans`: a registered, existing worktree no longer protects superseded workspace IDs. Current IDs remain protected, including through symlink aliases. Legacy set callers conservatively retain live copies because they provide no ownership ID; the production periodic caller now supplies the mapping.

Path audit: current hub-to-hub model changes normally use `retarget_model` and preserve the workspace. These must not delete it. Fresh/reconstructed backends, forced fresh provisioning, and allocation after a failed/missing workspace all reach the replacement allocation branch. Recovery of a missing hub project reuses its workspace ID and is not a workspace replacement. Hub-to-local switches use the persisted runtime-change path.

Validation:

- Added `tests/test_hub_switch_orphan.py`: 14 regression tests using fake MCP/SSH, including replacement cleanup, preserving the new and unrelated workspaces, reprovision after failed upload, failure logging/retry, old orphan recovery, in-place hub model changes, persistence failure, and active-backend ownership.
- Ran 9 backend/transport tests against the imported production backend with `unittest`: **9 passed**. Used the pre-existing `/opt/whisper/venv/bin/python` interpreter, `nice -n 15`, and a temporary directory inside this task directory. This is an alternative offline check, not the required project runner.
- Ran `offline_source_methods.py`: **5 passed** using unchanged session/manager method bodies extracted from source, with their surrounding application dependencies substituted. This does not validate full application imports or integration.
- Four independent in-memory mutations each produced the expected assertion failure: removing replacement cleanup, restoring worktree-only sweep retention, removing hub-to-local cleanup, and restoring the manager's path-only snapshot.
- Imported `app` was verified to resolve to this checkout's `app/__init__.py`; its absolute hub home path is intentionally omitted under the task's no-home-path/no-login constraint.
- Syntax, whitespace and credential-shape checks passed for the changed files and task artifacts.

Required checks not run: `uv run --frozen python -m pytest tests/test_backend_hub.py tests/test_hub_workspace.py tests/test_hub_switch_orphan.py -q` was attempted but the available `uv` is a shim reporting that uv is unavailable on this hub. Pytest and python-dotenv are also absent from the fallback interpreter. The full existing hub suite and normal session/manager integration tests remain unverified and must run in the receiving worktree. The partial copy also lacks `scripts/run_tests.py` and `scripts/check_instruction_contract.py`.

Evidence: `offline-tests.log`, `source-method-checks.log`, `required-runner.log`; the source-method/mutation runner is retained here for reproducibility. No real SSH, hub MCP, provider CLI, production DB, or credentials were used in the regression checks.

# git-safety — Final Report

Three git-safety features implemented for Orchestra. Advisory-not-blocking design throughout (warn the orchestrator, never block a spawn/merge), fail-loud on git failures.

## Feature 1 — Directory ownership at spawn (priority 3)

`spawn_worker(..., owned_dirs='["app/api/", "app/models/"]')`.

- New `owned_dirs TEXT` JSON column in `sessions` (ALTER guard in `app/db.py`, roundtrips through INSERT/UPDATE).
- `app/session.py`: `owned_dirs: list` field + serialization in `_to_db_dict`/`to_dict`.
- `app/workspace.py`: `parse_owned_dirs()` (normalizes JSON-string/list/None → clean list, bad input → `[]`) and `dirs_overlap()` (prefix-aware: `app/api` vs `app/api/v2` counts as overlap).
- `app/manager.py`: at `create_session`, scans live workers (idle/running, same repo scope) for overlapping `owned_dirs` → sets `ownership_warning`, returned to orchestrator via transient `session._spawn_warning`. Injects an ownership block into the worker's system_prompt ("you own X, don't touch siblings").
- `app/mcp_stdio.py`: `spawn_worker` parses/validates the JSON array, surfaces `⚠️ {spawn_warning}` in its return.
- Docs updated in `orchestrator.md`.

## Feature 2 — Pre-dispatch conflict simulation (priority 4)

- `app/workspace.py`: `simulate_conflict(repo, branch_a, branch_b)` — verifies both refs, checks merge-base (unrelated histories → error), runs `git merge-tree --write-tree`. Returns `{ok, conflicts:[paths]}` or `{ok:False, error}`.
- `app/mcp_stdio.py`: `check_conflict(worker_a, worker_b)` tool (resolves worker branches, calls simulate_conflict).
- `app/main.py`: `POST /api/sessions/check-conflict`.

## Feature 3 — Safer auto-commit + WIP visibility (priority 5)

- `app/manager.py` `_auto_commit_if_dirty`: no longer a silent commit. Returns a human-readable warning string (auto-saved N files / FAILED ...), labels the commit with branch + file list, checks `git status`/`add`/`commit` returncodes (fail-loud). Folded into `session._spawn_warning`.
- `app/prompts/roles/worker.md`: descriptive WIP commit guidance (`WIP: #49 — done X, Y; TODO: Z`).
- `app/workspace.py`: `branch_wip_status(worktree, base_ref)` — uncommitted files + unmerged commit subjects; returns `{error}` on git failure (never a false "clean").
- `app/mcp_stdio.py`: `worker_wip(name, base_ref)` tool. `app/main.py`: `GET /api/sessions/{name}/wip`.

## Codex reviews

- **Plan review** (`codex-review-plan.md`): 5 suggestions, all adopted into the plan before implementation.
- **Impl review** (`codex-review-impl.md`): 0 blocking, 3 suggestions — all fixed:
  1. `branch_wip_status` now checks `git status` + `git log` returncodes (no false "clean").
  2. `_auto_commit_if_dirty` checks initial `git status` returncode (no false "no changes").
  3. `simulate_conflict` parses conflict paths by regex — modify/delete conflicts now report the real file (`f.txt`) instead of `tree.`.

## Verification

- All 4 new helpers manually tested: `parse_owned_dirs` edge cases, `dirs_overlap` prefix-aware, `simulate_conflict` (content / modify-delete / clean / missing-branch), `branch_wip_status`.
- `owned_dirs` DB roundtrip verified.
- `pytest tests/test_workspace.py tests/test_manager.py` → 58 passed, 1 failed.
- The 1 failure (`TestRemoveScope::test_passes_orch_names_to_tg_bridge_when_flag_set`) is **pre-existing** — fails on clean checkout without these changes (TG-bridge monkeypatch, unrelated to git-safety).

## Scope notes

- `AgentStatus.ERROR` deletion requested by orchestrator was a no-op — the enum already only has `IDLE`/`RUNNING` (removed in a prior session). Touched nothing.
- The existing `merge_worktree_to_main` merge-tree precheck was left untouched — Fix 3 applies only to the new `simulate_conflict`.

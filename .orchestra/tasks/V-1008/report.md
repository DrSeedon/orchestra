# V-1008 — Workers on the MultiCode hub pool: the platform uploads, runs, syncs back

## Result

A new runtime `hub` sits next to Claude/Codex/Grok/harness. `spawn_worker(model="hub")` (aliases `hubsonnet`, `hubhaiku`, `hubopus`, `hubluna`, `hubgrok`; ids `hub-claude-haiku-5-5`, `hub-claude-sonnet-5-5`, `hub-claude-opus-5-5`, `hub-gpt-6-luna`, `hub-grok-4.7`) creates a worker whose model runs in a full-access thread on the hub. The `spawn_worker` signature is unchanged; only the model choice differs. Follow-ups are the normal `send_message`; status is the normal worker status; when the hub thread finishes, the session emits the usual `turn_end`, so the normal auto-report wakes the orchestrator. No polling tool, no "read the thread" step.

Per turn the broker (`app/hub_workspace.py`, driven by `app/backend_hub.py`):

1. **Plan** the upload from the worker's VPS worktree: tracked + untracked-not-ignored files (`git ls-files -co --exclude-standard`), minus everything credential-like (below).
2. **Upload** by `tar | ssh` into `~/orchestra-ws/hub-<16 hex>/` on the hub (our own user's home; first turn full, later turns only the delta that changed on the VPS).
3. **Register** that directory as a hub project (`t3_project_create{workspaceRoot}`) and launch a `full-access` thread bound to it (`t3_thread_launch{projectId}`), or `t3_thread_send` into the same thread on later turns.
4. **Wait** on the exact `runId`, read that run's `assistant_message`.
5. **Sync back**: `tar` of the hub directory is parsed in Python through `apply_changes` (the hub is untrusted), applied to the worktree, and the imported paths are committed on the worker's branch (`#V-1008: hub worker turn N (<model>)`, author from git config). `merge_worker` then works unchanged.
6. **Release** (worker killed → `SessionManager.remove`; worker merged → `_clean_worktree_after_merge`): `t3_project_delete(force)`, `rm -rf` of that one workspace directory (path must be `<root>/hub-<16 hex>`), delete of the local record. If cleanup fails, the record stays so it can be retried and the failure is logged, never blocking the kill.

### The open question: how to launch a thread in a directory we uploaded

From the hub's own code (`/usr/lib/node_modules/t3/dist/binCli-*.mjs`, MCP toolkit `ProjectToolkit`, read-only) and confirmed live: `t3_project_create({title, workspaceRoot})` registers any existing directory (git not required; `createWorkspaceRootIfMissing` also exists), and `t3_thread_launch({projectId, workspaceStrategy omitted → root})` runs the agent in exactly that tree. `scratch:true` picks a folder the hub chooses, so it cannot be used for our files. `existing_worktree` must be one of the project's git worktrees, so it is not needed.

## Acceptance

| # | Criterion | Evidence |
|---|---|---|
| 1 | Normal surface, follow-ups, report, mergeable commits | Registered runtime `hub` + model specs; `test_real_agent_session_drives_a_hub_turn_like_any_runtime` runs a real `AgentSession` (registry → `HubBackend` → fake hub) to `IDLE` with a branch commit. Live: two-turn session below (turn 2 is a follow-up into the same hub thread, delta upload). |
| 2 | On-demand upload only, cleanup on merge/kill | Nothing touches the hub before the first `send`. Live release test: before `['hub-6954…','hub-dbe3…']` → after `[]`, hub project list has no `orchestra hub-*` project, local state files `[]`. Hooks: `app/manager.py` `_release_hub_workspaces` (kill) and `app/merge_operations.py` (after merge). |
| 3 | No credential in workspace or prompt | Excluded by name (`.env*`, `.mcp.json`, `*.pem/.key/.token…`, `id_*`, `.git`, `.claude`, `.codex`, `.ssh`…), by literal value (every secret-named env var and every file in `data/secrets/`), and by shape (PEM, `ghp_`, `sk-`, JWT, AWS, Slack, Google, Telegram). A prompt containing one is refused before any hub call. **Live check** (`cred_check.py`): 7 known secret values, 2 live workspaces → `files with a platform credential: 0`, `credential-named/.git files: 0`; the throwaway repo had a real `.env` and `deploy.pem` which were reported as excluded. |
| 4 | Live end-to-end on a small task | See "Live proof". |
| 5 | Tests with a mutation that reddens a committed test | `tests/test_hub_workspace.py` (19 tests). Mutations on committed tests: containment check off → 1 failed; name blocklist off → 2 failed; content scan off → 5 failed; state not deleted on release → 1 failed. |
| 6 | Persistent tunnel + `.env` | Below. Not applied. |

## Live proof (22.10.2026, hub 1.3.2, OAuth full-access token, throwaway repo)

Repo `calc.py` with `add()` returning `a - b`, a test file, plus a planted `.env` and `deploy.pem` (neither tracked).

* `[status] hub: uploading 2 files (0 KiB), 2 excluded (credentials/limits)` — then Haiku 5.5 on the hub edited the file, ran the test functions with plain asserts, replied.
* `[hub sync] changed 1, deleted 0, commit 0307171`; the worktree diff:

```
-    return a - b   # BUG
+    return a + b
```
  Author `Maxim <…>`, header `#V-1008: hub worker turn 1 (hub-claude-haiku-5-5)`. `.env` and `deploy.pem` stayed untracked and never left the VPS.
* Second backend (Sonnet 5.5) turn 1 correctly reported "nothing to fix"; turn 2 (same hub thread, `t3_thread_send`, delta upload of `refreshing 2 files`) added `sub()` + `test_sub`, commit `d6b2848`.
* Steer: `sleep 45` task, steer sent at +25 s → hub replied `STEERED`, whole turn ended 26 s after the steer message (the running shell command is not preempted; the steer lands at the next step boundary).
* Interrupt: `interrupt()` returned in 0 s, turn ended `stop_reason=interrupted`.
* Concurrency: one hub thread at a time (≤1 of the allowed 2–3). In production `MULTICODE_HUB_MAX_THREADS` (default 3) caps concurrent hub turns of the whole platform.
* Models used: Haiku 5.5 and Sonnet 5.5 only.

Not exercised live: the full Orchestra process (`spawn_worker` → merge → release through the manager hooks); that needs the restart. The same chain is covered with fakes in tests and the individual hub operations were run for real above.

## Indistinguishable from native workers — and what is not

Same: spawn call, follow-up messages, `list_agents` status (RUNNING/IDLE), `turn_end` → auto-report, interrupt/stop, commits in the worker's branch, `merge_worker`, resume after an Orchestra restart (session id = workspace id; the record in `data/hub-workspaces/` carries thread id, project id and the upload manifest).

Differences the orchestrator will see:

* **No Orchestra tools inside the worker.** The hub agent cannot call `update_checklist`, `update_progress`, `send_message`; progress shows only as `status` events ("hub: uploading N files") and the final report text. It does not receive Orchestra's system prompt/role (those reference tools that do not exist there); it gets a short fixed preamble plus the task. The repo's own `CLAUDE.md`/`AGENTS.md` travel with the files and are read by the hub agent.
* **Mid-turn steer lands at the next step boundary**, not during a running tool call. Interrupt is immediate.
* **No token/cost data**: the hub does not report usage to the broker; turns are recorded with 0 tokens, `cost_usd=0`, `billing_mode=free`, unknown context. Dashboard totals for hub workers read zero by design.
* **No git inside the hub copy**: the hub agent sees no history and cannot commit; the platform commits what it imports. Binary files, symlinks and files over 20 MB are skipped; over 300 MB / 20 000 files the upload is refused.
* **Conflicts**: if the same file changed on the VPS (e.g. the orchestrator edited it) while the hub worked, the hub copy is not applied; it is listed under `conflicts` in the report text.
* **Merge with `task_outcome="continue"`** releases the hub workspace; the worker's next turn re-uploads and starts a new hub thread (hub-side conversation is lost, Orchestra-side history stays).
* **No effort mapping** (the hub model's default reasoning is used) and no `retarget_model` (change-model to/from `hub-*` is not supported).
* **Whole worktree is uploaded** (filtered). Not an API fork: it is the worker's own checkout, which the owner decision calls "what the task needs". A narrower per-task subset would need a new `spawn_worker` field; I did not add it. Say so if you want it.

## Persistent tunnel and the exact `.env` (NOT applied)

`deploy/orchestra-hub-tunnel.service`: `ssh -N -L 127.0.0.1:14606:127.0.0.1:14606` with `ExitOnForwardFailure`, `ServerAliveInterval=15`, `Restart=always`, `User=kesha`, key `/home/kesha/.ssh/multicode_hub_vps`. Independent of `orchestra.service`, so Orchestra restarts do not drop it. Installation is an operator action (`cp` to `/etc/systemd/system`, `daemon-reload`, `enable --now`). The local port must equal the hub serve port 14606 (Host check). Note that `multicode_oauth_renew.py` (colleague `feat-multicode-client`) will replace the token file in place; `MULTICODE_MCP_TOKEN_FILE` is re-read on every client construction, so renewal needs no restart.

```
MULTICODE_MCP_BASE=http://127.0.0.1:14606
MULTICODE_MCP_TOKEN_FILE=/home/kesha/orchestra/data/secrets/multicode-oauth.token
MULTICODE_HUB_SSH=<hub-user>@<hub-host>
MULTICODE_HUB_SSH_KEY=/home/kesha/.ssh/multicode_hub_vps
# optional
MULTICODE_HUB_WORKSPACE_ROOT=      # default: $HOME/orchestra-ws on the hub
MULTICODE_HUB_MAX_THREADS=3        # concurrent hub turns of the whole platform
MULTICODE_HUB_TURN_TIMEOUT_S=14400 # then the thread is interrupted and the turn fails
```

`ensure_spawn_allowed` refuses a `hub-*` model with the list of missing variables, so an unconfigured install fails loudly at spawn instead of at the first turn.

**What the restart enables** (together with the merge of this branch): the `hub` runtime and the five `hub-*` models for every orchestrator; kill/merge cleanup hooks; the earlier V-1006 `multicode_run` and V-1007 thinking capture, if not yet live. Before the restart nothing changes. Order for the owner: merge → install/enable the tunnel unit → add the four variables to `.env` → restart → spawn one Haiku hub worker as a smoke test.

## Verification

* `uv run --frozen python -m pytest tests/test_hub_workspace.py tests/test_multicode_client.py tests/test_mcp_stdio.py tests/test_models.py tests/test_model_flags.py tests/test_model_gates.py tests/test_model_registry_503.py tests/test_runtime_registry.py tests/test_quota_gate.py tests/test_mcp_quota_gate.py tests/test_model_catalog.py tests/test_manager.py tests/test_merge_operations.py -q` → 568 passed (imported `app` = this worktree). `tests/test_models.py` and `tests/test_runtime_registry.py` pinned the exact model/runtime sets and were updated for the deliberate addition.
* `tests/test_runtime_history.py::test_installed_claude_history_versions_match_pins` is red on this host (installed CLI 2.1.306 vs pin 2.1.293) — unrelated to this change, left alone.
* The full suite was not run (no PM agreement for the test lock).

## Remaining risks

* Orphans: if a worker dies while the hub is unreachable, cleanup is retried only when its worktree is killed/merged again; a periodic sweep of `data/hub-workspaces/` older than N days is not implemented.
* The hub is shared by ~80 users; a full-access agent there is bounded only by the hub's own user separation. The agent sees only our uploaded tree but is not sandboxed from the hub user's home (including the hub's own provider credentials, which are the hub's, not ours).
* `_SECRET_SHAPES` can skip a legitimate fixture that looks like a JWT/token; skipped files are listed in the upload status line.
* Probe scripts in this directory (`probe_*.py`, `live_*.py`, `cred_check.py`, `release_check.py`) read the token from `data/secrets/`; they print no secret values.

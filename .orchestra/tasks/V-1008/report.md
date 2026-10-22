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

From the hub's MCP tool schemas and a read-only look at its installed package, confirmed live: `t3_project_create({title, workspaceRoot})` registers any existing directory (git not required; `createWorkspaceRootIfMissing` also exists), and `t3_thread_launch({projectId, workspaceStrategy omitted → root})` runs the agent in exactly that tree. `scratch:true` picks a folder the hub chooses, so it cannot be used for our files. `existing_worktree` must be one of the project's git worktrees, so it is not needed.

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

`deploy/orchestra-hub-tunnel.service`: `ssh -N -L 127.0.0.1:$PORT:127.0.0.1:$PORT` (host, user, key and port come from `EnvironmentFile=/home/kesha/orchestra/data/hub-tunnel.env`, nothing is written in the unit) with `ExitOnForwardFailure`, `ServerAliveInterval=15`, `Restart=always`, `User=kesha`, Independent of `orchestra.service`, so Orchestra restarts do not drop it. Installation is an operator action (`cp` to `/etc/systemd/system`, `daemon-reload`, `enable --now`). The local port must equal the hub serve port (Host check). Note that `multicode_oauth_renew.py` (colleague `feat-multicode-client`) will replace the token file in place; `MULTICODE_MCP_TOKEN_FILE` is re-read on every client construction, so renewal needs no restart.

```
MULTICODE_MCP_BASE=http://127.0.0.1:<hub-serve-port>
MULTICODE_MCP_TOKEN_FILE=/home/kesha/orchestra/data/secrets/multicode-oauth.token
MULTICODE_HUB_SSH=<hub-user>@<hub-host>
MULTICODE_HUB_SSH_KEY=<path-to-ssh-key>
MULTICODE_HUB_PORT=<hub-serve-port>     # only for the tunnel unit; same number as in MULTICODE_MCP_BASE
MULTICODE_HUB_PROVIDER_LOG_DIR=<hub-path-of-the-per-thread-provider-log-dir>   # optional, enables log scrubbing
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


## Part 2 — complete cleanup, orphan sweep, routing hint, hub Sol (22.10, later)

### What `t3_project_delete(force)` really removes (code + live)

* It deletes every live **and archived** thread of the project through the hub's `thread.delete` command, then the project. A background purge then deletes the threads' messages, turn items, runs, provider rows and attachments; only an id/title tombstone stays in the hub's own event store (the creation event, the last state event, command receipts, the thread/project rows). Live check with a unique marker word in the prompt: before release the marker is found in the hub store's messages and turn items; 3 s after `project_delete` a logical scan of every text column finds **no** row with the marker, only 4 tombstone rows carrying the workspace id/title. `t3_project_list` no longer lists the project, `t3_thread_list` for it is empty and `t3_thread_read` of the thread answers `thread_not_found`. There is no MCP tool to hard-delete a thread; the tombstones are the hub's own bookkeeping in a database shared with the owner's live sessions, so I do not touch it.
* **Not removed by T3**, found live by searching the hub account's home for the workspace id: the uploaded directory (the hub says so itself), the provider's own session transcript for that working directory (Claude: a project transcript directory plus a CLI cache directory and a per-process session file; Codex/Grok keep rollouts in session directories), and a per-thread provider log containing the prompt. The broker now removes these itself (`HubSsh.scrub_traces`), keyed only by the unique workspace id or our thread id so nothing else can match. Residual, deliberately left: lines in the hub's shared rotating server trace (they carry the workspace id/title, not prompt content in the check I ran — the marker was absent), and, for `hub-gpt-*` threads, provider metadata rows in Codex's own state databases that cannot be cleaned without touching the account's other sessions.
* `release_workspace` order: interrupt thread → `project_delete(force)` → remove directory → scrub traces → **verify** (project not in `t3_project_list` including paging, `t3_thread_read` says not found, directory gone; up to 20 s). The local record is deleted only if verification passes; otherwise the error is raised and the record stays for the sweep.
* Live proof (Haiku, throwaway repos): released workspace → no directory, no project, no thread, no transcript/cache/session file/provider log mentioning its id (`find`/`grep -rlF` over the account home excluding only the hub store and the shared server trace → empty), marker gone from the hub store.

### Orphan sweep

`backend_hub.sweep_orphans(live_worktrees)`, run by `SessionManager._periodic_hub_sweep` 2 minutes after start and every 6 h:
1. every local record (`data/hub-workspaces/`) whose worktree is not registered for a non-archived session, or no longer exists, is released with full verification; records of live workers (even idle) are kept (`kept`);
2. hub projects under **our** root (`<home>/orchestra-ws/<host-tag>/`) with no local record, and directories there with no record, are removed only when older than 1 h (`ORPHAN_MIN_AGE_S`); projects of other people or outside the root are never touched. The default root is now per installation (`<home>/orchestra-ws/<hostname>`), so two Orchestra installations sharing one hub account do not sweep each other.
The state record is now written **before** the first hub write, so a crash mid-upload leaves a record the sweep can release.
Live: a dead worker's workspace was released while the live worker's was kept; an unrecorded 3-hour-old directory plus its project were removed; the live one stayed. Unit tests cover live/dead/unrecorded/fresh/foreign-project cases.

One unexplained event, in the interest of honesty: during the live run a Sol proof workspace and its local record disappeared about 50 s after creation, between two of my commands, while a background test run was in progress. Re-running the same tests with a fresh live workspace, and the whole set of suspect suites, did not reproduce it, no code path of mine releases without a verification call, and a decoy record survived. I could not find the cause; the sweep's liveness rule and the 1 h floor would not have deleted a live worker's copy.

### Routing hint when our quota holds a spawn

`models.hub_alternative_hint(model)` returns one sentence naming the hub alternative (`hubsol` for Codex-runtime models, `hubsonnet` for Claude-runtime models, both for an unknown target, empty for Grok/harness/hub or when the hub is not configured). It is appended to the three places an orchestrator reads a quota hold: `QuotaGateError` (spawn refusal / 429 envelope), the `WAITING_QUOTA` initial-delivery receipt, and the `send_message` quota-wait receipt. It never raises into a refusal.

### Hub Sol

`hub-gpt-6.1-sol`, alias `hubsol`, maps to the hub's `gpt-6.1-sol`. `MANUAL_ONLY_MODEL_IDS` is an exact-id guard, so the hub id passes `ensure_spawn_allowed` while `sol` / `gpt-6.1-sol` (our own Codex) stays refused; both arms are in `test_hub_sol_is_allowed_for_agents_while_our_own_sol_stays_refused`. Live: a tiny `hubsol` turn changed a file and the platform committed it (`964ad63` in the throwaway repo).

### Verification (part 2)

`tests/test_hub_workspace.py` (27 tests) plus the quota/model/manager/merge/frontend suites that mention the changed lists: green. Mutations against committed tests, each reddened exactly one or two tests: verification skipped, trace scrub matching everything, sweep ignoring liveness, sweep ignoring the age floor, hint for non-gated runtimes, sweep touching projects outside our root.

### Environment additions

`MULTICODE_HUB_PROVIDER_LOG_DIR` (optional, hub path of the per-thread provider log directory) and, for the tunnel unit only, `MULTICODE_HUB_PORT` plus `data/hub-tunnel.env`. Restart needed for: sweep, verified release, scrub, hub Sol, hint (all Python).

## Part 3 — live feed and sparse-safe commit (22.10, later)

* **Live feed.** The hub's `t3_thread_read` has an `activity` view: position-ordered items (`command_execution` with `$ cmd` + output, `file_change`, `dynamic_tool` JSON, `assistant_message`, `checkpoint`; reasoning-like items when a model exposes them), with `afterPosition` paging. `HubActivityStream` translates them into the native events (`tool_use`/`tool_result` with `tool_use_id`, `file_change`, `thinking`, `text`); `HubBackend._watch` polls once per 4 s wait slice. Items can change after first sight (running → completed), so the cursor stays just before the oldest running item and the stream keeps a per-item stage, which is what prevents both skips and duplicates. The latest assistant text is held until a later item shows it was not the last, so the final report is not shown twice. A failed poll loses only live detail. Live (Sonnet, throwaway repo, `live_feed.out`): tool_use for a `sleep 8` command appeared at 4 s, its result at 12 s, the edit at 16 s, the final text at 25 s; every tool_use had exactly one result and ids were unique. Test through a real `AgentSession`: the session log gets the tool card once, before the final text. Mutations against committed tests: duplicated tool_use, cursor skipping running items, final answer duplicated, other runs shown — each reddens at least one test.
* **Sparse-checkout defect (V-1017).** `git add -A -- <paths>` exits 1 for a path outside the worker's cone and the whole commit was lost. `commit_sync` now stages with `--sparse`, retries path by path on failure, commits the staged ones and returns the rest, which the sync note lists. Mutations: without `--sparse` and without the per-path fallback each reddens a committed test. The first prompt now names `.orchestra/tasks/<task-id>/` for artifacts.
* Restart needed (Python): live feed, sparse-safe commit, preamble.

## Part 4 — large repos, persistent copy, model changes (22.10, later)

**Root causes.** (1) "repository is too large": the upload took every checked-out file and ignored `owned_dirs`, which never reached the backend. `BackendBuildContext` now carries `owned_dirs`; the upload is restricted to them plus repo-level files; sparse cones were already honoured (skip-worktree files are absent on disk); a size refusal lists the biggest top-level entries and how to narrow. Never-uploaded paths are not in the manifest, so sync cannot treat them as deleted (committed test). (2) "hub SSH command failed rc=1:" with empty stderr: the state record is written before the first upload (part 2, for the sweep), the first attempt failed at the size check, and the next turn treated the existing record as an established workspace — `put` then ran `test -d <dir>` on a directory that never existed. Fixed three ways: the record is "established" only after `state.uploaded`, `put` creates the directory (`mkdir -p`), and SSH failures always carry output plus the kind of remote command (`rc=1: no output … [remote command: test -d]`). Reproduced in a test with a first turn that fails on size and a retry that must succeed.

**Per-project settings** (`data/hub-projects.json`, keyed by the project's scope path; `MULTICODE_HUB_PROJECTS_FILE` overrides; example `deploy/hub-projects.example.json`; re-read every turn, so no restart for edits): `max_total_mb` (default 300), `max_files` (20000), `max_file_mb` (20), `persistent` (false). To turn the persistent copy on for a project add its entry with `"persistent": true`; to turn it off set false/remove the entry and delete the warm copy with `python -c "import asyncio; from app.hub_workspace import drop_base; asyncio.run(drop_base('<scope>'))"` (credentials and `.env` are excluded exactly as before). Mechanism: `<hub-root>/proj-<hash of scope>/` holds the project; its manifest is kept locally (`data/hub-workspaces/base-*.json`). A new worker takes a per-project lock, sends only files whose hash differs from that manifest (and deletes removed ones), copies the warm copy into its own `hub-<id>` directory with `cp -a` on the hub and edits that copy; sync-back and commits are unchanged. Release and the orphan sweep only know `hub-<id>` directories, and `HubSsh.remove` refuses `proj-*` (tests). Live (throwaway project, 41 files): worker 1 sent 41; worker 2, after the repo changed in 2 files, sent exactly 2 (`live_persistent.out`); worker release left the warm copy; `drop_base` removed it.

**Model change.** Native→hub and hub→native were not blocked: they go through the existing `chat_history_v1` handoff, which prefixes the first turn of the new runtime with the dialogue (budget: 100 messages / 64 000 chars, oldest dropped with an "omitted for size" note). Two gaps closed: a credential in the old dialogue used to make the hub refuse the whole turn forever — the quoted history is now masked (`[redacted]`), while the rest of the prompt is still refused if it holds one; and hub→hub was refused (`model_retarget=False`) — it now re-configures the live hub thread (`t3_thread_configure`), keeping the hub-side conversation, and falls back to a new thread with a note when the hub refuses. Hub turns are logged as text/tool/tool_result by the live feed, so the reverse handoff carries them. The branch and worktree are the session's own and unchanged; hub files are re-uploaded on the next hub turn. Live proof (one real `AgentSession`, throwaway DB and repo, `live_switch.out`): native Haiku (Sonnet's quota gate was closed; gate bypassed in the proof script only) created `notes.txt` with a code word → switched to `hub-claude-sonnet-5-5` → the hub agent answered the code word from the earlier turn, appended a line, the platform committed it → switched back → the native model answered which line the hub agent added and the code word. Limits: the hub-side history is lost if the hub refuses a cross-provider re-configure (not exercised live); a hub workspace outlives a switch to a native model until merge/kill/sweep.

**Tests/mutations (committed, `tests/test_hub_workspace.py`, 46 tests):** owned_dirs ignored; upload requiring an existing directory; empty SSH error; remove() accepting the warm copy; persistent copy resending everything; history not masked; retarget not configuring the thread — each reddens at least one test.

**Restart needed** (Python). New optional settings: `data/hub-projects.json`. Not changed: credentials exclusion.

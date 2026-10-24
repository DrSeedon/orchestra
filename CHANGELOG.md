# Changelog

> **Two environments merged, 04.08.2026.** Before this date, the laptop and VPS maintained
> their CHANGELOGs independently, so versions 2.31.0-2.33.0 were used TWICE for different
> content: the VPS block comes first below, followed by the laptop block. Task #52 fixes the format.

## Unreleased

### Fixed
- **Full hub messages survive the message-field limit** (`app/backend_hub.py`, `app/hub_workspace.py`, `app/multicode_client.py`; V-1066). Fully composed inputs above 120,000 UTF-16 units travel intact through the existing private workspace transport with a short read-file message. First turns, resumed threads, replacement-thread fallback, steers and no-work retries use the same guarded route. Broker input files are atomic, checksum-verified, bounded by the existing workspace file limit and excluded from source uploads and result imports. Invalid parameters preserve the current thread; failed replacement launches retain its identity, and pending steers are acknowledged only after a confirmed start. No attachment truncation or additional provider call. Python change requires the normal idle-watcher lifecycle.
- **Hub return transport excludes nested caches before downloading** (V-1064; `app/hub_workspace.py`, `app/backend_hub.py`). Return tar packaging applies the existing blocked-directory names at every depth and omits custom virtualenv contents while retaining `pyvenv.cfg` for safe legacy-snapshot handling. Receiving stops at the unchanged transport cap; failures report observed bytes, limit and retained workspace identity and mark the turn failed. Successful sync reports archive bytes. The existing `_sync_back` path supports transport-only recovery of a preserved workspace without provisioning or another model turn; the task notes document identity checks and its offline proof. The real failed archive's composition remains unverified. Python changes follow the normal service lifecycle; no live recovery, deployment or restart was performed.
- **Plain-directory hub uploads work again without merge exemptions** (V-1063; `app/hub_workspace.py`). Uploads without Git freeze an empty input-provenance record, preserving pinned-uv provisioning and resumed uploads. Git worktrees still require index inspection and exact input paths/hashes; broken Git metadata does not fall back to an exemption. Publication-gate mutation fixtures now include real merge dependencies and verify that each unmodified control passes before the mutant fails an assertion.
- **Untracked hub source inputs no longer block output merges** (V-1062; `app/hub_workspace.py`, `app/backend_hub.py`, `app/workspace.py`, `app/diff_budget.py`). The broker freezes exact paths and SHA-256 values of upload-origin untracked inputs in its existing workspace record. Unchanged originals remain local and untracked while committed outputs merge and continuation switches branches; edited/missing inputs, dirty tracked or staged work, new untracked outputs and input/output path collisions still refuse. Sync-back preserves read-only originals instead of committing hub rewrites or deletions; the next upload restores rejected remote edits. Existing live records migrate from their upload manifest excluding hub-made files. Only validated, unpublished inputs are excluded from the merge's insertion budget; ordinary WIP counting and upload/publication security checks remain in force. Python changes require the normal service lifecycle; no deployment or restart is performed by this task.

### Added
- **Hub subscription image tool** (V-1059). `python -m app.hub_image` and the one-tool stdio server `python -m app.hub_image_mcp` ask a disposable Codex Sol thread to use its built-in image generator, download validated PNGs over the existing hub SSH transport, then remove the generated session, project and workspace. Includes bounded generation/cleanup, explicit errors and cleanup retry; size/aspect is a prompt hint. No paid API or DostupAI fallback. Kesha registration is documented in the task report.
- **Named hub Claude exceptions** (V-1024). `spawn_worker` and `change_worker_model` require a non-empty `model_reason` for hub Sonnet, Opus and Haiku under `hub_claude_reason_required`; server-side spawn/model-change paths enforce the same rule. The reason is persisted with the selected model, survives session reloads, and appears next to the model in dashboard cards and the active-session header. Sol and our own models need no reason.
- **Outbox for hub workers** (`app/hub_outbox.py`, `HubBackend._run_outbox`; V-1008). A hub agent has no Orchestra tools and no path back; it appends JSON lines `{"tool","args"}` to `.orchestra-outbox.jsonl` in its copy. When the turn is synced back the broker reads that file (it never reaches the worktree or git), empties it on the hub, and runs only `send_message` (always to the worker's own parent; `to`, `file_path` and other arguments are ignored), `update_progress` and `update_checklist` as the worker's own identity through the local API. Anything else is dropped, logged and named in the turn's sync summary. The hub link stays outbound only.
- **Lighter prompt for hub models** (`prompts/hub/worker.md`, `hub_preamble`). The hub model gets the role, task rules, the outbox tools and the commit/report contract instead of nothing but a one-paragraph preamble; nothing that assumes native MCP tools.

### Changed
- **Permanent hub Sol default** (`modules/model-routing.md`; V-1024, corrected by V-1029). Per the 2026-10-22 18:30 KRS decision, routing belongs only to Orchestra. The hub pool is effectively unlimited: `hubsol` handles any work regardless of remaining pool, including when our own subscription gate is closed. Hub Sonnet and Opus serve important creative work or an explicit user model request with `model_reason`; the known-heavy Opus restriction applies to our own pool. Removes the earlier project-ban exception while retaining whole-pool admission checks and keeping sensitive data off the hub.
- **Copy only what the worker needs** (`hw.require_scope`; V-1008). A hub turn with empty `owned_dirs` in a project that is not `persistent` in `data/hub-projects.json` is refused before anything is uploaded, with an error telling the orchestrator to call `set_worker_owned_dirs`. Persistent projects may still go whole.

### Fixed
- **Voice transcripts expose uncertain words** (`app/transcription.py`; V-1058). Deepgram words with confidence below 0.65 receive an inline `[?]` marker and one short uncertainty header before reaching Telegram agents or dashboard chat. Confident transcripts stay unchanged; punctuation and spacing are retained when formatted words align, otherwise the provider's word sequence retains every uncertainty marker. New cache entries store the readable annotated text in the existing string format; old entries still load without another API call. No extra transcription request or alternative-model charge. Python change requires the normal service lifecycle.
- **Quota refusals identify their rule** (`app/quota_gate.py`, `app/mcp_stdio.py`; V-1056, partial). Subscription, hub and Codex review refusals now name `worker_quota_admission` in the message and structured details while retaining the existing error code and unknown-quota policy. Added regression cases for initial and direct WAITING_QUOTA deliveries after a model change, including admitted hub routing, blocked Haiku routing and later release without duplicates. The existing server model-change releaser required no change. Direct adapters, arbitrary background commands and credential-bearing CLI processes remain an architectural fork; the inventory and verification limits are recorded in `.orchestra/tasks/V-1056/report.md`. This does not claim that those bypasses have been closed. Python changes require the normal service lifecycle.
- **Real uv for hub Python workers** (`app/hub_workspace.py`, `app/backend_hub.py`, hub worker prompt; V-1055). Before a turn with `pyproject.toml` and `uv.lock`, provisioning copies the VPS's Linux x86_64 `~/.local/bin/uv`, pinned to 0.11.28, into the hub user's versioned Orchestra tool directory. SHA-256 and version checks reuse a valid installation or atomically repair it; missing or incompatible binaries fail before the worker starts. New and resumed threads get the exact PATH export and frozen pytest command, bypassing the hub's connected-PC shim. The default `.venv` stays out of sync-back archives. Locked dependencies still need PyPI access or an existing uv cache, and imports require the source files in the worker's owned paths. Python change follows the normal service lifecycle.
- **Cut-turn recovery survives another startup crash** (`app/manager.py`, `app/db.py`; V-1057). Startup already detects durable `running` (abrupt exit) and `interrupted` (graceful shutdown) sessions independently of `/api/restart` and `cut_names`. It now keeps a durable recovery obligation while loading sessions and staggering continuation notices, closing the window where another crash left them permanently idle. Successful continuation or durable parent notification acknowledges the obligation; cancellation preserves it, manual stop cancels it, and waiting/archived agents are excluded. Prepared restarts use the same recovery path once. Python change requires the normal service lifecycle.
- **Merge guard checks what the squash publishes** (`forbidden_strings.scan_tree`, `merge_worker`; V-1052). A leak added in one worker commit and removed in a later one no longer blocks the merge: the guard scans the final base-to-head tree diff (paths, added lines, archive contents) and the squash message instead of every intermediate commit. The pre-push hook and `scan_range` remain per-commit. Python change requires the normal service lifecycle.
- **Empty hub failures recover on the same thread** (`app/backend_hub.py`, `app/hub_workspace.py`; V-1051). Failed/cancelled runs without a reply retry at most twice (1 s / 2 s) only after a complete activity read shows no provider tools and sync-back confirms no work. File changes, outbox entries, rejected/conflicting imports, uncertain sync/activity and provider limits prevent replay; retries retain the model and thread and appear in the worker log. Terminal errors include run-scoped hub diagnostics from wait/read/activity, or explicitly say no reason was exposed; read accepts T3's `recentRuns` field. Sync-back rejects directories containing `pyvenv.cfg`, regardless of their name or archive order, reports them in the sync note and continues importing sibling files. Python change requires the normal service lifecycle.
- **Publish guard scans compressed artifacts** (`app/forbidden_strings.py`, `app/publication_secrets.py`; V-1050). Added and modified Git blobs are detected by content and inspected inside gzip, tar, zip, bzip2 and xz, including nested archives, at both the `merge_worker` gate (`scan_range`) and the pre-push hook (`scripts/secret_scan.py`). Literal and shared credential-shape findings identify the archive/member without exposing values. Per-blob byte, member, depth and decoder-memory bounds refuse oversized, corrupt, encrypted or unsupported archives; deletions and plain-text policy retain their existing behavior. Archive refusals stop before constructing a binary text diff. Python change requires the normal service lifecycle; hook imports remain stdlib-only.
- **Publish guard accepts unrelated Git histories for scanning** (`app/forbidden_strings.py`; V-1042). When `git merge-base` confirms there is no common ancestor, `scan_range` compares the worker with the empty tree, scanning all worker content while retaining pathname and commit-message checks. Other Git errors remain failures. Tests isolate the forbidden-string list from operator data and supply the session logging interface required by V-1028. Python change: takes effect after an owner-authorized restart.
- **Honest recovery after platform interruptions** (V-1035). Restart, subscription-limit reset and backend reconnect notices explain that the interruption was not a user refusal, require checking uncertain tool effects, and resume the worker's task directly. Recovery notices remain eligible for a later quota reset; manual stops still prevent automatic continuation. Heartbeat recovery tolerates absent task metadata instead of aborting delivery with `AttributeError`.
- **Quota preflight preserves idle creation as a control action** (`SessionManager._create_session_locked`; V-1036). Subscription admission runs only with `planned_initial_turn=True`, before a task, session or worktree is allocated. Creating a worker without an initial task does not read its subscription quota; planned orchestrator turns remain exempt. Trigger: applying spawn admission to every creation rejected an idle worker even though no turn was requested. Python change: takes effect after an owner-authorized restart.
- **Private-folder ignore failures no longer cancel worker creation** (`app/private_folder.py`, `ensure_private`; V-1031). Root negations such as `!.orchestra/**` are overridden by a deeper local ignore file when possible. If a tracked or symlinked `.orchestra/.gitignore`, a Git error or a file access error prevents exclusion, the platform logs the path and reason and retains the shared folder and worktree link. Known tradeoff: the link can remain visible in Git status; tracked project ignore files are preserved. Python change, takes effect after an owner-authorized restart.
- **Worker merge acceptance and receipts** (`merge_worker`, `merge_worktree_to_main`; V-1034). Squash titles use the acceptance note or latest commit subject instead of an initial WIP title. The insertion budget excludes task evidence and reports its count separately. Unrelated target edits survive the merge, including staged work; overlapping edits still refuse with the target repository, affected paths and recovery action. New acceptance requires a full worker SHA and a meaningful note. Default receipts omit gate logs; `verbose=true` returns full detail without changing operation identity. Python changes require an owner-authorized restart.
- **Completed Claude compaction replaces stale context usage** (`app/session.py`, `app/session_turns.py`; V-1026). The acknowledgement's per-call token estimate updates the live and persisted context before compaction releases queued work; missing usage clears the previous snapshot. Deferred turn results wait for a fresh context reading before triggering automatic compaction, and responses from replaced backends, native sessions or turns are ignored. Trigger: a successful compaction from 95% to 10% immediately ran again using the original 945,985-token snapshot. Python change: takes effect after an owner-authorized restart.
- **Pool-wide hub admission and limit reporting** (`app/hub_pool.py`, `app/backend_hub.py`; V-1024). An exhausted active account no longer hides other accounts with headroom: admission and the dashboard use usable counts across the pool, requiring every reported usage window to be below a configurable threshold. Codex and Grok accounts that report only Weekly remain eligible; accounts without any valid window data stay unknown and do not count as usable. An unavailable relay warns and allows work. Exhausted pools refuse spawn, model change and new turns with the alternate hub model hint; a Claude reason does not bypass this gate. Provider usage/rate-limit failures produce a clear worker error and a notice to its parent.
- **Owned paths outside the sparse checkout reached the hub as an empty copy** (`hw.prepare_scope`; V-1008, from katya-work). Before the upload is planned, an owned path that is committed in HEAD but left off disk by a sparse checkout is added with `git sparse-checkout add` (a file in cone mode adds its directory); an owned path that is not in HEAD at all is allowed and named in the upload status line (`new: <path>`); and if the owned paths that exist in HEAD yield no file at all, the turn is refused with their names instead of sending an empty copy.
- **A changed `owned_dirs` now reaches the hub** (`HubBackend._paths_source`, `BackendBuildContext.owned_dirs_source`; V-1008). The backend kept the list it was built with, so `set_worker_owned_dirs` between turns changed nothing on the hub (a worker with `["app/x.py","tests/"]` kept a copy with that one file after being given `["app/","tests/"]`). The upload follows the session's live list every turn; deletions stay governed by the manifest.
- **Stale workspace after merge / task switch** (V-1008). A live hub backend kept its in-memory record after merge released the hub copy, re-saved it, and every later `t3_thread_launch` failed with `orchestration_error` against a project that no longer existed. A backend now starts a new workspace when its record has been released; `switch_worker_branch` and every other branch/task change release the hub copy of an idle worker (the persistent warm copy is not per worker and stays); and a launch refused with `orchestration_error` / not-found recreates the project and uploads again once before failing the turn.
- **False sync conflict on turn 2** (V-1008). Files the hub created outside the worker's `owned_dirs` (typically the task report under `.orchestra/tasks/<id>/`) were forgotten by the next turn's upload, so rewriting them looked like a change on both sides. Such files are now remembered as hub-made and keep their baseline; a real local edit still conflicts.

### Fixed
- **Claude start no longer fails with "Argument list too long" on a large system prompt** (`app/backend_claude.py: _set_appended_system_prompt`; V-1021). The appended system prompt (both the plain and the history-import branch) is written to a 0600 file under `~/.orchestra/system-prompts/` and passed as `--append-system-prompt-file`; the preset carries no inline `append`. The SDK otherwise puts the whole text into one argv value, and Linux caps one argument at 131072 bytes (Cyrillic costs 2 bytes per character). The file is rewritten on every connect and removed on disconnect. Trigger: Orchestra-orchestrator failed to start on 22.10.2026 after compaction because memory plus the handoff summary exceeded the limit.
- **The restart log drain can no longer hang the event loop** (`app/session.py` `_await_log_futures`, `_drain_handoff_log_writes`, `_build_claude_history_import`; V-1020). `while self._log_futures: await asyncio.gather(*tuple(self._log_futures), return_exceptions=True)` spun without ever letting a timer fire as soon as a finished future stayed in the set (reproduced on plain asyncio: even the `wait_for` meant to rescue it never fired), and it also had no end while sessions kept logging; on 22.10 `/api/restart` left the live process at 100% CPU with a dead API for ~16 min until a manual systemctl restart. The drain now waits once for a snapshot of the writes queued so far (`asyncio.wait`, 10 s budget), prunes finished futures, and on timeout logs a warning and goes on; unlike `gather`, a timeout no longer cancels the pending writes. No other `while <collection>: await gather(...)` exists in `app/`. Known limit: how a finished future got stuck in `_log_futures` in production is not established (every add site registers a discarding callback); the drain no longer depends on it.

### Added
- **Per-project hub settings and a persistent warm copy** (`app/hub_workspace.py` `ProjectOptions`, `project_options`, `provision_from_base`; V-1008). `data/hub-projects.json` (path overridable with `MULTICODE_HUB_PROJECTS_FILE`, read on every turn, example in `deploy/hub-projects.example.json`) maps a project's scope path to `max_total_mb`, `max_files`, `max_file_mb` and `persistent`. With `persistent: true` the project's files stay on the hub as a warm copy between workers: a new hub worker updates that copy with only the files whose hash changed, copies it inside the hub into its own directory and edits that; releasing a worker or the orphan sweep never touches the warm copy (only `drop_base(scope)` removes it). Credential exclusion is unchanged. Trigger: a 373 MB project exceeded the fixed 300 MB cap and every worker would have re-uploaded the whole tree.
- **A worker's model can be changed between native and hub runtimes in both directions, and between hub models** (`app/backend_hub.py` `retarget_model`, `_redact_history`; V-1008). Native↔hub uses the existing conversation handoff: the dialogue (including a hub worker's streamed text and tool records) is rendered into the first turn of the new runtime, with credentials masked rather than refused. Hub→hub re-configures the live hub thread, so its own history is kept; if the hub refuses, the next turn opens a new thread and says so. The branch and worktree files carry over (re-uploaded on the next hub turn).

### Fixed
- **Large and sparse repositories on the hub** (`app/hub_workspace.py` `plan_upload`; V-1008). The worker's `owned_dirs` now limit the upload (repo-level files always go along), only what is checked out is considered, paths that were not uploaded are never treated as deleted on sync, and a refusal for size names the largest top-level entries and how to narrow (`owned_dirs`, sparse checkout, project limits) instead of saying "too large". `owned_dirs` starting with a dot (`.orchestra/...`) were mangled by `lstrip("./")` and are fixed.
- **A hub turn after a failed first upload died with an empty SSH error** (`HubSsh.put`, `_ssh_failure`; V-1008). The record is written before the first hub write, so an attempt that failed early (e.g. tree too large) left a record without a remote directory and the next turn's `test -d` failed with rc=1 and no output. The upload now creates the directory itself, a record counts as established only after an upload reached the hub, and every SSH failure reports the output and the kind of remote command. Trigger: a worker switched to a hub model and, after narrowing its cone, failed with `hub SSH command failed rc=1:`.

### Added
- **A hub worker's chat shows its work live** (`app/hub_activity.py`, `app/backend_hub.py` `_watch`/`_poll`; V-1008). While the hub run is going, the platform polls the thread's activity timeline every ~4 s (only items after a cursor) and emits the same events native backends do: `tool_use`/`tool_result` for shell commands, file edits and provider tools, `file_change`, `thinking` for reasoning items, and intermediate assistant `text`; the existing chat, logs and SSE render them with no frontend change. Items are re-read while running and emitted exactly once, in order; the final assistant message is not repeated; hub paths are shown relative to the workspace. Trigger: the owner could watch a worker's steps in the hub's own app but only saw the final report on the dashboard. Known tradeoff: a poll adds up to ~4 s of latency, and assistant text appears when the hub marks it complete.

### Fixed
- **A hub turn is no longer lost when the hub writes outside the sparse-checkout cone** (`app/hub_workspace.py` `commit_sync`; V-1008). `git add` refused a path outside the worker's cone and aborted the whole sync commit ("NOT COMMITTED"). Staging now uses `--sparse`, falls back path by path, commits what could be staged and lists the rest in the sync note. The hub agent is also told to put task notes under `.orchestra/tasks/<task-id>/`. Trigger: a Sol worker wrote its report under another task directory.

### Added
- **`.orchestra/private/` and a forbidden-strings publish guard** (`app/private_folder.py`, `app/forbidden_strings.py`, `app/workspace.py`, `scripts/secret_scan.py`, `scripts/orchestra_backup.py`; V-1014). `.orchestra/private/` is a plain folder git ignores (`info/exclude` of the common git dir, plus `.gitignore` here because of the `!.orchestra/**` negation); every new worktree gets a symlink to the one real folder in the project's main checkout, so a worker's writes survive the worktree. `merge_worktree_to_main` and the pre-push hook refuse a change whose added lines, paths or commit messages contain a line of `data/secrets/forbidden-strings.txt` (outside git); the refusal names the list line, never the value. The daily backup archives the folder as `orchestra-private-<date>.tar.zst`. Triggering case: the hub login/host and a reverse recipe reached the public repo (V-1005/V-1006/V-1008/V-1012). Known tradeoff: worktrees created before this change get no symlink; only the Orchestra repo's own private folder is backed up, and only locally (not copied to the laptop).

- **Dashboard shows which workers run on the MultiCode hub and how much of the hub pool is left** (`app/hub_pool.py`, `app/routes/system.py` `GET /api/usage/hub-pool`, `app/static/js/usage.js`, `theme.js`, `app.js`, `i18n.js`). The endpoint reads the hub relay limits over the existing hub SSH helper and returns, per provider, the active account's windows (kind, label, `used_pct`, `resets_at`), the account count, how many have loaded credentials, and reset credits; the summary is built from a whitelist, so no account ids, e-mails or error texts leave the server. A successful read is cached for 5 minutes (a failed one for 1 minute); an unconfigured or unreachable hub gives `{available:false, reason}` instead of an error. The usage tooltip gets a "MultiCode Hub" section (percent left = 100 − used, time to reset) and workers whose model starts with `hub-` get a "Hub" badge in the agents list. JS/CSS load without a restart; the endpoint is a Python change and needs an owner-authorized restart.
- **Workers can run on the MultiCode hub model pool through a new `hub` runtime** (`app/backend_hub.py`, `app/hub_workspace.py`, `app/runtime_registry.py`, `app/models.py`, `app/manager.py`, `app/merge_operations.py`, `deploy/orchestra-hub-tunnel.service`; V-1008). `spawn_worker(model="hub")` (aliases `hubsonnet`, `hubhaiku`, `hubopus`, `hubluna`, `hubgrok`; ids `hub-<model>`) behaves like any worker: same `send_message`, `list_agents`, auto-report. On the first turn the platform uploads only the worktree's tracked and untracked-not-ignored files over SSH into a private directory on the hub, registers it as a hub project and launches a `full-access` thread there; at the end of every turn it imports the hub copy back through a validator (no path escape, links, oversized files or credential shapes) and commits the changes on the worker's own branch, so `merge_worker` applies unchanged. The hub thread gets no git remote, token or key; `.env`, `.mcp.json`, `*.pem`, `.git`, `.claude`, and any file containing a platform secret value or a credential shape are never uploaded, and a task prompt containing one is refused. The workspace, hub project and local record are deleted when the worker is killed or merged. Mid-turn messages are steered into the hub thread; `stop` interrupts it. Needs `MULTICODE_MCP_BASE`, `MULTICODE_MCP_TOKEN_FILE`, `MULTICODE_HUB_SSH`, `MULTICODE_HUB_SSH_KEY` and the tunnel unit; Python change, takes effect after an owner-authorized restart. Known tradeoffs: the hub agent does not see Orchestra's system prompt or MCP tools (no checklist/progress/send_message of its own), token usage and cost are not reported (recorded as 0, `billing_mode=free`), a steer lands at the next step boundary, not during a running tool, and a hub thread resets when its workspace is released by a merge with `continue`.

### Changed
- **Hub worker cleanup is complete, verified and swept** (`app/hub_workspace.py` `release_workspace`/`scrub_traces`, `app/backend_hub.py` `sweep_orphans`, `app/manager.py` `_periodic_hub_sweep`; V-1008). Release now interrupts the thread, deletes the hub project with `force` (the hub then purges the threads' messages and attachments, leaving only id tombstones), removes the workspace directory and the providers' transcripts/logs for that workspace, and checks that the project, thread and directory are gone before the local record is deleted. A sweep at start and every 6 h releases records of vanished workers and removes unrecorded hub directories/projects older than 1 h under our own root; live workers keep theirs. `hubsol` (`hub-gpt-6.1-sol`) is allowed for agents while our own `sol` stays refused, and quota-hold messages (`QuotaGateError`, WAITING_QUOTA receipts) name `hubsol`/`hubsonnet` as the alternative. The tunnel unit takes host, user, key and port from an EnvironmentFile. Known tradeoff: id/title tombstones stay in the hub's own store and shared server trace; Python change, takes effect after a restart.

### Fixed
- **Dashboard dates, times and money follow the selected UI language** through the shared `orchLocale()` helper, including timelines, chat and usage tooltips. Russian keeps Russian formatting; English uses English formatting, with existing time zones and monetary precision preserved.
- **Quota gate reasons in the allowance panel are translated by the dashboard, not shown as raw server text** (`app/quota_gate.py` `QuotaDecision.reason_key`/`reason_params`, `app/routes/system.py` quota-map lanes, `app/static/js/quota-lines.js` `_QL_REASONS`/`_qlReasonText`, `i18n.js`). The server now sends a stable `reason_key` (`hard_stop`, `above_line`, `within_line`, `override_active`, `pool_exhausted`, `observation_stale`, …) with pre-formatted `reason_params` next to the unchanged English `reason` string, which the 429 body, MCP and logs still read. The panel renders the key through `T()`, so the blocked-lane reasons read Russian in the Russian UI and English in the English UI; an unknown key falls back to the raw `reason`. The gate pill itself (`gate ON/LIFTED/…`) was already translated. JS loads without a restart; the new API fields are a Python change and need an owner-authorized restart.
- **Hub thread reply is the assistant message of the awaited run** (`app/multicode_client.py` `_last_assistant_text`; V-1008). User messages sent over MCP also carry `createdBy:"agent"`, so after an interrupted turn the parser returned the user's own prompt as the reply; items are now chosen by `type == "assistant_message"` and, when a run id is known, by `runId`.

### Added
- **Claude worker reasoning text is captured** (`_thinking_config` in `app/backend_claude.py`; V-1007). The CLI default omits thinking text (empty `thinking_delta`, only `estimated_tokens`); workers now request `thinking={'type':'adaptive','display':'summarized'}` so `ThinkingBlock.thinking` is a non-empty summary, stored verbatim as a `thinking` log row and shown in the existing collapsed reasoning card. Reasoning tokens are billed the same either way (probe: `thinking_tokens` 11214 omitted vs 5162 summarized on different runs, both non-zero). `ORCHESTRA_CAPTURE_THINKING=0` restores the old request. Needs a restart to take effect.
- **Delegate prompts to MultiCode Hub through official MCP** (`app/multicode_client.py`, `app/mcp_stdio.py`; V-1006). `multicode_run` creates a scratch thread with `approval-required`, retries timed-out waits, returns the last assistant message and archives the completed thread. The MCP HTTP base and bearer come from `MULTICODE_MCP_BASE` and `MULTICODE_MCP_TOKEN`; no token is logged or returned. Trigger: Orchestra orchestrators need to run a task in a MultiCode Hub thread and receive its answer without routing it through a token-stream model backend.

### Fixed
- **Renew the MultiCode Hub OAuth session headlessly** (`scripts/multicode_oauth_renew.py`; V-1006). The script registers a PKCE client, approves it with a short-lived pairing code, verifies a full-access Haiku thread, atomically replaces the local bearer at mode `0600`, and only then revokes the prior Hub session. All hub-specific values come from `MULTICODE_HUB_*`/`MULTICODE_MCP_*` environment (`.env` fallback); a missing one fails as `RENEW_FAILED`. An already-reachable Hub endpoint is reused instead of opening a second SSH tunnel. `--if-expiring-within-days N` skips Hub access when more than `N` days remain; cron output ends in `RENEW_SKIPPED`, `RENEWED`, or `RENEW_FAILED`. Trigger: Hub MCP bearer sessions expire after 30 days and have no refresh token.
- **Read the agent reply from MultiCode thread `items`** (`app/multicode_client.py`; V-1006). `t3_thread_read` identifies authors with `createdBy` and returns messages in `items`; the client now selects the latest non-user text, while retaining older `messages` and text-block content fallbacks. Trigger: a live `t3_thread_read` response returned a PONG in `items`/`createdBy`, which the old `messages`/`role` parser treated as no assistant reply.

### Added
- **Agents can search past logs across projects and fetch surrounding messages** (`app/db.py`, `app/routes/sessions.py`, `app/mcp_stdio.py`, `modules/knowledge.md`; V-1001). `search_logs` matches case-insensitively, including Russian voice transcripts in user-message content, filters by date and agent, defaults to the caller's project, and requires an explicit all-projects choice. Results are capped at 50 snippets; each search scans at most 10,000 candidate rows and reports when that scan was truncated. `get_log_context` returns at most 21 rows with bounded contents. A day index supports date filters; no FTS index was added. Trigger: a question about a 27.08 Sber account was answered from Markdown alone despite the source messages and voice transcripts being in the logs. The Python changes and day index take effect after an owner-authorized restart.
- **Claude Code local history is retained and compared with Orchestra usage** (`app/claude_history_usage.py`, `app/usage_analytics.py`, `app/manager.py`, analytics view; V-999). A six-hour periodic collector deduplicates assistant usage by `message.id`, stores per-message day/project/model token counts idempotently, and leaves previously captured rows intact when Claude removes source files. The analytics API and overview compare daily project totals from Claude history and `turn_usage`, including input, output, cache-read, cache-write and message-count differences. Trigger: V-998 found 24% more output and 21% more cache-write tokens in local Claude history than Orchestra recorded for 07–21.10.

### Fixed
- **Background run jobs have a separate memory-limited cgroup** (`app/agent_cgroups.py`, `app/bg_jobs.py`; V-1004). Local run processes started for agent workloads now enter `agents/jobs`; agent CLI processes remain in `agents/workers`. The jobs group gets half of the agents group's configured `memory.high` and half of its `memory.max`, so it throttles before reaching the parent high limit and an OOM at its own max is contained to jobs. Hosts without cgroup delegation keep the existing unisolated launch path. Trigger: eight parallel `node sim.js` commands reached about 10.6 GB RSS in `agents` and caused Claude CLI startup timeouts across projects on 21.10.2026.
- **A worker bound to a cancelled task takes new work like after a merge** (`app/manager.py` `_auto_switch_before_delivery`, `app/tm.py` `task_binding_is_cancelled`; V-996). Cancelling a task closed its run but left the worker's `task_id` and branch in place, so a new task sent to it was committed on the old `task-V-830/...` branch and then every acceptance path failed (`merge_worker`: `WORK_ASSIGNMENT_CHANGED`, `switch_worker_branch(promote_current)`: "session is already bound to a task"). Before each delivery an idle worker whose bound task is `cancelled` is now treated as completed: its binding is dropped and the existing auto-switch starts a fresh `adhoc-*` branch, which `merge_worker(task_id=<new>)` can promote. A task that is not cancelled behaves as before. Known tradeoff: a worker that already committed on the old branch before this fix is not repaired.

### Fixed
- **Video preview hides the player controls and cursor while playing** (`app/static/js/app.js` `_autoHideVideoControls`, called from the file preview; V-994). The native control bar permanently covered burned-in subtitles. Now controls and cursor hide 2 s after the last mouse move, touch, click, key or focus while the video plays, and reappear on any of those; paused/ended keeps them visible. Native seek/volume/fullscreen are unchanged (the same `<video>` element is used). Trigger: owner screenshot of an 8-minute explainer with the bar over the subtitles. Known tradeoff: on touch devices the first tap on hidden controls only reveals them. Frontend only, no restart. Test `test_video_preview_controls_autohide_while_playing` (real Chromium, ffmpeg-built webm), screenshots in `.orchestra/tasks/V-994/`.

### Changed
- **Codex prompt cache is shown and scored as non-expiring** (`app/models.py` `ProviderMetadata.cache_persistent`, `app/mcp_stdio.py:_cache_pill`, `app/usage_analytics.py:_cache_ttl_case`, `app/static/js/{app,analytics}.js`; V-992). The 30-minute approximate Codex window is removed: the dashboard pill shows `♾`, `list_agents` shows `♾ cached`, analytics no longer counts a cold start from an idle gap and labels the TTL `∞`. Claude (1 h), Grok and harness are unchanged. Trigger: the Codex product lead stated on 21.10.2026 that the cache for logged-in users is kept indefinitely, while every idle Codex worker was marked cold after 30 minutes. Known tradeoff: based on a public statement, not documentation; a Python change, takes effect after a restart.

### Added
- **`explainer-craft` skill for every agent** (`.orchestra/pipelines/default/prompts/skills/explainer-craft.md` + `references/{manim-ce,voice-checks}.md`, `pipeline.yaml` `defaults.skills`, `scripts/video_artifact/pace.py`; V-986). The craft of an explainer video (selection of one idea, "defect → fix" script, storyboard colour/label rules, voice pauses, the "from the viewer's seat" check) distilled from the 3Blue1Brown analysis (University V-19), now delivered to Claude and Codex agents like `video-artifact`, which links to it and back. Two outdated statements were corrected: `--rate 1.0` stays the default, and comma/colon/dash pauses are intonated by Tera since V-890, not by the tool (explicit pauses are `[sec]`, a step boundary or `hold`); the Manim notes now reflect `MovingCameraScene`, silent steps and the theme fonts. The V-19 measuring scripts it relied on are replaced by one self-contained `pace.py` (pauses per minute, share, vowels/s on `<name>.voice.wav`). Skill and reference files are read at agent (re)connect, so running agents pick them up on their next reconnect; no Python changed.
- **Free recoverable output in worker worktrees after merge** (`app/worktree_cleanup.py`, `app/merge_operations.py`, `scripts/worktree_cleanup.py`; V-984). After a merge operation succeeds and its result is stored, `_clean_worktree_after_merge` deletes from the worker's copy only ignored files whose content survives elsewhere: the blob is in the target branch, the same path in the main checkout has the same bytes, or the file sits in a tool cache (`__pycache__`, `.pytest_cache`, …). Only files ignored by a tracked `.gitignore` qualify (not `info/exclude`, where Orchestra marks planted files); planted files and environment directories (`.venv`, `node_modules`) are never touched; a copy with uncommitted paths, a merge in progress, or a process working in it or holding a file open is refused; each file's size and mtime are re-checked right before unlinking. A file found only in this copy is never deleted. `scripts/worktree_cleanup.py` runs the same rule over existing worktrees (dry run by default). Triggering case: worker copies held 23.3 GB (katya-work), 10.5 GB (seedon) and 8.7 GB (orchestra) on 20.10.2026. Known tradeoff: the one-off pass freed 1.2 GB; 12.9 GB of ignored output in the cleaned copies exists only there and stays until an owner decision. Python change: takes effect after a restart.

### Fixed
- **GPT-6.1 Sol is closed to agents again; only the owner selects it in the dashboard** (`app/models.py` `MANUAL_ONLY_MODEL_IDS`, `app/mcp_stdio.py`, `.orchestra/pipelines/default/prompts/modules/`; V-991). Reverses V-970: agent worker spawn, MCP change-model and dynamic-workflow tasks refuse `sol` like Astra, while dashboard model changes still accept it. Trigger: five Sol workers in one project burned the Codex 5-hour window from 0 to 100% in about 75 minutes.
- **Existing tasks can be bound to running taskless workers without disturbing WIP** (`bind_worker_task`, `/api/sessions/{name}/bind-task`, `app/tm.py`, `app/workspace.py`; V-982). The authenticated same-scope parent explicitly assigns the existing task; the canonical task state, session binding, task-run receipt and matching unmerged commit links use the existing binding transaction. Pending session snapshots drain before the live task id changes; task-store lock waits and projection refresh run off the event loop. Branch, HEAD, dirty files and worker status are preserved; repeated binding creates neither another task nor another run. Foreign scopes/parents, conflicting owners/tasks, reservations, completed tasks and pending branch switches refuse the operation. Commit headers such as `#V-251:` now retain the prefixed reference. Trigger: a running taskless worker held six V-251 commits and an uncommitted file while task_get still reported new with no commits. Known tradeoff: commit links are a snapshot at assignment; later commits are linked by the normal merge path, and old MCP processes need reconnection to expose the new tool.
- **Rebuild committed Tailwind CSS after the cache-warmth UI change** (`app/static/css/vendor/tailwind.css`; V-980). Regenerated the pinned Tailwind 3.4.17 output from current templates and JavaScript. Trigger: main CI run 39298172743, shard 4, failed `test_committed_css_matches_current_sources` because the committed generated stylesheet lagged the V-979 source state.
- **Harness OpenRouter cost is recorded as a per-turn delta across backend restarts** (`app/backend_harness.py`, `app/session_cost.py`; V-978). Each terminal turn now emits the sum of its request-level `usage.cost` values with `cost_is_delta=true`, so a new backend's zero-based counter is not compared against a persisted provider baseline. Missing cost remains unknown and failure turns remain unaccounted. Trigger: after restart, eight paid rounds reported $0.04504706316 total, but session cumulative-cost subtraction persisted $0.00 for the turn.

### Added
- **Per-session OpenRouter cache warmth evidence in the Info panel** (`app/routes/system.py`, `app/static/js/app.js`, `app/static/css/style.css`; V-979). The panel reads only the selected session's latest successful Harness turn and shows its timestamp, measured cached-token share, cost and observed provider/model. It labels the 10-minute sticky-routing boundary and the empirical 10–30 minute cache behavior; beyond 30 minutes is unknown. A configured provider order pin is called out as disabling sticky routing, and none of these observations is presented as a provider TTL guarantee. Trigger: session UI had no per-session evidence for recent OpenRouter cache behavior.
- **Vision-capable OpenRouter routes receive validated Telegram and workspace images as private data URIs** (`app/model_catalog.py`, `app/models.py`, `app/backend_harness.py`, `app/harness/{images,llm,tools}.py`; V-976). Catalog `input_modalities` survives registration and model retargeting. Telegram attachments remain `[photo: path]` / `[file: path | name]` in history and are sent after their unchanged text as separate `image_url` parts. Vision routes also expose a read-only `read_image` tool bounded to the current workspace; its text-only result is retained in history, then the request adds image parts after the tool-result group. Non-vision routes omit the tool and keep the text-only fallback. Invalid, missing, oversized, or out-of-root files fail explicitly; OpenRouter `finish_reason=length` is reported as truncation before any accumulated tool call can execute, while empty non-truncated responses remain distinct. Trigger: Telegram attachments and repository images reached the harness only as text/binary paths, and an empty response with `finish_reason=length` was indistinguishable from transport failure.
- **OpenRouter turn usage keeps provider evidence per request** (`app/harness/llm.py`, `app/backend_harness.py`, `app/db.py`, `/api/usage/turns`; V-975). Each completed API round now retains its sanitized endpoint URL, response identifiers and provider/model fields, response headers selected for request tracing, complete usage object, and measured API duration; endpoint records omit URL userinfo, query and fragment. `turn_usage` stores the per-round records and the project-scoped endpoint requires a nonempty `scope`, serves dashboard sessions only in owner mode, and binds MCP requests to the caller's proven session scope. Paid listed routes use `billing_mode=openrouter_credit`, `:free` routes use `free`, and missing paid-route cost stays unknown (`cost_usd=NULL`, `cost_unaccounted=1`). Turn wall time and reasoning tokens are recorded when all rounds report them; otherwise the reasoning aggregate stays unknown. API time sums completed rounds without tool wall time and provider differences remain separate. Trigger: project usage rows had no provider or timing evidence, missing paid-route cost could look like a priced zero, global dashboard authentication did not isolate project scopes, and a configured endpoint URL could contain credentials.
- **Strict InferenceNet routing for DeepSeek V4.1 Flash 1017** (`app/models.py`, `app/harness/llm.py`; V-973). The exact paid id `deepseek/deepseek-v4.1-flash-1017` is admitted and its request sets `provider.order` and `provider.only` to `InferenceNet` with fallbacks disabled. Other model routes retain the configurable provider order and fallback behavior. Trigger: the owner approved this paid route for openrouter-lab agents after provider evaluation selected the InferenceNet fp8 endpoint.

### Fixed
- **Task-directed writes outside a repository are no longer blocked by worktree rules** (`.orchestra/pipelines/default/prompts/modules/git-workflow.md`, `roles/worker.md`, `roles/full-cycle.md`, `base.md`; V-971). Worktree confinement now applies specifically to repository edits; installs, data directories and other external files named by the task remain within its authority and the safety rules. Trigger: a worker treated the installation target `/mnt/data/dwn` as forbidden because its role said every file edit had to stay in its worktree. In matched Luna trials, explicit refusals citing the old boundary fell from 4/5 to 0/5; one post-change success claim was not externally verifiable as a persisted file.

### Changed
- **Orchestra MCP calls render as readable, localized tool cards** (`app/static/js/chat.js`, `app/static/css/style.css`, `app/static/js/i18n.js`; V-967). Compact chat shows a translated action and useful argument values without exposing the argument JSON; expanded cards show translated fields, readable text and checklist states/estimates, with full arguments and structured results under technical details. Unknown future tools use a humanized generic card. Agent-count summaries no longer expose the English `(many)` marker. Trigger: Orchestra calls such as `update_checklist`, `publish_artifact` and `worker_wip` were shown as raw names/JSON, while the Russian dashboard had English labels and checklist items looked like key/value dumps.

### Fixed
- **Sol is available for agent work; Astra remains manual-only** (`app/models.py`, `.orchestra/pipelines/default/prompts/modules/`; V-970). The agent-only model gate now blocks Astra while Sol defaults to agent-enabled, so MCP worker creation/model changes and dynamic workflows can select `sol`; dashboard model metadata reflects availability. Routing guidance keeps Luna as default and assigns Sol to heavy Codex work. Trigger: the 2026-10-19 owner decision reopened GPT-6.1 Sol to agents without reopening Astra.
- **Accepted direct messages no longer hang forever in `QUEUED`/`WAITING_NEXT_TURN`** (`app/message_deliveries.py` `sweep_stuck_deliveries`, `fail_deliveries_to_archived_targets`, `start_sweeper`; `app/db.py` `archive_session`; `app/main.py`; V-966). Cause: a steer lost with a failed Codex turn becomes `WAITING_NEXT_TURN` (non-terminal) and is the head of the target's queue, but its only exit is the end of the target's next turn, which an idle session never has. The head blocked every later message (`QUEUED`, no error) — 12 records on the live DB, the oldest from 05.10 (decision-cost, plus tender-triage and feat-kesha-alert, both since archived). Now (1) archiving a session fails its undelivered `QUEUED`/`WAITING_NEXT_TURN`/`WAITING_QUOTA` deliveries as `FAILED_BEFORE_SUBMIT` with code `TARGET_ARCHIVED` and the usual failure notice to the sender, and drops their mailbox copies; (2) a 60 s sweeper started in `lifespan` repeats that for rows left behind earlier (this is the one-off migration of the 12 records, done by code at start), hands the mailbox to a live `IDLE` target whose `WAITING_NEXT_TURN` row is older than 120 s, restarts runners of `QUEUED`/`PREPARING` heads and retries pending notices (notices to archived senders are closed); (3) any `QUEUED`/`PREPARING`/`WAITING_NEXT_TURN` row older than 1 h is named once in the log and in the target session's journal. `DISPATCHING`/`DELIVERY_UNKNOWN` are never touched (at-most-once). Known tradeoff: decision-cost receives its five old messages together, days late.

### Fixed
- **Время шага чеклиста больше не капает у простаивающего агента** (`app/checklists.py:set_clock`, `drop_open_clocks`, `AgentSession.__setattr__`, `app/static/js/app.js`; V-968). `active_since` ставил и снимал только `save_checklist`, поэтому «Факт» текущего шага рос всё время простоя, а в сохранённый факт и в сравнение с оценкой попадал весь простой; просроченная по такому факту оценка запускала напоминание сразу после возобновления. Теперь часы идут только при `running` и compaction и останавливаются в `idle`/`waiting`/`stopped`, возобновляясь с накопленного значения; после рестарта открытые часы прежнего процесса сбрасываются без добавления простоя. Напоминание «нет обновления чеклиста» на карточке показывается только у работающего агента. Триггер: карточка gamelab со статусом «простаивает» и растущим «Факт 14:28:19». Known tradeoff: ожидание фонового задания (`waiting`) не считается работой; время от последнего сохранения до падения процесса теряется.
- **Compaction no longer demotes the previous handoff to "unconfirmed / do not apply"** (`app/agentic_compact.py` `COMMON`, `audit_prompt`, `final_prompt`, `PREVIOUS_SUMMARY_MARKER`; `app/session.py` `_compact_prompt`; V-963). The journal handed to the compactor starts at the last `[PREVIOUS CONTEXT SUMMARY` row, so the owner's original messages behind older requirements are not in it, and `FINAL` forbade facts "not verified in the journal". On a chain of compactions the compactor sometimes wrote that the carried rules were "not found in the owner's messages — do NOT apply" (or dropped them), turning an active requirement into a ban on applying it. The prompts now say that the first row is the agent's own earlier handoff, a trusted source: its still-active requirements, decisions, bans and open items are carried unchanged unless a later row cancels, replaces or completes them (then the final state is recorded), and only facts found in neither the journal nor the previous handoff are forbidden. The 20 000-character cap is unchanged. Measured on the V-961 stand (same inputs, step 4 of a real chain, Sonnet compactor): 12 of 45 runs of the old prompts lost or half-lost a carried item and 2 lost all 15 planted facts, against 0 of 45 with the new prompts; cancelling or replacing a carried requirement in the new segment still works (30/30 with both versions). `tests/test_compact_carry_963.py` keeps the marker the prompts name in step with the preamble header and the journal query.

### Fixed
- **Daily backup fits the 600 s job limit** (`scripts/orchestra_backup.py`, `_daily`, `_transfer_slice_seconds`; V-962). `--daily` created the archive (~5 min for 2.3 GB) and then ran a laptop rsync slice of up to 450 s, so the platform killed the job at 600 s (19.10, bg-789f036196). `--daily` now only makes and verifies the local archive; the laptop copy is left to the hourly `--push-task-store`, which resumes via `--partial --append-verify`. The hourly slice is cut to what remains of a 600 s budget minus a 90 s reserve for the post-transfer checks (skipped, without an error, when under 20 s remain). Known tradeoff: the laptop gets the new daily archive up to an hour later; a multi-slice transfer still reports `incomplete` after each slice, as before.
- **Backup no longer alarms while the laptop sleeps** (`scripts/orchestra_backup.py`, `_laptop_tunnel_available`; V-957). The probe was a bare TCP connect to the reverse-tunnel port, which the VPS keeps open even when the laptop is asleep, so the next ssh died with `Connection timed out during banner exchange` and the hourly `--push-task-store` job printed `BACKUP_FAILURE step=laptop` and exited 1 every hour. The probe now runs `ssh ... true` (ConnectTimeout 5, 10 s cap); a connection-level failure (timeout, banner/kex, refused, reset, no route) or a hanging probe means "laptop offline" and the laptop step is skipped with rc=0, like a missing listener. Auth failures, rsync errors, checksum mismatch and a copy older than 3 days still produce `BACKUP_FAILURE`. `--daily` shares the same function. Known tradeoff: a laptop that goes to sleep between the probe and the copy still fails that run once.

### Changed
- **Knowledge-base entries about the effect of a change carry a verdict and a cue** (`.orchestra/pipelines/default/prompts/modules/knowledge.md`; V-956). An entry about a prompt, rule, mechanism or model-route change must say `helped`/`hurt`/`no observed effect`/`confounded` on the basis of a before/after or with/without contrast, plus when to apply the lesson; without a contrast it is `confounded` or not written. Other findings are unchanged: no format is required for them. Owner decision, 2026-10-18; no automatic experience-to-rules loop was added.
### Added
- **The 5-hour quota strip shows how much of the window the week really leaves** (`app/static/js/usage.js`, `i18n.js`; V-969). The Claude "5 ч" mini-bar now hatches the part of the window locked by the weekly limit and adds "реально N%" with a plain-language tooltip. The numbers are `quota_headroom.available_pct/locked_pct` from `/api/usage`, the same source as the Telegram `/limits` card, with no separate arithmetic; when the week does not limit the window the strip looks as before. Triggered by the owner's request after the Telegram card showed 16% used but only 3% usable at 97% of the week.
- **Отметка «⏳ лимит, проснётся ~HH:MM» у агентов, остановленных лимитом подписки, и шаг пробуждения 10 с** (`app/limit_wake.py`, `app/routes/sessions.py`, `app/routes/system.py`, `app/mcp_stdio.py`, `app/static/js/app.js`; V-955). `limit_wake_marks()` строит отметку из тех же данных, что и планировщик (кандидаты `_load_limit_stopped_agents` + активные таймеры `wake_subscription_limited`): время таймера плюс позиция в когорте × `WAKE_STAGGER_SECONDS` (теперь 10 с вместо 30), а без таймера — причина (таймер ещё не создан / месячный лимит). Поле `limit_wake` приходит в `/api/sessions` и `/api/orchestrators`, показывается в карточке агента дашборда (в локальном часовом поясе браузера) и в выводе `list_agents` и `list_orchestrators`. Отметка исчезает, как только агент перестаёт быть кандидатом (проснулся или получил другое сообщение). Листинги не ждут расчёт: `limit_wake_marks()` отдаёт последнее готовое значение и пересчитывает его в фоновом потоке (прогрев при старте в `main.lifespan`), а поиск кандидатов идёт через индекс `idx_logs_session` по каждой подходящей сессии вместо оконного скана всех `turn ended` (на боевой БД холодный скан занимал 27 с). Триггер: 18.10 оркестраторы вручную будили воркеров, не видя, что пробуждение уже запланировано.

### Fixed
- **Пробуждение после сброса лимита подписки больше не теряет всю когорту** (`app/limit_wake.py`; V-953). 18.10 таймер `wake_subscription_limited` на 10:30:00 сработал в 10:30:00.001, повторно запросил usage, снимок ещё показывал 100% при `resets_at` = 10:30:00 уже в прошлом, `provider_readiness` вернул `manual: base capacity has no timed reset`, джоб завершился без единого пробуждения и не перепланировался — 8 агентов остались стоять, пока оркестраторы не будили их вручную. Теперь окно с прошедшим `resets_at` считается сброшенным (`available`), провал готовности внутри `run_wake_job` перепланирует неразбуженных (`_rearm_wake`, 120 с, не более 5 попыток), отказ провайдера с `resets_at` задаёт нижнюю границу пробуждения даже при usage 99% (`limit_reset_at`), а дубликат пустого `turn ended` через секунды (так выпал `sales`) больше не отрезает от хода запись `provider_limit` (`_latest_limit_info`, окно журнала расширено до 4 завершений хода).
- **Короткий `request_key` у `task_create` принимается; рутинный cron не держит агента в `waiting`; отказ merge называет, чего ждёт воркер** (`app/tm.py`, `app/mcp_stdio.py`, `app/bg_jobs.py`, `app/merge_operations.py`, `app/error_watch.py`; V-952). (1) Минимум в 16 символов у ключа идемпотентности ничего не защищал: хранилище уже ловит повторное использование ключа с другим содержимым (`TaskCreateConflict`), а id задачи — uuid5 от проекта и ключа; теперь допустимо 1–128 символов `A-Za-z0-9._:-`, а описание инструмента называет правило. Триггер: 12 отказов `burn-1810-N`, `v261-ui-1` и т. п. у четырёх оркестраторов. (2) `has_active_jobs` (и потому статус `waiting`, подавление auto-report и отказ merge «Worker is waiting») больше не считает plain `cron` — повторяющееся напоминание само себе никогда не завершается; `cron_command`, `timer`, `run`, watch'и по-прежнему держат ожидание. Триггер: у `prolider` два cron-напоминания на 100 лет навсегда оставляли воркера в `waiting`. Уже зависший в `waiting` воркер вернётся в `idle` на конце следующего хода. (3) `WORKER_BUSY` для `waiting` теперь перечисляет активные задания (`details.waiting_on_jobs`: id, тип, сообщение, срок), а error_watch относит такой отказ к ожидаемым.
- **Claude agents call Orchestra MCP tools by their working name** (`.orchestra/pipelines/default/prompts/base.md`; V-950). Rules name tools without the server prefix, and Claude Code registers them as `mcp__orchestra__<name>`; 11 calls to bare `update_checklist` (plus a few bare `update_progress`/`bg_create`) failed with "No such tool available", and one lost a checklist because the call was not repeated. One sentence in the shared base prompt now states the Claude Code name; Codex and harness runtimes keep the bare name. Text change only, no restart needed for new sessions.

### Changed
- **Temporary rules live in git, not in the database** (`app/temp_rules.py`, `app/routes/temp_rules.py`, `orchestration.md`; V-934). Text and metadata (text, reason, targets, mode, date, author, creation time) are stored in `.orchestra/temp-rules.yaml` of the project's main checkout; rules for all projects are in the Orchestra repository's file. `temp_rule_set/update/remove` rewrite that file under a per-project lock and commit exactly that path (`git commit --only`), so other uncommitted work in the tree is left alone; if git refuses (not on the mainline, merge in progress, hook failure) the file is restored and the call fails with the reason. A project without `.orchestra/layout.json` is refused, because creating `.orchestra/` there would break its prompt assembly. The prompt block is built from the file on every turn: a hand edit or a pulled change applies from the next turn; an entry without a reason, or without a valid date in `expires`/`review`, is skipped with one warning and never fails the build; a broken file yields no rules, a global entry in a foreign repository is ignored. Only reminder state stays in the database (`temp_rule_notices`, keyed by project, rule and date, so extending a rule re-arms its notice). The former `temp_rules` table is moved into the files once, at the first prompt assembly after the restart (so a rule in force does not lapse) and renamed `temp_rules_moved_to_git`, not dropped. The Orchestra orchestrator can no longer set a rule inside another project's repository: only its own project and `*`. The orchestrator-only prompt module now says where the file lives and that the later dated owner decision prevails on conflict. Trigger: the owner wanted rules to travel with git ("Всё в гите"). Known tradeoffs: a git commit happens on each change in the project's main checkout, so a concurrent git operation there can make the call fail (retry); ended `expires` rules stay in the file until removed; the file's uncommitted hand edits are committed together with the next tool change. Python change: takes effect after a restart.
### Added
- **Vertical 1080×1920 video mode** (`make.py --format vertical`, `--hook`, `safe_area_issues`; `video-vertical.css`; `paper.js` `Paper.hook`; skill `video-artifact.md`; V-949). Opt-in; horizontal 1920×1080 stays the default. The frame is 720×1280 CSS px at the same ×1.5 scale; captions are 38 px and raised above the platform UI; every build checks that each step's caption and the hook lie inside the safe area (x 120…960, y 250…1580 in video pixels) and fails otherwise. `--hook "claim with a number"` (refused without a digit) overlays the claim for the first 2.6 s so the first frame is a statement, not the painted opening. The contact sheet is six frames per row; Manim renders `-r 1080,1920`. Sound, paper kit and painted scenes work unchanged. Trigger: publishing short videos on Shorts, Reels and VK Клипы (V-947). Known tradeoff: a scene needs its own vertical layout (the V-937 rebuild lives in `.orchestra/tasks/V-949/build_vertical.py`); the Manim vertical mode is covered by a caption-wrapping test and one manual toy render (1080×1920 confirmed), not by a full VoiceScene render.
- **Qa writes a targeted headphone check** (`scripts/video_artifact/sound/qa.py`: `ear_check`, `duck_transition`; V-944). After the sound QA, `<name>.sound/ear-check/` holds frames two frames either side of every event cut from the encoded MP4 and `ear-check.md/json` with at most five timestamps (hero events by gain, the sharpest music duck at a voice onset, then support events), each with a one-line reason. Trigger: the V-943 comparison with a published sound prompt.
- **Sound licensing restrictions removed for personal-use videos** (`mix.py`, `sfx.py`, `make.py`, skill; V-946, owner decision 2026-10-18: videos are personal use only and never shown publicly). Reverses the licensing half of V-944: `synth:pluck`/`synth:bell` work again, `--music` takes any file, `--music-source`/`--music-license` are optional notes, `<name>.credits.md` is a best-effort side note that never blocks a build, and `sfx.py search` queries Openverse for any license and source (`--source jamendo`, `--license cc0` to narrow) while the CC0 kit stays the first place to look.
- **Video stress dictionary, support check for painted props, and a library of opening/closing scenes** (`scripts/video_artifact/stress_ru.json`, `make.py` `apply_stress_dictionary`/`paper_scenes`, `paper.js` `Paper.view`/`mini`/`live`/`supportIssues`, `brush(..., {out})`, `scripts/video_artifact/scenes/{night-desk,board,cafe}.svg` + `index.json`, skill `video-artifact.md`; V-935). Russian builds apply `fixed` stress corrections before synthesis and stop when a homograph (`стоит`, `замка`, …) has no manual `+`; every Tera build writes `<name>.stress.txt`. Props marked `data-on="<support>"` must rest on their support, otherwise the build stops. Three painted scenes (night room, bright office with a whiteboard, morning window with a laptop) are injected by `make.py` and selected with `Paper.picture(g, box, {scene})`; `Paper.view`/`Paper.mini` place the diagram copy on the scene's screen for the match cut. Trigger: the owner heard wrong stresses in the V-929 video («ход+а», «ст+оит» in «блок стоит», «з+амка» for a lock), saw a lamp hanging in the air and a misplaced chair, and wants a series of videos that do not all open and close with the same room. Known tradeoff: the homograph gate makes old Russian scenes containing such words fail until the word is marked; the support check only tests resting on the support, not whether the placement makes sense.

### Fixed
- **A review notice for a temporary rule no longer vanishes when its author is gone** (`app/temp_rules.py` `notify_due`/`_recipient`; V-933). If the author's session was archived or missing, the rule was marked as notified and nobody was told, so a `review` rule stayed in force forever. Now the notice goes to the live orchestrator of the rule's project (the Orchestra project's orchestrator for a rule on all projects); with no live recipient at all the rule is not marked and is retried on the next sweep, and one warning per rule is logged instead of one every 60 s. Trigger: found while auditing permanent rules in V-931. Python change: takes effect after a restart.

### Changed
- **Rules cleanup per the V-931 inventory** (`AGENTS.md`, `modules/user-values.md`, `project-maintenance.md`, `orchestration.md`, `report-format.md`, `base.md`, `roles/worker.md`, `roles/full-cycle.md`, `code-quality.md`, `model-routing.md`, `pipeline.yaml`; V-932). Restart: the project's orchestrator now restarts Orchestra itself after a merged Python change without cutting workers (owner decision 15.10/17.10); the ban stays for every other agent, and the shared module allows the exception only where a project's own rules delegate it. Removed the dormant PROJECT CONTEXT review block, the stale "live sub-orchestrator exists" reason (and its two misplaced copies), and the duplicated review-freeze statements (kept once in `orchestration.md` for orchestrators and once in `report-format.md` for workers). `worker.md` now sends commands over ~60 s to `bg_create` like `base.md`; the Monitor/run_in_background ban is stated once. Corrected rationale only (rule unchanged): the 32 KiB truncation is specific to the OpenRouter harness, the CLAUDE.md symlink reason follows the 08.10 KB correction, the tariff history in model-routing is shortened, the `MemoryMax` figure points to the live value. No tests referenced the removed wording.

### Changed
- **Temporary rules have a mandatory reason and three explicit modes** (`app/temp_rules.py` `add_rule`/`active_block`, `temp_rule_set`, `app/routes/temp_rules.py`, `orchestration.md`; V-927). `temp_rule_set(text, reason, targets, mode, expires_at, project)` replaces `on_expire`: `expires` drops out by itself at the date, `review` stays in force and tells the author once that it is time to review it, `permanent` has no date and is set explicitly (the date is required for the first two and refused for `permanent`). An empty `reason` is refused in every mode. The prompt block shows each rule's text, reason, mode with date (or "permanent"), author and creation date. A `reason` column is added to an existing `temp_rules` table with `ALTER`; older rows keep working (they simply show no reason). The orchestrator-only module `orchestration.md` now tells orchestrators when and how to use the tools; workers do not receive it. Trigger: the owner required every temporary rule to carry its cause and a deliberate lifetime. Known tradeoff: `on_expire` is gone from the tool and route (in-repo callers only; the earlier version was never used on live data).

### Added
- **Temporary rules with a deadline reach every targeted agent's prompt without a restart** (`app/temp_rules.py`, `app/routes/temp_rules.py`, MCP tools `temp_rule_set/list/update/remove` in `app/mcp_stdio.py`, `SessionManager.assemble_prompt`/`_periodic_temp_rules`, `AgentSession.send`; V-927). A rule is text + targets (`all`, `orchestrators`, `workers`, a role name, `agent:<name>`) + UTC deadline, stored in the database (table created lazily, no schema migration), not in git. It is rendered as a `<temporary-rules>` block at the very end of the prompt, sorted by creation time and id, so the cached stable prefix is not rewritten and the prompt changes only when a rule is added, removed or ends. `AgentSession.send` compares the fingerprint of that block with the one in the live prompt on every turn and, on a difference, re-delivers the prompt through the existing "role instructions were updated" injection — for a new rule and for an ended one alike. Per rule, `on_expire` is `remove` (the rule drops out by itself at the deadline) or `notify` (the rule stays in force; the author gets one platform message, marked in the database so it survives a restart and is retried if delivery fails; the author then extends, keeps it without a deadline or removes it). Rights: only orchestrators, authenticated by MCP proof; own project only; a rule for all projects only from the Orchestra project's orchestrator. Trigger: the owner wanted a model-routing rule valid until 2026-10-20 without editing pipeline files. Known tradeoffs: the sweep that sends notices runs every 60 s, so a notice can be up to a minute late; a notice to an author who was archived is dropped with a log line. Python change: takes effect after a restart.

### Fixed
- **Animated text no longer flashes the old word at its starting place** (player scaffold in `html-artifacts/references/animation.md`, `scripts/video_artifact/make.py` `warn_old_player`; V-922). On a text change the leaving text is drawn by a clone created at load; it copied only `opacity` and `fill`, so a label that had been moved or resized earlier flashed its old word for 3–4 frames where it stood at the start (in the V-917 demo: a blue 40-unit "CLAUDE.md" at the top of the frame at 9.3 s and 12.1 s). The clone now mirrors every animated attribute and the `along` transform. Scenes that embed the old player still build; `make.py` warns and names the line to replace. Trigger: the owner saw "blinking text" in the V-917 demo.
- **Agent workloads are contained and selected before Orchestra during global OOM** (`app/agent_cgroups.py`, `app/agent_cli_exec.py`, `app/pidfd_exec.py`, `app/routes/bg.py`, `app/bg_jobs.py`, `app/shell_policy.py`, `.orchestra/pipelines/default/prompts/modules/code-quality.md`; V-924). Local run jobs initiated by non-orchestrator sessions are explicitly marked as agent workload, launched under the `agents` cgroup, and set `oom_score_adj=1000`; non-agent jobs no longer inherit the service's agent cgroup environment. Agent CLI launchers use the same OOM priority, while orchestrators retain their existing priority. The Bash policy rejects `ssh kesha@localhost` commands without a remote `choom -n 1000 --` prefix and prints a corrected command. Trigger: three global OOMs on 17.10 killed the Orchestra API while FFmpeg render processes consumed memory and swap.
- **Рестарт Orchestra больше не теряет первый ход Claude-агента и не сообщает родителю ложный провал** (`app/backend_claude.py` `_convert`, `app/session.py` `_handle_event`, `app/session_cost.py` `adopt_session_id`, `app/manager.py` `auto_resume_all`/`restart_notice_text`; V-919). Claude отдавал id сессии только в `ResultMessage` в конце хода, а `auto_resume_all` брал лишь строки с `session_id IS NOT NULL`, поэтому агент, у которого рестарт оборвал первый ход, молча не возобновлялся: при рестарте 17.10 09:17 UTC так выпали 2 из 5 бежавших агентов (`feat-lossless-restart`, `bench-review-big`), хотя транскрипт CLI уже лежал на диске. Теперь id берётся из `system/init` в начале хода и сразу сохраняется (базовая стоимость новой сессии сбрасывается тем же путём, что и в конце хода); строка `running`/`interrupted` без id всё равно возобновляется, а в уведомление о рестарте подставляются сообщения оборванного хода. Родитель больше не получает «Turn failed … interrupted_by_orchestra_restart» за ход, который продолжается сам: сигнал V-680 пишется только если агента не удалось поднять или не дошло уведомление.
- **Фоновое run-задание переживает рестарт и усыновляется следующим процессом** (`app/bg_jobs.py` `_run_exec`, `_adopt_run`, `_RUN_WRAPPER`, `restore_from_db`, `shutdown`; V-919). Вывод run-задания идёт в `data/bg_runs/<id>.out`, код выхода записывает обёртка-shell в `<id>.rc`; штатный shutdown такой процесс не убивает, а при SIGKILL/OOM он и так живёт (`KillMode=process`). Новый процесс находит лидера по pid и времени старта, дожидается его и доставляет результат с настоящим кодом выхода вместо «[Background job INTERRUPTED] … повторный запуск не выполнялся». INTERRUPTED остаётся только когда процесс погиб, не записав код, и для строк, созданных до V-919 (там прежний путь V-915). Известная цена: первый рестарт на новый код идёт ещё старым `shutdown`, он задания убивает.
- **Остаточные worktree `dynamic_workflow` удаляются после прерывания процесса** (`app/workspace.py`; V-920). Startup/periodic уборка распознаёт `wf-*`, сверяет run-id с `data/workflow-runs/` и удерживает `.run.lock` на время уборки: активный или неопознанный прогон остаётся, изменённые, untracked и ignored файлы неактивного сначала попадают в `orphaned-workspaces` (кроме приватных/служебных файлов и пересобираемых директорий `.venv`, `venv`, `node_modules`, `.cache`, `.mypy_cache`, `.ruff_cache` и директорий с `pyvenv.cfg`). `workspace.json` перечисляет исключённые пересобираемые пути. Затем worktree удаляется через `git worktree remove --force`. Триггер: рестарт 15.10 оборвал три вызова V-19; startup уборка пропустила их как dirty.
- **Процесс run-задания не переживает вердикт INTERRUPTED** (`app/bg_jobs.py`, `app/db.py`; V-915). Юнит работает с `KillMode=process`, поэтому если прежний процесс Orchestra умер, не дойдя до `BgJobManager.shutdown` (остановка зависла и была оборвана), дочерние группы процессов `run`-заданий оставались жить с оборванным stdout, а новый процесс при `restore_from_db` слал агенту «Прерван рестартом… повторный запуск не выполнялся» — агент перезапускал команду, и старая копия писала в те же файлы. Теперь `_run_exec` записывает в конфиг задания `_process` (pid и время старта из `/proc`, `bg_record_process`), а `restore_from_db` перед уведомлением останавливает эту группу (SIGTERM, затем SIGKILL) через `_reap_orphan_run`: проверяются совпадение времени старта (либо лидера уже нет при живой группе — pid не переиспользуется, пока он чей-то pgid) и в тексте INTERRUPTED сообщается, что именно с процессом случилось. Присоединиться к живому процессу нельзя — его канал вывода уже потерян, поэтому выбрано «убить и честно сообщить». Известный предел: задания, созданные до этого изменения, процесс не записывали; для них сообщается «процесс не был записан», группу остановить нечем. Триггер: рестарты 17.10 в 09:22 и 09:36.
- **Claude tasks in `dynamic_workflow` and the measurement adapters get Bash behind the managed filter** (`scripts/wf_adapters.py` `_claude_tools`/`_claude_bash_settings`, new `scripts/wf_bash_hook.py`; V-913). `run_claude` with `tools="all"` and `network=True` now offers `Bash` and passes `--settings` with a PreToolUse command hook that runs the same `_classify_bash_payload`/`_make_pretooluse_hooks` classifier as managed workers (V-773); a forbidden command (`rm -rf`, `find -delete`, `curl | sh`, ...) is denied with the same reason, and any hook crash exits 2 (blocked), never open. `tools="read"` and `network=False` keep Bash closed (a shell could still curl without a sandbox). Trigger: in V-906 all 31 Sonnet answers said "not reproduced" because Bash was closed for Claude but open for Luna, so the phrase was never tested on Sonnet. Python change in `scripts/`: used by the next `dynamic_workflow` run, no restart of the service needed for the hook itself.

### Changed
- **Explainer videos default to the light "paper" style with a quiet music bed** (`scripts/video_artifact/make.py` `--theme`/`--no-music`/`default_bed`, new `video-paper.css` and `paper.js`, `video.css` → `video-dark.css`, `manim_voice.py`, `sound/sfx.py` type `bed`, `sound/library.json`, `sound/mix.py`, skill `video-artifact.md`; V-917). HTML scenes now render on `#f6f7f9` with Manrope/JetBrains Mono, no step heading, one caption line under a hairline, a 3 px progress bar and a short caption blur, added by `Paper.chrome` after every `P.seek`; `--theme dark` keeps the previous frame for old scenes. `paper.js` gives scenes pure-in-time helpers: torn-paper picture with grain, vignette and wobble (`Paper.picture`), roller-brush reveal, camera push-in, an inverse "miniature" transform for a match cut into the diagram, and typing with a block cursor. Manim's `VoiceScene` palette and font follow the same theme (`VIDEO_ARTIFACT_THEME`). Every build now mixes the kit's default `bed` ("Long Ambient Pad", indigo.cloud, CC0, Freesound 254856, first 2 s trimmed because its fade-in failed the silence check) under the voice, ducked during speech and looped with a 1 s crossfade; key clicks and other events work without passing `--music`, and `--no-music` restores voice-only. With a bed there is no silence between phrases, so the onset check reads the voice stem; `qa.py` already proves the stem matches the MP4. The skill states the style rules: painted opening/closing pictures, two or three large objects per frame, two meaning colors (blue known, orange hidden/wrong), only real numbers, and the order of presenting data. Trigger: the owner compared the NIST-curves video with our V-904/V-912 demos and chose this style as the standard. Owner decision, 2026-10-17. Known tradeoff: the sound kit must be rebuilt (`sfx.py kit`) to contain the bed, otherwise a build stops and names that command or `--no-music`; existing Manim scenes that hard-code Manim's `WHITE` text need `--theme dark`.

### Added
- **The platform keeps AGENTS.md and CLAUDE.md of every project one file plus a symlink** (`app/rules_link.py` `reconcile`/`sweep`, `Manager._periodic_rules_link`; V-902). At startup and every 6 hours it checks the pair in the root of each project that has sessions: already a symlink (or `CLAUDE.md` = `@AGENTS.md`) → nothing; byte-identical copies or a single file → the other name becomes a symlink (AGENTS.md is canonical; a lone CLAUDE.md stays canonical, no rename), committed locally with only those two paths, and rolled back to the original bytes if the commit fails; different copies → nothing is written and the project's orchestrator gets an alert with both sizes and the fix, repeated daily (immediately when the kind of problem changes) until fixed. Where symlinks are unavailable (`core.symlinks=false`, Windows) an exact copy is kept instead. The change is refused (and reported the same way) when the files have uncommitted changes, HEAD is detached or not on the mainline, or a merge/rebase is in progress, so a project tree is never left dirty for `merge_worker`. Nothing is pushed. Trigger: on 17.10 three projects held diverged copies (133 403/120 158 B, 105 245/99 053 B, 41 118/36 018 B) and three had only CLAUDE.md. Owner decision, 2026-10-17. Python change: takes effect after a restart. Known tradeoff: a git symlink checked out as a text stub on a no-symlink platform is left as is.

### Changed
- **Project rules are a small core plus a topic registry; AGENTS.md and CLAUDE.md are one file** (`.orchestra/pipelines/default/prompts/modules/project-maintenance.md`; V-900). The shared maintenance rule now says the root rules file is the core: the project's essence, small always-needed rules not worth a file, and a "topic → file → when to read" registry, while what is needed only sometimes lives in topic files; new rules and dated owner decisions go to topic files with one line in the core, the core has a 16 KiB ceiling (half of the harness's 32 KiB truncation point) and shrinks by moving content out rather than raising the ceiling, and AGENTS.md/CLAUDE.md must be a file and a symlink, not two copies. Topic files must live where runtimes do not auto-load them (e.g. `.orchestra/kb/rules-*.md`), never in `.claude/rules/`, which Claude Code loads in full (measured about 189 KB per turn instead of about 133 KB). The earlier owner-decision paragraph was merged into it, not duplicated. Trigger: one project's core grew from about 64 KB back to about 139 KB, and three projects had a diverged AGENTS.md copy. Owner decision, 2026-10-17.

### Changed
- **Candidate evaluation judges licenses by real use and requires real samples for media** (`.orchestra/pipelines/default/prompts/modules/code-quality.md`; V-894). A non-commercial license no longer rules out a candidate for personal or internal use; the restriction is recorded as a fact. The text lives in the module delivered to the orchestrator, sub-orchestrator, worker and full-cycle roles (not only the one doing research). Voice, image and video research must bring samples produced by the researcher plus public demos, not vendor scores. Trigger: a voice study discarded three candidates as non-commercial although the installation is used personally. Owner decision, 2026-10-16.

### Added
- **Role catalog states who can spawn** (`app/manager.py` `_fmt_role_catalog_entry`, `.orchestra/pipelines/default/pipeline.yaml`; V-889). Every entry in the orchestrator's "Available worker roles" now carries a "Can spawn" line generated from that role's `can_spawn` (the field the spawn check uses), so it cannot drift from enforcement. The `worker` and `full-cycle` descriptions now say which to pick: `worker` takes one bounded task and cannot spawn; `full-cycle` runs research, plan, implementation and verification with the full module set and can spawn sub-workers. Owner decision, 2026-10-16. Python change: takes effect after a restart.

### Changed
- **Оценка шага чеклиста обязательна** (`app/checklists.py:validate_items`, `update_checklist`, модуль task-management; V-887). Решение владельца 15.10.2026. `update_checklist` отклоняется, если у нового или изменённого шага нет положительной оценки в минутах; отказ перечисляет такие шаги и что прислать. Шаг с неизменным текстом сохраняет прежнюю оценку, поэтому вызов, который только отмечает выполненные шаги или текущий, не требует переоценки. Нулевая и отрицательная оценка теперь тоже отказ. Known tradeoff: у старого чеклиста с null-оценками первое же обновление потребует прислать оценки для этих шагов; переименование шага считается новым шагом.

### Fixed
- **Dynamic workflow schema replies, task identities, and resume writes are handled safely** (`scripts/wf_run.py`, `app/mcp_stdio.py`; V-916). Schema validation extracts JSON from a code fence or surrounding prose before retrying; declarative results carry task IDs and item metadata; a per-run process lock rejects a concurrent `--resume` with the owner's PID before manifest writes. Trigger: V-909 burned 47/70 calls on wrapped valid JSON, lost item-to-result mapping, and observed concurrent resume processes race on `manifest.json.new`.
- **Агентские cgroup ограничивают потребление swap** (`app/agent_cgroups.py`; V-897). `agents/memory.swap.max` идемпотентно выставляется в четверть доступного host/service swap, но не выше 1 GiB; при 16 GiB системного swap потолок равен 1 GiB. Если ядро не предоставляет swap controller или недоступен `SwapTotal`, пишется warning, а memory/cpu/io лимиты всё равно применяются. Trigger: 16.10 агентская группа накопила 12.1 GiB swap и заполнила системные 16 GiB.
- **Tera synthesizes whole sentences instead of comma-sized pieces** (`scripts/video_artifact/tts_worker_tera.py`: `split_pause_segments`, `compose_audio`; `make.py` cache key `audio-v4`; V-890). V-878 cut phrases at `, ; : —` and inserted fixed 0.33/0.63 s silence, so every piece got a falling sentence-final intonation and the silence did not shrink with `--rate` (University's V-23 measurement at rate 1.2: 25.8 pauses ≥0.3 s per minute, median 0.66 s). Now only `[seconds]` markers and sentence ends (`. ! ? …`; decimals and common abbreviations do not cut) split; the pause after a sentence is `0.42/rate` minus the model's own trailing silence, never negative; sentences of ≤3 vowels are glued to the next one because the duration predictor stretches a lone short utterance 2–3×. Supersedes the punctuation-pause part of the V-878 entry. Idea and defaults follow the supertonic-android Tera pause handling; no code copied.
- **Manim text cache is invalidated when the bundled fonts change** (`scripts/video_artifact/make.py`: `fresh_text_cache`; V-888). Manim keys cached text SVGs by font name only, so images rendered with DejaVu before CMU Serif was bundled (V-880) were reused under the name «CMU Serif» and captions overflowed the frame until `texts/` was deleted by hand. Each Manim render, preview and timing dry run now compares a SHA-256 of `fonts/*.ttf` with `<media>/texts.fonts`; a missing or different stamp deletes `<media>/texts`, so already poisoned projects heal on the next build. Known limit: the fingerprint covers only fonts bundled in `fonts/`, not system fonts or a TEXT_FONT that resolves to a system file.
- **Агент не застревает в `waiting`, когда его последний watcher закончился молча** (`app/bg_jobs.py`; V-886). Истечение или сбой file/command/ssh/cron-наблюдателя (в том числе при `restore_from_db` после рестарта) только менял строку джоба, а статус `waiting`, выставленный в конце хода из-за активных джобов, никто не снимал: `merge_worker` отвечал «Worker is waiting» часами. Теперь `_job_ended` при отсутствии других активных джобов будит цель сообщением «[Background job EXPIRED/FAILED] … nothing else will wake you»; штатный конец расписания cron лишь возвращает сессию в IDLE без пробуждения; при наличии другого активного джоба ничего не происходит. Триггер: ai-table-gm ждал file-джоб с маркером RIG_DONE, рестарт убил писавший процесс, джоб истёк в 13:35 UTC. Покрыт только случай, когда цель ещё в `waiting`; джоб `run`, `merge_watch` и прочие пути с уведомлением не менялись.
- **Tera raw phrases no longer clip** (`scripts/video_artifact/tts_worker_tera.py`, `make.py`; V-885). The model returns floats beyond ±1.0 and `save_wav` hard-clipped them: 57–203 full-scale samples per 3–6 s phrase, 0.04 % over University's 45-phrase film. `level_phrase()` now levels each phrase to RMS −20 dBFS with a −3 dBFS peak ceiling; the Tera cache key moved to `audio-v3`, so old clipped clips are regenerated. Kokoro and Vosk measured clean (peaks −2…−6 dBFS) and are untouched. Known tradeoff: short high-crest phrases stay quieter than the rest because the peak ceiling binds.

## v2.46.0 — 2026-10-15 — voice input, checklists with time estimates, mechanical rules, evidence-gated merges

### Highlights

- **Voice input in the dashboard.** Recordings are saved locally while you speak, transcribed on the server, and sent once to the agent that was selected when recording started.
- **Worker checklists with time estimates.** Each worker keeps a durable step list shown in the INFO panel; steps accept a minute estimate that is compared with the time actually spent, and reminders follow the estimate.
- **Dashboard design system.** Model colors, statuses and surfaces now come from one source (`design-system.css`, `theme.js`) instead of per-screen copies.
- **Rules enforced by mechanism, not by trust.** A shell guard rejects long `sleep` calls and recursive `find`/`grep -r` before the command runs; violations are recorded. It is a narrow policy, not a sandbox.
- **Merge gate with mutation checks.** Mapped tests run before a merge, and changed tests must fail against the pre-change sources; failed or inconclusive required gates block the merge. Merge stages are timed.
- **Orchestrators talk across projects.** Project orchestrators can message each other, and deliveries show whether quota is holding dispatch.
- **Partial (sparse) worker worktrees.** New worker worktrees are created without a full checkout, which keeps large repositories fast to start.
- **Quota gate override until a chosen time.** The dashboard can lift a worker quota gate until a date and time picked in the browser's time zone.
- **Local Russian voice-over for explainer videos.** `video-artifact` uses the local TeraTTSv2 voice with automatic stress, timed pauses, Manim scenes with 3Blue1Brown-style defaults, and a bundled CMU Serif font.
- **Live chat activity.** Streaming generation and running-tool output appear in the dashboard chat as they happen, and attachments show as compact chips with progress.
- **Safer merges of `.gitignore`.** Append-only conflicts in `.gitignore` are merged automatically instead of blocking the squash.
- **Refreshed public guides.** README (English and Russian) and CONTRIBUTING describe current workflows, setup and work in progress.

Removed in this release (internal MCP tools and API, not part of the install or configuration surface): project-memory search (agents use `rg` over `.orchestra/kb/` and `.orchestra/tasks/`), the suggested-task cards, the `idle` background-job type and the `vps-deploy` skill. Details are in the entries below.

### Changed
- **Public project guides refreshed around current workflows** (`README.md`, `README.ru.md`, `CONTRIBUTING.md`; V-879). Replaced stale dated comparisons, metrics, and private-project examples with user-facing team scenarios and capabilities cross-checked against current behavior; corrected the contribution clone URL and test command. Trigger: the published overview and contributor setup no longer matched the repository.
- **Voice transcription sends as one message and uses a compact status chip** (`app/static/js/chat.js`, `app/static/css/style.css`, `app/static/js/i18n.js`; V-874). After transcription, the existing draft and marked voice text are sent once to the agent captured at recording start; recovered recordings follow the same path. The short progress/error row now sits above the input, and saved audio remains available until the send succeeds. Trigger: the owner asked for automatic delivery and a compact file-chip style status instead of reviewing the transcript before sending.

### Added
- **CMU Serif is bundled; Manim captions wrap by real font width; a missing font fails the build** (`scripts/video_artifact/manim_voice.py`, `fonts/cmunrm.ttf`, `cmunbx.ttf`, `OFL-CMU-Serif.txt`; V-880). Fixes V-878 follow-up: the VPS had no CMU Serif, Pango substituted wider DejaVu Sans and 66-character caption lines overflowed the frame. Fonts register like Manrope; `require_font` raises instead of silently substituting; `VoiceScene.wrap_caption` measures each line (`CAPTION_MARGIN`, replaces `CAPTION_CHARS`). Trigger: University's part3 frames.
- **Дизайн-система дашборда: один источник цветов моделей, статусов и поверхностей** (`app/static/css/design-system.css`, `app/static/js/theme.js`, `docs/design-system.md`, dashboard `app.js`/`chat.js`/`usage.js`/`analytics.js`/`quota-lines.js`/`style.css`, `login.html`, `app/deps.py`; V-876). Токены (`--model-*`, `--provider-*`, `--status-*`, поверхности, текст, смысл, акцент) и компоненты `ds-model`, `ds-status`, `ds-chip`, `ds-btn`, `ds-card` вынесены в `design-system.css`; `theme.js` определяет семейство модели по id, псевдониму или подписи (`modelFamily`) и отдаёт `var(--model-…)` для DOM или вычисленный цвет для canvas/SVG. Один бейдж модели теперь в списке агентов, карточках «Инфо», вкладках оркестраторов (точка), карточках чата и аналитике; полосы графика лимитов и линии истории берут те же токены. Hex, точно равные токену, заменены на `var()` (style.css ≈200, встроенные стили JS ≈185) без смены значений; `_BUILD_GLOBS` следит и за новым CSS. Trigger: владелец увидел, что справа модели цветные, а в «Инфо» серые; причина — `_MODEL_COLORS` держал устаревшие id (`claude-opus-5[1m]`), поэтому Opus падал в цвет поставщика, а Luna, Sol, Astra и Haiku красились одним зелёным, Claude же был голубым в полосе лимитов, оранжевым на графике квот и фиолетовым в аналитике.
- **Tera speech preserves automatic stress beside manual markers and inserts timed pauses** (`scripts/video_artifact/tts_worker_tera.py`, `make.py`; V-878). RUAccent now processes each unmarked word even when another word in the phrase has `+`; comma/colon/semicolon/dash pauses are 0.33 s, sentence punctuation pauses are 0.63 s, and `[seconds]` adds an explicit silence segment. Silent `say: ""` steps require positive `hold`, and runs of more than two numeral tokens warn during checks. Trigger: University audio measurements found missing stress on unmarked words, nearly absent internal punctuation pauses, and no silent beat support.
- **Manim voice scenes expose 3B1B-like camera and typography defaults** (`scripts/video_artifact/manim_voice.py`; V-878). `VoiceScene` now inherits `MovingCameraScene` and defaults to CMU Serif on `#000000`; subclasses can override `TEXT_FONT` and `BACKGROUND_COLOR`. The default speech rate is 1.0. Trigger: University comparison found our delivery rate ~30% above 3Blue1Brown and noted the dark-blue background and fixed Manrope scene text.
- **Orchestrator checks whether a reported number supports the claim** (`.orchestra/pipelines/default/prompts/roles/orchestrator.md`; V-867). Comparative, causal, trend, and generalized figures are reported only after checking sample N/unit, denominator, comparable control, and noise; exact finite-set counts instead state their coverage. Trigger: owner decision 2026-10-15 to avoid elevating numerically precise but unsupported claims.
- **Checklist estimates are compared with persisted step time** (`app/checklists.py`, `app/session.py`, `app/routes/sessions.py`, `app/mcp_stdio.py`, dashboard `app.js`/`style.css`; V-875). Each step accepts an optional minute estimate; actual time accumulates across every interval when the step is current, including returns. Estimated steps trigger the once-per-turn reminder after exceeding their estimate; unestimated steps keep the five-minute reminder. `estimate_accuracy_report` groups completed steps by worker model for a period and reports count, unestimated count, median actual/estimate ratio, and interquartile spread. Trigger: owner requested a one-week calibration experiment to compare worker estimates with elapsed step time.
- **Orchestrator task cards support owner reasons and rejection messages** (`app/routes/sessions.py`, `app/task_proposals.py`, dashboard `app.js`/`i18n.js`/`style.css`; V-871). Approving or rejecting a card sends one durable message to its proposing orchestrator; an optional owner reason/instruction is included in that same message, with the decision intent bound to its idempotency receipt. Trigger: the owner asked to explain approvals/rejections and have explicit rejections reach the orchestrator.

### Fixed
- **Статус в шапке «Инфо» и живое обновление бейджа переводятся** (`_paintAiStatus`, `_applyLiveAgentStatus` в `app/static/js/app.js`; V-876). Шапка писала сырой `● running`, а бейдж в списке после живого обновления статуса — английское `running` вместо `⚡ выполняется`; теперь оба используют тот же словарь иконок и `T(status)`, а `status-waiting`/`status-broken` получили цвет. Trigger: аудит единого стиля.
- **Squash merges union append-only `.gitignore` conflicts** (`app/workspace.py`; V-872). When both branches preserve the merge-base lines and append entries, target-side entries followed by worker-side entries are merged with duplicate appended lines removed. If another file conflicts, the result still reports that file as CONFLICT; non-append `.gitignore` edits remain conflicts. Trigger: 10 katya-work merges from 08.10–15.10.2026 conflicted because workers appended different ignore entries.
- **Расшифровка chunked WebM не требует duration в заголовке** (`app/routes/tg.py`; V-870). Если ffprobe распознаёт формат, но не может сообщить длительность MediaRecorder WebM с timeslice, сервер вычисляет её полным декодированием аудиопотока в ffmpeg; те же проверки конечного положительного значения и пятиминутный лимит остаются применимы. Trigger: настоящий Chromium MediaRecorder WebM без Duration вызывал `invalid audio duration` и 400 до отправки расшифровщику.
- **Task proposal summaries display in full** (`app/static/css/style.css`; V-871). Removed the two-line clamp and allow long text to wrap inside proposal cards. Trigger: the owner saw proposal summaries truncated with an ellipsis on the live INFO panel.
- **Rebuild committed Tailwind output for the INFO panel** (`app/static/css/vendor/tailwind.css`; V-869). Regenerated the compiled utility CSS after the V-858 dashboard templates began using additional Tailwind classes. Trigger: the `test_committed_css_matches_current_sources` CI check found the generated stylesheet out of sync.
- **Delivery receipts state whether quota is holding dispatch** (`app/mcp_stdio.py`, `app/initial_deliveries.py`, `app/quota_queue.py`; V-866). Spawn/send receipts for ordinary queued or submitted deliveries say dispatch is proceeding without a quota hold; `WAITING_QUOTA` receipts say delivery is deferred by the quota gate and retain its reason/estimate. The initial-delivery API's existing `next_action.message` carries the same distinction for `retry_initial_delivery`. Trigger: an orchestrator mistook `state=QUEUED` for quota-gated delivery although quota was open and both workers started seconds later.
- **Mutation-gate verdicts use changed test nodes only** (`app/merge_test_gate.py`; V-861). Added/modified test functions are isolated from unrelated tests in the same module, and the mutation run applies Orchestra's `browser`/`live_probe` exclusions. If every changed test is excluded or a changed test node cannot be identified, the mutation result is `SKIPPED` with a reason; a changed non-browser test that passes against target sources still fails the gate. Trigger: a helper and four browser tests were added together, so AST fallback ran 14 unchanged green tests and reported `tests_not_guarding_source`.
- **Снятие quota gate до выбранного времени** (`app/quota_gate.py`, `app/routes/system.py`, `app/main.py`, dashboard `quota-lines.js`/`i18n.js`/`style.css`; V-862). Dashboard отправляет выбранную в локальном поясе браузера дату/время как zoned ISO timestamp; API сохраняет UTC expiration в `kv`, восстанавливает его после запуска и ограничивает снятие 14 сутками. Старый `minutes` API сохраняется, а «вернуть гейт сейчас» удаляет сохранённое окончание. Триггер: владельцу понадобилось снять гейт до конкретного срока дольше прежних 6 часов.

- V-863: red unread dots on orchestrator tabs work again (`_markUnreadTurns`, `_renderOrchestrators`, `refreshSessions` in app/static/js/app.js). The only detector sat in `refreshSessions`, comparing the old `orchData` with a fresh list; the 60 s `_pollRegister('orchestrators', loadOrchestrators)` poll replaced `orchData` wholesale first, so the transition was never seen. Detection now runs before every replacement and also fires when `last_turn_ts` advances (turns shorter than the poll gap). Test: `test_unread_dot_survives_orchestrator_list_poll`; the old test lost two source-text asserts.
- **Сглажены случайные падения линии фактического расхода** (`app/static/js/quota-lines.js`; V-859). История внутри одного окна отображается накопительным максимумом, а при продвижении `resets_at` начинается новая последовательность, поэтому дрожание процента провайдера не выглядит возвратом квоты, а настоящий сброс остаётся виден.
- **Прерывание хода не считается ошибкой, а старый listener не завершает новый ход** (`app/session_turns.py`, `app/session.py`; V-856). При `stop_reason="interrupted"` метаданные CLI могли содержать `errors=["error"]`, из-за чего штатный stop/steer логировался как `turn FAILED: error`. Done-callback завершившегося per-turn listener также мог сработать после запуска следующего хода и принять его `RUNNING` за смерть listener. Прерывание теперь остаётся статусом; callback устаревшей задачи не меняет состояние текущего хода, а настоящие сбои продолжают логироваться как ошибки.

### Removed
- **Карточки предложенных задач и сводка дочерних работ в INFO** (`app/main.py`, `app/mcp_stdio.py`, `app/routes/sessions.py`, dashboard `app.js`/`i18n.js`/`style.css`, `app/schema.sql`; V-873). Удалены MCP-инструмент, маршруты и UI карточек; при старте `task_proposals` удаляется. INFO показывает только воркеров с чеклистом; свёрнутый блок дочерних работ удалён. Причина: владелец решил, что карточки добавляют клики, а идеи уже обсуждаются в чате; дочерний блок дублировал список сессий и сам сворачивался при обновлении. Возвращаться к карточкам имеет смысл, если оркестратор будет публиковать предложения в своём чате.

### Added
- **Инфопанель, одобряемые предложения и долговечный чеклист воркера** (`.env.example`, `app/schema.sql`, `app/main.py`, `app/checklists.py`, `app/task_proposals.py`, `app/mcp_stdio.py`, `app/routes/sessions.py`, `app/session.py`, `app/session_turns.py`, `app/templates/dashboard.html`, `app/static/css/style.css`, `app/static/js/app.js`, `app/static/js/i18n.js`, `.orchestra/pipelines/default/prompts/modules/task-management.md`; V-858). Первая вкладка FILES/TASKS/JOBS теперь INFO; ширина меняется ручкой, сохраняется в localStorage и не прыгает при выборе JOBS (раньше `switchLeftTab('jobs')` выставлял `380px`, а затем сбрасывал ширину). MCP `propose_task` проверяет право оркестратора на сервере; карточки переживают перезапуск. Владелец одобряет карточку — платформа создаёт один durable message delivery в чат того же оркестратора и не запускает воркер. Воркеры сохраняют чеклист по session/task id, его N из M остаётся между ходами; агентский список и INFO показывают тот же счётчик. Пятиминутное напоминание ограничено `ORCHESTRA_CHECKLIST_REMINDERS` и датой 22.10.2026 включительно, каждый вызов пишется как `checklist_reminder`, а следующий `checklist_update` связывается тем же turn key для подсчёта отклика. Trigger: сессии хранили только live percentage, который очищался при конце каждого хода; JOBS менял ширину панели сам, а follow-up запуск не имел владельческого подтверждения.
- **Голосовой ввод дашборда сохраняет запись и отправляет расшифровку** (`app/static/js/chat.js`, `app/static/css/style.css`, `app/static/js/i18n.js`; V-860/V-874). MediaRecorder пишет аудиочанки в IndexedDB по мере записи; метаданные сохраняют исходного агента и scope, поэтому после перезагрузки запись отправляется тому же агенту. Строка над полем показывает загрузку, расшифровку и ошибку с повтором; на ошибке аудио остаётся для повтора или удаления. Если IndexedDB недоступна, микрофон и отправка продолжают работать с предупреждением о несохранённой записи. После распознавания введённый текст и пометка «Расшифровка голосового» отправляются одним сообщением без второго клика; используется существующий `POST /api/transcribe` без `send=true`, затем обычный `/send` адресату из черновика. Триггер: владелец терял запись при уходе со страницы и не видел процесс; позднее он попросил компактный статус и автоматическую отправку после расшифровки.
- **Блокировка долгих shell-пауз и рекурсивного поиска** (`app/shell_policy.py`, backend Claude/Codex/Grok и harness; V-846). Единый guard отклоняет `sleep` дольше 5 секунд, рекурсивные `find`-поиски и `grep -r/-R`, когда `rg` доступен в PATH; без `rg` эти поиски остаются разрешены, чтобы у агента сохранялся работающий fallback. Короткие проверки и обычный grep в пайпе разрешены. `find` с временными/метаданными фильтрами или действиями вроде `-mtime`, `-newer`, `-exec`, `-printf` проходит этот performance guard, поскольку его семантику `rg` не заменяет; существующий Claude safety guard отдельно отклоняет `find -delete`. Claude и Grok проверяют запрос до запуска shell-tool. Codex code-mode не вызвал настроенный PreToolUse hook для вложенного `exec_command`, поэтому его per-session PATH содержит обёртки, которые проверяют процесс-родителя: блокируют прямую команду Codex app-server и его `bash -c`, пропуская вызовы из Python/Node/make и исполняемых shell-скриптов. Codex сохраняет `approvalPolicy=never`; интерактивные approval-запросы не используются. Каждое срабатывание пишется в session log как `policy_violation`. Триггер: в V-844 за неделю найдено 4,786 ч явных shell-пауз и повторяющиеся рекурсивные поиски, хотя подсказка использовать `bg_create` уже была в промпте.

### Fixed
- V-854: `_streamRenderTick` (app/static/js/chat.js) resyncs `LivePacer` when `streamPending` grew without a `push`. Before this, the pacer's target stayed below the backlog: the RAF loop kept running and never drained the text. The CI browser job hung on `test_stream_updates_preserve_chat_selection`, and the rest of the job was cut off by the timeout. The test now injects `LivePacer` from live-activity.js.
- **Keep subtitle punctuation and normalize Vosk-unsupported glyphs before TTS** (`scripts/video_artifact/video_text.py`, `make.py`, `manim_voice.py`; V-849). Manim and HTML captions now preserve an explicit `sub` exactly while hiding stress markers only in fallback `say`. Russian speech normalizes typographic quotes, dash variants, ellipsis, and nonbreaking spaces to supported forms; other unsupported symbols fail during step validation with the step number and glyph. Trigger: formula subtitle `W·X + b` lost its plus, and Vosk's phoneme parser received guillemets and other unsupported punctuation.
- **Merge profile records stage durations and bounds waits for busy workers** (`app/merge_operations.py`, `app/merge_test_gate.py`, `app/routes/sessions.py`, `app/mcp_stdio.py`; V-848). Each durable merge stores snapshot/admission, pre-operation, queue, acceptance, test gate, mutation gate, Git, and finalization durations in `result_json.phase_durations_ms`; skipped stages stay `null`, and repeated attempts accumulate measured durations. A running worker gets up to 60 seconds to publish turn completion before admission proceeds; non-running busy states refuse immediately, and races after admission/operation creation are bounded too. The legacy session route also waits up to 60 seconds while preserving its branch/HEAD pin from before the wait, so commits, history rewrites, and branch changes during the wait retain their prior drift handling. Branch switching retains its original turn-completion wait. Trigger: V-844 recorded three `WAITING` runners consuming 48.4 minutes; one-week logs show a 40.17-second p95 from DONE `send_message` tool call to turn end, 38.74 seconds from its result to turn end, with only three of 444 paired turns finishing between 60 and 90 seconds.
- **Параллельный pytest ограничен Orchestra** (`scripts/run_tests.py`, `app/merge_test_gate.py`, CI; V-847/V-855). Полный локальный runner и CI явно включают два xdist worker-а `loadscope`; merge gate включает их только для linked worktree Orchestra. Root `pyproject.toml` не задаёт глобальные pytest addopts: гейт задаёт проектные `rootdir` и `-c`, используя временный пустой ini для проектов без pytest-конфига. Это не позволяет pytest из вложенных чужих worktree унаследовать Orchestra `-n/--dist`. Полный прогон V-847 сохранил 4 460 passed / 54 skipped / 4 deselected; xdist занял 6:29 против 12:25 serial (−47.8%). Диагностические screenshots сохраняются в `tmp_path`, CLI directory encoding нормализует `_`, тесты изолируют broker and bridge state, а merge gate разбирает xdist worker verdicts. Триггер: тест-гейт чужого worktree выбрал `/home/kesha/orchestra/pyproject.toml` и упал с `unrecognized arguments: -n --dist=loadscope`.
- **Повторное назначение той же ветки восстанавливает task_run после освобождения привязки** (`app/tm.py`, `app/routes/sessions.py`, `app/mcp_stdio.py`; V-843). Идемпотентный `switch_worker_branch` теперь атомарно проверяет актуальную задачу, привязывает её обратно только если она свободна в очереди (или уже принадлежит этой сессии), и создаёт отсутствующий открытый task_run; устаревший HEAD по-прежнему отклоняется проверкой merge, а здоровый no-op сохраняет прежнюю форму ответа. Триггер: после `PARTIAL` с `binding_released` задача возвращалась в `new`, но повторный switch на ту же ветку завершался `already_current` без открытия нового task_run.

### Added
- **Local TeraTTSv2 Russian voice for video-artifact** (`scripts/video_artifact/make.py`, `tts_worker_tera.py`; V-852). Russian synthesis defaults to the pinned local ONNX model and `ru_m1`; `--voice` selects `m1`, `m5`, `f1`, or `f2`. One CPU model serves concurrent phrases, Tera's bundled RUAccent-derived stress pass replaces the separate RUAccent worker, Russian numbers remain spelled out to preserve grammatical case, and Vosk remains selectable with `--tts-engine vosk`. Phrase cache keys include the engine revision, voice, rate, and stress mode. Trigger: the owner selected TeraTTSv2 after comparing it with the previous Vosk samples and then chose `ru_m1` as the default voice.
- **Compact chat upload chips** (`app/static/js/chat.js`, `app/static/css/style.css`; V-842). Upload attachments use a capped, internally scrollable grid with file-type icons, image thumbnails, sizes, remove and download controls, upload progress, and visible errors. Long names show their beginning and ending portions, including the extension; download and remove controls have separate positions. A bottom shadow signals further files, and phone widths collapse side panels so the composer remains usable. Trigger: a batch of 11 attachments occupied five large rows above the chat input.
- **Bound worker log snapshots at the database query** (`app/routes/sessions.py`, `app/mcp_stdio.py`; V-841). `get_worker_logs(limit=N)` now sends `limit=N` to the server, and `/api/sessions/{name}/logs` applies a bound only when `limit` is explicitly supplied. An omitted limit keeps the former up-to-5,000-row snapshot for raw transcripts and compaction; `before_id` retains its 500-row default, while omitted-limit `after_id` keeps its former incremental query. Rows are selected through the existing `(session_id, id DESC)` index and returned chronologically. Trigger: worker log requests fetched and serialized up to 5,000 rows before MCP discarded all but a small tail; making the new limit unconditional would truncate compacted transcripts.
- **Partial (sparse) worker worktrees for every project** (`app/sparse_worktree.py`, `app/workspace.py`, `app/pipeline.py`, `.orchestra/pipelines/default/pipeline.yaml`, `scripts/sparse_convert.py`; V-821). New worker worktrees are created with `git worktree add --no-checkout` and a per-worktree non-cone sparse rule from `defaults.worktree.sparse`: `artifacts/` and `.orchestra/tasks/` stay out, the task's own directories (`.orchestra/tasks/{id}`, `artifacts/{id}`, `artifacts/task-{id}`, `…-*`) come in by task number, `include` adds fixed directories (katya-work: `artifacts/task-2/tooling`), and `reference_scan` pulls in directories that tracked KB notes and tests mention (orchestra: KB links and test fixtures such as `.orchestra/tasks/224`, found by `git grep` at spawn, so a new fixture needs no list edit). Projects override by glob on the repository root; `enabled: false` gives a full copy; a failed rule setup falls back to a full copy instead of blocking the spawn. `switch_worktree_branch` and `promote_worktree_branch` recompute the own directories for the new task number from the rule stored in the worktree. `_clean_worktree_error` now recognises dirty paths that git cannot stage because they lie outside the sparse checkout (`git add -A` returns 0 and commits nothing for a modified tracked file there) and tells the worker which `git sparse-checkout add /<dir>/` to run, so `merge_worker` refuses with a way out instead of the old "commit or discard". `convert_worktree_to_sparse` and `scripts/sparse_convert.py` move existing worktrees over (dry run by default; refuses on modified or untracked files, a merge in progress or a process working inside; ignored and untracked files stay). The worker prompt (`git-workflow.md`) says to read absent history from the main checkout or `git show main:<path>` and to load a directory only when changing a file in it. Triggering case: the VPS disk reached 95% on 11.10.2026 with ~58 GB in katya-work worker copies. Measured on temporary clones: katya-work copy 4246 MB → 40 MB (+ own directories), seedon 1305 → 99 MB, orchestra 324 → ≈57 MB. Known tradeoff: a task that reworks an earlier result changes files that are not in the copy until `git sparse-checkout add`; in the 30-day replay that was 29% of katya-work tasks, 24% of seedon and 6% of orchestra tasks. Python changes take effect after a restart.
- **Accept scoped caller keys for durable file delivery** (`app/file_delivery_ids.py`, `app/mcp_stdio.py`; V-839). `send_file` and `send_files` now accept any non-empty `event_id`; non-UUID keys map deterministically to UUIDv5 using project scope and sender, while UUID keys keep their existing canonical identity for queued receipts. The internal `/api/tg/send_file` contract remains canonical UUID because the delivery table and receipt-status route use it as the durable storage key. Trigger: agents supplied readable retry keys such as `lada-kp27-0810`, which the MCP layer rejected before sending.
- **Retire historical managed skill copies across directory moves** (`app/prompting.py`; V-837). Skill cleanup follows Git renames when collecting approved historical hashes, so exact copies from the pre-`.orchestra` `pipelines/default/prompts/skills/` path are recognized. Refresh also removes orphaned temp files only when they match the injector's `.SKILL.md.<pid>.<8-hex>.tmp` naming pattern under a retired skill; tracked paths, symlinks, changed content, and unrelated temp files remain untouched. Trigger: V-819 removed `codex-debate` and renamed `explainer-video`, but copies from the old canonical path and an interrupted atomic write remained.
- **Fast video drafts, static Manim timing checks, build queue, and progress estimates** (`scripts/video_artifact/make.py`, `manim_timing.py`, `manim_voice.py`; V-835). Scenes can render selected stop frames before TTS, and supported Manim `self.left()` timings are analyzed before any frame render; unsupported Python falls back to Manim `--dry_run`. A host-wide `flock` queues builds, speech/frame/step progress includes ETA, and Deepgram matching normalizes common spoken numbers to digits while reporting omitted numerals separately from strict ordinary-word recall. Trigger: the 39-step University Manim draft/contact sheet appeared only after a 237 s full still render, and dry-run timing validation took 198 s.
- **Chat-ready export for interactive HTML artifacts** (`.orchestra/pipelines/default/prompts/skills/html-artifacts.md`; V-834). User-entered values are copied with field labels using one prominent button, with a selected-textarea fallback when clipboard access is unavailable; export is client-side without server storage, localStorage synchronization, or external requests. Trigger: the owner rejected public links and server storage as unsafe.
- **Live generation and running-tool activity in the dashboard chat** (`app/backend_claude.py`, `app/session.py`, `app/live_broker.py`, `app/task_output_tail.py`, `app/routes/sessions.py`, `app/static/js/live-activity.js`, `app/static/js/chat.js`; V-831). Claude partial messages are no longer filtered to `text_delta`: `input_json_delta` becomes `tool_input_stream` (tool id/name from `content_block_start`, keyed by parent and block index so sub-agents do not collide) and `thinking_delta` becomes `thinking_stream`, including the `estimated_tokens` counter the CLI sends when thinking text is omitted. The chat shows a card for the call being written — tool name, decoded argument text, character count, chars/s and elapsed time — replaced by the normal card when the persisted `tool` row lands. Every unanswered tool call shows a pulsing "running m:ss of m:ss" clock (Bash `timeout`, default 2:00, cap 10:00; elapsed only for tools without a timeout), and shell tasks (`local_bash`, foreground or background) show live output tailed from the CLI's `tasks/<task_id>.output` file. The SSE loop merges adjacent deltas of one block per ~100 ms tick, the broker keeps a capped tail of each open block so a reopened chat resumes it, and nothing partial is written to `logs`. Codex app-server 0.160.0 has no tool-argument delta notification, so Codex keeps its existing reasoning/output streams. Trigger: a 42 KB Bash heredoc took minutes to write with nothing visible, and running commands looked dead.
- **Parallel voice synthesis and incremental HTML rendering** (`scripts/video_artifact/make.py`, `tts_worker.py`, `tts_worker_en.py`; V-832). Each speech environment loads its model once and synthesizes up to four phrases concurrently; ordered cache results preserve the step timeline, while HTML frame segments start when their phrase and all preceding phrases are ready. Manim still waits for the complete timing plan before `construct()`. Trigger: cold video builds spent 66–77 s loading Vosk and then synthesized phrases serially before starting any HTML frames.
- **CI and local agent-documentation integrity check** (`scripts/check_instruction_contract.py`, `.github/workflows/ci.yml`; V-826). The instruction contract command reuses `app.kb_index` to check KB topic/index coverage and resolves relative Markdown and backtick file references in `AGENTS.md` and `.orchestra/kb/*.md`; CI runs it once in the test shards. Trigger: KB topics can be invisible to agents when absent from its index, and stale paths misdirect readers.
- **Optional event-synced sound layer for video-artifact** (`scripts/video_artifact/make.py`, `scripts/video_artifact/sound/`; V-824). HTML and Manim steps can declare timed `events`; `make.py` maps them from the voice-derived step plan into a cue sheet, mixes selected CC0 effects, looped music and the existing voice with ducking, then muxes and runs picture/audio QA. The CC0 kit defaults to `~/.local/share/orchestra-sfx/`; scenes without events retain the voice-only path. Trigger: the video builder had no sound beyond speech, and sparse effects alone produced an unusable loudness target and silence failures.

### Fixed
- **Tool-call arguments and assistant text now grow smoothly in the live chat** (`app/backend_claude.py`, `app/static/js/live-activity.js` `LivePacer`, `app/static/js/chat.js`; V-831). Orchestra starts agent CLIs with `DISABLE_TELEMETRY=1` and `DISABLE_NON_ESSENTIAL_MODEL_CALLS=1`, which leaves the CLI's remote flag for fine-grained tool streaming at its default (off). Tool input then arrived one JSON value at a time: a 3.4 KB `content` value came after 12.7 s of silence, measured with CLI 2.1.293 and Opus 5.5. The agent env now sets `CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING=1`, which gives ~14 chars every 50 ms. Opus text itself reaches the CLI in ~190-char bursts every ~600 ms, upstream of Orchestra. The text bubble and the tool-input card now reveal each burst at a rate spread over the observed gap instead of painting it within a few frames. In a browser replay of real captures, the tool card went from 2 paint updates (3 365 chars at once) to 601 (4 chars median), and the gap between text updates went from 386 ms to 76 ms at p90. Trigger: the owner saw tool calls appear in fragments and text "all at once".

### Changed
- **Consolidate visual skills and version the deployment workflow** (`.orchestra/pipelines/default/prompts/skills/`, `pipeline.yaml`, `app/prompting.py`, `app/session.py`, `scripts/video_artifact/`; V-819). Animation/playback guidance is part of the single visual-artifact skill, with its full player scaffold delivered as an on-demand reference so the entrypoint stays within the existing 16 KiB budget. The narrated-video skill and its internal script directory use one name, and the obsolete review skill is removed. The pipeline distributes the deployment skill only to orchestrator roles. On refresh, an untracked stale copy is removed only when its bytes match a historical canonical skill revision; tracked or locally edited copies remain untouched. Trigger: the owner requested one visual skill, removal of the frozen review skill, and an up-to-date owner-authorized deploy workflow.

### Added
- **Protect V-621 catalog migration from worktrees and self-includes** (`app/catalog_migration_v621.py`, `app/project_catalog.py`; V-833). Startup migration now writes only the canonical catalog in the primary checkout and skips when a foreign scope resolves to that same file or Git repository. Catalog loading rejects an `include_scopes` entry that resolves back to its own file with a direct diagnostic. Trigger: a demo server started in a worker worktree rewrote and committed the main catalog into its worker branch, and the resulting self-include duplicated catalog tags after merge.
- **Hidden orchestrator menu shows live status and cache expiry** (`app/static/js/app.js`; V-820). Hidden rows use the same orchestrator status painter and cache pill as pinned tabs, and an open menu refreshes with orchestrator polling and live status updates. Waiting uses 📆 consistently with the Telegram status vocabulary. Trigger: the 👁 menu listed hidden orchestrators by name only, so it hid working/waiting and cache state.
- **Quota-held first tasks follow the worker's current model and can be cancelled by delivery ID** (`app/initial_deliveries.py`, `app/routes/sessions.py`; V-810). A retry rechecks the current model's quota preflight and atomically queues/wakes the existing task when the gate is open; successful model changes run an immediate queue sweep, while the periodic sweep rechecks after a concurrent model switch. `cancel_message_delivery` now also cancels an initial task in `WAITING_QUOTA` or `QUEUED`; it refuses once the runner reaches `PREPARING` and verifies the original sender. Trigger: after an Opus worker changed to Luna, its first task still appeared Claude-blocked and the advertised cancel tool returned 404.
- **Worker spawn validates `delivery_id` before creating or binding a session** (`app/mcp_stdio.py`, `app/routes/sessions.py`; V-808). MCP `spawn_worker` rejects a non-empty malformed ID as `invalid_argument`, and HTTP `/api/sessions` rejects it during request validation; empty IDs keep their existing behavior. Trigger: a non-UUID delivery ID created and task-bound a worker before initial delivery failed with a UUID parsing error.
- **Telegram topics show waiting with a third icon and preserve their titles** (`app/tg_bridge.py`, `app/mailbox.py`, `app/quota_queue.py`, `app/workflow_scheduler.py`; V-804/V-805). A stable wait from a queued owner/dashboard message, an in-memory message queue, a quota-held delivery, a workflow waiting for a shared slot, or a session waiting on background work uses the available calendar icon 📆; active work keeps ⚡ ahead of waiting, and idle without pending work uses ☕. The icon reverts when waiting ends; the topic name never changes. Topic state changes coalesce per topic and share the group rate limiter. Trigger: the dashboard exposed waiting while Telegram topics showed only running/idle; the owner requested the wait state as a topic icon instead of a title prefix.
- **Shared dynamic workflow admission and cgroup isolation** (`app/workflow_scheduler.py`, `app/agent_cgroups.py`, `app/routes/bg.py`, `scripts/wf_run.py`; V-782). Workflow model calls acquire durable SQLite leases through Orchestra; admission is shared and fair across runs, and the limit follows CPU capacity, delegated-slice memory headroom, measured per-call memory samples, and PSI pressure. Queued calls do not consume call budget or dispatch accounting. At startup, leftover processes in the delegated service root move into `orchestra-api` before CPU, IO, and memory controllers are enabled; dynamic workflow runners and provider CLIs then enter `agents`, with weights below the API sibling and memory limits derived from the service limits. The workflow card and manifest expose waiting position, active/queued slots, and the limit reason. Trigger: concurrent workflow fan-outs and test/model processes exhausted the Orchestra service cgroup and stalled the API on 2026-10-08.
- **Claude API-credit usage ledger and dashboard estimate** (`app/claude_api_credits.py`, `app/db.py`, `app/static/js/analytics.js`; V-774, routing replaced by V-800). `turn_usage.billing_mode` identifies recorded credit charges and the owner dashboard shows the remaining estimate and expiry. The estimate starts from the verified Console balance and subtracts recorded API-credit usage; it does not observe usage from other Console clients. The initial session fallback was retired in V-800 after ordinary workers spent $202 from a $200 balance in 21 hours.
- **Readable live cards for dynamic workflows** (`app/routes/bg.py`, `app/static/js/chat.js`, `app/static/js/i18n.js`, `scripts/wf_run.py`, `app/mcp_stdio.py`; V-776). The dashboard shows workflow mode, tasks, stages, models, limits and budget, then polls the read-only run endpoint for progress, cost, elapsed time, per-task answers, preparation errors and result links. Task labels connect journal events to their prompts; repeated prompts collapse to one template with differing values. Trigger: `dynamic_workflow` appeared as raw argument fields and a queued `run_id` line, leaving progress and `prepare_failed` outcomes hidden.
- **Back up Orchestra's canonical task store and live SQLite database** (`scripts/orchestra_backup.py`, V-772/V-793). The task store is pushed hourly to a GitHub repository created private and checked through the API; each push scans unpublished commits with `scripts/secret_scan.py`, so a secret-form match blocks it. The daily database copy uses SQLite's backup API for the live WAL database and stores the two newest verified compressed local copies. The existing hourly task-store job checks laptop reachability, uploads the newest local archive when the reverse tunnel returns, and exits after a matching remote manifest without hashing the 1.3 GB archive; it stays silent while the laptop is offline and reports copies older than three days. Trigger: the live database and canonical task store had no confirmed backup, a sleeping laptop missed the daily upload, and hourly whole-archive verification burdened the laptop.
- **Route bounded, oracle-checked work to Haiku 5.5 at low effort** (`.orchestra/pipelines/default/prompts/modules/model-routing.md`, `.orchestra/pipelines/default/pipeline.yaml`; V-766). The router excludes open-ended or delivery-critical work after 4/40 hard benchmark runs stalled waiting for background checks; every role's effort map selects low for Haiku. Trigger: V-758 measured 10/10 small-task passes at low, without a quality gain from higher effort and at substantially higher cost.
- **Per-model generation speed to usage analytics** (`app/backend_claude.py`, `app/backend_codex.py`, `app/db.py`, `app/usage_analytics.py`, `app/static/js/analytics.js`; V-761). Turns store wall duration and provider API duration when available. Codex estimates model time by subtracting the union of local tool intervals from wall duration, while preserving raw interval sums and the measurement basis. The additive startup migration no-ops if `turn_usage` does not yet exist, so stubbed initialization and pre-schema harnesses cannot abort lifespan. The analytics view shows rolling one-hour and one-day medians plus a time series. Trigger: `turn_usage` stored tokens and timestamps but no duration; full Codex turn time included long command/test waits, while startup tests that stubbed `init_db()` hit a missing table.

### Fixed
- **Claude sessions compact before a send that would overflow the window** (`app/session_turns.py: injection_overflows_context`, `app/session.py: send/_overflow_compact`; V-995). The first message after a session restart carries the whole refreshed system prompt (~95K chars) and the CLI re-attaches its instruction files, which no displayed context figure included. A send now estimates that addition (bytes/2 plus a 4% reserve) and, if it would not fit, queues the message, compacts first and flushes afterwards; a compaction that leaves the context unchanged does not repeat. Separately, for deferred (Claude) context the turn-end compaction decision used the previous turn's percentage, so the refresh now re-runs it on the fresh number. Trigger: katya-work-orchestrator showed 93% (934K of 1M), got a 4-line message plus the refreshed prompt and failed with "Prompt is too long"; the critical 95% threshold never fired.
- **Restore Manim voice-scene setup and compile-check its Python sources** (`scripts/video_artifact/manim_voice.py`, `tests/test_video_artifact.py`; V-829). Indented the `VIDEO_ARTIFACT_VOICE` read inside `VoiceScene.setup()` and added a test compiling every `.py` under `scripts/video_artifact/`, including `sound/`. Trigger: V-819's moved Manim scene had an unindented function body, so every Manim render stopped with `IndentationError` before scene construction.
- **Artifact publication returns snapshot rejection reasons and logs failures** (`app/routes/artifacts.py`; V-828). Expected validation failures such as disabled artifact links, unregistered source roots, and size-limit violations are returned to the publisher; source read failures are categorized, and unexpected exceptions are logged with a 500 response. Trigger: a valid 147 KB University HTML was rejected while public artifact links were disabled, but the route replaced the cause with a generic 400 message.
- **Pool quota charts distinguish actual usage from policy limits** (`app/static/js/quota-lines.js`, `app/static/css/style.css`, `app/static/js/i18n.js`; V-816/V-818). Timeline usage is a solid pool-colored history; Sol and Claude limits use distinct pink/orange dash patterns in those pool colors, and the gray steady-burn diagonal is omitted from this chart (the window-share chart keeps its diagonal). Historical window boundaries come from observed reset events in usage history, so an early Codex reset no longer stretches the previous period to a synthetic seven-day boundary; when sampled history has no reset for a pool, its scheduled boundaries remain the fallback. Future limit projections are dimmed; hard-stop values shared by several pool lanes are drawn once per policy interval. Short labels identify each threshold and hard stop at the right edge. The window-share chart uses short stop/orchestrator/threshold labels with full explanations in SVG titles; actual pool use appears by its marker and pace/limit on the adjacent line. Added the Russian `Claude workers` translation required by the localized panel. Trigger: the owner's live review found unrelated blue/purple limit lines, a misleading straight-looking threshold after Codex reset early at 92%, duplicated unlabeled projections, labels on the X axis, and long chart annotations obscuring facts.
- **Schema-constrained workflow calls carry the schema on their first dispatch, and call-limit exhaustion is no longer reported as budget exhaustion** (`scripts/wf_run.py`; V-814). Each invalid schema response is saved as a per-attempt file capped at 64 KiB. Trigger: three schema tasks spent $0.016 of a $3 budget but were all sent without schema guidance; all retries then appeared as `budget` because the three-call cap was full, and the response text was absent from run artifacts.
- **Structured Orchestra tool results control chat and Telegram status** (`app/static/js/chat.js`, `app/tg_bridge.py`; V-815). The dashboard trusts the stored `tool_is_error` flag and recognizes structured `operation_state` values `FAILED`, `PARTIAL`, and `UNKNOWN`; successful merge results use `git.commits_merged` even when metadata contains `error: None` and `comparison_error: ''`. Telegram already used `tool_is_error` and now also marks partial merge outcomes as failures. Trigger: seedon's successful V-219 merge was shown as failed because its result text contained empty error fields.
- **The known pytest error series is scoped to Orchestra sessions** (`app/error_watch.py`; V-809). Log events retain their session scope; the V-783 baseline, post-fix count and growth alerts include only the repository root resolved from `__file__`. The same signature from other scopes appears as `pytest missing outside Orchestra scope` noise, including single events. Trigger: the `tender-triage` seedon worker ran `python3 -m pytest` in a project that uses unittest and was counted as an Orchestra V-783 recurrence.
- **Claude API credits require an explicit dynamic-workflow task selection** (`scripts/wf_run.py`, `scripts/wf_adapters.py`, `app/claude_api_credits.py`, `app/session.py`, `app/quota_gate.py`, `app/static/js/analytics.js`; V-800). Session workers and orchestrators always use subscription admission and no longer have an API-credit backend path. A workflow task may set `billing: "api_credit"`; it must select a Claude model, defaults to subscription, records charges in `turn_usage`, and refuses before CLI launch when credits are missing, exhausted, untrackable, or expired. The API key is mapped to `ANTHROPIC_API_KEY` only in the selected one-shot Claude CLI environment. Trigger: the V-774 session fallback spent $202 of the $200 credit balance in 21 hours, including $156 on one long-context Opus worker.
- **Dynamic workflow balancing is optional when cgroup delegation is absent** (`app/agent_cgroups.py`, `app/main.py`, `app/bg_jobs.py`, `app/routes/bg.py`; V-798). `ORCHESTRA_WORKFLOW_BALANCER_ENABLED=0` skips cgroup setup and central admission; an explicit `Delegate=no` also skips setup and allows workers to run without isolation. A configured delegate that fails setup still sets `ORCHESTRA_AGENT_CGROUP_REQUIRED`, preserving the VPS fail-closed path. Trigger: the laptop's Orchestra service had no `Delegate=` and could not launch any worker after V-782.
- **Initial spawn reports quota holds and notifies its parent on wait and delivery** (`app/routes/sessions.py`, `app/initial_deliveries.py`, `app/initial_delivery_events.py`, `app/quota_queue.py`, `app/mcp_stdio.py`; V-797). Initial acceptance checks the same worker-admission gate as a new turn, so a closed gate is returned in the spawn receipt with its reason. Later `WAITING_QUOTA` and `SUBMITTED` transitions are recorded transactionally and sent to the parent through a restart-recoverable outbox with log-based duplicate suppression. Trigger: queued initial tasks on the laptop stayed invisible to their orchestrator for 19–68 minutes until a manual quota override.
- **Initial quota-held tasks resume after process restart** (`app/manager.py`; V-788). `send_initial_delivery` now loads a persisted target by immutable session ID when it is absent from the in-memory registry, then keeps the existing identity check under the session lock. Trigger: quota release woke an initial-delivery runner after restart, but the unloaded session raised `KeyError('session not found')` and the accepted task was marked failed.
- **Mutation evidence excludes failures reproduced by the control tree** (`app/merge_test_gate.py`; V-791). The gate runs selected tests against worker sources and again against target sources in otherwise equivalent archived trees; it credits only test nodes green in control and red on target. Trigger: `git archive` mutation trees have no `.git`, so Git-dependent tests failed there and could be mistaken for evidence that source changes were guarded.
- **Telegram topic status ignores brief state flaps and rate-limits retries** (`app/tg_bridge.py`; V-785). Runtime running/idle transitions wait for the same 60-second stable period; topic edit attempts are at least a minute apart, including after an ambiguous timeout. Startup still performs one reconciliation from its current session snapshot. Trigger: under load, topic-status edits timed out while scope activity generated repeated running signals, producing icon-change service notices.
- **Mutation checks distinguish a pytest startup failure from test output** (`app/merge_test_gate.py`; V-784). The gate recognizes pytest as unavailable only when stdout is empty and stderr is the interpreter's exact `No module named pytest` startup error. Trigger: a failing assertion included that text as data, and the mutation gate misclassified the real test failure as `pytest_unavailable`.
- **Test commands use each worker worktree's uv environment; known error series alert only on growth** (`AGENTS.md`, `app/error_watch.py`; V-783). Instructions now use `uv run --frozen python -m pytest`. The recurring pytest-environment and ambiguous-delivery-timeout signatures retain task references, suppress unchanged counts through the ten-event baseline, and alert when the rolling count rises. Trigger: workers used system Python without pytest, and both known error series recurred.
- **Dynamic workflows accept linked worker worktrees as repositories** (`app/workspace.py`, `app/mcp_stdio.py`, `scripts/wf_run.py`; V-780). Repository validation resolves a linked worktree to its primary checkout while rejecting separate gitfile repositories and external Git directories. Workflow tasks are created from the caller checkout's pinned HEAD commit; `create_worktree` callers such as `spawn_worker` also accept linked worktree paths. Trigger: a worker supplied its own workspace, whose `.git` is a gitfile, and all workflow tasks failed preparation.
- **Dashboard bootstrap avoids full-history log scans** (`app/db.py`, `app/routes/system.py`, `app/usage_analytics.py`; V-779). Date-expression indexes cover analytics windows and the per-refresh last-turn lookup; the synchronous analytics snapshot runs on a dedicated worker. `/api/stats` no longer calculates `total_logs`, an unused field not read by project or Orchestra script callers. Trigger: on a 3.2 GiB live-database backup, the analytics retention scan took 55.4 s and the per-refresh `total_logs` count took 3.96 s. Existing database indexes are built once during startup; displayed analytics totals and window definitions are unchanged.
- **Raw file links from removed agent worktrees resolve to the same repository checkout** (`app/routes/system.py`; V-817). For archived sessions whose worktree directory has been removed, `/api/files/raw` serves the same relative file from the session scope only when the recorded worktree belongs to that scope's repository slug and both paths pass the existing allowed-root check. Missing downloads return a readable 404 page. Trigger: after merging and killing `zapros-prolider`, a chat download link still pointed into its deleted worktree while the same DOCX remained in the seedon checkout.
- **CI installs a pinned LGPL ffmpeg/ffprobe build without apt** (`.github/workflows/ci.yml`; V-777). The runner downloads a fixed GitHub release, verifies its SHA-256, and adds the real binaries to `PATH`. Trigger: apt mirror bandwidth prevented `libflite1` from downloading before the ffprobe setup timeout.
- **Managed Claude Bash classification no longer fails open when the thread pool is saturated** (`app/backend_claude.py`; V-773). The bounded classifier now runs synchronously with a 1 MiB command limit; malformed shell input blocks recognizable destructive operations while allowing unrelated commands. Recursive `rm` through `xargs`, `find -delete`, `shred`, and forced `git clean` are denied; `rmdir -p` is denied when its target escapes the session worktree or its path cannot be resolved. Trigger: the 100 ms `asyncio.to_thread` deadline expired under executor contention and allowed 147 calls to pass in seven days.
- **Claude quota thresholds no longer trail the rule already in force during a weekly window** (`app/quota_gate.py`, `app/static/js/quota-lines.js`; V-768). The gate and quota timeline take the maximum of the active rule and prior Claude policy curves recorded in the same weekly window; the envelope clears at the next provider reset. Trigger: after the 2026-10-07 day/night rule change, its later daytime line fell 2.389 p.p. below the preceding shifted rule at 90 hours into the window.
- **Worker Telegram topic toggles take effect immediately** (`app/routes/sessions.py`, `app/tg_bridge.py`; V-765). The bridge stops a worker's live log stream when its `tg_topic` flag is disabled and restarts it on the existing topic when enabled; startup and periodic topic reconciliation also respect the flag. Orchestrator and sub-orchestrator topics remain active by role. Trigger: a worker with `tg_topic=0` kept posting logs to its old Telegram topic after the dashboard toggle.
- **Ambiguous delivery transport errors expose the original idempotency key** (`app/mcp_stdio.py`; V-778). Message, single/batch file, worker spawn, and initial-delivery retry errors now include their generated or supplied `delivery_id`/`event_id` in both the human-readable message and structured error data when reconciliation cannot resolve a transport timeout. Trigger: a `send_message` POST timed out after the server accepted it, but the caller received only `ReadTimeout` and could not safely repeat the idempotent call.
- **Claude API-equivalent cached costs use model-specific prompt-cache rates and Haiku 5.5's per-request long-prompt tier** (`app/models.py`, `app/backend_claude.py`, `app/routes/system.py`, `app/session_turns.py`; V-760). The registry carries model cache-read, 5-minute and 1-hour write multipliers, and prompt tiers. Turn pricing deduplicates streamed `AssistantMessage` usage by `message_id`; if request prompt usage is missing/incomplete it uses base rates and sets `[price_may_be_understated]` in the durable turn-end status. When per-request output totals disagree with Result usage, output remains at base rates and the flag is set if any request crosses the tier. The agent-cost dashboard uses the backend's stored session total for Haiku because `turn_usage` rows combine multiple API requests. Trigger: aggregate turn usage applied Haiku's 5× tier to multiple sub-100k API prompts, while the shared formula also charged every cache read at 10% and every write at 125%.
- **Replace Haiku 4.5 with Haiku 5.5 in the selectable model registry** (`app/models.py`, `app/tg_bridge.py`; V-757). The `haiku` alias now resolves to `claude-haiku-5-5`, with a 1M context window and Anthropic's base API-equivalent rates of $0.10/$0.50 per million input/output tokens. Anthropic applies higher rates above 100k prompt tokens; Orchestra's flat-rate model metadata cannot represent that tier. Trigger: Haiku 5.5 became available, superseding the temporarily retained Haiku 4.5. The Claude Agent SDK is updated to 0.2.164, bundling CLI 2.1.292, so SDK calls accept the new model.
- **Identical `wf_run` tasks no longer collide, and every terminal run outcome is reported** (`scripts/wf_run.py`, `app/bg_jobs.py`, V-756). Writable calls now include the occurrence suffix in their worktree names, so equal prompts keep separate workspaces. Workspace preparation exceptions retain their cause in the journal/manifest, leave the call retryable, and return a partial result instead of aborting sibling tasks; the incomplete-manifest check wakes the caller immediately. Failed, timed-out, restarted, and manually cancelled run jobs use one terminal notification path with a parent-orchestrator fallback when the target cannot be reached. Trigger: repeated prompts collided on worktree names built from only the shared digest prefix; the resulting gather failure stalled until the 60-minute job timeout, while manual cancellation silently discarded the caller's wake.
- **Taskless worker assignments start from current main without discarding branch work** (`app/routes/sessions.py`; V-781). Parent `send_message` now recognizes current `adhoc-*` branches, checks dirty files and commits against `main`, and creates the task branch from current `main` only when the worktree is clean. Trigger: after merge and idle, a new task could stay on an old adhoc HEAD; the previous `force=True` switch could also discard unmerged work.
- **Merge mutation checks use the worker's changed test snapshots and fixtures** (`app/merge_test_gate.py`; V-755). The rollback checkout now overlays every changed file under `tests/` while keeping application source at the target revision. Trigger: a route snapshot changed with a removed route, so the old route and old snapshot passed together and the gate incorrectly reported `tests_not_guarding_source`.
- **Persist the dashboard TG topic toggle through the session manager** (`app/static/js/app.js`, `app/routes/sessions.py`; V-753). The context-menu action now uses the manager-backed `POST /api/sessions/{name}/tg_topic` route, which persists updates for loaded and detached sessions; the duplicate `PATCH /tg-topic` route is removed. Trigger: the dashboard called the duplicate route, which attempted `save_session()` without the required `session_id` binding and returned HTTP 500.
- **Remove four receipt-only MCP status tools and direct ambiguous calls to same-key retries** (`app/mcp_stdio.py`, delivery modules, default prompt modules; V-750). Agents no longer receive `message_delivery_status`, `file_delivery_status`, `delivery_status`, or `task_create_status`; internal HTTP reconciliation stays available. Message, file, initial-task, and task-create errors now carry the stable key needed to repeat the same call idempotently. Trigger: comfy-image-orchestrator-vps polled message status 32 times in one day after accepted sends.
- **File delivery failures wake agent senders and receipts no longer invite polling** (`app/tg_file_deliveries.py`, `app/mcp_stdio.py`; V-748). Terminal failures of the primary Telegram delivery create a durable, event-keyed sender notice; startup recovery retries a notice until logged, and its stable event ID prevents duplicate wakeups. Send/status tool descriptions and ordinary receipts reserve status lookups for ambiguous tool-call outcomes. Trigger: an agent was polling file status after every accepted send, while later terminal failures had no automatic wake path.
- **Format percentages from usage and quota payloads consistently** (`app/static/js/utils.js`, `usage.js`, `analytics.js`, `quota-lines.js`; V-747). A shared formatter rounds displayed utilization to whole percentages while retaining explicit precision for reset progress and cost share. Trigger: a Claude utilization of `0.29` was multiplied by 100 in the API and reached the browser as `28.999999999999996`, which the compact strip displayed verbatim.
- **Quota policy history writes only from the socket-activated service** (`app/quota_gate.py`, `app/routes/system.py`; V-745). `quota_policy()` is read-only; startup and live quota-map observations persist changes only when `LISTEN_PID` names the current process. A targeted, logged migration corrects the known V-744 probe row to the owner-reported restart timestamp. Trigger: a standalone line-value probe inherited the service's database path and recorded the V-744 rule before the service restart.
- **Quota timeline renders the line that was active at each past point** (`app/db.py`, `app/quota_gate.py`, `app/routes/system.py`, `app/static/js/quota-lines.js`; V-743). Complete `QuotaPolicy` snapshots are appended with effective-from times; the quota-map payload includes the snapshot before the chart window and every change within it, and the timeline splits each weekly segment at policy changes. The initial reconstruction uses the known 2026-09-29 baseline and V-732 restart; restart seeding is idempotent, and earlier Sol curve/cap activation times are bounded by commit and restart evidence in the task report. Trigger: the chart applied V-732's shifted Claude line to the preceding week and showed Sol's old straight line with its current curve/cap; a missing source prefix initially made each service restart duplicate the reconstructed epochs.
- **Wake an agent when an accepted direct message fails before submission, and let message delivery proceed without optional worker memory layout** (`app/message_deliveries.py`, `app/prompting.py`; V-741). Terminal failures now create a durable, delivery-keyed notice for the sending agent; startup retries pending notices and a stable event ID prevents replay after the message was logged. Missing `.orchestra/layout.json` now skips only worker-memory injection with a visible log instead of blocking the turn. Trigger: an MCP sender received `QUEUED`, but `ORCHESTRA_LAYOUT_MISSING` stopped the target worktree and no sender was woken.
- **Retire models without losing stored-session recovery or price history** (`app/models.py`, `app/manager.py`, `app/backend_codex.py`, default pipeline; V-739). The picker and alias targets now use the curated catalog, provider refresh cannot re-register the retired IDs, GPT-6.1 Sol is the `sol` target, and Astra/Sol are manual-only. Exact retired model IDs remain readable for persisted sessions and historical cost accounting; the reducer now uses GPT-6 Luna. Trigger: removing old selectable models would otherwise strand active sessions and turn analytics.
- **Owner-initiated worker turns no longer auto-report to their parent** (`app/session.py`, `app/session_turns.py`; V-740). A parented worker was still reporting after the owner sent it a direct dashboard/TG message because `parent_name` survives beyond the task sender that started an earlier turn. The active-turn marker now follows user/dashboard provenance through direct and queued sends; normal parent-task reports, restored background-job reports, restart recovery, and abnormal-end reports keep their parent path.
- **Force task switching discards only unlanded commits by explicit request** (`app/routes/sessions.py::switch_branch`, `release_previous`; V-737). A force switch of a worker holding committed work now assigns the new task while superseding/requeueing the old task run in the same task-store transaction. Dirty worktrees remain blocked before task state changes. Trigger: merged CI rejected the newly added V-736 guard even though `switch_worker_branch(force=True)` explicitly authorizes abandoning commits not verified in base; returning early also bypassed rollback tests and left an unhandled asyncio subprocess transport warning.
- **Restore CI coverage for current file, quota and task-switch behavior** (`app/db.py`, `app/routes/sessions.py`, frontend and worker tests; V-736). Resetless non-null usage windows remain in history, and tests model TTS tools and provider metadata at their boundaries. Browser checks exercise the protected preview and current file actions; the readiness check includes Claude's configured eight-hour line shift. V-737 corrects the initial force-switch guard to honor the force contract for committed work while keeping dirty worktrees blocked. Trigger: main's CI stopped passing after changes to PDF actions, quota formatting and worker task-run semantics.
- **Layout migration failures restore stashed project work** (`app/orchestra_layout.py`, V-704). If a startup migration errors after preserving dirty files, it runs journal recovery before returning the error; the trigger was user files left hidden in `stash@{0}` after migration failure.
- **Local background runs use the caller's project directory** (`app/routes/bg.py`, `app/bg_jobs.py`, V-704). A run job uses the first existing caller path in worktree, cwd, scope order and refuses if none exists; relative paths previously resolved under the Orchestra service directory, and removed worktrees could make jobs fail.
- **Mixed layout repair reports a manual resolution path** (`app/orchestra_layout.py`, V-704). When old and new project directories coexist, `--repair` explains that merging is unsafe and gives manual reconciliation steps instead of returning itself as the repair command.
- **Ignore Python caches inside Orchestra state** (`.gitignore`, V-704). Added a deeper `__pycache__` exclusion after reopening `.orchestra/**`; imported scripts under `.orchestra/` previously left untracked bytecode.
- **Keep worker work out of the shared Git stash stack** (`.orchestra/pipelines/default/prompts/modules/git-workflow.md`, V-704). The worker rules now direct unfinished work to its task branch or a task-local patch; stash entries are shared across linked worktrees.
- **Офлайн-установка RUAccent на ноутбуке и строгий запуск русской сборки** (`.orchestra/tasks/V-691/setup-laptop.sh`, `prompts/skills/explainer-video.md`; V-719). Установщик восстанавливает модель и данные `koziev` из локальных архивов; при ошибке RUAccent инструкция требует остановиться и сообщить о среде вместо незаметного обхода через `--no-stress`. Триггер: блокировка Hugging Face и отсутствующие веса/данные RUAccent на ноутбуке.

### Removed
- **Project-memory MCP search and API** (`app/mcp_stdio.py`, `app/routes/memory.py`, `app/memory_search.py`; V-718). Removed the tool, its API route and search implementation after the owner chose to remove the feature; agents now search `.orchestra/kb/` and `.orchestra/tasks/` with `rg`.

### Added
- **Claude's weekly quota line follows local day/night usage and retains eight hours of headroom** (`app/quota_gate.py`, `app/static/js/quota-lines.js`; V-744). The base line distributes its 89-point rise across actual daytime/nighttime hours in the Anthropic weekly window using V-721's 94.3%/5.7% usage split; the previous `+91×8/168` headroom is added without shifting clock phases, and the line remains capped at 99%. The effective-from policy history from V-743 keeps earlier cycles on their saved rule. Trigger: the owner clarified that “smooth” meant faster daytime growth and slower overnight growth, rather than shifting the same straight line.
- **Dynamic workflows support staged simulations and list templates** (`app/mcp_stdio.py`, `scripts/wf_run.py`, V-738). `dynamic_workflow(mode="stages")` expands a stage prompt across `items`; every task in a later stage receives every completed value from the prior stage as structured input. The spec lives at `data/workflow-runs/<run-id>/request.json` and the background command carries only its path. One engine instance shares budget, call count and concurrency across all stages; journal replay and file-backed resume keep completed earlier work. Limits: 20 stages, 1,000 expanded tasks, 1 MiB spec. Trigger: multi-round persona simulations and final analysis previously needed a custom workflow script and argv was limited to 64 KiB.
- **One-call dynamic workflow launches** (`app/mcp_stdio.py`, `scripts/wf_run.py`, V-720). The `dynamic_workflow` MCP tool accepts task prompts, optional schemas/models, mode and limits, task ID, and repository; it passes those parameters directly to the durable `wf_run` runner, which supports parallel tasks or a result-fed chain without a user-authored workflow file. `bg_jobs` checks the manifest and wakes the caller with short answers and result paths. A plain-text answer is also accepted as a string when the task declares `{"type":"string"}`, preventing a JSON-only retry for ordinary text. Astra and Sol are rejected, Luna is the default. Trigger: six scripted workflow runs required manually writing a script, constructing a background command, and reading its manifest.
- **Dynamic workflows support parallel stages and prompt templates** (`app/mcp_stdio.py`, `scripts/wf_run.py`, V-738). A stage can expand one prompt over a list of items, then each task in the next stage receives every prior-stage result as a structured input. Specifications are saved as run files and passed to `wf_run` by path instead of command-line payloads; the shared call and cost limits apply across all stages, while journal replay preserves completed earlier stages on resume. Trigger: running multi-round persona simulations and final analysis previously required custom workflow code and prompt payloads were capped by argv size.
- **Точные лимиты Claude и Codex сохраняются вместе с исходным ответом** (`app/backend_claude.py`, `app/routes/system.py`, `app/session.py`; V-707). Claude `rate_limit_event` раньше только логировался: его дробные `unifiedWindows` не доходили до кеша, квотного гейта и снимков. Теперь событие обновляет окна без округления; лог сохраняет полный сырой payload, `usage_snapshots.provider_usage` хранит сырой ответ API и события с окнами, длительностью и временем снимка. Нормализатор Codex сохраняет исходный `account/rateLimits/read` вместе с 5-часовым и недельным окном, отдельными лимитами по `rateLimitsByLimitId` и кредитами; `turn_usage` получает точные числа в существующих `REAL`-полях. Схема БД не менялась: используются существующие `provider_usage` и журнал событий. Образцы текущих payload — `.orchestra/tasks/V-707/`. Живые ответы: Claude CLI 2.1.284 передал `0.11`/`0.83` в долях; Codex CLI 0.156.1 передал `usedPercent` 25/14 и баланс кредитов `"0"`. Тесты проверяют дробные окна и сохранение полного ответа.
- **Кнопка «Открыть в новой вкладке» для PDF и других файлов, а не только для HTML** (`app/static/js/app.js`, `app/static/js/chat.js`). Владелец 05.10 попросил открывать PDF и прочее в нативном браузере, как HTML. В карточке `send_file` вместо HTML-only «👁 Preview» теперь «🔗 Open» по тому же списку `_SEND_FILE_OPENABLE`, что и в `send_files` (html, pdf, txt, md, json, csv, log, xml, yaml). В просмотрщике файлов кнопка 🌐 Open появляется для всего, что браузер показывает сам (плюс картинки, видео и аудио через `_FILE_MEDIA_OPENABLE`), а PDF вместо «⚠ binary file» встраивается во фрейм встроенным просмотрщиком браузера (без `sandbox`: Chromium не запускает PDF-просмотрщик в песочнице). `/api/files/raw` уже отдавал PDF inline как `application/pdf`.
- **Автоматическая разметка русских ударений в `explainer-video`** (`make.py`, V-696). Отдельный TTS-процесс с RUAccent размечает русские `say` до Vosk; ручной `+` остаётся приоритетным и скрывается в подписи, `--no-stress` явно отключает обработчик, английский Kokoro его не запускает. Ключ TTS-кэша включает размеченный текст, поэтому прежние WAV не переиспользуются при новом произношении. RUAccent и совместимые зависимости закреплены в установщике ноутбука и TTS-окружении VPS после неверного ударения `лимита` и немаркированного OOV `оркестратору` в ролике V-690.
- **Живое сообщение `/limits` в личке владельца** (`app/tg_bridge.py`; V-692). Команда создаёт фото с текущими лимитами и подписью с временем обновления и следующего обновления по Красноярску; `chat_id`, `message_id` и расписание лежат в `kv` платформенной БД. Мост обновляет его каждые 30 минут, возобновляет прежнее сообщение после перезапуска и заменяет его одним новым, если Telegram сообщил, что старое нельзя редактировать. Повторный `/limits` назначает новым текущим сообщением ответ команды. Ошибки данных, рендера и сети не запускают повторную отправку.
- **Английская озвучка в `explainer-video`** (`make.py --lang en --voice <голос>`, `scripts/explainer_video/tts_worker_en.py`; V-686). Владелец 03.10 попросил ролик для README GitHub «с анимациями на английском». Vosk-модель только русская, а Silero и Piper ранее отвергнуты по лицензиям, поэтому английский голос — Kokoro-82M (веса Apache 2.0) через `kokoro-onnx` (MIT) в своём окружении `~/.local/share/orchestra-tts/en/` (`ORCHESTRA_TTS_EN_HOME`), без облака и платных API. `check_steps` для `en` отказывает только на кириллицу (цифры и названия Kokoro читает сам), кэш фраз различает движок и голос, Deepgram проверяет с `language=en`. Замер: пять голосов на одной фразе — дословное распознавание у всех; синтез 14 фраз ролика ~1 мин против ~2 мин одной загрузки Vosk. Пример: `.orchestra/tasks/V-686/media/orchestra-tour.mp4` — тур по настоящему дашборду на демо-стенде.
- **Видео-превью и проигрыватель дашборда** (`app/static/js/app.js`, `app/static/js/chat.js`, `app/routes/system.py`; V-688). Видео MP4/WebM/MOV получают неподвижный muted-превью-кадр и открываются в общем lightbox с управлением; `/api/files/raw` отдаёт byte ranges и валидирует медиа по ETag/Last-Modified с `Cache-Control: no-cache` (неизменённый файл отвечает 304 без тела). Карточки GIF используют существующий WebP-preview без cache-buster: GIF V-686 размером 4,544,124 байта и 329 кадров уменьшается до 12,974 байт (640 px, первый кадр) вместо полного декодирования в списке.
- **Формулы LaTeX в Manim-роликах** (`scripts/explainer_video/manim_voice.py`, скилл `explainer-video`; V-685). Владелец 03.10: «давай латекс тоже ставь, чтобы формулы тоже было всё чётко». TinyTeX (TeX Live 2026, 220 МБ) поставлен без apt и root в `~/.local/share/orchestra-manim/tex/` с пакетами, которые нужны шаблонам Manim, плюс `babel-russian`/`cyrillic`/`lh`. `manim_voice` при импорте добавляет его `bin` в PATH (папки нет → системный `latex`) и ставит `config.tex_template` с T2A и `babel[english,russian]`: шаблон Manim по умолчанию грузит только `babel[english]`, и `\text{кеш}` в `MathTex` падал с `Unicode character ц not set up`. Поправка к V-684: системный TeX Live 2023 на VPS стоял с 07.08 (apt), просто шаблон не умел кириллицу. В скилле — пример с подстановкой чисел (`TransformMatchingTex`), разбор ошибки `latex error converting to dvi` и команды установки. Ролик-пример: `.orchestra/tasks/V-685/video/compact55.mp4` — почему компакт по простою ждёт 55 минут, по формуле подписки V-660 и 70 компактам из `logs`.
- **Manim — второй движок сцен в `explainer-video`** (`scripts/explainer_video/manim_voice.py`, ветка `.py` в `make.py`: `manim_steps`, `render_manim`; V-684). Владелец 03.10 попросил графики «как у 3Blue1Brown». ManimCE 0.20.1 (MIT) стоит вне репозитория в `~/.local/share/orchestra-manim/` через micromamba и conda-forge — Cairo, Pango и ffmpeg приходят пакетами, apt и root не нужны (`ORCHESTRA_MANIM_HOME` меняет путь). Сцена — класс-наследник `VoiceScene` с тем же `STEPS`, что у html-motion; блок `with self.step(i)` растягивает шаг до длины фразы, а `self.left()` даёт анимациям долю оставшегося времени, перебор шага останавливает сборку. Длительности приходят от `make.py` через `EXPLAINER_VOICE`, Manim сам пишет 1920×1080, контакт-лист снимается из готового MP4. LaTeX не ставили, поэтому `MathTex` недоступен — формулы пишутся Unicode-текстом. Пример: `.orchestra/tasks/V-684/video/night-shift.mp4` — сутки Оркестры циферблатом по `logs` за месяц.

### Changed
- **Ролики по умолчанию в 1.5 раза быстрее** (`--rate 1.5` в `make.py`, паузы `LEAD`/`GAP` делятся на темп в `plan`; V-684). Владелец: «в полтора раза быстрее». Замер на фразах cache-ttl: Vosk `speech_rate` 1.5 сокращает речь в 1.48 раза при той же распознаваемости Deepgram (минимум по фразам 0.87 против 0.86 у 1.0), а `atempo=1.5` поверх обычной речи хуже (0.83). Без ускорения пауз ролик сократился бы только в 1.4 раза; `hold` последнего шага не трогается — это время досмотреть итог. cache-ttl: 68.8 → 47.4 с. Поправка: владелец, послушав, решил «полтора слишком много, давай 1.25» — умолчание `--rate` стало 1.25 (тот же день).

### Fixed
- **`spawn_worker` no longer times out while Git creates a large worktree** (`app/mcp_stdio.py`, `app/backend_codex.py`; V-699). The session-creation POST now gets 300 s; Codex's generated `orchestra` MCP server gets 360 s so the host can receive the result and initial-delivery receipt. Claude's documented unset MCP tool deadline is about 28 hours. Trigger: `git worktree add --detach` measured 147.702 s for seedon under concurrent checkout I/O, beyond the former 30 s HTTP timeout.
- **`spawn_worker` после таймаута больше не теряет начальную задачу** (`app/mcp_stdio.py::_resume_cut_off_spawn`, `app/initial_deliveries.py::record_spawn_intent/spawn_resume_verdict`, `POST /api/sessions/{name}/spawn-resume`; V-695). Клиент делал `POST /api/sessions` (30 с), потом доставку; при `ReadTimeout` на создании сервер воркера всё равно создавал, строки в `initial_deliveries` не было, а повтор получал 409 «already exists» — 04.10 так остались без задачи `design-elements` и `zad9-urok-0510`. Теперь `delivery_id` выбирается до создания и уходит в `/api/sessions`; сервер запоминает «имя + delivery_id + sha задания» (`kv spawn_intent:<id>`). После таймаута или 409 клиент спрашивает `spawn-resume`: тот же delivery_id и тот же текст, плюс нет доставки и ходов у воркера → идёт обычная идемпотентная доставка; другой delivery id даёт `SPAWN_DELIVERY_ID_MISMATCH`, тот же id с изменённым текстом — `SPAWN_TASK_MISMATCH`, а работавший воркер — `SPAWN_SESSION_NOT_FRESH`. Если создание до сервера не дошло, ошибка несёт `next_action` с delivery_id для повтора. Known tradeoff: воркеры, потерявшие доставку ДО этого фикса, интента не имеют — их повтор откажет; задачу им шлёт `send_message`.
- **CI actions and dashboard localization/history** (`.github/workflows/ci.yml`, `app/quota_gate.py`, `app/static/js/{i18n,analytics,usage,quota-lines}.js`, `app/db.py`; V-700). GitHub Actions no longer pins actions on Node 20; quota lane labels translate in the browser, analytics and usage dates/numbers follow the selected language, and real zero utilization without reset metadata remains in the usage history graph. Trigger: Node 20 runner deprecation, English dashboard showing Russian formatting, and legal `utilization: 0` samples disappearing.
- **Явно назначенная задача закрепляется при создании любой роли, а смена задачи закрывает устаревшие прогоны** (`app/manager.py`, `app/tm.py`; V-705). Менеджер пропускал `task_id` для `is_orchestrator`, поэтому `sub-orchestrator` создавался с незакреплённой задачей и позже получал отказ мержа; теперь явная привязка передаётся в атомарную публикацию независимо от роли. При переключении открытый прогон предыдущей задачи закрывается как `task_superseded`, включая устаревшую legacy-квитанцию, не совпадающую с текущей привязкой сессии. Триггеры: T069 и T080/T154.
- **Stop waits for the turn's terminal event, and failed `send_message` calls no longer suppress worker auto-reports** (`app/session.py`; V-706 T097/T176). A successful interrupt acknowledgement is only a request acknowledgement: the session stays `RUNNING` until the listener records the actual turn end, preventing Stop from reporting idle while the backend keeps working. Auto-report suppression now follows a successful `send_message` tool result; a failed result leaves the silent-turn report path active.
- **MCP sender identity comes from the proof header, and chat snapshots support conditional 304 responses** (`app/routes/sessions.py`, `app/static/js/app.js`; V-706 T179/T184). A body `sender` claim without a matching session proof is rejected; a valid proof supplies the sender even when the body omits it. `/api/sessions/{name}/logs` remains `no-store` but returns an ETag and 304 on a matching `If-None-Match`; the chat keeps its fetched page in memory and reuses it only after that network validation.
- **Quota thresholds and model buckets have one owner; queue diagnostics reuse the active SQLite transaction** (`app/routes/system.py`, `app/limit_wake.py`, `app/message_deliveries.py`; V-706 T104). Removed the duplicate bucket-level `limit_pct`, routed wake classification through `quota_bucket_for_model`, deleted the unused restart-grace constant while preserving the zero-valued result field, and queried the queue head on the transaction connection when a receipt is built inside a transaction. `_blocking_runtimes()` was already absent.
- **Фото с недопустимой геометрией отправляется документом, неизвестные темы только логируются** (`app/upload_limits.py`, `app/tg_bridge.py`; V-701). Раньше PNG/JPEG проходил в Bot API только по расширению и размеру, поэтому файл 3.2 МБ с `PHOTO_INVALID_DIMENSIONS` не доходил; теперь проверяются сумма сторон и соотношение, включая одиночные durable-файлы, альбомы и прямые фото-превью. Старые принятые альбомы с уже записанным видом `photo` при неверной геометрии уходят документами всей группой. Неизвестная теме VPS-бота привязка не доказывает, что тема ничья в других инстансах, поэтому сообщение в такой теме не отправляется и событие остаётся в WARNING-логе.
- **Merge gate and worker merge replies preserve actionable, machine-readable outcomes** (`app/merge_test_gate.py`, `app/merge_operations.py`, `app/mcp_stdio.py`, `app/routes/sessions.py`, `app/routes/merge_operations.py`; V-702). Mutation checks ignore deleted test files, preserve dot-prefixed repository paths, and treat every pytest usage exit as inconclusive; pending merges expose nonterminal/nonfailure flags in structured results. A taskless merge refusal distinguishes a completed task run from missing completion history; when `merge_worker` receives an explicit task ID for committed adhoc work, the operation route uses the existing `promote_current` flow before admitting the merge. Ordinary post-completion message delivery still auto-switches to adhoc. A diff over the review ceiling tells the worker to wake its parent orchestrator, the only role that can authorize a waiver. Trigger: deleted test modules produced pytest collection errors that were mistaken for successful mutation evidence, while structured pending results and taskless post-completion flows hid their recovery paths.
- **Codex history imports remain version-pinned to verified formats** (`app/runtime_history.py`; V-703/V-726). Synthetic rendered history was accepted by CLI 0.156.1, then again by 0.160.0 through `thread/resume` in separate temporary `CODEX_HOME` directories; live threads were not used. The version pin follows the latest verified CLI. Codex usage failures include exception repr (so empty `TimeoutError` is visible), and cleanup tolerates `ProcessLookupError` if the app-server exits during kill. Active Codex messages keep their live steer and a durable mailbox backup: successful turns clear it, failed turns replay it once. Terminal usage-limit errors report the reset for the exhausted window, or both labeled windows if exhaustion is not identified. Triggers: import-version mismatch, 15 empty usage-fetch errors in V-647, a steered message lost after an interrupted Codex turn, and `(no output)` after quota exhaustion.
- **`spawn_worker` после таймаута больше не теряет начальную задачу** (`app/mcp_stdio.py::_resume_cut_off_spawn`, `app/initial_deliveries.py::record_spawn_intent/spawn_resume_verdict`, `POST /api/sessions/{name}/spawn-resume`; V-695). Клиент делал `POST /api/sessions` (30 с), потом доставку; при `ReadTimeout` на создании сервер воркера всё равно создавал, строки в `initial_deliveries` не было, а повтор получал 409 «already exists» — 04.10 так остались без задачи `design-elements` и `zad9-urok-0510`. Теперь `delivery_id` выбирается до создания и уходит в `/api/sessions`; сервер запоминает «имя + delivery_id + sha задания» (`kv spawn_intent:<id>`). После таймаута или 409 клиент спрашивает `spawn-resume`: тот же delivery_id и то же задание, плюс нет доставки и нет ходов у воркера → идёт обычная идемпотентная доставка; иначе `SPAWN_NAME_TAKEN` (другое задание/delivery_id) или `SPAWN_SESSION_NOT_FRESH` (воркер уже работал). Если создание до сервера не дошло, ошибка несёт `next_action` с delivery_id для повтора. Known tradeoff: воркеры, потерявшие доставку ДО этого фикса, интента не имеют — их повтор откажет; задачу им шлёт `send_message`. Сам медленный `create_session` не лечился.
- **CI fixtures no longer fail on runner setup or stale browser-copy expectations** (`.github/workflows/ci.yml`, `tests/conftest.py`, browser tests; V-693). Git identity is explicit for fixture repositories, and tests set a non-production `INTERNAL_TOKEN` before importing the app. Browser doubles provide `T()` and other required interfaces; heartbeat tests no longer monkeypatch the shared `asyncio.sleep`. UI checks assert lifecycle/data state instead of translated captions. Trigger: 0 green Actions runs in 100 after task-store commits lacked Git identity, proof setup lacked a token, and English-locale pages disagreed with Russian text assertions.
- **Committed Tailwind output matches its pinned source build** (`app/static/css/vendor/tailwind.css`; V-693). Rebuilt with the existing `tailwindcss@3.4.17` script after the served asset omitted 19 classes used by current HTML/JS; the byte-for-byte source/build test remains the guard.

- Кадры контакт-листа пишутся в `frames/<имя>/`: две сцены, собранные в одну папку, раньше перезаписывали `frames/stepNN.png` друг друга, и контакт-лист второй мог захватить лишний кадр первой.
- **Скилл `explainer-video`: объясняющий ролик с русской озвучкой** (`prompts/skills/explainer-video.md`, `scripts/explainer_video/make.py`, `tts_worker.py`, `video.css`, шрифты Manrope и JetBrains Mono (OFL) в `fonts/`; V-681). Запрос владельца 02.10: видео-объяснения «как 3Blue1Brown». Сцена — тот же каркас `html-motion`, у шага добавлена фраза `say`. Время задаёт озвучка: инструмент сначала синтезирует фразы локальным Vosk TTS (`vosk-model-tts-ru-0.9-multi`, Apache 2.0), потом ставит длительность шага = 0.35 с + фраза + 0.55 с и передаёт её сцене через `window.voice?.(STEPS)`. Поэтому начало фразы совпадает со сменой кадра по построению, а не подгонкой. Дальше покадровая запись `P.seek(k/30)` в 1920×1080 на тёмной теме кусками в параллельных Chromium (69 с ролика: 25 мин в один поток → 9.5 мин сборки целиком), дорожка голоса раскладывается по началам фраз, `loudnorm` −16 LUFS. Проверка: контакт-лист кадров конца шагов и распознавание итогового MP4 Deepgram nova-2 с дословностью каждой фразы плюс фактическое начало её звука по `silencedetect` (`*.check.json`; в примере сдвиг ≤ 0.03 с). Vosk падает с `KeyError` на латинице и цифрах, поэтому инструмент отказывает заранее и требует писать их словами; экранные субтитры берутся из `sub`. Пример — `.orchestra/tasks/V-681/video/cache-ttl.mp4` по замеру V-676. Окружение TTS (`~/.local/share/orchestra-tts/`) вне репозитория: прежняя копия в `~/.cache/v75-tts` оказалась пустой — каталоги без файлов.

### Changed
- **MP4 в Telegram приходит видео, а не документом** (`app/tg_video.py`; `send_as_video` в `app/upload_limits.py`; `_tg_send_file_safe`, `_submit_file_snapshot_once`, `_submit_file_group_once`, `_MirrorItem` в `app/tg_bridge.py`; вид `video` в `_batch_kind` у `app/tg_file_deliveries.py`; V-681). Владелец хотел, чтобы ролики играли в ленте, как фото. `.mp4/.m4v` (только MPEG4 Telegram проигрывает в клиентах) уходят `sendVideo` с `supports_streaming`, длительностью, размерами и JPEG-превью 320 px из середины ролика (`ffprobe`/`ffmpeg`; без них — видео без метаданных). Отказ Telegram (400/403: сообщения нет, исход известен) откатывается в `sendDocument`, альбом — в альбом документов. Таймаут и сетевая ошибка не откатываются: исход неизвестен, повтор задвоил бы файл. Зеркала идут тем же путём, `as_document` по-прежнему форсирует документ. Нужен рестарт Python.
- Known tradeoff: отпечаток идемпотентности альбома включает вид файла, поэтому повтор `send_files` с тем же `event_id`, начатый до рестарта и повторённый после, для пакета с MP4 получит конфликт отпечатка (`document` → `video`).
- **Доставка, отбитая гейтом квот, ждёт его снятия внутри платформы — таймер «повтори через N часов» больше не нужен** (`app/quota_queue.py`, состояние `WAITING_QUOTA` в `message_deliveries`/`initial_deliveries`). Раньше `send_message` и `spawn_worker` получали 429 `weekly_quota_blocked`, и оркестратор ставил себе bg-таймер: ~4 таких таймера в сутки с 23.09, каждое пробуждение — платный ход, часто впустую. Теперь отбитое сообщение принимается durable-доставкой (приёмка в `routes/sessions.py: _preflight_or_quota_wait`, отказ runner'а в `run_message_delivery` переводит в ожидание вместо `FAILED_BEFORE_SUBMIT`), отправитель сразу получает «принято в очередь» с оценкой времени (`next_action.eta_at`), а `quota_queue.release_waiting` возвращает строки в обычную очередь, когда гейт пропускает: циклом раз в минуту (`quota_release_loop`, стартует в lifespan) и немедленно при `POST /api/usage/quota-override` (в ответе `released_deliveries`). Порядок к одному адресату сохраняется (`accept_seq`, ждущая голова держит очередь), повтор с тем же `delivery_id` дубля не даёт, рестарт ничего не теряет (строки в SQLite, `recover_*` их не трогают). Первое задание нового воркера не обгоняется прямыми сообщениями ему. Сменил задачу/убит адресат к моменту выпуска — доставка падает громко (`TARGET_TASK_CHANGED`/`FAILED_BEFORE_SUBMIT`), отправителю уходит платформенное сообщение. Отмена: тул `cancel_message_delivery` и `POST /api/message-deliveries/{id}/cancel` (только ещё не ушедшее: `WAITING_QUOTA`/`QUEUED`), список ждущих: `GET /api/message-deliveries`. Промпт `modules/background-jobs.md` запрещает ставить таймеры повтора доставки. Тесты `tests/test_quota_wait_queue.py`.

### Changed
- **`spawn_worker` при закрытом гейте квот больше не отказывает** (`SessionManager.create_session`): воркер создаётся, а его первое задание ждёт в `WAITING_QUOTA` и уходит само. Прежний отказ до создания (#227) нужен был, чтобы не плодить «мёртвые» сессии, но теперь первый `/send` не отбивается, и мёртвой сессия не бывает. Известный компромисс: пока гейт закрыт, простаивающий воркер с привязанной задачей и worktree существует; неотправленное задание видно в `delivery_status`.
- Не затронут путь без `delivery_id` (HTTP `/send` от UI/TG): там по-прежнему работают сообщения в памяти сессии и уведомление `quota_blocked`; перенос их в durable-очередь — отдельная работа.
- **Конец хода воркера без отчёта родителю теперь durable-сигнал платформы вместо idle-сторожа** (`app/turn_signals.py`, `_make_idle_callback` и `auto_resume_all` в `app/manager.py`, `TurnManager.report_abnormal_end` в `app/session_turns.py`). Раньше авто-отчёт жил в `asyncio`-задаче: отказ доставки (`DrainingRefused` при рестарте, `QuotaGateError`, `CLIConnectionError`) оставлял запись в журнале «автоматического повтора нет», смерть слушателя / обрыв потока / сбой автопродолжения вообще не вызывали отчёта, а ход, убитый рестартом, не сообщал родителю ничего. Оркестраторы страховались `bg_create(type="idle")`. Теперь факт пишется в таблицу `turn_signals` (UNIQUE по сессии+процессу+номеру хода → одно пробуждение на ход, сколько бы путей его ни заметило), доставляется сразу и повторяется sweeper'ом с backoff до принятия родителем; после рестарта pending-строки доезжают, а для ходов, оборванных рестартом, сигнал создаётся при старте (если воркер не успел написать родителю). Сигналы одного родителя, созревшие вместе (типично — после рестарта), уходят одним сообщением; перед повтором лог родителя проверяется на ссылку `turn_signal[id]`, чтобы падение между «принято» и «помечено» не дублировало. Явный DONE дубля не даёт (прежний гейт `_did_report`). Триггер: 8 недоставленных авто-отчётов с 13.08 (6 — дренаж рестарта) и 154 постановки idle-сторожа, 150 из них в сентябре. Тесты `tests/test_turn_signals.py`.
- В промпте оркестратора (`background-jobs.md`) вместо рекомендации ставить idle-сторожа — описание этого сигнала.

### Changed
- `bump_turn_gen` больше не отменяет отложенный авто-отчёт прошлого хода: теперь это записанный факт, и начало следующего хода (до того, как задача успела записать строку) не должно его стирать.

### Removed
- **Тип bg-задания `idle` удалён целиком** (`app/idle_watch.py`, `_run_idle` и ветки `idle` в `app/bg_jobs.py`, описание и проверка роли в `bg_create` в `app/mcp_stdio.py`, «Сторож простоя» в `jobs-timeline.js`, тесты). Его единственный сценарий — не потерять конец хода воркера — закрыт платформенным сигналом `turn_signals` (V-680); 154 постановки, по умолчанию бессрочные. `bg_create(type="idle")` теперь отвечает ошибкой «тип удалён, конец хода воркера родителю сообщает платформа». Старые строки `bg_jobs` с `type='idle'` при старте (`restore_from_db` → `bg_cancel_removed_idle`) переводятся в `cancelled` с причиной, историю не трогаем. `has_active_jobs` больше не исключает idle, потому что idle не существует. Тесты в `tests/test_bg_jobs.py`.

- `_record_undelivered_auto_report` и `_auto_report_key` (политика «ретраев нет», #30/#47/#50) вместе с тестами `test_auto_report_undelivered.py`: заменены повтором из `turn_signals`.

### Known tradeoff
- Для хода, оборванного рестартом, «воркер уже писал родителю» определяется по журналу родителя с момента последнего входящего воркера; сообщение, пришедшее воркеру посреди хода после его DONE, даст лишнее пробуждение, а не потерю.

### Fixed
- **Иконка простоя TG-топика появлялась через 5 минут после конца хода** (`_TOPIC_STATUS_IDLE_FADE_DELAY_SECONDS` в `app/tg_bridge.py`: 300 → 60 с). Пауза из #99 защищает от мигания иконки между частыми ходами, но 5 минут владелец воспринимал как «иконки запаздывают». Успешная смена иконки теперь пишется в журнал (`TG topic_status <orch> -> running|idle (edit Ns)`); раньше логировались только отказы, и реальную задержку нельзя было измерить.
- **Сжатие контекста (компакт) срывалось у агентов OpenRouter: ack-ход не укладывался в 60 с** (`_compact_ack_timeout`, `COMPACT_ACK_TIMEOUT_SECONDS`/`_HARNESS` в `app/session.py`). После сжатия платформа поднимает свежую сессию без префикс-кеша и шлёт «Acknowledge briefly», ожидая завершения хода `asyncio.wait_for(..., timeout=60)`. DeepSeek V4.1 Flash на OpenRouter (7–83 tps у разных провайдеров) не отвечал за минуту на полном перечитывании системного промпта → таймаут → откат к несжатой сессии, агент залипал у потолка контекста. Триггер: `openrouter-lab-orchestrator`, компакт с 59% контекста — «compact ack turn did not complete (60s)». Лимит для Claude/Codex оставлен 60 с, для Harness поднят до 240 с; переопределяется `COMPACT_ACK_TIMEOUT_SECONDS`. Тест `test_compact_ack_timeout_is_longer_for_harness`.

### Added
- **Панель JOBS (фоновые задания агентов) стала читаемой и попала на временную ленту** (`app/static/js/jobs-timeline.js`, `renderJobsPanel`; стили `.job-*` в `style.css`; `switchLeftTab` расширяет панель до 380 px на вкладке). Раньше строка показывала `timer/cron/idle`, обрезанный на 50 символов текст и «ACTIVE». Теперь карточка: человеческий тип («Напоминание», «По расписанию», «Сторож простоя», «Команда в фоне»…), полный текст «зачем» (3 строки, раскрывается кликом), «поставил X → разбудит Y», когда сработает — «через 3 ч» и абсолютно в Красноярске, у cron следующий запуск считается по `cron_expr` (UTC, как в `bg_jobs`) плюс последний запуск и число срабатываний, статус и ошибка. Переключатель «По агентам / Лента»: лента — прошедшие и будущие события по времени с границей «СЕЙЧАС». Забытое бросается в глаза: активное не-таймерное задание старше 2 дней помечено «⚠ висит N дн» (красным с 7 дней), таймер с вышедшим сроком — «застряло»; в шапке счётчик забытых. Отмена — кнопка ✕ (с подтверждением) через существующий `DELETE /api/bg/jobs/{id}`. Тест `tests/test_jobs_view.py` (разбор cron, правило «забытого»).
### Changed
- `bg_get_jobs`: лимит 50 → 200 и активные впереди завершённых, иначе самые старые (то есть забытые) активные задания выпадали из списка за новыми завершёнными. Требует рестарта Python. История завершённых по-прежнему стирается через сутки (`bg_cleanup_old`), поэтому прошлое на ленте — это последние 24 часа.
- Из `app.js` удалены старые `renderJobsPanel`/`_createJobItem`/`cancelJob`/`_timeLeft`/`_elapsed` (заменены в `jobs-timeline.js`); `_JOB_ICONS` дополнен новыми типами.

### Added
- **Закрепление провайдера OpenRouter по цене кеша** (`_provider_order` в `app/harness/llm.py`, поле `provider` в `_build_body`). Без пина OpenRouter сам маршрутизировал на дорогого Together ($0.006/1М чтения кеша, $1.20/1М выход). Теперь запрос несёт `provider.order = [DeepInfra, StreamLake, GMICloud]` с `allow_fallbacks: true`: порядок по стоимости чтения кеша (главная статья расхода при перечитывании контекста), откат не даёт агенту зависнуть, если провайдер не обслуживает модель (GLM у этих нет — уходит к дефолтным). Переопределяется `HARNESS_PROVIDER_ORDER` без правки кода; пустая строка возвращает авторутинг. На нашем профиле (99% кеша, ~1.7 млрд читаемых токенов/день) это ~$11/день против ~$19 на Together. Тест `test_provider_order_pins_cheap_providers_with_fallback`.

### Fixed
- **Дашборд показывал «кеш 0.00%» у агентов OpenRouter, хотя провайдер кешировал до 99%** (`_cached_prompt_tokens`, `_cache_hit_pct` в `app/backend_harness.py`; `_accumulate`, `_turn_end`, `_error_turn_end`). OpenRouter возвращает `usage.prompt_tokens_details.cached_tokens`, но backend выбрасывал это число и жёстко писал `cache_hit: 0`, а весь `prompt_tokens` (включая кеш) шёл в `input_tokens`. Теперь кешированная часть вычитается из входа в `cache_read`, а `cache_hit` считается как её доля от промпта. Деньги не пересчитываются — стоимость берётся из ответа провайдера, где скидка за кеш уже применена. Триггер: `openrouter-lab-orchestrator` на DeepSeek V4.1 Flash, ход с 55 652 токенами промпта, 55 168 из них кеш (99.1%), в дашборде «кеш 0.00%». Тесты: `test_openrouter_cached_prompt_tokens_split_into_cache_read_and_hit_pct`, `test_turn_end_reports_cache_read_tokens_not_zero`.

### Added
- **Агенты Harness (OpenRouter, GigaChat) видят правила проекта** (`project_instructions` в `app/harness/prompts.py`, `HarnessBackend._refresh_system_prompt`). Claude и Codex читают CLAUDE.md/AGENTS.md сами, а Harness до сих пор собирал системное сообщение только из промпта роли. Правила проекта до его агентов не доходили: в первом ходе `openrouter-lab-orchestrator` их не было. Теперь правила читаются так же, как в управляемом Codex: от корня git до cwd, по одному файлу на каталог (AGENTS.md, иначе CLAUDE.md), симлинк на тот же файл не дублируется, потолок 32 KiB как у Codex. Личные глобальные файлы не читаются, по решению V-570. Перечитываются на каждом ходу: правка доходит со следующего хода. Пока файл не меняется, системное сообщение остаётся тем же, и кеш провайдера не сбивается. Тесты: `test_project_rules_reach_the_harness_like_managed_codex`, `test_edited_project_rules_apply_on_the_next_turn`.
- **Платные маршруты OpenRouter по белому списку владельца** (`PAID_HARNESS_ROUTES` и `harness_route_allowed` в `app/models.py`; допуск в `validate_harness_model_spec`, `normalize_catalog_model`, `OpenRouterClient._validate_route`). Раньше Harness пускал только точные `:free` маршруты, и оркестратор на DeepSeek V4.1 Flash (бесплатного варианта нет) создать было нельзя. В списке три маршрута: `deepseek/deepseek-v4.1-flash`, `z-ai/glm-5.3`, `z-ai/glm-5.3-flash` — владелец открыл их 01.10 для экспериментов с оркестраторами на OpenRouter (GLM-5.4 в каталоге нет, последняя GLM-5.3). Остальные платные маршруты по-прежнему отклоняются. Требование нулевой стоимости `usage.cost` сохранено для `:free`; у платного маршрута стоимость идёт в учёт сессии. Тесты: `test_owner_listed_paid_route_is_billed_and_others_stay_blocked`, `test_catalog_admits_only_free_or_owner_listed_paid_routes`.

### Fixed
- **GIF-превью README начинается с задачи и рассказывает весь цикл** (`docs/dashboard-live.gif`; V-689). После замечания владельца 04.10, что старый GIF начинался с середины ролика, превью пересобрано от пользовательской задачи через разбор, запуск и работу воркеров, DONE, ревью/тесты, мерж, доску и квоты. У GIF собственные английские подписи без номеров: 1100×618, 10 fps, 6.54 MB, с возвратом к первому кадру на стыке цикла.
- **Долгие таймеры `bg_create(type="timer")` больше не умирают молча** (`app/bg_jobs.py`). Срок жизни таймера (`delay + 1 ч`) обрезался потолком 8 суток, поэтому таймер дольше ~8 суток принимался с «OK», но истекал раньше своего срабатывания (баг-репорт seedon 29.09: bg-a0c0992639, срабатывание 27.10, истечение 07.10). Потолок для таймеров снят по решению владельца («без ограничений»): срок всегда позже `trigger_at`. Тест `test_long_timer_expires_after_it_fires`.

### Removed
- **Тень-гейт «DONE без проверки после последней правки» (V-614) удалён** (`app/done_gate.py`, вызов в `app/message_deliveries.py`, `scripts/done_gate_weekly_report.py`). Неделя в тени (23–30.09): отмечено 73 из 217 докладов DONE, ни один из отмеченных не упал на тест-гейте мержа, а 4 из 5 реальных провалов гейт не отметил; основная масса отметок — проекты без кода (презентации, тексты). Решение владельца 30.09 «убираем». Старые строки `done_gate_verdict` остаются в журнале; чат по-прежнему их не рисует.
- **Скилл `vps-deploy` убран из продукта** (`prompts/skills/vps-deploy.md`, `pipeline.yaml` у оркестратора). Решение владельца 29.09: это было единственное место поставки с упоминанием хостинга, а перезапуск Orchestra и так инициирует только владелец.

### Fixed
- **Инструменты AUDIT/FINAL больше не попадают в обычную ленту как сиротские результаты** (`AgentSession.compact`, `_agentic_audit_summary`, V-672). Черновик, AUDIT и FINAL записывают отдельные `compact_event` с общей принадлежностью и ID вызовов; дашборд собирает их в свёрнутый блок с результатами, итоговой сводкой и доступной статистикой. Telegram-мост пропускает эти служебные события. Ограничение объёма истории оставляет событие валидным JSON, показывает отметку и даёт загрузить полный текст, не меняя запись в БД. Триггер: после запуска компакта seedon-orchestrator записал 34 `tool_result` без ID и ни одного парного `tool`.

### Changed
- **Плавное движение в каркасе `html-motion`** (`prompts/skills/html-motion.md`, V-668). Владелец посмотрел примеры V-665: «не плавно нихуя, надо плавнее, как Apple». Каркас переписан так, что плавность обеспечивает он сам, а формат `STEPS` не изменился. У каждого атрибута теперь свой список отрезков. Движение по умолчанию идёт по пружине с критическим затуханием, а не по квадратичному in-out. Если атрибут меняется в соседних шагах в одну сторону, стык склеивается монотонным кубическим сплайном (Фрич–Батленд), и объект проходит границу шага без остановки: курсор графика раньше вставал на 4 границах из 6, теперь ни на одной. Цвет, `opacity` и `text` меняются за 0.5 с. Текст сменяется наплывом через клон-призрак: старый уходит раньше, чем проявляется новый. Появление идёт с лёгким сдвигом и масштабом. Подпись шага и подсветка главы тоже меняются наплывом и вычисляются из `t`, поэтому пауза и перемотка по-прежнему дают тот же кадр до пикселя (добавлена проверка середины наплыва: 0 px). ⏮ ⏭ и ←/→ доезжают до цели за 0.4 с. Панель получила круглые кнопки с SVG-иконками, анимацию нажатия, превращение пуска в паузу и ползунок с заливкой. Примеры перерисованы: токен идёт невидимыми путями через центры узлов, за узлами, поэтому исчезли 2 видимых телепорта. Точка графика едет по линии, а не ступеньками по целым процентам. Видео пишется покадрово через `P.seek(k/60)` при 60 к/с. Экранная запись Playwright давала 25 к/с с повторёнными кадрами, отсюда большая часть рывков в роликах V-665. Все числа — в `.orchestra/tasks/V-668/report.md`.
- **Known tradeoff:** каркас вырос с ~2.3 до ~4.3 тыс. токенов (o200k). Его копируют командой `awk`, а не пишут, при этом скрипт сцены в примерах изменился на −3% и +8%. Элементу с анимируемым `text`/`opacity` больше нельзя давать собственный `transform`: каркас двигает его через CSS `transform`.

### Added
- **Скилл `html-motion`: анимированные объяснения по шагам с плеером** (`prompts/skills/html-motion.md`, `defaults.skills`, V-665). Скилл содержит готовый каркас одного HTML-файла: кадр — чистая функция времени, сцена задаётся декларативным массивом `STEPS` (`set`/`w`/`along`) с пояснением к каждому шагу. Плеер умеет пуск/паузу, шаги, ползунок, скорость, клавиши, главы, reduced motion и ссылку `#t=`, а для проверки открыт `window.P`. На одной и той же сцене четыре техники сравнивались по токенам, офлайну и совпадению кадров: у выбранной сцена стоит 668 токенов против 741–893 у остальных, а кадр на паузе совпадает с кадром при перемотке до пикселя. В Web Animations API найдены две ловушки: асинхронный `pause()` и `play()`, который перематывает завершённую анимацию в 0 (1684 px расхождения в конце). GSAP с CDN не работает офлайн. Каркас вынесен в отдельный скилл, потому что тело `html-artifacts` упирается в потолок 16000 байт, а в воркеры копируется только `SKILL.md`. `base.md` называет `html-motion` спутником `html-artifacts`. Примеры, кадры и MP4 — в `.orchestra/tasks/V-665/`.
- **Sonnet 5.5 (1M) становится единственным Sonnet в выборе** (`app/models.py`, V-658). `sonnet`, `sonnet5.5` и прежние Sonnet 5/4.x id направляются в `claude-sonnet-5-5[1m]`; при восстановлении сессии `Manager` канонизирует сохранённый id до создания backend. Старый Sonnet 5 пропадает из списка, а окно 1M и цены $2/$10 за миллион соответствуют новой модели. Запуск со старым `claude-sonnet-5[1m]` теперь возобновляется на 5.5.
- **Временная шкала квот пула** (`QuotaPanel`, `build_quota_map`, V-652). Над прежним графиком добавлена 168-часовая шкала ±84 ч с центром в моменте снимка, часовыми/дневными метками Красноярска и ночной подсветкой 00:00–08:00. Пороги и равномерный расход повторяются от границ циклов квоты; исторические точки из `usage_snapshots` включают сбросы и не продолжаются в будущее. Старый график сохранён ниже без изменения SVG.
- **Read-only детектор повторяющихся ошибок** (`app.error_watch`, V-647). Команда для расписания читает ошибки unit-журнала и строки `logs` через SQLite `mode=ro`, обезличивает динамические значения, отсеивает квотные/лимитные отказы, штатный listener `IDLE`/`WAITING` и парные записи двух logger handlers, затем дедуплицирует новые превышения порога. Подтверждённый listener exit во время `RUNNING` сигналится с порогом 1. Реестр рядом с БД связывает сигнатуру с задачей, коммитом и временем запуска для post-fix наблюдения; включение `cron_command` описано в отчёте V-647. Детектор не меняет код и не создаёт задач.

### Fixed
- **Проверка сводки сжатия (V-650) откатывалась на черновик при любом предупреждении о лимите** (`AgentSession._agentic_audit_summary`). Claude присылает `provider_limit` со статусом `allowed_warning` на каждом ходу, если недельный лимит выше 75%, а проход AUDIT считал его отказом. Первое боевое сжатие (cog-second-brain, 28.09 11:12 UTC) ушло на черновик за 22 с. Теперь проходы прерывает только `rejected`, как и ход черновика.
- **Временная шкала квот показывает фактическую историю** (`QuotaPanel._qlTimelineSvg`, V-654). `timeline.points[].resets_at` менялся между снимками, но график принимал каждый вариант за отдельный сброс и перекрывал линии расхода пороговыми зигзагами. Циклы порогов теперь строятся по текущему `window.resets_at` и длительности окна, а история отдельно соединяет реальные снимки и текущую точку. На шкале есть двухчасовые засечки; подписи времени идут через 4 часа, а границы ночи 00:00 и 08:00 всегда подписаны днём недели.
- **Ожидающий таймер предкомпакта отменяется при удалении воркера** (`Manager.remove`, `AgentSession._cancel_precompact_timer`, V-653). Раньше убитый Codex-воркер оставлял таймер на 25 минут; он запускал нативное сжатие уже после архивации и удаления worktree, затем завершался `FileNotFoundError`. Удаление отменяет таймер до срабатывания.
- **`cron_command` сообщает о таймауте цели задания** (`BgJobManager._fire_cron_command`, V-653). Таймаут 600 секунд сохраняется в `last_output` и доставляет цели job id, команду, лимит и подсказку проверить запуск; повторные таймауты не дублируют сообщение до успешного запуска. Это исправляет молчаливый простой cron-сборщика seedon. Заменяет прежнее ограничение из V-647: таймаут теперь будит цель.
- **Миграция V-576 восстанавливает отсутствующую `attention_events`** (`_migrate_database`, V-653). Существующие базы v2→v3 создают таблицу с `IF NOT EXISTS`; старт v3 также чинит базу, где таблицу удалили или она отсутствовала, включая ручное создание без дубликатов. Триггер: `notify_user` падал с `no such table: attention_events` на VPS и ноутбуке.
- **`cron_command` убивал команду через 30 с молча** (`_CRON_COMMAND_TIMEOUT_SECONDS` в `app/bg_jobs.py` 30 → 600, лимит назван в описании `bg_create`). Сборщик закупок seedon 4 дня не собирал ничего, error watch Orchestra (`app.error_watch scan`, ~59 с на базе 2.2 ГБ) не отрабатывал ни разу за последние 12 ч: в `last_output` только `[command timed out after 30 seconds]`, цель не будилась. Запуски идут последовательно, поэтому длинный лимит не создаёт наложений. Таймаутное уведомление добавлено в V-653.
- **Ложная тревога «silent death» больше не пишется на штатный конец хода** (`AgentSession._on_task_done`, V-648).
  Предупреждение `listen task exited without exception (silent death)` печаталось при любом нормальном выходе
  слушателя: конец потока после `turn_end` и подавленная отмена перед сжатием. За 20–27.09 — 475 событий, из них
  474 со статусом IDLE/WAITING и один настоящий обрыв хода (seo-cro, 24.09). Теперь штатный выход — debug,
  warning и `_finish_failed_running_turn` остаются только для выхода во время RUNNING.
- **Агентное сжатие сохраняет в журнал заменённую сводку из контекста** (`AgentSession._agentic_audit_summary`).
  Первое боевое сжатие 26.09 (seedon-orchestrator: 9152 → 15698 знаков, $2.18) нельзя было сравнить с исходной
  сводкой — она нигде не оставалась. Теперь перед строкой `agentic compact audit:` пишется status
  `agentic compact context summary (replaced):` с её полным текстом.
- **Telegram-лента оркестратора: каждый `send_message` агента — отдельное раскрываемое сообщение, счётчик ⚙️ больше не врёт** (`stream_logs`, `_send_message_parts`, `_update_progress`, V-644).
  Владелец, 25.09: «почему написано что 2 действия если было одно, и не раскрыть че ты там ему написал».
  Заголовок ⚙️ считал `len(state.actions)` — все действия хода, а список показывал только пачку `state.block`
  (текст юзеру начинает новую пачку), поэтому «2 действия» стояло над одной строкой; теперь счёт — `len(state.block)`.
  Вызов send_message уходит сообщением `✉️ → адресат` с полным текстом в expandable blockquote (лимиты UTF-16 — общим
  `_expandable_message`), в строке ⚙️ остаётся только `→ адресат`. Повтор строки журнала (откат курсора) второго
  сообщения не даёт: id хранится вне `_TurnState`, который якорь обнуляет. Known tradeoff: итог (`✓`) вызова после
  закрытия пачки в ленте не отображается.
- **История чата снова дозагружается страницами до самого начала** (`loadMoreLogs`, `app/static/js/app.js`).
  С 28.08 кнопка «▲ предыдущие 100» срабатывала один раз и исчезала, старшая история была недоступна
  (владелец, 25.09: «не могу бесконечно по 100 загружать сообщения выше»). Теперь полная страница из 100
  строк возвращает кнопку для следующей; кнопка пропадает, только когда страница пришла неполной.
- **Квотный гейт Claude больше не блокирует сжатие и платформенные ходы** (`AgentSession._compaction_permit`,
  `AgentSession.send`, `QUOTA_GATE_EXEMPT_ORIGINS`, V-640; решение владельца: «никаких лимитов на сжатие и
  систем запросы»). Сжатие воркера (авто по таймеру, ручное, любое) не обращается к гейту; ходы с origin
  `background_task`/`platform`/`system` проходят закрытый гейт. Ходы по сообщениям пользователя и агентов
  гейт блокирует как раньше; реальный лимит провайдера не менялся. Триггер: `precompact timer fired` в
  08:35 UTC без `compact started` до ручного снятия гейта (`QuotaGateError` из таймера уходил молча) и
  `НЕДОСТАВКА` результата bg-задания воркеру. Known tradeoff: очередь `_flush_pending` не хранит происхождение
  сообщений и по-прежнему проходит гейт.

### Changed
- **AUDIT и FINAL Claude-компакта продолжаются в сессии, написавшей черновик** (`AgentSession._agentic_audit_summary`,
  `app/agentic_compact.py`, V-650). После штатного compact-хода сессия получает файлы журнала от последней
  преамбулы (`journal`-чанки и `journal.jsonl`) в `data/compact-sandbox/` рядом с БД (под `.gitignore`), а AUDIT и FINAL из V-649
  отправляются как следующие ходы того же backend-сеанса. FINAL заменяет черновик в ack-преамбуле; текст этих
  проходов не публикуется как обычный ответ. Инкрементальная стоимость каждого хода учитывается `CostTracker`,
  без отдельного CLI и холодной записи полного prefix. Ошибка, таймаут (`AGENTIC_COMPACT_TIMEOUT`, 900 с), стоп,
  включая stop во время чернового хода, пустой или слишком длинный итог (`AGENTIC_COMPACT_MAX_CHARS`, 25 000)
  оставляют черновик и записывают причину;
  временный каталог удаляется. Выключатель: `AGENTIC_COMPACT_ENABLED=0`. Codex остаётся на нативном компакте.
  Триггер: замер V-649 показал холодную премию форка около 0.497 п.п. недельного пула, тогда как оценка тех же
  двух проходов на прогретом prefix составляла около 0.096 п.п. за компакт.
- **Сигналы «воркер молчит» и «доставлено, но ход не начался»** (`app/stall_signals.py`, V-642).
  Сессия RUNNING с живым backend без единого события провайдера 20 минут → родителю уходит одно
  сообщение (имя, задача, минуты тишины, последнее событие с именем инструмента, время); новое
  событие или новый ход заново взводят сигнал, `HibernateManager._signal_silence_once`.
  Сообщение, доставленное простаивавшему воркеру, без события провайдера за 60 с помечается в
  `message_delivery_status` (`stalled: true`, `error.code=TURN_NOT_STARTED`, причина — статус агента),
  отправитель получает сообщение. Состояние доставки остаётся `SUBMITTED`: отдельное состояние
  стало бы головой очереди цели и заблокировало её. Сообщения в pending за идущим ходом или
  сжатием под наблюдение не попадают. Ничего не прерывается автоматически.
  Триггер: «воркер просто стоит» — heartbeat писал лишь «possible long thinking» в лог.
  Known tradeoff: долгий инструмент (bash) — тоже тишина провайдера, сигнал приходит и по нему;
  медленный первый токен дольше 60 с даёт ложный stalled (метка остаётся, состояние не меняется).
- **Офлайн-установка из комплекта поставки** (`scripts/build_offline_bundle.sh`, `deploy/install-offline.sh`, V-638).
  Сборка вытягивает 60 wheels (linux x86_64, CPython 3.12, версии и sha256 из `uv.lock` через
  `uv export --no-dev`) и пакует код, `wheels/`, README и LICENSE в архив (~150 МБ); установка ставит
  из него через `python3 -m venv` и `pip install --no-index --require-hashes`, без uv и сети.
  Комплект не несёт наш `.orchestra/projects*.yaml`: установщик создаёт пустой каталог проектов
  (приложение без него не стартует) и git-идентичность пользователя сервиса (хранилище задач — git-репозиторий).
  Проверено в пустом network namespace: установка доходит до сервиса, отвечающего HTTP 302.
  Триггер: подача в реестр российского ПО, установка не должна тянуть uv и пакеты из-за рубежа.
  Онлайн-путь `deploy/install.sh` не менялся. Known tradeoff: Chromium для `/limits` в комплект не входит.

### Fixed (V-637, harness на GigaChat)
- **Цикл одного результата при меняющихся аргументах** (`app/harness/loop.py`, `SAME_RESULT_HINT`/`SAME_RESULT_OFF`).
  GigaChat-3-Ultra 16 раз слал сломанный `bash -lc 'python3 - << "PY" …'`, каждый раз меняя символ.
  Дословного повтора не было, прежняя защита не срабатывала, ход стоил 500 тыс. токенов. Теперь тот же
  непустой результат одного инструмента в третий раз даёт подсказку «запиши скрипт через write и
  запусти», в шестой отключает инструменты до конца хода.
- **Шаблон `$(...)` в отчёте помечается** (`_has_shell_template`): воркер «сделал аудит», записав
  `$(uname -r)` в .md, и отчитался об успехе. После такой записи модель получает пометку, что
  подстановки не выполнены.
- **Напоминание запустить написанный код** (`_unrun_code`). Воркер написал тесты к несуществующим
  функциям, не запустил их и доложил «все тесты прошли». Если за ход записан .py/.sh и после записи
  не было ни одного bash, перед концом хода модель один раз получает требование запустить.
- **Перечитывание одного файла** (`REREAD_HINT`/`REREAD_OFF`, `_inspected_path`). Воркер аудита
  25 раз перебирал `sed -n 'A,Bp'` по своему отчёту в 178 строк, большей частью за концом файла,
  и потратил 430 тыс. токенов. Теперь на 4-м чтении даётся подсказка, на 8-м инструменты
  отключаются.
- **edit в Python-файле с переводом строки внутри строкового литерала** (`app/harness/tools.py` `edit`).
  GigaChat присылал `new` с настоящими переводами строк там, где в `old` было `\n`; проверка
  синтаксиса трижды отклоняла одну и ту же правку. Теперь, если так файл не компилируется, а с
  экранированными `\n` компилируется, берётся второй вариант.
- **Пустой блок вывода под молчаливой командой в чате** (`app/static/js/chat.js`): у `cp` и
  `mkdir` без вывода оставался пустой чёрный прямоугольник.

### Added
- `HARNESS_BASH_DENY`: регулярное выражение установки для команд bash, которые меняют систему.
  На стенде оркестратор по «рекомендации» своего аудита пытался выполнить `sudo fallocate`/`swapon`/fstab.
- `HARNESS_OUTPUT_CAP`: потолок одного результата инструмента в символах (по умолчанию 30 000).
  На бесплатной квоте один результат в 69 КБ оседал в истории и отправлялся заново в каждом
  следующем раунде хода.

### Known tradeoff
- Harness заново отправляет всю историю в каждом раунде и сжимает её только обрезкой при 85% окна.
  У оркестратора стенда с историей 229 КБ один простой запрос стоил 190 тыс. токенов вместо 1.8 тыс.
  Сжатия сводкой для harness нет, решение за владельцем.

### Changed
- **Автокомпакт Claude по простою взводится только от 30% контекста, а не от 5%** (`app/session.py`
  `PRECOMPACT_MIN_CONTEXT_PCT`, общий для Claude и Codex).
  Порог 5% считали под окно 200k, а сессии Claude теперь идут с окном 1M и после компакта
  остаются на 7-12% (промпт плюс handoff). За неделю до 25.09 из 67 компактов 34 начинались
  ниже 30% и срезали только 35-38% контекста, заново записывая в кеш 90-150k токенов и теряя
  детали; компакты от 30% срезали 78-86%. Порог аварийного компакта (95%) не менялся.

### Fixed
- **Worktree воркера в старой раскладке мигрирует сам при подъёме воркера** (`app/orchestra_layout.py`
  `migrate_worker_worktree`, вызов из `app/prompting.py` `load_worker_memory`, V-635).
  Ветка, созданная до миграции своего базового чекаута, оставалась с `docs/*`, и воркер
  падал с `ORCHESTRA_LAYOUT_MISSING`, а подсказка `repair` указывала на уже current базу.
  Теперь при resume, auto-switch и первом сообщении (все они собирают промпт через
  `load_worker_memory`) чистый linked worktree над current-базой переводится каноническим
  `migrate_project_layout`: `git mv` и коммит миграции в ветке воркера. Грязное дерево не
  трогается и не стэшится: `ORCHESTRA_LAYOUT_DIRTY` называет сам worktree и даёт команду
  «закоммитить и мигрировать». Если старая и база, остаётся прежняя ошибка V-611 на базу.
  Триггер: 22 таких worktree на ноутбуке после синка (V-634), переведены вручную.
  Known tradeoff: миграция идёт синхронно под `repo_mutation_lock` репозитория; если этот
  лок в тот момент держит мерж, сборка промпта ждёт его окончания.
- **Сквош-мерж больше не падает на выводе git, который не декодируется как UTF-8** (`app/workspace.py` `_git_cmd`).
  Git в diffstat `git merge --squash` обрезает длинные пути по байтам. В seedon (ветка
  bizdev, 130 переименований с кириллицей) обрезка пришлась на середину символа (`...\x80`),
  и строгое декодирование бросило `UnicodeDecodeError` уже после того, как squash был застейджен.
  Операция осталась UNKNOWN, коммит и автозакрытие задачи не выполнились. Теперь вызовы
  git с `text=True` декодируются с `errors="replace"`. Воспроизведено на настоящих
  коммитах seedon: до фикса ошибка в позиции 12433, после — rc 0.
- 🧹 **Рестарт без продвижения каталога больше не коммитит, а чужой scope не считается
  ошибкой раскладки** (`app/catalog_migration_v621.py`, `app/orchestra_layout.py`
  `migrate_registered_projects`, V-634). `migrate_v621` раньше писал бэкап, переписывал
  домашний файл тем же содержимым и коммитил его на каждом старте, пока в каталоге
  оставался хоть один пропущенный scope. Теперь при `include_scopes` без единого сдвинутого
  scope он возвращает `state=pending` без записей. Scope, которого нет на диске этой
  машины, в миграции раскладки получает `status=absent` вместо `ORCHESTRA_LAYOUT_GIT_ERROR`.
  Триггер: ноутбук держит в общем каталоге девять путей VPS (`/home/kesha/...`, `/opt/...`).
  Из-за них в main ноутбука набралось пять одинаковых коммитов «V-621: разбить общий
  каталог», а журнал на каждом старте получал девять ложных «not a Git checkout».
- **`change_worker_model` now follows the dashboard history path** (`app/mcp_stdio.py`,
  `app/session.py`, `app/routes/sessions.py`, V-633): MCP sends `model` and `scope` with its
  existing `via: mcp` authorization metadata, so
  same-runtime changes retain their native session and Claude↔Codex changes use
  `chat_history_v1`. The tool reports the transfer mode and character count, and displays
  API refusal errors. Removed the unused fresh-switch branch and updated the KB.
  Trigger: MCP model changes always sent `fresh: true`, discarding dialogs while the same
  dashboard switches preserved or transferred history.
- 🔗 **Taskless adhoc work can finish through `merge_worker(task_id=..., task_outcome="complete")`** (`app/routes/sessions.py`, `app/tm.py`, `app/mcp_stdio.py`, V-631): the explicitly named in-progress task receives commit links and closes in merge finalization. A live owner blocks transfer while running or waiting, and an idle owner blocks it when its task branch has unmerged commits or dirty files. Trigger: seedon’s `accountant` had completed V-44 on a taskless adhoc branch, while the task still belonged to another session.
- 🛡 **Восстановление раскладки сверяет содержимое и пишет атомарно** (`app/orchestra_layout.py`,
  V-629): перед `stash drop` восстановленные staged, unstaged и untracked файлы побайтно
  сравниваются со снимком; несовпадение оставляет stash и recovery-журнал. Запись идёт во
  временный файл с атомарной подменой, поэтому сбой не оставляет целевой файл пустым. Чистая
  смешанная раскладка ремонтируется при старте, а актуальная больше не создаёт stash без
  необходимости. Триггер — цикл сохранения состояния раз в событие мог принять нулевой файл
  за восстановленный по одному лишь Git status и удалить stash с целым содержимым.
- 🧪 **Полный `pytest tests/` снова доходит до сводки (V-624).** Две независимые причины:
  1. **rc=137 на ~35–38 %.** Тесты пути рестарта (`test_hot_apply`, `test_seamless_restart`,
     `test_system_restart`) глушили `os.kill`, но не `_arm_supervisor_exit_guard`, и тот
     поднимал настоящего помощника `app.restart_guard` с целью `os.getpid()` — то есть сам
     pytest. Первый же позднейший `TestClient` в teardown писал ему `application_teardown_complete`,
     и через 5 с помощник слал SIGKILL по pidfd. bpftrace поймал отправителя дословно:
     `python3 -m app.restart_guard --pid <pytest> … --post-cleanup-budget 5.0`. Теперь
     `tests/conftest.py` отказывает взводу стража на pid pytest (`AssertionError`), а файлы
     пути рестарта берут фикстуру `no_real_exit_guard`.
  2. **Вечное ожидание на ~85–88 % (набор V-610).** `app.limits_card.shutdown_renderer()`
     ждал `browser.close()` у Chromium, поднятого на цикле событий ДРУГОГО теста
     (`test_tg_bridge::TestLimitsCommand` рендерит настоящую карточку); ответ Playwright
     уходит в мёртвый цикл, и lifespan-teardown `TestClient` висел бесконечно. Теперь
     shutdown на чужом цикле отпускает ресурсы через `_release_renderer_from_previous_loop`,
     как это уже делал путь рендера. Регрессионный тест
     `test_shutdown_does_not_await_browser_of_another_loop`.
- 🛑 **SIGTERM больше не ждёт закрытия дашбордного SSE бесконечно** (`deploy/orchestra.service`, `deploy/orchestra.service.template`): Uvicorn принудительно закрывает долгие соединения через 5 секунд graceful shutdown и продолжает штатный teardown lifespan. Случай: открытая вкладка дашборда оставляла `Waiting for connections to close`, и systemd доходил до второго сигнала.
- 📎 **Ошибка загрузки файла больше не переезжает в чат другого агента** (`app/static/js/app.js`,
  `selectAgent`): красная строка `#chat-drop-error` снимается при переключении агента. Триггер —
  загрузка PDF 29.9 МБ падала на `HTTP 413` от nginx (`client_max_body_size 20m` при лимите
  приложения 2000 МБ; nginx-лимит поднят до 2000m вне репозитория), а ошибка оставалась висеть
  после перехода к другому оркестратору.
- 📥 **Входящие сообщения в TG-топиках свёрнуты в одно сообщение** (`app/tg_bridge.py`, V-628):
  agent/platform/background/system/unknown provenance теперь получает короткий заголовок и
  `EXPANDABLE_BLOCKQUOTE`; длинный текст ограничивается 4096 UTF-16 внутри цитаты с указанием
  на полный текст в дашборде. Сводка контекстного сжатия (`compact_summary`) передаётся по
  тому же пути, а сообщения владельца и обычная речь оркестратора не меняются.
- ⏱ **Плановый precompact больше не пропускается из-за фоновых заданий** (`app/session.py`,
  V-627): таймер запускается для `IDLE` и `WAITING`, в том числе при активном cron/timer/command;
  одновременно сохраняются пропуски во время хода и уже выполняющегося сжатия. Доставка,
  пришедшая во время сжатия, остаётся в штатной очереди `_pending_messages`, а активное задание
  сохраняет статус `WAITING` после native Codex compact. *Triggered case:* постоянные фоновые
  задания оставляли seedon-orchestrator и другие сессии без планового сжатия.
- 📏 **Строка «compact done» показывает контекст одного обращения, а не сумму за ход**
  (`app/session.py`, `compact()` делит расход ack-хода на `num_turns` из его `turn_end`).
  Случай: 23.09 у katya-work ход подтверждения после сжатия сделал 4 обращения к модели по
  ~77 тыс. токенов, и отчёт написал «20% → 31% (post 307564)», хотя контекст ужался с ~198 тыс.
  до ~77 тыс. Прежний расчёт предполагал, что ack-ход — одно обращение.

### Changed
- 🎚 **Opus 5.5 работает на `medium`, а не на унаследованном `high`** (`pipeline.yaml`,
  карта `effort_policy`). Anthropic сменила умолчание эффорта именно у 5.5 и в своём
  руководстве пишет, что 5.5 на medium совпадает или обходит Opus 5 на high, а заявленные
  «−40% стоимости» считаются на умолчании и исчезают на max. Ступени с одинаковым названием
  между версиями не эквивалентны: 5.5 на том же названии думает больше предшественника.
  GPT-6 Luna добавлена в карту явно (`high`). Источник: https://claude.dev/blog/getting-the-most-out-of-opus-5-5/
- 🧭 **Общее правило «продолжай сам, останавливайся только перед необратимым»**
  (`prompts/base.md`, блок `keep-going`) — доходит до всех ролей во всех проектах. Повод:
  руководство Anthropic по Opus 5.5 отмечает, что модель на длинной работе склонна
  останавливаться ради отчёта, и это лечится явным правилом о том, какие остановки нужны.
  Наши границы сохранены дословно: слово владельца на реализацию, запрет на самостоятельный
  рестарт, архитектурная развилка и необратимые действия по-прежнему требуют вопроса.
- 🔁 **Рабочая лошадка воркеров — GPT-6 Luna** (`app/models.py`, модуль `model-routing`), решение
  владельца 23.09 после замера V-616…V-620 на одной задаче: та же работа за $0.26 против $0.57 у
  GPT-5.6 Luna, с сохранением основания закрытия задачи и перепроверкой ветки под блокировкой
  репозитория. Прежняя доступна как `luna5.6`. Алиас `sol` тоже переведён на GPT-6, но обе версии
  Sol остаются закрытыми для агентов: запрет владельца от 20.09 в силе.

### Added
- 🆕 **Opus 5.5, GPT-6 Luna и GPT-6 Sol в каталоге моделей** (`app/models.py`). CLI обновлены до
  claude 2.1.280 и codex-cli 0.156.1 — до этого Opus 5.5 отвечал «version 2.1.280 or newer is
  required», а GPT-6 — «not supported when using Codex with a ChatGPT account». Алиас `opus`
  теперь указывает на Opus 5.5 (вход $4, выход $20, чтение кеша $0.20 против $5/$25/$0.50 у
  Opus 5); прежний остаётся по `opus5`. Маршрут `luna` намеренно оставлен на GPT-5.6 до живой
  проверки воркером, GPT-6 доступен по `luna6`. GPT-6 Sol заведён с `default_agents=False`:
  запрет владельца на Sol от 20.09.2026 новая версия не снимает.

### Changed
- 🗂 **Каталог проектов — файл на каждый scope, а не один общий** (`app/project_catalog.py`,
  `app/catalog_migration_v621.py`, `app/tm.py`, `app/routes/tm.py`, `app/mcp_stdio.py`,
  `app/static/js/app.js`, V-621). До этого один `.orchestra/projects.yaml` в репозитории
  Orchestra нёс теги ВСЕХ 18 проектов, поэтому у каждого оркестратора во вкладке ЗАДАЧИ
  висели чипы чужих проектов вперемешку со своими. Теперь у каждого проекта со `scope`
  свой файл `<scope>/.orchestra/projects.yaml` (`own_catalog(scope)`), который правит
  только его владелец, руками, без рестарта платформы; оркестратор видит и может
  выставить только теги из СВОЕГО файла — `/api/tm/projects`, фильтр `tags=` и поле
  `tags` у `task_update`/`task_create` отклоняют чужой тег, даже если он существует в
  каталоге другого проекта. Слитый вид (`catalog()`) остался только для внутренней
  бухгалтерии одной установки (проекция номеров при старте, метка источника задачи) —
  собирается из домашнего файла и его `include_scopes`. Существующие 1863 задачи и их
  теги остаются валидными: `migrate_v621()` разбивает старый общий файл на файлы по
  scope автоматически при старте (по образцу V-576 — бэкап до записи, точечный
  git-коммит по своим путям), от владельца требуется один рестарт и ни одной команды.
  Непригодный чужой scope (грязный git, нет каталога на диске, отказ записи)
  деградирует вместо отказа старта всей платформы: громко логируется и остаётся в
  домашнем файле как был — тег всё ещё резолвится через слитый вид, старт не падает;
  доедет сам на следующем рестарте, когда сам scope станет пригоден. Падать на старте
  может только нечитаемый/испорченный домашний файл каталога — второй заход решения
  владельца 23.09.2026 после замечания, что жёсткое предусловие «каждый scope чист»
  роняло бы Orchestra из-за одного чужого грязного репозитория, чинить который изнутри
  уже некому.
  *Triggered case:* владелец 23.09.2026 — «эта хуйня в каждом оркестраторе свои задачи
  должны быть и свои проекты не надо мешать блять».
- 🗂 **Один каталог проектов файлом вместо двух сущностей «проект»** (`.orchestra/projects.yaml`,
  `app/project_catalog.py`, `app/tm.py`, `app/routes/tm.py`, `app/task_store.py`,
  `app/task_runtime.py`, `app/static/js/app.js`). Проект — это тег из файла, который правится
  руками и виден в диффе; словарь тегов закрыт, тега вне файла не существует. Файл владеет
  именем, `scope` и `write_namespace` (куда уходит номер новой задачи), а `tm_projects`
  деградировала до внутренней таблицы соответствия, которую человек не видит.
  `task_create` без аргументов по-прежнему берёт проект из scope агента, но теперь scope
  регистрирует каталог: неизвестный scope отклоняется с перечислением разрешённых.
  *Triggered case:* неизвестный scope молча заводил проект `scope:<путь>`, и один человеческий
  проект расползался на несколько пространств номеров — comfy-image-pipeline вёл два счёта
  одновременно (`#3…#114` и `V-67…V-112`), cog-second-brain три. Отдельно чинится живая
  ловушка: строка `orchestra` была одновременно локальным id проекта с 5 задачами и
  canonical-id чужого пространства с 375, и селектор молча возвращал не тот проект.
  *Known tradeoff:* номер задачи по-прежнему уникален только внутри своего пространства
  (замер 15.09.2026: 424 конфликтующие ссылки `#N` на 857 задач из 1755), поэтому namespace
  остался владельцем номера, а в списках рядом с номером печатается источник —
  `#161` и `#161 · ноутбук` разные задачи.

- 🏷 **Теги задачи живут в самой задаче** (`app/task_store.py`, `app/task_runtime.py`,
  `scripts/migrate_task_tags_v576.py`). `tags` — обычное мутабельное поле записи задачи в
  Git-хранилище; SQLite держит только проекцию. Задача может числиться за несколькими
  проектами или ни за одним; тег не выводится из того, где выдан её номер.
  *Triggered case:* владелец потребовал, чтобы теги хранились там же, где сами задачи —
  в файлах, а не во второй базе, которая разъедется с ними.
  *Known tradeoff:* формат записи поднят до `schema_version: 2`, и это ЛОМАЕТ ноутбук со
  старым кодом — он откажется открывать хранилище целиком (`task repository is not
  initialized`). Отказ громкий намеренно: прочитав запись молча, старый код потерял бы
  теги при первой же правке. Порядок выката: миграция → рестарт VPS → обновление ноутбука.
  Правка тега — git-коммит под flock на всё хранилище, то есть на время записи блокирует
  создание задач во всех проектах; цена принята владельцем.

### Removed
- 🗑 **Портфельный слой целиком** (`app/portfolio.py` 1207 строк, `app/routes/portfolio.py` 405,
  `app/portfolio_watchdog.py` 307, 21 роут, MCP-тулы `project_goal` и `project_wait`, параметр
  `portfolio_project` у `task_update`, доска `PROJECTS` в дашборде — 274 строки JS и 263 CSS,
  1844 строки тестов, 8 таблиц схемы и триггер `portfolio_wait_response_submitted`).
  *Triggered case:* за всё время существования слоя в проде 0 проектов, 0 целей, 0 ожиданий
  и ни одного вызова `project_goal`/`project_wait` — все совпадения в журнале оказались
  текстом промптов и выводом `rg`. Сторож застоя ни разу не сработал, потому что целей не было.
  *Reasoning:* `notify_user` жив (17 вызовов, последний 11.09.2026) и его durable-квитанция
  лежала внутри того же модуля, поэтому она вынесена в `app/attention.py` с единственным
  роутом `POST /api/attention`; таблица переименована в `attention_events`, потеряв колонку
  проекта и мёртвую `delivered_at`. Взамен `project_wait` у оркестратора появился
  `notify_user(kind="waiting")` — иначе после сноса зафиксировать ожидание решения было бы нечем.

### Added
- **V-614: shadow "DONE without a passing check" verdict** (`app/done_gate.py`, hooked
  from `app/message_deliveries.accept_message_delivery`). For every worker (not
  orchestrator) `send_message` whose text starts with `DONE`, replays that session's
  own `logs` to find the last code edit and whether a strict, successful check ran
  after it (Canny-style strictness: `| tail`, `|| true`, `; echo` don't count — idea
  from `.orchestra/tasks/V-613/research.md` §2.1, no Jev/external hook involved).
  Edits confined to `.orchestra/` or `docs/` don't count as code. The verdict is only
  recorded as a `logs` row (`type='done_gate_verdict'`); it never blocks, delays or
  changes `send_message` — any error inside the gate is swallowed. Per-scope overrides
  for what counts as code/a check live in the existing `kv` table
  (`done_gate.set_config_override`), so no schema migration was needed.
  `scripts/done_gate_weekly_report.py` counts flags over N days and cross-checks them
  against `merge_operations` rows that a real merge later turned back with
  `TEST_GATE_FAILED`/`TEST_GATE_INCONCLUSIVE`. Tests: `tests/test_done_gate_v614.py`.
  Follow-up: the verdict row is invisible to the worker's own chat — `chat.js`
  `addChatEntry` drops `type='done_gate_verdict'` the same way it already drops
  `provider_limit`, and the Telegram mirror (`app/tg_bridge.py::stream_logs`) already
  falls through its `else: continue` catch-all for unrecognized log types. Test:
  `tests/test_tg_bridge.py::TestTurnEndMention::test_done_gate_verdict_never_reaches_telegram`.
- 🇷🇺 **Русский интерфейс дашборда и переключатель RU/EN** (`app/static/js/i18n.js` —
  новый файл: словарь, `T()`, применение к разметке и сам переключатель; отметки
  `data-i18n*` в `app/templates/{login,dashboard}.html`; вызовы `T()` в `app.js`,
  `chat.js`, `usage.js`, `analytics.js`, `tool-renderers.js`, `connection.js`).
  Русский — язык по умолчанию, выбор хранится в `localStorage['orch_lang']` и
  переживает перезагрузку, переключатель доступен со страницы входа, до логина.
  Ключ словаря — сама английская строка, поэтому английская локаль работает без
  словаря и осталась дословно прежней. Механизм целиком клиентский: шаблоны и JS
  дашборд читает с диска живьём, а Python живёт в памяти до рестарта, так что
  серверный перевод доехал бы до экрана только после ручного перезапуска.
  *Triggered case:* продукт подаётся в реестр российского ПО, подп. «л» п. 5 Правил
  (ПП РФ от 16.11.2015 № 1236) требует русский графический интерфейс, а проверяет его
  живой эксперт по экранам — «перевели строки в исходниках» приёмкой не является.
  Приёмка снята прогоном по 41 отрисованному экрану (`.orchestra/tasks/V-584/audit_screens.py`):
  ноль находок латиницы, отрицательный контроль сработал на каждом экране, обратный
  контроль на английской локали — 1564 находки на 41 экране из 41.
  *Known tradeoff:* словарь по английскому ключу молча роняет перевод в английский,
  если надпись в коде переименуют; ловится только тем же прогоном по экранам, поэтому
  его надо звать руками после заметных правок интерфейса. Старый браузерный набор
  (`tests/test_frontend.py`, `tests/test_t344_quota_lines_browser.py`) проверяет
  английские подписи и пришпилен к английской локали через `window.__ORCH_LANG__` —
  его ожидания остались дословно прежними.

### Fixed
- 🔓 **`switch_worker_branch` снимает привязку воркера, застрявшего после
  `merge_worker(task_outcome="continue")`** (`app/routes/sessions.py`, `app/tm.py`, `app/db.py`,
  `app/mcp_stdio.py`). После continue-мержа ветка воркера стоит на цели, а прогон задачи
  (`review_receipts`, `subject_kind='task_run'`) остаётся открытым: `merge_worker(complete)`
  отказывал «point to the same commit», а перевод на новую задачу падал с `ValueError: open task
  run conflicts with current assignment provenance` и откатывал ветку — воркер оставался на
  старой задаче навсегда. Теперь, если снимок до git (`branch_wip_status` против базы воркера)
  чист — нет незакоммиченного и нет коммитов вне базы, — перевод освобождает прежнюю задачу
  в той же транзакции, что назначает новую (`api_update_task_if_current(release_previous=...)`):
  прогон закрывается `interrupted/binding_released`, задача по правилу `release_session_task_binding`
  возвращается в `new` (или остаётся за другим живым воркером). Явный
  `complete_previous=True` с обязательным `acceptance_note` закрывает её как `done`; основание
  и HEAD ложатся в `verdict_value`/`worker_head` закрытого прогона. Мерж не менялся.
  Грязное дерево или несмерженные коммиты сохраняют привязку (с `complete_previous` — отказ 409
  до git); задача, зарезервированная merge-операцией, не отпускается.
  *Triggered case:* katya-work 23.09.2026, воркер `struktura-ege` навсегда оставался на V-5.
  *Known tradeoff:* поведение по умолчанию изменилось для любого чистого воркера с прежней
  задачей — перевод теперь возвращает её в очередь, а не оставляет `in_progress` за ушедшим
  воркером.
- 🇷🇺 **GigaChat provider for the Harness** (`app/harness/llm.py`, `app/backend_harness.py`):
  direct OAuth and chat requests use Sber endpoints, refresh the 30-minute token (including
  one retry after HTTP 401), and translate the Harness OpenAI tool history to GigaChat's
  `functions`/`function_call` contract. `GigaChat-2` and `GigaChat-2-Max` are selectable
  alongside existing OpenRouter routes. *Triggered case:* the 17.09.2026 probe showed that
  GigaChat silently ignores OpenAI `tools`/`tool_choice` and only calls tools through its
  legacy function schema.
- 🩹 **`ORCHESTRA_LAYOUT_MISSING` при auto-switch подсказывает repair на базовом чекауте,
  а не на брошенной ветке воркера** (`app/orchestra_layout.py` — новый `_base_checkout` через
  `git rev-parse --git-common-dir`, применяется в `LayoutMigrationError` для кода
  `ORCHESTRA_LAYOUT_MISSING`). Auto-switch каждый раз заводит worktree-ветку заново от
  `base_branch`; если у `base_branch` не мигрирован `.orchestra/layout.json`, старый
  `repair_command` чинил именно эту одноразовую ветку, а не источник, и следующий
  auto-switch падал с тем же кодом заново.
  *Triggered case:* seedon, воркер `seo-cro` (`/home/kesha/projects/seedon/site`) —
  три подряд «почини» на брошенных ветках, коммиты `86e5291`, `ccb0a93`, `0dfaad4`, каждый
  раз новый круг. Воспроизведено и закрыто в `tests/test_orchestra_layout_repair_base_v611.py`:
  красный без фикса на пред-фикс коде (репо подтверждает адрес worktree вместо базы),
  зелёный с фиксом, плюс сквозной прогон «сломанный auto-switch → repair базы →
  следующий auto-switch проходит».

- 💵 **Стоимость первого хода после рестарта больше не получает накопительный итог CLI**
  (`sessions.provider_cost_baseline_usd`, `app/session_cost.py` через восстановленный
  `_last_cost`, `app/db.py`). База провайдерского `total_cost_usd` хранится рядом с
  native `session_id`; terminal `turn_usage` и новая база фиксируются одной транзакцией,
  а свежая нативная сессия обнуляет её. История `turn_usage` не переписывается.
  *Triggered case:* после рестарта 21.09 первый resumed ход записывался как `$154.21`
  вместо `$1.52`, восемь строк за неделю дали `$502` ложного расхода.
  *Migration:* перед рестартом остановить Orchestra и выполнить
  `scripts/migrate_provider_cost_baseline_v609.py --db <path>/orchestra.db --apply`.
  *Known tradeoff:* падение до commit terminal-транзакции неотличимо от потерянного
  provider result и может повторно включить этот расход в следующий cumulative delta;
  после commit потеря отдельной строки `turn_usage` baseline не раздувает цену.

- 🧪 **Merge-гейт проверяет, что изменённые тесты сторожат изменённый исходник**
  (`app/merge_test_gate.py`, `app/merge_operations.py`). После зелёного прогона на ветке
  воркера изменённые тесты запускаются в отдельном временном дереве с исходниками target;
  зелёный откат означает отказ `TEST_MUTATION_GATE_FAILED`, а timeout/сбой подготовки
  остаются явно видимым `inconclusive` и не маскируются под доказательство. Только тестовые
  или только документальные/config/prompt-правки этот контур пропускают; окружение каждого
  прогона получает временные БД и task repository до импорта `app`.
  *Triggered case:* ручная проверка ломала фикс после мержа и возвращала в цикл модель,
  хотя тесты воркера проходили; теперь мерж сам сохраняет оба вердикта и путь интерпретатора.

- 🧭 **Отказы операций над воркером различают область и отсутствие имени** (`app/routes/sessions.py` — `compact`, `session-history`, `rollback-session`, `restart-cli`, `clear-session`, `change-model`). Вместо голого `not found` ответ сообщает, что воркер с таким именем живёт в другой области и называет только её, либо что имени нет нигде и нужно проверить `list_agents`; статусы и успешные пути не изменены.
  *Triggered case:* `change_worker_model("globe-astra", "luna")` из `/home/kesha/orchestra` скрывал существование сессии в `/home/kesha/projects/comfy-image-pipeline`, и вызывающий тратил ход на догадки.

- 🧾 **Квитанция `bg_create` сразу содержит эффективную постановку задания** (`app/bg_jobs.py`, `app/mcp_stdio.py`). В ответ добавлены вычисленный конфиг, адресат, эффективный timeout, срок действия, trigger и текущее состояние; второй вызов `bg_list` для этих полей больше не нужен.
  *Triggered case:* агенты последовательно создавали джобу и тут же вызывали `bg_list`, чтобы увидеть значения, подставленные сервером.

- 🧭 **Описания MCP-инструментов приведены в соответствие с действующим контрактом**
  (`app/mcp_stdio.py`: `spawn_worker`, `send_message`, `send_file`, `send_files`,
  `send_chart`, `notify_user`, `merge_worker`, `report_bug`, `set_worker_owned_dirs`,
  `bg_create`). Восстановлены в компактном виде recovery-пути, лимиты, запреты и
  условия применения; у `set_worker_owned_dirs` убран ложный запрет пересечения
  областей: он вводил в заблуждение, поскольку пересечение допустимо, а отказ бывает
  только для running/waiting воркера, при атомарном обновлении dirs и prompt.
  `list_agents` теперь запускает независимые чтения сессий, задач и иконок конкурентно,
  сохраняя прежнее форматирование и необязательность задач/иконок.
  *Triggered case:* описание ownership советовало убить живого воркера при пересечении,
  хотя `validate_owned_dirs_transition` и миграционный тест закрепляют допустимость
  пересекающихся рабочих областей.

- 🚧 **Отказ привязки задачи называет причину и действие вместо внутренней механики**
  (`app/db.py` — `_task_binding_refusal`; описание `spawn_worker` в `app/mcp_stdio.py`).
  Было: `task #27 binding compare-and-swap failed` — одно условие, две разные причины, ни
  подсказки. Стало: «задача #27 уже закреплена за воркером 'X'; одна задача = один воркер,
  для второго исполнителя заведите отдельную» либо «строка задачи изменилась во время
  привязки, перечитайте и повторите». В описание тула добавлено, что `task_id` — номер
  СУЩЕСТВУЮЩЕЙ задачи из ответа `task_create` и что одна задача держится одним воркером.
  *Triggered case:* seedon-orchestrator получил два отказа подряд — придумал номер задачи
  под имя каталога на диске, затем посадил второго воркера на занятую задачу. Оба правила
  он узнал отказами, потому что в описании тула их не было.
  *Reasoning:* неудачный спавн уносит весь текст задания (~1 500 токенов) и вместе с
  ошибкой остаётся в истории сессии, пересылаясь в каждом следующем ходе, — непонятная
  ошибка оплачивается многократно и провоцирует повтор тем же способом.

### Changed
- 📝 **Код стороннего автора в `app/` переписан собственной реализацией** (V-610).
  Тест-лок полного прогона (`app/db.py` `acquire_test_lock`/`release_test_lock`/
  `get_test_lock`, HTTP-ручки `/api/test-lock*` в `app/routes/system.py`, MCP-тулы в
  `app/mcp_stdio.py`), выбор и удаление TG-топиков (`app/tg_bridge.py`
  `_pick_unique_topic_name`, `remove_topics_for_orchs`), `SessionManager.remove_scope`,
  путь к БД (`_db_path_from_env` вместо `_resolve_db_path`), список `disallowed_tools`
  Claude (считается один раз на сессию и общий для клиента и сверки handoff), возврат
  основного checkout после merge (`_checked_out_branch`, `_checkout` в
  `app/workspace.py`; проверка имени ветки сведена в `_branch_name_error` для всех
  четырёх мест) и диалог удаления оркестратора (статичная модалка из
  `dashboard.html` заменена диалогом `confirmOrchestratorDelete`, собираемым в JS).
  Захват тест-лока теперь начинается со вставки `ON CONFLICT(scope) DO NOTHING`:
  одновременный захват двумя агентами больше не может упасть на PRIMARY KEY между
  чтением и вставкой. Мёртвая ветка `result.get("error")` в MCP-тулах лока удалена:
  `_api` сам поднимает `ApiToolError` на ответ с `error`.
  *Triggered case:* подача в реестр российского ПО (п. 9 ПП № 1236) требует одного
  правообладателя, а `git blame` по `app/` и `scripts/` показывал 239 строк
  Диденко В. (191 из них в `.py`). После правки — 0 строк по обычному `git blame`.
  *Known tradeoff:* имена API-контрактов (MCP-тулы, env `TG_USER_MENTION`, поля
  сессии, параметры ручек) сохранены; с `-M -C` blame ещё находит их и перенесённые
  строки-разделители — подробный разбор в `.orchestra/tasks/V-610/report.md`.
- ⏱️ **Предсжатие по простою больше не ждёт заполнения контекста или дневного окна**
  (`app/session.py`, `AgentSession._schedule_precompact_timer` и
  `_fire_precompact_timer`). Таймеры Claude (55 минут) и Codex (25 минут) теперь
  взводятся от 5% контекста и после тишины сжимают его одинаково днём и ночью для
  воркеров и оркестраторов; ручной и критический пути не менялись. Нижняя граница 5%
  оставлена по формуле Claude Max: на 35 измеренных компактах медиана выжимки —
  10 552 знака (≈2 638 токенов); при контексте 5% от 200 000 (10 000 токенов)
  экономия записи `0,811 × (10 000 − 2 638) / 1М = 0,00597 п.п.` против
  `1,81 × 2 638 / 1М = 0,00477 п.п.` за выход, то есть **+0,00120 п.п.**.
  При 4% получается `0,00435 − 0,00477 = −0,00042 п.п.`, поэтому ниже 5%
  сжатие не запускается. Расходная модель: [формула Claude Max V-605](.orchestra/kb/models-and-quotas.md#формула-подписочного-расхода-claude-max-платит-запись-кеша-и-выход-v-605-21092026).
  *Triggered case:* за неделю таймер срабатывал 485 раз,
  но сжал только 8; пропуски были при `context_pct` 19, 37 и 53, а ночное окно
  дополнительно блокировало 8 срабатываний. Замер расхода — 23–28 п.п. недельного
  пула.

- 🎚 **Ступень рассуждения харнеса берётся из манифеста, а не угадывается по тексту сообщения**
  (`app/backend_harness.py` — удалены `classify_effort`, `_HIGH_EFFORT_RE` и список тривиальных
  фраз, 38 строк; `app/runtime_registry.py` передаёт `context.effort`; в карту
  `effort_policy` добавлен ключ `harness: medium`). У Claude, Codex и Grok ступень всегда
  приходила из карты `модель → effort` в `pipeline.yaml` с обоснованием замерами (#208, #373);
  харнес был единственным местом, где она выводилась поиском слов вроде «почини» или «why».
  *Triggered case:* на 12 подряд идущих реальных сообщениях пользователя эвристика вернула
  `medium` одиннадцать раз — то есть решения не принимала, а её `high` срабатывал от слова
  «почему» в любом вопросе.
  *Known tradeoff:* `harness: medium` не измерен ни на одном бесплатном маршруте — это середина
  и заодно выключатель гейта планирования (`todo_write` включается только на `high`). Появится
  замер по конкретному маршруту — добавляется строка с его id, карта разрешает id раньше рантайма.
  *Reasoning:* менять ступень посреди разговора нельзя — платформа при расхождении пересобирает
  сессию (`app/session.py`, перечитывание манифеста), и это холодный старт с потерей кеша;
  манифестное значение задаётся на спавне, то есть там, где старт и так холодный.

### Changed
- 🔗 **`CLAUDE.md` теперь симлинк на `AGENTS.md`, а не его копия** (`scripts/check_instruction_contract.py`
  требует симлинк и отвергает копию; режим `--sync` удалён за ненадобностью). Claude Code читает
  только `CLAUDE.md`: поддержка `AGENTS.md` заявлена в ченжлоге 2.1.277 как fallback «если нет
  CLAUDE.md», но на 2.1.278 у нас не включается — проверено с отключёнными файловыми инструментами
  и положительным контролем, в пустом каталоге с одним `AGENTS.md` агент отвечает «НЕТ», тот же файл
  под именем `CLAUDE.md` читается. Симлинк — обход, который рекомендует сама официальная
  документация Anthropic по памяти.
  *Triggered case:* пока рядом лежали две копии, они дважды разъехались; в одном случае `CLAUDE.md`
  был на 671 байт короче и не содержал правил владельца про маскирование секретов и про Codex.
  *Reasoning:* копия требует синхронизации и молча устаревает, симлинк не может разойтись физически;
  Codex продолжает читать `AGENTS.md`, Claude — `CLAUDE.md`, содержимое у них одно и то же.
  *Known tradeoff:* проверка контракта теперь ЗАВИСИТ от файловой системы с симлинками; на носителе
  без них корень придётся собирать иначе.

### Fixed
- 🧯 **Один кривой вызов инструмента больше не убивает остаток сессии воркера**
  (`app/harness/loop.py` — `_sanitize_tool_args`, вызывается после диспетча раунда).
  Ассистентский месседж с `tool_calls` уезжает в КАЖДЫЙ следующий запрос, а строгий
  провайдер отвергает весь запрос, если аргументы хоть одного вызова — не строка-объект
  JSON: Cohere отвечает `invalid tool call provided in messages[42].tool_calls[0]: tool
  arguments must be a stringified JSON object`. Разбор и сообщение об ошибке уже
  происходят при вызове инструмента, поэтому в истории негодное значение заменяется
  на `{}`; валидный объект не переформатируется — он уезжает рядом с подписью рассуждений.
  *Triggered case:* 17.09.2026 воркер на `cohere/north-mini-code:free` после одного
  такого вызова не смог сделать больше ни одного хода.
- 🚫 **Бесплатные маршруты, отказавшие в нашей пробе, больше не предлагаются и не
  проходят спавн** (`app/models.py` — `BLOCKED_HARNESS_ROUTES` и проверка в
  `validate_harness_model_spec`; `app/model_catalog.py` — фильтр в `apply_model_catalog`).
  Каталог OpenRouter продолжает рекламировать у них поддержку инструментов, поэтому
  допуск по живому каталогу (#V-582) их пропускал. Заблокированы восемь: `inkling`
  и `inkling-small` (HTTP 403 — открыты только в харнесах провайдера), `laguna-s-2.1`,
  `laguna-xs-2.1`, `gemma-4-31b-it` (HTTP 429 в обоих прогонах), `nex-n2.5-mini`
  (таймаут чтения 90 с), `nemotron-3-nano-omni-...-reasoning` (инструмент не вызывается),
  `ling-3.0-flash-vl` (вызывает и игнорирует результат).
  *Triggered case:* проба #V-581 и повторный прогон 17.09.2026; отказ наступал только
  на спавне, уже потратив ход воркера.
  *Reasoning:* блок стоит в двух точках, потому что одной регистрации мало — маршрут
  может прийти из сохранённой сессии, минуя выбор моделей. Снимается по одной строке
  при обратном замере, не списком.
- 🔁 **Временная перегрузка провайдера больше не убивает ход воркера целиком**
  (`app/harness/llm.py` — `_StreamError` и ветка повтора в `OpenRouterClient.stream`).
  OpenRouter отдаёт перегрузку апстрима не статусом, а обычным SSE-чанком с полем
  `error` уже при 200 OK («Upstream error from Nvidia: Service temporarily overloaded»,
  «Upstream idle timeout exceeded»), поэтому прежний ретрай по 429/5xx её не видел.
  Повтор разрешён ровно до первого отданного события и только для заведомо временных
  ошибок (код 5xx/408/409/429 либо текст про перегрузку, таймаут, недоступность);
  отданное событие или нетранзиентная ошибка вроде исчерпанных кредитов — честный отказ.
  *Triggered case:* вечером 17.09 пять воркеров на бесплатном маршруте
  `nvidia/nemotron-3-ultra-550b-a55b:free` потеряли так 13 ходов, каждый раз вместе
  с несохранённой работой; ошибок 429 при этом не было ни одной.
  *Known tradeoff:* повтор не спасает, если модель успела отдать текст или вызов
  инструмента — дублировать побочные действия опаснее, чем потерять ход.
- 🧭 **Допуск харнес-маршрута решается по живому каталогу OpenRouter, а не по нашей
  записи о нём** (`app/models.py` — `validate_harness_model_spec`, из
  `SELECTABLE_MODEL_SPECS` убраны оба зашитых харнес-маршрута; `app/model_catalog.py` —
  `live_catalog_entry`, `harness_capable` вместо приватного `_cached_harness_eligible`).
  Отказ наступает, когда провайдер говорит «нет tools» или маршрут исчез из каталога,
  даже если наше поле `supported_parameters` утверждает обратное. Состав харнес-маршрутов
  теперь приходит ТОЛЬКО из каталога. *Triggered case:* замер 16.09.2026 (#V-581) показал,
  что мертвы оба зашитых: `z-ai/glm-5.2:free` в живом каталоге отдаёт `tools=False` и
  `ctx=32768` против наших 256000, а `nvidia/nemotron-3-ultra-550b-a55b:free` вызывает
  инструмент и игнорирует его результат. До правки это узнавалось только сожжённым ходом
  воркера. *Known tradeoff:* с пустым кешем каталога ни один харнес-маршрут не проходит
  допуск — выбрано осознанно (fail-closed), каталог подтягивается обновлением на экране
  моделей.
- 🏷 **Окна квоты Codex подписаны своей длительностью, а не позицией в ответе**
  (`app/static/js/utils.js` — новый общий `windowLabel`, `_PROVIDER_META.codex.windows`;
  `app/static/js/analytics.js` — подписи окон Spark). Панель аналитики печатала
  «Основной» и «Вторичный», что ничего не сообщало о том, какой лимит упёрся.
  Заодно снята вторая копия этой логики: ярлык считался ещё и в `app/static/js/usage.js`
  (`_codexWindowLabel`), теперь владелец один. *Triggered case:* 17.09.2026 аккаунт
  перешёл с free на Plus, и у Codex вместо одного 30-дневного окна стало два — 5 часов
  и неделя; на панели они назывались «Основной/Вторичный», хотя у Claude рядом
  честно стоят 5h и 7d.


### Added
- 🔬 **`scripts/probe_free_models.py` — проба `:free` маршрутов на полный протокол
  инструментов** (`--out` с машиночитаемым JSON, `--model`, `--limit`,
  `--requests-per-route`, `--budget-seconds`). Маршрут засчитывается пройденным, только
  если он вызвал инструмент, передал осмысленный аргумент И ответил ПО РЕЗУЛЬТАТУ
  инструмента; вызов с игнорированием ответа — `result_ignored`, то есть непрошедший.
  Ошибки провайдера (`rate_limited`, `http_403`, `timeout`) отделены от отказов самой
  модели, а маршруты, до которых не дошёл бюджет, помечаются `not_probed`, а не молча
  выпадают. *Triggered case:* проба жила разовым скриптом в `.orchestra/tasks/V-581/`,
  и проверять протухание маршрутов было нечем.
- 🔓 **Кнопка «снять гейт на время» на панели квот** (`app/quota_gate.py`:
  `set_gate_override`/`clear_gate_override`/`gate_override_remaining`, `POST
  /api/usage/quota-override`, индикатор и кнопка в `app/static/js/quota-lines.js`).
  Пока снятие действует, полоса не держится диагональю, а потолок полосы (`sol` 95%)
  заменяется общим; **жёсткий стоп не снимается никогда** — за ним стоит предел
  провайдера, и пропуск туда обменял бы наш отказ на 429 у провайдера. Снятие живёт в
  памяти процесса и гаснет при рестарте: это выбрано намеренно, потому что забытое
  бессрочное снятие уже стоило трёх суток снятого гейта (`QUOTA_GATED_LANES=` с 12.09
  по 15.09.2026), а потеря снятия отказывает в безопасную сторону. Потолок одного
  нажатия — 6 часов. Агентам выключатель не выдан: ни MCP-тула, ни параметра спавна.
  *Known tradeoff:* снятие общее, а не по полосам — снять только Claude, оставив Sol,
  сейчас нельзя. *Triggered case:* 16.09.2026 спавн воркера отбит нашей же линией на
  0.4 п.п. (23% против 22.61%) в начале недельного окна, при том что пул был свободен.

### Fixed
- 🚦 **`lanes[].gated` в карте квот берётся из вердикта гейта, а не из состава
  `policy.gated_lanes`** (`app/routes/system.py`). При временном снятии полоса остаётся
  в списке гейтящихся, но прямо сейчас не держит — панель рисовала бы её держащей.

### Changed
- 🧹 **У каждого повторявшегося правила в каталоге промптов остался один владелец**
  (`.orchestra/pipelines/default/prompts/`: `modules/background-jobs.md`,
  `modules/orchestration.md`, `roles/worker.md`, `roles/full-cycle.md`,
  `roles/sub-orchestrator.md`). Дублем считалось только то, что попадает в ОДИН собранный
  промпт дважды, поэтому совпадения между `roles/worker.md` и `roles/full-cycle.md` не
  трогались — эти файлы никогда не встречаются вместе. Сведены к владельцу: `owned_dirs`
  как не-allowlist (три места → `modules/git-workflow.md`), «silence is not consent»
  (два → `modules/user-values.md`), commit-before-DONE и запрет built-in `SendMessage`
  (`modules/git-workflow.md` и `base.md`), «зелёный прогон не закрывает невоспроизведённый
  дефект» и test-first (`modules/code-quality.md`). Тег `<background-jobs>` больше не
  открывается в промпте оркестратора дважды: обёртка снята с модуля, владелец тега —
  `base.md`, как у `modules/dynamic-workflows.md`, где тега нет вовсе. *Проверка:* промпт
  каждой роли пересобран из `HEAD` и из дерева, состав восьми категорий-якорей не
  изменился ни у одной роли, и каждое исчезнувшее предложение имеет названный дом в
  промпте той же роли (`.orchestra/tasks/V-577/verify.log`). Каталог 147 130 → 146 585 Б,
  промпт оркестратора 73 530 → 73 371 Б, воркера 33 293 → 32 964 Б, редьюсера без
  изменений. *Известный компромисс:* `modules/model-routing.md` не тронут — Sol, Terra и
  Fable живы в реестре (`app/models.py:56,95,103`) и алиас `codex` до сих пор указывает на
  Sol, поэтому «do not use» там — действующий запрет, а не мёртвая ветка.

### Fixed
- 📛 **Скилл деплоя больше не обещает автоматический `uv sync`, которого в юните нет**
  (`.orchestra/pipelines/default/prompts/skills/vps-deploy.md`). Строка 34 утверждала, что
  «`uv sync` runs automatically via `ExecStartPre`», и противоречила правилу в строке 54
  того же файла («do not run an unpinned `uv sync` in production»). Фактически
  `ExecStartPre` у `orchestra.service` отсутствует, а эффективный `ExecStart` задан
  drop-in'ом `60-runtime-isolation.conf` и равен
  `/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m uvicorn app.main:app --fd 3`
  (сверено с `/proc/<MainPID>/cmdline` живого процесса). *Триггер:* разбор V-577 —
  единственное расхождение каталога промптов с реальностью машины.
- 🔀 **Мерж больше не запирается на расхождении ДВУХ ЗАПИСЕЙ ПЛАТФОРМЫ — про ветку
  спрашивают git** (`app/routes/sessions.py`, `execute_merge_session`). Раньше
  `expected_branch` операции сверялся с колонкой `sessions.branch`, а git в этой точке не
  опрашивался вовсе. Закреплённая операцией ветка САМА приходит из git
  (`accept_merge_operation` → `_session_snapshot` → `inspect_worktree_identity`), поэтому
  отказ означал только одно: колонка БД отстала — и новая операция падала точно так же,
  ведь приём снова пинил ту же git-ветку. Теперь при расхождении читается worktree: git на
  закреплённой ветке и на закреплённом HEAD → `sessions.branch` приводится в соответствие
  с git (`persist_lifecycle`, привязка задачи не трогается) и мерж идёт; любое другое
  состояние или неудачный опрос worktree → отказ (fail-closed), и его текст называет все
  три стороны — что в БД, что закрепила операция, что показывает git. Git платформа не
  двигает и не переименовывает: чинится только СВОЯ запись.
- 🧭 **`next_action` на `SESSION_IDENTITY_CHANGED` перестал предписывать ремонт, который не
  может сработать** (`app/merge_operations.py`, `_classify_failure` и ветка
  `_verify_accepted_snapshot`). `REFRESH_WORKER_THEN_NEW_OPERATION` звал `worker_wip`, а тот
  через `branch_wip_status` только ЧИТАЕТ git и в `sessions.branch` ничего не пишет — обе
  стороны сравнения после «починки» оставались прежними. Теперь
  `INSPECT_WORKER_THEN_NEW_OPERATION`: осмотреть `worker_wip`, затем начать операцию БЕЗ
  `operation_id` (приём перепинит ветку и HEAD с worktree), и прямо сказано, что повтор того
  же `operation_id` помочь не может. Отказ `_verify_accepted_snapshot` заодно называет
  значения обеих сторон, а не голый список полей.
  *Triggered case:* 15.09.2026, проект seedon — пять операций на одном готовом результате,
  три FAILED с побайтово одинаковым текстом (`f9731106-c585-4a28-80e8-f2e61e7a98ef`,
  `d68cd973-0673-4b29-a59a-bb6de26926bc`, `806519aa-85c6-49ab-a494-a840ec8af9c8`); оркестратор
  в итоге подгонял git под устаревшую строку БД (`git branch -f adhoc-…`), то есть чинил
  правильное состояние по неправильному. Тест-якоря —
  `tests/test_identity_drift.py::test_stale_branch_record_is_repaired_when_git_confirms_the_pin`
  и три отказных плеча рядом.
  *Known tradeoff:* разрешающее плечо требует совпадения И ветки, И HEAD, поэтому воркер,
  дописавший коммит после приёма операции, при разъехавшейся записи получит отказ, хотя на
  здоровой записи такой `BENIGN_ADVANCE` мержится. Запись платформы правится только под
  полным подтверждением от git; выход назван в самом тексте отказа — новая операция.
  Первопричина потери привязки (обнуление `sessions.task_id` с уходом ветки в
  `adhoc-<ts>/<имя>`) здесь не чинилась.
- 🚦 **Правка квотных `QUOTA_*` в `.env` наконец применяется без рестарта**
  (`app/quota_gate.py`, `_dotenv_owned_names`, `_live_quota_env`). Обещание «горячей»
  перечитки файла по mtime было мёртвым в бою: systemd отдаёт процессу весь `.env`
  через `EnvironmentFile`, поэтому каждый ключ приходил ещё и в окружении, а
  значение со старта перебивало файл — включая пустую строку. Теперь ключ, чьё
  стартовое значение совпало со снимком файла в тот же момент, считается
  принадлежащим файлу, и его правка действует сразу; значение, отличное от файла
  (шелл, unit-файл, разовый прогон тестов), по-прежнему держится до рестарта.
  *Triggered case:* 15.09.2026 владелец вернул общий гейт командой «включай общий
  гейт снова на лимиты», `QUOTA_GATED_LANES=claude,sol` лёг в `.env`, а живой
  процесс продолжал работать со снятым гейтом, потому что стартовал с пустым
  значением из того же файла.

### Changed
- Уточнены trigger orchestra-agents, условность исследовательских шагов и границы
  выбора роли/согласований. Причина: общие описания конфликтовали с исключениями
  собственных скиллов и уже разрешённой самостоятельной работой; формат ответа
  владельцу, безопасность и приёмка сохранены.
- Добавлен единый pipeline-скилл laptop-access с прямым SSH через обратный туннель
  и датированной картой каталогов. Причина: личные версии расходились и описывали
  недоступную платформенным агентам обёртку вместо проверенного маршрута.
- Общие правила файловой безопасности и ведения документации доставляются модулями
  safety и project-maintenance из pipeline.yaml. Code-quality подключён всем ролям,
  которым разрешены изменения проекта. Причина: отдельные managed CODEX_HOME не
  наследовали обычный глобальный AGENTS.md, поэтому личный файл не обеспечивал
  одинаковую доставку этих правил разным рантаймам.
## v2.45.2 — 2026-09-15 — производная от `.env` больше не может доехать до публичного репозитория

### Fixed
- 🔐 **`.gitignore` закрывает весь класс `.env.*`, а не одно точное имя** (`.gitignore:4-8`, `!.env.example` оставляет публичный шаблон версионируемым). Гейт секретов (`scripts/secret_scan.py`) ловит по ФОРМЕ провайдера, и токена Telegram (`<digits>:<base64url>`) в его списке форм нет — значит `.env`, попавший под `git add -A`, гейт бы пропустил. Игнор закрывает класс раньше, чем дело дойдёт до разбора форм. Тест-якорь: `tests/test_secret_commit_gate.py::test_repo_gitignore_covers_every_env_derivative`, краснеет при снятии правила.
- **Triggered case:** 15.09.2026 в рабочем дереве VPS (`/home/kesha/orchestra`, origin — ПУБЛИЧНЫЙ `github.com/DrSeedon/orchestra`) лежал untracked `.env.V-545-20260914-050429.bak`. Один `git add -A` любого агента — и весь боевой `.env` уезжает наружу. Утечки не случилось, история чиста: единственный `.env*` за всё время в индексе — `.env.example` (c547a112, 09.05.2026).
- **Known gap:** на VPS `.git/hooks` был ПУСТ — гейт секретов там не стоял вовсе, притом что коммитят на нём агенты, а не владелец. Поставлен тем же `scripts/install_git_hooks.py`; хуки не версионируются, поэтому на каждом новом клоне команду надо повторять.

## v2.45.1 — 2026-09-15 — чужой битый репозиторий больше не роняет старт Orchestra

### Fixed
- 🩹 **`migrate_registered_projects` изолирует ЛЮБУЮ ошибку проекта, а не только `LayoutMigrationError`** (`app/orchestra_layout.py:1104-1128`). `_run_bytes` бросает голый `RuntimeError`, поэтому сбой git внутри `_recover_preserved_dirty` → `_restore_preserved_stash` → `_diff_paths` пролетал мимо `except LayoutMigrationError` и убивал lifespan целиком. Теперь второе плечо `except Exception` пишет тот же контракт `{status: failed, code: ORCHESTRA_LAYOUT_GIT_ERROR, repository, error, repair_command}`, `app/main.py:391` логирует проект как деградировавший, а сервис поднимается. `BaseException` (`KeyboardInterrupt`, `SystemExit`) не перехватывается.
- **Triggered case:** 15.09.2026 на ноутбуке владельца Orchestra не стартовала, systemd крутил рестарт-петлю — **892 рестарта**. Причина: в `/mnt/data/Projects/Python/TradingCryptoBot` пустой объект `.git/objects/4f/25fc30…` — это preserve-stash, который создала сама Orchestra и который обнулило аварийное выключение машины 13.09. Один чужой checkout, который Orchestra даже не редактирует, останавливал платформу для всех 20 проектов. Тест-якорь: `tests/test_orchestra_layout_fleet_430.py::test_fleet_isolates_a_raw_git_failure_from_a_broken_checkout`.
- **Known issue:** четыре проекта стартуют деградировавшими и чинить их надо в их собственных репозиториях, не в коде Orchestra: `tradingcryptobot` (пустой объект), `parsing-hub` и `stargate-tactics` (`cannot locate the migration commit while recovering stash=…`), `VPN-Service` (`ORCHESTRA_LAYOUT_PARTIAL`). Подробности и объём потерь — в `TODO.md`.

## v2.45.0 — 2026-09-11 — жёсткий стоп пула стал свойством полосы: хвост недели остаётся дешёвой модели

### Changed
- 🚦 **Потолок жёсткого стопа теперь у каждой полосы свой** (`app/quota_gate.py`, `QuotaPolicy.hard_stop_for`, `line_limit`, `evaluate_worker_admission`). По умолчанию `sol` (туда же попадает Astra) встаёт на **95%**, `luna` остаётся на **99%**, `claude` и `spark` не меняются — у Claude свой пул, у Spark свой кошелёк. Настраивается как остальное правило: `QUOTA_LANE_HARD_STOP_PCT=sol=95,luna=90` в окружении или в `.env` с той же горячей перечиткой по mtime, что у `QUOTA_HARD_STOP_PCT`. Общий `QUOTA_HARD_STOP_PCT` остаётся общим: `hard_stop_for` берёт `min` из него и потолка полосы, поэтому опустив общий стоп владелец опускает и полосу со своим потолком, а не открывает ей дорогу выше. Решение полосы едет наружу в `QuotaDecision.hard_limit_pct` и в блоке `rule.lane_hard_stop_pct` карты квот; панель (`app/static/js/quota-lines.js`, `_qlHardStop`) рисует для такой полосы отдельную линию стопа и кладёт на неё же свою кривую — иначе картинка показывала бы 99% там, где гейт уже не пускает. *Triggered case:* 11.09.2026 недельный пул Codex выжран до 99% дорогой моделью, до сброса четверо суток, не стартует ни один Codex-воркер — при том что те же 5 п.п. по кредитной модели провайдера это ~800 ходов Luna против ~9 ходов Astra.

## v2.44.0 — 2026-09-06 — оглавление базы знаний собирает платформа, а не корневой файл

### Added
- 📚 **`app/kb_index.py` — платформа вставляет оглавление тем KB в системный промпт агента.** Собирается из `<scope>/.orchestra/kb/README.md` того проекта, где работает агент, и приходит в `ROLE_SYSTEM_PROMPT` (`app/manager.py:347`) — там же, где живёт `<worker-memory>`. Блок получают ВСЕ роли манифеста, включая `reducer`: он не лежит ни в одном `prompts/modules/*.md`, поэтому роль с коротким `modules:` не может его потерять. 40 тем = 3 800 Б, +3 802 Б к промпту любой роли (+5.3% оркестратору, +22.0% редьюсеру).
- **Новая тема доезжает до живого агента на следующем ходе, без рестарта.** Тот же путь переинжекта, что у личной памяти: `session.py` → `manager.assemble_prompt` → `ROLE_SYSTEM_PROMPT`. Замерено на `assemble_prompt`: строка, дописанная в README между двумя вызовами, есть во втором промпте, и заголовок блока в нём ровно один — блок пересобирается, а не дописывается. Чтобы это работало у воркеров, им теперь тоже передаётся `scope`; блоки других оркестраторов и воркеров остались под `if is_orch` и воркеру по-прежнему не видны.

### Changed
- **Индекс убран из корневых `AGENTS.md`/`CLAUDE.md` вместе с маркерами `<!-- kb-topics:start/end -->`.** `--sync` больше не генерирует список — только зеркалит `AGENTS.md` в `CLAUDE.md`. Один список — один владелец: разбор README живёт в `app/kb_index.py`, и `scripts/check_instruction_contract.py` читает ТОТ ЖЕ парсер (`check_kb_index`), поэтому незаиндексированная тема ловится как раньше, но чинится правкой одного файла. Корень: 20 751 → 17 041 Б; зеркало восстановлено (до этого `CLAUDE.md` = 16 370 Б и не содержал правил владельца про маскирование секретов и Codex 0.153.4 — Claude-агенты их не видели).
- **Known issue:** контракт остаётся красным, перебор над 16 KiB сократился 4 367 → **657 Б**. Резать дальше нечего без решения владельца; кандидаты названы в `TODO.md`.

### Reasoning
- Список тем описывает ПРОЕКТ агента, а не правила Orchestra, поэтому его место — в сборке промпта, а не в версионируемом файле: в корне он ломал потолок 16 KiB, требовал `--sync` + коммит на каждую новую тему и вообще отсутствовал в чужих проектах. Проект без `.orchestra/kb/README.md` или с пустым индексом не получает ни блока, ни пустого заголовка — «тут знать нечего» это утверждение, которого мы не проверяли.

## v2.43.0 — 2026-09-04 — сторож памяти: один прожорливый процесс умирает вместо всего дерева

### Added
- 🛡 **`app/runaway_guard.py` — сторож, убивающий ОДИН процесс, вышедший за потолок RSS.** Каждые 20 с обходит `/sys/fs/cgroup/system.slice/orchestra.service/cgroup.procs`, читает `VmRSS` из `/proc/<pid>/status` и после ДВУХ подряд превышений шлёт `SIGKILL`, записывая в журнал pid, объём и полную командную строку. Потолок `RUNAWAY_GUARD_LIMIT_MB=2048`, интервал `RUNAWAY_GUARD_INTERVAL`, выключатель `RUNAWAY_GUARD_ENABLED=0`. Собственный pid Orchestra не трогается никогда: его смерть — отказ платформы, а не лечение.
- **Почему не хватало живого `MemoryHigh=8G` на юните:** cgroup-лимит наказывает ВСЁ дерево, а не нарушителя. 04.09 `awk` с вложенным квантификатором `([^|]*\|){8}`, написанный Luna в ходе `codex_review` воркера `ane-research` (comfy-image-pipeline, задача #96), вырос до **7.9 ГБ на файле в 21 КБ / 53 строки**. Cgroup упёрся в `MemoryHigh`, начал реклейм — и в своп уехали Orchestra, четыре агентских CLI и TG-мост разом: **iowait 68.7%, load 26 на 12 ядрах, свободной RAM 280 МБ, отклик `/api/sessions` не измерялся**. Виновник при этом продолжал работать в состоянии `D`. После `SIGKILL` вручную: RAM 280 МБ → 3.7 ГБ, load 26 → 10.3, отклик 57 мс.
- **Почему не `RLIMIT_AS` на агентских CLI** (первый напрашивающийся вариант, отвергнут замером): они резервируют адресное пространство десятками гигабайт при копеечном RSS — `claude` показывает `VmPeak` **9.27 ГиБ** против `VmRSS` **220 МБ**. Любой осмысленный потолок убил бы сам агент, а не его выродившегося внука. Потолок 2 ГиБ выбран как ~6× над всем легальным, что удалось намерить (максимум одного процесса в cgroup — 0.31 ГиБ, суммарный пик прогона шарда pytest — 0.50 ГиБ), и ~4× под аварией. **Known tradeoff:** замер на самых тяжёлых 40 файлах сьюта не доехал (таймаут на 49%), поэтому верхняя граница легального прогона намерена не полностью; потолок вынесен в переменную окружения именно из-за этого.
- Сторож поднимается в `lifespan` рядом с `portfolio_watchdog` (`app/main.py`). Оракул — `tests/test_runaway_memory_guard.py`, три шва (убийство нарушителя без соседей, требование двух страйков, неприкосновенность своего pid), каждый проверен отдельной мутацией; плюс живая проба на настоящем процессе в 2.26 ГиБ — первый проход молчит, второй убивает с кодом −9.

### Known issue
- **Сторож смотрит только на ПАМЯТЬ.** Осиротевший `chrome-headless-shell` от прерванного прогона Playwright крутил 458% CPU при 341 МБ RSS и под это правило не попадает. Ловится тем же обходом cgroup, но требует второго замера (CPU за интервал) и другого потолка — отдельная задача.

## v2.42.0 — 2026-09-03 — компакт: честная квитанция, дословный хвост, терминальный отказ

### Fixed
- **Строка успеха компакта врала во ВСЕХ 75 случаях из 75** (`app/session.py`, `compact()`). Печаталось `compact done: 100% → 100%`, хотя реально контекст падал до 23%. Причина: `after_pct` читался из `self._last_context` синхронно сразу после ack-хода, а свежая сессия отдаёт `DeferredContext`, чья ветка в `app/session_cost.py:116` процент НЕ ТРОГАЕТ — точное число прилетало фоновым `_refresh_context_from_api` уже после возврата. Теперь размер новой сессии считается по расходу самого ack-хода (`_context_token_total()`, разница снимков до и после), медиана ошибки 2 п.п. на 57 замеренных компактах против 200К-окна, где ошибка была бы 30 п.п. Квитанция получила `pre_tokens`, `post_tokens`, `dropped_tokens` — аналог `compactMetadata` у Claude Code. *Triggered case:* сравнение систем компакта показало медиану сжатия «1.0x» на 75 компактах, что физически невозможно.
- **Компакт сессии со снесённым worktree ретраился трижды с бэкоффом 30 и 60 секунд** (`app/session.py`, `_is_terminal_compact_error`). `Working directory does not exist` — 27 из 38 всех ошибок компакта в базе, то есть 9 воркеров × 3 бесполезные попытки по 90 секунд каждый. Отказ признан терминальным и возвращается с первой попытки. **Known tradeoff:** предикат по подстроке текста SDK, а не по предусловию на `self.cwd` — предусловие ломало два чужих теста #380, чьи фикстуры используют несуществующий `cwd` при замоканном бэкенде.

### Added
- 🧵 **Дословный хвост диалога рядом со сводкой** (`app/session.py`, `_preserved_tail`, `COMPACT_TAIL_CHARS=12000`). Сводка — пересказ, и самый свежий обмен терял в ней формулировки: Claude Code хранит последние сообщения сырыми (`preservedSegment` в `compactMetadata`), у Orchestra их не было ВОВСЕ — весь контекст проходил через горлышко пересказа. В преамбулу новой сессии теперь едет блок `[VERBATIM TAIL]` с последними репликами (`user_message` и `text`) в пределах бюджета символов. `tool_result` в хвост намеренно не берётся: это 442 МБ из 555 МБ всего содержимого логов, то есть ровно тот вес, ради которого компакт и затевается. **Reasoning:** берётся `self.id` (id сессии Orchestra), а НЕ `session_id` нативного CLI — `logs.session_id` ссылается на `sessions.id`; первая версия брала нативный и молча давала пустой хвост, поймано оракулом T2.

### Known issue
- **Микрокомпакт строить не нужно — он уже есть.** Orchestra поднимает тот же бинарник Claude Code (`cli_path = shutil.which("claude")`, `app/backend_claude.py:909`), а в нём 2.1.259 лежат `tengu_time_based_microcompact`, `compact_micro_keep_recent`, `tool_result_clear` и `microcompact_boundary`: выгрузка тел `tool_result` с сохранением через `persist(content, tool_use_id)` по серверному `context_hint`. Следов его СРАБАТЫВАНИЯ в наших транскриптах нет, но отсутствие события означает неизвестность, а не отсутствие механизма.

## v2.41.1 — 2026-09-02 — чат дашборда чинён: гейт происхождения отвергал КАЖДОЕ сообщение
### Fixed
- **`POST /api/sessions/{name}/send` без `sender` больше не отвечает `403 SOURCE_PROVENANCE_REQUIRED`** (`app/routes/sessions.py`). Гейт из #433 требовал авторизованного оператора, но `validate_session` возвращает False при пустых `DASHBOARD_USER`/`DASHBOARD_PASSWORD` (`app/auth.py:58-61`) — это наша штатная конфигурация, — а фронт шлёт в `/send` только `{message, scope}` (`app/static/js/chat.js`). Оператор был недоказуем В ПРИНЦИПЕ, поэтому чат дашборда не работал ЦЕЛИКОМ, а не иногда. Теперь недоказанное происхождение помечается `origin="unknown"` и сообщение доставляется. **Reasoning:** это правило самого #433 («отсутствующее происхождение рисуется как `unknown`, НИКОГДА как `user`») — отказ означал не «не соврать», а «не доставить». Ветка с доказанным кукой оператором по-прежнему даёт `user`, ветка с `sender` — `agent`. *Triggered case:* юзер написал агенту из дашборда и получил 403; ветка 403 не была покрыта ни одним тестом, поэтому оракулы #433 её падение не заметили.
- **Тот же класс дефекта пойман третий раз за двое суток** — операторский гейт на контуре с выключенной авторизацией отказывает ВСЕМ: 01.09 в `POST /api/message-deliveries/{id}/resolve` (снят вместе с эндпоинтом), 01.09 в `restart_preflight`, теперь здесь. **Проверка перед любым новым `require_operator_*` / `validate_session`: пройдёт ли этот путь на контуре БЕЗ `DASHBOARD_USER`?** Нет — значит гейт не сужает доступ, а выключает функцию.

## v2.41.0 — 2026-09-01 — codebase audit: 27 defects closed, 2 fixes reverted as regressions

Multi-agent audit (`docs/tasks/audit-0901/report.md`): 10 reviewers → 33 findings → adversarial
verification → three rounds of fixes, with every diff reviewed. Gate run: 915 passed, EXIT=0.

### Fixed
- **Canonical and legacy state in `app/tm.py` diverged in three places—one defect, one ticket (3×P0).** (1) `_api_update_task_if_current_unlocked`: a canonical CAS rejection fell through to `_candidate_receipts` and raised `KeyError: 'stable_id'` after legacy state had ALREADY been committed—a split brain. The shadow branch handled the same rejection explicitly; the canonical branch did not. The failure was systematic: legacy-only writers (`bind_task_to_session`, requeue/heir, `finalize_merge_outcome`) advance only legacy `sync_revision`, so every bound task permanently has `legacy_rev > canonical_rev`. (2) `discard_unbound_task` issued a raw DELETE only against `tm_tasks` (`TaskStore` has no deletion at all), making counters diverge so `IdentityConflictError` blocked EVERY subsequent task creation in the project. (3) `api_create_task` committed canonical state BEFORE fallible legacy validation, with no try/except or compensation. *Triggered case:* the TODO defect “`switch_worker_branch` is not atomic, `KeyError: 'stable_id'`” was symptom (1); the 28.08 comfy incident with jammed counters was symptom (2).
- **Permanent session-lock deadlock** (`app/session_hibernate.py`): three RUNNING→IDLE heartbeat transitions did not publish `publish_turn_finished`, while `wait_for_turn_completion` parked on that event with no timeout INSIDE `wait_for_session_lock`. `switch_worker_branch` hung forever, never released the lock, and every subsequent switch, merge, or delivery received LockBusy until restart—even though the dashboard showed the worker as `idle`. All three sites now publish the event, and the wait no longer trusts it blindly.
- **The restart button did nothing during an active mutation** (`app/routes/system.py`): `732d89cc` removed the gate from `_do_restart_service` and reduced the budget to zero, but `restart_server` first called `restart_preflight` with the old gate. With a 0.0 budget, any mutation returned 409 “still in flight after 0s.” The rule that restarts proceed without asking was not enforced in code; TG `/restart` used the same path.
- **The quota chart printed the WRONG threshold for Sol** (`app/static/js/quota-lines.js`, `app/routes/system.py`): every marker used the linear `bucket.limit_pct` label, including Sol's curved lane, although the curve itself was drawn correctly. At 50% window progress, the label said “threshold 55.5%” while the curve ran at 81.3%. The frontend now uses `lanes[].limit_pct`, which the server already sent.
- **Harness tokens grew quadratically** (`app/backend_harness.py`): `_cumulative_input/_output` were not reset between turns, and `_turn_end` returned them as per-turn `AggregateUsage`; `session_cost` then added them after every turn. Ten 50K turns produced ~2.75M rather than 500K. The implementation now follows the Codex scheme (`_usage_baseline`).
- **Control messages to the harness disappeared silently** (`app/harness/loop.py`, `app/backend_harness.py`): the `_injected` queue was drained only at the start of a tool round; on the final round or an interrupted turn, the next `clear()` destroyed the remainder even though delivery was already marked `SUBMITTED`. A carried-over message now arrives and is placed at the correct chronological position.
- **Voice messages whose transcription took over 30 seconds disappeared silently** (`app/tg_bridge.py`): after `MEDIA_WAIT_MAX`, `buf.epoch` rotated; late transcription failed the epoch check and returned without carry-over or notification. If the voice message was the only message, nothing at all was sent. The fix also closes double resolution of the same token, loss of the `important` flag in the mirror, collapse of distinct messages in one topic, and a synchronous `subprocess.run` in `_bot_api_health_loop` that froze the entire event loop and swallowed `sudo` failures.
- **MCP printed “accepted” for terminally failed deliveries** (`app/mcp_stdio.py`): `_message_delivery_receipt_text` special-cased only `DELIVERY_UNKNOWN`, so `FAILED_BEFORE_SUBMIT` (including non-retryable `TARGET_TASK_CHANGED`) was printed as acceptance; `_delivery_receipt_text` for `spawn_worker` had the same flaw. Merge recovery also discarded a CONFIRMED `FAILED` status and claimed “status could not be confirmed,” while the retry hint after a failed spawn lost the cross-repository warning.
- **Restart, not a person, clears the delivery barrier** (`app/message_deliveries.py`): `DELIVERY_UNKNOWN` at the FIFO head silenced a worker indefinitely (25 hours and six lost assignments), while the sender received a cheerful `QUEUED`. The barrier is justified while the outcome may still change—but after a restart, the process that could complete the delivery is dead and ordering can no longer change. `recover_message_deliveries` changes these records to `DELIVERY_UNKNOWN_ORPHANED`: the queue resumes, while uncertainty remains recorded as `DELIVERY_OUTCOME_UNRECONCILED` and is never treated as “delivered.” A sender behind a live barrier now sees `TARGET_QUEUE_BLOCKED` and its age.
- **SSE froze `agent_status` at connection time** (`app/routes/sessions.py`): `live_session` was resolved only once per connection, so a session not loaded when the stream opened stamped an active turn's events as `idle`, and the client overwrote the correct status.
- **The ×1000 money migration could run twice** for legitimately small prices (`app/db.py`). A durable marker now replaces value-based guessing, with a journal line whenever it runs.
- **A background job interrupted in the `triggering` phase remained stuck forever** (`app/db.py`). For a `run` job, users were told “interrupted by restart; the command was not rerun” even though the command HAD completed and its result was stored in the row. The result is now delivered through the normal trigger path (`app/bg_jobs.py`).
- **`resolve_base_branch` crashed `merge_worktree_to_main`** (`app/workspace.py`): target validation changes no refs, but ValueError escaped to the route's catch-all and became `partial/unknown`, retaining the task reservation. It now reports an honest `failed/not_reached`; the handling also covers `RuntimeError`, `OSError`, and a missing git binary.

### Removed
- Manual resolution of delivery barriers: the `POST /api/message-deliveries/{id}/resolve` endpoint, the `resolve_message_delivery` function, the manual-resolution state, and the operator gate. **Reasoning:** the gate depended on an operator session, but with authentication disabled (our default `.env` without `DASHBOARD_USER`), `require_operator_session` rejects EVERYONE, so the endpoint was dead on the laptop. Across 1,043 deliveries since 25.08, `DELIVERY_UNKNOWN` occurred ZERO times—an authenticated endpoint for such an event was overengineering. Restart-based automatic barrier clearing replaces it (see Fixed).

### Known tradeoff
- **Two fixes were reverted as regressions, and the defects returned to TODO.** (1) The `anthropic_fable` quota-gate bucket: the live `weekly_scoped` limit arrives with `resets_at: None`, so the bucket would have no parseable window, the diagonal would not apply, and Fable would be protected only by the hard 99% stop—a WEAKER gate than the current one. (2) Forced teardown in `AgentSession.interrupt()`: background `_disconnect_backend()` canceled the listener and heartbeat for an already NEW turn, leaving a `RUNNING` session without a watchdog—worse than the original false report. Rule #224 was applied literally: when the cure is worse than the disease, remove it entirely.
- **Contract #380 R7 was revised.** The earlier rule that “`DELIVERY_UNKNOWN` must never be bypassed” applies while the outcome can still change; after a restart, it cannot. Three `test_message_delivery_receipts_380.py` oracles failed ONLY on the state name—the behavioral checks (do not call the provider again, do not schedule the runner, `retryable: false`) were unchanged.

## v2.40.1 — 2026-09-01 — Claude no longer silently downgrades xhigh

### Fixed
- **`effort=xhigh` reaches the API as xhigh for Claude models.** Instead of silently downgrading to high, `backend_claude.py` enables `options.thinking = {"type": "adaptive"}` and passes through the requested effort. Technical cause: the 21.07 guard (`eff == "xhigh" → "high"`) protected against `400 output_config.effort 'xhigh' is not supported when thinking is disabled`; a two-arm live probe on Opus 5 on 01.09 showed that the SDK path accepts xhigh both with adaptive thinking and even without the flag—the guard had gone stale and silently stole the requested effort. **Triggered case:** the user hit the same 400 in interactive Claude Code (Opus 5 + ultracode + the thinking toggle off). Interactive mode explicitly sends `thinking: disabled`; Orchestra's SDK path does not. The `pipeline.yaml` defaults are unchanged (Opus remains high per #208); the branch activates only when xhigh is explicitly requested.

## v2.40.0 — 2026-08-19 — #343 one quota-admission rule; previous systems removed

### Added
- **The only worker-admission rule: a diagonal with shrinking tolerance plus a hard 99% stop** (`app/quota_gate.py` is the sole owner). Baseline = percentage of the window elapsed; tolerance = a linear `10` percentage points at the start of the window → `1` point near reset; threshold for a gated lane = `min(99, baseline + tolerance)` (`line_limit`, `tolerance_pp`). Sol and Claude workers are blocked STRICTLY above the line. Luna and Spark bypass the diagonal entirely; their only stop is `HARD_STOP_PCT`. Orchestrators never pass through the gate (the `is_orchestrator` check in `app/manager.py` and `app/session.py` precedes the gate call). A worker's pool is selected by model runtime; window start = `resets_at − window_minutes`; one formula covers Claude's fixed weekly window and Codex's rolling window (`window_progress`). The rule looks only at the current point and retains no history, so counter resets work without dedicated reset code. *Triggered case:* the old thresholds were flat percentages, so 40% usage looked equally normal on day seven and catastrophic on day one.
- **Spark uses its OWN `codex.spark.primary` counter, not the aggregate Codex counter** (`deciding_window`). *Triggered case:* on 19.08, Codex showed 100% while Spark showed 39%; one number cannot represent both pools, and the aggregate counter would have blocked the cheap executor alongside the expensive one.
- `GET /api/usage/quota-map` gives the panel a ready-made verdict and `limit_pct`/`tolerance_pp`/`progress` for every pool, plus the rule constants in `rule`. JavaScript does not duplicate the arithmetic: a second owner of the numbers would silently diverge from the gate. Contract: `docs/tasks/343/api-contract.md`.

### Fixed
- **Unknown quota PASSES, consistently at every call site** (`require_worker_admission` rejects only `state="blocked"`). The old fail-open behavior existed at one site only: spawn passed with `quota=unknown`, but the next mandatory `/send` returned 429 for the same condition. *Triggered case:* #227 produced a dead session that was unusable yet indistinguishable from a live one, which forced the gate to remain disabled. `unknown` now passes spawn, `/send`, queue draining, compaction, and `codex_review`.
- The stale `tests/test_mcp_quota_gate.py` fixture responded to `/send`, although spawn has long used `/api/sessions/{name}/initial-deliveries`; the test was red on `main`.

### Removed
- Removed in full, including tests, database fields, endpoints, and settings: `app/quota_controller.py` (shadow controller #291), `app/quota_runway.py` and `deficit_hours`/`min_work_hours` (the observational half of #314), `app/quota_alert.py`, `app/runtime_router.py` (inert audit path #187), `_quota_headroom` and the derived weekly block in `/limits`, `worker_model_policy` with `model_policy_override_reason` (gate #227), and the `quota_controller_*`, `quota_alert_state`, `quota_silence`, `runtime_routing_*`, and `usage_exchange_rate` tables.
- Removed nine endpoints: `/api/usage/quota-controller` (plus `/policy` GET/PUT, `/policy/rollback`, `/reserve` POST/DELETE), `/api/usage/routing-policy` (GET/PUT), and `/api/usage/routing-policy/explain`. `/api/usage` no longer returns `quota_headroom`; `/api/usage/analytics` no longer returns the `quota_controller` key. The legacy dual-wire readiness wrapper (`worker_readiness_envelope`, `wire_version`, `decision_state`) is gone: with fail-open for `unknown`, every branch reduced to “pass.”

### Reasoning
- The user selected this as the final rule, and it was implemented literally. `docs/tasks/314/quota-line-controller.html` shows its behavior on live data. Removal was preferable to coexistence because thresholds lived in four places at once (gate constants, hot `quota_controller_policy`, pipeline manifest, and router config); answering “why won't this worker spawn?” required reconciling all four.
- Thresholds are deliberately NOT operator-configurable: the hot policy was the second owner that made the numbers diverge. Changing the rule means changing the code.

## v2.39.4 — 2026-08-16 — #290 fail-closed cross-runtime handoff

### Changed
- **Runtime switching is now a verifiable transaction, not an optimistic transcript import.** Orchestra freezes one deterministic state packet from its own `logs`, computes the entire declared model-visible manifest up front, runs a separate tools-disabled ingress canary, verifies an independent capability receipt, and only then releases the source. The packet neither carries hidden reasoning nor elevates transcript/tool data to system/repository authority; an incomplete tool effect blocks the switch before a target is created.
- **Fallback is limited to one smaller packet candidate.** Network/auth/unknown errors are not disguised as incompatibility; a second compatibility failure ends the operation loudly. Two operation-ledger tables are added additively, while an ambiguous crash leaves the session in `recovery_required` rather than guessing ownership or redelivering a side effect.
- **All cross-runtime capabilities remain disabled.** Codex 0.146.0 and Grok 1.0.3 have not mechanically proven an empty ingress tool surface. Claude CLI 2.1.197 / `claude-agent-sdk==0.2.114` proved tools-disabled ingress, but the live semantic canary hit quota, and the complete provider-private normal surface cannot be serialized exactly before process launch. Before source release, Claude also verifies the attached normal-profile surface and provider-reported complete context, but this is a safety gate, not permission to enable the capability. Updating `claude-agent-sdk` deliberately breaks import/validation via a version tripwire and requires an isolated canary. The ledger remains; there is no return to silent summary/fresh-target switching.

### Compatibility gate
- A screenshot of an internal Codex benchmark dated 15.08 reports these results for a 741-turn / 231 MiB conversation: 27.62→1.66 s, 894→16 requests, 15,529→64 loaded transcript items, and −41.2% whole-app memory growth. The metric is named `conversation-renderer JavaScript heap`, so this is evidence about UI/lazy loading, not model context. As of 16.08 there is no official release note for the optimization, and the installed CLI remains 0.146.0.
- After an official release, one bounded A/B is allowed: native-resume latency/RSS/request count, plus a separate raw-history import payload/context-admission test. Packet/preflight ceilings stay in place until a separate token/context canary proves a change in model-visible behavior; a UI win alone is not that proof.

## v2.39.3 — 2026-08-15 — Grok chat: no double answer bubble

### Fixed
- **Grok's response is no longer drawn twice at the end of a turn** (`app/static/js/app.js`). `_log` is fire-and-forget: `turn ended` status sometimes received an id before `text`; defensive finalization on status closed streamBubble, and the following `text` created an identical second bubble. Finalization on `turn ended` is removed; `text` with the same body after live finalization is skipped (`_lastFinalizedStreamText`). *Triggered case:* “Nice. Another clean bubble” + Reasoning + the same text again.

## v2.39.2 — 2026-08-15 — Grok harness polish: resume flood + thinking

### Fixed
- **`session/load` no longer floods logs with old history as new events** (`_suppress_history_replay`, `_drain_history_replay_queue`). *Triggered case:* after compact/reconnect, a “hello” at 07:40:07 re-recorded dozens of tool/thinking/text events from the previous turn; user messages “disappeared” beneath the first-paint flood.
- **One reasoning card per turn, not 50+**—thinking flushes only on turn_end/fail/exit; tool/plan events flush only `text`. *Triggered case:* 54 thinking bubbles starting at 07:30.
- **MCP tool_result unwraps `OkayOutput`** (`_content_text` for `{type:MCP, output:{OkayOutput}}`). *Triggered case:* list_agents appeared as a JSON wrapper rather than a card.

### Known tradeoff
- Replay already written to the DB (07:36/07:40) remains; only new turns after restart are clean. Grok's 60-second compact acknowledgment timeout is unchanged.

## v2.39.1 — 2026-08-15 — Grok harness: connect + chat UI

### Fixed
- **Grok `session/new` no longer fails on HTTP/SSE MCP configurations without `headers`** (`app/backend_grok.py` `_mcp_server_configs`, `_headers_to_acp`). Bare `{type:http,url}` → Invalid params (measured on grok 0.2.112); the request now always includes `headers: []` or a list of pairs. *Triggered case:* COG-second-brain's `agentic-jobs` URL-based MCP broke switching to Grok, while Orchestra-orchestrator without HTTP MCP started normally.
- **Grok responses are stored in history and no longer merge across turns** (`_message_buf`/`_thought_buf` → final `text`/`thinking` on tool/plan/turn_end/fail). Previously only live `stream`/`thinking_stream` events were emitted, while the session persists only `text`/`thinking`: the DB held zero text events for an entire day after switching to Grok, and the frontend bubble stayed open. *Triggered case:* “messages merge into one,” reasoning appears in a separate live card above it, and responses vanish after reload.
- **Grok tool results are plain text, not a JSON grid** (`_content_text` unwraps `{type:content, content:{type:text,…}}`). *Triggered case:* the chat showed `type / content / text` instead of read/grep output.
- **Frontend: defensively close the stream on `turn ended` and show a `grok mcp ready` badge** (`app/static/js/app.js`).

### Known tradeoff
- The Python changes (`backend_grok.py`) take effect after an Orchestra restart or Grok-session reconnect. JS/CSS changes do not require a restart.

## v2.39.0 — 2026-08-13 — #245 dashboard voice input

### Added
- **Mobile voice input with a text preview was added to the message field** (`initVoiceInput`, `startVoiceInput`, `app/static/js/app.js`, `app/static/css/style.css`). A second tap stops recording; a separate `×` cancels it without a request; a timer and RMS indicator driven by `AnalyserNode` show live volume. Chrome selects Opus/WebM; Safari selects a supported MP4 format via `MediaRecorder.isTypeSupported`. The transcript is appended to the textarea and is never sent to the agent automatically. Permission, browser, network, and server errors appear beside the field. *Triggered case:* users had to type long messages on a phone even though Orchestra's Telegram path could already transcribe voice messages.
- **`POST /api/transcribe` accepts browser recordings and uses the shared Deepgram client** (`app/routes/tg.py`, `app/transcription.py`, `app/tg_bridge.py`). A single `transcribe_audio` serves both Telegram and the dashboard. Before the external request, the server validates MIME type, enforces a 10 MB ceiling and a real five-minute duration limit via `ffprobe`, then deletes the temporary file after the response. *Triggered case:* copying the Deepgram call into the frontend route would have created a second owner of retry/cache/cost logic and allowed unlimited uploads.

### Known tradeoff
- The new Python route appears in the running process only after a managed Orchestra restart. Shipping JS/CSS alone shows the button, but transcription returns 404 until restart.

## v2.38.3 — 2026-08-12 — #228 mandatory Bash payload guard

### Added
- **New and reconnected Claude sessions receive one `PreToolUse` guard for `Bash`, only when `CLAUDE_BASH_HOOK_ENABLED=1`** (`app/backend_claude.py`). The flag is off by default and read when the client is built, so a restart/reconnect applies the change without a code rollback. When enabled, the guard stops `run_in_background=true`, recursive `rm`, `chmod 777/0777`, and direct `curl | sh/bash`; the rejection text gives a safe next step (`bg_create(type=run)`, `trash`, least-privilege mode, or inspecting the file first). A normal newline is a command boundary; GNU forms such as `rm target -rf` and unambiguous `--r`/`--recu` abbreviations are covered too. Guard failure, internal timeout, or unknown outcome remains a loud `ERROR` but fails open. The matcher has no external deadline; the only time boundary in our code is the internal fail-open `wait_for(0.1)`.

### Known tradeoff
- This is a narrow mini-grammar, not a shell sandbox. Remaining historical misses are one quoted `rm -rf` inside a nested SSH shell, four `for …; do rm -rf …; done` bodies, and one `find -exec rm -rf`. Wrappers, shell keywords, expansion, command substitution, and nested shells are deliberately not claimed as covered. A heredoc body is data; commands after its terminator are analyzed again. Existing Claude clients do not receive the hook until a controlled reconnect; activation and the marker canary run in a separate operator window.

## v2.38.2 — 2026-08-12 — #222 narrow Spark admission

### Changed
- **Spark became a narrow fast/overflow route with an external oracle** (`pipelines/default/prompts/modules/model-routing.md`). Before spawn, the task must name no more than two files, fit within 100K of total initial context, specify every decision, and provide an independent mechanical check for every criterion. Semantic prose, review, and research are forbidden; any unsuccessful Spark run moves to another model without retry. The dedicated Spark bucket is explicitly described as small, and its unknown research-preview price makes cost totals incomplete. *Triggered case:* in blind replay, Spark silently invented a missing constant 2/2 times and failed the future oracle (19/42 and 18/42), while Luna stopped and asked 2/2 times. At ~164K, by contrast, Spark rejected both runs loudly before answering.

### Known tradeoff
- **Until #301, Spark has no reliable completion/accounting path in Orchestra.** `CODEX_TOKEN_PRICES["gpt-5.3-codex-spark"] = None`, and `_codex_cost()` fails before `turn_end` is created. Already streamed text may remain visible, but the completion event and dollar accounting are lost. We do not substitute a zero rate: any Codex-dollar total that may include Spark usage is understated by an unknown amount.

## v2.38.1 — 2026-08-12 — #212 `Read` images in chat history

### Fixed
- **Truncated `Read` results containing images are restored from the complete log row** (`_restoreToolResultImage`, `_toolResultImageSrc`, `app/static/js/app.js`). Chat still prefers the original file, then an inline thumbnail. If the temporary path is gone and the 16 KB history limit truncated base64, the frontend requests `/api/logs/{id}` and renders the full image with its actual media type. *Triggered case:* `/tmp/wedding-contact.jpg` had disappeared, `/api/files/raw` returned 404, and the dashboard left `🖼 [Image result]` even though the event log retained the complete image.

## v2.38.0 — 2026-08-11 — #174 native history import, Claude ↔ Codex

### Added
- **Codex→Claude transfers the complete conversation from `logs`, not a bounded summary** (`app/runtime_history.py`, `AgentSession._change_to_claude_with_history_locked`, `ClaudeBackend`). User/assistant records and completed tool call/result pairs are rendered into a target-native transcript through `SessionStore.load()`; reasoning is not synthesized. Tool history has a hard ceiling of 256,000 serialized model-visible characters, while payload and metadata are scrubbed of known secrets, including wrapped/URL-safe base64. An incompatible version or rejected schema explicitly activates the old summary fallback; reconnect releases the old SDK client even after version-preflight failure. *Triggered case:* during runtime switching, the production mechanism gave the new model at most 120 recent records / 32,000 characters and lost all tool results—in a measured long session, only 0.86% of the text survived. The first import implementation made the opposite error, reproducing 680,548 tool characters under a claimed 256,000-character budget.
- **Claude→Codex uses only `thread/resume.history`** (`render_codex_history`, `CodexBackend`, `AgentSession._change_to_codex_with_history_locked`). The experimental capability is enabled only for the import connection. The fresh thread ID in the response becomes the durable native ID, while ordinary resume still fails if the ID is substituted. Both adapters share one normalizer, sanitizer, and hard cap for tool history; historical tool calls are completed and marked as already executed. *Triggered case:* app-server 0.146.0 deliberately ignores a supplied seed ID during history import, so the old generic resume guard rejected a valid import as a foreign thread.

### Known tradeoff
- **`claude-agent-sdk` is deliberately pinned to `0.2.114`.** The native transcript contract was verified only with Claude CLI 2.1.197 / SDK 0.2.114. Updating `claude-agent-sdk` now deliberately breaks history import through a version tripwire and requires an isolated native canary; the pin must not be removed without that canary. The SDK accepts opaque provider entries, but its public type does not promise schema compatibility.
- **Codex history import is pinned to CLI `0.146.0` and an experimental API.** Any other version deliberately activates summary fallback before app-server starts; a CLI update requires an isolated native canary. Upstream marks `thread/resume.history` as unstable / cloud-only, so seamless import is not a guaranteed contract for the next version.

## v2.37.0 — 2026-08-11 — #185 chat navigation

### Added
- **Clickable event timeline and sequential navigation through your own messages** (`initChatTimeline`, `_jumpChatTimelineUser`, `app/static/js/app.js`). A narrow bar on the right distinguishes your messages, agent replies, workers, tools, statuses, and errors. The first `↑` jumps to your latest message, then cycles backward; `↓` moves forward. The timeline's `MutationObserver` processes only added and removed top-level nodes, avoiding a full-history scan on every render. *Triggered case:* in sessions with 7,338 records, finding your latest message manually meant scrolling through a mixed feed of messages, tools, and workers.

### Known tradeoff
- The timeline reflects only the loaded portion of chat and retains the existing `MAX_CHAT_NODES = 500` limit; unloaded pagination is not materialized as hidden markers. This keeps long live-session switching free of measured regression: median first paint was `78.0 → 61.8 ms` over five before/after runs. No speedup is claimed because the baseline ranged from `66.9–219.2 ms`.

## v2.36.1 — 2026-08-10 — #173 P0 prompt correctness

### Fixed
- **Reload no longer mixes personal memory with the custom/ownership overlay** (`app/manager.py`, `app/prompting.py`, `sessions.prompt_overlay`). A new nullable component distinguishes a legacy assembled prompt from an explicitly empty overlay. Reload removes every stale `<worker-memory>` block and inserts exactly one current block. Rename and manual replacement of the full prompt update the same persistence contract. *Triggered case:* audit #172 reproduced full-cycle prompt growth from `84,652 → 129,655 B` and stale memory appearing after an ordinary reload.
- **`codex_review` no longer labels every project `small team, MVP stage`** (`app/mcp_stdio.py`, `codex-debate.md`). The caller must provide its own `PROJECT CONTEXT`; an empty or context-free call fails before readiness/API, and both review modes receive one neutral rubric. *Triggered case:* high-load projects received understated severity calibration from an unconditional constant.
- **Codex guidance now matches the current runtime/config** (`CLAUDE.md`, `compact_worker`). It records the machine-local `project_doc_max_bytes = 131072` with a mandatory config recheck, native `.codex/skills`, and native same-thread compaction for automatic/manual Codex; Claude summary→fresh behavior is documented separately. *Triggered case:* #172 found three rules that already contradicted current code and configuration.


## v2.36.0 — 2026-08-06 — #127 prompts trimmed for Opus 5, #119 artifact skill rewritten

### Changed
- 🧹 **Removed self-review instructions that Opus 5 already performs on its own** (`Adversarial self-review` in `pipelines/default/roles/worker.md` and `roles/full-cycle.md`). Anthropic's official migration guide says to remove instructions where the review target is the agent's own output and no new observation is introduced. The “Checks and evidence” collection is UNCHANGED: it requires producing an artifact (run, mutation, command output), which the guide does not address.
  - *Triggered case:* the user received a summary of the guide claiming that “the main migration work is deletion.” The primary source contains four removal sections versus seven addition sections, while a grep for its own anti-patterns found two real matches in our 132,753-character collection. The correct cut was 330 bytes, not half the file.
- 🎚 **A delegation ceiling instead of “always spawn”** (`modules/orchestration.md`, Step 0.5 in `base.md`). Opus 5 delegates more readily than earlier models. A fresh spawn pays for ~90 KB of prompt again (≈$4 even for a one- or two-turn session, measured across 31 sessions). Queue mechanics and `check_conflict` are preserved verbatim; only the frame changed: parallelism is a means, not an end.
- 📏 **Length calibration for written artifacts** (`<communication-style>` in `base.md`). The threshold is new factual content, not file size: a measurement-heavy report is “correctly long,” while a section with no fact absent from the rest is padding at any length. *Triggered case:* the median file in our `docs/` was 10.3 KB, the maximum 61.8 KB, and five files exceeded 52 KB, yet there was no length rule at all.

### Added
- 🎨 **The `html-artifacts` skill was rewritten around design principles extracted from Codex** (`pipelines/default/prompts/skills/html-artifacts.md`). The hard-coded `#7c3aed` accent is gone; the palette derives from the artifact's subject, the type scale comes from one base, `@media print` is mandatory, and shadows are allowed only as state.
  - Measurement across 14 artifacts in independent sessions: purple 5/5 → 0/5, font-size scale 0/5 → 5/5, print support 0/5 → 5/5, focus states 1/4 → 3/3.
  - The honest limit of the effect is recorded in `docs/tasks/119/report.md`: there are two perceptually distinct tones, not five, and on everyday topics the old skill moved away from purple on its own. Some of the improvement belongs to the topic, not the change.

### Fixed
- 🌗 **The skill specified the arguments to `light-dark()` in reverse order** (`html-artifacts.md`). The specification puts the LIGHT-theme value first; an agent following the skill literally produced inverted themes. Nothing crashes or highlights the defect—the artifact simply renders backward. *Triggered case:* found in #123 by running one file under `color_scheme=light` and `dark` in the same execution.
- 🖱 **Image paths are inserted at the caret, not at the end of the field** (`_insertPathAtCaret`, `app/static/js/app.js`). Previously, `input.value += ...` moved the path to the end while restoring the caret to its old position, so the user continued typing before the path. A duplicate was removed at the same time: the ➜ button in the file tree called its own copy of the same logic.
- ⏱ **The drop test waits for every upload result instead of a fixed 100 ms** (`tests/test_frontend.py`). *Triggered case:* the flake occurred 3/9 times on code WITHOUT the #94 change and 1/9 times on current `main`. Alternating runs in two scratch worktrees proved the failure was unrelated to the change.

### Reasoning
- Prompt changes went into project files, not global `~/.claude/CLAUDE.md`: the `AGENTS.md` mirror is built byte-for-byte from `CLAUDE.md`, so every deletion automatically reaches Sol/Spark/Grok, where nobody has verified the claim that “the model checks itself.”
- The open question remains explicitly open: the distinction between self-review and producing an evidence artifact is inferred from the guide's examples, not stated in it. Only an A/B of `full-cycle` with and without the evidence section can close it; neither we nor Anthropic have that measurement.

## v2.35.5 — 2026-08-04 — #69 migration no longer confuses scope with repository

### Fixed
- 🧭 **`migrate_agent.py` asks git for the worker repository instead of deriving it from scope** (`worker_repo`, `target_worktree`, `slugify_repo`). `--from-scope`/`--to-scope` simultaneously acted as project directory and git repository: the bundle came from the root repository, while the directory slug came from scope, although the platform derives it from the **repository root** (`create_worktree`). In a project with nested repositories, this produced a bundle without the required branch and a path the platform would never inspect.
  - The repository is resolved exactly as the platform resolves it: `cd <worktree> && cd "$(git rev-parse --git-common-dir)/.." && pwd`. Failure falls back to scope, with an explicit warning that this is wrong for nested repositories.
  - The target path is computed **once per worker** (`target_worktree`) and reused by the transcript, worktree, and database row. Divergent copies of this formula caused the defect.
  - A missing target repository now fails loudly on the receiving host: silently moving a worker into another repository would give it unrelated history.
  - **Triggered case:** seedon contains `site/` and `infra/`, independent repositories with their own origins, both ignored by the parent. In #67 I declared their sessions unrecoverable precisely because I searched for repositories as name-based siblings instead of using `rev-parse --show-toplevel`.
  - Verified end to end: a worker from a nested repository migrates into ITS OWN repository (the copy contains `site.txt`, not files from the root repository) and commits. Mutating the repository source back to scope makes the test fail.
- 🌿 **`base_branch_strategy=parent` no longer blocks spawn across a repository boundary** (`app/manager.py::_resolve_base_branch`, `_crosses_repo_boundary`, `app/workspace.py::repo_root`). A parent on a feature branch in the root repository and a child in `site/` means the parent's branch does not exist there. Previously this raised `ValueError: local base branch does not exist`, which concealed the cause. Now, if the repositories are DIFFERENT (compared through git, not string prefixes), the base comes from the child's repository mainline and a WARNING names both repositories. If they are the SAME repository, the original error propagates unchanged because the missing branch is real. If repository identity cannot be determined, the code assumes no boundary: the original error is more honest than an invented explanation.

### Known tradeoff
- ⚠️ **The end-to-end nested-repository migration test requires passwordless sudo** (the `needs_two_users` marker from #55; the skip is explicit). Without it, only unit tests for the path formula remain.
- ⚠️ There is no silent base substitution, but the WARNING appears only in logs; the worker does not learn of the change from its prompt. For `strategy=parent` into another repository, this is a deliberate compromise; the alternative is refusing to spawn.

## v2.35.4 — 2026-08-04 — #62 test runs no longer erase other workers' worktrees

### Fixed
- 🛑 **Worktree cleanup does not run under pytest** (`app/manager.py::start_background_tasks`). `TestClient(app)` enters lifespan, which used to start `_periodic_worktree_cleanup`. A test that replaced `app.db.DB_PATH` with an empty temporary database but left the REAL `app.workspace.WORKTREE_ROOT` unchanged concluded there were “no live sessions” and deleted every project's clean worktree, including registrations in `.git/worktrees` and scope directories.
  - **Reproduced before the fix:** a green `pytest tests/test_build_signal.py` in a sandbox copy of the checkout erased both decoys and their registrations. **After the fix**, the same command preserves 2/2.
  - Seven files instantiate `TestClient` without isolating the root: `test_auth.py`, `test_bug_report_notify.py`, `test_build_signal.py`, `test_logs_sync.py`, `test_merge_operations.py`, `test_startup_bridge.py`, `conftest.py`. The safeguard for the next such file is the `_isolate_worktree_root` autouse fixture in `tests/conftest.py`.
  - **Triggered case:** at 14:19:56 UTC on 03.08, subagent `local_bash` ran “Verify template guard and run task 15 tests” in the MAIN checkout; at 14:20:37, `feat-instant` lost its working directory. Only four Orchestra directories were restored then. Seven seedon worktrees and the dnd-game-master directory remained deleted for two days, until the seedon orchestrator first tried to switch branches.
- 🚧 **An empty list of live sessions no longer means “delete everything”** (`app/workspace.py::cleanup_stale_worktrees`). An empty registry signals the wrong registry, not dead worktrees; the code now emits WARNING and aborts the pass. A second guard preserves any directory whose name belongs to a live (non-archived) session even if the stored path differs. A mismatch is a reason to inspect, not erase.
- 📢 **INFO from `app.*` modules is visible in journald again** (`app/main.py`). The handler was attached only to logger `"orchestra"`, while modules use `logging.getLogger(__name__)`; `app.workspace`, `app.session`, and the others are not descendants of `"orchestra"`, the root logger was empty, and `lastResort` filtered below WARNING. Consequently, worktree deletion left no journal entry: `journalctl -u orchestra --since 2026-08-03 | grep -c "stale worktree"` → **0**. The `app` package root is now configured, so new modules are visible by default. Worktree deletion itself is logged at WARNING; it is not routine.
- 🩹 **A worker whose worktree disappeared is shown as `broken`, not `idle`** (`app/session.py::_display_status`). Previously it looked healthy and failed only when assigned work; seven seedon workers remained “idle” for two days.

### Restored
- ♻️ **Seven seedon worktrees were restored** from `sessions.branch` at the paths stored in the database (`bizdev`, `designer`, `dev-lead`, `direct-research`, `marketer`, `payroll`, `sales`), with `.env` and `.mcp.json` copied as `create_worktree` does. The branches survived: cleanup deletes working trees, not refs.

### Known tradeoff
- ⚠️ **There is no source from which to restore `infra` and `seo-cro`.** Their `worktree_path` points to `…-seedon-infra` and `…-seedon-site` slugs, while the database scope is `/home/kesha/projects/seedon`; no `seedon-infra`/`seedon-site` repositories exist on the host, nor do seedon's `adhoc-748404/infra` / `task-1/seo-cro` branches. This data mismatch predates the incident; the orchestrator must decide whether to archive or rebind them.
- ⚠️ **`broken` is a new frontend status value.** `app/static/js/app.js` has its own status dictionaries and will show it as unknown; updating that dictionary belongs to the frontend owner (territory #33).
- ⚠️ The `test_api.py` race where “the monkeypatch is removed while the cleanup thread is still running” was not reproduced (three runs, 150 cleanup calls) and was not fixed separately; both guards in `cleanup_stale_worktrees` cover it as well.

## v2.35.3 — 2026-08-04 — #55 migrated workers can commit again

### Fixed
- 🔑 **Migration transfers the target repository's `.git` to the service user as well as the worktree** (`scripts/migrate_agent.py`). `git worktree add` and bundle `git fetch` run over SSH as the login user (usually root), leaving that user as owner of 17 target `.git` entries: `worktrees/<name>/*`, `refs/heads/<branch>/*`, `logs/refs/heads/*`, `objects/pack/*`, `FETCH_HEAD`. The old `chown` covered only the worktree, which was wholly insufficient.
  - **Two measured failures, not inferred ones.** (1) With a completely transferred worktree (0/0 foreign entries), git still reports `fatal: detected dubious ownership in repository at '<worktree>'`; for a linked worktree it also checks gitdir `.git/worktrees/<name>`. (2) After transferring gitdir too, `status` works but commit fails: `cannot lock ref 'HEAD': Unable to create '.git/refs/heads/<branch>.lock': Permission denied`.
  - **Triggered case:** the dnd-game-master orchestrator's 03.08 bug report—`kill_worker` and `worker_wip` failed with `dubious ownership`, leaving `force=true` as the only way to stop the worker, i.e. a kill WITHOUT checking unmerged work. The “check WIP before kill” gate silently vanished for every migrated agent. The other half was quieter and worse: under the rule “ALWAYS commit before reporting DONE,” a worker that can read but cannot commit appears healthy and loses its work.
- 🕵️ **The service user comes from the systemd unit, not the installation directory's owner** (`unit_service_user`, `target_service_user`, new `--to-unit`/`--from-unit`). Directory ownership is a guess: on 03.08, 3,021 files under `/home/kesha/orchestra` on this same VPS belonged to root while the unit had `User=kesha`. At that moment the script would have run `chown -R root` and **reported success**, preserving the defect it meant to fix. The `LoadState=loaded` gate is mandatory: `systemctl show <nonexistent-unit> -p User` prints nothing and exits 0, indistinguishable from a live unit without `User=` (the same class as the `OOMScoreAdjust` trap). If the unit does not exist, the code falls back to the directory owner with an explicit “this is a guess” label.
- 👁 **The chown check is no longer blind** (`_foreign_entries`, `_mode_snapshot`). Previously `find … 2>/dev/null | wc -c` returned `0` both when every entry had the right owner and when the path did not exist; the function reported a successful transfer without touching anything. Missing and unreadable paths now fail with different messages, and modes are compared after `chown` to ensure ownership, not permissions, changed.
- 🔊 **`git bundle create` and `git fetch` errors are no longer discarded** (`2>/dev/null || true` removed). The operator now receives the cause of lost worker commits; previously only the downstream symptom remained: `git worktree add: invalid reference`.

### Changed
- 🧹 **`git config --global --add safe.directory` on another host was replaced by one-shot `git -c safe.directory=…`** (`git_at`). The old approach permanently added an exception to the login user's gitconfig on a host we merely visit, while doing nothing for the service user—it treated the symptom for the wrong user.

### Reasoning
- We considered running target-side git through `runuser -u <service-user>`, which would prevent the defect structurally rather than cleaning up afterward. It was rejected on cost: every remote git call would have to be rewritten for a rare, human-operated migration. Revisit if migration becomes frequent.
- The original report's claim that `worker_wip` turned every git error into “no main or master branch exists” **required no change**: `4b722ba` (#7) fixed it at 09:31 UTC on 03.08, one hour after the report was filed at 08:28 UTC. A live run verified that `branch_wip_status` returns the actual git text for a foreign repository. The report sat for two days because nobody connected it to the fix already on `main`, motivating #56 (bug-report delivery).

### Known tradeoff
- ⚠️ **End-to-end migration tests require passwordless sudo** (`tests/test_migrate_agent.py`): ownership cannot be modeled with stubs; it requires two real users and real git. Without sudo, three tests are skipped—but those are precisely the tests that prove a migrated worktree can commit.

## v2.35.2 — 2026-08-04 — #53 orphaned `GET /api/report_bug/status` removed

### Removed
- 🧹 **`GET /api/report_bug/status`** (`app/routes/system.py`) and the `has_reports` and `version` fields in `_bug_snapshot()`—they existed only for this route (`version` was the dashboard banner's `localStorage` version; `has_reports` was computed only to populate it). The snapshot fingerprint's sha256 is gone too; nothing needs to compute it now.
  - **Triggered case:** #53 removed the “New bug reports” banner, which was this route's only caller.
  - Route surface: `tests/route_surface_snapshot.json` lost **exactly one** route, `("/api/report_bug/status", ("GET",))`, and gained none—verified by symmetric difference rather than visual inspection.

### Known tradeoff
- ⚠️ **`GET /api/report_bug` was NOT removed even though no code calls it either.** It is the only reader of the private `~/.local/state/orchestra/bug-inbox/records/` store, where `POST /api/report_bug` writes each report as a separate file outside git. At the time of the change, it held seven live reports from four agents (03.08, 28,371 B), and **none appeared in the repository's `BUGS.md`**, which had not been updated since 01.08. In addition, `POST` returns the literal string `Bug reported: … Read: /api/report_bug` to the agent (`app/mcp_stdio.py:1418`); removing GET would make the platform distribute a 404 link. The store needs a different entry point in a separate task.
- ⚠️ Nobody reads `snapshot["inbox"]` and nobody did before this change. It is someone else's dead code and was left untouched. — 2026-08-04 — #53 “New bug reports” banner removed

### Removed
- 🐛 **The new-bug-report banner and its polling** (`app/templates/dashboard.html`, `app/static/js/app.js`), removed at the user's direct request. This removed `#bug-report-banner`, 106 lines of client code (`_BUG_INBOX_SEEN_KEY`, `_bugSafeText`, `_hideBugReportBanner`, `_showBugReportError`, `_refreshBugReportStatus`, `initBugReportBanner`), the `orchestraBugInboxSeenVersion` localStorage key, and two banner tests.
  - `setInterval(_refreshBugReportStatus, 30000)` disappeared as a side effect: a 99 B response (112 B on the wire), two requests per minute, or **1,200 round trips and ~131 KB during a ten-hour day** for an element that no longer exists.
  - **Server-side behavior is unchanged:** MCP tool `report_bug` needs `POST /api/report_bug`. Neither `GET /api/report_bug` nor `GET /api/report_bug/status` has frontend consumers now; the orchestrator owns the routes' fate, so they were not removed without authorization.
  - Rendering of `mcp__orchestra__report_bug` tool calls in the chat feed remains; that is a different mechanism.

## v2.35.0 — 2026-08-04 — #49 self-hosted chart.js; the page no longer depends on third parties

### Changed
- 📦 **`chart.js` moved from `cdn.jsdelivr.net` to `app/static/css/vendor/chart.umd.min.js` and gained `defer`** (`app/templates/dashboard.html:29`). Version **Chart.js v4.5.1**, license **MIT** (c) 2025 Chart.js Contributors; the file header is preserved unchanged. It occupies 208,522 B on disk and 70,658 B gzip. It is served through `g.asset()`, with a versioned URL (#9) and nginx compression like the other six vendor files.
  - **It was the page's ONLY external dependency** and its only script tag without `defer`/`async`, so it stopped the parser and delayed `DOMContentLoaded`. Yet `Chart` is needed ONLY by the analytics modal (`analytics.js`, `_analyticsRenderChart`), not by first paint.
  - **What `defer` does NOT do:** by specification, deferred scripts execute BEFORE `DOMContentLoaded`, so DCL still waits for the file. The change removes parser blocking and a third party from the critical path. `async`, which would also free DCL, was deliberately rejected: `_analyticsRenderChart` silently returns without `Chart`, so opening the modal within the first few hundred milliseconds would show an unexplained blank area.
  - **No median improvement was measured or claimed.** Three paired runs through the domain produced −204, +77, and +207 ms with ±1.2 s spread; the measurement tool (intercepting `**/*` to replace the template) outweighed the effect. Post-merge measurement belongs to perf, where nginx serves the file and interception is unnecessary. The justification is the distribution tail, not the median (see triggered case).
  - **Triggered case:** perf measured dashboard opening through the domain and caught a run where jsdelivr took **16.8 s**. Everything else moved by the same amount: DCL 17.3 s, agent list 17.6 s, chat 17.9 s. From the VPS, the same CDN usually responds in 50–115 ms, so this was not “the CDN is down” but a tail event on the data center's direct route; the user's route to a foreign CDN is predictably worse. Ordinary measurements miss it because the browser caches the file—it hits first visits and cache misses.
  - The post-`defer` modal was verified by opening it, not by reasoning: `Chart` existed at load time, the canvas measured 1007×250, the chart object was created, and **80,328 pixels were painted**. There were zero jsdelivr requests.
## v2.34.0 — 2026-08-04 — #37 `HEAD /api/models` for heartbeat

### Added
- 🪶 **`HEAD /api/models` returns 200 with the same `X-Orchestra-Build` and an empty body** (`app/routes/system.py`). It uses a separate handler rather than adding `methods=["GET","HEAD"]` to the existing route; a shared route would still compute the complete GET body and let the transport discard it. GET, its keys, and its header are unchanged, preserving the live-client contract.
  - **Triggered case:** `_heartbeatProbe` calls `/api/models` every three seconds for status and the version header, then discards the body. `HEAD` returned 405, so the client had no alternative.
  - The test compares HEAD and GET headers **within one run** and requires an empty body. It verifies “the header is identical,” not merely “the method is allowed”: a green “405 is gone” could hide the silently disabled update banner from #15. Both mutations fail (no route → 405; route without header → mismatch with GET).
  - **Deployment order:** switch the client to HEAD only AFTER restart. Until then the live server returns 405, and the client change would break the version banner.

### Reasoning
- ⚖️ **Wire savings are ≈240 B/s per tab, not 1.5 KB/s** as the ticket estimated. 4,732 B is the uncompressed body; on the production path nginx sends `content-encoding: gzip` and **747 B** (+162 B of headers). This does not invalidate a three-line, strictly better change, but on a 15–80 KB/s link it saves 0.3–1.6% of bandwidth. `docs/tasks/37/report.md` analyzes the body and its two duplication sources (`capabilities`: three distinct blobs in 12 copies, 57% of the array; `backend`: a byte-for-byte copy of `runtime`). The response shape was not changed because that would break the live client before restart.

## v2.33.2 — 2026-08-04 — #34 role icons come from the manifest; frontmatter fallback removed

### Removed
- 🧹 **`role_can_spawn()` was removed** (`app/prompting.py`) along with its six unit tests (`tests/test_manager.py::TestCanSpawn`). The function read `can_spawn` from role YAML frontmatter and always returned `None` (“no restrictions”), but nobody consumed its result: `1bff39a` removed the import from `app/manager.py` together with the fallback itself. Only the manifest decides spawn permissions through `validate_spawn()` (`app/pipeline.py:483`), called at the single `create_session` site (`app/manager.py`) behind the sole agent-creation route, `POST /api/sessions`.
  - Evidence, not code reading: for identical inputs, `role_can_spawn('worker')` returned `None`, while `validate_spawn(default, worker→worker)` raised `ValueError: cannot spawn, allowed (none — terminal)`. The prohibition is observable, so the manifest controls it.
  - **Frontmatter data was not “lost during migration”; it never existed:** `git show 1bff39a^:app/prompts/roles/*.md | grep -c can_spawn` → `0,0,0,0`, and the `pipelines/` files were created without frontmatter from the start (`7ccaadb`). The #25 mechanism shipped with zero configured data and was replaced by the manifest. Without this check, we would have “restored” something that never existed.
  - The `app/manager.py` comment no longer mentions legacy fallback. It does not exist, and `FileNotFoundError` from a missing manifest is not caught (fail loud).

### Fixed
- 👑 **`get_role_icons()` reads `roles.<name>.tg.emoji` from the manifest** (`app/prompting.py`, `pipelines/default/pipeline.yaml`). Previously it scanned `pipelines/default/prompts/roles/*.md` for `icon:` frontmatter—but role bodies begin with `<role>` and contain no frontmatter, so the live server returned `{}` for every `GET /api/role-icons`. Emoji were added for three roles (`orchestrator 👑`, `worker ⚙️`, `full-cycle 🔄`; `sub-orchestrator 🎯` already had one). The deployment order was the reverse of removal—data first, then the source—or icons would disappear entirely between commits.
  - **Triggered case:** MCP `list_agents` rendered the orchestrator as `⚙️`, identical to workers, because the single `_icons.get(r, "⚙️")` default (`app/mcp_stdio.py`) applied to every role. The dashboard happened to look correct: `app/static/js/app.js:2100` maintains its own hard-coded dictionary for six roles and merges an empty response over it. This was observed in a live tool call, not in code.
  - Where the icon went during migration: `scripts/extract-manifest.py:120` maps frontmatter `icon` → `tg.emoji`. `PipelineConfig` parsed the field but NOBODY in `app/` read it; now it has a consumer. Only one role (`sub-orchestrator`) had an icon before migration, so restoring frontmatter would add no information.
  - As a side effect, blocking I/O left the event loop: cached `load_pipeline` replaces four file reads per request (lever C from `docs/tasks/3/research.md`).
  - `app/mcp_stdio.py` and `app/routes/system.py` required no changes: both consumers call the endpoint unchanged and simply began receiving a nonempty response.

### Reasoning
- The option to remove icons entirely and hard-code them in two places was rejected: it would create two source-of-truth dictionaries instead of one source, reproducing the exact drift already seen with `AGENTS.md` and status dictionaries.
- `parse_role_frontmatter()` was NOT removed: skills have real frontmatter, and `_read_skill_index_entry` needs it.

### Known tradeoff
- ⚠️ **The hard-coded dictionary in `app/static/js/app.js:2100` is now a second copy of truth.** Its values match the manifest, so the dashboard looks unchanged, but the frontend owner must remove the copy; this was handed off separately.
- ⚠️ `tg.emoji` now means two things: role icon and TG topic emoji. They were designed as one (`scripts/extract-manifest.py:15`), but if topics need their own icon, the fields must be separated.
- ⚠️ **`validate_spawn` remains fail-open:** an unknown parent or child role may spawn; the whitelist works only for known roles. This is a manifest boundary, not a frontmatter boundary, and removing `role_can_spawn` does not widen it (frontmatter allowed everything unconditionally and was strictly weaker). Tracked as #36.
## v2.33.1 — 2026-08-04 — #21 `/api/sessions` no longer reads the entire logs table

### Fixed
- 🗂 **Partial index `idx_logs_status` on `logs(session_id, ts) WHERE type='status'`** (`app/db.py`). Every `/api/sessions` call invokes `get_last_turn_map()`, which performed `SCAN logs USING INDEX idx_logs_session`. To apply `content LIKE 'turn ended%'`, SQLite read `content` from all 9,685 rows (14.4 MB of text) to retrieve 801 (8%). **16.0 → 0.6 ms**, with an identical 20-row result. Building the index on the live 23 MB database took 35 ms; no separate migration is needed (`IF NOT EXISTS` in the schema).
  - A partial index was chosen instead of `(type, session_id, ts)`: the speed is identical (0.6 ms), while only 8% of rows are indexed; `logs` is the hottest write table.
  - **Triggered case:** task #21 asked us to examine lever C: “`get_role_icons` reads disk on every request; `get_all_sessions` accesses SQLite on the event loop.” Re-measurement under raised limits (`MemoryHigh=8G` instead of the 2G used for earlier profiles) showed that **neither named function needed a fix**: `get_role_icons` had zero profile samples and took 3 ms; `get_all_sessions` took 1.9 ms. An unnamed third function accounted for 55% of the entire wall-clock profile. GIL profiling hid it (`sqlite3` releases the GIL during queries, understating everything that blocks the loop through SQLite); only ordinary wall-clock profiling exposed the number.
  - Measurements and conditions: `docs/tasks/21/report.md`. It also records that under six concurrent clients, a trivial endpoint degrades from 3 ms to p50 185 ms, so the `/api/sessions` handler monopolizes the loop; and why the overnight “dashboard loads slowly” complaint did not belong to the server (between 00:00 and 05:00, neither nginx nor the application received a dashboard request—only scanners).

### Reasoning
- The change deliberately leaves the functions named in the ticket untouched. “This function reads disk/DB on every request” is a cost hypothesis, not measured cost. Under a healthy limit it was false; the adjacent line in the same handler was the real cost.

## v2.33.0 — 2026-08-03 — #28 reindex returns control immediately

### Changed
- ⏳ **`POST /api/memory/reindex` queues indexing and responds immediately** (`app/routes/memory.py`, `app/rag_service.py`). Before: the route waited for `await backfill_scope(...)` to finish while the request field was named “fast per-agent reindex.” After: `schedule_backfill(scope, session_name)` → `{"ok", "status": accepted|coalesced, "index"}`, with progress visible in journald and `index_status`.
  - **Breaking:** the response no longer contains `{files, logs}` because they do not exist yet when it returns. The endpoint has no code or frontend consumers (searched across `app/`, `scripts/`, `tests/`, `pipelines/`); humans call it directly.
  - **Triggered case:** `perf` called it to measure a session with ~500 logs and timed out after 6.5 minutes. This path cannot be made fast in principle: embedding one log takes 1.3–2.9 seconds, so “fast” and “synchronous” are incompatible here; the label itself was false.
  - Session reindex now uses the same `_LOG_SLICE` chunks as the global run instead of one unbounded query. The scheduler key is composite (`scope::session`) so an explicitly requested reindex is not coalesced into a background scan of the entire scope.

## v2.32.0 — 2026-08-03 — #19 chart loads one period, not all history

### Changed
- 🪟 **The frontend requests `hours=168`—exactly one anchor window; earlier windows arrive when ◀ is clicked** (`app/routes/system.py`, `app/db.py`, `app/static/js/usage.js`). The route accepts `until` (exclusive right boundary) and returns `oldest_ts`, the timestamp of the first snapshot ever. It keeps ◀ active after loaded periods are exhausted and now drives the “Snapshots since …” label. Previously the label used the first LOADED snapshot, which would become false with lazy loading. Chunks merge into `_sparkData` and live until the tooltip closes.
  - Initial load: **860,039 B → 414,667 B** (760 points instead of 1,629), gzip through nginx ≈57 → ≈26 KB. One ◀ click: 152,497 B / ≈11 KB. More important than the numbers, the initial response **no longer grows**: the seven-day window is fixed regardless of accumulated history. It previously grew by 29 KB/day.
  - **Cache rather than refetch**—a data-driven decision: an ≈11 KB gzip chunk over a 15–80 KB/s link with TTFB 0.53–4.22 s costs 0.7–5 s, and merging is cheaper in code too (refetching would require discarding chunks on ▶). Browser verification: ◀ ◀ ▶ produced two requests; forward navigation came from memory.
  - **The navigation window follows data, not the calendar** (`usage_history_ts_before`): after a gap longer than a week, a calendar-based chunk would be empty and ◀ would remain stuck forever.
  - Verified that “frequent clicks through 5h windows” are impossible: navigation is anchored to the provider's longest window (`anchorSeries`), and no window exceeds seven days, so each click always moves one week.
  - This also measured what #13 had only calculated: nginx does compress this response (`content-encoding: gzip` on the production path), but **1.130×** less efficiently than Python's `gzip.compress(level=6)`. The “50.9 KB” claimed in #13 becomes ≈57.5 KB on the live path.

### Fixed
- 🎨 **Provider series order no longer depends on which chunk loaded first** (`app/static/js/usage.js`). Series are sorted by `window_minutes`; previously the first data row encountered set both order and palette color.
  - **Triggered case:** clicking ◀ to the “2w ago” frame swapped the 5h and 7d lines and colors because the older loaded chunk did not yet contain the 5h window. This never appeared before lazy loading because the complete history kept order stable. A visual run found it; neither tests nor code reading did.

### Known tradeoff
- ⚠️ **The first ◀ click always costs a request.** Deep navigation is linear: N periods back = N requests of ≈11 KB. Preloading the second period would surrender half the saved volume for an action that most tooltip openings never take.
- ⚠️ `_SPARK_VIEW_HOURS = 168` is hard-coded in the client. If a provider gains a window longer than a week, the initial chunk will be shorter than the period and the chart will appear truncated until the first ◀ click.

## v2.31.0 — 2026-08-03 — #13 usage history: range-based resolution and honest gaps

### Changed
- 📉 **`/api/usage/history` selects its own resolution and returns `{step_minutes, rows}`** (`app/routes/system.py`, `app/static/js/usage.js`). Database-layer thinning through `usage_get_history(hours, step_minutes)` existed from the start, but the route never exposed it. Now `hours ≤ HISTORY_FINE_HOURS` (48) returns the full five-minute grid; longer ranges use `HISTORY_COARSE_STEP` of 30 minutes plus a full-resolution 48-hour tail. One year over HTTP: **4.25 MB / 0.93 s → 857 KB / 0.33 s**, 8,479 → 1,628 points, gzip -6 (nginx compresses `application/json`) 203 → 51 KB.
  - **Breaking:** the response is no longer a bare array. The client needs grid spacing to distinguish missing data from sparse sampling; a second copy of the spacing ladder in `usage.js` would drift from the server (as already happened with `AGENTS.md` and status dictionaries). The endpoint has no other consumers. `_loadSparkline` reads `history.rows` and `_sparkStepMin`; tests were updated.
  - **Why 30 minutes rather than guesswork:** the SVG is fixed (`usage.js`, `W = 280, PL = 28`) at 252 px, and the chart draws one period rather than the entire range. The provider's longest window anchors the period, and none exceeds seven days (`anthropic five_hour 300`/`seven_day 10080`, `codex primary 10080`, `codex_spark primary 10080`). Seven days over 252 px = 40 minutes/pixel; a five-minute grid produced eight points per pixel.
  - **The 48-hour tail is not cosmetic:** the current period starts at the latest reset, so during the first hours after a weekly reset, a 30-minute grid would leave only 2–4 points. The decision to stop is made from the current 5h window.
  - Shape-degradation check across 252 pixel columns over the latest seven days: in the tail, the 5h line differs by ≥1 px in exactly **1 of 71 columns**, while the 7d line differs in 0. Before the 48-hour tail, 5h differs in 42 of 179 columns (16 are reset edges where a 30-minute horizontal shift equals 0.75 px), and 7d differs in 2. Screenshot of both grids over identical data: `docs/tasks/13/before-after.png`.

### Fixed
- 🕳 **Forward-fill no longer draws a flat line across snapshot gaps** (`app/db.py::usage_get_history`, `app/static/js/usage.js`). The grid extended the last known value indefinitely. Now no point is emitted if the latest snapshot is older than `stale_limit = step * 2`; on the client, a point marked `p.gap` (neighbors more than `1.5 × _sparkStepMin` apart) starts a new polyline segment. Both usage and the dotted ideal-pace line break.
  - Live database measurement (6,583 snapshots, 29 days): **45 gaps longer than 30 minutes; the longest was 9h 11m**. The inverse risk was checked on the same data: only four 10–12 minute intervals (exactly one missing snapshot, where a break would be excessive) occurred in a month. The collector either works or stays down for a long time.
  - Both new tests were mutation-checked: `stale_limit = step * 100000` fails `tests/test_usage_history_resolution.py`; removing `p.gap` fails the line-break test in `tests/test_usage_history_frontend.py`.
  - **Triggered case:** the chart did not render at all because the one-year response weighed 4.29 MB and exceeded `api()` timeout. Volume analysis revealed that during nights with no snapshots, the curve still displayed the old 97%, even though the 5h window had reset and filled again. “Time to stop” decisions were based on this picture.

### Known tradeoff
- ⚠️ **A provider-specific outage shorter than 45 minutes is still connected by a line.** The client derives the break threshold from declared `step_minutes`, while the response mixes two intervals: the 48-hour tail actually uses five minutes but declares 30. Service outages last hours, so this does not affect them. But a provider unavailable for half an hour (`status: unavailable`, empty windows, hence no series points) appears continuous. Knowing this is cheaper than re-measuring: `docs/tasks/13/report.md`.
- ⚠️ **Volume growth is slower, not stopped:** ~149 KB/day before, ~30 KB/day now; today's 4.25 MB returns in 114 days (the arithmetic in the first version of this entry was wrong by 8×). The cause is structural: the frontend loads all history while drawing one period, and the year is needed only for ◀ navigation. Addressed in #19.

## v2.33.0 — 2026-08-03 — #134/#133/#132 retrieval quality ceiling: three consecutive “do not build” decisions

This section consists entirely of **negative results**. Not one line of production code changed,
and that is the substance of the release: three consecutive tasks ended with “option rejected,”
each for a different reason. The measured evaluation below preserves those reasons so they need
not be repeated.

### Rejected
- 🚫 **A reranker on top of hybrid search was measured, works, and was rejected by the user because it costs money**
  (`docs/tasks/134/research.md`, measurements in `docs/tasks/134/bench/`, visual analysis in
  `docs/tasks/134/134-reranker.html`). `hybrid + cohere/rerank-v3.5` through OpenRouter yields
  **MRR 0.7321 versus production's 0.4893** at `t = +3.46` (threshold 2.052; 28 queries against
  a live corpus of 68k chunks), with 13 improvements and one regression. The measurement cost $0.040.
  - **The main finding is not the reranker but the ceiling: 86% top-three recall is the limit of
    retrieval itself on our corpus.** Remaining misses require better index content, not ranking.
  - **A local reranker was rejected for TWO independent reasons, either sufficient:** the gain is
    insignificant (`t = +2.01 < 2.052`), AND CPU inference takes 17–28 seconds per query versus
    1.6 seconds for the API. The premise that “we cannot run it locally” is technically false—the
    model runs—but it does not solve the task.
  - **The existing production hybrid of vec+FTS5+RRF is justified:** 0.4893 versus 0.4012 for pure
    vector search and 0.3458 for pure FTS5 (the latter is significantly worse, `t = −2.54`).
  - **The unresolved deployment issue is latency, not money:** +1.6 seconds on EVERY agent turn.
  - ⚠️ OpenRouter's `POST /api/v1/rerank` **exists but is absent from the `/models` catalog**—the
    same trap as embeddings in #133. Exactly one model is live; 16 other ids return 400.
    **Do not trust the catalog; verify with a request.**
  - **Triggered case:** the post-#133 hypothesis that we had hit the embedder ceiling. A reranker acts
    on another link (ordering, not representation), which is why it delivered what no model swap did.

- 🚫 **Migration to API embedders: superiority was not demonstrated, so local bge-m3-int8 remains**
  (`docs/tasks/133/research.md`). One script tested seven models in one pass against 14 triplets
  from **our** production corpus (`data/vec.db`: 28,723 log_chunks + 39,447 file_chunks).
  - Three candidates “beat” local, but `|t| < 2` and the confidence interval includes zero.
    **Only two LOSSES are significant:** gemini and ada-002. Paying money, adding a network
    dependency, and accepting ~100× latency for a gain indistinguishable from zero is a bad trade.
  - As a side finding, the current production configuration (CLS pooling, no prefixes) is the best
    of eight tested pooling × normalization × prefix combinations.
  - ⚠️ **The old RAG document's numbers are not reproducible and were archived:** the model and
    pipeline did not differ; the triplets themselves did. The document was rewritten AFTER the
    measurement and retained wording that could not produce its numbers. Diagnosis: a broken model
    would move all five triplets together, but only 2/5 moved.
  - **Triggered case:** suspicion that the local model was worse than paid alternatives. It was not.

- 🚫 **No shared embedder service for Orchestra and the Kesha bot** (`docs/tasks/132/research.md`;
  `plan.md` was never executed). Measurement CONFIRMED duplication and disproved the orchestrator's
  original hypothesis that “the model does not load on the VPS”: two processes hold
  `AlpEge/bge-m3-onnx-int8` simultaneously (bot: 1.20 GiB RSS, including 1,206,268 kB anonymous;
  Orchestra on VPS: 881 MB), with two hash-identical 561 MB copies on disk.
  - **Why the “model is absent” check returned a false negative—three independent reasons, each
    sufficient:** (1) the bot model lives in `/tmp/fastembed_cache`, not the HF cache, so `find`
    under `~/.cache/huggingface` misses it; (2) the bot lacks `RAG_ENABLED` not because RAG is off,
    but because **the flag does not exist in its code**—`bot.py:196` calls backfill unconditionally;
    (3) the second process is not our local Orchestra but a **separate Orchestra instance on the VPS**.
  - **ONNX Runtime reads weights into the heap:** searching `/proc/<pid>/maps` shows only runtime
    `.so` files and creates the false impression that the model is absent. Inspect anonymous RSS
    (`/proc/<pid>/smaps_rollup`) and the loading log instead.
  - **Triggered case:** a four-core / 8 GB VPS at load 31.7 with full swap; we were identifying the memory consumer.

## v2.32.0 — 2026-08-03 — #8 dashboard switches agents without the network

### Added
- ⚡ **IndexedDB log mirror—chat history no longer travels over the network** (`app/db.py`,
  `app/routes/sessions.py`, `app/static/js/app.js`, +180/−95). The browser keeps a local copy of
  the `logs` table, synchronizes every project in one request (`GET /api/logs/sync`: a cold slice
  of the latest N rows per session plus watermark-based increments, capped by BYTES), and renders
  chat locally. The SSE stream opens directly at the tail; its first event (`__session`) names the
  session authorized by the server.

  | | Before | After |
  |---|---|---|
  | network waits before content (cache hit) | 3 sequential round trips | **0** |
  | history requests per switch | 1 (uncompressed SSE) | **0** |
  | history on cache miss | ~90 KB uncompressed over SSE | **17.6 KB gzip** (4.0×) |
  | browser switch | 826 ms | **39–121 ms** |

  - **The #2 DOM cache was removed** and replaced by the mirror in the same change; otherwise the
    switching logic would exist twice.
  - Any row with a foreign `session_id` clears and reloads chat, leaving no way to mix in another
    session's history.
  - A truncated row never enters chat: **if the mirror contains even one truncated row, the complete
    history is fetched from the server** (three lines of code instead of a “load” button). The approach
    changed because 5/6 truncated rows were `tool_result`, which has **no DOM node of its own** and merges
    into the preceding tool row. With production `tail=20` / `cap=16 KB`, none of 419 rows in the live
    database is truncated.
  - Tests: `tests/test_logs_sync.py` (16), plus three browser runs of `docs/tasks/8/verify-*.py`
    (19/19, 12/12, 6/6). Numbers were measured in headless Chromium **on the server**, not on the user's machine.
  - **Requires an Orchestra restart.** Until then `/api/logs/sync` returns 404, `__session` does not arrive,
    and the dashboard behaves as before while noting it in the console.
  - **Known tradeoff:** history is stored as plaintext in the browser profile, a deliberate trade on a
    personal machine. The mirror depends on **`logs` immutability**; the first `UPDATE logs` would make it
    silently lie. A comment on `add_log` records the invariant; there is no test for it.
  - **Triggered case:** measurement #2 found agent switching took 826 ms, including 172–446 ms merely to render
    100 messages (`marked.parse` + `DOMPurify` + `hljs`), while the network delivered the batch in ~15 ms.

### Fixed
- 🔁 **Background polling no longer opens a second stream containing complete history** (`app.js`, `_chatLoading`).
  `refreshSessions` contains `if (!eventSource) connectSSE()`. While `_showChatFor` waited for IndexedDB,
  `eventSource` was null, so the three-second poll could open a stream with `after_id=0`; the server then sent
  the entire history over a second, uncompressed stream. A flag and `finally` prevent the recovery `connectSSE`
  from being blocked forever.
  - **Triggered case:** it did **not fail on every run**—12/12 passed, then three failed on the next run.

### Removed
- ♻️ **The #2 chat DOM cache lived for one day and was removed** (`bcb86b6` → replaced in #8). A `Map`
  of detached `DocumentFragment` objects (eight-agent LRU) reduced switching from 826 ms to 30 ms with zero
  messages redrawn, so it **worked**. It was removed not because it was bad, but because the IndexedDB mirror
  solves the same problem together with network and history; two switching implementations cannot coexist.
  - The lasting lessons from #2: **cache the rendered DOM, not the network response**—reparsing JSON is cheap,
    rendering is expensive—and retain **the complete invalidation list** (session recreated under the same name,
    scope change, compact/normal, navigation away mid-stream, unconfirmed own message). It applies to any client-side
    chat cache. Analysis: `docs/tasks/2/report.md`.
  - **Time-consuming trap:** live :8888 serves static files from the MAIN checkout, not the worker's worktree.
    JavaScript changes on a worker branch are invisible in the live frontend, with no error—the “fix simply does
    not work.” Test the frontend through `page.route('**/static/js/app.js', …)`.

## v2.31.0 — 2026-08-03 — #1/#4/#5/#6/#7/#10/#14 dashboard stops lying and losing input

A batch of seven parallel tasks with one shared trait: **the system knew the truth but remained silent
or displayed an invention**. Every change makes unknown state look unknown.

### Added
- 🔑 **`OWNER_MODE` decouples “our data in the dashboard” from “require login”** (`app/auth.py`,
  `is_owner_mode()`; `app/routes/proxy.py`, `app/routes/system.py`, `app/static/js/app.js`,
  `.env.example`). The usage bar, proxy panel, and Claude profiles are shown to the owner.
  - Default = old behavior: **without login, the machine is considered ours** (development laptop);
    **with login, it is considered a client's**. `OWNER_MODE=1` overrides both.
  - Tests: `tests/test_owner_mode.py` (+103).
  - **Triggered case:** login is enabled on our VPS because it has a public address, but the data are ours;
    the old logic hid the owner's own quotas.
- 💵 **`SUBSCRIPTION_COST` is the real subscription price as a free-form `.env` string** (`app/routes/system.py`,
  `app/static/js/usage.js`). It is free-form because a plan is not necessarily one number (`$200+$20/month`).
  **Unset → no row at all.**
  - **Triggered case:** the panel contained hard-coded `₽100+₽100/month`, the only REAL number among
    API-equivalent estimates, and it had already become wrong. An invented value among calculated values is
    indistinguishable from a real one, so blank is better.

### Fixed
- 📉 **Quota snapshots no longer lie when a provider is silent** (#4, `app/routes/system.py`).
  Before: `snapshot_codex = codex_data or _codex_usage_cache.get("data")` gave a silent provider's snapshot
  **the last known value with a new timestamp**, drawing a flat line where no data existed. After: three
  distinct states—key absent (not configured) / `{"windows": [], "status": "unavailable", "error": "..."}`
  (asked, no answer) / numbers (answered).
  - **Answer to the user's question, “where did July's Codex history go?”: it was never written and cannot
    be recovered.** Measurement on a read-only copy of the live database: from 05.07–02.08, 6,400 rows had
    empty `provider_usage` in **100%** of cases; from `2026-08-03T06:29:27Z` onward it is populated in 100%,
    and at `07:02:20Z` the `codex` key appears. Two sharp boundaries, not degradation. The hypothesis that
    “migration broke it” was **inverted**: migration did not stop recording; it started it. Every store was
    checked (`usage_snapshots`, `turn_usage`, `usage_cache.json`, journald); the data are nowhere, and the
    provider API does not expose history.
  - “Limit reached” ≠ “no data”: `utilization: 100` is a provider response, not silence.
  - **Known remainder:** `_renderSparklines` draws one `polyline` through every point, so a one-day gap still
    becomes a straight line. The data contain `status=unavailable`, but it does not break the line.
- 🖼 **Pasting an image no longer erases typed text** (#5, `app/static/js/app.js`).
  Before: `input.value = oldText + '\n' + data.path` after `fetch` returned overwrote everything typed during
  upload. After: the field is only **appended to**, and caret position is restored (`setSelectionRange`).
  - **Send waits for the image:** `sendChat` awaits any unfinished upload (`_trackUpload`, 60-second timeout),
    the button shows `⏳`, and the field remains editable. Previously the message was sent without the image,
    then its path was appended to the already-cleared field as an orphaned line for the next message.
  - **Upload failure is no longer silent:** the old `catch { input.value = oldText; }` restored stale text;
    a JSON response without `path` did not even enter catch, leaving `⏳ uploading image...` forever. All four
    branches were tested (nginx 413 with HTML body, application 400 with JSON, disconnect, 200 without `path`).
    The exception class is printed deliberately: `TimeoutError` and some network errors have an empty `message`.
  - **WebP q=0.9 instead of PNG for clipboard paste:** 683 KB → 354 KB (1.9×, PSNR 38.6 dB), reducing 8.3–12.9 s
    to 4.3–6.7 s on the user's 53–82 KB/s link. Two unexpected measurements: the browser PNG encoder **inflates**
    the file (667 → 898 KB), and lossless WebP in Chromium exceeds the source PNG. Guardrails: clipboard paste
    only; files under 100 KB remain unchanged; WebP no smaller than the original → send original; any encoding
    error → original.
  - **Known tradeoff:** the format is now `.webp`. Claude agents read it natively; other runtimes were not tested.
    The remedy is a one-line change from `image/webp` to `image/jpeg` in `_compressScreenshot`.
  - **Triggered case:** the user's complaint that “images take fucking forever to upload; can I keep typing while
    they do?” revealed two problems. The unreported one—lost text—was more severe: input was not blocked, it was
    overwritten, losing 15–30 seconds of typing.
- 🚧 **A false reboot overlay no longer blocks the dashboard** (#6, `app/static/js/app.js`,
  `_onFetchFail`, `_dismissRebootOverlay`). A request timeout means the server is **slow**, not dead:
  under disk load, `/api/models` can take over two seconds while the service remains fully operational.
  `TimeoutError`/`AbortError` no longer count as a crash. A genuinely dead server still raises the overlay
  (`TypeError` on connection refusal or 502+ through the proxy).
  - Added a “Close and continue working” button and an exit from `_pollReconnect`. If the overlay still appears
    incorrectly, it is no longer an inescapable trap (the `while (true)` loop reloaded the page even after closing).
- 🩺 **Git errors are no longer disguised as “branch missing”** (#7, `app/workspace.py`, `_inspect_branch_ref`).
  Git exits 128 both when a directory is not a repository and when it **refuses to work with it** (dubious ownership,
  unreadable `.git`). Asserting the first hid the second and sent callers looking for branches that existed. Every
  `show-ref --verify` in `resolve_base_branch` and `merge_worktree_to_main` now uses one helper: git failure → git's
  error text, not an invented diagnosis.
  - `scripts/migrate_agent.py` no longer swallows `sqlite3` errors, gained a binary preflight and automatic dubious-
    ownership fix, and no longer places migrated files outside the service user's ownership.
- 📊 **The usage panel no longer hides failure behind a placeholder** (#10, `app/static/js/usage.js`). `Collecting data...`
  appeared both before collection started and after a request failed, although these are different states.
  It now shows gray “No snapshots yet” versus yellow “History failed to load — `<class>: <text>`.”
  - The one-year history request has its own 30-second timeout (`AbortSignal.timeout`). The general `api()` timeout
    of five seconds was designed for small responses and fired **before the response arrived**, while an empty `catch`
    hid the failure. Measurement on 03.08: 8,403 rows, 4.29 MB.
  - Tests: `tests/test_usage_history_frontend.py` (+112).
- ⚙️ **Background jobs work on kernel 6.8** (#14, `app/pidfd_exec.py`). `PIDFD_SIGNAL_PROCESS_GROUP` exists only
  since Linux 6.9; older kernels reject the flag with `EINVAL`, killing **every** background job on such hosts.
  Added a pidfd-bound `_send_group_via_killpg` fallback: until the leader is reaped, its pid cannot be reused, so pgid
  still names OUR group. If `pidfd_pid()` returns 0, the group is considered gone rather than signaling a stranger.
  Capability is **probed through the syscall**, not inferred from the version (`group_signal_supported()`).
- 🧪 **Tests no longer depend on whose machine runs them** (#14, `tests/conftest.py`, `_hermetic_dashboard_env`
  autouse fixture). Two leak sources must both be stopped: the systemd unit supplies `EnvironmentFile=.env`, so
  `DASHBOARD_USER` already exists in `os.environ` even in a clean clone without `.env`; and `lifespan` calls
  `load_dotenv()`, restoring it after any prior cleanup. With auth enabled, every `/api/` request returned 401:
  **green on CI, red for the owner**. A test dependent on someone else's environment is worse than red—it cannot reproduce.
- 🎭 **CI installs the browser** (`.github/workflows/ci.yml`). `uv sync` installs the Playwright package but not browser
  binaries. Without `playwright install --with-deps chromium`, every browser test **silently skipped**, leaving CI green
  while proving nothing about the frontend.

### Changed
- 🗄 **Agent logs are never deleted** (`app/db.py`, `app/manager.py`). The retention timer is gone, and
  `cleanup_old_logs` now **fails when called** instead of silently cleaning—fail loudly rather than lose data
  irreversibly. The same append-only log property is the foundation of the #8 mirror.
- ⏳ **When status is RUNNING, `merge_worker` explains why and waits for the outcome** (`app/mcp_stdio.py`)
  instead of blindly retrying.
- 📌 **`uv.lock`: removed `exclude-newer`.** Local uv 0.11.28 deletes these lines on every run, so they
  generated diff noise without pinning anything.

## v2.30.2 — 2026-08-03 — rules and prompts: foreign machine, rollbacks, environment migration

No code changes, but every agent in every project reads this, so it belongs here.

### Changed
- 🧹 **The “Traps” section of `CLAUDE.md` was rewritten for meaning** (`docs/tasks/claude-md-cleanup/`):
  60 items in four groups → 56 in eight, ordered by frequency of use (evidence checks first, hardware last).
  The file deliberately **grew** by 1,174 bytes: three rules returned and wording that had been shortened past
  the point of meaning was expanded.
  - **Triggered case:** “Codex truncates `AGENTS.md` at 32 KiB” was correct as a DEFAULT but false for the active
    configuration (98,304 locally, 65,536 on VPS). Half a day was spent cutting live rules for a nonexistent limit.
    General rule: **before relying on a documentation claim, verify it against config with one command.**
  - Before each deletion, the mechanism was searched in code. Removed text remains verbatim in
    `docs/archive/sessions/2026-08.md` rather than being erased. The `.gitignore:9-10` workaround is LIVE, so the
    `!docs/workers/` rule was restored.
  - ⚠️ No external review (Codex quota unavailable until 08.08): the only change to a file shared by every agent
    that received no second opinion.
- 🧯 **Prompts: do not put large files in `/tmp`** (`pipelines/default/prompts/modules/research-method.md`,
  `roles/full-cycle.md`). “Run in /tmp” became “run in scratch scripts” plus an explicit `findmnt /tmp` check.
  - **Triggered case:** on the laptop `/tmp` is **tmpfs, i.e. RAM**. A worker placed 1.6 GB of “disk files” there,
    taking memory from agents competing for it at the same time. `CLAUDE.md` contained the right rule while the role
    prompt said the opposite—and **the worker follows the prompt**.
- 📦 **Rules from #129** (`CLAUDE.md`, `docs/archive/sessions/2026-08.md`): group B moved to the archive; new rules
  cover two-pass documentation of a period and validation of rollback SHAs (`--is-ancestor` proves reachability,
  not revertibility; run `git revert --no-commit` in a scratch checkout).

### Added
- 🚚 **Instructions for transferring the environment to the VPS** (`docs/HANDOFF-from-laptop.md`, `docs/tasks/131/`).
  The production environment is running at `https://orchestra.seedon.ru`: 4 GB swap with `swappiness=10`, memory
  priorities (`oom_score_adj` 800 for Orchestra, −900 for tinyproxy), updated code, and a migrated database schema
  (`turn_usage`, `tool_errors`, `merge_operations`, `improvement_rules`, `voice_costs`—all five created). The local
  environment was untouched (85 laptop sessions).
  - **`OOMScoreAdjust` applies only on restart, while memory limits apply live:** systemd changes the cgroup without
    restarting. Verify `/proc/<pid>/oom_score_adj`, not `systemctl show`, which always prints the configured value.
  - **`uv sync` without `--extra rag` silently removes RAG** while leaving `RAG_ENABLED=true` in `.env`, making the
    configuration contradict itself. Every deployment must use `uv sync --extra rag`.
  - **Found but unfixed defect:** bootstrap ignores `WORKSPACE_DIR` and tries the default `/workspace/project`
    (`Bootstrap: cannot create workspace ... exit status 1`). It does not affect operation; the service starts.
    The warning also appeared in the pre-update July journal.
  - **Triggered case:** `git stash`/`fetch` failed under the service user with
    `insufficient permission for adding an object to repository database .git/objects`. Half the directory belonged to root (295 `.git` files, 3,021 tree
    files) while the unit had `User=kesha`. Foreign owners do not prevent reading or startup; only WRITING `.git`
    fails, midway through deployment.

### Known issue
- ⚠️ **Do not replace the system-prompt preset with `type: "custom"`** (`docs/tasks/125/research.md`).
  The preset was inspected and is not a black box, but it carries live harness behavior (tool guidance, destructive-
  action safety, `file_path:line_number`) that we would not reproduce and would silently lose on replacement.
  `exclude_dynamic_sections` provides a cheap targeted gain instead.
  - A side finding from the same research was the post-compaction role bug fixed in v2.30.0 (#126).
  - Measured injection-turn cost: `input_tokens ≈ 271,722` versus `34` for an ordinary turn (n=30 versus n=1,359).
    The system slot is cached; the user slot arrives as fresh text.

## v2.30.1 — 2026-08-03 — #12 spawn no longer dirties the worker tree

### Fixed
- 🧹 **The platform never overwrites files tracked by the repository** (`app/workspace.py`, `app/prompting.py`).
  New `workspace.tracked_paths(worktree, rels)` is the only way to ask whether a path is in the index; if git cannot
  answer, it raises `RuntimeError` rather than guessing. `create_worktree` skips tracked `copies`,
  `inject_skills_to_worktree` skips tracked `.claude/skills/<n>/SKILL.md`, and `sync_agents_md` uses the same helper.
  `_exclude_claude_dir` became `_exclude_worktree_artifacts(wt, extra)`: copies actually created and symlink targets
  (`.env` and others) now add themselves to `info/exclude` as anchored `/<path>` entries, removing per-repository manual edits.
  - **`info/exclude` cannot protect tracked files:** ignore rules do not apply to the index. The `AGENTS.md` mirror had
    a safeguard while skill injection did not, so the symptom existed only where skills were indexed: seedon had 14
    `.claude/skills/*` files; Orchestra, dnd-game-master, and kesha-tg-bot had zero.
  - Behavior change: in a repository that versions its own skills, the agent reads the **repository version** (Claude
    CLI already loads native skills from this path, and `_project_skill_files` already treated them as truth for Codex).
    Parent fallback for `CLAUDE.md` applies only to untracked files.
  - Tests: `tests/test_workspace.py` (+3), `tests/test_manager.py` (+1). All four were mutation-checked and fail with
    the fix stashed. Analysis and decision cost: `docs/tasks/12/report.md`; no cross-LLM verdict due to subscription
    limits: `docs/tasks/12/codex-review.md`.
  - **Triggered case:** six consecutive seedon branches failed to merge. `merge_worker` returned
    `worker working tree is dirty (.claude/skills/codex-debate/SKILL.md, .env)` although the workers never touched
    those files; the orchestrator manually repaired `info/exclude` in each project.

## v2.30.0 — 2026-08-03 — #126 role survives context compaction

### Fixed
- 🧠 **The role returns to the prompt after compaction** (`app/session.py`, `compact()`). The successful compaction
  path now sets one flag, `self._prompt_injected = False`, adding seven production lines.
  - **The failure point is not “after compaction” but the first reconnect after compaction.** The wording matters
    for search: immediately after compaction the agent is still alive and remembers its role. The failure happens
    later: successful `compact()` moves the session to a new native `session_id`; the next startup is a **resume**,
    and resume receives no `system_prompt` (`backend_claude.py:165-168`). An hour may separate these events.
  - The flag resets ONLY on the successful branch. Failure branches (`compact()` retry, acknowledgment timeout,
    quota) restore the **previous** session whose prompt remains live. Resetting there would cost an extra ~270k
    input tokens on every failed compaction.
  - Tests: `tests/test_session.py` `TestCompactReArmsPromptInjection`, three cases (+160). The third is end to end:
    it verifies that the first turn on the resumed backend actually contains the role text after compaction, not
    merely that “the flag changed.”
  - **Triggered case:** after compaction, a worker stopped behaving like a worker—it lost pipeline phases and role
    rules. Diagnosis came from `~/.claude/projects/**/*.jsonl` (`compact_boundary` records plus the
    `PREVIOUS CONTEXT SUMMARY` preamble), with zero paid calls.

### Known issue
- ⚠️ **Native compaction with a custom prompt is unreachable** (`docs/tasks/125/research.md`, `docs/tasks/126/research.md`).
  We tested delegating compaction to the Claude runtime while supplying our own `COMPACT_PROMPT`, but the API exposes
  no such seam. This also disproved the argument that “at least the warm cache survives”: `cache_read=0.889` was measured
  on the **injection turn of the current path** (appending at the tail preserves the prefix), not on the proposed operation
  of sending `system_prompt` on every resume, which risks invalidating the entire prefix. The number measured what would
  be replaced, not what was proposed.

## v2.29.0 — 2026-08-02 — #106 new compaction prompt

### Changed
- 🗜 **`COMPACT_PROMPT` was replaced by the `hot_state_ledger` bundle** (`app/session.py`, around line 1184).
  Seven old sections (INTENT/DECISIONS/FILES/PENDING/RECENT/BUGS/IMPORTANT CONTEXT) became four typed sections
  (TASK STATE / DECISIONS / BLOCKER-NEXT / CONSTRAINTS), plus rules to never claim an action without evidence and
  never assert a negative (`no evidence of X`, not `X did not happen`). Codex sessions are unaffected; they use
  `_compact_codex_context()`.
  - Selection used four evaluation rounds with preregistered gates and judging, `docs/tasks/106/q6/`; 7/8 gates PASS.
  - **Rollback: `docs/tasks/106/rollback.md`:** `git revert --no-edit f796a08` plus restart. The prompt is reread on
    every `compact()`; no migration or data depend on it. The file contains a per-property “what regression looks like” table.
  - ⚠️ `rollback.md` itself names SHA `8b5392d`, a **pre-squash worker commit unreachable from `main`**;
    `git revert 8b5392d` will not work there. The actual squash commit on `main` is `f796a08`.
- 🗑 **Removed `_ORCH_PRESAVE`**, the block that ordered the orchestrator to update `CLAUDE.md`, `TODO.md`, and `BUGS.md`
  before EVERY compaction. This is an intentional behavior change, not a side effect: **orchestrators no longer auto-save
  notes during compaction**. Durable facts are now written explicitly as a session proceeds.

### Known tradeoff
- ⚠️ **The headline number is not confirmed in production.** The recent-recall gain (**+75.66 pp**) came from a
  harness where `run_evaluation.py` called postprocessor `compose_handoff()`, which mechanically appended the latest
  three user messages, tool ledger, and file diff AFTER model output. **The appender produced 100% recall, not the prompt.**
  Production has NO such postprocessor: `compact()` concatenates only the model's own text.
  - Therefore the candidate phrase “the runtime will append the tail and ledger” did not ship; it promised a block that
    would never arrive. It was replaced with “preserve the latest three user messages verbatim.” The model is instructed
    to do what the harness guaranteed structurally. Every other rule shipped byte for byte.
  - **Confirmed in production** (these rules shipped unchanged): unrelated file writes **218 → 0** across 63 measured
    outputs, false claims about file actions **8 → 0**, handoff size **−61.4%** (median ~2.0 KB, 38.6% of the old size).
  - **Not confirmed in production:** recent-recall gates G1 and the recent half of G8. An honest closure would port
    `compose_handoff()` into `compact()`; that exceeded the approved scope and **was not done**.
- ⚠️ Of six changed prompt rules, five are tied to a measured number. The sixth (`UNKNOWN — source gap`) shipped inside
  the bundle and was not isolated separately, so its specific contribution is unknown. This is recorded explicitly to
  avoid inventing a neat causal story (`docs/artifacts/compact-prompt-q6-106.html`).

## v2.28.0 — 2026-08-01 — #93/#111/#114 lifecycle, Codex hibernation, bug inbox

### Added
- 💤 **Codex worker hibernation** (`app/backend_codex.py`, `app/session_hibernate.py`, `app/runtime_registry.py`, #111).
  After normal idle time (300 seconds for a worker, 600 for an orchestrator), a Codex worker releases its complete
  app-server + MCP process scope and returns to **the same native Codex thread** on the next message. Manual route:
  `POST /api/sessions/{name}/hibernate`.
  - Processes start in a unique transient user scope. Before enabling hibernation, the system verifies `Linger=yes`,
    actual user-scope attachment, ownership of the unified cgroup, and readability of `cgroup.events` from inside a
    disposable scope. Failed verification → direct launch with `hibernate_safe=False` in the log.
  - Backend ownership is retained until successful teardown. A substituted thread id is rejected BEFORE sending a turn.
    Running/waiting/pending/compacting states return conflict rather than disconnecting.
  - Current capability matrix: `claude` and `codex` have `hibernate=True`; `grok` and `opencode` have `False`
    (`app/runtime_registry.py`).
- 🐞 **Bug-report inbox outside the working tree** (`app/routes/system.py` `_bug_state_root`/`_publish_bug_record`,
  `deploy/orchestra.service.template`, #114). Records are published to a private `bug-inbox/` (`0700`) inside the
  service state directory (`$STATE_DIRECTORY`), not checkout `BUGS.md`. One report = one immutable file in `records/`
  (`0600`); publication is an atomic rename after `fsync`, and readers ignore temporary files.
  - The entire candidate path is validated: `lstat` on every component; reject worktrees, `.git`, bare repositories,
    and symlinks inside them; recheck with `git rev-parse` in an environment without inherited `GIT_*`. An unsafe path
    is a service error, NOT a reason to write into the checkout. Blocking writes run in `asyncio.to_thread` so a long
    report or `fsync` cannot stall the event loop.
  - **Triggered case (this is Changed, not cosmetic):** `report_bug` wrote to checkout `BUGS.md` and left the tree dirty.
    After the fail-loud clean-target check (#90 T2), any incoming bug report **blocked EVERY merge** until a person
    committed someone else's file. It happened five times in one day.
- 🔔 **Unread bug-report banner in the dashboard** (`app/static/js/app.js`, `app/templates/dashboard.html`
  `#bug-report-banner`). A backend reader is insufficient; a person must notice the report without knowing its route.
  Read version is stored in `localStorage` (`orchestraBugInboxSeenVersion`); Markdown renders through `marked` + `DOMPurify`.

### Fixed
- 🔒 **Atomic spawn/switch/merge lifecycle** (`app/workspace.py`, `app/routes/sessions.py`, `app/manager.py`, `app/db.py`, `app/tm.py`, #93, four tickets).
  - **T1:** `create/merge/switch/remove` share one stable repository flock stored in the git common directory. Switch
    rollback uses CAS and fails closed. Merge returns typed commit-point snapshots and exact conflict paths.
  - **T2:** `execute_merge_session()` resolves id/name/scope/branch/head **once** and owns the chain
    `session → lifecycle → repo`; task lookup and CAS updates are project-scoped. A post-merge switch/task failure now
    returns as a partial result instead of disappearing.
  - **T3:** a worker remains invisible until worktree preparation and runtime startup finish. Repeated cancellation
    cannot break ownership of preparation, compensation, or finalization.
  - **T4:** HTTP, Telegram, background jobs, limit-wake, auto-reporting, and system routes converge on one
    `SessionManager.send()`. It rechecks `needs_switch` under the session lock, permits automatic switching only in
    IDLE, and preserves delivery to a RUNNING mid-turn session.
  - **Lock order is explicit** to prevent deadlock: manager session lock → `AgentSession._lifecycle_lock` → repository
    flock. There are no reverse edges.
  - Read-only verification on the **live** database: 383 sessions, 81 non-archived, nine active with
    `needs_switch=true`; all nine were IDLE with an existing worktree and resolvable base. Full run:
    **1,388 passed, 7 skipped**.
- 🛡 **Safe process termination** (`app/ssh_tunnel.py`, `app/bg_jobs.py`, new `app/pidfd_exec.py`, #120).
  - **Removed broad `pkill -f`** over a constructed pattern. It matched processes across the ENTIRE system, including
    the user's personal SSH sessions. **Measurement: three unrelated VPN-Service processes matched, versus zero useful
    matches in a month.** `grep pkill` under `app/` now returns zero matches.
  - **Removed `killpg` using a saved numeric PGID** after the leader exits. PGIDs are reused, so a signal could hit an
    unrelated new group. Replacement: pidfd identity (`app/pidfd_exec.py`).
  - Termination quality was retested rather than assumed: 100 shell-job iterations with a grandchild in the same group
    produced `grandchild killed with group: 100/100`, `unrelated process survived: 100/100`.
  - **Deliberately retained:** a narrow numeric TOCTOU inside `_kill_proc()` (the window exists only while
    `returncode is None`), moved to a separate task.
- 📋 **Task details appear consistently everywhere** (`app/mcp_stdio.py`, `app/static/js/app.js`, #113), and **chat
  restores at the last-read boundary** (`app/static/js/app.js`, `app/static/css/style.css`, #118); an anchor appears
  only when unread turns exist.
- 📊 **Stale statistics refresh on demand** (`app/static/js/usage.js`, #112).
- 🧰 **Typed MCP error contract** (`app/mcp_stdio.py`, #116 T5): a transport/domain failure becomes one envelope at
  the shared HTTP/MCP boundary. Partial success remains a domain result; optional failure becomes an explicit warning.
  Motivation: defects where the system knew the cause but remained silent (`Send failed: network error:` followed by
  empty text from stringifying `httpx.ReadTimeout`).
- 🔁 **RAG backfills are retained and coalesced** (`app/rag_service.py`, `app/routes/sessions.py`, #116 T7).

### Added (Telegram)
- 📱 **`/limits` command in the bot's private chat** (`app/tg_bridge.py`, #109). Shows independent remaining Claude 5h,
  Claude 7d, and Codex primary quotas, with each reset as absolute Krasnoyarsk time (UTC+7) and relative duration.
  - Access is limited to the configured group's `creator`; administrators and members receive `⛔ Access denied.`
    **before** data loading. Missing sender, missing group, or request failure all fail closed.
  - `extra_usage.spend_limit_reached` appears as a SEPARATE fact with a warning that base windows are independent—the
    exact case where a limit flag had already been misread as a provider verdict.

### Removed
- 🗑 **The entire private `tasks-pm` pipeline** (`pipelines/tasks-pm/`: 17 files, `app/pipeline.py`, #118), removed by
  owner decision. Basis: **zero sessions** used it and eight audit findings were solved by deletion rather than repair.
  Only `default` remains under `pipelines/`; no `tasks-pm` references remain in `app/`.

### Changed
- 🧭 **Worker default is Opus based on quota headroom** (`pipelines/default/pipeline.yaml`, `pipelines/default/prompts/`).
  Every role in the `default` pipeline currently uses `claude-opus-5[1m]`. The `<model-routing>` block in the system
  prompt is the sole routing source of truth; selecting models by worker names, old session models, or historical shares
  is explicitly forbidden.
- 🔐 **Restarts and deployments require explicit authorization** (`pipelines/default/prompts/base.md`,
  `git-workflow`/`orchestration`/`self-improvement` modules, `full-cycle` role, `vps-deploy`/`codex-debate` skills).
- 💵 **Prompt prices use exact units, not thousands** (`pipelines/default/prompts/modules/orchestration.md`): the phrase
  “in thousands” risked a 1,000× error.
- 🧱 **Worker lifecycle is stated before kill** (`app/manager.py`, `orchestration` module): a full-cycle agent at a gate
  is ALIVE and waiting for the next phase; only one-shot agents may be killed.

### Known issue
- ⚠️ The #113 orphan detector is a one-time process-age snapshot immediately after job completion, not continuous
  monitoring. It deliberately kills nothing (`orphan_tree=1 … observation_only=true`).
- ⚠️ #113 proposed three memory optimizations and **withdrew all three after measurement**: batch 64→16 changes
  embeddings deterministically (max `|Δ|=0.0296734`, min cosine `0.9718105`); a separate embedder process saves at most
  0.21 GiB time-weighted; an automatic reaper hits the same stale-PGID problem. The memory owner was still established:
  the bge-m3 ONNX embedder holds **0.8900 GiB PSS+SwapPss**, and unload+trim returns 91.90%.
- ⚠️ #121 (Agent Reach): the claim was tested and **disproved**; deployment is not recommended, and Orchestra code was
  unchanged (`docs/tasks/121/research.md`). Separately, launching Hiddify does not fix Reddit; every live proxy returns 403.

## v2.27.0 — 2026-07-31 — #108 overengineering audit: dead-code cleanup

The audit found a **healthy** foundation: overengineering was not a systemic style. Three suspects
were cleared—`backend_protocol.py` (a genuine protocol with four implementations plus fail-loud
validation in `build_backend`), `session_state.py` (breaks a real import cycle), and
`usage_analytics._provider_case` (already generated from one `PROVIDER_METADATA`). The real excess was not
architecture but **residue from removed features**. Result: 429 fewer production lines; full run
1,270 passed / 0 failed. Details: `docs/tasks/108/`.

### Fixed
- 🔇 **Prompt-block construction failure no longer pretends to be an empty list** (`app/manager.py`
  `_other_orchestrators_block`, `_workers_block`). Both were wrapped in `except Exception: return ""`, so any database
  error silently gave the orchestrator a system prompt WITHOUT its workers and other orchestrators.
  - An agent reads an empty block as “there are no workers” and **spawns duplicates** instead of reusing live ones.
    The failure is invisible and looks like “the agent is being stupid.”
  - Evidence: enclosing `ROLE_SYSTEM_PROMPT` says “Fail loud: … → ValueError” in its own docstring and does raise;
    the silent inner `except` contradicted the function's own contract.
  - Now: `logger.exception` with class and text, plus explicit `⚠️ … unavailable` and a workaround (`list_agents` /
    `list_orchestrators`) instead of `""`. The path does NOT fail: prompt construction is used by spawn/resume, so one
    corrupt row must not break recovery of every session. `except` is narrowed to `sqlite3.Error/KeyError/TypeError`.
- 🪵 **Nine silent fallbacks gained logging** (`app/tg_bridge.py`, `app/session_turns.py`). Control flow is unchanged;
  only logging changed (verified: removed diff lines contain only `except` headers, no `return` or `pass`).
  - Most important: `_md_entities` failure degrades **every** formatted TG message to plain text. It previously produced
    no log line and looked as if “Telegram decided to do that.”
  - Others: mirror-send ×2 (aligned with adjacent sites that already logged), tool-argument parsing ×4
    (Read/Grep/Bash/Glob), `spawn_worker` header, Local Bot API health probe (all ten attempts omitted WHY), and parsing
    `resets_at` in the quota line.

### Removed
- 🗑 **The entire spawn-queue subsystem** (`app/manager.py`, `app/db.py`, `app/routes/system.py`, `app/mcp_stdio.py`).
  It was a producer/consumer system without a producer: every startup made `start_background_tasks()` launch a coroutine
  that waited forever on `_spawn_queue.get()`, while nobody called `enqueue_worker_spawn`.
  - Archaeology: `e9b4e7f` (2026-06-02) moved `spawn_worker`/`kill_worker` from the queue to synchronous HTTP, but left
    the infrastructure behind. Tool `list_jobs` existed so an agent could learn the result of ITS OWN spawn; synchronous
    spawn leaves nothing to wait for.
  - Consequently, the only `update_job` calls lived INSIDE the dead loop and the only `INSERT INTO jobs` lived in dead
    `add_job`. A table without a writer, `list_jobs` always returned “No jobs,” and the production database had zero rows.
  - **There were seven copies of `list_jobs`, not two:** two tool registries, four in `app.js`, one `SKILL.md`, and
    **two prompt files** (`pipelines/default/prompts/`). Prompts were an unexpected third class of copy.
  - The dashboard is unaffected: its JOBS tab reads `/api/bg/jobs`, backed by a **different**, live `bg_jobs` table.
- 🗑 **The `inbox` table** had the same disease: `add_inbox` was dead, while `get_inbox`/`ack_inbox` were called by a
  live route guaranteed to return `[]` forever.
- 🗑 **Ten symbols with zero references** (−112): `db.kv_set`, `db.bg_get_active_for_scope` (duplicate of
  `bg_get_jobs(active_only=True)`), `db.usage_get_latest_provider_usage`, `models.register_provider_metadata`,
  `prompting.roles_catalog` (orphaned after `_roles_catalog_from_manifest`), `rag.apply_file_change`,
  `tm.get_project_prefix`, `tm.get_pending_syncs`, `tg_bridge._edit_expandable`, `tg_bridge._find_thread_for_scope`.
  Plus `manager.find_worker`/`find_session_id_by_name`/`unload`, fragments of the same `e9b4e7f` change.
- 🗑 **Three dead routes** (−111): `/api/open-file` (near-duplicate of `open_folder`), `/api/git-status` plus orphaned
  `_git_status_cache`/`_GIT_STATUS_TTL`/`_run_git`, and `/api/usage/daily{,/agents}` (superseded by
  `/api/usage/analytics`; `usage_daily_agents` contained the file's worst SQL—a manual `_conn()` and `c.close()` without
  a context manager).
- 🗑 **Runtime-registry plugin loader:** `load_runtime_plugins`, `_PLUGINS_LOADED`, `ORCHESTRA_RUNTIME_PLUGINS` were
  configured nowhere, yet `get_runtime()` called the loader on every resolution. The registry and four built-ins remain.
- 🗑 `db.rename_session` (shadowed by a same-named route that builds its own UPDATE), `db.usage_cleanup_old` (its only
  “reference” was a comment about its removal), and `TG_WORKER_TOPICS` from `.env.example`.

### Changed
- ♻️ **Shared JSON-RPC transport for Codex and Grok:** new `app/backend_jsonrpc.py` (`JsonRpcStdioTransport` plus
  canonical `bounded_tool_arguments`).
  - Basis: measured `difflib` similarity, not visual judgment—`_write` 0.97, `_request` 0.94, `_notify` 0.93,
    `is_alive` 1.00, `_drain_stderr` 0.86. Exactly two things differed and became `RUNTIME_LABEL` and
    `JSONRPC_ENVELOPE`. `_bounded_tool_arguments` and `_bounded` were one function with one docstring under two names.
  - **The boundary was deliberately not crossed:** `connect`, `send`, `_read_stdout`, `_turn_completed`, `_build_env`,
    and `_classify_error` are untouched; the same measurement gives 0.06–0.37, a legitimate semantic difference.
    Extract transport, not meaning.
  - Behavior was verified rather than assumed: error text remains runtime-specific; only Grok uses the
    `{"jsonrpc":"2.0"}` envelope; **JSON key order matches the original byte for byte** (some JSON-RPC servers care).
- 🎨 **JavaScript dictionaries have one source** (`app/static/js/app.js`). The background-job icon dictionary existed
  four times (three inline plus canonical `_JOB_ICONS`), and statuses twice. Inline copies now reference constants.
  TDZ safety was tested with a case under `node` rather than inferred. An inline copy of `_escHtml` was replaced by `_escHtml`
  itself because their bodies were byte-identical.
  - The canonical choice between `escHtml` (DOM-based, escapes quotes) and `_escHtml` (string replacement, does NOT
    escape quotes) was **left unchanged**. They are not equivalent; mechanical replacement could cause an XSS regression.

### Known issue
- ⚠️ **`_hydrate_row` and `_load_from_db` have diverged** (`app/manager.py`), two database-row-to-`AgentSession`
  mappers. The first sets `_last_context["max_tokens"] = 0`; the second reads `get_model_spec(...).context_length`.
  The same session receives a different context limit depending on its load path. Given the prior `ctx=100%` and three
  extra compactions, this is a plausible real defect. Tracked separately; not changed in #108.
- ⚠️ `jobs` and `inbox` remain empty orphan tables in existing installations. Their schemas were removed from `db.py`,
  but `CREATE TABLE IF NOT EXISTS` does not delete existing tables. No `DROP TABLE` migration was added because they hold no data.
- ⚠️ Production `.env` defines `KESHA_INBOX_URL`, but no line under `app/` reads it. The file is outside the repository;
  the owner must decide its fate.

## v2.26.8 — 2026-07-28 — #98 task numbers vs docs/tasks

### Fixed
- 🔢 **`task_create` no longer issues a number whose `docs/tasks/<n>/` directory already exists** (`app/tm.py`
  `_next_par`). It previously used only database `MAX(par_number)+1`; deleting a task returned its number to the pool
  while disk artifacts remained, so new research inherited someone else's `#96`.
  - After the database maximum: `while (scope/docs/tasks/<n>).is_dir(): n += 1`. The root comes from
    `tm_projects.scope`, like the project, not a hard-coded path.
  - Explicit `par_number=` for imports/migrations remains untouched.
  - **Triggered case:** `task_create` issued `#96` while `docs/tasks/96/` from OpenCodeBackend (`3031c42`) was live;
    the worker stopped before writing. Tests: `tests/test_tm.py` (RED→GREEN).

## v2.26.7 — 2026-07-28

### Fixed
- ⏱ **TG bridge tests no longer flake under load** (`tests/test_tg_bridge.py`). At 21 sites,
  `asyncio.wait_for(..., timeout=0.1)` imposed a wall-clock window rather than a contract requirement. On a busy machine
  (three workers plus parallel runs), 100 ms was insufficient even to start the coroutine, causing a random test in the
  file to fail. The symptom was order-dependent: 6/6 alone, failures in 2/3 combined runs, with a DIFFERENT test each time.
  - Timeouts increased to five seconds. Test semantics are unchanged—they still fail if the event never occurs—but the
    threshold no longer depends on machine load. The file contains no tests expecting `TimeoutError` (verified), so this
    adds no fixed delay: file runtime 4.4 → 7.1 seconds.
  - **Triggered case:** the T7 worker, whose diff changed documentation only, received a red full run and correctly reported
    that the failure was unrelated. Reproduced on a clean tree: 2/3 runs failed on untouched `main`.
- 📎 **`send_file` no longer fails with an empty `network error:`** (`app/mcp_stdio.py`). Delivery uses the reliable TG
  queue, which waits through flood control; Telegram routinely returns `429 Too Many Requests: retry after 24` for an active
  group. The MCP client cut the connection at its 30-second timeout in the middle of that retry.
  - This call's timeout alone increased to 180 seconds; the general `_api` default remains 30 seconds, appropriate for other tools.
  - Error text now includes the exception CLASS. `httpx.ReadTimeout` stringifies to an empty string, so the report previously
    read `Send failed: network error: ` with no cause. Silent diagnostics are worse than none.
  - **Triggered case:** two consecutive failures sending a PDF application from seedon. After the fix, the same file succeeded
    on the first attempt (`msg_id=104346`). No restart was needed because MCP processes start fresh for each call.

## v2.26.6 — 2026-07-28 — #95 Grok T7: documentation

### Added
- 📗 **`docs/grok-field-guide.md`:** a runtime field guide paired with `codex-field-guide.md` (same genre and location;
  no new directory). It covers bootstrapping a worker, why each worker needs its own `GROK_HOME`, differences from
  Claude/Codex, money and context with both traps ($0.30 cache and the prohibition on `TOKEN_PRICES`), a **“symptom →
  file to fix” map**, a rule for the next runtime, and a registry of unverified claims.
- 📄 **`docs/tasks/95/report.md`:** final task report with nine latent bugs found along the way and the method that found them.

### Reasoning
- **The unverified registry is consolidated in one place** (guide §7), not scattered through the CHANGELOG. Every entry
  states not only what is unknown but HOW to verify it: terminal quota-exhaustion shape (capture `Grok raw error payload:`
  from the first real limit hit and branch `rate_limit` on a field, not substring), `type:"http"` for URL MCP (only `stdio`
  verified; `mcpCapabilities` claims http/sse, but claimed ≠ verified), and cache TTL (binary-search delays between turns
  in one session, using a cron job rather than an agent background process that dies when the turn ends).
- **`CLAUDE.md` grew by 1,515 bytes rather than 2,339.** New traps were written in English because Cyrillic costs two
  bytes per character and little room remained below Codex's 32 KiB limit. Final size 30,095 bytes, 2,673 bytes headroom.
  The traps contain only what an agent will actually encounter; the full explanation belongs in the guide.
- **The shared-code contract lesson is a rule for the NEXT runtime**, not a narrative: catch the exception class, not one
  encountered instance; test new calls against REAL values from the live database, not fixtures; `ELSE claude` is always
  a bug; search for the second copy.

## v2.26.5 — 2026-07-28 — #95 Grok T6: dashboard, TG, consistency

### Fixed
- 📊 **Grok spending was charged to the Claude pool** (`app/usage_analytics.py`). Bucketing was binary:
  `CASE WHEN codex/gpt-% THEN 'codex' ELSE 'claude' END`, so the trailing `ELSE` swallowed every new runtime. SuperGrok
  usage would look like Claude quota usage, while cache hits used Claude's TTL—the dashboard hid the very reason Grok existed.
  - The expression was duplicated in TWO places (`_PROVIDER_SQL` and an inline CASE in the CTE), plus a THIRD copy of the
    same binary assumption in the cold-start threshold (`CASE WHEN provider='codex' THEN ? ELSE ?`). One `_PROVIDER_RULES`
    table now generates both SQL expressions and TTL parameters.
  - **Verified on a copy of the live database** (330 sessions; original untouched): existing buckets did not change
    (Claude 650 turns / Codex 328); a synthetic Grok turn creates a separate bucket with its own cost and `approx=True`.
- 🚫 **A Grok orchestrator could not start at all** (`app/backend_grok.py`). We passed `--no-subagents` when
  `is_orchestrator=True`, but `grok agent` has NO such flag (it belongs to the top-level command), producing
  `error: unexpected argument` before startup. The defect was latent because no orchestrator had used Grok. Replaced with
  documented `GROK_SUBAGENTS=0`; both modes were verified with live connections.
- 🎨 **Three binary ternaries in the provider card** (`app/static/js/analytics.js`). `isClaude ? … : …` meant “not Claude
  → render as Codex”: a third pool would inherit Codex's title, window shape, and—through `_analyticsCapacity`—**someone
  else's quota**. A `_PROVIDER_META` table plus explicit `_PROVIDER_CAPACITY_KEY` now generates provider lists in cards,
  cache grid, and agent filter instead of repeating four literals.
- ⏱ **`cache_policy_for_runtime()` no longer promises an exact Grok TTL** (`app/models.py`). The default “everything that
  is not Codex → 3600/exact” claimed precision nobody measured. Grok now has its own `approximate=True` branch, so the
  dashboard shows “≈”. xAI does not document cache TTL and the runtime does not report it; measurement would require hours
  of wall-clock time and did not fit the task.

### Verified (using REAL data from a read-only copy of the live database)
Audit after the empty-`pipeline` incident: the new runtime expanded the shared-code contract, and legacy sessions could
not satisfy it. Run against the actual values from 330 sessions:
- `pipeline` is empty in 27/330, `profile` in 316/330, `task_id` in 243/330, and `base_branch` in **all 330**;
  `role`/`scope`/`backend_type` are populated everywhere.
- `_grok_factory` builds successfully for every real combination: empty pipeline, empty profile, both, nonexistent
  pipeline name, and an orchestrator with an empty pipeline.
- No session has an empty `cwd`, but **248/330 directories have already been deleted**, normal for archived workers.
  Behavior was compared with Codex: both fail; only readability differs—`RuntimeError: worktree removed or relocated?`
  versus bare `FileNotFoundError`. There is no runtime discrepancy.

### Tests
`tests/test_backend_grok.py` (70): the Grok bucket matches before all others while the tail remains `ELSE 'claude'`;
TTL CASE covers every known provider with registry values; Grok cache policy is marked approximate; provider ids match runtime ids.

## v2.26.4 — 2026-07-27 — #95 Grok T5: errors, interruption, quota

### Fixed
- 🚨 **A Grok worker could not execute ANY shell command—the turn was canceled** (`app/backend_grok.py`). In response
  to `session/request_permission`, we sent `optionId: "allow"`, an id I **invented** in T1 from ACP convention. The
  agent's actual options are **`allow-once` / `reject-once`**. The mismatch meant “nothing selected,” so the agent
  canceled the entire turn: `tool_use` and `tool_result` existed, command output had arrived, yet `turn_end` reported
  `ok=False stop=interrupted`. Externally this would look like “the worker mysteriously abandons tasks,” with no error line.
  - Approval is now **selected from the offered list** (`_pick_allow_option`), preferring a durable choice over a one-time
    choice. If no allow option exists, the result is explicit `cancelled` plus a log containing every option; no invented id.
  - A second layer adds `--always-approve` for managed workers, preventing requests entirely (verified:
    `client requests: NONE`). Fallback was tested separately with the flag removed: it selects `allow-once` and finishes
    with `ok=True`.
- 🧪 **Eliminated the `test_sandbox_config_write_is_atomic` flake** (`tests/test_backend_grok.py`). The test started
  threads and required a reader to **happen to observe** new content, making the test itself a race that failed about one
  in four full-file runs. It is now deterministic: observation occurs exactly when the temporary file is written and
  checks that the destination still holds the old COMPLETE content, with separate tests for `rename` and write skipping.
  Verification: 40/40 green file runs; mutating back to ordinary writing fails both tests, so they catch the regression
  rather than merely pass.

### Verified (measurements using the live CLI)
- **Process death mid-stream** → exactly ONE `turn_end` (`ok=False`, `stop_reason=process_exit_-9`,
  `model_error=server_error`); `events()` returns immediately and **already received text is preserved**.
- **Error after streaming begins:** text is preserved and success is not reported (`stream` → `error` → `turn_end ok=False`).
- **`interrupt()` during a long turn with an active tool:** succeeds; the turn closes as `interrupted` with one `turn_end`.
- **Reconnect after process death:** `session/load` restores the same session and preserves its id.

### Known issue
- **The terminal quota-exhaustion shape remains UNKNOWN.** We could not exhaust SuperGrok, so no pattern was invented.
  An unrecognized failure remains `error` and fails loudly. Added: **the raw payload is logged verbatim** (`logger.error`,
  up to 4,000 characters) both in the error stream and on `session/prompt` failure, so the first real limit hit leaves its
  actual shape in the log rather than our summary. Classification comes after that, not before.
- `report_bug()` is deliberately not called from the backend: it is an agent MCP tool, not a tool for the Orchestra
  process, and under the project's then-current traps it wrote into checkout `BUGS.md` and blocked merges. The backend
  equivalent is a loud log + `error` + `turn_end(ok=False)` without silent retry.

### Tests
`tests/test_backend_grok.py` (66): approval comes from the offered options; durable beats one-time; no allow option returns
`None` instead of an invented id; raw payload reaches the log; process death emits one `turn_end` while preserving text;
an error after streaming is not reported as success.

## v2.26.3 — 2026-07-27 — #95 Grok T4: usage/cost locked down by tests

Almost no code changed; nearly everything already worked after T1. The value of this slice is that every assumption was
verified rather than trusted: incorrect cost does not crash; it lies in the dashboard for years.

### Verified (measured using the live CLI and locked down by tests)
- 📏 **The `context_pct` denominator comes from the RUNTIME, not our constant.** Verified by replacing
  `GROK_CONTEXT_LIMITS["grok-4.5"]` with a deliberately wrong 12,345; after connection the window became 500,000 and
  `context_pct` used it. Equal constant and runtime values (both 500,000) would conceal a broken mechanism, so tests
  deliberately separate them. This is the exact Opus failure where `CONTEXT_LIMITS` lied about the denominator and the
  agent compacted at the wrong time.
- 🧮 **`turn_completed.usage` is PER TURN, not cumulative.** This differs critically from Codex, which accumulates over
  the thread and requires a delta. Measurement across three turns in one session: `outputTokens` 49 / 22 / 23 (cumulative
  would be 49 / 71 / 94); input is almost entirely cached. The payload is consumed as-is, `cost_is_delta=True` is correct,
  and delta machinery is unnecessary. This had previously been my UNVERIFIED assumption.
- 🧠 **`reasoningTokens` are not billed in addition to output.** A test compares turns with and without them at equal
  `outputTokens`; cost must match.
- 💵 **Currency was already correct; no change was needed.** `MODEL_COST_CURRENCY = '$'` (`app/static/js/utils.js`) is
  used for `cost_usd` and model pricing. `data-currency` (rubles for tasks and payments) does not enter this path. Grok
  follows the same route as Claude/Codex.

### Known issue
- ⚠️ **Grok prices are deliberately NOT registered in shared `TOKEN_PRICES`.** `routes/system.py:_cost_cached_for()`
  recomputes history for every model in that dictionary using the Claude cache heuristic (cache_read = 10% of input).
  Grok cache costs $0.30 versus $2.00 input, or 15%; on a real measured turn the heuristic overstates cost by **+27.6%**.
  While absent from the dictionary, the function returns the stored value computed from `costUsdTicks`. A test locks this
  down: an attempt to “register prices like Claude while we're here” will fail.
- Consequence: Grok does not show `price_input`/`price_output` in the model dropdown, like all Codex models for the same
  reason. A deliberate compromise, not a defect.

### Tests
`tests/test_backend_grok.py` (58): runtime window overrides the constant from both `initialize._meta` and `session/new`;
foreign list model is ignored; `context_pct` uses the runtime window; cached tier is actually cheaper than fresh;
`cached > input` cannot produce negative tokens; unknown model costs zero rather than a guess; reasoning is not doubled;
usage does not accumulate across turns; Grok remains absent from `TOKEN_PRICES`, with the size of the error asserted.

## v2.26.2 — 2026-07-27 — #95 Grok T3: session resume

### Fixed
- 🔥 **Race on shared `GROK_HOME/config.toml` could disable MCP isolation by itself** (`app/backend_grok.py`).
  `ensure_grok_home()` rewrote the file on EVERY connection using ordinary `write_text`, i.e. truncate + write. A worker
  starting in that window read an **empty** config: without `mcps = false`, T2 isolation was off and foreign MCP servers
  started with their secrets.
  - **Measurement:** four writers + four readers for three seconds → **57.9% of reads saw an empty file** (17,626 of
    30,466). The same measurement after the fix: **0%**.
  - Fix: write through a unique temporary file plus atomic `rename`, and skip writing when content matches. This is the
    same technique as `workspace.sync_agents_md`, for the same reason.
- 🔁 **A stale `sessionId` no longer blocks a worker forever** (`app/backend_grok.py`). The store key is `(cwd, sessionId)`,
  so a moved or cleaned worktree made `session/load` fail forever and connection impossible. Now `session/load` failure →
  a new session plus a **loud** warning that history is unavailable. History is never lost silently.
- 📁 **Clear error for a missing worktree.** Previously process spawn produced a bare `FileNotFoundError` naming the path
  but not the cause.

### Known tradeoff
The failed-resume warning initially **never reached the user**: it carried the old `sessionId`, while `events()` discards
notifications with a foreign id, so the lost-history message filtered itself out. The key was renamed `staleSessionId`.
A live test caught this by requiring the warning to appear, not merely a successful connection.

### Reasoning
Measurements using the live CLI (risks specified by PM):
- **One shared `GROK_HOME` is session-safe for every worker.** Two workers connected simultaneously from different cwds
  received different ids and isolated turns (`ALPHA`/`BETA`). The session store is partitioned by URL-encoded cwd, so it
  cannot overlap by design. Only shared `config.toml` was dangerous; see above.
- **Resume SURVIVES a branch change in the same worktree.** After `main` → `feature/x`, `session/load` returned the same id
  and remembered the code word. Sessions bind to path, not branch, so the “survives restart” contract also holds after a
  post-merge branch switch.
- **Foreign cwd** with the same id → `Path not found` → fallback to a new session (verified: different id, history honestly unavailable).

### Tests
`tests/test_backend_grok.py` (48): atomic config writes under a concurrent reader, rewrite on content drift with no
temporary debris, resume warning not filtered by routing, and connection failure for a missing worktree.

## v2.26.1 — 2026-07-27 — #95 Grok T2: MCP isolation

This closes a leak channel, not a hygiene issue: the T1 artifact contained a live third-party service key because Grok
starts foreign MCP servers itself and relays their environment.

### Fixed
- 🔒 **A Grok worker starts with EXACTLY our MCP server set** (`app/backend_grok.py`). Two layers: an Orchestra-owned
  `GROK_HOME` (`data/grok-home`, in `.gitignore`) with `[compat.claude] mcps = false`, plus verification of the actual roster
  on connect. A foreign server raises `GrokMcpIsolationError`; the worker **does not start**, and the error lists offenders.
  - `auth.json` is a symlink to the user's file so token refresh does not go stale in a private copy. The directory is
    stable, not temporary: it also holds the session store required for resume (T3).
- ⚙️ **Environment `GROK_BIN` overrides PATH discovery** (`app/backend_grok.py`). Previously `shutil.which()` ran first,
  allowing an unrelated `grok` in PATH to silently beat explicit configuration.

### Reasoning
Measurements that determined the design (`docs/tasks/95`):
- **`session/new.mcpServers` MERGES with discovered servers rather than replacing them.** Supplying only `orchestra`
  produced `{orchestra, websearch, mcp-pandoc}`; supplying an empty list still produced two foreign servers.
- **The only working `[compat.claude] mcps = false` switch is read ONLY from user config.** The same key in project
  `.grok/config.toml` is ignored (`on (default)` versus `OFF (config)`). We cannot modify `~/.grok/config.toml`; it is the
  user's personal file and would break interactive Grok. Hence a dedicated `GROK_HOME`.
- **The plan rejected `GROK_HOME` as breaking authentication; measurement disproved that:** a sandbox with an `auth.json`
  symlink logs in normally (`logged in with grok.com`).
- **Discovery sources, exact list:** `~/.claude.json` (top-level plus 47 per-project records), project `.mcp.json`,
  `~/.grok/config.toml`, project `.grok/config.toml` files up to repository root, and plugins.
- **`.mcp.json` is suppressed by folder trust, not a switch:** the file itself removes trust from the directory, so the
  headless server does not start. We do not rely on this; the runtime check catches it independently.

### Known tradeoff
The connection check initially relied on `_x.ai/mcp/server_status`, producing a **false “clean”** result: our `orchestra`
reports `ready` only AFTER the first turn, while `mcp_initialized` arrives earlier, leaving the roster empty at verification.
The roster now comes from `_x.ai/mcp/servers_updated`, which arrives early and is itself the leak channel that relayed the
key. `server_status` remains a secondary signal.

### Tests
`tests/test_backend_grok.py` (43): connection rejection for a foreign server, roster limited to our sources, roster from
`servers_updated` (regression for false “clean”), `GROK_HOME` with Claude compatibility disabled and auth symlink, fail loud
without credentials, injected `GROK_HOME` overriding inherited state, and `GROK_BIN` priority. Live: no leak with the sandbox;
bypassing isolation makes the connection fail.

## v2.26.0 — 2026-07-27 — #95 Grok Build runtime (T1)

A fourth runtime alongside `claude`/`codex`/`opencode` (`docs/tasks/95/research.md`, `plan.md`). The motivation is a
separate SuperGrok quota pool. The research itself received no cross-review because the Codex pool was exhausted until
2 August. For now it is **registry-only**: the runtime must be selected explicitly; `pipeline.yaml` defaults are unchanged.

### Added
- 🤖 **`GrokBackend`: ACP (Agent Client Protocol) over `grok agent stdio`** (`app/backend_grok.py`). A long-lived process
  plus JSON-RPC 2.0 over stdio, analogous to `codex app-server`. Session resume uses `session/load`; interruption uses
  `session/cancel` (verified: immediate, `stopReason=cancelled`, stream stops). Model `grok-4.5`, context **500,000**
  (runtime value; articles claiming “256K” were disproved).
- 🧩 **Runtime and model registration** (`app/runtime_registry.py`, `app/models.py`). `_infer_backend()` sent everything
  outside `gpt-*`/`claude-*` to **`opencode`**, so an unregistered `grok-4.5` would silently reach the wrong runtime.
  Added `grok-*` → `grok` with provider `x-ai`; provider-qualified ids such as `x-ai/grok-4` deliberately remain on `opencode`.

### Reasoning
- **A separate backend, not a shared Codex layer.** Line-based measurement: of 1,105 method lines in
  `backend_codex.py`, only **220 (20%)** are shared JSON-RPC transport, while **826 (75%)** implement Codex's event
  vocabulary (`item/started`, `item/completed`, `collabAgentToolCall`), which Grok lacks entirely. ~80% divergence at
  a 30% threshold. Precedent: `backend_opencode.py` imports nothing from `backend_codex.py` either; the only shared layer
  is the 16-line `BackendLike`.
- **The system prompt travels ONLY through `--agent-profile`** (temporary `.md` with YAML frontmatter, deleted on
  `disconnect`). ACP fields `systemPrompt`/`_meta.systemPrompt`/`instructions` are accepted and **silently ignored**,
  leaving the worker without any prompt. A canary proved this before code was written.
- **`mid_turn_inject=False`.** A prompt sent during a turn does not steer it; it enters the native queue and runs as a
  SEPARATE turn, so N messages = N `turn_end` events. The event loop completes when the queue empties, not at the first
  `prompt_complete`, or queued turns would stream into nowhere.
- **Cost comes from the runtime.** `costUsdTicks` = **1e-10 USD**, not 1e-9—the first research version used the wrong
  units and was retracted. Four measured turns match `((in−cached)·$2 + cached·$0.30 + out·$6)/1e6` exactly. The real
  cache price is **$0.30/M**, not the $0.50 quoted by every article. Prices live in `backend_grok.py`, not `TOKEN_PRICES`,
  which has no `cached` tier.

### Known issue
- **The terminal quota-exhaustion shape is unknown:** we could not exhaust SuperGrok. `_classify_error` does not guess;
  an unrecognized failure remains `error` and fails loudly (`report_bug`, no silent retry). Classification will follow the
  first real limit hit, not precede it.
- **Foreign MCP servers are not yet suppressed** (T2). Grok discovers servers from `~/.claude.json`/`.mcp.json` and
  relays their environment; this exposed a live `OPENROUTER_API_KEY` during research. The factory already assembles an
  explicit set from our sources, but suppressing implicit discovery is a separate ticket.

### Tests
`tests/test_backend_grok.py` (33): event mapping from a real dump, idempotent `turn_end` under two completion signals,
`x-ai/grok-4` not intercepted, MCP-to-ACP translation (environment as a list of pairs, not a dictionary), and three
measured turns as cost fixtures. `grok` was also added to contract test `test_backend_classes_satisfy_structural_contract`.

## v2.25.1 — 2026-07-27

### Removed
- 🗑 **Opus 4.6 and 4.8 were removed from the model registry** (`app/models.py`, `app/tg_bridge.py`,
  `app/static/js/app.js`). They are gone from `MODELS`, `CONTEXT_LIMITS`, `BACKENDS`, `TOKEN_PRICES`, semantic aliases,
  short TG names, and the dashboard palette, leaving only current models in the dropdown.
  - Old ids (`claude-opus-4-8[1m]`, `claude-opus-4-6`, with and without suffixes) **remap to
    `claude-opus-5[1m]`**, using the same technique as `claude-sonnet-4-6` → Sonnet 5. A database session with an old
    model starts on Opus 5 rather than failing.
  - Also removed dead auto-bump `effort low/medium → high` for 4.8 from `backend_claude.py`. Claude's auto-downgrade
    `xhigh → high` remains because it addresses an API limitation, not a model.
  - The database contained no live 4.6/4.8 sessions (`sessions.model` measurement); the single 4.8 worker was moved to
    Opus 5 before the change.

## v2.25.0 — 2026-07-27 — #90 lifecycle T1–T3

Worktree/merge lifecycle audit (`docs/tasks/90/audit.md`, 12 confirmed defects, 19 experiments). Implementation proceeds
in vertical slices T1→T7; T4–T7 are frozen until the weekly Codex quota resets on 2 August.

### Added
- 🌿 **Persisted base-branch contract** (T1; `app/db.py`, `app/session.py`, `app/workspace.py`,
  `app/routes/sessions.py`, `app/mcp_stdio.py`). Columns `base_branch TEXT DEFAULT ''` and
  `needs_switch INTEGER DEFAULT 0`; the spawn base resolves ONCE (explicit → symbolic remote HEAD → sole local
  `main`/`master`) and is stored in the session. `merge`/`switch`/`wip`/`kill` read it instead of literal `main`.
  - **Why not “infer it from HEAD”:** after `checkout feature/x`, symbolic HEAD names the feature branch; mainline
    cannot be reconstructed retroactively. An ambiguous legacy row now fails loudly before any git operation instead
    of merging into a random branch.
  - **Triggered case:** primary branch ≠ `main`—Aperant uses `develop`; VPN-Service contains both `main` and `master`.

### Changed
- 🔒 **Merge runs in the checkout that owns the target and rejects a dirty target** (T2; `app/workspace.py`). A branch
  checked out in the parent worktree is merged there. Auto-stash was removed from the merge path; uncommitted changes
  are returned to the user as a path list, and neither target nor worker branch is touched. Prunable worktree metadata
  no longer produces 500 (found in Codex review).

### Fixed
- ♻️ **Squash commit is atomic: hook failure rolls back the target** (T3; `app/workspace.py`). Failed `git commit`
  (pre-commit hook, related or unrelated paths) now restores HEAD/index/worktree to original `old_head` and verifies
  the rollback; the worker branch is unchanged. Previously failure left cherry-picked commits in the target while
  reporting an error, a “half-merged” state.
- 🔗 **`merge_worker` no longer prints `FAILED — unknown` after successful linking** (T3; `app/tm.py`,
  `app/routes/sessions.py`, `app/mcp_stdio.py`). `link_commits_to_task()` returned a task row or `None`, while MCP read
  the same object as `{ok, added, error}`; success without an `ok` key rendered as an unnamed error. The function now
  returns stable DTO `{ok, added, task_id | error}`, and an unknown task has explicit text.
  - **Triggered case:** two consecutive merges reported failure after actually succeeding; task status was set manually.
  - **Tests**: `test_related_commit_failure_rolls_back_target_and_preserves_worker`, `test_unrelated_commit_failure_rolls_back_target_and_preserves_worker`, `test_merge_links_commits_with_normalized_sqlite_results`, `test_merge_worker_formats_normalized_and_legacy_link_results`.

### Known tradeoff
- Until Orchestra restarts, live FastAPI retains old `app/routes/` code while fresh MCP processes load new code, so
  `FAILED — unknown` and `target branch '' does not exist` remain reproducible. Workaround: explicitly call
  `merge_worker(name, target="main")`.

## v2.24.3 — 2026-07-27

### Changed
- 🔇 **Compact summary is no longer sent to TG** (`app/session.py:1201`). The full summary was logged as type `text`,
  and `text` means agent speech to the bridge, so it immediately forwarded several kilobytes into the topic with a user mention.
  - Restore old behavior with `LOG_COMPACT_SUMMARY=1` in `.env` (default `0`, documented in `.env.example`).
  - The summary is preserved in `session.last_summary`, the new context preamble (`user_message` log), and the
    `compact_worker` response. Chat now receives one line: `compact done: X% → Y% (summary N chars)`.
  - **Triggered case:** the user received a wall of text in TG after orchestrator compaction and requested a flag rather
    than permanently changing behavior.

## v2.24.2 — 2026-07-26

### Removed
- 🗑 **`_auto_commit_if_dirty`: spawn no longer commits the user's uncommitted work** (`app/manager.py`). Before creating
  a worktree, the function ran `git add -A` + `git commit` in the working checkout, justified by the claim that
  “worktrees inherit unstaged junk.”
  - **The justification was false**, verified experimentally in a clean repository: `git worktree add <path> HEAD`
    builds from the commit; source unstaged changes and untracked files never enter it. The function ran only under
    `use_worktree and repo_path`, exactly the one case where it was unnecessary.
  - **Triggered case:** the inscryption-ai orchestrator discovered that Orchestra committed someone else's `.serena/`
    directory to `main` before spawning a worker. This happened on every spawn from a dirty repository since `1e39c47`.
  - Removed two mocks from `tests/test_manager.py`; nobody tested the function itself.

### Fixed
- 📁 **Worktree directory and branch are named from repository root, not session `scope`** (`app/workspace.py:285-294`).
  Before: `wt_dir = WORKTREE_ROOT / _slugify(scope)`, while the repository came from `repo_path`: two independent,
  never-reconciled sources.
  - **Symptom:** workers `impl-deck-search`, `impl-inscryption`, and `feat-inscryption-ai` lived under
    `worktrees/home-maxim-cursor-cog-second-brain/` even though `git-common-dir` was
    `/mnt/data/Projects/Python/inscryption-ai/.git`. This appears when a parent in one project spawns a worker in another.
    Branches were also named `feat/home-maxim-cursor-cog-second-brain/<name>` inside the unrelated repository.
  - **Why it matters:** this produced a series of false “`repo_path` is ignored” bug reports. Orchestrators read the path
    instead of `git-common-dir` and inferred a miss. The earlier `fix-repo-path` investigation cleared `repo_path` but
    did not find the actual cause.
  - Removed `scope` from `create_worktree`; after the fix it was unused. Existing worktrees are unaffected because their
    paths are stored in the database.
  - **Tests:** `test_repo_namespaced_path`, `test_branch_namespaced_by_repo`, `test_worktree_belongs_to_requested_repo`,
    `test_different_repos_no_collision` (replaced `test_different_scopes_no_collision`; the property “different scopes
    → different paths” no longer exists). 152 green.

## v2.24.1 — 2026-07-01

### Added
- 🔀 **`POST /api/proxy/set-env`: switch proxy with a button, without editing `.env` manually.** The frontend sends
  `{"id": "contabo-de"}`; the endpoint finds the proxy in `PROXY_LIST` and rewrites ONLY `HTTPS_PROXY`/`HTTP_PROXY`
  lines in `.env` (line surgery via `(?m)^KEY=.*$`; TG/YouGile tokens untouched). `url=="direct"` → empty value for a
  direct connection. Response: `{"ok": true, "wrote": <url>, "need_restart": true}`.
  - **NOT a hot switch:** neither `os.environ` nor the database changes. `.env` remains the source of truth and applies
    after the user restarts. The old `select_proxy` behavior (mutate environment live → drift) is excluded by design.
  - **Implementation** (`app/routes/proxy.py`): `_set_env_proxy(url)` performs an atomic write (temporary file plus
    `os.replace`; a crash must not corrupt `.env` containing tokens). `ENV_FILE = Path(__file__).parent.parent.parent/.env`
    matches systemd `EnvironmentFile`/`WorkingDirectory`. `re.sub` uses lambda replacement so URL/password are written
    literally without backslash interpretation.
  - **Codex review:** zero bugs (checked regex anchor against `PROXY_LIST`, case sensitivity against `https_proxy`, path
    traversal through `body.id`, and direct→empty). Atomic writing was added from a residual comment.
  - **Tests**: `tests/test_proxy.py` — token preservation, direct→empty, append-when-missing (9 pass).
  - **Frontend:** the proxy-selection button implementing this contract belongs to frontend-opus.

## v2.24.0 — 2026-07-01

### Changed
- 🔌 **Proxy: `.env` `HTTPS_PROXY` is the sole source of truth; database/hot-switch removed.** The user asked to
  “cut all the unnecessary parts.” Proxy management now uses only `.env` plus `sudo systemctl restart orchestra`.
  Removing all live environment mutation makes drift impossible by design (`.env` showed 12343 while CLI agents retained
  12342 from the database).
  - **Root cause of drift:** database `kv.active_proxy` **overrode** `.env`; `load_saved_proxy()` rewrote `os.environ`
    from the database at startup. Live CLI agents then held DIFFERENT proxies because `backend_claude._make_client()`
    snapshots `os.environ["HTTPS_PROXY"]` at `connect()` into a persistent SDK client (verified: pid A→12334, pid B→12342).
  - **Removed from `proxy_manager.py`** (net −107 lines): `load_saved_proxy` (read database kv), `select_proxy` (mutated
    `os.environ` + `MCP_BASE_ENV`, wrote kv), `refresh_loop`, `_cache`/`CACHE_TTL`/`_ts` stamps, and `_active_id` state.
    The module is read-only now: `list_proxies()` derives `active` from `os.environ` via read-only `_active_id()`, while
    `check_all()`/`check_proxy()` perform on-demand health checks without cache.
  - **`routes/proxy.py`:** removed `POST /api/proxy/select/{proxy_id}` and live-agent interrupt logic. `list`, `check`, and
    `tunnel/status` remain. `route_surface_snapshot.json` updated.
  - **`main.py`:** removed `proxy_manager.load_saved_proxy()` and the `refresh_loop` task.
  - **Frontend** (`app.js`): removed the “select proxy” button (`.proxy-select-btn`) and handler. Check and active indicator remain.
  - **Database:** `DELETE FROM kv WHERE key='active_proxy'`. Migration/column untouched; they are dead and unread.
  - **#3 Direct id fix:** force `id="direct"` when `url=="direct"`. Previously the id came from the name, yielding
    `direct-(vpn/соту)` with Cyrillic and parentheses, so `select/direct` returned 404. The `.env` name is now simply `Direct`.
  - **#4 zombie backoff + health gate** (`ssh_tunnel.py`): dead VPS endpoints (timeweb/ezhik) reconnected SSH every five
    seconds forever (`kex_exchange_identification: Connection reset` in logs), creating zombies. A two-second TCP health
    gate on `:22` now precedes spawn, with exponential backoff 5→300 seconds and reset after uptime >60 seconds.
  - **`CLAUDE.md`:** “🔌 PROXY” section documents the source of truth, how to switch, and read-only dashboard behavior.
  - **Codex wrapper** (`~/.local/bin/codex`): added `HTTP_PROXY`; only HTTPS existed before and Codex WebSocket failed without it.
  - **Tests:** `tests/test_proxy.py` (six: direct id, active-from-env, no-mutation-methods, port probe, health gate). 48 green.
  - **Reverted from v2.23.0:** `CACHE_TTL`/`refresh_loop`/`_cache`, added in the prior iteration but unnecessary with
    on-demand dashboard checks.
  - **Docs**: `docs/tasks/proxy-fix/{best-practices,plan-simplify}.md`.

## v2.23.0 — 2026-07-01

### Fixed
- 🔌 **Proxy SSH tunnels depended on VPN and accumulated zombie processes (proxy-fix).** Every Orchestra proxy was an
  `ssh -L` tunnel to a VPS. After a network change or disabling Reality VPN, old SSH processes remained half-alive and
  held the local port; a new tunnel could not bind, and the proxy silently returned HTTP 000. Duplicates also accumulated:
  nine SSH processes for four tunnels.
  - **Root cause:** NOT Russian network blocking. Contabo (<VPS_IP>) and Fornex (<Fornex IP>) were directly
    reachable from Russian Wi-Fi without VPN (verified by SSH banner plus
    `curl -x :12343 https://api.anthropic.com/v1/messages` → HTTP 405). Problems: (1) with VPN ON, xray TUN mode
    (`ip rule 9001 lookup 2022`) routed VPS traffic through tun0; (2) stale SSH processes were never killed.
  - **`_kill_stale(t)`** (`app/ssh_tunnel.py:37`) runs
    `pkill -f "ssh -N -L {local}:127.0.0.1:{remote} .*root@{host}"` before each tunnel starts—once in `start_tunnel`,
    NOT in the reconnect loop. The pattern pins local and remote ports **and** host, killing only ITS tunnel definition,
    not another same-port forward. Tested against real SSH processes: kill own, preserve foreign.
  - **Hard kill:** `stop_tunnel` and its CancelledError handler now run `terminate()` → `wait_for(KILL_GRACE=3s)` →
    `kill()` (SIGKILL) if SSH hangs on a dead route. `KILL_GRACE=3` (`ssh_tunnel.py:18`).
  - **Dashboard TTL** (`app/proxy_manager.py`): `_cache` without a TTL showed a dead proxy as 🟢 forever. Results now
    receive monotonic `_ts` stamps under `CACHE_TTL=60s`; `list_proxies` drops stale data, making the frontend show ⚪
    (unknown, already supported at `app.js:4879`). `refresh_loop()` (background task at `main.py:56`) rechecks every
    60 seconds and self-heals.
  - **`.env`:** reordered `SSH_TUNNELS` with live contabo/fornex first and dead ezhik/timeweb last. `check-proxies.sh`
    candidates follow the same order.
  - **NM hook:** `scripts/99-orchestra-proxy` dispatcher for up/down/vpn-*/connectivity-change → `check-proxies.sh`.
    The user installs it manually as root; instructions are in the file header.
  - **Triggered case:** the user disabled Reality VPN on home Wi-Fi and Orchestra failed as its tunnels died. The goal is
    a proxy as a REPLACEMENT for VPN, not a dependency on it.
  - **Skipped:** `ip rule` split tunnel (#5). The user runs VPN **or** proxy, not both, so VPN-off leaves nothing to intercept.
  - **Codex review:** confirmed safe matching (12340≠123400) and correct `_kill_stale` placement in `start_tunnel`; accepted
    the suggestion to narrow the pkill match to host + remote (implemented).
  - **Research**: `docs/tasks/proxy-fix/research.md`.

## v2.22.0 — 2026-06-21

### Added
- 📡 **Real-time token streaming in dashboard (task #83)** — agent text now types out live in the chat bubble as the model generates it, instead of appearing all at once when the turn's text block completes. Latency drops from "whole block after completion" to ~5 chunks/sec (~80-100 chars/chunk — the Claude CLI batches deltas; not per-token).
  - **Backend**: `include_partial_messages=True` in `ClaudeAgentOptions` (`app/backend_claude.py:138`). `_convert` gained a `StreamEvent` branch (`backend_claude.py:242`) that emits `AgentEvent("stream", text)` — STRICTLY scoped to main-agent `text_delta`: `parent_tool_use_id is not None` (subagents), non-`content_block_delta` events, and `thinking_delta`/`input_json_delta`/`signature_delta` are all filtered out. The final `AssistantMessage` still emits `text`/`thinking`/`tool_use` and is persisted exactly as before.
  - **Pub/sub**: new `app/live_broker.py` — in-memory per-session broker (`broker.subscribe/publish/unsubscribe`). Bounded `asyncio.Queue(maxsize=256)` per viewer, drop-oldest on overflow (partials are ephemeral, never block the agent loop). Single-process/single-loop only (like the session manager). Sync `publish` — never awaits.
  - **Routing**: `session._handle_event` (`session.py:519`) routes `stream` events to `broker.publish(self.id, ...)` — NO DB write. Key is `self.id` (== `manager.get_session_id` == `logs.session_id`), NOT the Claude `session_id` (often `None` on first turn).
  - **SSE**: `stream_session_logs` generator (`app/routes/sessions.py:279`) now subscribes to the broker, drains live partials BEFORE polling the DB each tick (ordering: partials always precede their final `text` row → no orphan bubble), 0.1s poll while active / 0.5s idle, `unsubscribe` in `finally`.
  - **Frontend**: the `type:"stream"` bubble renderer existed since 2026-05-01 (`c82e725`) but was DEAD CODE — no backend ever emitted it. Now wired up. Fixes: final `text` replaces the bubble body with the DB-authoritative content (`app.js:2155`, handles dropped/truncated partials); `firstId`/`lastId` bookkeeping guarded with `Number.isFinite(l.id)` (`app.js:189` — partials carry no id).
  - **NOT touched**: DB schema, cost/usage accounting, TG bridge (stays final-only — partial spam would be insane), codex/opencode backends (emit no `StreamEvent`).
  - **Tests**: `tests/test_live_broker.py` (7 — fan-out, drop-oldest, unsubscribe cleanup, session isolation), `tests/test_backend_stream.py` (7 — scope filter: text_delta passes; thinking/input_json/signature/subagent/non-delta dropped). All 14 green.
  - **Codex review**: APPROVED, 0 blocking — verified no subscription leak, no broker race, no orphan bubble, correct scope filter.
  - **Research artifacts**: `docs/tasks/83/` (research.md, plan.md, capture_partial.py, partial_dump.jsonl).

## v2.21.1 — 2026-06-15

### Fixed
- 🐛 **OpenCode turn never ends → orchestrator stuck `running` (task #97, 11h in prod)** — the turn boundary relied on the fire-once SSE `session.idle` event (global bus, 30s heartbeats, frequently MISSED) plus a chat `POST /message` that could hang forever. When both failed, `events()` never yielded `turn_end`, the listen task never exited, status stayed `RUNNING` indefinitely.
  - **Technical core**: rewrote `OpenCodeBackend.events()` (`app/backend_opencode.py`) to detect completion by POLLING `GET /session/status` every `STATUS_POLL_INTERVAL=3s` — an authoritative daemon query that cannot be "missed" like an event. Idle ⟺ session absent from the status dict OR `type=="idle"`; `busy`/`retry` ⟶ keep waiting. SSE is kept ONLY for live streaming of `text`/`thinking`/`tool` parts (`_handle_sse` helper + `_SESSION_IDLE`/`_SESSION_ERR` sentinels — SSE idle just triggers an immediate status poll, never ends the turn on its own).
  - **Send path**: `send()` now submits via `POST /session/{id}/prompt_async` (returns `204` immediately) instead of a chat-POST task that could hang. Dropped `_chat_task`/`_post_chat`; per-turn state is a single `_turn_active` flag. Body uses NESTED `model:{providerID,modelID}` (the `prompt_async` schema differs from the old `/message`).
  - **turn_end** built from `GET /session/{id}/message` (last assistant message) via new `_fetch_last_message()` — cost/tokens independent of the submit. `_turn_end` normalizes both `{info,...}` and flat-`AssistantMessage` shapes (`info = msg.get("info") or msg`).
  - **No-stuck guarantees (all Codex-flagged)**: HARD deadline enforced INSIDE `events()` (`TURN_TIMEOUT`) — the `session.py` timeout only runs when `events()` yields, so a perma-`busy` daemon would've still hung; `_turn_active`/`_sse_response` reset in the `finally` (cancel-safe); status-poll tolerates transient failures (`STATUS_FAIL_THRESHOLD=3` consecutive OR `_proc_dead()` before declaring dead); message-fetch is total → exactly one `turn_end` on every exit path.
  - **`app/session.py:365`** — wrapped `await backend.send(message)` in try/except: a `send()` failure after `status=RUNNING` and before the listen task is created was a SECOND stuck-running path (any backend). Now resets to `IDLE` on failure.
  - **Removed**: all the prior debug-patch cruft — `INACTIVITY_TIMEOUT`, `wait_timeout`, the SSE-drain loop, the useless heartbeat daemon-poll.
  - **Tests**: `tests/test_backend_opencode.py` event-loop suite rewritten for the poll model (fake SSE + scripted `/session/status`). New cases: SSE-never-sends-idle (THE bug), perma-busy hits hard deadline, single vs repeated status failures, retry-not-premature, message-fetch empty/raises, flat-message shape, cancel resets `_turn_active`, submit-grace. 44 tests green.
  - **Triggered case**: orchestrator on opencode backend sat at `running` for 11h after a turn the daemon had actually finished — the `session.idle` SSE event was dropped and the chat POST response was lost.

## v2.21.0 — 2026-06-14

### Added
- 🔌 **OpenCodeBackend (`app/backend_opencode.py`)** — third `BackendLike` backend wrapping the `opencode serve` daemon (HTTP + global SSE bus), alongside Claude/Codex. Wired into `session.py:_make_backend` (`backend_type == "opencode"`) + `events.py` type-comment. Task #96, Codex-reviewed plan + impl (4 rounds → APPROVED). 39 unit tests, all green.
- 🧭 **Backend routing → opencode (`app/models.py`, Phase 2)** — `_infer_backend()` now: `gpt-*`→codex, `claude-*`→claude, **everything else** (deepseek, gemini, llama, mistral, …) → `opencode`. `backend_for_model()` infers from the ID prefix for UNregistered models instead of defaulting to claude — a never-seen `deepseek/deepseek-v4-flash` from the proxy routes correctly. No model IDs hardcoded; dynamic `fetch_models_from_proxy` populates `BACKENDS` via `_infer_backend`. Provider/model split (`OpenCodeBackend.__init__`) parses proxy `provider/model` IDs (`deepseek/deepseek-v4-flash` → provider `deepseek`, model `deepseek-v4-flash`; first slash only). `tests/test_backend_routing.py` (9 tests).
  - **Shape**: Codex-like managed subprocess (one turn per `send`, native `cost` from the chat response — NO `TOKEN_PRICES` table needed) but with Claude-like streaming richness (`text`/`thinking`/`tool_use`/`tool_result`) delivered over a SEPARATE global SSE stream (`GET /event`), not inline.
  - **Dual-source turn coordination**: `events()` does `asyncio.wait({next_sse_line, chat_task}, FIRST_COMPLETED, timeout=TURN_TIMEOUT)`. `session.idle` = turn boundary; the awaited chat POST (`{info:{cost,tokens}}`) supplies authoritative `turn_end` metadata. Exactly ONE `turn_end` on every exit path (idle / sse_failed / timeout / chat_failed / chat_cancelled / early-close).
  - **Transport**: plain `httpx` (not the `opencode-ai` SDK) — the SDK's pydantic event types silently drop `reasoning`/`message.part.delta`/unknown events; raw-dict parsing keeps full fidelity. No new dependency (httpx already present).
  - **MCP**: Orchestra stdio `{command,args,env}` → OpenCode `McpLocalConfig {type:"local",command:[...],environment,enabled}`, written into a per-worker `opencode.json` in the worktree (merged if one exists). `permission: {edit,bash,webfetch:"allow"}`.
  - **Daemon lifecycle**: one daemon per backend instance, free-port alloc with 3× retry, readiness via `GET /app` 200 poll, stdio → DEVNULL (no pipe back-pressure), teardown = abort → terminate → wait → kill → **reap** (verified: no zombies).
- **Reasoning**: re-derived the whole seam from a LIVE probe (opencode v1.17.6 + SDK 0.1.0a36) because the referenced `docs/research/RESEARCH-OPENCODE.md` never existed in the worktree. Captured real event shapes from a daemon turn — that's how the `reasoning` part (→ `thinking`) and cumulative-text streaming (suffix-only emit) were found.

### Fixed (caught during Codex review, in the new backend)
- 🐛 **SSE `aclose()` on a running generator** — `next_line.cancel()` must be `await`ed BEFORE `sse.aclose()`, else `RuntimeError: asynchronous generator is already running` silently swallows the close → HTTP-stream leak. Now: cancel → await → aclose.
- 🐛 **`CancelledError` leak on normal-end await** — `await wait_for(chat_task)` caught only `Exception`; an externally-cancelled task raises `CancelledError` (BaseException). Now a `chat_task.cancelled()` pre-check + explicit `except asyncio.CancelledError` → `turn_end(chat_cancelled)`.
- 🐛 **Concurrent `disconnect()` race** — snapshot `chat_task = self._chat_task` at the top of `events()`; a parallel `disconnect()` nulling the field no longer causes `AttributeError` mid-iteration.

## v2.20.0 — 2026-06-11

### Changed
- 🏗️ **Full architecture refactor P0–P4** (per `docs/reviews/arch-audit.md`, Codex-reviewed plan + impl, 5 commits `3a7b76a..57949c5`). Public API (HTTP/MCP/DB) byte-identical — guarded by `tests/test_routes_surface.py` snapshot (77 routes). 487 tests green.
  - **P0 fail-loud + async**: 24 silent `except: pass` → `logger.warning` with context; `tm_yougile.py`/`routes/tm.py` sync SQLite wrapped in `asyncio.to_thread` (connection-per-helper, transaction never crosses await); `tm.set_main_loop()` + `run_coroutine_threadsafe` fallback — YouGile sync fired from worker threads no longer silently no-ops; codex turn loop got `_on_task_done` callback; `_auto_continue` capped at 5 consecutive max_turns
  - **P1 union-type fix**: `manager.get_by_name()` always returns `AgentSession | None` — detached DB-hydrate via `_hydrate_row()` with `loaded=False` discriminator + `db_row` for legacy response shape; 34 `isinstance(found, dict)` sites killed; `manager.update_session_fields()` replaces handler-level `_persist()` triplets
  - **P2 main.py drain**: 1574 → 91 lines; 56 handlers → `routes/{sessions,system,tg}.py`; `templates` → `deps.py`; `/api/open-file` now passes `_is_safe_path` (was the one unguarded sibling)
  - **P3 cycles → wired callbacks**: session→tg_bridge via module hooks `on_scope_idle`/`on_scope_running`; manager→tg_bridge via `tg_topics_remover` slot; tm→tm_yougile via `on_task_synced`/`on_payment_changed` registered at import; `MCP_BASE_ENV` → `runtime_env.py` leaf; `_fire_sync`/`_fire_journal_sync` deduped
  - **P4 session split**: `session_cost.py` (CostTracker), `session_turns.py` (TurnManager), `session_hibernate.py` (HibernateManager), `session_state.py` (AgentStatus leaf). Systems-over-state: ALL fields stay on `AgentSession` dataclass, systems hold methods. Cost math delta-based AS-IS, locked by `tests/test_p4_cost.py` contract
- **Reasoning**: audit found 43% of codebase (4 files) carrying all architectural debt; import graph was a DAG only via ~75 lazy imports. Now: downward-only edges, one lookup type, thin transport layer.

### Fixed
- 🐛 **Test hot-loop starvation** — `_MockBackend.events()` re-yielded `turn_end` infinitely with zero suspension points after `finish()`; tests hung when default DB had `bg_jobs` table. Fix: re-arm `_finish_event` after yield. Triggered case: full-suite run started hanging mid-`test_session.py` after stale WAL cleanup
- 🐛 **stop_bridge stale globals** (Codex impl review) — `bot`/`_manager` now cleared on stop; a handler racing past the unhook sees inactive state

### Known tradeoff
- Pending `tm_sync_log` row dangles if sync fired in a CLI context with no event loop — byte-identical legacy behavior, kept for behavior-preservation (in TODO)


## v2.19.0 — 2026-06-04

### Added
- 🔧 **Pipeline-as-config (PR #2)** — opt-in YAML manifests for roles/pipelines. Each client gets isolated `pipelines/<name>/` with custom roles, prompts, workflow. Rebased from v2.16.0 onto v2.18+, all conflicts resolved. `app/pipeline.py`, `pipelines/`

### Fixed
- 🐛 **TG topic icons for sub-orchestrator workers** — running status wasn't propagated to sub-orchestrator's TG topic. Added `notify_scope_running()` + `_find_scope_orch_name()` dedup. `session.py`, `tg_bridge.py`
- 🐛 **Single tilde rendered as strikethrough** — agents writing `~5 min` got false strikethrough between two tildes. Fix: escape single `~` before marked.parse. `app.js`

## v2.18.0 — 2026-06-03

### Added
- 🔧 **`needs_switch` guard** — after `merge_worker`, session is flagged `needs_switch=True`. Sending tasks to a merged worker returns 400 error until `switch_worker_branch` is called. Eliminates LLM-dependent "remember to switch" failure mode. `session.py`, `main.py`
- 🔧 **`merge_worker(next_task_id=)` atomic merge+switch** — optional parameter auto-switches to new branch after merge. One tool call instead of two. `mcp_stdio.py`, `main.py`
- 🔧 **Auto-cleanup stale worktrees** — on startup + every 24h, scans `worktrees/` and removes directories without active DB sessions. Checks dirty tree before removal. `workspace.py`, `manager.py`
- 🔧 **Cross-project `send_message`** — fallback to `ensure_loaded_any(name)` when same-scope lookup fails. Orchestrators can now message agents in other projects. `main.py`

### Fixed
- 🐛 **System prompt lost on compact/resume** — `backend_claude.py` had mutually exclusive `if resume_id` / `else` branches: resuming a session skipped `system_prompt` entirely. Fix: always set `system_prompt`, then optionally set `resume`
- 🐛 **Compact summary invisible in dashboard** — `session.py` sent compact preamble via `backend.send()` without `_log()`. Fix: added `_log("user_message", ...)`
- 🐛 **`switch_worker_branch` blocked after squash merge** — overly strict `merge-base --is-ancestor` check rejected worktrees diverged by squash merge. Fix: `git reset --hard from_ref` before branch switch. `workspace.py`
- 🐛 **Send errors hidden in dashboard** — `mcp__orchestra__send_message` renderer returned `null` on failure, silently hiding errors. Fix: show red `❌` with error text. `app.js`
- 🐛 **Spawn bubble text wrapping** — `task.slice(0, 200)` cut markdown mid-line, breaking bullet lists. Fix: cut at newline boundary. `app.js`
- 🐛 **Merge didn't update session** — `merge_session` reset worktree files but left `session.branch` and `session.task_id` stale. Dashboard showed outdated branch info. Fix: update session fields after merge. `main.py`

## v2.17.0 — 2026-06-01

### Changed
- **Merged `codex-review` module into `codex-debate` skill** — one skill, two modes: **Quick Review** (one-shot `codex exec review`/`codex exec` for pipeline Phase 2/3, no session) and **Debate** (multi-round persistent sessions, existing). All Bash rules preserved: `timeout: 300000` on the Bash tool, `timeout 300` wrapper, `EXIT:$?` check, `HTTPS_PROXY= HTTP_PROXY=`, anti-hallucination, MCP `codex_review()` as legacy fallback. `app/prompts/skills/codex-debate.md`

### Removed
- **`app/prompts/modules/codex-review.md`** — folded into the codex-debate skill. Removed `codex-review` from `modules:` in full-cycle, worker, reviewer; full-cycle body refs now point to the codex-debate skill (Quick Review)

### Added
- **`codex-debate` skill on orchestrator** — `skills: [html-artifacts, vps-deploy, codex-debate]` so the orchestrator can invoke Codex review directly when needed

### Reasoning
Two overlapping Codex prompts (review module + debate skill, both added via separate tasks #43/#46) caused divergence and double maintenance. Consolidated: review is just debate's one-shot mode. Skill > module here because Codex review is invoked on demand (lazy-loaded native skill), not needed in every turn's system prompt.

## v2.16.0 — 2026-06-01

### Fixed
- 🐛 **Zombie workers after restart** — `auto_resume_all` flipped ALL non-idle rows to idle, including archived. Killed workers resurrected every restart. Fix: only flip `running`/`waiting` → `idle`, leave `archived` alone
- 🐛 **Deepgram SSL BAD_RECORD_MAC** — aiohttp 3.13+ defaults trust_env=True → picks up VLESS proxy → TLS record corruption. Fix: explicit trust_env=False + ssl=certifi
- 🐛 **Codex through proxy → Reconnecting 5/5** — Codex CLI inherited HTTPS_PROXY (VPS tunnel) → OpenAI API unreachable. Fix: strip proxy env from codex commands
- 🐛 **User message duplication** — pending bubble not cleaned after SSE delivers real message. Fix: track finalized bubble ref
- 🐛 **send_file silent false-positive** — returned "File sent to TG" on non-JSON TG response. Fix: validate response, explicit error on failure
- 🐛 **Tinyproxy MaxClients exhaustion** — old VPS Tunnel (12338) connections filled Tinyproxy pool. Fix: MaxClients 50→200, Timeout 600→120

### Added
- 🔧 **SSH tunnels in lifespan** — 3 SSH tunnel proxies (Ezhik/Timeweb/Fornex) start/auto-restart from Orchestra lifespan via SSH_TUNNELS env. No separate systemd services needed
- 📋 **Prompt best practices** — Codex bash-primary (not MCP), orchestrator merge/kill safety (worker_wip before kill, cherry-pick on conflict), codex-review module rewritten
- 🔧 **Modular prompts** — `_load_modules()` in manager.py, `modules:` frontmatter key in roles → git-workflow, codex-review, report-format auto-injected
- 📊 **Proxy dashboard** — 4 proxies (Hiddify, Ezhik, Timeweb NL, Fornex NL) configured and benchmarked
- 🔒 **Security** — passwords removed from git history (BFG), .gitignore for sensitive docs + artifacts

### Fixed (11 P2 bugs from review #35 — task #42)
- Reconnect backoff cap (5 failures → give up)
- Hibernate pending messages guard
- GC task protection (`_spawn_bg` for all create_task calls)
- Log retention + WAL checkpoint
- rawMaxTokens from SDK instead of CONTEXT_LIMITS
- ~95 lines dead code removed (backend.py, 3 DB funcs, _react_processing, aliases)

## v2.15.0 — 2026-06-01

### Fixed (13 P1 bugs from review #35 — task #40)
- 🐛 **SDK errors silent (worst bug)** — `_convert` hardcoded `"ok": True`; `ResultMessage.is_error`/`errors`/`permission_denials` and `AssistantMessage.error` never read → auth/billing/rate-limit failures ended the turn as a normal idle, fired auto-report as success. Fix (`backend_claude.py`): `ok = not is_error`, surface `errors` in `turn_end` meta + `AssistantMessage.error` as an `error` event; `permission_denials` logged (informational, does NOT flip `ok`). `session.py _handle_turn_end` logs `turn FAILED` and `_fire_auto_report` skips when `_last_turn_ok` is False
- 🐛 **ThinkingBlock dropped** — extended thinking silently discarded → looked like a hang. Fix: `ThinkingBlock` branch in `_convert` → `"thinking"` event, logged in `_handle_event`
- 🐛 **dead `usage["iterations"]` branch** — SDK never emits `iterations`; the `if iters:` cost loop was dead, `last = iters[-1] if iters else usage` was noise. Fix: deleted, cost from flat usage dict
- 🐛 **billing-derived context_pct wrong** — `_convert` computed ctx% from billing tokens (input+cache) against CONTEXT_LIMITS, overwritten ~1s later by `get_context_usage()` → transient wrong %, spurious "context corrected" jumps. Fix: stopped computing it (meta `context_pct=0`); `_handle_turn_end` keeps prev `_last_context` when incoming is 0; auto-compact triggers on `live_pct` from `_last_context`
- 🐛 **cost under-counts after reconnect/compact** — `total_cost_usd` is cumulative per session_id; on a new session_id it resets smaller → `max(0, new-last)` clamped to 0 → first turn after every compact contributed $0. Fix (`session.py:_handle_turn_end`): reset `_last_cost`/`_last_cost_cached`=0 when `session_id` changes (before the assignment)
- 🐛 **stale prompt on failed inject** — `_template_hash`/`_prompt_injected`/`system_prompt` set BEFORE `backend.send()` → a failed connect left a false "injected" flag, worker ran rest of life on old instructions. Fix: commit inject flags only AFTER `send()` succeeds
- 🐛 **auto-report empty stop_reason** — manager re-read live `worker._turn_logs` for `stop_reason=`, which `_turn_logs` never contains (it holds text/tool only) → always empty. Fix: `_fire_auto_report` captures `_last_stop_reason` at fire time, passes it to `on_idle(... , stop_reason)`; manager dropped the dead scan
- 🐛 **resume drops `waiting` bg-job state** — `auto_resume_all` excluded `waiting` from the resumable filter and flipped it to idle. Fix: capture `was_waiting`, include `waiting` in filter, restore WAITING post-load if `bg_manager.has_active_jobs` (both worker AND orchestrator loops — Codex)
- 🐛 **`_flush_pending` loses batch on error** — `msgs` extracted + cleared, not requeued on send failure. Fix: `_pending_messages[0:0] = msgs` in except
- 🐛 **squash stats first-ref-only** — `_parse_merged_commits` used `.search()` → multi-task squash commit attributed stats only to the first `#N`, co-refs got zero. Fix: `.finditer()`, attribute commit to ALL distinct refs
- 🐛 **`_log`/`_persist` choke the default thread-pool** — shared with git ops (`asyncio.to_thread`) → 10 agents streaming logs starved merge/spawn. Fix: dedicated `_db_executor()` (ThreadPoolExecutor max_workers=4) for DB writes
- 🐛 **blocking git/merge in the event loop** — `_load_from_db` ran `git rev-parse` sync at resume; `/merge` + `/switch-branch` ran `merge_worktree_to_main`/`switch_worktree_branch` (fcntl.flock + ~10 subprocess) SYNCHRONOUSLY in async endpoints → froze the whole loop. Fix: `asyncio.to_thread` for all three
- 🐛 **stream_logs DB connection churn** — `get_logs` opened a fresh `_conn()` (fd + 3 PRAGMAs) every 0.5–2s tick per SSE/TG poller. Fix: `get_logs(conn=...)` optional connection; SSE + TG loops reuse one connection (try/finally close) with adaptive backoff (0.5→3s / 2→5s when idle)
- 🐛 **split-brain DB (tm.py)** — `tm.py` hardcoded its own `DB_PATH`+`_conn()`, ignoring `ORCHESTRA_DB_PATH` → tasks in one file, sessions in another for tests/worktrees. Fix: deleted the dup, `from app.db import _conn` (one path resolution)

**Known tradeoff:** 2 items deferred to separate tasks — #15 (scope-level spawn lock, larger design change) and #17 (persist `_pending_messages` to inbox table, heavy feature for a rare edge).

**Triggered case:** review #35 found 19 P1s; #39 fixed the 7 P0s, this round fixes the P1s. The error-silence bug (#1) was the worst — an autonomous orchestrator can't see a rate-limited/billing-dead worker reporting "done" with empty output.

## v2.14.0 — 2026-06-01

### Fixed (7 P0 bugs from review #35 — task #39)
- 🐛 **compact() re-entry corruption** — no re-entrancy guard + `_compacting` cleared BEFORE the ack send. `_auto_compact()` (ctx>90%) and a manual `compact_worker` could enter `compact()` concurrently, racing on `session_id`/`_backend`/`_listen_task` → `RuntimeError: not connected`, dangling client, or permanent `session_id=None` (full context loss). Fix (`session.py` `compact()`): guard `if self._compacting: return {...}` set synchronously at entry; `_compacting` held True across the ack turn; ack sent via `backend.send()` directly (bypasses `send()`'s pending-queue gate)
- 🐛 **compact 60s blind poll → fabricated success** — `compact()` returned `{"ok": True}` after a 60s sleep-poll regardless of whether the ack turn completed. Fix: `_compact_ack_event` (asyncio.Event) bound to `_compact_ack_gen`; `_handle_turn_end` sets it only for the matching turn gen; `await wait_for(event, 60)` → `{"ok": False, "error": "ack turn did not complete"}` on timeout. A stray `_flush_pending`/heartbeat turn can no longer false-positive the ack (Codex finding #2)
- 🐛 **persist race resurrects stale state** — full-row `save_session(_to_db_dict())` fired from `_handle_turn_end` (438) and `_refresh_context_from_api` (704) on unordered executor threads → a stale `status=running` snapshot could overwrite a fresh `status=idle`. Fix: single-flight persist (`_persist_task` + `_persist_dirty` coalescing in `_persist_loop`). Last snapshot always wins; `get_running_loop()` fails loud off-loop; done-callback logs crashes; in-loop try/except so one DB error doesn't stop future writes
- 🐛 **merge vs remove worktree race** — `merge_worktree_to_main` held `.git/orchestra-merge.lock` but `remove_worktree` took NO lock → removing a worktree mid-merge could abort the merge / leave repo on wrong branch. Fix: `remove_worktree` now acquires the same `fcntl.flock(LOCK_EX)` on `orchestra-merge.lock`
- 🐛 **orphaned worktree on spawn crash** — `create_session` except block only called `delete_session`, leaking the worktree if `start()`/`_inject_skills`/`_safe_format_prompt` raised after creation. Plus `create_worktree` itself leaked if `git worktree add` succeeded but the PROJECT_FILES copy then raised (Codex #4). Fix: rollback inside `create_worktree` (post-add copy wrapped, removes worktree on failure) + `remove_worktree` in the manager except block
- 🐛 **zombie CLI on connect timeout** — `ClaudeBackend.connect()` left `_client` set (subprocess alive) on timeout/exception, never disconnected. `reconnect()` had the identical leak (used by heartbeat/listener recovery), and `except Exception` missed `CancelledError` (Codex #5). Fix: shared `_cleanup_failed_client()`, `except BaseException` → disconnect → re-raise, in both `connect()` and `reconnect()`
- 🐛 **restart_cli → 500** — `/api/sessions/{name}/restart-cli` called `session._disconnect_client()` which doesn't exist (`AttributeError`). Fix: `_disconnect_backend()` + imported `AgentStatus` for `AgentStatus.IDLE`

### Known tradeoff
- **P1-1 (session_id NULL window) fixed as a side-effect** — Codex review (#1) showed the ack turn needs a FRESH SDK session (no resume token) so compaction actually drops context, but the *persisted* `session_id` must NOT be nulled. New `force_fresh` param on `_make_backend`/`_ensure_backend`: ack runs on a fresh session while the old token stays in DB until the ack `turn_end` writes the new one → crash mid-compact now resumes old context instead of losing everything

### Fixed (2nd Codex round — diff review)
- 🐛 **compact COMPACT_PROMPT phase unlocked** — the summary turn (`backend.events()` loop) didn't hold `_lifecycle_lock`, so a `_flush_pending` already past its outer `_compacting` check could interleave a non-ack turn. Fix: wrap the COMPACT_PROMPT phase in `_lifecycle_lock` + recheck `_compacting` INSIDE the flush's lock body (requeues if compact won the race)
- 🐛 **ack-timeout left turn running** — on the 60s ack timeout `compact()` cleared `_compacting` while the ack turn could still be live. Fix: `_disconnect_backend()` + status IDLE before returning, so no stale turn interleaves with the next send
- 🐛 **force_fresh ignored if backend exists** — `_ensure_backend(force_fresh=True)` returned the existing backend. Now disconnects + rebuilds fresh (correctness, not just-happens-to-work in compact)
- 🐛 **spawn cleanup missed CancelledError** — `create_session` except was `except Exception` → cancellation skipped worktree cleanup. Now `except BaseException`

### Reasoning
Full research → plan → Codex review (×1 plan) → implement → Codex review (×1 diff) → fix → tests. Codex found 5 holes in the PLAN + 4 more in the DIFF (1 P0, 3 P1), all incorporated. 17 new tests (`test_session.py`, `test_backend_claude.py`, `test_workspace.py`), 86 passing (6 pre-existing failures on clean HEAD are unrelated — stale `AUTO_REPORT_IDLE_SEC`/`remove` tests). Docs: `docs/tasks/39/{research,plan,findings,codex-diff-review}.md`

## v2.13.0 — 2026-06-01

### Fixed
- 🐛 **[1m] suffix stripped — ALL agents on 200K instead of 1M** — `_make_client()` did `model.replace("[1m]", "")` before passing to CLI. CLI REQUIRES `[1m]` suffix to enable 1M context window (`claude-opus-4-6` = 200K, `claude-opus-4-6[1m]` = 1M). Every [1m] agent in Orchestra silently ran on 1/5 of their context. Fix: pass `self.model` as-is, no stripping
- 🐛 **compact_boundary invisible** — CLI `SystemMessage` with `subtype="compact_boundary"` was not caught by any branch in `_convert()`. Now emits status event "CLI auto-compacted (trigger): pre→post tokens"
- 🐛 **max_tokens from API** — `_refresh_context_from_api()` now updates `max_tokens` from SDK alongside percentage and total_tokens

### Reasoning
CLI changelog 2.1.75: "Added 1M for Opus 4.6 by default for Max plans" — but ONLY when model name includes `[1m]` suffix. Our `_make_client` stripped it → CLI saw `claude-opus-4-6` (200K). Betas approach (`context-1m-2025-08-07`) also doesn't work on subscription ("Custom betas are only available for API key users"). The ONLY way to get 1M on subscription is passing the full model name with `[1m]`.

## v2.12.0 — 2026-05-31

### Fixed
- 🐛 **Phantom context loss** — `context_pct` was reverse-engineered from `ResultMessage.usage` iterations (last iteration tokens / model limit), NOT actual context window size. Replaced with authoritative `get_context_usage()` SDK method. Fixes wildly swinging % after tool-heavy turns
- 🐛 **CLI silent autocompact invisible** — Claude CLI has its OWN internal autocompact that fires independently. We now log when authoritative % diverges >20% from estimate ("context corrected: X% → Y%")
- 🐛 **Compact crash window** — `compact()` NULLed `session_id` and persisted before starting fresh session. Server restart in that window → agent not resumed (auto_resume_all filters NULL). Removed premature persist
- 🐛 **Stale 0% after resume** — `_last_context` not refreshed until first turn_end after reconnect. Now `_refresh_context_from_api()` fires on backend connect
- 🐛 **`_compacting` double-managed** — both `_auto_compact()` and `compact()` set/cleared flag. Now `compact()` is sole owner
- 🐛 **Multiproject scope UNIQUE crash** — `ensure_project()` crashed on UNIQUE(scope) when same agent created tasks in 2+ projects. Now skips scope binding if already bound to different project

### Added
- 🎨 **Role icons from frontmatter** — `icon:` field in role MD files (`app/prompts/roles/*.md`). `/api/role-icons` endpoint serves role→emoji map. Frontend + MCP load dynamically instead of hardcoded maps
- 📁 **New role templates** — `sub-orchestrator.md` (🎯), `reviewer.md` (🔍), `watcher.md` (👁️) with frontmatter + minimal prompts
- ✅ **#34 tg_topic** — `tg_topic` bool parameter for per-agent TG topics. Root orchestrators get `tg_topic=True` automatically. API: `POST /api/sessions/{name}/tg_topic`

### Changed
- `backend_claude.py` — new `context_usage()` method wrapping `ClaudeSDKClient.get_context_usage()`
- `session.py` — `_refresh_context_from_api()` called on turn_end + backend connect; `_auto_compact` simplified to just delegate to `compact()`

### Reasoning
Context bug was a CLUSTER of 5 root causes (RC1-RC5), found by Opus research worker + Codex cross-review. Primary: per-iteration token estimate ≠ actual context window, and CLI internal autocompact runs invisibly. Fix A (authoritative API) + Fix C (no NULL persist) + Fix D (refresh on resume) + Fix E (single flag owner) applied. Full research in `docs/research-context-bug.md`.

## v2.11.0 — 2026-05-31

### Added
- 📁 **Change orchestrator scope/repo_path without losing session** — move an idle orchestrator to a new root folder while preserving its Claude `session_id` (context survives via resume). `POST /api/orchestrators/{name}/change-scope` `{old_scope, new_scope, new_cwd?}` + “Change folder” context-menu item in the dashboard. MVP scope: orchestrator-only, idle-only, no live workers in the old scope
- `db.change_scope()` (`app/db.py`) — single transaction: move `sessions.scope+cwd`, optional `tm_projects.scope` migration (skip on UNIQUE collision), active `bg_jobs.target_scope`, `test_lock.scope`. Gated on `WHERE id=? AND scope=old_scope` → aborts before any migration on a stale/concurrent retry (no partial move)
- `manager.change_orchestrator_scope()` (`app/manager.py`) — guards (orchestrator-only, `is_dir`, no live workers via `_live_workers_in_scope` scanning memory + DB), all under `session._lifecycle_lock` (idle race). Rebuilds `mcp_servers` via `_make_mcp_config` so the lazy reconnect gets the new `ORCHESTRA_SCOPE`; `session.id` (dict key) unchanged

### Changed
- **`_is_safe_path` containment** (`app/main.py`) — replaced `startswith(root)` with `os.path.commonpath` containment. Closes sibling-prefix escape (`/tmproot_escape` no longer passes as inside `/tmp`). Affects ALL path-guarded endpoints, not just change-scope
- **Persist drain fence** (`app/session.py`) — `_persist()` now tracks every `run_in_executor` save future in `_persist_futs` (set, auto-discarded on done); new `_drain_persist()` awaits all pending. change-scope drains in-flight persists after backend disconnect and before the DB transaction, so the transaction is the last writer of `scope+cwd` (prevents a stale `save_session(old_cwd)` clobbering cwd → wrong root after restart)

### Reasoning
`scope` is the orchestrator's identity key (UNIQUE(name,scope)), woven through 5 DB tables, the MCP subprocess env, CWD, and dashboard tabs. The hard part isn't renaming a path — it's keeping the move consistent under concurrent control-plane ops. Three Codex-flagged cross-layer races were closed: stale/partial DB migration, worker-spawn TOCTOU (in-lock re-check; full scope-level spawn lock deferred), and async-persist cwd-clobber (set-based drain). Session context is preserved because `session_id` is independent of scope.

### Known tradeoff
- Worker-spawn TOCTOU is mitigated (in-lock re-check) but not fully closed — a true close needs a scope-level lock shared with the spawn path. Acceptable for the "orchestrator with no live workers" MVP; flagged as follow-up

## v2.10.0 — 2026-05-31

### Added
- 🛡️ **Directory ownership at spawn** — `spawn_worker(..., owned_dirs='["app/api/"]')`. New `owned_dirs TEXT` JSON column in `sessions`. At spawn, overlapping dirs with a live worker (idle/running, same repo) → advisory warning to orchestrator (NOT blocked). Injected into worker prompt as off-limits siblings. `parse_owned_dirs()`/`dirs_overlap()` (prefix-aware) in `workspace.py`
- 🛡️ **Pre-dispatch conflict simulation** — `check_conflict(worker_a, worker_b)` MCP tool + `POST /api/sessions/check-conflict`. `simulate_conflict()` in `workspace.py` dry-runs `git merge-tree --write-tree`, reports conflicting paths (regex-parsed, handles content + modify/delete). Pick merge order before collisions happen
- 🛡️ **Worker WIP visibility** — `worker_wip(name, base_ref)` MCP tool + `GET /api/sessions/{name}/wip`. `branch_wip_status()` shows uncommitted files + unmerged commit subjects before resuming a worker. Returns `{error}` on git failure, never a false "clean"
- 🔒 **Block ScheduleWakeup + Cron\* tools** — removed from all agents via `disallowed_tools`. Orchestra manages scheduling via bg_jobs, agents don't need client-side scheduling

### Changed
- **Safer auto-commit** — `_auto_commit_if_dirty()` (`manager.py`) no longer silently commits dirty source-repo state before spawn. Loud labelled WIP commit (branch + file list), fail-loud on git `status`/`add`/`commit` returncodes, warning surfaced to orchestrator via `spawn_warning`
- **Worker WIP commit prompt** — `worker.md` now mandates descriptive WIP commits (`WIP: #49 — done X, Y; TODO: Z`) instead of bare `WIP`

### Reasoning
Parallel workers in isolated worktrees can silently collide (same files) or bury source-repo work (silent auto-commit). These three advisory tools surface collisions to the orchestrator at decision points (spawn, resume, pre-merge) without blocking — fits the small-team MVP "warn, don't gate" philosophy.

## v2.9.4 — 2026-05-31

### Added
- **Module `codex-review.md`** — single source for Codex review rules: when to call (`exec` for plans, `review` for diffs), `codex_review(target, output, mode)` syntax, iterate-to-consensus, MCP-only (not bash/skill), PROJECT CONTEXT via `context`. Wired into `worker` + `full-cycle` via `modules:`. `app/prompts/modules/codex-review.md`
- **Module `report-format.md`** — single source for report shapes: DONE / WIP-STOPPED / pipeline-gate messages via `send_message`. Wired into `worker` + `full-cycle`. `app/prompts/modules/report-format.md`

### Changed
- **Dedup across roles** — removed inline Codex rules and `<report-format>` block from `worker.md`; replaced inline Codex syntax + DONE format in `full-cycle.md` Phase 2/3 with module references. Roles now carry only role-specific workflow; shared rules live in modules. `app/prompts/roles/worker.md`, `app/prompts/roles/full-cycle.md`

### Reasoning
Follow-up to prompt audit. Codex review + report format were duplicated/divergent across worker and full-cycle (two different DONE formats) → consolidated so the orchestrator parses one shape and Codex usage is consistent.

## v2.9.3 — 2026-05-31

### Changed
- **Git-rule dedup** — removed the `<git>` block from `worker.md` body (duplicated `modules/git-workflow.md`, injected via `modules: [git-workflow]`). The one non-dup behavioral rule ("workers do NOT create/switch branches themselves") moved into the module so it reaches all roles. `app/prompts/roles/worker.md`, `app/prompts/modules/git-workflow.md`
- **AskUserQuestion/Monitor compressed** — two NEVER lines merged into one in `base.md` (both denied via permission hook; kept short in case the model sees the tool). `app/prompts/base.md`

### Added
- **Worker context-limit rule** — `worker.md`: on CONTEXT CRITICAL → finish current sub-task, commit, report progress, do NOT start new sub-tasks. Closes audit gap 5.1
- **Full-cycle gate-idle rule** — `full-cycle.md`: explicit "do NOT self-approve and start implementation before orchestrator approves". Closes audit gap 5.2

### Reasoning
P2 batch from prompt audit (docs/tasks/prompt-audit/). Determinism-focused: dedup keeps git rules single-source (the module), the two new rules close behavioral gaps where Opus might improvise (start new work near context limit / self-approve a plan).

## v2.9.2 — 2026-05-31

### Fixed
- **Stale Codex instruction in worker.md** — `Skill(skill="codex-review")` → `codex_review()` MCP tool. worker.md lagged behind the v2.9.0 migration to the native tool (full-cycle.md already correct) → generic workers asked for Codex review followed the obsolete path. `app/prompts/roles/worker.md`
- **report_bug scope conflict** — base.md said "platform bug only", project CLAUDE.md said "any error". Disambiguated in base.md: `report_bug` = Orchestra platform/MCP/SDK/harness failures; task-code bugs → `docs/tasks/<id>/` + orchestrator message. `app/prompts/base.md`
- **bg_create cron drift** — `<background-jobs>` listed only one-shot types and stated "Jobs are one-shot", but `cron` (recurring, added #26 in v2.9.0) was undocumented for agents. Added `cron` to the list, corrected the blanket one-shot claim. `app/prompts/base.md`

### Changed
- **orchestrator.md `<tools>` trimmed** — removed bare tool signatures that duplicate MCP tool descriptions; kept only non-obvious constraints (must be idle, do-not-retry, debugging-only) and the routing map. ~14 lines saved per orchestrator turn without losing one-path routing. `app/prompts/roles/orchestrator.md`

### Reasoning
Result of prompt audit (docs/tasks/prompt-audit/). Codex cross-review corrected 2 v1 errors (run_in_background IS enforced via permission hook; Agent/Task stripped only for orchestrators, load-bearing for workers) → mass NEVER-rule deletion was cancelled. Calibration: for MVP, determinism > token minimalism. P0 manager.py:391 (orchestrator custom prompt replaces role template) tracked separately as #28 (backend, not in this commit).

## v2.9.1 — 2026-05-31

### Fixed
- 🍒 **merge_worker unrelated histories** — `git merge-base` detects unrelated histories before merge attempt. Falls back to `_cherry_pick_branch()` which replays commits individually via `git cherry-pick --no-commit`. Clean linear history, no fake merge nodes. `workspace.py`

### Changed
- **merge precheck flow** — `git merge-base` check added before `merge-tree --write-tree`. Unrelated histories skip precheck entirely (it would fail anyway) and go straight to cherry-pick strategy
- **Prompt restructuring** — all role prompts migrated to XML tags (`<role>`, `<rules priority="critical">`, `<tools>`, etc). Critical rules deduplicated into `base.md`. English-only prompts
- **Native skills** — skills copied as `worktree/.claude/skills/{name}/SKILL.md` instead of system prompt injection. `_inject_skills_to_worktree()` in `manager.py`
- **Agent role in dashboard** — info panel shows role (worker/orchestrator/full-cycle) in purple
- **Cost precision** — `.toFixed(2)` instead of rounded integer
- **File preview** — Download button + Open in browser button for HTML files

### Added
- 🧠 **Opus 4.8** model option in all frontend model pickers

## v2.9.0 — 2026-05-29

### Added
- 🔁 **Cron agents** (#26) — `bg_create(type="cron", cron_expr="*/5 * * * *")` recurring background jobs. Fires on schedule via `croniter`, survives restart. Non-terminal trigger keeps job `active`. `no_expiry` via `timeout_seconds=0`. `bg_jobs.py`, `db.py`, `mcp_stdio.py`
- 🔌 **MCP per agent** (#24) — `spawn_worker(mcp_servers='{"playwright": {...}}')` attaches custom MCP servers to workers. Persisted in DB (`mcp_servers_custom` column), re-merged on restart. Guards `orchestra` key from override. `manager.py`, `main.py`, `mcp_stdio.py`, `session.py`, `db.py`
- 🛡️ **validate_spawn** (#25) — `can_spawn: [worker, full-cycle]` in role YAML frontmatter. Parent role whitelist enforced in `create_session`. Absent/empty = allow all. `manager.py`, `mcp_stdio.py`
- 🤖 **codex_review MCP tool** — native `codex_review(target, output, mode)` tool. Runs Codex CLI via `bg_create(type="run")`, notifies worker on completion. Replaces bash/skill workaround. `mcp_stdio.py`
- 🎨 **Pretty tool result rendering** — `get_worker_info`, `send_message`, `get_worker_logs` results rendered as styled cards instead of raw JSON. `app.js`
- 🔧 **Skills library** — `app/prompts/skills/` directory with YAML frontmatter. Roles select skills via `skills: [html-artifacts]` in frontmatter. Auto-injected into system prompt via `_load_role_skills()`. `manager.py`
- 📋 **Click-to-copy inline code** — click `<code>` in chat to copy text (like Telegram). URLs/IPs open in new tab instead. Toast notification on copy. `app.js`, `style.css`
- 🔗 **Autolink URLs/IPs** — bare URLs and IP addresses in markdown auto-wrapped in `<a>` tags. DOM walker skips `<a>`, `<pre>`, `<code>`. `app.js`
- 🏷️ **Full-cycle role** — 3-phase pipeline (Research → Plan+Codex → Implement+Codex) with 2 orchestrator approval gates. All artifacts to `docs/tasks/<id>/`. `app/prompts/roles/full-cycle.md`

### Changed
- **codex-review skill removed** — migrated to native `codex_review()` MCP tool. `full-cycle.md` updated to reference MCP tool. `app/prompts/skills/codex-review.md` deleted
- **Reviewer/Watcher roles removed** — vanilla Orchestra ships with orchestrator, worker, full-cycle. Custom roles via constructor

### Fixed
- 🔗 **URL in code copies instead of opening** — clicking URL inside backticks now navigates instead of copying to clipboard. `app.js`

### Known issue
- 🧪 **Pre-existing test failure** — `TestRemoveScope::test_passes_orch_names_to_tg_bridge_when_flag_set` (KeyError 'names'). Unrelated to v2.9 changes

## v2.8.0 — 2026-05-27

### Added
- 🚀 **Deploy script** — `deploy/install.sh root@IP` installs Orchestra on a clean VPS in five minutes: systemd + nginx + `.env` with random credentials. `deploy/`
- 🔐 **Test lock** — global lock for parallel tests. `acquire_test_lock`/`release_test_lock` MCP tools + API + database table (PR #1, Vadim)
- 🌿 **Base branch** — workers branch from any branch, not only `main`. `spawn_worker(base_branch="feature/x")`, `switch_worker_branch(from_ref=)`. Merge into any target (PR #1)
- 📊 **Progress bar** — `update_progress(percent, status)` shows an indigo bar in the agent card and info panels, plus polished rendering in the log feed. `app/static/js/app.js`, `app/session.py`
- 📈 **Usage sparkline** — seven-day chart with weekly navigation (◀ ▶), midnight separators, and splits at resets. Forward-fills data gaps. `app/db.py`, `app/static/js/app.js`
- 💰 **cost_usd_cached** — cost calculation including prompt cache (cache_read×0.1 + cache_create×1.25). `app/backend_claude.py`, `app/session.py`, `app/models.py`
- 🔔 **TG @mention** — `TG_USER_MENTION` environment variable for mentioning the user in agent speech, not agent-to-agent messages. (PR #1)
- 📱 **TG topic collision** — `_pick_unique_topic_name()`: pm-taksa → pm-taksa-2 on collision. Backward compatible. (PR #1)
- 🗑️ **TG topic cleanup** — “Delete TG topics” checkbox in the project deletion modal. (PR #1)
- ⏱️ **Jobs UI** — real-time timer (elapsed + expiry updated every second), click-to-expand details, persistent expanded state
- 💳 **Payment auto-resolve** — `payment_receive` without a client parameter; resolves the client automatically from project scope

### Changed
- **Codex token prices** — corrected from understated ($1.25/$10) to actual ($5/$30 per 1M). `backend_codex.py`
- **TG flood handling** — three-second minimum interval, important/unimportant prioritization, drop tool/status messages during floods. `tg_bridge.py`
- **TG long messages** — `_split_message()` splits into 4,096-character chunks instead of silently truncating
- **Worker prompt** — added `update_progress` to worker instructions

### Fixed
- 🔴 **cost_usd overcounting x85** — CLI returned cumulative cost, which we added as deltas. $24,609 → actual $302. Delta tracking + reconstruction from logs. `session.py`, `db.py`
- 🧟 **Codex zombie detection** — `_codex_turn_loop` did not set IDLE on timeout/error. Heartbeat checked backend=None and skipped. Now: a `finally` block plus zombie check before backend check. `session.py` (#11)
- 💥 **Compact running crash** — event loop accessed a None backend. Guard + disabled frontend button. `session.py`, `app.js` (#12)
- 📝 **report_bug permission denied** — workers wrote directly to a file from their worktree. Now routed through an API endpoint. `mcp_stdio.py`, `main.py` (#13)
- ⚡ **TG icon did not return** — `_handle_turn_end` did not log “turn ended,” so `stream_logs` could not update the icon. `session.py` (#14)
- 🔇 **TG reactions removed** — removed 👍/👂 from every message. `tg_bridge.py`
- 🔓 **Auth on /send** — POST /api/sessions/*/send was accessible without authorization. (PR #1)
- 🤖 **Disallowed sub-agents** — orchestrators spawned Claude sub-agents instead of MCP `spawn_worker`. (PR #1)
- 🗑️ **manager.remove() leak** — did not delete the session from the database, leaving an orphan. (PR #1)
- 🧪 **Test suite revival** — 128 passed, 5 skipped. `conftest.py` mocks, `ORCHESTRA_DB_PATH` isolation. (PR #1)
- 📁 **/tmp allowed** — `send_file` from `/tmp` returned “access denied”
- 🌐 **Global exception handler** — every 500 is now logged with a traceback
- 📊 **5h sparkline** — removed redundant midnight lines (14 over two weeks of data), clipped to the current week

## v2.7.0 — 2026-05-21

### Added
- 🔒 **Dashboard Auth** — cookie-session login/password from `.env` (`DASHBOARD_USER`/`DASHBOARD_PASSWORD`). Deterministic HMAC token survives restarts. 30-day cookie. Backward compatible: no variables means open access. `app/auth.py`, `login.html`
- 🔒 **Security hardening** — full Codex audit, six critical/high fixes: path-traversal deny-list (dotfiles, `.db`, `.key`), internal-token auth for MCP callbacks, upload-extension blocking, `safe_path` on `send_file`/session creation, SSE/log limit caps, rename validation
- 📊 **Task priorities** — 0=critical 🔴, 1=high 🟠, 2=medium 🟡, 3=low 🟢. CSS dots in task panel. Sorted by priority. MCP tools `task_create(priority=)`, `task_update(priority=)`
- 📦 **Worker description** — `description` field on spawn, `update_worker_description()` tool, shown in `list_agents`, info panel, and list_agents bubble
- 🔍 **get_worker_info** — MCP tool returns complete information including system_prompt (500 chars), description, and stats
- ✏️ **update_worker_prompt** — MCP tool updates the worker's system_prompt
- 🗄️ **Archive workers** — `kill_worker` now archives (`status=archived`) instead of deleting. Logs and statistics remain. Archived workers do not block respawn
- 📈 **Session statistics** — `total_turns`, `total_input_tokens`, `total_output_tokens`, `total_tool_calls` tracked per session. `/api/stats` endpoint
- 💰 **Payment journal** — automatic journal task in YouGile. Description updates after every `payment_receive`. Balance + deposits + allocations
- 📂 **File tree auto-refresh** — polls open folders every ten seconds, diff updates without flicker
- 📎 **File drag & drop** — dropping on the textarea uploads the file and inserts its path. Drop hint on dragover
- 🕐 **Message timestamps** — prepend `[HH:MM]` for the LLM; strip in dashboard and TG mirror
- 🔄 **Mid-turn inject restored** — Claude: try inject → fallback queue. Codex: always queue
- 🪞 **Mirror send_file** — files are mirrored to the agent's TG topic
- 📋 **Tab context menu** — right-click a tab to hide/delete it. Wheel scrolling. Hidden-tabs button
- ⚖️ **AGPL-3.0 license** — dual licensing: AGPL + commercial from Seedon LLC
- 🚀 **VPS deployment support** — complete deployment guide, systemd service, nginx config, auth, security audit

### Changed
- **Task prefixes removed** — `PAR-49` → `#49`. Plain numbers, legacy prefixes accepted. `format_task_ref()`, `resolve_task_ref()`, workspace branches `task-N/name`
- **Proxy parametrized** — `HTTPS_PROXY` from `os.environ`, not hard-coded. `cli_path` through `CLAUDE_CLI_PATH` environment variable
- **Merge auto-stash** — `merge_worker` automatically stashes/pops a dirty main repository
- **MCP scope passthrough** — `task_get`/`task_update` pass scope for disambiguation
- **Rename full** — updates system_prompt identity, git branch, and database
- **Compact blocks send()** — messages queue during compaction and arrive afterward
- **Auto in_progress** — `spawn_worker`/`switch_worker_branch` with task_id automatically set `in_progress`
- **bg_jobs cleanup** — triggered/expired/cancelled jobs older than 24 hours are automatically deleted
- **Scope MCP servers** — workers receive MCP configuration from the project's `.mcp.json` (Playwright, etc.)

### Fixed
- 🔴 **Crash loop sr/nt** — `_handle_turn_end` used removed variables, causing a listener reconnect loop
- 🔴 **Compact interrupted** — incoming messages during compaction → empty summary → cascading crash
- 💲 **Double “kk”** — price “8k” + frontend “k” = “8kk”. Backend already formats it
- 🏷️ **Universal prefix strip** — `replace('PAR-','')` → regex `/^[A-Z]+-/` for every prefix
- 🔐 **Internal token for every API** — MCP tools authorize with a Bearer token, not only `/send`
- 🍪 **Cookie auth on /send** — the frontend sent a cookie while middleware checked only the token
- 📋 **Ambiguous task numbers** — scope resolves identical numbers in different projects
- 📂 **Hidden files visible** — removed the `startswith('.')` filter from `/api/files`
- 🖱️ **Text selection restored** — document-level drag listeners prevented selecting text
- 📊 **Sync indicator removed** — useless sync indicator for projects without YouGile
- 🎯 **Task detail modal** — pretty commits display, scope passthrough, informative task_update bubble
- 🔄 **YouGile description sync** — description is pushed in `push_update`; previously only title and column were

## v2.6.0 — 2026-05-14

### Added
- 🔄 **Auto-resume ALL sessions on restart** — `auto_resume_all()` restores orchestrators AND workers from DB (was orchestrators-only). Sessions that were `running` at shutdown get a restart notice injected after 3s: `[system] Orchestra server restarted. Your session was restored — continue where you left off.`
  - `_inject_restart_notice()` in `manager.py` — delayed inject with error handling
  - `auto_resume_orchestrators()` kept as backward-compat wrapper
- 🤝 **Cross-orchestrator awareness** — `_other_orchestrators_block(scope)` dynamically generates a list of all other orchestrators with project names, injected into `ORCHESTRATOR_SYSTEM_PROMPT`. Each orchestrator knows who else exists and can `send_message` them. List updates on restart/compact
- 👤 **TG sender name** — all messages from TG now include `[from TG: Name]` prefix so agents know who's writing. Works for text, photos, files, video, audio, voice, video notes, stickers
- 🔒 **TG polling auto-restart** — `_safe_polling()` wraps `dp.start_polling` with crash recovery (auto-restart after 10s) + logging. No more silent polling deaths
- 📊 **Usage cache persistence** — `data/usage_cache.json` survives server restarts. No more empty usage bar after reboot caused by Anthropic rate limit + cold cache
- 🔀 **merge_worker MCP tool** — orchestrator can merge a worker's branch into main with one call. `git merge-tree` precheck detects conflicts before merging. fcntl lock serializes parallel merges. Auto-commits dirty worktree. `workspace.py`, `mcp_stdio.py`, `main.py`
- 🛑 **stop_worker MCP tool** — interrupt + idle without destroying session/worktree. Resumable via send_message. Separate from kill_worker (full delete)
- 📈 **Worker progress tracking** — `update_progress(percent, status)` MCP tool. Green glow progress bar in sidebar. Resets on new task. `session.py`, `db.py`, `mcp_stdio.py`, `app.js`
- 🖼️ **TG images as photos** — `send_file` auto-detects images (.jpg/.png/.gif/.webp/.bmp) → `send_photo()` for inline preview. `as_document=True` forces file attachment
- 🌿 **Git status in worker cards** — sidebar shows `branch+N 💾N "last commit"` per worker. `GET /api/git-status?scope=` with 10s server cache. Green/yellow/gray coloring
- 💓 **Persistent client heartbeat** — 60s heartbeat detects silent listener death, auto-reconnects with inject notice. Silence warning >300s. Full tracebacks on crash

### Changed
- **Usage cache TTL 120→300s** — backend and frontend polling aligned at 5min to reduce Anthropic API rate limit hits
- **TG logger** — `tg-bridge` logger now has `StreamHandler` + `DEBUG` level, all TG events visible in journalctl
- **SSE disconnect leak** — `stream_session_logs` generator now checks `request.is_disconnected()`, stops on tab close

### Fixed
- 🟢🟡 **TG topic status desynced from frontend** — single source of truth via `_any_running_in_scope(scope)`. When orchestrator finishes turn but workers still running → stays 🟢 (was: immediately 🟡). When ANY worker goes idle → `_notify_scope_idle()` checks scope → flips to 🟡 only when ALL idle
  - `check_scope_idle()` in `tg_bridge.py` — public function called from `session.py` and `stream_logs`
  - `_notify_scope_idle()` in `session.py` — fires on every worker IDLE transition, not just auto-report
- 🟢🟡 **TG topic status on startup** — `_sync_all_topic_statuses()` sets correct 🟢/🟡 on all topics when bridge starts
- 🪞 **TG mirror formatting** — mirror messages now receive `converted` text + `entities` from `md_convert()` (was: raw plain text without formatting). All 3 send paths: text/status, tool, tool_result

## v2.5.0 — 2026-05-11

### Added
- 🚀 **Persistent client + mid-turn message injection** — replaced "fresh client per turn" with persistent client per session. `send()` → `client.query()` directly via SDK stdin transport. No more pending queue, debounce, turn boundary waiting. Messages inject mid-turn as system-reminders
  - `_ensure_client()` — connects once, reuses across turns
  - `_persistent_listen()` — infinite loop over `receive_messages()`, does NOT disconnect on ResultMessage
  - `_disconnect_client()` — clean shutdown helper
  - Auto-reconnect: detects dead listener, retries `query()` on failure
  - Removed: `_pending`, `_debounce_task`, `_turn_task`, `_run_turn()`, `_arm_debounce()`, `_on_debounce()`, `debounce_sec`
- 📊 **Usage status bar** — global bar at top of dashboard. OAuth API (`/api/oauth/usage`) with 120s cache, shows 5h/7d utilization with HSL gradient color (green=under budget, yellow=on track, red=burning fast), reset progress % in parentheses. `/api/usage` endpoint combines Anthropic data + per-agent cost from DB
- 🎯 **Spawn worker bubble** — card with `🚀 Spawning name` + model badge pill (color-coded) + markdown task preview + system prompt + repo path. Single click expands all
- 🌐 **WebSearch result renderer** — bracket-counting JSON parser for Links format, Perplexity markdown with token/cost header, standalone detection when `lastTool` is null. Collapsible (5 lines preview)
- 🔍 **ToolSearch bubble** — `🔍 Loading: query` → `✅ Loaded: ToolName` on result
- 🐛 **report_bug bubble** — `🐛 Bug: title` with collapsible description
- 🖼️ **Base64 image rendering** — tool_results with image data render as `<img>`, not raw base64 text
- 📝 **Textarea resize upward** — drag handle above textarea, pull up to expand (bottom of screen = can't drag down)
- 🔄 **Auto-compact for orchestrators** — removed `not self.is_orchestrator` exclusion, orchestrators auto-compact at >90% context

### Changed
- **`interrupt()`** — uses `client.interrupt()` SDK method instead of asyncio task cancellation
- **`compact()`** — stops listener first (race condition fix), bracket-counted JSON parse, disconnects cleanly
- **Turn timeout** — tracked via `_turn_start` timestamp instead of `asyncio.wait_for()`
- **send_message bubble** — split by lines (5 preview), re-render full on expand. No more mid-word cuts
- **Tool result expand** — line-based preview (was char-based), single element with maxHeight (no gap/separator), universal click-to-expand on all bubble types
- **Model aliases** — `claude-opus-4-6` → `claude-opus-4-6[1m]` auto-resolve
- **Worker custom prompt** — `_safe_format_prompt()` replaces `str.format()`, only substitutes known placeholders. Resume correctly extracts custom portion
- **Load-more tool_result matching** — `_findLastBefore()` constrains querySelector to prepended batch only

### Fixed
- **WebSearch `isEdit` bug** — spawn_worker/WebSearch/ToolSearch bubbles had `dataset.isEdit='1'` which caused tool_result handler to early-return, silently swallowing results
- **WebSearch regex** — replaced fragile regex with bracket-counting parser for Links JSON arrays (handles truncated SDK output, multi-item arrays, special chars)
- **Load-more rendering** — old messages now use `addChatEntry()` with full custom bubbles
- **compact() race condition** — listener paused before iterating `receive_messages()`
- **Persistent client dead process** — `_ensure_client()` checks `_listen_task.done()`, `send()` retries with reconnect on `query()` failure
- **Universal click-to-expand** — audit of all handlers, WebSearch and Read .md fixed (were hint-only)

## v2.4.0 — 2026-05-10

### Added
- 🎤 **TG Voice** — Deepgram Nova-3 voice transcription in the TG bridge
- 📷 **TG Media** — complete support for photos, documents, video, video_note (ffmpeg), audio, stickers, and forwards with captions. File + transcription caches
- 🔄 **TG Debounce** — state machine IDLE→COLLECTING→WAITING_MEDIA. Five-second debounce + 30-second media timeout. Batches messages into one turn
- 📂 **File preview** — clicking a file opens a modal. Markdown renders through marked.js, images through `<img>`, code with horizontal scrolling. `/api/files/content` + `/api/files/raw` endpoints
- ✏️ **Diff view** — Google `diff-match-patch` for character-level inline highlighting. LCS line diff + inline highlighting for similar lines (>40% common). Five-line preview + expand
- 📖 **Read view** — code viewer with shimmer skeleton, five-line preview + expand. Images render as `<img>`
- ✍️ **Write view** — content displayed as a diff, all green
- 📨 **send_message bubble** — `📨 → target` + Markdown preview instead of raw JSON
- 📜 **Prompt viewer** — three sections (📦 Platform / 🎭 Role / ✨ Custom) with actual substituted names
- 📋 **Compact mode** — 📋/📄 toggle in the header. Tools collapse to one line and expand on click
- 🖼 **Images everywhere** — user messages, Read tool, and text images are clickable and open file preview
- 💰 **Sidebar price** — green `$X.XX` beside the model
- 🌐 **WebSearch rendering** — title link + snippet instead of JSON
- 🔧 **Autocommit** — `git add -A && commit "wip:"` before `spawn_worker`. Worktree starts from current code, avoiding conflicts
- ⚡ **Seamless turn** — after ResultMessage, pending input starts a new turn immediately (0 ms instead of 2.5-second debounce)
- 📊 **stop_reason logging** — every turn records `stop_reason=X, num_turns=N`
- 🎼 **Orchestra skill** — `/orchestra` Claude Code skill in `app/skills/orchestra/SKILL.md`
- 🔒 **XSS fixes** — 3 innerHTML→textContent fixes (Codex review)

### Changed
- **max_turns 25→50** — workers are no longer cut off on large tasks
- **kill_worker** — now `DELETE` for complete removal, not `POST /stop`; ghost workers no longer remain
- **Inject removed** — every message enters the pending queue; no losses or duplicates
- **Logs limit 200→5000** — older messages are visible in chat
- **MAX_CHAT_NODES 500→5000** — the DOM no longer truncates history
- **Deepgram Nova-2→Nova-3** — more accurate for Russian at the same price
- **Orchestrator prompt** — mandatory system_prompt for workers (template + examples), file conflict rule, CTO delegation
- **Worker prompt** — bash rules (no polling loops), identity placeholders

### Fixed
- **TG flood control** — retry with backoff instead of falling back to plain text
- **TG error logging** — explains why formatted send fails
- **HTML injection in tool_result** — escape `<>` before innerHTML
- **Paste preview** — preserved and restored when switching agents
- **Markdown everywhere** — user messages and [from:worker] messages all render through marked.js
- **chat-bot border** — `#1e293b`→`rgba(99,102,241,0.1)` (visible)
- **diff-code overflow** — `break-all`→`overflow-wrap: anywhere`
- **Read skeleton** — shimmer placeholder until tool_result arrives
- **Expand hint** — rHint moved; querySelector works
- **Restart without confirm** — removed the confirmation dialog
- **Prompt viewer identity** — actual names instead of the `{worker_name}` placeholder
- **Custom prompt after reboot** — custom section survives hot reload
- **streamBubble on orchestrator change** — reset during switching
- **initFilePanel drag listeners** — guard against accumulation
- **refreshSessions stale scope** — capturedScope check

## v2.3.1 — 2026-05-09

### Added
- 🗜 **compact_worker MCP tool** — orchestrator can compact a worker's context (summary → reset session → continue fresh). Tested: 81%→17%, 56%→16%, 20%→16%
- ⚠️ **Context warning >90%** — platform auto-appends `⚠️ CONTEXT CRITICAL` to worker messages
- 🚫 **AskUserQuestion + run_in_background denied** — blocked via `can_use_tool` deny
- 🔧 **Tool+result merged** — one bubble on frontend, one expandable on TG
- 🎨 **Tool icons** — 🖥 Bash, 📖 Read, 🎼 orchestra, 🔌 MCP
- 📝 **Draft per agent** — unsent text preserved when switching
- 🔗 **URL linkify** — clickable links in tool_result
- 💊 **Status badge** — pill with colored bg on idle/running text

### Fixed
- **compact_worker timeout** — was 30s, compact takes ~40s → empty error → double compact. Now 120s
- **Prompt placeholders** — `{orchestrator_name}` was literal in hot-reload for workers
- **Scroll on switch** — chat now scrolls to bottom when opening agent
- **Timestamps overlap** — inline block instead of absolute positioning

## v2.3.0 — 2026-05-09

### Added
- 📱 **TG Bridge** (`app/tg_bridge.py`) — mirrors orchestrators to Telegram group topics.
  Auto-creates topic per orchestrator, bidirectional messaging, real-time log streaming.
  Separate bot (`@orchestraClaude_bot`), config in `.env` / `data/tg_bridge.json`
- 📬 **Kesha inbox server** (`inbox_server.py` in kesha-tg-bot) — HTTP endpoint :18081,
  Orchestra → Kesha via `notify_kesha` MCP tool → shows in Telegram chat
- 🔄 **Auto-report** — workers that finish without `send_message` get force-reported to
  orchestrator with last 3 text outputs. `[from:worker] [auto-report]` format
- 💉 **Message inject** — messages to RUNNING agents injected via `client.query()` immediately,
  no waiting for turn end. Fallback to pending queue on failure
- 🔥 **Prompt hot-reload** — updated `app/prompts/*.md` injected on first turn after restart.
  `[Orchestra platform note]` tag avoids prompt injection detection
- 📊 **Context tracking** — `input + cache_creation + cache_read` from last iteration,
  per-model limits (Opus 1M, Sonnet 200k), cache hit % in agent info panel
- 📈 **Context bar** — colored progress bar per agent in sidebar (green/yellow/red)
- 🌐 **Cross-project messaging** — `list_orchestrators()` discovers all orchestrators,
  `send_message` fallback searches by name across all scopes (`ensure_loaded_any`)
- 🐛 **report_bug MCP tool** — agents file bugs to `BUGS.md` with timestamp/reporter/scope
- ⟳ **Restart button** — dashboard header, `sudo -n systemctl restart orchestra`
- 💊 **Orchestrator tabs** — pill buttons replace dropdown, recent-first, live status dots
- 🖼 **Image paste** — Ctrl+V upload with md5 dedup, preview under input, render in chat
- ⚡ **Status badges** — `⚡ interrupted`, `⚡ system prompt updated` as centered badges in chat
- 📐 **Shared prompts** — `app/prompts/base.md` + `orchestrator.md` + `worker.md`, shared platform knowledge

### Fixed
- **Stop deleted logs** — `POST /stop` now calls `unload()` (preserves DB), not `remove()` (cascade)
- **Scroll hijack** — `showWaitingIndicator` respects `wasAtBottom`, no re-creation in refresh loop
- **Context 0%** — usage is dict not object (`.get()` not `getattr()`), last iteration not sum
- **Context 227%** — top-level usage sums all API calls, context = last iteration only
- **Trailing slash** — scope normalized with `rstrip("/")` at creation and lookup
- **Ghost workers** — `kill_worker` for DB-only sessions deletes from DB directly
- **MCP not visible** — `.mcp.json` no longer copied to worktrees (was overriding Orchestra MCP);
  `mcp_stdio.py` invoked by absolute path (was failing with `-m` from non-orchestra CWD)
- **SendMessage vs send_message** — prompts explicitly say `mcp__orchestra__send_message`
- **Interrupt stuck** — now awaits task cancellation, drops client, sets IDLE + persist
- **Newlines lost** — tool input via `json.dumps(indent=2)`, `white-space: pre-wrap` on frontend
- **Lost messages** — SSE user_message replaces pending bubble instead of skipping
- **Prompt injection** — `[SYSTEM UPDATE]` tag softened to `[Orchestra platform note]`
- **Repeated prompt inject** — `system_prompt` synced after inject, no more every-turn spam

### Changed
- **spawn_worker scope** — uses orchestrator's ORCHESTRA_SCOPE, not repo_path (workers visible in list_agents)
- **Prompts split** — old `orchestrator_prompt.md` + `worker_prompt.md` → `prompts/base.md` + role-specific
- **SDK 0.1.74** — updated from 0.1.72

## v2.2.0 — 2026-05-05

### Added
- 🗑️ **Delete orchestrator** — `DELETE /api/orchestrators/{name}` removes orchestrator + all
  workers in scope (active sessions, worktrees, DB records). Dashboard button `✕ Delete` with
  confirm dialog. `manager.remove_scope(scope)` handles cleanup.
- 💾 **Remember last orchestrator** — `localStorage` saves `lastOrchScope`/`lastOrchName` on
  switch, restores on page load. No more "always opens first in list".

### Fixed
- **Stop deleted logs (critical)** — `POST /stop` called `manager.remove()` which ran
  `DELETE FROM sessions` → `ON DELETE CASCADE` wiped all logs. Now stop calls `unload()`
  (stops session, removes from memory, preserves DB). Only explicit Delete removes from DB.
  - Triggered case: kesha-tg-bot orchestrator stuck running after interrupt, used stop to
    unstick it → 2318 log entries deleted by cascade. User saw empty chat.
- **Scroll hijack on history read** — three sources of forced scroll-to-bottom:
  1. `showWaitingIndicator()` unconditionally set `scrollTop` — now checks `wasAtBottom`
  2. SSE handler had duplicate scroll check after `addChatEntry` (which already handles it)
  3. `refreshSessions` re-created waiting indicator every 3s (SSE removed it → refresh
     recreated → scroll). Removed re-creation from refresh loop.

## v2.1.0 — 2026-05-04

### Added
- 📡 **SSE realtime logs** — `GET /api/sessions/{name}/stream` replaces polling for chat
- 🏥 **Health check loop** — detects crashed worker tasks every 60s
- 🔌 **Systemd service** — `orchestra.service` with auto-restart and Hiddify proxy
- 🎨 **Smart color picker** — unique color per worker, least-used fallback
- 🏷️ **Auto sender tag** — server adds `[from:name]`, workers send plain text
- 📴 **Offline CSS** — Tailwind/marked/DOMPurify bundled locally

### Fixed
- **Auto-resume crash** — error sessions marked stopped on startup
- **cli_path** — dynamic via `shutil.which("claude")`
- **Worker logs** — filtered (text/tool/error only), no raw dumps
- **tool_result parsing** — unwraps `{"result":"..."}` wrapper
- **Proxy** — `HTTPS_PROXY` set in session.py, manager.py, service file

## v2.0.0 — 2026-05-03

### Changed
- **External stdio MCP server** — MCP tools now run as separate process (`app/mcp_stdio.py`)
  via FastMCP, communicating with Orchestra API over HTTP. Replaces in-process `create_sdk_mcp_server`
  which caused deadlocks (SDK issue #425). External process = no shared event loop = no hang.
- **Simplified session.py** — removed persistent client, locks, _is_connected, _cleanup_client.
  Each turn: create fresh ClaudeSDKClient → connect → query → receive → disconnect (in finally).
  Root cause of ALL hangs was accumulated state in persistent connection.
  Proven: direct SDK test = 5 MCP calls in 17s. Old session.py = hang on 3rd call.
  New session.py = 18 MCP calls in 85s, zero hangs. -328 lines, +166 lines.
- **Worker communication via HTTP** — workers send reports via `curl POST /api/sessions/{name}/send`.
  Orchestrator receives via debounce → new turn. No MCP inject needed.
- **System CLI** — uses system Claude CLI 2.1.126 via `cli_path` instead of bundled 2.1.117

### Added
- 📬 **Worker Inbox** — `inbox` DB table + `GET /api/sessions/{name}/inbox` endpoint.
  `send_to_worker` queues messages in inbox. Real delivery semantics.
- 📋 **Job Registry** — `jobs` DB table + `GET /api/jobs` endpoint + `list_jobs` MCP tool.
  spawn/kill create tracked jobs with status (queued/executing/succeeded/failed).
- ⏱️ **Turn timeout** — 300s hard deadline on `_listen()`, 60s on `connect()`.
  TimeoutError → ERROR status. No more infinite hangs.
- 🔒 **Scoped lookups** — `find_worker(name, scope)`, `find_session_id_by_name(name, scope)`.
- 🧪 **`.mcp.json`** — project-level MCP config for local testing from Claude Code
- `alwaysLoad: true` — MCP tools skip ToolSearch deferral (v2.1.121 feature)

### Removed
- `create_sdk_mcp_server` in-process MCP (deadlock source)
- Persistent client connection in session.py (accumulation source)
- `.env` copy to worktrees (security fix)
- Prompt rule "max 2 MCP calls" (no longer needed)
- SDK monkey-patches (buffer, stdin) — no longer needed

### Fixed
- **Duplicate user_message logs** — send() logs once, _run_turn no longer duplicates
- **Timestamps** always visible in white on dashboard
- **pytest discovery** — testpaths=["tests"], norecursedirs for worktrees

## v1.3.0 — 2026-05-02

### Fixed
- **SDK MCP tool hang — root cause found and workarounds applied** — in-process MCP tool calls
  (`create_sdk_mcp_server`) hung after 2-3 calls per turn. Root cause: SDK `Query._read_messages`
  single read task handles both control_request routing AND bounded message stream (`max_buffer_size=100`).
  When buffer fills, read task blocks on `send()` → control_requests never reach Python MCP handlers → CLI
  waits for control_response forever → deadlock. SDK issue #425 (open, no PR).
  - **SDK patch: buffer 100→10000** — `query.py` monkey-patch, prevents backpressure up to 10000 messages
  - **SDK patch: stdin kept open** — `wait_for_result_and_end_input()` no longer closes stdin when SDK MCP
    servers present. Needed for persistent connections with multiple query() calls
  - **Spawn queue** — `spawn_worker` MCP tool no longer does heavy work (git worktree + session start)
    inside the MCP handler. Jobs enqueued to `asyncio.Queue`, processed by background supervisor task
    with 0.5s delay to let control_response flush first (Codex review finding)
  - **git worktree via to_thread** — `create_worktree()` sync subprocess moved to `asyncio.to_thread()`
    to avoid blocking event loop during MCP response path
  - **Inject removed** — `session.send()` no longer calls `client.query()` inject on RUNNING sessions.
    Messages queue in `_pending`, processed as new turn when session goes IDLE. Inject caused transport
    deadlock (both directions: worker→orch and orch→worker)
  - **Worker HTTP callback** — workers send reports via `curl POST /api/sessions/{name}/send` instead of
    MCP `send_message` inject. Eliminates transport deadlock entirely for worker→orchestrator communication
  - **Async DB writes** — `_log()` and `_persist()` via `run_in_executor()` to avoid blocking event loop
  - **include_partial_messages=False** — reduces stream event volume in SDK bounded buffer
  - **Orchestrator prompt: max 2 MCP calls per response** — prevents hitting CLI tool call limit per turn
  - Triggered case: every test with orchestrator + worker — spawn→list_workers→get_worker_logs chain hung
    on 3rd MCP call every time. Single MCP calls worked fine (5s). Multiple calls = deadlock.

### Changed
- **SDK pinned** — `claude-agent-sdk>=0.1.72` in pyproject.toml. Was unpinned, any `uv sync` could
  break everything. v0.1.72 fixes silent MCP tool result loss (v0.1.70+)

### Added
- **Spawn queue** — `SessionManager.enqueue_worker_spawn()`, `_spawn_worker_loop()` background task
- **Session error callback** — `AgentSession.on_error` + `SessionManager._on_session_error()` moves
  errored sessions from active to archived automatically

## v1.2.0 — 2026-05-01

### Changed
- **Data layer refactor — single source of truth** — `SessionManager` is now the sole data gateway.
  `manager.archived: dict[str, dict]` holds stopped/error sessions in memory. `list_sessions()` reads
  purely from memory (active + archived), zero DB merges. `stop()` moves session from active → archived.
  `tools.py` has zero direct DB imports (except `get_logs`). `main.py` reduced from 4 DB fallback paths to 0.
  - `load_archived()` at startup populates archived dict from DB
  - `find_worker()`, `find_session_id_by_name()`, `archive_by_id()`, `get_session_id()` — new manager methods
  - `ensure_loaded()` skips archived sessions (no zombie resurrections)
  - `kill_worker` for DB-only sessions now properly archives via `archive_by_id()`
  - 10 new TDD tests for archived dict behavior (107 total)
  - **Before**: 8 code paths with direct DB access scattered across tools.py + main.py, different formats (AgentSession vs dict), merge logic, fallback reconnects
  - **After**: manager = memory cache, DB = write-through backup + logs storage. One path, one format

## v1.1.0 — 2026-05-01

### Added
- 📡 **Streaming text** — responses appear live as chunks, not after full generation. `StreamEvent` + `content_block_delta` handling
- 📎 **Tool results visible** — MCP tool outputs (`ToolResultBlock`) shown in chat with 📎 prefix
- 🪦 **Agent archive** — stopped/killed workers get hash suffix (e.g. `worker-1-abc123`), move to archive section. Name freed for reuse. Chat history preserved, read-only
- 🏷️ **Model registry** — `app/models.py` single source of truth. Aliases resolved (`sonnet` → `claude-sonnet-4-6`). API validates, dropdown loads from `/api/models`
- 🔄 **restart_worker** MCP tool — kill + respawn in one call
- 📊 **Context display** — `5% (12k/200k)` format, cached on agent switch

### Fixed
- **Worktree preserved on stop** — `stop()` no longer deletes worktree. Only explicit `kill/remove` does
- **Auto-resume rehydrate** — all fields restored from DB (worktree_path, branch, created_at)
- **`_run_turn()` exceptions** — done callback logs errors, sets ERROR status
- **Error UX** — no "waiting for response" after 404/error. Debounce cancelled on failure
- **Stopped agent resume** — writing to stopped agent auto-resumes it (fallback cwd if worktree missing)
- **Duplicate names** — stopped agents archived with hash, name freed for new workers
- **`list_workers`** — shows active + archived workers

### Changed
- `shutdown_all` — orchestrators stay `idle` (not stopped) for auto-resume. Workers get stopped with worktrees intact

## v1.0.0 — 2026-04-30

Complete rewrite from MVP v0.4. One class, one way, Apple-level simplicity.

### Added
- 🏗️ **`AgentSession`** — single SDK wrapper replacing both `Worker` and `Orchestrator` classes. One class for all agents, config-driven (model, system_prompt, mcp_servers)
- 🌿 **`workspace.py`** — isolated worktree management. Scope-namespaced paths (`worktrees/{scope_slug}/{name}`), fail loud, no silent fallbacks
- 🔧 **MCP tools for orchestrator** — `spawn_worker`, `send_to_worker`, `list_workers`, `get_worker_logs`, `kill_worker`. Orchestrator manages workers natively via MCP, not prompt hacking
- 🔧 **MCP tools for workers** — `send_message` (to any agent), `list_agents`. Workers can communicate with orchestrator and each other
- 📝 **System prompts** — `orchestrator_prompt.md` and `worker_prompt.md` in `app/`. Editable .md files, not hardcoded strings
- 🖥️ **Dashboard v2** — single-screen UI: chat with any agent (left), agent list + info (right). Click to switch between orchestrator and workers. Markdown rendering, debounce indicator, adaptive polling (500ms when waiting, 3s idle)
- 📊 **Message debounce** — multiple rapid messages batched into one (2s window, like Kesha). Visual ring timer on pending messages
- 💉 **Live inject** — messages sent while agent is RUNNING inject directly into current turn (no queue, no "session busy")
- 🧪 **97 TDD tests** — `test_db.py` (29), `test_workspace.py` (16), `test_session.py` (18), `test_manager.py` (14), `test_api.py` (20). Written before code (RED→GREEN)
- 🔑 **UUID primary keys** — `UNIQUE(name, scope)` for display, UUID internally. No collisions between scopes
- 📡 **Multi-orchestrator support** — one dashboard, multiple orchestrators (one per project). Picker in header, scope filtering
- 🔄 **Auto-resume** — orchestrators survive server restart (status stays `idle`, SDK resumes via `session_id`)
- 🛡️ **Permission fix** — `default` + `can_use_tool` auto-approve instead of `bypassPermissions` (known regression: Claude Code #36497, #37157, #36923)

### Removed
- `worker.py` — replaced by `AgentSession` in `session.py`
- `orchestrator.py` — replaced by `AgentSession` in `session.py`
- `callbacks` table — replaced by session logs with `type="notification"`
- 18 API endpoints → 9 (one resource `/api/sessions`)
- `max_turns` parameter — SDK manages this
- `data/orchestrator_session` file — session_id now in SQLite
- Separate notifications tab — everything in chat

### Changed
- **DB schema** — `sessions` + `logs` (was `workers` + `logs` + `callbacks`). UPSERT, CASCADE, `busy_timeout=5000`, `foreign_keys=ON`
- **API** — one resource `/api/sessions`. Pydantic validation, proper HTTP status codes (404/409/422), no `{"ok": false}`
- **Dashboard** — HTML/CSS/JS split into separate files. DOM API rendering (no innerHTML XSS). Cursor-based log pagination

### Architecture
```
app/
  main.py            — FastAPI, 9 endpoints
  session.py         — AgentSession (single SDK wrapper)
  manager.py         — SessionManager (registry + lifecycle)
  workspace.py       — git worktree create/remove
  db.py              — SQLite (sessions + logs)
  tools.py           — MCP tools for orchestrator + workers
  orchestrator_prompt.md
  worker_prompt.md
  static/css/style.css
  static/js/app.js
  templates/dashboard.html
```

### Process
- 4-round Codex (GPT-5.5) adversarial review of spec before implementation
- TDD for all modules: tests written first, then minimal code
- Codex code review (Round 5) caught 4 real bugs post-implementation

# V-1163 — Terra rollout preflight

Current owner decision applies to **all** managed orchestrators. The first draft incorrectly used the 22 Claude→Sol rows from V-1141 and inferred seven exclusions from that earlier operation; that historical cohort does not bound this rollout. The corrected dry-run discovers each machine’s full current `/api/orchestrators` inventory and verifies `is_orchestrator`, role and identity against its own read-only SQLite DB. VPS: 10/10 rows are managed `orchestrator`; laptop: 19/19. All 29 are included, including the prior Sol and other-model selections. Nothing is excluded as a manual exception: the current owner rule has no exception list, and the live API has no separate exception field. Existing model differences alone are not treated as exceptions.

No model-change POST, provider request, config edit, restart, interrupt, compaction, or message send occurred. The only API calls were GET `/api/orchestrators` and GET `/api/models` against each live host; DB access used SQLite `mode=ro`.

## Current preflight

Both hosts returned HTTP 200 for both GET endpoints. `gpt-6.1-terra` is absent from both live `/api/models` responses, so every row is blocked. The current source and the unaccepted Terra catalog branch also do not yet declare an explicit Terra→High effort entry for the orchestrator role. Current fallback `default: high` resolves High in the local code, but the owner rule requires an explicit High manifest entry because Codex’s Terra default is low. `terra_rollout.py` checks every active pipeline role whose kind is `orchestrator` for the exact `gpt-6.1-terra: high` mapping; current result is false on both hosts. The orchestrator role’s configured default model is still Opus in the inspected source and Terra branch, so the later source rollout must update that default as well if newly created orchestrators are to inherit Terra.

The current table has 29 rows: VPS has 10 (7 idle, 3 running); laptop has 19 (all idle). Two VPS running sessions have three pending mailbox messages between them; no nonterminal `message_deliveries` rows were found. Existing mailbox/delivery rows are read-only counted; no queue state was changed. The route remains the final concurrency guard: it takes the session lifecycle lock and refuses a running turn or compaction; Codex in-place retarget refuses a settling turn and verifies the native session ID remains unchanged, rolling back if persistence fails. The script blocks anything not exactly `idle`, and records delivery integrity before calling the route. A change racing after preflight is still subject to those existing API guards.

There is one live VPS orchestrator on the harness runtime. Changing its runtime through the supported owner model-change API starts a new native session and transfers the recent chat tail (`chat_history_v1`, at most 100 messages). Older native-only context is not guaranteed to transfer. This is the existing runtime-change contract, not a reason to omit this managed orchestrator or add a new readiness receipt; its actual handoff remains guarded by the API. Same-runtime Codex switches preserve the native session ID. Queued deliveries are retained by existing durable delivery code; the script neither consumes nor cancels them.

Stored effort is `high` for 9 VPS rows and 12 laptop rows; seven laptop rows store an empty effort. The active manifest must explicitly set Terra to High for orchestrator role before any apply. At the next turn boundary, the session reads the role manifest; Codex receives the resolved effort in `turn/start.effort`. The script checks the live host manifest’s exact Terra entry instead of treating an empty DB field or provider default as High.

### Per-session table

Ordinals are assigned by stable session ID order but do not expose identifiers or names. Every proposed value is `gpt-6.1-terra` / `High`. All rows are blocked by the missing live Terra catalog and missing explicit Terra→High manifest. The VPS running rows also show their independent active-turn/queue blockers.

| Machine/session | Is orch | Runtime | Current model | Effort | Status | Readiness | Proposed model | Proposed effort | Blocked reason |
|---|---:|---|---|---|---|---|---|---|---|
| VPS/1 | yes | harness | deepseek/deepseek-v4.1-flash-1017 | medium | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| VPS/2 | yes | codex | gpt-6.1-sol | high | running | blocked | Terra | High | live Terra absent; explicit manifest entry absent; active turn |
| VPS/3 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| VPS/4 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| VPS/5 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| VPS/6 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| VPS/7 | yes | codex | gpt-6.1-sol | high | running | blocked | Terra | High | live Terra absent; explicit manifest entry absent; active turn and queued delivery |
| VPS/8 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| VPS/9 | yes | codex | gpt-6.1-sol | high | running | blocked | Terra | High | live Terra absent; explicit manifest entry absent; active turn and queued delivery |
| VPS/10 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/1 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/2 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/3 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/4 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/5 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/6 | yes | codex | gpt-6.1-sol | unset | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/7 | yes | codex | gpt-6.1-sol | unset | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/8 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/9 | yes | codex | gpt-6.1-sol | unset | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/10 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/11 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/12 | yes | codex | gpt-6.1-sol | unset | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/13 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/14 | yes | codex | gpt-6.1-sol | unset | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/15 | yes | codex | gpt-6.1-sol | unset | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/16 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/17 | yes | codex | gpt-6.1-sol | unset | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/18 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |
| Laptop/19 | yes | codex | gpt-6.1-sol | high | idle | blocked | Terra | High | live Terra absent; explicit manifest entry absent |

No rows were excluded. If a future `/api/orchestrators` row fails live role proof, the script lists it as excluded with the specific role-proof reason and never posts to it.

## Rollout script and contracts

Dry-run is the default:

```bash
uv run --frozen python .orchestra/tasks/V-1163/terra_rollout.py --machine both
```

After the parent’s later apply instruction and live catalog/manifest checks, the same idempotent script uses:

```bash
uv run --frozen python .orchestra/tasks/V-1163/terra_rollout.py --machine both --apply
```

The only model write is the existing owner API `POST /api/sessions/{name}/change-model`, with exact body `{"scope": <live scope>, "model": "gpt-6.1-terra", "via": "dashboard"}`. The route requires `MODELS` registration plus dashboard visibility and runs `ensure_loaded` then `AgentSession.change_model`; no direct DB model update is used. The task-local script checks the full managed-orchestrator inventory against API and SQLite, live model registration, explicit High manifest, `idle`/`waiting` boundary and queued delivery counts. It re-reads before each API call, verifies the resulting model, preserves concrete API refusal details and suppresses blind replay of a refused target; repeat success reports already-target as a no-op. It does not touch quota, role, ownership, provider credentials, workers or manual provider settings. The laptop path uses the existing reverse SSH route with `nice -n 15`; no key, CLI, service or laptop configuration changes are made.

## Evidence and checks

Private read-only snapshots (names, identifiers, scopes and SSH inventory) are stored with mode 0600 under `.orchestra/private/V-1163/`; dry-run refreshes `vps-preflight.json` and `laptop-preflight.json`. No private identifiers, raw tokens or laptop host details are included in this report or stdout.

Reading order: `app/routes/sessions.py` (owner API auth/model visibility) → `app/session.py` (lifecycle lock, busy/compaction/settling guards, runtime handoff) → `app/backend_codex.py`/`app/runtime_registry.py` (native retarget and stable same-runtime session) → `.orchestra/pipelines/default/pipeline.yaml`/`app/pipeline.py` (explicit High) → `app/models.py` and live GET `/api/models` (registry).

Checks: syntax compile passed; live two-host dry-run returned 29 managed orchestrators, zero exclusions and 29 blocked rows; role, `is_orchestrator`, model and session identity matched read-only SQLite; all GETs returned 200. Current model catalog lacked Terra on both hosts; active pipeline lacked explicit Terra→High on both. Three VPS sessions were running and two had queued/nonterminal deliveries; these were not touched. No CLI/model-list probe, inference, tests, or POST was run. `git diff --check` passed.

The original 31-Oct dry-run found Terra absent on both hosts. Parent later reported that the VPS has been restarted and `/api/models` now contains exact `gpt-6.1-terra`/Codex, with `/` returning 302. This is parent-supplied evidence; I have not queried or restarted the VPS. The V-1156 explicit Terra High source passed the bounded VPS host-acceptance checks below; the root retains source acceptance/merge and the apply gate. No model POST was executed. No new native-context receipt or per-target fit gate is part of this rollout.

## Authorized laptop restart follow-up

The new owner command authorized updating the laptop checkout and restarting only its Orchestra process. I read the current `laptop-access` and project `vps-deploy` instructions. The deployment skill requires identifying the live checkout/process and doing `origin` fast-forward only; the owner command specifically permits the API restart and exact laptop scope. The task branch still matches the specified `origin/main` source commit `a215e0ea0ead690283d76ad0b28e4f28ca46a845`; no laptop checkout state was inferred from that fact.

The current reverse-tunnel check `ss -ltnH 'sport = :2222'` succeeded with empty output, and the one-shot SSH command returned `Connection refused`. A `bg_list` check found no active watcher for this listener; exactly one durable command watcher was created: `bg-4e26109f3c`, `ss -ltnH 'sport = :2222'`, pattern `^LISTEN `, 60-second interval, no expiry, targeted to this worker. It wakes only on a nonempty LISTEN row; it does not message the parent each interval. Thus I could not inspect the laptop's configured service user, running PID/cwd, checkout `HEAD`/worktree/remotes, or current API registry. The saved laptop snapshot from 2026-10-31 14:47 UTC is stale and was not used as current evidence. No laptop fetch, merge, API POST, process signal, restart, model change, or external provider request occurred. Private blocker receipt: `.orchestra/private/V-1163/laptop-blocker.json`.

On watcher wake, first make fresh SSH checks for the laptop service/checkout and call live `/api/models`. If Terra is absent, verify the current fetched `origin/main` contains the safe catalog ancestor `a215e0ea0ead690283d76ad0b28e4f28ca46a845`, confirm the checkout is clean and fast-forwardable as user `maxim`, fast-forward only to that exact ancestor, and restart the laptop Orchestra once. Verify new PID, root 302, live Terra/Codex registration, startup restoration and cut receipt. Only after Terra is live in that process may the clean checkout fast-forward to fetched `origin/main` with the explicit Terra→High manifest. If live Terra already exists, do not repeat a restart already performed by the owner/other side. Any dirty/non-FF/ancestry mismatch blocks writes. No Terra model POST until root supplies the apply gate. Do not make another SSH connection before the existing watcher triggers.

For the parent’s review, the selected source commit contains `POST /api/restart`. Source inspection shows it closes mutating admission, drains durable session state, records `cut_names`/`cut_ids` and `restore_after_restart` before signaling, then signals only after the HTTP response flush. Startup calls `auto_resume_all`, recovers initial and message deliveries, restores background jobs, and schedules restart-inbox draining. This verifies the current code path, not the inaccessible laptop's running binary. The local endpoint was not called. After tunnel recovery, live service/checkout identity and clean fast-forward checks must precede any laptop action; ambiguous restart submission must be resolved from PID/journal/receipt before any further signal.

## VPS host acceptance of V-1156 source

The exact author HEAD `5e56e22f18db8cdea5de822f75ad3e30be15c73e` was checked in its clean, kesha-owned host worktree. The running Orchestra service was configured as `kesha`, PID `3648960`, cwd `/home/kesha/orchestra`; this test worktree used its existing `.venv` and locked `uv 0.11.28`, with offline/no-sync mode. Imported `app` resolved to the task worktree. No service restart or catalog model/API call occurred.

The six focused committed test files (`test_orchestrator_terra_manifest_v1156`, `test_orchestrator_defaults_v1156`, `test_default_pipeline`, `test_local_luna_route`, `test_model_gates`, `test_instruction_contract`) finished **113 passed, 0 failed, 0 skipped** in 6.76 seconds. The direct `scripts/check_instruction_contract.py` invocation returned **0**: AGENTS is 16,349 bytes; CLAUDE is an exact symlink to AGENTS; `.orchestra/rules-model-defaults.md` exists and is indexed. Thus no instruction shape repair was needed.

Two isolated mutations used temporary pipeline copies and the committed `test_orchestrator_terra_manifest_v1156.py`: changing both orchestrator models Terra→Sol yielded **3 failed / 8 passed** including the intended default model/API assertions; changing explicit Terra effort High→Low yielded **2 failed / 9 passed** at the intended High assertions. Baseline in each isolated run was 11 passed. SHA-256 for the repository pipeline remained `4ba444771a5fa8decc59d3b138d9bb2e7d57dec60b877848360a3a5ce709f223` before and after; the author worktree stayed clean. Detailed mode-0600 receipts/logs are in `.orchestra/private/V-1163/vps-host-acceptance.json` and sibling `host-acceptance.log`, `instruction-contract.log`, `mutation-*.log`, `mutation-receipt.json`.

The full 7k suite and provider/inference calls were not run. Source HEAD remains in the author worktree pending the root's merge/host receipt decision; no product source was modified here. No model POST or default YAML hot activation occurred during these source acceptance checks.

## VPS rollout under parent apply gate

Parent authorized the VPS owner API rollout. Current live inventory is all 10 managed orchestrators, no exclusions. Nine have changed to Terra; one (ordinal VPS/9) remains Sol while it is running. It currently has no queued mailbox or nonterminal delivery. The task-local readiness watcher `bg-14b96a6ef5` wakes this worker when any unblocked non-Terra target reaches an `idle`/`waiting` boundary with empty queues, or an authorized context-refused target is safe for its one compact attempt. It excludes previously compact-refused targets from API replay until compact succeeds and records resolution.

The first pass changed seven; three active sessions were deferred. Three model-change calls then returned the existing API's HTTP 409 `target context cannot fit the native codex session`. Parent authorized native Codex compaction for these exact three IDs. All three compactions completed once, returned HTTP 200, preserved the same native session ID and reduced their current context below Terra's 258400 window: 295559→129717, 443051→132925, and 462378→161069 tokens. For the first two, queues stayed empty and the owner model API subsequently changed them in place, with `native session preserved` status logs. Compaction on the third target finished while one mailbox message was pending; that message remains durably queued and the target is currently running it. No model POST was sent after the third compact while that turn/queue is active.

For the first two 409s, the rollout log retained only the exact refusal text, not the complete response JSON; this limitation is recorded, and no refusal was replayed to recover it. The third refusal has its full JSON body in the private receipt. Fresh precompact snapshots capture each target's native ID, total context tokens, Terra window, status and queue counts privately.

Eight same-runtime Codex changes have status evidence `native session preserved`; both compacted targets have native-ID equality before/after compact and after the in-place model change. One prior harness→Codex change correctly used `chat_history_v1`, resetting its native session and transferring the supported bounded recent history. Current inventory has nine Terra with stored effort `high` and one Terra (the former harness session) with stored effort `medium`; it has no current native Codex session yet. The live default manifest resolves Terra to explicit High for both orchestrator roles, so its next turn will construct Codex with High through `_apply_manifest_effort`. No extra message or model-generation turn was sent to force that transition.

The latest VPS inventory is 10/10 managed orchestrators, 9 Terra and one Sol; the Sol target is running with one pending mailbox message and zero nonterminal delivery rows. The one Terra session that came from the harness route has stored effort `medium` until a real next-turn manifest boundary; the manifest resolver supplies High to its next Codex backend. I did not send a prompt or model-generation turn to force this refresh. Private evidence: `.orchestra/private/V-1163/vps-apply-pass1.tsv`, `vps-apply-pass2.tsv`, `vps-apply-pass3.tsv`, `vps-apply-after-compact-1.tsv`, `vps-apply-after-compact-2.tsv`, `vps-post-compact-postflight.tsv`, `vps-after-apply.json`, `vps-final-live.tsv`, `vps-api-refusals.json`, `vps-context-precompact.json`, `vps-native-compact-1.json` through `vps-native-compact-3.json`, and compact run logs. All remain local with mode 0600.

## Status update — 1 Nov 2026

This section supersedes the earlier current-state paragraphs above.

The laptop tunnel became available. The clean laptop checkout had one local-only commit removing `rule-a5085d8acb`; that temporary rule had expired on 24 Oct, and the permanent `hubsol` default is in `model-routing.md`. I merged the pinned safe catalog commit, resolving the sole `temp-rules.yaml` conflict to the safe side so both currently active rules were retained and the expired local removal remained. The laptop service was active before the merge and the checkout stayed clean. The single authorized `/api/restart` returned HTTP 200 with `scheduled=true`, `cut_turns=0`, and `cut_names=[]`. After startup, the service had a new PID, dashboard root returned 200, and live `/api/models` exposed exactly one Terra/Codex entry. All 73 pre-restart session IDs remained; there were no pending mailbox or delivery rows before or after. Startup completed and logged `bg_jobs: restored 0 jobs, expired 0`; the post-start background-job API listed zero jobs. No cut session needed resumption. The startup journal also contains seven `Failed to resume worker` entries for ordinary worker sessions whose status was `idle` both before and after; none was named in `cut_names`. Their reported reason was `ORCHESTRA_LAYOUT_MISSING`; these were not changed or messaged as part of this task. Raw startup journal: `.orchestra/private/V-1163/laptop-current-startup-journal.txt`.

After catalog registration, I fetched only `origin` and previewed the merge tree against current `origin/main`; it was clean. A normal merge preserved the laptop-local commit. The checkout is clean at the fetched origin tip plus the local merge; disk pipeline manifest has explicit Terra High for both orchestrator roles. A read-only rollout dry-run found all 19 managed laptop orchestrators ready, with no exclusions. No laptop model POST was sent because the parent apply gate has not been issued. The running process was not restarted a second time.

On the VPS, the one additional authorized compact for the third actual context refusal completed once: native ID preserved, 158990 tokens versus Terra's 258400 window, and queues empty. One supported owner API model change then succeeded. Fresh full inventory shows 10/10 Terra, no exclusions; nine sessions store High and the harness-origin orchestrator stores Medium. The latter has no native session ID or current backend, so a next-turn backend has not yet been observed. On the live source, `resolve_effort` resolves the orchestrator role's exact Terra/Codex route to High; `_apply_manifest_effort` applies the manifest value at a turn boundary, `_make_backend` passes `self.effort`, and the Codex runtime maps it to `reasoning_effort`. No model-generation turn was forced; actual next-backend application remains unverified until that orchestrator naturally begins a turn.

Private receipts and topology/preflight evidence (mode 0600) are under `.orchestra/private/V-1163/`, including `laptop-git-topology.json`, `laptop-candidate-merge-trees.json`, `laptop-restart-attempt.json`, `laptop-pre-restart.json`, `laptop-post-restart.json`, `laptop-stage2-merge-tree.txt`, `vps-native-compact-4.json`, `vps-context-precompact-4.json`, and `vps-target3-current-context.json`. No inference/provider generation was used at that checkpoint.

## Final apply — 1 Nov 2026

The parent opened the laptop apply gate. The fresh full preflight showed all 19 laptop targets ready: live Terra/Codex registry, explicit High manifest for both orchestrator roles, API/SQLite identity agreement, idle status, and empty queues. One task-local apply run reported `changed` for each of the 19 owner API calls. A fresh post-apply full snapshot confirmed 19/19 laptop and 10/10 VPS orchestrators on Terra, no exclusions, and live model registration on both hosts. No model API retry, compaction, or additional restart occurred.

The 19 laptop native session IDs matched their saved post-restart values exactly; no IDs were lost or replaced. The laptop’s stored effort fields are 12 High and 7 unset after migration; the VPS has 9 High and one Medium. The live pipeline resolver returns High for both `orchestrator` and `sub-orchestrator` with Terra/Codex. The existing turn-boundary path applies this value before backend construction, passes it into `BackendBuildContext`, and `runtime_registry` maps it to Codex `reasoning_effort`. No inference was triggered to inspect a backend. VPS/1 remains Medium in stored state with no native thread/current Codex backend; its actual next backend effort remains unobserved until a natural turn. The seven laptop `ORCHESTRA_LAYOUT_MISSING` startup warnings are enumerated privately in `laptop-startup-resume-errors.json`; all seven were ordinary worker sessions idle before and after the restart, and none was in `cut_names`.

The rollout script reports each laptop API result as `changed`; the API’s raw per-target JSON bodies were not retained by that existing script. `.orchestra/private/V-1163/laptop-apply-outcomes.json` preserves each target’s ID, scope/name, reported result, and native ID before/after, with that raw-body limitation explicit. Final full snapshots are `.orchestra/private/V-1163/vps-preflight.json` and `laptop-preflight.json`. No tests were run in this final phase; live read-only verification, receipt reconciliation, resolver execution, and `git diff --check` were performed.

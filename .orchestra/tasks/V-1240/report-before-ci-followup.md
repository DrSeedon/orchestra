# V-1240 — DONE (accepted product at exact06f3; final test-only delta)

All hub worker routes now require `hubsol` / `hub-gpt-6.1-sol` through the existing routing-policy owner in `app/models.py`. Non-Sol hub requests fail with actionable `hub_workers_require_sol`, regardless of scope, alias/direct/versioned ID, old enabled catalog flags, creative/research reason or billing request. No model migration/reset, replay or latch clearing is performed on refusal.

Owner authority: 2026-11-02 17:27 UTC / 2026-11-03 00:27 KRS, clarified 17:29 UTC. The permanent English decision and reason are recorded in the canonical `model-routing.md`; earlier creative-Claude permission is superseded. No model review/refuter was run.

## Final acceptance follow-up: test-only delta

Orchestra-orchestrator accepted the product after reading the independent V-1243 host evidence on **exact06f3**: **1153 passed, 4 browser tests deselected**; instruction contract, three Git-dependent checks and pipeline check **PASS**. Independent committed-test mutation: **22 intended reds**, **16 positive passes**, then **38 restored passes**. These are host results relayed by the orchestrator, not runs performed in this copy or on the later test-only delta. They resolve the earlier copy-only acceptance blockers recorded below.

The final delta removes exactly **3 assertion lines** from **2 test files**: literal quota-hint wording checks in `tests/test_manager.py` and the alert wording predicate in `tests/test_hub_model_reason_frontend.py`. No replacement wording anchors were added. Notice delivery/recipient and queued-message evidence, forbidden-selection nulls, alert count, allowed Sol/native selections, reason escaping, stable `hub_workers_require_sol` error-code checks and every admission/provider-zero/queue guard remain.

Focused affected behavior checks: **3 passed in 4.94 s**, with broker uv 0.11.28, frozen lock, default .venv, NOTIFY_SOCKET unset, offline fakes/Node and serial nice=10/oom_score_adj=1000. Exact nodes: `TestCreateSession::test_quota_block_notice_targets_exact_parent`, `TestCreateSession::test_quota_block_notice_falls_back_when_exact_parent_missing`, and `test_reason_stays_in_info_only_and_non_sol_selection_is_refused`. See `raw/test-only-delta.log`. No broad suite, mutation, live call or model review was repeated.

**Product equivalence: 13/13 production/manifest/routing/CHANGELOG hashes are unchanged** against the supplied source manifest attributed to06f3 by the orchestrator. `source-hashes-06f3.sha256` retains that baseline; `source-hashes.sha256` updates only the two test hashes. `test-only-delta.patch` records +0/-3; `product-equivalence.json` records exact before/after test hashes and unchanged product hashes. Public artifact scanning excludes private raw and finds no foreign host/user paths or secret-shaped values; prior raw files remain byte-for-byte intact.

**Final source HEAD is assigned by the broker after this turn imports the delta** onto `task-V-1240/enforce-hub-sol`. This copy still has no .git, so a new commit SHA cannot truthfully be emitted before that receipt. Root must read and retain the broker's final HEAD;06f3 remains the accepted product/host-evidence baseline, not a fabricated final test-delta HEAD.

## Original implementation change inventory

`changed-files.json` lists all 27 original implementation source/documentation/test paths; `source-hashes.sha256` pins their final bytes. The deliberately Git-free copy cannot produce a Git diff or HEAD/clean-status proof. The platform owns import and commit on `task-V-1240/enforce-hub-sol`; root must review its resulting Git diff/HEAD. No git commit/push/clone was attempted.

| Files | Behavioral diff |
|---|---|
| `app/models.py` | Shared pure `ensure_hub_worker_allowed`, exact Sol allowlist, called by existing spawn admission and reason validation. Non-Sol hub defaults advertise agents=False; stale enabled flags cannot bypass policy. Remove obsolete Claude reason permission. Existing aliases/catalog identities remain available for history; `hub` still resolves to its former Claude route and is refused, never silently remapped. |
| `app/manager.py` | Check before auto-switch/reset for ordinary, initial and durable direct sends and preflight. Quota notices name Sol/wait, replacing Luna/Spark suggestions. |
| `app/session.py` | Recheck before send mutations, including running/internal delivery, queue consumption, backend creation/reconnect and handoff recovery. Checks under lifecycle locks release locks on refusal. Model-change errors report the Sol rule; prior model/reason/history/latches remain intact. |
| `app/backend_hub.py` | Check connect, send/steer, events before pending-input consumption, turn/recovery before workspace mutation, start/resume, retarget and reconnect before disconnect. Capacity refusal says Sol only and wait/report; no alternative model. |
| `app/routes/sessions.py`, `app/mcp_stdio.py` | API worker default Sol; dashboard/MCP changes reject before loading. Spawn/change tool descriptions and error metadata name the enforced rule rather than a creative exception. |
| `app/hub_pool.py`, `app/report_holds.py` | Hints name Sol only; exhausted Sol requires wait/report. Existing capacity arithmetic/admission is retained. |
| `app/static/js/app.js`, `i18n.js` | Reject non-Sol hub selection with localized explanation instead of asking for a Claude reason. Historical reason display/storage remains. |
| Pipeline manifest / `model-routing.md` / `CHANGELOG.md` | Generic worker fallback plus worker/full-cycle/reducer defaults become Sol; permanent English decision; hand-written Unreleased patch entry. Every effort-map entry and native orchestrator Terra High default is unchanged. |
| 14 test files (see inventory) | New behavioral guard/recovery suite; replace obsolete creative permissions with refusals and preserve storage tests through local Luna/Sol. Shared successful workspace fixtures use Sol so privacy/scope tests still reach their original guards. Held initial/direct queues explicitly survive a forbidden model change. |

Native orchestrators and manual native choices, protected local Luna with reason, ordinary native subscription refusal and explicit separately authorized eval/API paths retain their boundaries. No native/API fallback was added. Configuration, company/privacy, ownership, quota and capacity checks remain in place. No `app/hub_workspace.py`, live DB/schema, queue implementation, services, auth, credentials, environment or lockfiles were changed. The separate privacy-held workspace-recovery fix was not resumed. No live worker, remote copy or held queue was migrated.

## Earlier source-copy verification (historical; unchanged raw evidence)

All Python commands used broker **uv 0.11.28**, default `.venv`, `uv run --frozen`; pytest was serial with nice=10 and oom_score_adj=1000, NOTIFY_SOCKET unset, isolated test DB/temp roots outside checkout, mocked hub/provider calls. Resources checked: 8 cgroup CPUs, about 49 GiB memory limit, at least 19 GiB cgroup headroom; no browser/test farm ran.

Imported app: `app/__init__.py` from this copy. Exact absolute app/interpreter paths are kept privately in ignored `raw/environment.log`.

| Check | Actual result |
|---|---|
| Initial focused suite after admission fixes | **288 passed, 4 browser tests deselected**, 53.88 s. |
| Canonical test-map selection plus instruction/pipeline fixture tests | **979 passed, 4 browser tests deselected**, 171.65 s (`raw/mapped-final.log`). Includes models, manager, session, MCP, route surface, backend hub, native orchestrator/manual/Luna allowance, capacity, reasons and new persisted-worker recovery. |
| Additional workspace, company/file-policy/scope, ownership/switch, queues, outbox-report and backend-routing regressions | **302 passed, 3 failed, 2 subtests passed**, 159.45 s. All three were obsolete test assumptions: exhausted Claude instead of Codex after fixture migration; two old Sonnet-allowed queue branches. |
| Final focused repair run | **135 passed**, 11.27 s (`raw/risk-fixed.log`): complete new guard suite including billing escape refusal, whole quota-wait-queue suite, exhausted-Sol/no-upload case and both quota-notice tests. Unchanged additional regressions were already green. |
| Real pipeline manifest check | **PASS**: `uv run --frozen python scripts/check_pipeline_manifest.py --check`. |
| Direct instruction contract | **RED**: `CLAUDE.md` symlink is omitted from this copy. `AGENTS.md` untouched, **16349 bytes**, below 16384. No checker/contract was weakened or replacement file fabricated. |
| Repository-specific knowledge/source contract | **3 RED** in the earlier mapped+docs run: each stops at Git exit 128 because `.git`/historical objects are absent. These frozen checks are unchanged; root must rerun them in the full checkout. KB index and model-default rules file were also not supplied and were not invented/overwritten. |
| Final syntax/artifact review | Changed Python parses; mutation absent; final source hashes match. Task artifacts pass canonical secret-shape masking unchanged (`artifact-scan.json`). Raw logs are ignored via `raw/.gitignore` and hashed. |

No full suite or live/provider probe was run. Four browser layout cases were deliberately deselected; the offline Node selection/reason-display test passed. There was no visual layout/CSS change, site publication or live activation.

Earlier reds are retained in ignored logs and `notes.md`: one pytest reserved-parameter collection error; seven first targeted failures (five exposed dashboard admission after lookup, two fixture assertions); five first mapped failures (two updateable tests plus the three unavailable Git checks). All implementation/fixture defects were corrected and rechecked. These four copy-only failures were not waived; the later independent exact06f3 host checks passed, as reported in the acceptance follow-up above.

## Committed-test mutation proof

`tests/test_hub_sol_only_v1240.py::test_all_non_sol_hub_requests_refuse_even_with_old_enabled_flags` is included for the platform commit. `mutation.py` disables only the canonical non-Sol refusal branch, restoring old admission with stale enabled flags, then restores the exact source in `finally` and reruns the same node.

- Mutant: **22 intended `DID NOT RAISE` failures**, exit 1, 5.59 s.
- Restored control: **22 passed**, exit 0, 4.85 s.
- Before/restored `app/models.py` SHA-256: `b745ff54a695407e87509b0987827b65b2cf75dae309f3ec29a8d3a3e1cf9ab6`.
- Mutant SHA-256: `39f9ea07d4f90675ff53c1d095244daf67db805a1e9f69a894f7c2b8082040f5`.

Exact command/node and hashes: `mutation-proof.json`; raw evidence: `raw/mutation.log`, `raw/mutation-restored.log`; all log hashes: `raw-log-hashes.sha256`.

Root next: retain the broker-imported final test-only HEAD/diff and own merge/push; the existing independent exact06f3 host acceptance remains correctly versioned. Python activation remains exclusively with the owner's idle watcher. No manual restart/deployment was performed or implied.


## Parent acceptance evidence

Independent full-history host checkout QA is recorded in V-1243: instruction contract, all three Git-dependent source contracts and pipeline manifest passed; mapped 18-file selection passed 1,153 cases with four browser layout cases deselected. The committed refusal mutation produced 22 intended negatives while all 16 positive Sol/native-orchestrator/protected-Luna cases passed; source restored exactly and the 38-case control passed. These host runs used exact source candidate `06f3af9a5536d4f2813c17469e258fcc39fb12ed`.

The final source delta removes three newly added wording assertions in two test files. Parent comparison confirms all 13 production/manifest/routing/changelog bytes remain identical to that host-QA candidate; affected behavioral checks passed separately. Parent preserved all 14 raw source logs byte-identically with SHA-256 custody in ignored private storage. This closes source acceptance without claiming a new full-suite run.

Python activation is still pending the owner-authorized idle watcher. Task completion is pending live refusal/readiness verification; no manual restart and no actual provider test is authorized by this receipt. Worker shutdown must preserve usage/history; the existing coupled remote-history purge is not authorized as an automatic consequence here.

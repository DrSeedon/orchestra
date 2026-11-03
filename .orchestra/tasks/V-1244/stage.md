# V-1244: five integrated host outcomes corrected

DONE for source/artifact delivery; acceptance and live activation remain root-owned. The integrated candidate `c38c19e7411885c7e37f9db969010daf001a0f42` was reported by root as 7887 passed / 60 skipped / 4 failed / 1 error (exit1, 652.17s). This worker reproduced all five reported outcomes before editing. That host result is not replaced by a claim of a green full suite.

Fresh full-source manifest: `8825239827e0b5013e33d96f86bedad6440fad1506c827bb388b7ee138b0d1fe` (29 files). Fresh corrective-delta manifest: `fd2f4bf90cbdb0f50ebb636fd919a1eec7aaffc2a49ccf07099a47708e3d6a20` (7 files). The exact Git parent-to-candidate delta is `23bd5155d9b4d57046432e0b59c57f9adad99652` → `cf1a86568677a6a5b77db015a98e91ff04c9bb6f`: 7 files, +188/-29. `host-outcomes-delta.patch` is regenerated from that exact Git range with full index/binary metadata. The prior captured patch was relative to a slightly different Git-free baseline; it remains reachable at `cf1a86568677a6a5b77db015a98e91ff04c9bb6f:.orchestra/tasks/V-1244/host-outcomes-delta.patch`. Preserve root's integrated enforcer/cron/routing changes; do not overlay historical complete modules from this bundle.

## What changed

Production delta is only `app/backend_hub.py` (+4/-2): optional completion-action fields use the existing bridge identity with empty missing ID/name/branch and a conservative missing-role hold. Incomplete legacy identity no longer interrupts a completed safe sync. It emits no close instruction when ID/name/role is absent or empty; it invents no worker identity and does not derive identity from prose, cwd or workspace ID. Existing canonical worker directives, failed-provider boundaries and orchestrator exclusions remain covered. No change to report delivery/retry ownership, routing or lifecycle execution.

The two `test_hub_inputs_v1062.py` cases now enforce the approved continue/retention contract: saved state bytes survive merge observation, project/thread/workspace IDs and input provenance persist, local/remote RAW input bytes survive, INPUT stays absent from tracked worker/main trees, and the next explicit turn reuses the same thread without archive/delete/relaunch. The full input suite still tests mutation/collision and publication refusal.

`test_worktree_cleanup_v984.py` now inserts its own native session at a real temporary Git scope/worktree, pins actual branch/HEAD, uses a real SessionManager and lifecycle lock, and runs the real output cleaner. It checks recoverable output removed, unique data/main output retained, failed merge untouched, and a changed native generation held. Acceptance and final operation state are asserted; the existing30s await bound is unchanged. No source hold was weakened.

The frozen stale-snapshot regression function is byte-identical (body SHA256 `6c01daf8dbadcd6397eff743ef590ba80cca25728c4f9799cdc0681a1d8bdf72`). Only its dependency registration changes from collection-order-dependent `pytest_plugins` to explicit fixture imports, as in neighboring tests. Six missing/empty identity cases exercise the real import/commit completion path and assert no action while the committed artifact and saved state survive.

## Actual checks

Runner: provisioned uv0.11.28, frozen lock, default .venv, Python3.12.3 / pytest9.0.3. Absolute imported app provenance is recorded privately in `raw/host-outcomes/runner.log`. Tests are synthetic/offline, use temporary repositories outside the checkout, and ran at nice10/OOM1000. Two-worker checks had ample measured memory headroom; no concurrent test batteries.

| Check | Actual result |
|---|---|
| Original five host outcomes + archive control; -n2 --dist loadscope | 4 failed, 1 error, 1 passed; 27.34s |
| First corrected target | 1 failed, 13 passed; 16.73s (native fixture scope insertion still wrong) |
| Native fixture diagnostic | 1 failed; 6.18s, SESSION_NOT_FOUND because save_session preserves scope on conflict; fixed with a distinct inserted synthetic session |
| Correct native positive/failed/changed-generation target | 3 passed; 8.40s |
| Restored full changed-test modules + archive-before-generation fixture control; -n2 --dist loadscope | **106 passed; 36.48s; exit0** |
| Restored serial archive, cancellation, native ownership and report-order boundaries | **63 passed; 17.72s; exit0** |
| Restore unsafe direct identity reads | Expected **4 failed / 2 passed**;10.20s |
| Disable actual native cleanup return path | Expected **1 failed / 1 passed**;7.90s (failed-merge negative remains green) |
| Restore collection-dependent pytest_plugins | Expected **1 error / 1 passed**;10.40s, missing history fixture with two loadscope workers |

`mutate_host_outcomes.py` implements the three bounded mutations against tests delivered in this diff. It restores bytes in finally and verifies exact restoration; it never overlays an old whole module. All restored results above were run after the mutations. No skips or remaining red outcomes in these restored targets. The106 and63 are separate invocations with one shared archive control, not169 unique tests.

Reading order: `host-outcomes-delta.patch` → `app/backend_hub.py` completion block → input/native/identity/frozen-fixture regressions → `host-outcomes-proof.json`. Relevant unchanged owners are `hub_completion_action`, `_clean_worktree_after_merge`, SessionManager lifecycle locks and canonical routing guards. Raw logs/source hashes: ignored `raw/host-outcomes/`; current payload hashes: `host-outcomes-delta.sha256` and `candidate-source.sha256`.

## Preservation and limits

Read/hash checks show no changes to models, manager, session, merge_operations, both existing cron fixtures or the three canonical pipeline/app.js/i18n.js inputs during this correction (9 protected files). The frozen regression body is unchanged. Full archive tests recheck stored/reconstructed close, history/accounting/provider/recovery object survival, repeated close, pending/privacy/UNKNOWN stops and native best-effort paths. Directive tests cover strict-complete/continue/next-task/failure identity boundaries; native concurrency/cancellation tests still use actual flock and publisher ordering. No literal prose assertion was added or updated.

Must-fix before acceptance: root must integrate only this delta atop its current source and rerun the full host gate, including Git/assets and CLAUDE symlink contracts. This copy has no Git metadata and lacks the required CLAUDE.md symlink; neither prerequisite was fabricated, and no full copy suite was run. Root's earlier contract successes belong to its integrated candidate, not this worker run. The earlier163/182/223/66 results and earlier mutation proofs remain historical, not fresh evidence for this delta.

No models/effort/provider settings, quota/admission guards, queues, WIP or accounting changed. No live provider/model/close/kill/purge/merge/restart action, no private QA worktree access. Separate image cleanup is outside this task and unchanged. Python on disk is not live; existing Hub close restrictions remain until root acceptance, approved idlewatch activation and verification.

Publication check:49 source/report/mutation payloads scanned by the repository scanner and Hub credential shapes;0 findings. All29 source-manifest hashes and Python ASTs valid; current safe hashes match all three mutation logs. .venv, Python/pytest caches and raw logs remain ignored and outside the patch/export manifests.

# V-1240 CI follow-up — DONE source; host acceptance remains open

The source repair and available focused verification are complete. This is **not a green full-CI claim**. Root supplied the latest imported source HEAD `0ffaf3ba1b3f1bac6118ec1a4a97f1a4cf190518`; the final delta is imported/committed by the broker after this turn. This copy still has no Git metadata and cannot truthfully report a new local HEAD or create the fresh branch itself.

## Cause and exact scope

Public failed run: https://github.com/DrSeedon/orchestra/actions/runs/41505519278 on exact `0bbb0b96eb9b50cacee41023542d1d25cb560310`. Public run/jobs metadata confirms failure; full-run and individual-job log endpoints returned HTTP403, and the browser requires sign-in. No credentials or root's private log copy were accessed. The full public failed log remains unavailable in this copy; response evidence is retained privately.

The provided-source comparison checked718 files against the public exact0bbb Git tree. Only8 intended source/test paths differ. Final delta: **+103/-16**, with `app/models.py` the only production file. `changes.patch`, `diff-stat.json` and `source-hashes.sha256` specify exact bytes.

| Group | Cause / final change |
|---|---|
| Native/runtime identities and metadata | The Hub-only helper eagerly called global `get_model_spec`, rejecting existing opaque/retired native/runtime identities before their own quota/runtime owners. It now defers their validity while retaining native spawn admission. Unknown hub-prefixed identities and registered future Hub specs still fail closed unless exact Sol. No native/API fallback was opened. |
| Case normalization | The canonical resolver admitted case-insensitive direct Sol IDs but the helper compared raw mixed case. It now canonicalizes a registered normalized fallback before the exact Sol check. Uppercase alias/direct-ID positives are tested; forbidden Hub negatives retain stable `hub_workers_require_sol` checks. |
| New regression assertions | Removed generic `unknown model` prose match. Native refusal remains asserted by exception; stable rule-code checks remain. Added auth/startup registry-preservation coverage. |
| Cron drain tests | The SimpleNamespace target lacked the real mandatory model attribute. The fixture now uses permitted Sol consistently in target object and persisted row; real drain/delivery/at-most-once assertions remain. Production manager/session code is unchanged. |
| Seedon ownership and source-layout tests | Old successful Hub Luna/Haiku/Opus cases are now explicit stable-code refusals with zero dispatch/allocation and unchanged model/ownership; allowed Sol/native ownership and later uploads remain tested. |
| Frontend | The forbidden Claude picker case asserts no API request, one alert, no reload/history result and unchanged selection. Sol/native permitted cases remain. No service-message wording assertion added. |
| Defaults and report holds | Pipeline test follows accepted Sol fallback. Removed obsolete Hub Claude permission prose assertions from report-hold test; exact target delivery, provenance, no report-body leak, durable status and retry behavior remain. |

Manager/session/backend are byte-for-byte identical to public exact0bbb; V1244 retention is not touched. No manifest/effort/routing-default/queue/schema/live-settings/auth/credentials/service changes. No restart/kill/purge/legacy-complete, provider turn, model change, UNKNOWN replay or historical screenshot edit.11 existing public image fingerprints remain unchanged. Direct V1244 T3 lookup was unavailable in this copy; root coordinates the integration, and zero shared-file edits avoid that overlap.

## Actual outcomes, including red and incomplete runs

All Python verification used broker uv0.11.28 with `uv run --frozen`, default `.venv`. Isolated test DB/temp roots, NOTIFY_SOCKET unset, serial nice10/oom_score_adj1000; at most2 non-browser workers in the one interrupted broad run. Final verification removes provider endpoint keys **only from child-process env**. Exact absolute imported-app path remains privately in the existing `raw/environment.log` of V-1240; the public source is `app/__init__.py`.

| Run | Actual outcome |
|---|---|
| Original reported red families + new guard tests | **360 passed**,277.69s (`raw/red-set.log`). |
| Whole available browser, first environment | **113 passed,7 skipped,136 setup errors**,247.69s; test task-store commits lacked the synthetic Git identity that public CI sets. Terminal summary retained; outer receipt143. |
| Whole available browser, CI identity | **245 passed,3 failed,8 skipped**,774.75s,exit1. Failures: omitted compact fixture; image retry with omitted image asset; workflow-card fixture needs absent `.git`. Affected Sol/native picker cases passed. |
| Browser affected/video follow-up | **4 passed**,81.90s,exit0, including previously skipped video fixture after pinned FFmpeg was on PATH. Other7 skips:6 unavailable Antigravity phase2 cases and1 cancelled legacy voice-input case. |
| Available full core collection | **7617/7877 nodes**,260 deselected, no collection errors. |
| First broad core serial | **2133 passed,344 failed,7 skipped,1 error,2 subtests passed**,690.93s pytest,exit1. NOT hermetic: inherited relay endpoint caused catalog discovery400 and enterprise registry clearing; later model/quota tests were contaminated. Raw red evidence retained, not converted to green. The observed catalog request was not an inference call and is explicitly recorded. |
| First broad core parallel | **INTERRUPTED/INCOMPLETE at23%**. Last log20:21:35Z; no surviving PID or terminal summary; old exec session39161 unavailable. No numeric exit receipt. No replay/restart or second whole-copy battery. |
| Final isolation proof, before justified module run | **2 passed**,19.30s,exit0: actual auth/artifact startup with0 external catalog fetches;7 registry views and23 models preserved exactly. Before/after fingerprint `9eb1848c9cc88e59ac6549822047fd3bb00be1654f6fbe2af76064d3c7d4049d`. See `raw/startup-path-proof.json`. |
| Final clean20 justified modules | **1336 passed,1 failed**,571.01s,exit1. Every changed fixture/new guard/native/runtime/quota test passed. Sole red is existing cancellation test's2s cleanup-entered wait; no assertion or wait weakened. |
| Cancellation isolated | **1 failed**,16.79s,exit1, same original2s wait. |
| Cancellation bounded timing diagnostic | **1 passed**, original assertions/waits unchanged. Real worktree call returned normally in1.210085s wall /0.012843s thread CPU. This does not erase earlier reds or claim a stable timing fix. Host CI must resolve this remaining timing-sensitive acceptance result. |
| Final committed-test mutations | Eager registry restored: **6 intended red/25 green**. Case-normalization removed: **1 intended red/30 green**. Restored exact final source: **31 passed**,8.21s. |

Child isolation proof intercepts forbidden catalog fetches at the affected startup path and compares all registry views; it changes no production registry policy or live configuration. The standalone committed regression tests `refresh_models` under enabled auth without an endpoint and preserves the same views. After that proof the20-module run was justified; the corrupted whole-copy battery was not rerun blindly.

Full Git/assets CI remains impossible here: missing `.git`/history, `CLAUDE.md` symlink/KB source contract assets, compact JSON fixture and image asset. These failures were not hidden, skipped by modifying tests, fabricated or weakened. Actual full Actions CI after integration remains root's acceptance. Earlier exact06f3 host greens are historical and are not relabelled as this final source.

## Interrupted provider/run receipt

T3 durable receipt identifies run `run:thread:mcp%3Aa06bb0cd-c08a-4262-98ee-f681b32b70e8:ordinal:3` as **cancelled** at20:21:38.721Z. Timeline position733 says “T3 Code restarted and resumed this turn” at20:22:10.957Z; ordinal4 completed20:22:38.498Z. These times align with the partial core-parallel log. No lower-level provider exception/error code is exposed by the available receipt, so this report does not infer OOM, rate limit, model refusal or a provider fault. Exact bounded receipt is `raw/interrupted-run-receipt.json`; this is the evidence root can attach to the hub_error bug without replay.

## Mutation, preservation and handoff

`mutation.py` restores final source in `finally`. Final `app/models.py` before/restored SHA256: `0644a7304db57887096f86ce9db0255abc6f5b2f8c46e92a822c8d47096cc78a`. `final-mutation-proof.json` lists intended failing committed-test nodes, mutant hashes and passing controls. Raw mutation logs are retained.

Reproducible browser/npm/tool-bin caches were moved **outside the export worktree**, with explicit owner approval and zero active consumers, retaining logs/metadata in `cache-placement.json`. They are absent from source/export artifacts. No prior raw log/evidence/history was removed, no ignored raw force-added. Current raw37-file hashes were captured before final packaging; the final hash inventory covers all retained evidence files. Prior historical screenshots were neither changed nor replayed.

Root next: inspect the broker's final import HEAD/diff against prior0ffaf3, integrate with V1244 without overwriting shared files, and run actual full host CI with real repository/assets. No activation/restart is implied by source completion.

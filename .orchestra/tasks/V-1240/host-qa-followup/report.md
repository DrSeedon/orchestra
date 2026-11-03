# V-1240 — DONE test-only host-QA repair candidate

Root's native V1248 QA on exact `cf2912cfe49ed5625f893d83c598ce282e172858` reported7807passed/60skipped/9failed,exit1. Those are **parent-supplied host results**, not a Hub run. Its two HOME/TMPDIR failures were already shown environmental by root's bounded probes; no source change was made for them. Final full-host validation remains V1248/root acceptance after fresh candidate import.

## Exact scope

**3 test files, +109/-24. No production change.** `source-manifest.json`, `source-hashes.sha256` and `changes.patch` identify exact final bytes and captured local baselines. Public retrieval of exactcf291 source failed, so this report does not fabricate a Git/host-source equivalence claim. The provided local test/source paths were fingerprinted before edits. This copy still has no `.git`; final source HEAD comes from the broker import receipt.

Six protected implementation files are unchanged: models, app.js, chat.js, manager, session, backend_hub. Guard SHA256 remains exactly `0644a7304db57887096f86ce9db0255abc6f5b2f8c46e92a822c8d47096cc78a`, matching the host-provided guard hash. No model/API/effort/guard expansion, source polling change, V1244 manager/session/backend/merge WIP, timeout increase, live action or architecture choice.11 historical image fingerprints remain unchanged.

| Host failure group | Repair and preserved behavior |
|---|---|
| Four invalid/uncertain retarget variants | Replace forbidden Hub Luna target with permitted Sol. Real `retarget_model` and real `_model_selection` execute: same-ID Sol retarget still reconfigures the existing thread. Assert the exact configure target and canonical Sol selection. Keep original MultiCodeError classification, one call, persisted old-thread/model integrity and empty early-steer assertions. No guard bypass. |
| Initial-delivery locked entry | FakeSession now includes real `name` and existing legacy `model` fields. Mandatory provenance signature, lock ownership, auto-switch-before-send order and delivery identity assertions remain. |
| V788 released initial target | LoadedSession includes the same real fields. Existing-session legacy model matches the persisted fixture; no new native worker admission. Preserve loading, at-most-once delivery, provider submission receipt and single user log assertions. |
| Workflow card | The fixture globally returned workflow JSON for all API calls and waited on a mutable last-fetch URL. Hidden visibility stops registered polling, not every independent API request. A later unrelated GET can overwrite that URL even after the card rendered. Scope synthetic responses to the current workflow detail/result only; forward unrelated requests unchanged; retain append-only workflow request evidence. Existing card detail/answer/error/render checks and original30000ms wait remain. |

## Bounded root-cause evidence

This is stronger than isolated success:

1. `workflow-last-url-repro.js` runs actual API/visibility/watcher code without network: hidden=true, workflowRendered=true; one later unrelated GET makes the old wait predicate false.
2. `reproduce_existing.py` runs the **same original failing full dashboard test node** with the identical controlled late GET after actual refresh/render. Old fixture exits1 at the original30s predicate; evidence confirms the card had rendered and last URL was overwritten. Fixed fixture exits0 with the detail request retained. No production polling change or timing relaxation.
3. A new committed behavioral regression executes actual API/card/watcher/visibility functions. It checks the unrelated API's independent response, retained workflow evidence, hidden polling state and full answer retrieval. Removing the endpoint filter restores the faulty global JSON injection and fails the response-data assertion; restored source passes.

The Hub lacks Git metadata needed only to locate optional historical workflow content in the existing test. The diagnostic plugin substitutes an empty synthetic optional-history root and does not replace API/card/polling/render/assertion behavior. Thus full historical-run coverage and exactcf291 host execution are **not claimed** here; host raw/private was not copied.

## Actual checks

Broker uv0.11.28, frozen lock/default.venv; child-only provider endpoint isolation and synthetic CI Git identity. Offline/mock transports, one browser instance, nice10/oom_score_adj1000. No full-copy suite, provider/model/TG call, live archive/kill/merge/push/restart or legacy completion. Same external browser/tool-bin/npm caches remain outside export; none are force-added.

| Check | Actual result / evidence |
|---|---|
| Complete transport + initial-delivery modules | **68 passed**,28.79s,exit0; `raw/transport-delivery.log`. |
| Final transport parameter matrix after exact wire assertions | **16 passed**,12.51s,exit0; `raw/transport-final.log`. |
| First focused browser attempt | New deterministic regression passed; original fixture setup errored because independent module browser and dashboard_browser started concurrent sync loops: **1passed/1error**,29.16s. Retained `raw/workflow-focused.log`; changed the new test to share dashboard_browser without altering assertions or waits. |
| Complete workflow-card module with source-copy diagnostic | **6 passed**,34.61s,exit0; `raw/workflow-module.log`. |
| Same original node, controlled late unrelated GET | Old observer **exit1**, fixed **exit0**; `same-node-repro-proof.json` and both raw logs/probes. Old failure is expected reproduction, not hidden. |
| Meaningful committed-test mutation | **1 intended failed**,25.59s,exit1; restored **1 passed**,25.60s,exit0. Source before/restored SHA256 `2c34a853cd158461d1936eee72f529a01bfe7cb553653180b3877763446e40a6`; `mutation-proof.json`. |

No skips occurred in these target runs. The parent-reported60 full-host skips remain versioned tocf291; none were silently reclassified here. Full-host integration, its Git/assets requirements and the two environmental host cases remain root's responsibility.

Public artifacts are checked for foreign host/user paths and secret-shaped values; raw diagnostics stay ignored/private and hashed. No historical screenshot was edited, restored or replayed. Root should inspect the broker's worker-authored candidate diff/HEAD and rerun V1248 on that exact candidate with the established valid checkout/HOME/TMPDIR. This result does not claim full CI green before that acceptance.

# V-1248 final integrated host QA

## Verdict

The exact integrated source/test candidate a1d81f96837c3dc99f2fa7ee19116bd47ebf9720 received two native full-suite attempts. The first detached checkout run was RED: **7,894 passed, 60 skipped, 5 failed, 7 warnings** in 539.38 s. The root-authorized rerun used the existing named branch at the same HEAD and passed: **7,899 passed, 60 skipped, 5 warnings** in **578.03 s**, exit 0. No source or test file changed between these runs; only the test checkout's branch metadata differed. The initial detached-run reds and their five-node diagnostic remain recorded below.

At the time of host QA no service action had been performed by this worker. Root later merged and published main d8fd509df0579f09b2f35c8ca88f54c933d664d6 and completed its owner-authorized restart; the activation receipt is recorded below.

## Candidate integration and preserved inputs

The worker-authored V-1244 host-outcome delta was integrated from the exact 23bd5155d9b4d57046432e0b59c57f9adad99652 → cf1a86568677a6a5b77db015a98e91ff04c9bb6f Git range using the seven-path full-index patch. It is **188 additions / 29 deletions**. The exact seven-file manifest is committed in the branch; all seven candidate file hashes match host-outcomes-delta.sha256 byte-for-byte. The only production change in that delta is the optional identity handling in app/backend_hub.py (+4/-2); the other paths are the five-outcome regression tests, CHANGELOG.md, and the committed mutation helper. The V-1244 source/evidence correction from e847cdc27663a114ec9edd4d40f14f445ef77b1a and the current sanitized V-1247 receipt from db415c9efd6c3047e1117ed33e9173d7c05dec1a are retained.

The approved V-1240 test pins from 40c368a130e86d6113e58daae6a62dd8795d5152 remain exact in tests/test_default_pipeline.py, tests/test_hub_sol_only_v1240.py, and tests/test_cron_drain_delivery_v1074.py. app/models.py is SHA-256 0644a7304db57887096f86ce9db0255abc6f5b2f8c46e92a822c8d47096cc78a. The pipeline manifest and app/static/js/app.js / i18n.js match main 0bbb0b96eb9b50cacee41023542d1d25cb560310. The main V-1240 and V-1243 reports, disk KB topic, and temporary rules are preserved; .orchestra/tasks/V-1240/report.md was restored to the exact main blob and its previous branch-specific short summary retained privately. Full source manifest SHA-256 is 8825239827e0b5013e33d96f86bedad6440fad1506c827bb388b7ee138b0d1fe; corrective seven-file manifest SHA-256 is fd2f4bf90cbdb0f50ebb636fd919a1eec7aaffc2a49ccf07099a47708e3d6a20.

The report import path and diagnostic identifiers are replaced with approved placeholders in public artifacts. The actual import path and raw evidence remain private. The local pre-push secret scan of unpublished branch commits exited 0 with no findings.

## Pre-suite checks

The existing full Git checkout is non-shallow, clean at the tested commit, has CLAUDE.md → AGENTS.md, KB history, V-672 fixture files and docs/dashboard-real.png. The absolute imported app path is {{PRIVATE_APP_IMPORT_PATH_02}} (raw import proof is private). Runtime was uv 0.11.28, Python 3.12.3, pytest 9.0.3; --timeout and --timeout-method are available.

Both current contracts passed: scripts/check_instruction_contract.py and scripts/check_pipeline_manifest.py --check. Collection of the 22 changed test files found **832 tests**, no collection errors. These checks and the focused batch ran at commit 57083dbafab9935192c24dbfe6dd57a5da119743; the full-run commit a1d81f96837c3dc99f2fa7ee19116bd47ebf9720 differs only by restoring the public V-1240 report, with source and test files unchanged. The corrected focused batch for the prior five V-1244 outcomes and related archive/native/cancellation/report boundaries passed **195 tests in 25.35 s**, no skips. Startup isolation passed **1 test in 4.67 s**: auth enabled, 0 catalog fetches, 23 models, registry unchanged, before/after fingerprint 9eb1848c9cc88e59ac6549822047fd3bb00be1654f6fbe2af76064d3c7d4049d.

One precheck command listed a nonexistent test file and exited 4 before running any test. The path was corrected; the completed 195-test run above is the actual result.

## First full-suite run: detached-HEAD RED (preserved)

The command was exactly uv run --frozen python scripts/run_tests.py; the checked-in runner used its native not live_probe marker and two-worker loadscope distribution. Its only five failures were:

- tests/test_wf_run.py::test_manifest_contains_ready_resume_command
- tests/test_wf_run.py::test_manifest_can_use_a_runner_specific_resume_command
- tests/test_wf_run.py::test_missing_scheduler_route_runs_without_admission
- tests/test_wf_run.py::test_unavailable_scheduler_keeps_waiting[503]
- tests/test_wf_run.py::test_unavailable_scheduler_keeps_waiting[None]

Each raised RuntimeError: cannot resolve workflow workspace base branch: detached HEAD from _current_branch() before the tested workflow behavior ran. The full checkout had been detached at the exact commit. After the first run, a local branch was created at the same commit and only those five nodes were run; all five passed. A later root-authorized full run at that branch/HEAD is recorded in the next section.

The native quiet runner reported 60 skipped but did not print skipped node IDs/reasons; QA added no skip or deselection. Seven warnings were two multiprocessing fork deprecations, one duplicate FastAPI operation ID, and four websockets deprecations.


## Root-authorized named-branch full suite

At root's direction, the existing full checkout remained on named branch qa-v1248-final-a1d81 at exact HEAD a1d81f96837c3dc99f2fa7ee19116bd47ebf9720, with clean status, seven source-delta hashes, app/models.py, all three 40c test pins, and uv.lock hash verified before dispatch. The exact native command uv run --frozen python scripts/run_tests.py ran once more, with a 20-minute external command budget; the runner still used its normal not live_probe marker and two-worker loadscope behavior.

Result: **7,899 passed, 60 skipped, 5 warnings in 578.03 s**, exit 0. The five workflow nodes that had failed from detached HEAD were included and passed in this full run. Warnings: two multiprocessing fork deprecations, one duplicate FastAPI operation ID, and two websockets deprecations. The quiet runner did not print skip IDs/reasons; no QA skips or deselections were added. No source/test changes or extra focused test runs occurred after this full suite.

Raw output and resource measurements: private raw/full-suite-named-a1d81.log, raw/full-suite-named-a1d81-time.txt, raw/full-suite-named-a1d81-resources.txt. The exact browser-generated screenshot diff is private raw/full-suite-named-a1d81-screenshot-changes.patch (SHA-256 f0eaf40151bbda88c8d2297ef0e78607fed6578930a371f3080e7670465a3a42); the nine affected tracked images were restored and the full checkout is clean at the tested HEAD.

## Environment, resources, and remaining limits

The runner child used env -i, UV_OFFLINE=1, HOME outside /tmp, TMPDIR=/tmp, an isolated synthetic SQLite path, and the existing frozen venv/cache. NOTIFY_SOCKET, live service/task-store values, provider endpoints/auth values and real CLI credentials were absent. Tests used no production DB or external provider/network/model calls; the workflow scheduler cases used local test servers. Heavy runs used localhost SSH, nice -n 15, and choom -n 1000 outside the Orchestra service cgroup.

For the first detached run, /tmp available space moved from **12,489,572,352 B** to **9,922,121,728 B** and pytest temp storage from **98,848,768 B** to **2,700,460,032 B**; maximum RSS was **2,489,168 KiB**, swaps 0, elapsed 9:00.63. A later five-node diagnostic used pytest's normal retention and free space returned to 12,607,864,832 B, without manual cleanup.

For the successful named-branch run, free space moved from **12,540,129,280 B** to **9,885,421,568 B** and pytest temp storage from **27,815,936 B** to **2,699,567,104 B**; maximum RSS was **2,500,112 KiB**, swaps 0, elapsed 9:39.86. At 00:35:40 UTC after screenshot restoration, free space was **9,851,301,888 B** and pytest temp storage **2,701,754,368 B**. The canonical backup cron remains scheduled for 02:00 UTC; no backup process was active at the post-run check. Free space is 3,199,756,709 B below the previously measured 13,051,058,597 B backup-creation gate. No cleanup script, manual deletion or reserve change was performed.

## Initial retry preflight stop (before root clarified the operation-specific reserve)

After root authorized one full run on a named QA branch, the existing full clone passed the objective checkout checks: symbolic-ref returned branch qa-v1248-final-a1d81, HEAD was exactly a1d81f96837c3dc99f2fa7ee19116bd47ebf9720, and tracked status was clean. All seven source-delta hashes, app/models.py, the three approved 40c test pins, and uv.lock SHA-256 b1b9364dd130ddc03376563d83c14d8ef15bc9753d3f421e682df1588a558a70 matched. No pytest process was active.

That preliminary retry was not dispatched: free disk was 12,597,731,328 B and the measured previous pytest-temp increase was 2,601,611,264 B. This was preserved as the resource-stop decision at that point. Root later clarified that the backup gate protects archive creation and provided a bounded QA operating threshold plus the 02:00 schedule check; the named-branch run above then passed those updated conditions. The original preflight receipt remains private raw/full-suite-retry-preflight-final.json.

Earlier results remain distinct: the corrected cf2912 run was 9 failed / 7,807 passed / 60 skipped / 5 warnings; the prior integrated c38c19e run was 4 failed / 7,887 passed / 60 skipped / 1 error / 5 warnings. Those runs are not represented as green and do not replace the successful named-branch a1d81 run.

Raw logs, timing/resource measurements, startup proof, screenshot diffs, invalid precheck output, retry preflight, and five-node diagnostic remain in ignored private V-1248 evidence. The full suite tested source/test commit a1d81f96837c3dc99f2fa7ee19116bd47ebf9720 before integration. Root later merged/pushed d8fd509df0579f09b2f35c8ca88f54c933d664d6; GitHub CI run 41554641506 succeeded for that exact SHA. The activation check below is separate host evidence.


## Activation acceptance after merge

After root's exact-source merge, push and successful CI run, the owner-authorized restart was scheduled once at 2026-11-03 00:54:55 UTC. Its HTTP response was 200 with scheduled=true; cut_names contained only the initiating Orchestra orchestrator. No worker was cut. The recovery timer fired, the root returned, restart_cut_turns was empty, and no worker resumption was owed. The new MainPID started at 00:56:23 UTC. Main was clean at d8fd509df0579f09b2f35c8ca88f54c933d664d6 before the restart and remained clean afterward; the new process started after that commit. This links startup to the accepted source tree but is not a direct hash of every imported module in memory.

Post-start checks returned HTTP 302, systemd active/running, parent cgroup MemoryHigh 14 GiB / MemoryMax 16 GiB, and oom_score_adj 800. The bounded restart journal reported 25 background jobs restored, 0 expired, and systemd readiness published; it contained no warnings or errors. The live MCP refusal check confirmed the negative hub-model admission path: ApiToolError hub_workers_require_sol, details.field=model, retryable=false, outcome_unknown=false; it created no worker and requested no provider submission. This checks only that negative MCP entry guard, not Sol provider capacity/readiness, a real provider turn, or every route.

No Hub closure, kill or purge was attempted; the legacy close hold remains. The DB contains two unresolved historical merge records in PARTIAL/UNKNOWN states; they remain recorded separately and were not counted as PENDING/RUNNING. Actual runtime paths, database identities, cut identifiers, authentication material and raw responses remain in private V-1248 evidence. The private activation-preflight report records full coverage and limitations.

# #313 — research-only test-suite pruning audit

## Question

**Context:** the current Orchestra pytest suite on frozen `main` SHA `1d9be7ae8511a1c5657362cc56eef395b4585bf2`.

**Change under test:** future Class-C pruning or rewriting of tests that are redundant, representation-bound, vacuous, obsolete, low-signal, or unsafe for automatic execution.

**Baseline:** every currently collected test node and its current production seam; the #250 result that a checklist alone did not improve behavioral correctness (`28/30` vs `28/30`) and that independent valid-alternate/mutant oracles are required [1].

**Outcome:** a test is a proven DELETE/MERGE candidate only when its unique behavior set is empty, current production symbol/caller status is verified, and a recoverable selection plus seam-mutation experiment shows another named test catches the same mutant while positive and valid-alternate controls remain meaningful.

No test, production file, pipeline, configuration, live DB, provider, model, eval, or review was changed/called. The only writes are under `docs/tasks/313/`, `docs/kb/test-suite-pruning.md`, and this worker-memory file.

## Hypotheses and falsifiers

- **H1 — a small set of tests is genuinely redundant.** Falsifier: exact inventory and an independent mutant show a unique positive control or valid-alternate dimension for every apparent duplicate.
- **H2 — static representation/aggregate/mock signals identify deletions.** Falsifier: static candidates protect a contract, or a negative control makes the suspected vacuity observable.
- **H3 — rare or verbose recovery tests are low value.** Falsifier: the test covers a unique production recovery, safety, handoff, merge, quota, delivery, or provider capability path.
- **H4 — the current suite is deterministic enough for pruning.** Falsifier: collection errors, live state, stale seams, external CLIs, or service startup prevent the named behavior from being reached.

## Findings

### F1 — exact baseline and collection gaps are measured

**CONFIRMED — direct collection and AST measurement.** The suite has 153 Python test files, 78,491 physical LOC, 65,583 nonblank LOC, 2,886 source test definitions, 162 local fixtures, and 3,284 collected nodes including three live-probe nodes [2]. The default `not live_probe` selection is 3,281 nodes [3].

The unpatched host collection is not a clean baseline: it collected `3151/3154` and stopped on eight `AttributeError: module 'os' has no attribute 'pidfd_open'` import errors [4]. The patched collection used only an in-process compatibility shim for inventory and did not run test bodies [3]. The eight affected files are named in `metrics.md` and `collect-default.txt`; they are a collection/environment gap, not silently skipped tests.

### F2 — static detectors find signals, not deletion proof

**CONFIRMED — direct AST measurement.** Static counts are 29 `all`, 65 `any`, 415 mock-double sites, 2,078 representation/cardinality comparisons, 207 wall-clock waits, 155 source/argv/DOM-shape sites, 108 browser/client sites, 135 subprocess sites, and six `inspect.getsource` sites [5]. Exact normalized body duplicates are zero. The only near-duplicate lower bound is the two pipeline skill-path tests at Jaccard `0.9211` [5]. They exercise separate `defaults.skills` and `roles[*].skills` configuration paths, so the pair is KEEP/LIKELY, not MERGE.

The detector intentionally did not label every aggregate or mock as vacuous: fixed nonempty controls and explicit branch attributes are valid negative controls. #250 directly falsified prompt-only confidence; a candidate test obeyed six design questions yet rejected a valid metadata extension [1].

### F3 — route surface tests overlap on one mutant but protect different failures

**CONFIRMED — source plus recoverable runtime mutants.** `test_route_surface_snapshot` catches a one-route omission [6]. However, the compound mutant that returns one route and supplies a matching one-route snapshot passes the snapshot test while `test_route_surface_is_discoverable` fails the minimum-surface guard [7]. Conversely, route-snapshot exact path/method drift is not guaranteed by the minimum count. Both tests therefore KEEP/CONFIRMED. This is the required positive-control and valid-alternate counter-evidence against deleting the apparent pair.

### F4 — quota E2E tests are high-value contracts with a broken deterministic seam

**CONFIRMED — targeted measurement and source trace.** The quota admission group produced 95 passes and four failures [8]. The failing parameterized nodes are the above-line worker refusal cases and hard-stop Luna/Spark cases in `tests/test_quota_admission_e2e.py`; the failure reaches a live blocked quota decision despite the test's monkeypatch. The test's intended seam and the manager's imported call path do not align, so current red output is not a quota-behavior verdict. These tests have below-line, orchestrator, and unknown-quota controls in the same file, so deletion would remove unique admission behavior. Verdict: REWRITE, not DELETE.

This is the exact #250/test-oracles failure class: the test names the desired behavior but does not independently prove that the production path uses the patched boundary. The minimum future ticket is to patch the imported loader or inject an explicit admission seam, then run above/below/hard-stop/unknown positive and alternate controls without live telemetry.

### F5 — merge-stuck tests are obsolete at the fake seam, not unnecessary

**CONFIRMED — targeted output and current source signature.** The manager/merge group produced 184 passes and two failures [9]. Both failures are `TypeError: live_merge.<locals>.fake_execute() got an unexpected keyword argument 'expected_target_head'`; current `app/routes/sessions.py:1461` accepts `expected_target_head`, and `app/merge_operations.py:1304` passes it [10]. The two tests are the missing-task warning and explicit-resolution recovery scenarios. Their intended behavior remains unique and safety-critical; the fixture is stale. Verdict: REWRITE/CONFIRMED, with a future acceptance check after the fake signature is repaired.

### F6 — oversized runtime-handoff and backend/session suites protect unique recovery behavior

**CONFIRMED for uniqueness; current run partially blocked — source plus targeted measurement.** Backend Claude/Codex plus session-hibernate tests passed 152/152 [11]. Runtime-handoff v2 produced 64 passes and 10 failures because current model-registry setup reports `unknown model 'gpt-5.6-sol'` before those contract assertions [12]. The tests cover authority, packet integrity, oversized context preflight, receipt ordering, rollback, and source/target cleanup. Their rarity/LOC is not evidence of redundancy; verdict KEEP/CONFIRMED, and environment/seam repair is separate.

### F7 — live-provider probes are explicitly outside automatic conclusions

**CONFIRMED — collection inventory and source.** `test_native_history_import.py` contributes three collected `live_probe` nodes: two parameterized runtime canaries and one cross-runtime handoff canary [13]. They use real Claude/Codex CLIs and copied credentials when explicitly run. They were collected only; no provider command or body ran. They protect unique oversized native-history and release-capability behavior and remain KEEP/CONFIRMED with external-risk exclusion.

### F8 — prompt/browser representation checks need contract-aware handling

**LIKELY — source inspection plus static signals.** Prompt tests assert generated anchors, absence of inlined bodies, path safety, and manifest ownership. These are representation-bound by design but encode prompt-delivery/security contracts; no deletion proof exists. Browser tests include exact DOM/source anchors and synthetic timing. `test_dashboard_polling_equivalent_twelve_minutes_before_after` was not accepted as a runtime measurement because its child process exited before app startup on the host `pidfd_open` gap [14]; its implementation also uses a wall-clock wait. Verdict UNKNOWN/LOW until a deterministic in-process browser oracle is available. Other browser safety tests remain KEEP unless a named mutation proves otherwise.

### F9 — task/payment/YouGile tests remain an explicit future decision boundary

**LIKELY — targeted pass plus #299 decision.** The task/payment/YouGile group passed 71 and skipped 7 [15]. `test_yougile_import_uses_resolved_project_id` exercises current import identity and DB behavior. YouGile/payments are pre-decided for future removal under #299, but #313 has no migration or replacement oracle; verdict UNKNOWN/LIKELY, no deletion now.

### F10 — no proven DELETE or MERGE candidate exists

**CONFIRMED under the requested oracle bar.** One apparent redundant route guard was disproved by the compound negative control. No exact duplicate body exists, no current direct production import is unresolved [16], and no other candidate received a valid recoverable seam mutant plus alternate control. Proven DELETE: **0 nodes / 0 LOC**. Proven MERGE: **0 nodes / 0 LOC**. Candidate details and required future oracles are in `candidates.csv`.

## Decision summary

The exact decision table is `docs/tasks/313/candidates.csv` with the requested 16 columns. It contains 12 concrete nodes/functions covering route snapshot/discovery, quota admission, merge acceptance, frontend polling, live history, runtime handoff, prompt-path variants, and YouGile import. The conservative conclusions are:

- **KEEP:** route snapshot/discovery, live history canaries, runtime-handoff safety, and both pipeline-path tests;
- **REWRITE:** quota admission E2E seam and merge-stuck fake signature;
- **UNKNOWN:** frontend polling until deterministic browser evidence, and YouGile until #299 migration supplies a replacement oracle;
- **DELETE/MERGE:** zero proven candidates.

## Counter-evidence and limitations

- The route snapshot pair looks redundant by ordinary one-route mutation, but the compound truncated-snapshot mutant makes the minimum-surface test uniquely fail [7].
- The quota tests have extensive positive/alternate controls and are not unnecessary; the current failures demonstrate a seam leak and live-state dependence.
- The merge tests are red due a changed production signature, not because the recovery scenarios are obsolete.
- Static `all/any`, MagicMock, source-shape, and wall-clock counts include valid tests with explicit nonempty controls; counts are not candidate counts.
- Full execution was not used as a cleanliness claim: the host collection has eight import errors; live probes and service-starting tests were excluded; no live credentials, provider, `NOTIFY_SOCKET`, or successful service startup were used.
- No mutation run was performed for any DELETE/MERGE candidate beyond the route pair because no other candidate satisfied the precondition for a deletion experiment. This is why the result is zero proven deletions rather than a speculative estimate.
- Test source copied into generated AST evidence contained fixture-like secret strings; the artifact was sanitized and `evidence/secret-scan.txt` reports no secret-form matches.

## Affected files, risks, and future Class-C tickets

No production/test implementation changes are authorized by this research. Future cleanup tickets should be minimal:

1. `tests/test_quota_admission_e2e.py::test_gated_worker_is_refused_above_the_line` and `::test_luna_and_spark_are_refused_at_the_hard_stop`: repair imported admission seam; AC is the exact focused command green with above-line, below-line, hard-stop, orchestrator, and unknown controls and no live quota reads.
2. `tests/test_merge_stuck.py::test_missing_task_ref_does_not_freeze_the_branch_forever` and `::test_primary_failure_blocks_until_it_is_explicitly_resolved`: accept `expected_target_head` in the fake; AC is the exact focused command green and both recovery paths reach PARTIAL/SUCCEEDED assertions.
3. `tests/test_frontend.py::test_dashboard_polling_equivalent_twelve_minutes_before_after`: replace child-service/wall-clock dependence with an in-process deterministic timer/request oracle; AC names hidden-state zero polling plus a visible-state positive control.
4. `tests/test_tm.py::test_yougile_import_uses_resolved_project_id`: defer to #299; AC must include a replacement migration/API oracle before any deletion.

## Sources

1. `docs/tasks/250/research.md`, `docs/tasks/250/analysis-summary.json`, `docs/tasks/250/raw/` — frozen A/B and valid-alternate/mutant evidence.
2. `docs/tasks/313/inventory.json` — frozen SHA, files, LOC, fixtures, source definitions, node IDs, imports, markers, and static assert patterns.
3. `docs/tasks/313/evidence/collect-default-patched.txt`, `collect-live-patched.txt` — collection inventory.
4. `docs/tasks/313/evidence/collect-default.txt` — unpatched collection errors.
5. `docs/tasks/313/evidence/static-signals.json`, `clusters.json` — AST candidate signals and duplicate lower bounds.
6. `docs/tasks/313/evidence/mutant-route-snapshot.txt` — one-route removal mutant.
7. `docs/tasks/313/evidence/compound-discoverability.txt`, `compound-snapshot.txt` — compound negative-control mutant.
8. `docs/tasks/313/evidence/target-quota-proxy.txt` — quota/proxy targeted run.
9. `docs/tasks/313/evidence/target-manager-acceptance.txt` — manager/merge targeted run.
10. `app/routes/sessions.py:1461`, `app/merge_operations.py:1304`, `tests/test_merge_stuck.py:82-113` — current merge signature and stale fake.
11. `docs/tasks/313/evidence/target-backend-recovery.txt` — backend/session recovery run.
12. `docs/tasks/313/evidence/target-session-recovery.txt` — runtime-handoff run and model-registry failures.
13. `tests/test_native_history_import.py:197-268`, `docs/tasks/313/evidence/collect-live-patched.txt` — live-probe nodes and external-risk boundary.
14. `docs/tasks/313/evidence/target-polling.txt` — excluded frontend runtime attempt; child exited before app startup.
15. `docs/tasks/313/evidence/target-prompt-task.txt` — prompt/task/payment/YouGile targeted run.
16. `docs/tasks/313/evidence/import-status.json` — current direct import/re-export resolution.

## Review constraint

The user explicitly prohibited model/provider/eval/review calls. No adversarial model review was run; this report records the mechanical evidence and the explicit review exclusion.

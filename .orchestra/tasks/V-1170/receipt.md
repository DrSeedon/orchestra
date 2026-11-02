# V-1170 integrated native eval QA receipt

## Executive summary

- The QA candidate integrates current main `ae76920655d19c64cbbd006dfebc0138ccee1008` and V-1166 source HEAD `8b74515cfb54471a88d5d9496cee5f01fa94b65d` by graph merges. Before this receipt edit, HEAD was `235d3a81b2d02f0db2d57a8e77efe8b5caecfb06`; prior WIP `0379e057bbcad11ad26fe5a2f79bdca45dd4f750` remains reachable. QA is local to `task-V-1170/local-ops`; no main merge, push, deployment or activation.
- The source worktree fingerprints match for `app/backend_codex.py` (`c38e14e089ef1cc4a80c4b3691cb9abc27ec4e27583a77f196eba97cffec4eae`), `app/eval_admission.py` (`76a14cf818093c2d4107758515d6611a3c2ef3fe4c1662aed077bb2c3838ba66`) and `tests/test_eval_admission.py` (`74854f3b3c5092f64ef95f5ea95b53c53b41309c92981064d4a2749241dfeed8`). The integrated backend hash is `df9c3f6c9b693ed0cd73d0adf0a92d01a79312a94df1d305cce4b92daf723d5c`; it also retains earlier current-main native-path hunks. The source delta passes eval-only advertised non-empty effort strings unchanged, including `ultra`; ordinary worker/UI enum, normalization and admission remain in place. The eight-file source delta also updates closure/handoff/token notes/mutation script and the V-1166 changelog entry. The stale V-1166 `REPORT.md` remains explicitly historical.
- Focused integrated command covering eval admission, native backend, sessions, route surface, quota, workflow and MCP stdio: **770 passed, 0 failed, 0 skipped** in 30.73 s. `scripts/check_instruction_contract.py` passed. `app` imported from this QA worktree. A committed test passed baseline and failed at its intended effort-equality assertion when the eval passthrough was mutated to clamp `ultra` to `high`; source SHA-256 was restored exactly.
- Frozen coding-v2 plan: 4 fixtures × 2 models × 6 advertised efforts = **48 one-shot task invocations**, with all 8 original RED/GREEN controls passing. Plan hash `96f396629caa8348ae923d103b7742afc1171e16d98e4fbd34d0b1a882a9f9c2`; run-order hash `d8e8d01bfa62502a5a20c32e753df8487870d1a6c4fe4907d467912eba208f42`. All 16 model-input/hidden-reference files and 6 original root artifacts still match their frozen hashes. The unchanged source fixture manifest is `64ac99c3f6ea62dbf6dfd72cddc0cddc15348b037ada6c73a702e01286ea7b3f`.
- The original limits remain 56 calls, 5,400 seconds, concurrency 1 and subscription-only/no retries/API fallback. The 500,000 generated-token value is an observed stop-remaining threshold, not a hard cap. The v2 manifest is hash-frozen but `dispatch_ready=false`; root acceptance, live activation and root-issued grant remain required. Actual grants/inference/provider/account/CLI-generation calls: **0**.
- No new full-suite run was made after the narrow ultra delta. The preceding corrected full-suite result remains **7,625 passed, 2 failed, 60 skipped, 7 warnings**; the two reds were image-retry timeout and long-TMPDIR worktree-name collision. Earlier invalid-environment full run remains **7,360 passed, 14 failed, 62 skipped, 251 errors**. Skip reasons were not captured. These results are not recast as full-suite green.
- Before this delta, the corrected 18-node rerun was **16 passed, 1 image-retry timeout, 1 fixture-setup error**. A later matched browser pair on the prior candidate and accepted main ran the two browser nodes with the declared fixture plugin: workflow-card passed on both; image-retry timed out on both. Those results remain historical and do not imply the new ultra delta was exercised by a full run.

## Current integrated source and evidence

Reading order: `app/eval_admission.py` and `app/backend_codex.py` for frozen admission and native parameter handling; `tests/test_eval_admission.py` and `tests/test_backend_codex.py` for committed behavior guards; `app/routes/bg.py`, `app/mcp_stdio.py`, `scripts/wf_run.py` and `scripts/wf_adapters.py` for unchanged quota, workflow and recovery callers; then this receipt's focused and historical test evidence.

The current QA branch preserves the existing main fixes and adds the V-1166 source delta through Git history, including the current-main V-1228 research files. `git diff --check` passed after integration. The exact imported app path is `/home/kesha/orchestra/worktrees/home-kesha-orchestra/local-ops/app/__init__.py`. The source worker's final receipt SHA-256 is `27ddc030453275d41ae965a6d4892ab7a35c007bfaa9e18ffb88c6bb710afef4`; the new 132 KiB source raw bundle and its logs are preserved in ignored local storage at `.orchestra/private/V-1170/effort-20261102-source/`. The source-worktree product hashes and the preserved raw-log hashes were verified against that receipt; integrated `app/backend_codex.py` also contains the earlier current-main changes, while eval admission and its test retain the source hashes. The worker's final receipt records 271 completed regression tests across disjoint partitions, two corrected late-identity intended-assertion mutations, one combined attempt exit 124 (incomplete), and withdrawal of the former invalid three-mutation claim. Those source-host checks are source evidence, not replacements for the host integration result above.

The source leaves the legacy ordinary effort enum and ordinary non-eval clamp unchanged. In the eval actor path, `CodexBackend.__init__` rejects non-string/blank effort and preserves any non-empty advertised value unchanged. Eval manifest validation now freezes non-empty effort strings, requires exact model/effort matrix equality and enforces the existing call cap; dispatch rechecks against that frozen map. The committed tests cover ultra/future-advertised passthrough, ordinary normalization, matrix completeness, cap refusal and the corrected late-identity zero-send boundary.

`python scripts/check_instruction_contract.py` passed. The focused command used `uv run --frozen --no-sync --offline python -m pytest` over `tests/test_eval_admission.py`, `tests/test_backend_codex.py`, `tests/test_session.py`, `tests/test_routes_surface.py`, `tests/test_quota_gate.py`, `tests/test_dynamic_workflows.py` and `tests/test_mcp_stdio.py`; result **770 passed, 0 failed, 0 skipped**. Raw output: `.orchestra/private/V-1170/integrated-20261102/ultra-mapped.log`. The dedicated environment omitted inherited auth, service/database and `NOTIFY_SOCKET` variables; pytest basetemp was under `/var/tmp/orchestra-v1170-ultra-qa-20261102/`.

The new committed-test mutation used `test_native_thread_and_turn_use_normal_backend_without_experiment_sandbox`: baseline passed; replacing eval passthrough with the legacy clamp produced an `AssertionError` at `assert backend.reasoning_effort == expected_effort`; `app/backend_codex.py` returned to its exact pre-mutation SHA-256 `df9c3f6c9b693ed0cd73d0adf0a92d01a79312a94df1d305cce4b92daf723d5c`. Test blob `6e34ba58f23c5c9cc4a148e4c7b20c713e29622d`. Mutation receipt/logs: `.orchestra/private/V-1170/integrated-20261102/ultra-mutation.json` and `ultra-mutation-*.log`.

## Frozen v2 plan and dispatch boundary

The private builder used the previously captured metadata-only Codex CLI 0.166.0 `model/list` evidence; it did not repeat metadata probes. Terra and Sol each advertise `low, medium, high, xhigh, max, ultra`. The generated run order has 48 rows, one per fixture/model/effort pair, no duplicates or omissions, with sequence 1–48. Builder validation and a second read-only verification passed: 16 model-input/hidden-reference file hashes, 6 root artifact hashes, 8/8 fixture controls, manifest hash, run-order hash, 56-call/5,400-second ceiling and all six efforts per model. The v2 plan files and verification record are local-only under `.orchestra/private/V-1170/integrated-20261102/`; manifest file SHA-256 is `cc382e0e8ecd636bc1bc774cd1a71047ff0e4749cce63b61d195509377a352b2`.

This is a prepared frozen plan, not live readiness or execution permission. `dispatch_ready=false`; no actual grant was issued. The parent retains root acceptance, activation and one-shot grant issuance. No effort was omitted or mapped to `high`, and the ordinary worker route was not expanded. Source HEAD `8b74515c…` is integrated only in this local QA candidate and is not live in main.

The only tracked working change for this receipt update is `.orchestra/tasks/V-1170/receipt.md`; staged whitespace validation and `uv run --frozen --no-sync --offline python scripts/secret_scan.py --staged` passed. Source/private raw evidence and v2 plan files remain under ignored local storage and are not staged.

## Historical prior profile-path QA receipt

The following sections preserve the earlier receipt for the profile-based candidate; its old app/server identities and profile-blocker conclusion apply only to that earlier QA snapshot and are not current native-path status.

### Earlier profile-path V-1170 receipt

### Integrated source and custody

QA ran on integrated HEAD `86a640e71e42e1106030461903f65b2f71c18ec4`, including corrected source `d122996778b9d3f61d1cec14eb09941c6233b7ed` and accepted main `a215e0ea0ead690283d76ad0b28e4f28ca46a845`. The source worktree remains clean at d122; QA did not edit it or merge the QA branch to main. V-1171 contributed test isolation changes, not product code.

The V-1166 host-preservation receipt reports 3,484 regular files / 508,458,914 bytes, zero symlinks, successful before/after verification, zero missing or mismatched canonical files, six allowlisted public task files, and zero file contents deleted. The final safety product manifest matches feature source HEAD for all nine entries. The eight product/source-test files remain byte-identical in the integrated QA tree; the corrected route snapshot SHA-256 matches the supplied value.

| Integrated source file | SHA-256 |
|---|---|
| `app/eval_admission.py` | `929433ef14247686bb73b309c7ebc7d8336a31cb98c3e6e9d4224071a2a86095` |
| `app/eval_fixtures.py` | `acaebaecdf60829fae074fcf21ef1d28b2788b7e5f74c67f58c1fa896f36cf39` |
| `app/backend_codex.py` | `2ecff357fec5f8debd3c4805a316a6bbbdd2cebd35d8b19ff58f70c26e9c9203` |
| `app/routes/bg.py` | `17935fa2455cc87d7046f0ffea7d6e9751837073558aa7e90890217d2ec490f4` |
| `app/mcp_stdio.py` | `d7274c0326e17f74d5cd41551ae106dcc3f5a904c0a24ad2a93f947a32c81b06` |
| `scripts/wf_run.py` | `4da8f6227e5baab9583808e2e0e00db90b53121e9338c78fadfed2c9027f67fb` |
| `scripts/wf_adapters.py` | `ac879873cf0911e9d7ef69d4155d8863a5e8d2e1df6f96dc7819c0b4fb1db8b7` |
| `tests/test_eval_admission.py` | `fa525034ea5512a2f6a6a87212f2f85cf9410d6161a78c0248d4852f2d72248c` |
| `tests/route_surface_snapshot.json` | `9214fdb6a5de3e4dfb140cab79e9d1e653af77932854eca304bd8004dc57b50e` |

The archived `original/source-sha256.txt` is an earlier snapshot and differs on four later-final files; current source identity was checked against the final safety product manifest. `CHANGELOG.md` retains accepted main entries plus the V-1166 entry; it is the intentional mechanical union. Exact `app.__file__` is preserved in `.orchestra/private/V-1170/import-path.txt`.

All ten preserved historical PNGs were checked against their pre-full-run hashes. Nine were rewritten by the suite and restored from exact private backups; the tenth was unchanged. Final hash comparison: 10/10 match baseline.

### Checks

`python scripts/check_instruction_contract.py` passed. The app import resolved to the QA worktree. Before d122 integration, the 699-case core selection had one route-snapshot red for four newly added eval routes. After integrating d122 and a215, the same selection passed: **699 passed, 0 failed, 0 skipped**, 38.92 s, with one duplicate-operation-ID warning. This covered `test_eval_admission`, backend/model catalog, build signal, MCP, dynamic workflow, scheduler/quota, API, auth, and route-surface tests.

The single full runner was executed once: `uv run --frozen --no-sync --offline python scripts/run_tests.py`, using the isolated prepared venv, synthetic HOME/CODEX_HOME/Git identity, unset `NOTIFY_SOCKET`, and basetemp/cache outside Git. Result: **7290 passed, 18 failed, 60 skipped, 8 warnings**, 508.06 s, exit 1. No second full run was made.

The 18 failures were:

- `tests/test_frontend.py::test_codex_view_image_retries_after_initial_load_failure` — Playwright `TimeoutError`, `Page.wait_for_function`, 30 s.
- `tests/test_merge_test_gate.py::test_red_mapped_test_does_not_reach_merge_executor` — expected `TEST_GATE_FAILED`, received `TEST_GATE_INCONCLUSIVE`.
- `tests/test_merge_test_gate.py::test_mutation_gate_overlays_changed_snapshot_with_changed_test` — nested pytest `pytest_usage_error`.
- `tests/test_merge_test_gate.py::test_mutation_gate_rejects_updated_snapshot_without_source_guard` — expected `failed`, received `inconclusive`.
- `tests/test_merge_test_gate.py::test_mutation_gate_accepts_regression_test_that_breaks_on_target_sources` — expected `passed`, received `inconclusive`.
- `tests/test_merge_test_gate.py::test_mutation_gate_rejects_test_that_stays_green_on_target_sources` — expected `failed`, received `inconclusive`.
- `tests/test_merge_test_gate.py::test_mutation_gate_treats_pytest_missing_text_in_assertion_as_real_failure` — expected `passed`, received `inconclusive`.
- `tests/test_merge_test_gate.py::test_mutation_gate_ignores_git_environment_failure_but_counts_source_regression` — failed; exact trace is in the private full log.
- `tests/test_merge_test_gate.py::test_mutation_gate_skips_test_only_change` — expected `passed`, received `inconclusive`.
- `tests/test_merge_test_gate.py::test_linked_worktree_symlinked_python_retains_venv_packages` — expected `passed`, received `inconclusive`.
- `tests/test_merge_test_gate.py::test_argv_verbosity_really_prints_per_test_lines` — nested pytest exit 4: `--basetemp` cannot be the current directory or an ancestor; pytest identifies `PYTEST_ADDOPTS` as its source.
- `tests/test_merge_test_gate.py::test_green_mapped_test_reaches_executor[gate_db0]` — expected one executor call, observed zero.
- `tests/test_merge_test_gate.py::test_hung_node_becomes_a_named_red_not_inconclusive[2.0]` — same nested pytest `--basetemp` usage error.
- `tests/test_mcp_config_isolation.py::test_t3_config_dir_is_private_and_outside_worktree_and_tmp` — generated config was under the synthetic HOME located in `/tmp`.
- `tests/test_merge_target_oracle_386.py::test_t386_t1_pinned_oracle_passes_and_mutation_blocks_before_execution` — expected `passed`, received `failed`.
- `tests/test_merge_target_oracle_386.py::test_t386_t1_nested_target_passes_while_main_and_mapped_regression_reject` — expected `passed`, received `inconclusive`.
- `tests/test_merge_target_oracle_386.py::test_t386_t1_candidate_subset_metadata_cannot_hide_mapped_regression` — expected `failed`, received `inconclusive`.
- `tests/test_workflow_cards.py::test_dynamic_workflow_call_renders_detail_card_and_expands_answer` — Playwright `TimeoutError`, `Page.wait_for_function`, 30 s.

The full-run environment passed `PYTEST_ADDOPTS` with an external basetemp to child processes. Nested pytest rejected that path when it became a child run's current/ancestor directory; the raw log shows the error and resulting inconclusive statuses. The synthetic HOME under `/tmp` accounts for the config-isolation assertion. The two browser timeouts and pinned-oracle failed status remain as recorded. Pytest reported 60 skipped but emitted no skip-reason breakdown. Eight warnings comprised two multiprocessing-fork deprecations, one unawaited-coroutine warning, one duplicate OpenAPI operation ID, and four websockets deprecations. Raw output and run metadata are `.orchestra/private/V-1170/full.log` and `full.json`.

### Independent mutation checks

Two valid source mutations ran in separate temporary copies against the committed V-1166 test file. Clean baselines passed. Removing the dispatch quota guard made the quota-refusal test fail at its `answer.ok` assertion; removing issuance root proof made the non-root issuance test fail with `DID NOT RAISE`. Both mutated source files were restored to their exact pre-mutation SHA-256. A separate late-identity mutant was excluded: the fake backend lacks `Backend.events`, so that red followed an `AttributeError`, not the intended guard assertion.

No real grant was issued; tests used isolated synthetic grants. No native Codex CLI/profile request, provider request, inference, runtime activation, service/config change, or session change was performed. The previously documented V-1166 runtime profile limitation remains unprobed. No source/test changes were made by QA. The feature worktree remains clean at d122; the QA worktree is clean after this receipt update. `git diff --check` and staged secret-form scan passed. Full logs, mutation traces, PNG baselines/restoration checks, source hashes, and exact import path are local-only under `.orchestra/private/V-1170/`.

### Resumed isolated run of the 18 full-suite failures

After integrating d122 and a215, the exact 18 prior failing node IDs were run once with `PYTEST_ADDOPTS` absent and `--basetemp` supplied only on the top-level pytest command. Synthetic `HOME` and `CODEX_HOME`, Git identity, TMPDIR, basetemp and pytest cache were rooted under a dedicated `/var/tmp` directory outside `/tmp` and all checkouts. No database/auth environment variables or `NOTIFY_SOCKET` were inherited. The full suite was not repeated.

Result: **16 passed, 1 failed, 1 error**, 42.42 s, exit 1. `PYTEST_ADDOPTS` was absent. The earlier nested pytest basetemp usage errors did not recur; the config-isolation test now passed, and the pinned-oracle test that previously failed also passed in this targeted set. The remaining red is `tests/test_frontend.py::test_codex_view_image_retries_after_initial_load_failure`, still a Playwright `Page.wait_for_function` timeout at 30 s. `tests/test_workflow_cards.py::test_dynamic_workflow_call_renders_detail_card_and_expands_answer` errored during fixture setup: pytest could not find `dashboard_browser`. The raw setup/timeout traces are in `targeted18.log`; the exact 18-node argv, clean environment, target-root before/after `du`, and `df` readings are in `targeted18.json`.

The target-only temporary root remained at the recorded location and used 13,209,600 allocated bytes after the run (36,864 B at the pre-run stat/du snapshot; +13,172,736 B; both du RC=0). Its root device/inode was unchanged. The same filesystem df used 305476567040 B before and 305499901952 B after; available space moved from 5418070016 B to 5394735104 B. No old temp data was deleted. The 10 PNGs still match their saved pre-full-run hashes, with no further restoration needed. No additional tests were run after these red/setup results; no source or assertion changes were made.

### Matched two-version browser pair

The two requested browser nodes were run against accepted main `a215e0ea0ead690283d76ad0b28e4f28ca46a845` and integrated candidate `86a640e71e42e1106030461903f65b2f71c18ec4`, once each. Minimal source copies were built outside the checkout from 326 files / 10,014,720 archive bytes (baseline) and 328 files / 10,065,920 archive bytes (candidate). They contain the app, scripts, the two test modules, conftest, required policy/pipeline files and one image asset; no data tree, QA DB, artifacts or private V-1166 evidence. Each copy received only a fresh empty synthetic Git directory because the tests' `_repo_scope()` helper calls `git rev-parse`.

Fixture registration comes from `tests/test_workflow_cards.py` declaring `pytest_plugins = ("tests.test_frontend",)`; `dashboard_browser` is defined by `tests/test_frontend.py`. The previous selected-node invocation did not expose that fixture and failed at setup. The matched invocation explicitly loaded the declared plugin with `-p tests.test_frontend`; both requested test bodies then ran in both copies.

| Source | Image-retry test | Workflow-card test |
|---|---|---|
| Baseline `a215e0e` | `Page.wait_for_function` timeout at 30 s | passed |
| Candidate `86a640e` | same `Page.wait_for_function` timeout at 30 s | passed |

For the image test, both runs used the test's same ordered producer: first image request returns 404; after the tool-result event the test waits for `naturalWidth > 0`. `tests/test_frontend.py`, `tests/test_workflow_cards.py`, app JS, CSS, dashboard template and `app/main.py` have identical hashes in the two copies. The image timeout therefore remains unassigned by this paired comparison. The workflow-card timeout from the earlier full run did not recur in this pair; that historical full-run result remains unexplained, not reclassified as flaky.

The pair used the same prepared locked venv, browser binary, isolated synthetic HOME/CODEX_HOME and process environment with `PYTEST_ADDOPTS` absent; top-level basetemp was a CLI argument. App imports resolved to each corresponding source copy. The target root is outside `/tmp` and all existing checkouts; its exact path, source-copy hashes, environment, logs, `du` and `df` readings are in `.orchestra/private/V-1170/matched-browser-pair.json` and adjacent logs. The target root ended at 29,388,800 allocated bytes; free space changed from 5,693,059,072 to 5,682,118,656 bytes on the same filesystem. Old temporary roots/logs were left untouched. No further tests followed this pair; no source or test file was edited.

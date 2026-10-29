# V-1119 — routing implementation and compatibility repair

The orchestrator reports that host acceptance confirmed all original ten source hashes, absence of the duplicate patch, both instruction/pipeline contracts, and 278 focused tests. Its required full run then returned **6588 passed, 54 skipped, 15 failed in 417s**. That result preceded the compatibility repair below; it is reported evidence, not a locally inspected full-suite log. The task is **not merged**, and no full-suite green result is claimed.

The worker now returns **18 real source/test files**, listed with baseline/result SHA-256 hashes in `verification.json`. All are retained on disk. The original ten hashes remain unchanged; this pass adds eight compatibility/test-isolation files. No implementation exists only in a report or patch. The public duplicate `changes.patch` remains absent; its earlier original is private local evidence.

## Reading order and exact changed files

Read the canonical `model-routing.md`, shared admission in `app/models.py`, MCP normalization and actual one-shot dispatch, then the regression tests. Existing unchanged manager and HTTP callers distinguish agent admission from manual dashboard actions.

Original ten files, already hash-confirmed by host:

- `app/models.py`: hub-only ordinary agent admission independent of stored catalog flags; explicit Claude API-credit task admission and manual/legacy lookup boundaries retained. Hub reason metadata has no creative-importance threshold.
- `app/mcp_stdio.py`: pass explicit billing to shared admission; refuse unsupported hub one-shot jobs before queueing; retain actionable refusal metadata.
- `scripts/wf_adapters.py`: gate actual provider dispatch; zero-cost refusal before native subscription calls; preserve explicit credit admission and no-fallback behavior.
- `.orchestra/pipelines/default/prompts/modules/model-routing.md`: coherent English owner decision effective 2026-10-29 15:11 KRS; local Codex orchestration, ordinary hub workers, general hub Sol and hub Sonnet/Opus for any creative work. Protected data, live infrastructure, spending/restart/deletion boundaries and idle native worktrees remain protected; historical quality evidence grants no native-route permission.
- `.orchestra/pipelines/default/prompts/modules/dynamic-workflows.md`: describe the existing missing hub one-shot adapter and explicit authorized credit path.
- `CHANGELOG.md`: functional routing behavior and Python activation boundary.
- `tests/test_agent_hub_routing.py`: admission/dispatch refusal, legacy enabled flags, permitted hub aliases, manual selection, credit opt-in and no-fallback behavior.
- `tests/test_models.py`: remove obsolete literal routing-hint assertions.
- `tests/test_model_gates.py`: visibility/agent-flag coverage on permitted hub models.
- `tests/test_dynamic_workflows.py`: authorized credit fixtures for successful workflow/alias/workspace paths, with mocked provider effects.

Eight additional files in this pass:

- `tests/conftest.py`: a named `configured_hub` fixture supplies synthetic settings to the real hub configuration validator. The cgroup isolation fixture clears inherited `ORCHESTRA_AGENT_CGROUP`, `ROOT`, `CGROUP_REQUIRED` and `JOB_CGROUP` before each test and restores the runner's original state afterward. Production cgroup code is untouched.
- `tests/test_manager.py`: the seven reported native-child fixtures now choose hub Sol with synthetic hub configuration. Role denial before worktree creation, allowed spawn, worker-kind denormalization, pipeline/profile inheritance and explicit profile override still exercise real manager behavior. Existing parent records stay valid legacy/local data.
- `tests/test_api.py`: orphan-guard children use hub Sol. Real deletion refusal with live children and explicit-force override remain asserted through HTTP.
- `tests/test_toggle_live_agent.py`: exercise enabled → disabled refusal → enabled recovery on a permitted hub target, preserving runtime lookup throughout.
- `tests/test_quota_wait_queue.py`: change only `test_model_change_rechecks_held_delivery_with_new_route_policy`. Both initial/direct deliveries switch to permitted hub routes through the real `AgentSession.change_model`, persistence and admission. Synthetic hub telemetry admits the model change first; before real queue release Claude becomes exhausted while Sol retains capacity, then Claude capacity recovers. Held state, recovery using the same delivery, submitted state and absence of duplicate delivery remain asserted. The old fake model-change implementation was removed. Only provider submission and telemetry are fake; model change, its own hub-capacity check, persisted new route and queue release run for real.
- `tests/test_default_pipeline.py`: remove the prose/formatting anchor-count assertion. Keep model-routing module membership, exact-once inclusion for spawn-capable roles and exclusion from terminal workers, without literal wording anchors.
- `tests/test_agent_cgroup_env_isolation_v928.py`: retain consecutive-test direct-write isolation; add inherited-state clearing/restoration and explicit production fail-closed checks.
- `tests/test_runtime_process_group.py`: the real-stdio resume test explicitly configures its fixture-proven disposable cgroup parent with `CGROUP_REQUIRED=1`; it cannot depend on a live runner's group or silently disable the production requirement. This body remains unexecuted here when the existing delegation fixture skips.

No production change was needed in this compatibility pass. Quota policy, credential/data guards, service/deployment settings, temporary rules and neighboring tasks were not edited.

## Cgroup failure: controlled baseline comparison

Before changing test isolation, inject inherited `CGROUP_REQUIRED=1` with no `CGROUP` and run the CLI-version regression plus the real-stdio resume regression. With the current routing code: **1 failed, 1 skipped in 77.62s**. Replacing only admission with the previous implementation in memory gives **1 failed, 1 skipped in 18.57s**, with the same failure:

`RuntimeError: delegated agent cgroup is unavailable; refusing to launch provider process`

The CLI-version test failed before its mocked CLI launch, at unchanged `agent_process_options`. The real-stdio test was skipped because this worker environment cannot create a delegated cgroup. This is a limited in-memory admission contrast, **not an untouched-main checkout comparison**. Summaries are in `cgroup-current-summary.log` and `cgroup-baseline-summary.log`; raw paths and probe details remain private.

The previous autouse fixture restored inherited cgroup state but did not clear it on entry. Consequently a required-but-missing inherited group reached unrelated fake-provider tests even when no previous test leaked state. The new fixture isolates only tests; explicit required-but-missing state set inside a test still raises the production error.

A new committed regression checks inherited-state isolation and restoration. Replacing its fixture implementation in memory with the previous restore-only function makes that test fail (**1 failed**, expected negative control). `cgroup-isolation-mutation.log` preserves this check. With the final fixture and a deliberately broken inherited environment, the relevant tests return **7 passed, 3 skipped**. No real provider process or paid call was launched. The three skipped real OS-cgroup cases still need a host with delegation.

## Actual local verification

Every test shell used provisioned **uv 0.11.28**, the default `.venv`, and unchanged locked dependencies. Tests imported the actual expanded source tree, with normal repository fixtures and the task's network-rejection plugin; no downloaded replacement source tree or supplemental import namespace was used. The plugin rejects IPv4/IPv6 connections, and does not replace quota, admission, lifecycle or data guards.

Common shell setup:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export PYTHONPATH="$PWD/.orchestra/tasks/V-1119"
export TMPDIR="$PWD/.orchestra/private/V-1119/tmp"
export GIT_AUTHOR_NAME='Orchestra Tests'
export GIT_AUTHOR_EMAIL='tests@example.invalid'
export GIT_COMMITTER_NAME='Orchestra Tests'
export GIT_COMMITTER_EMAIL='tests@example.invalid'
unset NOTIFY_SOCKET
```

Git identity applies only to disposable test task stores; no Git configuration or result commit was written by this source-only worker.

```sh
uv run --frozen python -m pytest -p offline_checks tests/test_quota_wait_queue.py::test_model_change_rechecks_held_delivery_with_new_route_policy tests/test_manager.py::TestProfileInheritance tests/test_manager.py::TestIsOrchestratorDenormalization tests/test_manager.py::TestPipelineInheritance tests/test_manager.py::TestValidateSpawnIntegration tests/test_manager.py::TestCanSpawn tests/test_api.py::TestDeleteOrphanGuard tests/test_toggle_live_agent.py tests/test_default_pipeline.py tests/test_agent_cgroup_env_isolation_v928.py tests/test_backend_claude.py::test_history_import_requires_exact_cli_version tests/test_runtime_process_group.py -q --timeout=20
```

**87 passed, 3 skipped in 39.61s** (`compatibility-repair.log`), before strengthening the queue test to use the real model-change path and explicitly binding the stdio fixture group. All reported routing/fixture failures are included; final rechecks below cover those two later test changes. The CLI-version regression passes; the three OS cgroup cases are skipped for unavailable delegation, not removed.

```sh
uv run --frozen python -m pytest -p offline_checks tests/test_workflow_scheduler.py tests/test_quota_wait_queue.py tests/test_backend_codex.py::test_fake_backend_fixture_isolates_inherited_cgroup_requirement -q --timeout=20
```

The first run returned **42 passed in 22.35s** (`queue-cgroup-compatibility.log`). After replacing the fake model change with the real session operation, the final full queue/scheduler rerun returned **42 passed in 32.87s**, using `--timeout=45` (`queue-cgroup-final.log`). Includes complete queue and scheduler/cgroup policy tests with final source.

```sh
export ORCHESTRA_AGENT_CGROUP_REQUIRED=1
export ORCHESTRA_AGENT_ROOT='/unavailable-test-root'
export ORCHESTRA_AGENT_JOB_CGROUP='/unavailable-test-root/jobs'
unset ORCHESTRA_AGENT_CGROUP
uv run --frozen python -m pytest -p offline_checks tests/test_agent_cgroup_env_isolation_v928.py tests/test_backend_claude.py::test_history_import_requires_exact_cli_version tests/test_runtime_process_group.py -q --timeout=45
```

**7 passed, 3 skipped in 38.51s** (`cgroup-isolated-final.log`) on the final cgroup test source. This explicitly tests the inherited state that caused the baseline failure; these variables were scoped to that test shell. The final rerun used `--timeout=45`: an intervening run with the former 20-second limit returned 6 passed, 3 skipped and one setup timeout while cold-importing aiogram/Pydantic in an unrelated autouse fixture, before the test body. No production or fixture protection was removed to address that import timeout.

```sh
uv run --frozen python -m pytest -p offline_checks tests/test_agent_hub_routing.py tests/test_hub_model_reason.py tests/test_models.py tests/test_model_gates.py tests/test_dynamic_workflows.py -q --timeout=20
```

**194 passed in 46.19s** (`routing-after-compatibility.log`). The original routing implementation remains green after global fixture isolation changes. Counts across commands overlap and are not summed as unique tests.

Final real model-change check: `uv run --frozen python -m pytest -p offline_checks tests/test_quota_wait_queue.py::test_model_change_rechecks_held_delivery_with_new_route_policy -q --timeout=45` → **4 passed in 33.90s** (`real-model-change.log`). Both initial/direct and admitted/held-then-recovered branches pass with real session model changes. The host must reconcile this named test with V-1121; no quota implementation was changed.

All 18 real source-file hashes were checked against the manifest; all changed Python compiles. The original ten source hashes are unchanged. Public task artifacts are checked for actual remote identities/absolute workspace paths and secret shapes. Publication scan coverage/results are in `publication-checks.log` and `verification.json`.

Actual imports are recorded relatively as `app/__init__.py`, `app/models.py`, `app/mcp_stdio.py` and `scripts/wf_adapters.py`. Absolute host-side confirmation belongs in the orchestrator's private evidence. Historical local contract logs still record the broker copy's missing `CLAUDE.md` symlink; the newer **host** instruction/pipeline PASS is explicitly attributed to the orchestrator. Root files and instruction checkers were not changed.

## Acceptance boundaries and coordination

**Must-fix before merge:** import the eight additional real files and repeat the required host full-suite runner. The earlier 15-failure run is not superseded by a new full run. No merge should be inferred from focused green tests. Verify the final host commit and clean status after broker return; this copy has no `.git` and cannot supply a result commit SHA.

The queue-file overlap with V-1121 is limited to the named model-change test. A coordination message was queued through the available broker outbox; this runtime exposes no direct Orchestra `send_message` tool, so direct peer delivery was not confirmed during the turn. Preserve V-1121 changes during integration; no quota source was changed here.

**Open architecture boundary:** `wf_run` still has no hub one-shot adapter. Ordinary work must use existing hub workers. A new adapter/data-transfer contract was not invented in this task.

Real OS cgroup resume behavior remains unverified here because delegation is unavailable. Production cgroup validation remains fail-closed and is covered by explicit tests. Manual model selection, persisted routes, enabled/disabled flags, queue recovery and duplicate prevention retain focused coverage. No paid evaluations/model review, services/restarts/deployment, protected-data transfer or native-thread deletion/migration occurred. Disk Python changes are not claimed live; activation follows the normal owner-approved lifecycle.

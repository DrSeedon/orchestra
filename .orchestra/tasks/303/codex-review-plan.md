## Summary

The four-release decomposition is genuinely vertical and correctly ordered A → B → C → D. The plan keeps recovery separate from prevention, assigns credential isolation to C, and explicitly avoids presenting D’s path guard as enforcement.

Current source references for the existing restart path are accurate: `_DRAIN_DEADLINE_S = 900`, `prepare_restart_handover`, rollback, `tools_are_stale`, and turn-boundary refresh all exist. The captured RED outputs also match the immutable tests.

However, the frozen tests do not mechanically enforce most load-bearing safety claims. One named RED test is already green, while the remaining tests can be made green using names and inert strings without implementing the promised security or recovery behavior.

Evidence that the plan itself was reviewed includes this verbatim line:

> “A prompt, approval callback, path parser, or best-effort hook is not the boundary.”

`cross-family verdict unavailable` because Anthropic usage is exhausted through 2026-08-18T07:00Z.

## Findings

blocking: `docs/tasks/303/test_release_a_recovery.py:41` — `test_ta_existing_restart_path_waits_and_refreshes_old_mcp_at_a_turn_boundary` is already green in the captured RED run (`F.`), although the plan calls both named T-A tests “committed RED.” This is the frozen oracle for active-turn waiting, failed-handover rollback, and old-MCP boundary refresh, but it only confirms pre-existing source strings. It cannot distinguish preservation from a broken implementation that leaves those strings unused → add a genuinely RED integration seam before implementation, covering: a live non-adoptable turn prevents signalling; failed handover restores admission; an adopted Codex turn completes; and the next boundary replaces the old MCP process/path.

blocking: `docs/tasks/303/test_release_a_recovery.py:18-38` — Release A’s remaining RED test checks an exact `ExecStart`, four function names, and text anchors such as `os.replace` and `previous_selector`. It does not exercise any failure cut promised by `plan.md:51-53,147,173`. An implementation could satisfy it while changing the selector before durable state, restoring the wrong link, accepting traffic from a failed staged supervisor, or losing rollback after POST scheduling → freeze an executable scratch-runtime transaction test covering every listed cut: before selector, after selector/before POST, 409, failed new health, and failed post-health verification, with exact selector/state restoration and a positive old-runtime health control.

blocking: `docs/tasks/303/test_release_b_identity.py:26-35` — the claimed “one fail-closed project identity” oracle only searches each consumer for the substring `execution_identity`. An unused import or comment passes; removing the actual launcher call while retaining the import stays green. It therefore does not enforce the AC at `plan.md:180` that removing any consumer’s launcher must make the oracle red. The rehearsal test likewise checks only vocabulary, not UID or `EACCES` outcomes → add executable/mutational tests for each named seam—backend, bg/cron, local SSH, MCP, acceptance, merge, workspace, and prompting—asserting observed child UID, positive project/cache writes, and protected-target `EACCES`, plus dependency-bearing Orchestra and DND compatibility runs.

blocking: `docs/tasks/303/test_release_c_credentials.py:11-48` — Release C can turn green with four empty functions and a rehearsal file containing provider/anchor words. Nothing mechanically proves controller/tool separation, that native tools are disabled, that project operations use Release B’s UID, or that one failed provider holds the global latch closed. Most critically, no oracle executes the required positive startup/authenticated-turn/refresh and negative EACCES matrix for all four providers → freeze a result-schema validator and production-shaped harness whose four provider rows require exact binary/config hashes, positive auth and refresh evidence, negative Read/Bash/test/MCP/background evidence, zero canary leakage, and an all-provider fail-closed latch.

blocking: `docs/tasks/303/test_release_d_env.py:20-51` — Release D’s frozen oracle covers only three keys in `MCP_BASE_ENV`, removal of literal `.env`, one flattening-comprehension spelling, and five guard strings. It contains no test for session/scope/access-mode capability binding, operator-route denial, archive/kill revocation, per-server environment isolation, value-free auditing, safe `.env` migration, or the requirement that B remains effective with the guard disabled. It can also be bypassed by rewriting the same flattening behavior with different syntax → add behavioral oracles for cross-session/scope/access-mode rejection, operator denial, revocation, two-server env non-leakage, unchanged-versus-modified `.env` cleanup, and a guard-disabled rerun of B’s direct attacks.

blocking: `docs/tasks/303/plan.md:51-52,155` — the failure-cut contract is internally incomplete. `POST /api/restart` returns after scheduling the background restart, before signalling or new-process health; therefore “409/timeout restores the previous selector” covers only preflight/request outcomes. After the old supervisor signals itself, a staged process may fail or briefly accept before the external manager detects bad health. The plan says to restore the selector “while no accepting supervisor exists” but specifies no mechanism that establishes or enforces that condition → define the transaction precisely: readiness/admission must remain closed until the selected executable and postchecks are verified, with an external rollback owner that survives supervisor death and can atomically restore the selector during systemd restart loops.

suggestion: `docs/tasks/303/plan.md:41-43` — Release A promises the same direct-runtime contract for `deploy/orchestra.service.template`, but the frozen oracle examines only `deploy/orchestra.service`. The current template has a different installation layout, direct `.venv` references, `ExecStartPre=uv sync`, and no socket/FD-store contract. A future installer could therefore remain incompatible while T-A is green → extend the delivery oracle to the template and installer, while parameterizing installation roots rather than freezing the live `/home/kesha` layout onto new installations.

## Verdict

**CHANGES REQUIRED**

Blocking findings: 6. The architecture and release boundaries are directionally sound, but the immutable RED gate is not strong enough for recovery, UID isolation, credential separation, or scoped capability/secrets migration. The already-green T-A test and the viable missing behavioral oracles must be corrected before implementation begins.

## Round (2026-08-16T16:05:20Z)

## Summary

All seven round-1 findings are materially addressed in the plan and frozen tests. Every named v2 test is RED for missing behavior rather than collection failure. The four releases remain vertical and correctly ordered, and A now specifies rollback ownership across supervisor death.

Evidence of direct review: “The external owner may stop/start only after a post-signal failure, while the pending gate is closed.”

Two evidence-binding gaps remain. `cross-family verdict unavailable`.

## Findings

blocking: `docs/tasks/303/test_release_b_identity.py:130`, `test_release_c_credentials.py:70`, `test_release_d_env.py:183` — B, C, and D only read pre-generated JSON; they never invoke the named production-shaped rehearsal. Hashing the rehearsal script does not prove that script produced the observations: fields such as `observed_child_uids`, `protected_write_errno`, `authenticated_turn.passed`, `archive_revocation`, and leak counts can be handwritten while all implementation hashes remain current. That could approve a UID/credential/capability bypass → bind evidence to an actual privileged run, such as a root-owned attestation containing command, timestamp/nonce, producer hash and result digest, or make the acceptance command invoke the producer and validate its fresh output.

blocking: `docs/tasks/303/test_release_c_credentials.py:91-94` — “exact deployed binary/config hashes” is not mechanically enforced. The binary path comes from the evidence itself and may point to any existing file; `config_sha256` is checked only for length. Thus `/bin/true` plus an arbitrary 64-character config value can satisfy the current-hash gate while the deployed provider binary/config remains untested → derive binary and config paths from the runtime registry or service configuration independently of the report, then recompute both hashes. Include the effective merged configuration where providers use multiple files or user-level settings.

suggestion: `docs/tasks/303/test_release_b_identity.py:74-81` — the raw-launch AST gate recognizes fully qualified spellings only. Direct imports or aliases such as `from asyncio import create_subprocess_exec` or `import subprocess as sp` evade it. Privileged seam evidence is the stronger gate, but resolving import aliases would make the stated mechanical claim accurate.

## Verdict

**CHANGES REQUIRED**

Prior findings: 7 resolved. New findings: 2 blocking, 1 suggestion. The plan architecture is ready, but B–D evidence must be bound to actual production-shaped executions and C must independently resolve the deployed binary/config before Phase 3 begins.

## Round (2026-08-16T16:24:02Z)

## Summary

Round-2 alias finding is resolved. Root attestations prevent direct report editing, and all v3 failures are missing-behavior failures. A’s recovery transaction and release separation remain sound.

Evidence of review: “A handwritten JSON or a report from another producer/run cannot satisfy the gate.”

Two security-relevant trust gaps remain.

## Findings

blocking: `docs/tasks/303/plan.md:77-98`, `test_release_b_identity.py:169-197` — the root wrapper and privileged producers are loaded from the ordinary repository and validated only against their current repository hashes. Before B activates, project agents still share the service UID and can replace those scripts; root then executes the modified wrapper/producer and attests its fabricated results. Matching current hashes proves identity, not trustworthiness → install the minimal wrapper and privileged probe components into a root-owned, non-service-writable location before execution, or use a fixed root-owned helper that runs untrusted producer logic without root authority and independently collects privileged observations.

blocking: `test_release_b_identity.py:179-197`, `test_release_c_credentials.py:109-129`, `test_release_d_env.py:197-217` — attestations are replayable. Timestamps need only be positive, and no test binds a run to the pending activation ID, current boot/live-state generation, or a maximum age. An old green B/D attestation remains acceptable after ownership, sudo policy, capability revocation, or other live state drifts; C’s protected-store fingerprint activation requirement is described in the plan but absent from its frozen oracle → require a one-use nonce issued by the activation transaction, bind attestation to activation ID and current live-state/inventory/store fingerprints, and reject already-consumed or stale attestations.

blocking: `docs/tasks/303/plan.md:107-120`, `test_release_c_credentials.py:151-163` — `/bin/true` substitution remains possible through common-mode ownership. The oracle obtains binary/config paths by calling the same new `app/provider_inputs.py` implementation used by `runtime_registry`; a faulty or malicious resolver can return `/bin/true` and arbitrary configuration files, after which both runtime and oracle agree and all hashes pass. The claimed root-owned selected-provider manifest is not independently parsed or compared by the frozen test → have the oracle read the fixed root-owned manifest directly, validate its ownership/mode and provider-specific executable selection, then compare those independently derived inputs with `resolve_provider_inputs`.

## Verdict

**CHANGES REQUIRED — third-round ceiling reached**

Prior round: both blockers remain partially resolved but not closed; alias suggestion resolved. New status: 3 blocking findings. Do not begin Phase 3 until these trust-root, replay, and common-mode provider-selection gaps are resolved. `cross-family verdict unavailable`.

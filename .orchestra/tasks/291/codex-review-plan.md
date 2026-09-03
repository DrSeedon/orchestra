## Summary

The Phase 2 direction is sound: independent quota topology, shadow-only first release, explicit fail-safe states, prospective evidence, and static-gate rollback are the right architecture.

However, the immutable RED suite does not yet protect several core safety properties. Most importantly, concurrent reservation is not specified atomically, evidence eligibility is aggregated where the plan requires per-bucket/per-stratum proof, and T3/T5 tests can pass without exercising real delivery or enforcement paths.

Exact command run:

```text
uv run python -m pytest -q docs/tasks/291/oracles/test_t1_schema_and_topology.py docs/tasks/291/oracles/test_t2_adaptive_gate.py docs/tasks/291/oracles/test_t3_shadow_delivery.py docs/tasks/291/oracles/test_t4_replay_evidence.py docs/tasks/291/oracles/test_t5_enforcement_rollback.py
```

Result: `16 failed in 1.49s`. This confirms all committed oracles are genuinely RED, but RED status alone does not make them sufficiently discriminating.

Architecture dissent preserved from this first round: the controller must treat reservation and eligibility as transactional, per-constraint safety contracts—not scalar calculations around an eventually consistent audit store.

## Findings

1. **blocking:** Concurrent dispatch reservation is not atomic. The plan says `u_eff` includes unsettled reservations and writes the decision before `backend.send` ([plan.md:52](docs/tasks/291/plan.md#L52), [plan.md:261](docs/tasks/291/plan.md#L261)), but it never requires “read current reservations → evaluate → append reservation” to occur under one SQLite transaction or bucket lock. Two callers can both observe the same headroom, both allow, and only then append distinct decisions. T2 merely supplies `inflight=1` in a sequential pure-function call ([test_t2_adaptive_gate.py:23](docs/tasks/291/oracles/test_t2_adaptive_gate.py#L23)); it does not run two simultaneous admissions against one store. Add an atomic reservation API and a concurrency oracle proving that two contenders cannot both reserve the same final headroom.

2. **blocking:** The evaluator interface applies one scalar `q95_next_turn_pp`, `guard_pp`, and `reserve_pp` to every constraint ([test_t2_adaptive_gate.py:48](docs/tasks/291/oracles/test_t2_adaptive_gate.py#L48)), while the plan defines q95 strata by constraint and reserve by bucket ([plan.md:115](docs/tasks/291/plan.md#L115), [plan.md:129](docs/tasks/291/plan.md#L129)). A Fable turn can consume different percentage increments in 5h, 7d-all, and scoped-Fable windows. Reusing one scalar can allow the binding constraint prematurely or hold unnecessarily. Require per-constraint q95/guard/reserve inputs and test materially different values across all three Fable constraints.

3. **blocking:** The evidence gate can qualify one healthy stratum as proof for every enforcement bucket. The plan requires three stable windows “для каждого enforcement bucket/constraint” and 20 outcomes for every allowed stratum ([plan.md:325](docs/tasks/291/plan.md#L325)), but the oracle uses scalar `stable_same_regime_windows`, scalar coverage/block/ESS metrics, and only one Codex outcome stratum ([test_t4_replay_evidence.py:34](docs/tasks/291/oracles/test_t4_replay_evidence.py#L34)). An implementation could enable Claude, Spark, or Grok using Codex-only evidence. Represent qualification per bucket/constraint and per enabled stratum; test missing, under-sampled, and drifted members individually.

4. **blocking:** The test named `test_t4_every_machine_gate_clause_has_a_named_failure` does not mutate every machine criterion. It never tests telemetry coverage below 80%, settled usable outcomes below 20, or `q95_binomial_lower_95` below 0.80, despite those fields existing in the fixture ([test_t4_replay_evidence.py:38](docs/tasks/291/oracles/test_t4_replay_evidence.py#L38)). Those omissions permit under-supported evidence to become eligible. Add one negative mutation for every criterion and reject missing fields fail-closed.

5. **blocking:** Time-causal replay is asserted but not tested. The reviewed artifact says verbatim: “Replay идёт по времени без look-ahead: q95/forecast на момент `t` видит только строки `<t`.” ([plan.md:309](docs/tasks/291/plan.md#L309)). The oracle only checks summary labels from the fixed #285 dataset ([test_t4_replay_evidence.py:19](docs/tasks/291/oracles/test_t4_replay_evidence.py#L19)); a hard-coded or full-dataset/look-ahead implementation can pass. Add paired replay fixtures differing only in future rows and assert all decisions before the divergence are byte-identical.

6. **blocking:** T3 does not exercise the real delivery topology it claims to freeze. It checks a method parameter, a standalone helper, an intent-kind lookup, and an empty status object ([test_t3_shadow_delivery.py:4](docs/tasks/291/oracles/test_t3_shadow_delivery.py#L4)). It never proves exactly one `backend.send`, decision-before-submit ordering, deduplication across admission refresh, terminal-event idempotency, interval settlement under concurrency, orchestrator coverage, or owner-versus-agent reserve authorization. A disconnected helper implementation could make the oracle green while production has no shadow observation—or duplicates delivery. Add integration tests at the actual `AgentSession`/`TurnManager` seams described in T3.

7. **blocking:** T5 has no successful enable path and does not test most enforcement barriers. Both authorization calls use `default_policy()`, which is shadow mode ([test_t5_enforcement_rollback.py:37](docs/tasks/291/oracles/test_t5_enforcement_rollback.py#L37)); there is no proof that qualifying evidence enables only named strata, CAS is enforced, stale evidence is rejected, controller exceptions demote atomically, or agent/internal-token API paths receive 403. There is also no assertion that `mode="enforce"` with valid evidence selects the adaptive decision. Add a positive path followed by targeted negative mutations; otherwise an implementation that always refuses enforcement—or one that bypasses authorization elsewhere—can pass.

8. **suggestion:** “Append-only” decisions and “immutable” evidence are prose properties, not schema properties. The proposed tables contain no trigger or other database-level protection against `UPDATE`/`DELETE` ([plan.md:146](docs/tasks/291/plan.md#L146), [plan.md:210](docs/tasks/291/plan.md#L210)), and T1 only checks table names and one legacy row value ([test_t1_schema_and_topology.py:108](docs/tasks/291/oracles/test_t1_schema_and_topology.py#L108)). Since evidence may later authorize enforcement, accidental mutation is telemetry corruption. Specify the enforcement mechanism and test rejected updates/deletes, required indexes, foreign keys, CHECK constraints, and all-or-nothing migration rollback.

## Verdict

**Changes required before approving Phase 2.**

The plan’s rollout boundary is appropriate, and all five oracle files are presently RED as intended. Approval should wait until findings 1–7 are reflected in the immutable oracles, because the current suite permits unsafe concurrency, cross-bucket evidence leakage, look-ahead replay, disconnected shadow wiring, and untested enforcement authorization.

## Round (2026-08-16T11:01:56Z)

## Summary

All eight prior findings are addressed in the revised plan and frozen oracles. The five oracle files match immutable baseline `f1a5460b24eb91b7408d11b0ecaa93bbdbb2571b`; current `plan.md` differs only by replacing the placeholder freeze wording with that exact SHA.

The five named commands produced the expected RED baseline:

- T1: 5 failed
- T2: 5 failed
- T3: 7 failed
- T4: 4 failed
- T5: 6 failed

Total: 27 failures, all attributable to absent controller/replay/schema/routes or current behavior lacking the planned shadow integration—not defective test setup.

## Findings

No new blocking findings.

Prior findings are closed:

- Atomic `BEGIN IMMEDIATE` reservation and concurrent two-connection oracle: resolved.
- Per-constraint q95/guard/reserve: resolved.
- Per-constraint/per-stratum evidence and every numerical threshold: resolved.
- Causal replay without future leakage: resolved.
- Real send/settlement integration and authorization coverage: resolved.
- Positive and negative deferred-enforcement paths, CAS, and rollback: resolved.
- Schema immutability, constraints, indexes, FK, and transactional rollback: resolved.

The T1–T4 boundary remains strictly shadow/advisory. T5 remains explicitly deferred pending new authorization and qualifying prospective evidence.

## Verdict

**APPROVE Phase 2 plan and immutable RED baseline `f1a5460b24eb91b7408d11b0ecaa93bbdbb2571b`.**

Implementation may proceed for **T1–T4 only**. T5 is not authorized.

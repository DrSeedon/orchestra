# Codex adversarial review — research #288, round 1

Recovery note: the background wrapper reported `review artifact is blind: execution never happened`,
but the job populated this complete `agent_message`, including a verbatim sentence found only in the
target. The paid round was therefore recovered as substantive and was not restarted.

## Summary

The architectural direction is credible: FULL would duplicate Orchestra’s enforced owners, and ADAPTER currently has no demonstrated consumer. However, two load-bearing claims are not established by the presented method: the “0 unique facts” result is circular, and the six-run pilot cannot distinguish capsule benefit from run/task/scorer noise.

Proof I read the target: “Full migration могла бы быть оправдана только обратным решением: сделать `openspec/specs/` единственным нормативным owner **и удалить/сделать производными** пересекающиеся AC/docs.”

The local arithmetic itself checks out: 13 represented facts, 55 placements, and `55 − 13 = 42` repeated placements.

## Findings

### blocking: `docs/tasks/288/research.md`, §3 — the “0 unique load-bearing facts” experiment cannot test unique value

The preregistration says reconstruction uses the tracker record and `docs/tasks/214/report.md`; “unique value” is then defined as facts absent from those same two inputs. The reconstruction was manually derived from that corpus. Consequently, it cannot discover a fact absent from its source corpus: zero unique facts is structurally favored by the experiment, not independent evidence that an OpenSpec workflow would capture zero new facts while a change was being developed.

The preregistration also does not contain or hash the fourteen-fact inventory. `evidence.json` asserts that fourteen facts were enumerated before counting, but the auditable pre-reconstruction artifact records only the counting rule. Fact selection and atomic boundaries therefore cannot be independently shown to have been frozen before the reconstruction result was known.

This invalidates:

- “**CONFIRMED**” for zero unique facts as an empirical comparison;
- “CONFIRMED counterexample к H1-фальсификатору”;
- the use of this result as confirmation of the FULL verdict.

The 55/42 arithmetic remains valid for the chosen matrix, and the reconstruction still demonstrates documentation duplication. To support the stronger claim, reconstruct from a temporally frozen pre-implementation corpus, then compare independently against later code/tests/report facts—or use an OpenSpec bundle authored contemporaneously without access to the final report.

### blocking: `docs/tasks/288/research.md`, §8 — six runs cannot attribute an observed difference to the capsule

Each task receives one A run and one B run. Autonomous-agent variance is therefore completely confounded with condition: a better B result may be ordinary sampling variance. “Same runtime/effort” does not control generation variance. The current PASS rule can accept SLICE from two lucky B runs out of three.

No procedure measures or bounds:

- repeated-run noise within A or B;
- task-selection sensitivity;
- answer-key/scorer reliability;
- scorer blindness to condition;
- inter-rater disagreement or deterministic scoring;
- order/position effects from appending the capsule;
- whether capsule facts existed at the historical handoff point rather than being reconstructed from final knowledge.

“Different runtime-shaped handoff” is also an outcome-aware selection criterion unless tasks and freeze points are fixed before capsule construction. Building capsules for completed tasks from final authoritative artifacts risks hindsight leakage into B.

This invalidates the proposed pilot as a measurement of benefit and therefore blocks the Phase 1 recommendation to proceed with that pilot as written. A viable pilot needs repeated runs or a larger preregistered sample, blinded deterministic scoring, frozen historical handoff inputs, and a measured within-condition noise baseline. The improvement threshold must exceed that measured noise.

### suggestion: `docs/tasks/288/research.md`, §2 — rename “1:1 mapping” and separate semantic overlap from observed drift

The table is useful, but it is not literally 1:1: for example, `proposal.md` maps to tracker description plus research plus plan, while delta specs map to plan AC, RED tests, code, tests, and report. It establishes overlapping responsibility and potential competing ownership, not measured drift.

Call it an “ownership-overlap matrix.” Mark each row as:

- enforced owner;
- writable normative owner;
- derived evidence;
- historical record;
- potential rather than observed drift.

This would strengthen the FULL rejection without overstating what was measured.

### suggestion: `docs/tasks/288/research.md`, §5 — narrow the categorical state claim

The proposed ownership boundary is sound for Orchestra, but “OpenSpec cannot be chat/session memory” is stronger than the evidence. Markdown can physically contain serialized session or runtime state; the demonstrated point is that OpenSpec does not provide the lifecycle, atomicity, replay semantics, native protocol fidelity, or security boundary required to own that state safely.

Prefer: “OpenSpec must not be authoritative for Orchestra runtime/session/native state.” Product intent may be canonical only after competing normative owners are removed. Derived capsules may reference live state identifiers, but should not own or replay that state.

### suggestion: sources and maturity — pin all load-bearing sources to the declared snapshot

The package, dependency, Node, postinstall, telemetry, supported-tool, Codex-path, and Grok-absence claims are consistent with the inspected primary material. The security discussion is appropriately cautious, and the supported-tools table confirms Codex uses `.agents/skills`, while Grok is absent.

However, several manifest URLs use `main` or mutable documentation pages even though the report claims an exact SHA snapshot. Preserve SHA-pinned raw files or hashes for all load-bearing source/code claims. For mutable docs, record captured content/hash. Also label issue-based hook/concurrency claims as evidence of missing documented capability or reported behavior—not definitive proof of every current code path unless source inspection confirms it.

## Verdict

**BLOCKING FINDINGS REMAIN**

FULL rejection remains a strong architectural recommendation, and ADAPTER rejection is reasonable absent a consumer. But the claimed empirical confirmation from #214 and the proposed six-run falsification pilot are not methodologically sufficient. Phase 1 should not be approved until those claims and the pilot design are corrected.

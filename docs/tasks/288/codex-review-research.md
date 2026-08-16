# Codex adversarial review — research #288, round 2

- Resume of round 1; first-round dissent is preserved verbatim in
  [`codex-review-research-r1.md`](codex-review-research-r1.md).
- Scope: verify that both blocking findings were actually removed from the changed research and
  return the final Phase 1 verdict.
- Status: launched 2026-08-16; substantive verdict is appended by the review job below.

## Round (2026-08-16T09:50:07Z)

## Summary

Both prior blocking findings are resolved.

The #214 result is now correctly limited to a descriptive duplication audit, with its circular source construction and unfrozen fact inventory disclosed. The revised pilot addresses hindsight leakage, run variance, position/length effects, scorer reliability, contamination, and preregistration.

Proof of reading the changed target: “P отделяет смысл от эффекта длины/структуры/позиции.”

## Findings

- Prior blocking 1 — **resolved**. The report no longer treats zero unique facts as prospective or causal evidence. The retained 13/55/42 arithmetic is appropriately scoped and auditable.
- Prior blocking 2 — **resolved**. The 27-run A/P/B design, chronological selection, handoff-time freeze, repeated controls, blinded scoring, agreement threshold, and noise-aware PASS rule make the pilot safely falsifiable for a discovery study.
- Prior ownership/state/source suggestions — **resolved**. The report distinguishes potential from measured drift, narrows the runtime-state claim to authority, and qualifies issue-derived claims.
- suggestion: Before running the pilot, preregister the exact aggregation code and handling of tied medians/missing runs. Three repetitions yield a coarse range-based noise estimate, so implementation details should not remain discretionary.
- suggestion: SHA-256 and byte length authenticate a captured mutable page only if its bytes remain stored somewhere. Preserve the captured S7–S12 and S17–S19 bodies alongside the hashes if long-term reproducibility matters.

## Verdict

**APPROVED FOR PHASE 1**

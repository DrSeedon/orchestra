<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The document traces the configured effort into `turn/start` convincingly and correctly separates quality from cost and latency. Its main weakness is terminology: it sometimes promotes a model-only resolver into a claim about the entire task-to-turn routing chain. Several confidence labels also exceed what the cited `N=1` or unpaired evidence can establish.

## Findings

1. **suggestion:** `docs/tasks/374/research.md:34-39,77-80,298` — “not task-aware” is too broad for the complete routing chain. The document itself says task class influences model selection, after which model determines effort. Therefore:

   - `resolve_effort` is model-aware and role-invariant;
   - end-to-end `task → model → effort` routing is indirectly task-sensitive;
   - it is not a direct task-aware effort policy.

   Replace the categorical conclusion with this narrower distinction. Otherwise a research task routed to Sol and a closed task routed to Luna demonstrably receive different efforts because of task routing, even though the resolver never reads task class.

2. **suggestion:** `docs/tasks/374/research.md:114-118,228-229,299` — the snapshot establishes seven idle stored-policy mismatches, but “stale” additionally implies a historical cause that the presented evidence does not fully reconstruct. Old provider-turn dates plus current mismatch do not identify which manifest revision governed each last turn. Call them “idle mismatches consistent with stale pre-policy state,” or provide per-row policy/version provenance before labeling all seven confirmed stale state.

3. **question:** `docs/tasks/374/research.md:41-45,63-65,130-132,298` — does rollout `turn_context` record the request Orchestra sent, or server-acknowledged effective settings? The artifact proves agreement among DB, argv, and `turn/start` payload, which strongly excludes a hidden Orchestra config override. Unless the event is emitted from Codex after resolving configuration, it does not completely prove the model executed with that effort. Clarify the event’s provenance and narrow “effective effort” to “observable turn request” if it is client-authored.

4. **suggestion:** `docs/tasks/374/research.md:187` — `LIKELY` overstates what #199 supports. Two Sol cases with one run per cell and unchanged binary acceptance show only “no observed xhigh benefit in these cases.” They do not make `medium` likely preferable across the class, particularly without repeat-run noise or cases where effort changes acceptance. Mark the row `UNCERTAIN / no observed benefit in this sample`.

5. **suggestion:** `docs/tasks/374/research.md:188,300-301` — “**CONFIRMED для NIAH**” is underspecified and risks implying an effort comparison. A `9/9 PASS` result at `medium` confirms only that this particular NIAH fixture was solved at medium. It does not confirm that raising effort is unhelpful, nor generalize to large-context extraction. Label it “CONFIRMED: medium passed this fixture; comparative effort effect UNMEASURED.”

6. **suggestion:** `docs/tasks/374/research.md:47-52,155-166,302` — #208’s monotonic three-point ladder is accurately transcribed: the gains are `1.758816` and `1.677315`, and both adjacent cost ratios are approximately `1.4737×`. But “LIKELY, только направление” still generalizes beyond a single observation per configuration with no uncertainty estimate. Prefer “OBSERVED in the published AA ladder; general direction UNCERTAIN.” This preserves the valid counterexample to “effort is always useless” without treating monotonicity as replicated evidence.

7. **suggestion:** `docs/tasks/374/research.md:201-216` — the proposed minimum experiment uses one task and explicitly admits that one run cannot demonstrate stability. It therefore cannot close the stated representative long-horizon evidence gap, only produce an exploratory case study. Separate:

   - a minimal mechanism/pilot run: one frozen task across three efforts;
   - a policy-validating study: multiple representative tasks, repeated or balanced orders, and independent blinded acceptance/rework evaluation.

## Verdict

**Needs revision; no blocking findings.** The numerical transcriptions visible in the artifact are internally consistent, and the central “representative long-horizon evidence is absent” conclusion is appropriately cautious. The principal corrections are to distinguish the model-only resolver from indirectly task-sensitive end-to-end routing and to downgrade confidence derived from unreplicated evidence.

Evidence that the artifact was read: “Цена ошибки не отменяет измерения: она может поднять допустимый budget/latency, но не превращает отсутствие gain в gain.”

## Round (2026-08-23T15:46:28Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

All seven prior findings are **FIXED**:

1. Resolver vs end-to-end task sensitivity — fixed.
2. DB mismatch provenance — fixed.
3. Observable request vs provider compute — fixed.
4. Closed-task confidence — fixed.
5. NIAH comparison scope — fixed.
6. AA ladder confidence — fixed.
7. Pilot vs policy-validating study — fixed.

## Findings

No new material blockers.

## Verdict

**APPROVED.** The AC is met, metrics remain separated, and the conclusions are appropriately calibrated.

Evidence of review: “Один frozen task across three efforts не закроет policy-вопрос: это лишь mechanism/pilot case.”

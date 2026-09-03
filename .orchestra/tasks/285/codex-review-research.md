## Summary

The research has strong source hygiene around pool topology, integer counters, API-equivalent cost versus actual payment, the Codex plan transition, and uncertainty around post-100 Opus admission. However, the controller’s dispatch equation does not enforce its stated 99% target, and several conclusions are stronger than the available evidence. The referenced #286 evidence is absent from the reviewed tree, so its Spark conclusions cannot be audited.

## Findings

blocking: `docs/tasks/285/research.md:135` — The dispatch gate contradicts the controller’s 99% target. Headroom is defined as `H = 99 - u - g - R`, but dispatch is allowed while `u + q95(turn) + g ≤ 100 - R`. This permits a turn to consume the nominal 1 pp safety margin. For example, with `u=98`, `g=0.5`, `R=0`, and `q95=1.4`, dispatch passes at `99.9`, although the declared guarded target permits only `98.5`. The same inconsistency is copied into `limits-data.json` and the HTML at line 104. Because continuity under quota exhaustion is blocking project context, the policy must use one coherent boundary and explicitly show where the 1 pp margin is enforced.

blocking: `docs/tasks/285/research.md:169` — The load-bearing Spark↔Luna result cannot be independently verified: all three directly cited #286 artifacts—`research.md`, `data.json`, and `report.md`—are absent from `docs/tasks/286/`. Consequently, the claims of preregistration, byte-identical diffs, timings, token counts, isolation configuration, and “Codex approved” have no reviewable evidence in the allowed scope. Restore the cited frozen artifacts or downgrade/remove these conclusions, including the routing dependence at lines 159, 163, 269, and 278.

suggestion: `docs/tasks/285/research.md:193` — “VPS quota exhaustion — REFUTED” overstates the evidence. Successful turns only establish availability through the observed 78–79% period; afterward quota telemetry becomes unavailable, and the document correctly says current state is unobserved. Zero explicit quota markers cannot falsify exhaustion during an interval where the relevant telemetry is missing. Classify quota exhaustion as “not observed through 79%; unknown afterward,” while retaining the confirmed token/login failure of the read-only usage path.

suggestion: `docs/tasks/285/research.md:193` — “current VPS failure = login/token fault, CONFIRMED” needs its scope narrowed. The evidence confirms that quota collection failed with token/login errors; it does not establish current inference failure because no current model/inference probe was run. State “current VPS quota-fetch failure” to avoid conflating telemetry health with execution reachability.

suggestion: `docs/tasks/285/research.md:139` — The reported `58.36%` linear target trajectory is not reproducible from the stated timestamps alone. From `2026-08-11T07:00Z` to first 100 at `2026-08-15T10:01:51Z`, approximately 75 of 168 hours elapsed, yielding about `44.2%` on a zero-to-99 linear trajectory. If 58.36% incorporates a nonzero starting utilization or another anchor, name that baseline and formula in both the narrative and machine data. As written, the arithmetic is under-specified.

suggestion: `docs/artifacts/model-limits-source-of-truth.html:192` — The interactive HTML does not implement the narrative’s zone predicates. It assigns zones from fixed `required rate` thresholds (`>0.35`, `>0.08`) and ignores p50/p90 projections, early-exhaust probability, telemetry freshness, plan/reset drift, and calibration history. Since the artifact presents itself as the offline view of the source of truth, label this widget explicitly as an illustrative headroom calculator or make its displayed classifications consistent with the narrative.

suggestion: `docs/tasks/285/research.md:122` — “3-hour blocks for preserving burstiness” conflicts with the later requirement for “≥20 independent 3-hour blocks.” Adjacent demand blocks within a window are unlikely to be independent, and block bootstrap is normally used precisely because observations are dependent. Replace “independent” with an effective-sample or separated-block criterion and justify the chosen block length from observed autocorrelation.

suggestion: `docs/tasks/285/research.md:262` — The evidence confirms that the two post-100 completions were Opus and were not already in flight at the first observed 100 transition. It does not fully distinguish integer rounding, delayed enforcement, admission-time counter differences, or another undocumented allowance. The document mostly handles this correctly under `UNCERTAIN`; change “soft admission” language to avoid implying a demonstrated provider policy.

suggestion: `docs/tasks/285/research.md:230` — Publishing a live PID, PPID, precise start time, executable path, and credential-class inventory is value-free but still operationally sensitive metadata. It is not a secret disclosure by itself, yet the durable public artifact does not need ephemeral process identifiers. Retain the finding and timestamp, but omit PID/PPID from the narrative unless they are necessary for a private remediation artifact.

## Verdict

**BLOCKING FINDINGS REMAIN**

## Round (2026-08-16T09:50:19Z)

## Summary

All eight prior findings are resolved. The controller invariant now preserves the 99% boundary; #286 evidence is restored and auditable; Grok, replay arithmetic, HTML labeling, dependence handling, post-100 uncertainty, and security metadata are appropriately scoped.

## Findings

suggestion: `docs/tasks/286/report.md` — One residual wording issue remains from its own review: parent-root isolation was configured but not independently proven inside the process. The #285 narrative already states this correctly, so it does not block #285.

No new blocking findings.

## Verdict

**APPROVED**

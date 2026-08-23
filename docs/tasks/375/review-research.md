<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The document is unusually careful about separating configured, reported, and accepted capacity. Its arithmetic is sound, and it correctly states that zero current compactions do not validate either threshold. I found no blocking defect under the supplied severity definition, but four material overclaims weaken the recommendations.

Verification quote from the artifact: “Dormant managed homes are stale by design.”

## Findings

1. suggestion: `docs/tasks/375/research.md:63,124-126` — H1 and the delivery conclusion overstate what the snapshot proves. Exact config files for all five running and three waiting sessions do not prove those already-running app-server processes loaded that config. The end-to-end evidence shown at lines 106–122 establishes `task_started=828400` and `token_count=828400` for one Sol and one Luna session only. The reconnect code supports next-turn delivery, but file state alone is not runtime delivery. Narrow H1 to observed Sol/Luna turns and separately report that all running/waiting homes had the desired file contents.

2. suggestion: `docs/tasks/375/research.md:27-30,171-173` — the `94.74%` comparison risks implying a runtime occupancy threshold without establishing that `model_auto_compact_token_limit` and `token_count.model_context_window` use the same token semantics. The document’s own source note mentions “total/body-after-prefix scope,” while the report alternates among “active tokens,” “input tokens,” and effective-window occupancy. Keep `784800 / 828400 = 94.74%` as arithmetic only and explicitly say the denominator/measurement semantics are not demonstrated to be comparable.

3. suggestion: `docs/tasks/375/research.md:226-227,238-249` — “CONFIRMED mechanism” is too strong for the token-cost conclusion. Current bins show that later, larger contexts are highly cached; #330 models what historical work might have transmitted under another window. Neither proves that the configuration change itself causes repeated larger prefixes, nor the resulting subscription-token multiplier. Relabel this as “observed cache/context association plus modeled mechanism; causal magnitude unmeasured.”

4. suggestion: `docs/tasks/375/research.md:39-43,253-260,350-351` — keeping both `872K` and the `60%` policy does not follow uniquely from the evidence. Acceptance at 474K supports retaining a ceiling above 474K, not specifically 872K. Likewise, historical execution proves that the 60% timer works, but the report provides no comparative evidence that compacting at roughly 497K is safer than waiting, and it acknowledges compact-fidelity risk. Present “keep current settings” as a change-avoidance/default-status-quo recommendation under the no-change constraint, not as an evidence-backed risk minimum; the optimal per-model ceiling and compact threshold remain insufficient evidence.

## Verdict

No blocking findings. **Needs revision** for evidentiary calibration: narrow runtime-delivery coverage, qualify denominator semantics, downgrade the modeled token-cost mechanism, and separate “do not change yet” from proof that `872K + 60%` is preferable.

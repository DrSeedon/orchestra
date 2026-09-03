<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

No blockers found under the stated calibration. The research correctly keeps both pilot thresholds `null`, separates HTTP-200 provider errors, identifies the hidden-enum judge flaw, and matches the cited `AgentLoop` context-guard behavior. Mechanical check passed:

`MECHANICAL_OK hashes=2 pilot1=26+7/33 pilot2=12+9/21 complete=0 db=467->467 secret_shapes=0`

Exact evidence that I read `research.md`: “Mutable state can be smaller while becoming confidently wrong.”

## Findings

- suggestion: `docs/tasks/430/research.md:134-145` — A/B/A/B ordering and identical surfaces are specified but not mechanically demonstrated → record the actual request sequence and assert alternation, arm balance, identical rendered schema/tool inputs, and identical controller parameters.

- suggestion: `docs/tasks/430/research.md:130,136,164-179` — “Recursive merge patch” is underspecified, especially for `null`, arrays, replacement, deletion, and permitted state paths → freeze the exact merge semantics and validate patches against a manifest schema before grading.

- suggestion: `docs/tasks/430/research.md:149-158` — The protocol risks conflating provider-envelope failure with model-output failure. A non-empty `choices` response can have valid provider transport but invalid JSON content; the format canary already distinguishes these as `provider_success` plus `invalid_json` → define envelope validation separately from model JSON parsing, and grade only the latter as a model outcome.

- suggestion: `docs/tasks/430/research.md:112-122` — `N=30` with six hash-selected tasks per stratum is explicitly screening, but it does not establish how representative the result is of “our tasks” → report eligible-task counts, exclusions, and the resulting sampling fraction per stratum alongside benchmark results.

- suggestion: `docs/tasks/430/research.md:193-205` — `η_tokens` and `η_quality` use the maximum observed A/A discrepancy, then add a one-sided 90% bootstrap bound. The maximum is not itself a 90% estimate of noise and has no uncertainty treatment → either define this as a deliberately conservative heuristic guard or use a statistically specified A/A calibration estimator with its own uncertainty.

- question: `docs/tasks/430/research.md:70-74` — The claim that all nine second-pilot episode arms entered the provider bucket is stronger than what `pilot-audit.json` exposes, which only provides aggregate counts → add a per-case/per-arm aggregate receipt so that claim is mechanically auditable without relying on inaccessible raw files.

- suggestion: `docs/tasks/430/research.md:172-179` — The judge controls test semantic cases, but the hidden-enum failure specifically occurred at the rendered prompt/manifest boundary → add a control proving that every disclosed enum and normalization rule is actually present in the model-facing prompt before the first response.

## Verdict

No blocking findings. Phase 1 review passes. Address the suggestions concerning request-order evidence, patch semantics, provider-vs-model parsing, and threshold calibration before freezing the full benchmark.

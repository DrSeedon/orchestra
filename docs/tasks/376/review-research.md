<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The arithmetic, phase decomposition, cache-invalid verdict withholding, token/call/failure totals, and pilot exclusions are mechanically supported. No blocking defect found.

Commands rerun:

```text
$ python3 docs/tasks/376/analyze.py aa
"noise_range_s": 0.9374368898570538
"expected_removable_effect_s": 1.9899498978629708
"pass": true

$ python3 docs/tasks/376/analyze.py ab
"median_effect_s": 2.891090984339826
"cache_arm_medians_within_2pp": false
"cache_full_range_within_5pp": false
"valid_causal_comparison": false
"verdict": "no-path-verdict"
```

Per-run summary spot-check produced:

```text
confirmatory 7 calls 7 pass 7 fail 0 tools 0
input_tokens 66052
cached_input_tokens 6912
output_tokens 147
reasoning_output_tokens 0
cache_write_input_tokens 0
```

Raw-event recomputation matched summary timing. For `aa-exec-1`, process/queue/model values matched exactly; post and total differed by only `0.000005380018 s` because the summary uses the process-wait timestamp immediately before the raw process record is written. `ab-app-1` matched exactly in every checked phase.

Evidence quote from `research.md`, absent from the request:

> “Operational no-change follows from absence of a valid verdict, not from pretending the existing path won.”

## Findings

suggestion: `docs/tasks/376/research.md:103-104` — The exact Codex event-consumption path is cited incorrectly. Codex has `event_stream == "persistent"`, so `_activate_backend_tasks()` launches `_persistent_event_loop()` at `app/session.py:1791-1796`, which consumes events and invokes `_handle_event()` at `app/session.py:1854-1865`. The cited `_turn_event_loop()` at `1914-1938` is the per-turn path and is not launched for the persistent Codex capability. Replace the citation and wording; this does not change the benchmark conclusion.

suggestion: `docs/tasks/376/research.md:18-19,239-240` — “Directly refutes inference” and “total wall cannot locate” overstate what three A/A samples prove. The evidence shows that total wall was not a usable transport locator for this fixture and sample size because observed same-path noise exceeded the interleaved median difference. It does not establish a general impossibility of locating transport effects from total-wall measurements with adequate replication or modeling. Use the already well-calibrated wording at lines 171-172 consistently.

question: `docs/tasks/376/research.md:249-251` — The claim specifically refuting what task #372 establishes depends on an external report that this review was expressly forbidden to inspect. The current A/A data independently establishes large total-wall/model-wait variation, but not what #372 itself measured or claimed. Should finding 6 be rewritten solely in terms of the present experiment, or explicitly marked as not independently verified in this review scope?

## Verdict

Needs minor documentation correction, not experimental rework. The central decision is sound: the preregistered cache invariant failed, so withholding all requested path verdicts is the correct outcome. No blocking findings.

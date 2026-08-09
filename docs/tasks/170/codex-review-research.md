# #170 — research second opinion

## External verdict

**UNAVAILABLE.** The mandatory `codex_review(mode="exec")` call was attempted
once against `docs/tasks/170/research.md` and returned immediately:

```text
weekly_quota_unknown: New Codex worker turn blocked: weekly quota status for gpt-5.6-sol is unavailable or stale (missing or legacy readiness policy). Stop/model change remain available.
```

Per the assignment, the review was not bypassed and Claude was not used. The
following is a strict GPT-5.6 Sol self-review, not an independent verdict.

## Adversarial checks

1. **Could the 94.81% residual be mislabeled provider latency?** Yes. It also
   contains reasoning, generation and uninstrumented native activity. Research
   now calls it `model/workload` and explicitly refuses a pure-compute claim.
2. **Are background review seconds double-counted with active turns?** The raw
   2,917.47 s includes 338.74 s of overlap. Research separately reports
   2,578.73 s outside turns and does not add the raw total to active wall.
3. **Does the failed `codex_review` prove that all 48.6 review minutes were
   avoidable?** No. Independent review was required and produced substantive
   findings. Research limits the claim to the broken route/fresh-session
   fallback and states that the counterfactual saving is unmeasured.
4. **Was the entire 80.89 s bwrap review wasted?** No. The same job also
   returned a verdict. Wording was corrected: 80.89 s is an upper bound, not
   measured waste; the incremental loss is unknown.
5. **Could different workloads manufacture the before/after regression?** The
   blocking conclusion uses the same `codex_review` tool outcome: 14/14 starts
   before commit `8369737`, 5/5 legacy-policy refusals after it. Overall turn
   speed is not compared across unrelated tasks. Compact uses the same native
   lifecycle signature before/after #97.
6. **Is legacy readiness merely real quota exhaustion?** No. The route returns
   provider `available`, target native quota rises only 4%→33%, and 26/26
   ordinary Codex turns complete. Current client source requires the missing
   `worker-weekly-v1` field. The causal contract mismatch is directly observed.
7. **Are turn and payload counts internally consistent?** Recomputed assertions
   pass: 26 complete `ok/end_turn` rows; duration sum 18,736.803 s; seven turns
   ≥600 s; their output sum 347,938; 21 fresh review jobs, 20 completed.
8. **Are initial prompt sizes exact?** The first draft used rounded structural
   JSON sizes. They were replaced with decoded message-text byte counts:
   developer items 47,654; project instruction payload 68,043; task 5,573.
9. **Could secrets or sensitive prompt content have entered artifacts?** The
   analyzer only emits classes, counts, hashes, timestamps and sizes. Link and
   credential-marker assertions passed; the only bearer string is the literal
   `$INTERNAL_TOKEN` placeholder in the reproduction command.
10. **Does the archived final session state undermine the timeline?** No. The
    source DB/rollout persisted after archival, the last task completed at
    13:54:49Z, and the snapshot time/state is recorded separately.

## Self-review verdict

**PASS WITH EXTERNAL VERDICT UNAVAILABLE.** No unresolved blocking hole remains
in the measured conclusions. The strongest result is the exact readiness
contract skew. Claims about model/workload, bwrap cost and review overhead are
deliberately bounded where the telemetry cannot identify a counterfactual.

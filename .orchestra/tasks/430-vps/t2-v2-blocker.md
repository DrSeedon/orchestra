# #430 T2 blocker — Appendix A.4 revision failed the semantic gate

The single authorized replacement revision completed all 9 Luna calls, but the mandatory comparable triple did not pass. Calibration and main remain at 0 calls/files.

## Outcome buckets

- provider success: **9/9**;
- valid fenced JSON: **9/9**;
- `malformed_output`: **0/9**;
- protocol failures: **0**;
- tool calls: **0**;
- resumed sessions: **0**;
- production DB writes in per-call trace: **0**;
- completed correct arms: **1/3**.

This establishes that the paper-faithful text/fence protocol is syntactically viable on Luna. The measured reason for stopping is semantic quality, not provider availability or malformed JSON.

## Arm results

| arm | Q | total tokens | final reason | critical loss |
|---|---:|---:|---|---|
| append | 1.00 | 51,486 | `CURRENT_DB_IS_FTS_NOT_VECTOR` | no |
| state | 0.75 | 50,812 | `LOW_USAGE_ONLY` | yes |
| append_repeat | 0.75 | 51,397 | `LOW_USAGE_ONLY` | yes |

Observed state-vs-append token saving on this one control was **1.3091%**; same-arm append-repeat token discrepancy was **0.1730%**. These are diagnostics, not calibrated thresholds. Both state and append-repeat preserved the decision/keep/rejected fields but selected the wrong critical reason.

T2 acceptance remains RED at the frozen condition:

```text
assert data["completed_three_arm_cases"] == 1
E assert 0 == 1
RC=1
```

## Decision boundary

The user authorized one Appendix A.4 revision, not a series. It failed, so no calibration or N=30 run is permitted. The measured `malformed_output` rate is zero, therefore the predeclared reason for switching to the local strict `operations[]` variation did not occur; strict operations would also not address the observed wrong reason code.

Codex quota moved **33% → 34%**. No further Luna revision, free-route fallback, or Sol call was made.

# #430 — final report: SKILL.state benchmark closed before main run

Decision: **closed without a local treatment verdict**, by explicit user instruction “закрывай тему блокнота”.

## What completed

- Phase 1 defined a 30-case, five-stratum paired benchmark and identified reason-bearing research/architecture/incident work as the dangerous class.
- Phase 2 froze Luna runner/oracles, provider-vs-model buckets, deterministic cohort reconstruction, calibration thresholds and a mandatory positive control.
- Phase 3 implemented the task-local stateless Luna runner and ran only the authorized controls.
- No production `app/` code was changed; `app/harness/` remained untouched.

## Measured controls

### Free OpenRouter pilot

- HTTP requests: 54.
- Request envelopes with choices: 38.
- Provider malformed/error envelopes: 16.
- Comparable three-arm cases: 0.
- Calibration/main calls: 0.

The free lane measured availability, not memory representation.

### Luna Appendix A.4 text/fenced-JSON control

- Provider success: 9/9.
- Valid fenced JSON: 9/9.
- `malformed_output`: 0/9.
- Protocol/tool/resume/DB-write failures: 0.
- Correct arms: 1/3.

| arm | Q | total tokens | critical reason |
|---|---:|---:|---|
| append | 1.00 | 51,486 | correct |
| state | 0.75 | 50,812 | lost (`LOW_USAGE_ONLY`) |
| append_repeat | 0.75 | 51,397 | lost (`LOW_USAGE_ONLY`) |

State saved 1.3091% against the successful append and 1.1382% against append_repeat. Same-arm append token discrepancy was 0.1730%. These are n=1 control diagnostics, not calibrated thresholds.

## What the result does and does not say

The critical reason loss cannot be attributed to state: append_repeat failed on the identical field. The earlier sentence “SKILL.state теряет важное у нас” was withdrawn and must not be cited.

The only defensible local conclusion is: on short episodes the token effect is too small and quality retention too noisy to identify a treatment effect. The paper’s 23–60% savings were reported on longer public workloads; #430 did not run comparable long horizons.

## Gates and tests

- T1 runner: RED RC=1 → `1 passed`.
- Strict provider-schema control: stopped at call 1/9 with `invalid_json_schema`; excluded permanently because the paper did not use Structured Outputs.
- Appendix A.4 T2: 9/9 technically valid but acceptance RED at `completed_three_arm_cases: 0`, RC=1.
- Census oracle: focused RED → green; bypass mutation RC=1; restored RC=0.
- T3/T4 remained intentionally RED; calibration/main were never authorized after the failed T2 gate.
- KB validation: recorded in `docs/tasks/430/kb-contract-final.txt`.

## Breaking changes and cleanup

Breaking changes: none. Production database/model/runtime contracts were not changed. Historical raw receipts, failed gates and frozen oracles are retained under `docs/tasks/430/` and explicitly marked closed in `CLOSED.md`.

## If the question returns

Use a new task/revision. Start with long episodes and a stable reason-retention control; do not reuse #430’s null thresholds or join its controls into a new statistic.

Review: no new model review — user closed the task after the plan review ceiling; final facts are mechanically checked against stored receipts.

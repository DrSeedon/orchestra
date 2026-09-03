<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The plan has a sound ticket dependency chain and correctly enforces Luna-only main execution, positive-control gating, calibration-before-main, and free-lane exclusion. However, Phase 3 is not executable or mechanically safe yet.

## Findings

### blocking

- `blocking: docs/tasks/430/plan.md:29 — --output-schema uses a relative path while Codex runs with --cd <fresh empty /tmp dir>, so the schema lookup can fail before the first call → resolve the schema path to an absolute path before constructing argv; likewise require an absolute output-message path.`

- `blocking: docs/tasks/430/plan.md:58-61, 71, 86, 98-104 — the plan never defines the frozen positive-control episode/correct answer, the five strata, the case format, or the quality score Q → provide task-local frozen fixtures and explicit scoring/stratum definitions before Phase 3; otherwise implementation must invent protocol values.`

- `blocking: docs/tasks/430/plan.md:100-104, 174 — “frozen cluster-bootstrap seed” and CI bounds are named but not specified: seed value, resampling unit, replicate count, interval method, and Q/ratio definitions are absent → define these parameters and the exact recomputation algorithm in the plan or a frozen task-local specification.`

- `blocking: docs/tasks/430/plan.md:116, 174 — acceptance checks only `sessions` row counts, which cannot detect writes to logs, tasks, inbox, or other production-DB tables → require a read-only SQLite connection/snapshot and an acceptance check covering the complete database write surface, not only `sessions`.`

### suggestion

- `suggestion: docs/tasks/430/acceptance/test_t2_luna_positive_control.py:8-38 — T2 validates a receipt after it exists but does not independently verify the frozen episode’s answer, step count, receipt linkage, or raw-receipt digest → strengthen the oracle so a fabricated or incomplete positive-control receipt cannot pass.`

- `suggestion: docs/tasks/430/acceptance/test_t3_luna_calibration.py:18-46 — T3 trusts precomputed noise arrays and thresholds and does not recompute them from the raw calibration receipts → make the acceptance test derive the six discrepancies and thresholds from raw receipts.`

- `suggestion: docs/tasks/430/acceptance/test_t4_luna_main_benchmark.py:22-83 — T4 checks that summary fields are internally consistent but does not verify that the reported 480–720 calls equal the actual per-case step ledger or that every selected case has the required source payload → add those ledger-level checks.`

## Verdict

Needs work. The architecture and dependency ordering are acceptable, but the relative schema path, unspecified benchmark/scoring inputs, incomplete statistical specification, and insufficient production-DB safety oracle block approval.

## Round (2026-09-01T16:31:46Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Round 1 blockers are fixed:

- Absolute cwd/schema/output paths: FIXED; specified and checked by T1.
- Frozen fixture, strata, case fields, enums, normalizers, and Q: FIXED.
- Bootstrap seed, unit, replicates, statistics, and percentile indices: FIXED.
- Production DB safety: FIXED in the plan/spec and covered by T1/T4 checks.

Round 2 found three new blocking oracle/design issues.

## Findings

### blocking

- `blocking: scripts/skillstate430/luna_benchmark_spec.json:129-137 — selection_key is only sha256(prefix + task_id), producing one identical value rather than a deterministic per-case ranking; the plan never defines how six eligible cases are selected within each stratum → specify a per-case selection key/ranking and deterministic top-six algorithm.`

- `blocking: docs/tasks/430/acceptance/test_t4_luna_main_benchmark.py:75-79 — `all(record["model_outcome"] for record in step_records)` accepts any truthy value, including `"failure"`, while the plan requires model-success outcomes and separate provider/model buckets → assert the exact successful outcome and reject model failures before computing episode results.`

- `blocking: docs/tasks/430/acceptance/test_t4_luna_main_benchmark.py:66-99 — T4 does not require each raw step to be protocol-valid, non-resumed, one-attempt, or fresh-thread, and it does not verify that selected cases’ strata match the population’s six-per-stratum allocation → add these checks before accepting the 30 pairs; otherwise an invalid or misallocated cohort can produce a verdict.`

## Verdict

Needs work. All four Round-1 blockers are fixed, but Phase 3 is not yet mechanically reproducible or protected against accepting invalid model outcomes and cohort allocation.

## Round (2026-09-01T16:35:41Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Round 2 blockers:

- Per-case selection algorithm: FIXED in the plan/spec.
- Exact model/protocol outcome validation: FIXED in T4.
- Fresh-thread, attempt, resume, and stratum validation: FIXED in T4.

One new blocking oracle gap remains.

## Findings

### blocking

- `blocking: scripts/skillstate430/luna_benchmark_spec.json:93-105, docs/tasks/430/acceptance/test_t4_luna_main_benchmark.py:54-67 — selection requires `case.task_id`, but `task_id` is not a required case field; T4 also does not recompute the per-case selection hash/top-six algorithm and only checks that `source_sha256` is non-empty → require `task_id`, eligible-census data, and independently recompute/verify each selected case’s hash, ordering, and source digest.`

## Verdict

Needs work. The prior three blockers are resolved, but the final oracle still permits an arbitrary 30-case cohort to pass without proving it came from the specified deterministic selection procedure. This is the executable-oracle ceiling; no further review round is authorized.

# T5 — fixed-workload A/B gate

Verdict: **NO_CHANGE**.

The workload, hashes, metrics, minimum repetitions and decision rule were
frozen in `t5-workloads.json`. The evaluator is `t5_ab_gate.py`; raw run rows
would live in `t5-runs.json`.

Command:

```bash
python3 docs/tasks/170/measurements/t5_ab_gate.py
```

Raw result:

```json
{
  "baseline_runs": 0,
  "candidate_runs": 0,
  "counts": {
    "baseline": {"distant-domain": 0, "multi-file-review": 0, "yielded-test-handle": 0},
    "candidate": {"distant-domain": 0, "multi-file-review": 0, "yielded-test-handle": 0}
  },
  "reason": "insufficient_comparable_runs",
  "required_per_arm": 12,
  "verdict": "NO_CHANGE"
}
```

External Sol execution was unavailable without bypassing the mandatory
readiness gate; Claude was forbidden by the task. Starting direct `codex exec`
would reproduce the exact bypass that #170 forbids. Therefore there is no
comparable baseline-baseline noise estimate or candidate arm, and no
runtime/prompt change is authorized.

The gate itself was checked in memory with 12+12 hash-matched synthetic rows:
zero-noise gains of `10 reads / 100 bytes` returned `PASS`; zero gain returned
`NO_CHANGE`. These synthetic rows validate evaluator polarity only and are not
performance evidence.

Quantified recommendation remains unchanged: the audited session made `193`
read actions, returned `2.34 MB` of tool results (`39` results ≥16 KiB), and
spent `31.06 s` in explicit poll commands. A future candidate should reduce
unchanged-path rereads or large result bytes while preserving correctness and
the distant-domain case; test polling is a low-priority 31-second contributor,
not an hours-scale regression.

# #466 T1 — contradictory frozen oracle

## Observed result

After implementing the planned author-outcome selection and both merge enforcement points:

```text
.orchestra/tasks/466/test_run_receipt_466.py -k test_t1_
4 passed, 2 deselected; RC=0

tests/test_review_coverage_gate_462.py -k test_t3_
1 failed, 14 passed, 7 deselected; RC=1
```

The failing #462 parameter is:

```text
status=completed
coverage_outcome=reviewed
author_outcome=unknown
allowed=True
```

`tests/test_review_coverage_gate_462.py::_receipt_payload` fixes `author_outcome='unknown'` and
the positive parameter at lines 602–612 expects the reviewed row to satisfy coverage. The frozen
#466 test creates a structurally completed reviewed row with `author_outcome='unknown'` and expects
`status=blocked/reason=author_outcome_missing`.

## Why production cannot satisfy both honestly

Both tests call the same active-policy `coverage_decision` path with the same semantic receipt
state. Distinguishing the cases by `verdict_value='APPROVED'`, `round`, artifact path, task number,
or timestamp would infer the author's response from unrelated review prose/metadata and preserve
a production bypass. That contradicts #436's explicit direct `record_review_outcome` owner and
#466's accepted architecture.

## Required resolution

The #462 positive reviewed fixture must represent the new post-T1 contract by recording a direct
author outcome (for example `author_outcome='accepted'`, `outcome_source='direct'`), or its
`allowed` expectation must become false. `skipped` and typed `unavailable` remain valid with
`author_outcome='unknown'`; their #462 cases are green now.

The current #466 ownership boundary excludes `tests/test_review_coverage_gate_462.py`, so this
worker has not changed that oracle. T1 cannot be reported complete until the owner/orchestrator
chooses the compatible fixture change.

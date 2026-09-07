# Open candidate task — diagnose the red frozen oracle

The frozen acceptance suite is red on this Orchestra source snapshot. Diagnose why and make the
exact command green by changing production code. Diagnosis is part of the task; no defect list,
target-file list, or implementation outline is provided.

The received acceptance tests are immutable: NEVER edit, delete, rename, skip, xfail, or weaken
them. Do not modify any test, fixture, test helper, `conftest.py`, test configuration, marker, or
test-selection setting. Do not read git history or any file outside this working directory; prior
task and benchmark artifacts are deliberately hidden from the runtime.

Acceptance command:

```bash
/tmp/astra505/venv/bin/python -m pytest -q \
  tests/test_review_coverage_target_drift_474.py \
  tests/test_merge_test_gate.py \
  tests/test_acceptance.py \
  tests/test_review_receipt_migration_436.py
```

Run the command, investigate the failures through the supplied source and tests, implement the
smallest coherent production fix, and finish only when the exact command passes.

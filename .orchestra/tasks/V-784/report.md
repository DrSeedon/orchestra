# V-784 — distinguish pytest startup failure from test output

`run_pytest()` searched combined stdout/stderr for `No module named pytest`. A failing test can include the same text in an assertion message, so the runner marked a real test failure `INCONCLUSIVE / pytest_unavailable`; the mutation gate then failed to report `guarded_source_change`.

The runner now recognizes pytest as missing only when stdout is empty and stderr exactly matches the selected interpreter's module-startup error (full invocation path or executable basename). A test failure's assertion output no longer changes its status.

| Case | Outcome | Evidence |
|---|---|---|
| Target-source test failure includes `No module named pytest` as assertion data | Fixed | `test_mutation_gate_treats_pytest_missing_text_in_assertion_as_real_failure`: red before fix (`inconclusive`), green after with mutation result `guarded_source_change`. |
| Selected Python interpreter cannot import pytest | Preserved | `test_run_pytest_reports_project_pytest_missing_without_fallback` supplies the interpreter's exact startup stderr and still gets `pytest_unavailable`. |

Full merge-test-gate suite: `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_merge_test_gate.py tests/test_merge_gate_mutation_702.py -q` → **50 passed in 78.05s**. Raw output is in `pytest.log`; `app` imported from `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-merge/app/__init__.py`.

After commit `6364dddf` included the new regression test, restoring the previous broad output search made it fail with `inconclusive` instead of `guarded_source_change`. The mutation is recorded in `mutation-red.log`; after restoring the fix, the assertion-text and missing-pytest tests both passed.

The Python change needs the owner's Orchestra restart after merge; none was performed.

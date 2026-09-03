# #322 merge-test-gate batching timeout

## Reproduction

Operation `e507e460-6217-4f0e-908d-ade928306288` showed the failure mode: the old
`[12, 2]` split gave the second, heavy batch only its fixed half of the 180-second
budget. Batch 1 (2 files) completed in 36.82 seconds; batch 2 (12 files) timed out
at 46% without a test failure.

## Change

For mapped subsets larger than `MAX_TEST_FILES` (12), `_ordered_batches` uses a
deterministic maximum batch size of six and distributes files as evenly as
possible, so 14 files become `[5, 5, 4]`; no large batch of 12 remains.
`_batch_result` allocates `remaining / batches_left` from one monotonic
180-second deadline, attempts every batch, and keeps FAILED precedence over
INCONCLUSIVE. The existing direct path for 12 or fewer files is unchanged.

Diagnostics remain bounded at 4000 characters while reserving space for every
batch and retaining head/tail output from verbose results.

## Evidence

The 14-file regression asserts `max(batch_sizes) < 12`, exact `[5, 5, 4]`
distribution, and dynamic timeout allocation. Its deterministic cost model
assigns 36.82 + 240 seconds to the old `[2, 12]` profile (which exceeds 180)
and 60 + 60 + 48 seconds to the new distribution (which fits); the simulated
timeouts are 60 seconds per batch. A 13-file regression proves that a FAILED
first batch does not suppress later batches and FAILED remains the aggregate
status. Existing 12-file coverage asserts the direct single-call path.

## Verification

- RED baseline: the prior implementation produced `[2, 12]`; the corrected
  oracle rejects it because `max(batch_sizes) < 12` and its modeled cost exceeds
  the 180-second deadline. Restoring the pre-fix implementation from
  `HEAD~2:app/merge_test_gate.py` made the exact 14-file test fail with aggregate
  `inconclusive`; restoring `HEAD` plus `touch` made it pass again.
- GREEN: `/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_merge_test_gate.py`
  → `17 passed in 9.36s`.
- `/home/kesha/orchestra/.venv/bin/python -m py_compile app/merge_test_gate.py tests/test_merge_test_gate.py`
- `git diff --check`

No deploy or restart was performed.

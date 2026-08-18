# #317 merge_test_gate batch scheduling fix

## Repro + exact imbalanced case
- Repro operation: `c2d472de-cac2-4a5f-b456-4d7598c6fdd2`
- Observed before fix: `len(tests) > 12` produced batches `[12,2]`, each with a fixed preallocated `90s`; a large batch could timeout while a small batch passed within `32.56s`, leaving no carry-over time despite `180s` total budget.

## Changes
### `app/merge_test_gate.py`
1. Added ordered batching via `_ordered_batches`: partial/smaller batch runs first for any uneven final chunk.
2. Changed batch timeout allocation in `_batch_result` to `remaining_total / batches_left` at each step, so leftover wall time flows forward.
3. Kept per-batch attempt semantics and `FAILED` precedence over `INCONCLUSIVE`.
4. Added bounded per-batch head+tail diagnostics via `_compact_output` and capped each batch section inside the overall `4000` budget.
5. Preserved direct single-batch path for `<= 12` tests.

## Tests run
- `/home/kesha/orchestra/.venv/bin/python -m py_compile app/merge_test_gate.py tests/test_merge_test_gate.py`
- `/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_merge_test_gate.py`
- `git diff --check`

## Mutation proof
1. `test_large_mapped_subset_runs_all_files_in_bounded_batches`
   - Guards exact imbalanced regression (`14` tests).
   - Asserts batch order `[2,12]` and dynamic timeouts `90s -> ~147.44s` with simulated partial timing; a mutation to fixed or equal-split timeout fails.
2. `test_each_batch_is_attempted_when_non_final_batch_fails`
   - Ensures the second batch still runs after an earlier `FAILED`, validating “each batch attempted” and `FAILED` precedence behavior over `INCONCLUSIVE`.

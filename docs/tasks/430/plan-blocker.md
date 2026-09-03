# #430 Phase 2 blocker at review ceiling

Luna Round 3 closed every prior finding and left one blocking oracle gap:

- `luna_benchmark_spec.json` uses `case.task_id` in selection but does not require `task_id` in the case format;
- T4 checks a non-empty `source_sha256` but does not hash the actual source bytes;
- T4 does not rebuild the eligible census, recompute each case selection key, sort `(selection_key_hex, numeric task_id)`, and prove the selected six per stratum are exactly the deterministic top six.

The finding is correct. Without those checks an arbitrary 30-case cohort can satisfy the current oracle.

Required resolution before Phase 3:

1. add numeric `task_id` to required case fields;
2. freeze the full eligible-census ledger, including exclusion reason, stratum, source paths and source-byte digest for every eligible row;
3. make T4 independently read/hash the cited source bytes, recompute the per-row selection key and top-six list for every stratum, and compare it byte-for-byte with population + selected cases;
4. re-freeze the acceptance/spec before any implementation or model call.

`codex-debate` executable-artifact ceiling is exhausted at three rounds. Additional Luna/Sol review is not authorized by the skill; Sol is also explicitly forbidden without a separate decision. Phase 3 has not started.

## Resolved by manual option A

The orchestrator accepted a mechanical fix with no fourth model review. RED `3b816439` failed on `T4 census rebuild guard missing`. Fix `2cd13159` requires `task_id`, enumerates task ids from the frozen Git source, hashes actual `git show` bytes, rebuilds the per-stratum top six, and rejects arbitrary cohorts. Focused test: `1 passed`; whole T4: `1 passed, 1 failed` only on missing real population. Mutation that bypasses census rebuild: `MUTANT_RC=1`; restored oracle: `RESTORED_RC=0`. Evidence: `red-census-oracle.txt`, `green-census-oracle.txt`, `red4-t4.txt`, `mutation-census-oracle.txt`.

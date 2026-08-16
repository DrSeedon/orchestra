<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

V12’s deterministic runtime-prefix packaging contract is satisfiable and fail-closed. I found no executable false-green or common-mode authority bypass.

Executed:

```text
python -m pytest ... test_v12_delivery_oracle.py test_authority_oracle_selftest.py
............... [100%]
15 passed in 7.25s
```

Additional verification:

- All 23 registered V9–V12 oracle/supporting hashes matched; zero mismatches.
- Two fresh frozen-lock Python 3.12 runtimes independently normalized to the same inventory: 3438 members, 408 directories, exactly 5 activation grammars, 17 shebangs, and 16 owning `RECORD` files.
- Exact delivery commands remained RED solely for missing implementation behavior:
  - A: 2 failed, 16 passed
  - B: 2 failed, 15 passed
  - C: 1 failed, 9 passed
  - D: 4 failed, 9 passed
- Candidate bytes are compared without candidate-side normalization.
- The final prefix is independently derived as `/opt/orchestra/runtimes/<full-commit>-<release>-py312`; arbitrary, overlapping, mismatched, and common-mode prefixes cannot redirect it.
- Missing, duplicate, stale, or wrong `RECORD` ownership/hash/size cannot satisfy normalized inventory equality.
- V11’s canonical internal-directory symlink, exact inventory, pinned snapshots, path-replacement, explicit-directory, and TOCTOU protections remain inherited and hash-preserved.
- The selected normalization approach is narrower and safer than privileged offline-wheel materialization: deterministic bytes are established before privilege, while root performs descriptor-pinned extraction only.
- Delivery reports remain fixed pending-only. Package GREEN neither authorizes activation nor claims isolation.
- A recovery, B executor-UID separation, C provider broker, and D defense-in-depth remain distinct gates. Live host, PID 1, protected-state, provider-authentication, signature/replay, activation, and rollback evidence cannot be synthesized or skipped.

Cross-family verdict unavailable.

## Findings

No blocking findings.

No suggestions. The selected contract is minimal and security-preserving for the measured 38 prefix-dependent files.

## Verdict

APPROVED

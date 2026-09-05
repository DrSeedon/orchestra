# #502 emergency slice — reserved merge trailer

## What the guard protects

Worker commit **bodies do not reach `main`** on either merge path:

- `_inspect_candidate_commits` reads each full body only for the reserved-marker check, but returns `messages=subjects` (`app/workspace.py:932-956`).
- `_build_squash_message` constructs a new message only from those subject lines (`app/workspace.py:970-996`).
- `_validated_squash_message` appends the current operation's one authoritative trailer itself (`app/workspace.py:999-1021`).
- the normal path passes only that constructed string to `git commit -m` (`app/workspace.py:1697-1706`); the unrelated-history path receives the same `prepared_squash_message` (`app/workspace.py:1634-1645`).

Therefore an arbitrary trailer in a worker body cannot forge the final squash message. The live refusal is still not safe to delete: the malicious arm remains fail-closed. The narrow rule for this slice is:

1. a candidate commit carrying `Orchestra-Operation: <id>` is allowed only when durable `merge_operations` evidence says that **the exact candidate SHA** was the target commit produced by operation `<id>`;
2. an absent/malformed/unknown id, a non-committed operation, or the right id on a different SHA remains the existing refusal.

This distinguishes provenance, not a lower threshold. A worker cannot reuse a real operation id on a crafted commit because changing the body or tree changes the commit SHA.

## Frozen oracle

`tests/test_merge_operations.py::test_t1_legitimate_operation_trailer_is_not_worker_spoof`

Frozen command: `uv run python -m pytest -q tests/test_merge_operations.py::test_t1_legitimate_operation_trailer_is_not_worker_spoof`

RED before production change: exit 1 at `assert legitimate["ok"] is True`; actual result carried `error=worker commit contains reserved Orchestra-Operation: trailer`.

- allow arm: content-equivalent current target plus an inherited, DB-proven prior merge-result trailer; merge succeeds and the final message contains only the current operation trailer;
- deny arm: the same worker hand-crafts `Orchestra-Operation:` on a new commit; merge fails before target movement with the existing error.

## Implementation and verification

- `app/merge_operations.py::operation_created_target_commit` accepts only a canonical UUID whose durable row has `commit_point='REACHED'` and whose normalized result binds `git.target_after` to the exact candidate SHA.
- `app/workspace.py::_inspect_candidate_commits` permits exactly one reserved trailer only through that proof; every malformed, duplicated, unknown, incomplete, or SHA-mismatched marker keeps the existing refusal.
- Focused regression: `uv run python -m pytest -q tests/test_merge_operations.py tests/test_merge_ref_gate.py tests/test_workspace.py::TestBranchWipStatus` → `44 passed in 4.53s`.
- Allow-path mutation replaced the durable predicate with `False`: original/mutant marker counts `1/0 → 0/1 → 1/0`; the frozen test failed at `assert legitimate["ok"] is True`; restore + `touch` rerun passed.
- Deny-path mutation bypassed the refusal: mutant marker count `0 → 1 → 0` and original `if not (` count `2 → 2`; the same frozen test failed at `assert malicious["ok"] is False`; restore + `touch` rerun passed.
- Luna implementation review round 1 found one blocker: structurally valid JSON with a non-object result or `git` field raised `AttributeError`. A separate frozen oracle produced `3 failed`; explicit type guards now return `False`, and the full focused run is `47 passed in 5.85s`.
- Luna round 2 reran the same focused suite (`47 passed in 5.48s`) and returned `APPROVED`; author outcome recorded on receipt `review-receipt:61b50285-8149-4e38-bdce-16dee2df286f`.

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

The frozen T381 tests pass (`5 passed, 15 deselected`), and the retry claim and provider boundary appear correct. However, unsupported historical states now crash resource reads rather than being handled safely, so the patch does not fully satisfy the requested compatibility contract.

Review comment:

- [P2] Handle unsupported historical states without raising — /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-initial-delivery-class/app/initial_deliveries.py:57-57
  blocking: Historical rows with an unknown state now make `_resource()` raise, so status reads and matching same-key receipts return a server error instead of a safe non-retryable response. This regresses the previous `None` fallback and violates the requirement to handle unsupported historical data safely; return a quarantined action that cannot trigger replay.

> ⚠ Codex usage unaccounted: ValueError: Codex completed turn reported zero tokens

## Author resolution before Round 2

- ACK P2: replaced the raising unsupported-state branch with a structured quarantine action:
  no tool, same delivery id, and `retryable=false`; no row is rewritten.
- Isolated temporary-DB probe exercises both `get_initial_delivery` and matching
  `accept_initial_delivery` for `LEGACY_CUSTOM_STATE`: both remain readable, the actions match, and
  runner wake count is zero.
- Frozen tests remain byte-identical to `621891aa0d44425610c564ac72f4b6c0c8b72726`.
- Attempt 2 requested 2026-08-23: resume the same Sol review after this code change.

## Round (2026-08-23T16:38:17Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Round 2

**Re-review status**

- P2 — **FIXED**. Unsupported historical states remain readable through status and matching same-key receipts.
- They return `QUARANTINED_DELIVERY_STATE` with `tool=null` and `retryable=false`.
- No runner wake or row rewrite occurs.
- Retry remains exclusive to `FAILED_BEFORE_SUBMIT`; all six supported-state actions retain the planned structure.

**New findings**

None.

**Evidence**

```text
uv run python -m pytest -q tests/test_initial_deliveries.py -k 'test_t381_'
5 passed, 15 deselected in 9.98s

uv run python -m pytest -q tests/test_mcp_stdio.py -k 'test_t3_'
9 passed, 91 deselected in 5.67s
```

Unsupported-state probe:

```text
unsupported probe: status+receipt readable; retryable=false; tool=null; wakes=0; row_unchanged=true
```

Frozen T381 test diff against `621891aa0d44425610c564ac72f4b6c0c8b72726` is empty.

**Verdict: APPROVED**

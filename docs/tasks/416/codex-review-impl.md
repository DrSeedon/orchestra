<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

The context override fixes the immediate IA-mode failure, but concurrent shadow creates can still interleave between legacy allocation and canonical projection, causing task-store parity failures.

Review comment:

- [P1] Serialize the full shadow create — /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-delivery-visibility/app/tm.py:1587-1597
  With concurrent HTTP creates, this context only covers the legacy write; the candidate write happens after the legacy transaction releases its lock. A request can therefore allocate `n`, pause, let another request allocate and project `n+1`, then fail or record projection debt when the first candidate is written out of order, leaving canonical and legacy stores inconsistent. Hold the existing create serialization across both writes.

> ⚠ Codex usage unaccounted: ValueError: Codex completed turn reported zero tokens

## Round (2026-08-28T11:35:39Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Re-review status: **APPROVED**

- Prior P1: **FIXED** — `_TASK_CREATE_LOCK` now covers both legacy allocation and canonical projection.
- New findings: **none**

Evidence:

- Changed production line: “Keep the projection in this lock too, so its display number and expected canonical head stay paired with that write.”
- Command: `git diff --check && uv run python -m compileall -q app/tm.py`
- Output: `PASS: git diff --check; app/tm.py compiles`

Verdict: the reviewed diff satisfies the concurrency AC.

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The research correctly identifies `codex_review` subject selection as the primary causal seam and preserves the fail-closed merge behavior. I found no blocking flaw in the proposed direction.

## Findings (Conventional Comments)

- suggestion: `.orchestra/tasks/513/research.md:72` — `app/db.py:2828-2830` points to outcome/source constants, not the immutable-provenance enforcement; cite `review_receipt_finish` at `app/db.py:2987-3010` and `review_receipt_set_outcome` at `app/db.py:3013-3018`.

- suggestion: `.orchestra/tasks/513/research.md:86` — the README update scope is incomplete: `README.md:179` still says review “is not yet enforced by the merge code.” Require updating that statement too; `check_table.py` will not detect this contradiction.

- suggestion: `.orchestra/tasks/513/research.md:86` — the checker only verifies that `RECORD_REVIEW_THEN_NEW_OPERATION` exists in `app/merge_operations.py`; it does not validate the README’s target-worker claim or the `REVIEW_COVERAGE_MISSING` behavior. Do not describe it as mechanically checking both semantic claims.

- suggestion: `.orchestra/tasks/513/research.md:59-64` — the proposed `target_worker` seam should explicitly require a same-scope worker session, not merely any resolvable session name. The Phase-2 oracle should cover rejecting an orchestrator or wrong-scope target.

- question: `.orchestra/tasks/513/research.md:108-112` — the research cites `probe_current_behavior.py`, tests, route code, and git history, although this review scope excludes them. Which causal claims remain independently established using only the named production paths?

## Verdict

APPROVED — with the non-blocking corrections above.

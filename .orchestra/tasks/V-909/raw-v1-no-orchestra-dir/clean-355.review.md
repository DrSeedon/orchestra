## Summary

The commit adds content-bound merge receipts and gates task finalization on their persistence. I reviewed the complete specified diff without editing files.

## Findings

### Blocking

- **Malformed receipt data can crash receipt verification.** In [merge_receipts.py](/home/kesha/v909-work/v909-clean-355-1mry4k1e/app/ia/merge_receipts.py:224), `evidence.count` is converted with `int()` outside the `MergeReceiptError` handling used for other receipt fields. A durable receipt with a nonnumeric count raises `ValueError`; callers that catch `MergeReceiptError` can then fail instead of reporting the receipt as invalid. Validate this field inside the same guarded parsing path.

### Suggestion

- **The receipt mode has no application call site in the reviewed tree.** `merge_receipt_mode()` is only defined in this diff; no app code enters it. Consequently, `merge_receipt_configured()` remains false in ordinary execution, so receipt creation and enforcement are inactive. Wire the mode to the canonical task/evidence/head resolvers in the runtime path that runs task-aware merges.

## Verdict

NEEDS WORK
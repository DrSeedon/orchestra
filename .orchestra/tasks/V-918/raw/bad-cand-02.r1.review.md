## Summary

Reviewed the complete diff between the specified commits. The currency constant is used in the changed displays, but two strings in the task detail view interpolate it incorrectly.

## Findings

### Suggestion

- [app/static/js/app.js](/home/kesha/v918-work/v918-bad-cand-02.r1-_qm3ievl/app/static/js/app.js:4912): The price and debt expressions use single-quoted strings containing `'${CUR}'`. JavaScript renders those characters literally, so the task detail view will show `k ${CUR}` instead of `k ₽`. Use template literals or concatenate `CUR`.

## Verdict

NEEDS WORK
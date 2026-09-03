<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Apparently a 300-character cap needed a nine-file convoy, but the scoped #398 implementation is clean 😏

ACK. Summary shaping at [app/ia/projections.py:104](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-summary-detail/app/ia/projections.py:104) preserves metadata, records original length, and leaves `record`/`evidence` content untouched. Storage and `limit` remain unchanged.

## Findings

None in the two declared files.

Verbatim reviewed line:

```python
result["items"] = [_summary_item(item) for item in result["items"]]
```

Checks run:

- `uv run pytest -q tests/test_knowledge_detail_summary.py` — 2 passed
- Related runtime check — 5 passed

## Verdict

ACK — Correct. No blocking, suggestion, or question findings in scope.

The diff arrived at a two-file appointment carrying a nine-file suitcase. 🧳

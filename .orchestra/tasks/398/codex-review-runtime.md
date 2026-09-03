<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Another runtime seam where one keyword decides whether agents receive 300 characters or 70K 😏

Reviewed only `/tmp/398-runtime-summary.diff`, `app/ia/runtime.py`, and the new oracle. The implementation correctly defaults to `summary`, applies `_summary_item` only there, preserves full content for `record`/`evidence`, and performs no writes.

## Findings (blocking/suggestion/question)

None.

## Verdict

ACK. Test passed:

```text
uv run pytest -q tests/test_knowledge_runtime_detail_summary.py
2 passed in 1.93s
```

Verbatim reviewed line:

> Request progressive detail as `summary` < `record` < `evidence`.

Live proof after merge/restart remains for the orchestrator.

Apparently production still needs the chef to serve the already-tasted dish after restarting the kitchen.

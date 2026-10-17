## Summary

Reviewed the complete diff from `93fc6c8` to `0c10b92` and traced how `codex_review` configures `_run_exec`. No files were changed.

## Findings

### Suggestion

`_blind_review_error` requires a `## Verdict` heading for every nonempty `success_file`, even when `success_pattern` is empty. `codex_review` deliberately sets an empty pattern for `mode="review"` and does not pass `--require-verdict` to its finalizer in that mode. A review artifact without a verdict is therefore rejected by `_run_exec`, despite the caller not requiring one. Consider applying the verdict check only to exec reviews, or making it an explicit validation option. ([app/bg_jobs.py](/home/kesha/v909-work/v909-clean-180-cieodf48/app/bg_jobs.py:47), [app/mcp_stdio.py](/home/kesha/v909-work/v909-clean-180-cieodf48/app/mcp_stdio.py:2315))

## Verdict

NEEDS WORK
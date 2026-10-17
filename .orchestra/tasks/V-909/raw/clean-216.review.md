## Summary

Reviewed the complete diff between the specified commits. No files were changed. One suggestion finding: a Spark continuation can be moved to another model when the policy omits the optional `spark` block.

## Findings

### Suggestion

[app/runtime_router.py](/home/kesha/v909-work/v909-clean-216-mnev7e_1/app/runtime_router.py:1008): If `models.spark` is configured but `policy.spark` is `None`, `_spark_candidate` marks Spark excluded before checking whether this is a continuation already running on Spark. `_choose_candidate` then falls back to another eligible lane, potentially switching the running session’s model and resetting its native session. The policy validator permits this configuration, and the diff adds no test for it. Consider preserving the current Spark lane for continuations in this case, while still applying access, telemetry, and quota guards.

## Verdict

NEEDS WORK
# item-44

Commit under review (in /home/kesha/orchestra, read-only): `ecfcba9812a598efa1f80301414c95bbc56c315a`
Subject / date:
#216: #216: Spark выбирается по opt-in оператора; Sol-first порядок полос
2026-08-12

The diff reviewed is `git -C /home/kesha/orchestra show ecfcba9812a598efa1f80301414c95bbc56c315a -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the complete diff between the specified commits. No files were changed. One suggestion finding: a Spark continuation can be moved to another model when the policy omits the optional `spark` block.

## Findings

### Suggestion

[app/runtime_router.py](app/runtime_router.py:1008): If `models.spark` is configured but `policy.spark` is `None`, `_spark_candidate` marks Spark excluded before checking whether this is a continuation already running on Spark. `_choose_candidate` then falls back to another eligible lane, potentially switching the running session’s model and resetting its native session. The policy validator permits this configuration, and the diff adds no test for it. Consider preserving the current Spark lane for continuations in this case, while still applying access, telemetry, and quota guards.

## Verdict

NEEDS WORK

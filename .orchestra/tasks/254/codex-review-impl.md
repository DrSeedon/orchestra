## Summary

The changes are narrowly scoped and consistent with the diagnosis. Mailbox isolation does not hide a production defect: these unit tests target wake scheduling, while production sessions provide the mailbox-required fields and `_log`. The live canary remains bounded by 180s connect + 600s response + 30s disconnect, under the 840s pytest backstop.

## Findings

No blocking issues or actionable suggestions.

## Verdict

APPROVED

Verified:

`uv run pytest -q tests/test_limit_wake.py::test_turn_end_on_limit_wakes_only_after_status_left_running tests/test_limit_wake.py::test_normal_turn_end_does_not_schedule_a_wake --timeout=30`

Result: `2 passed in 4.79s`.

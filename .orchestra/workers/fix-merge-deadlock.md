# fix-merge-deadlock

- Orchestra: `needs_switch=1` plus nonempty `task_id` is not sufficient by itself to declare quarantine. Pre-task-tracker scopes and exact `done`/owner-NULL completion retain legacy auto-switch; a task-managed missing, unfinished, or owned task must block delivery before Git. Evidence: #465, `tests/test_adhoc_switch.py` + frozen promotion quarantine oracle.
- Manager tests that verify call ordering must return an explicit `QuotaDecision` instead of deriving one from live `QUOTA_GATED_LANES`; deployment env can legally turn the same fixture from blocked to available before the seam under test runs. Evidence: #465 merge-gate repair.

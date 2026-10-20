# V-983 — quota gate held nothing for Luna while a Codex window was at 100%

Trigger: seedon-orchestrator bug report 2026-10-20 08:19 UTC (bug-inbox record
20261020T081949.345836Z-278c43893527457facac0f5cea4024d7). Three gpt-6-luna workers received
`send_message` while the Codex 5h window was exhausted (reset 11:44:33Z); each delivery went out
immediately ("quota gate is not holding it") and each turn failed with stop_reason=error.

Cause: `evaluate_worker_admission` decides by the longest (7d) window. Luna is an ungated lane
(QUOTA_GATED_LANES=claude,sol), so only the hard stop applies, and only to the deciding window; an
exhausted 5h window with the weekly window below the stop admitted the delivery.

Fix (6579ac81b, worker fix-codex on Sonnet because Codex was exhausted): for codex/codex_spark
buckets any window with utilization >= 100 and a future `resets_at` makes the decision
`blocked`/`at_reset` with the latest such reset, so the existing WAITING_QUOTA queue holds and
releases it. Stale/absent observation, a reset already in the past, or an active manual override
keep the previous behaviour. No line/curve was added for Luna.

Verification: orchestrator reran test_quota_gate, test_quota_wait_queue, test_mcp_quota_gate,
test_quota_admission_e2e, test_codex_quota_103 — 146 passed; disabling the new branch fails
`test_luna_with_exhausted_five_hour_window_waits_until_its_reset` (also confirmed by the merge
mutation gate). Main CI run 39393094947 passed.

Activation: owner-delegated `/api/restart` 10:27 UTC, MainPID 1163912 → 1280490, GET / 302,
startup complete, MemoryHigh/Max 14/16 GiB in the cgroup, oom_score_adj 800, 23 bg jobs restored,
0 expired; cut_turns=9, restart notices injected for all 9 and all were running/waiting again.

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The plan has exactly seven vertical tickets and an acyclic dependency graph. The frozen test matches commit `ef4b03be` byte-for-byte. Its RED run collects successfully and reports 11 missing-behavior assertion failures—no ImportError or collection failure.

However, R1–R7 do not mechanically cover several high-risk contracts involving authorization, recovery, lost wakes, and idempotency. Some implementations capable of data loss or duplicate provider submission could pass the frozen oracle.

## Findings

blocking: [tests/test_message_delivery_receipts_380.py:385](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-send-message-receipt/tests/test_message_delivery_receipts_380.py:385) — R3 always supplies `DELIVERY_ID`; it never exercises blank-key UUID creation. An implementation could mint multiple UUIDs, mint one only after a timeout, or use a different ID for reconciliation and still pass. Add a blank-key arm asserting one generated UUID is used by both the sole POST and sole reconciliation GET, with no second POST.

blocking: [docs/tasks/380/plan.md:77](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-send-message-receipt/docs/tasks/380/plan.md:77) — Neither the authenticated status route nor `message_delivery_status()` is exercised. Consequently, the implementation could expose receipts across sources/projects, omit the route/tool, or return a materially different resource while all R1–R7 pass. Add owner/operator success and unrelated-source/internal-token denial cases.

blocking: [tests/test_message_delivery_receipts_380.py:606](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-send-message-receipt/tests/test_message_delivery_receipts_380.py:606) — R6 covers only proof-backed, same-project MCP identity plus ambiguous names. It does not cover cookie operator scope, authorized cross-project resolution, archived targets, source-task authorization, or the rule that a shared internal token without MCP proof is insufficient. This leaves the principal/project authorization boundary largely unguarded.

blocking: [docs/tasks/380/plan.md:196](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-send-message-receipt/docs/tasks/380/plan.md:196) — The promised accept-while-runner-exits lost-wake protection has no race oracle. R7 disables scheduling and performs sequential accepts; it never interleaves a new commit with the runner’s empty-head exit/done callback. An implementation that permanently strands a committed `QUEUED` row can pass. Add a deterministic event-barrier race around the durable-head recheck.

blocking: [tests/test_message_delivery_receipts_380.py:705](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-send-message-receipt/tests/test_message_delivery_receipts_380.py:705) — FIFO is tested only with sequential acceptance. It does not verify concurrent `BEGIN IMMEDIATE` acceptance, commit-order/`accept_seq` agreement, or two competing target runners. A non-transactional read/insert or multiple-runner race capable of overtaking or duplicate submission could pass.

blocking: [docs/tasks/380/plan.md:303](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-send-message-receipt/docs/tasks/380/plan.md:303) — Orphaned `DISPATCHING` recovery is untested. R5 explicitly changes the row to `DELIVERY_UNKNOWN` before calling recovery, so recovery could incorrectly requeue and replay an actual orphaned `DISPATCHING` row without failing R5. Freeze a row in `DISPATCHING`, invoke recovery, and assert atomic transition to `DELIVERY_UNKNOWN`, zero scheduling, and zero provider attempts.

blocking: [tests/test_message_delivery_receipts_380.py:791](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-send-message-receipt/tests/test_message_delivery_receipts_380.py:791) — The #385 test manually clears the interrupt flag, changes status to idle, and directly invokes `run_target_message_deliveries`. It does not exercise either planned safe-boundary wake hook. The implementation could omit the terminal-event/compact-completion wake entirely, leaving the durable message stuck forever, and still pass. It also does not cover compacting or a running provider without mid-turn injection.

blocking: [docs/tasks/380/plan.md:215](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-send-message-receipt/docs/tasks/380/plan.md:215) — Atomic receipt/log transitions are asserted only by final row counts. No injected fault occurs between user-log insertion and `PREPARING`, or between state transitions and commit. Separate transactions—or recovery that creates a second user row after a partial failure—could satisfy the happy-path assertions while accepting duplication/data loss. Add rollback fault points around the paired receipt/log mutation.

suggestion: [docs/tasks/380/plan.md:38](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-send-message-receipt/docs/tasks/380/plan.md:38) — `UNSUPPORTED_KEYED_INGRESS`, legacy blank-key routing, scheduling-failure-after-commit behavior, and commit-error reconciliation are required contracts but absent from R1–R7. Existing compatibility tests help with legacy behavior, but do not establish that the new keyed branch is selected before mailbox/fan routing or that a committed receipt still returns 202 when scheduling fails. Add focused frozen assertions or explicitly narrow the claim that R1–R7 mechanically cover every contract.

## Verdict

Needs work; Phase 2 should not be accepted as the immutable implementation gate yet. The ticket graph is sound and there is no evident scope creep, but the oracle currently permits security-boundary omissions, stranded accepted messages, and replay of an orphaned provider attempt.

## Attempt log

- Attempt 2 started 2026-08-23 after plan changes and review-driven oracle re-freeze
  `0f4ee12a`; resume the same Sol thread and resolve every Round 1 blocking finding.
- Attempt 2 rejected by the wrapper before reviewer execution:
  `invalid_argument: context must include caller-supplied task instructions and PROJECT CONTEXT`;
  no reviewer output and no review round.
- Attempt 3 started 2026-08-23 with the required explicit task and PROJECT CONTEXT blocks.

## Round (2026-08-23T21:14:41Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Frozen test matches commit `0f4ee12a` exactly. RED verification collected normally and produced 21 assertion failures for missing #380 behavior, with no ImportError or collection failure.

Prior findings:

- FIXED: blank-key UUID stability and MCP status tool.
- FIXED: status/source/operator/internal-token authorization coverage.
- FIXED: cross-project, archive, and server-derived identity coverage.
- STILL BROKEN: production lost-wake wiring.
- FIXED: concurrent FIFO and competing-runner serialization.
- FIXED: orphan `DISPATCHING` recovery.
- STILL BROKEN: production safe-boundary wake.
- FIXED: transactional log/`PREPARING` rollback.
- FIXED: unsupported ingress, legacy split, scheduler failure, commit-ack reconciliation, and keyed-before-fan coverage.

## Findings

blocking: [tests/test_message_delivery_receipts_380.py:1217](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-send-message-receipt/tests/test_message_delivery_receipts_380.py:1217) — The lost-wake test manually installs both production seams: it writes `registry[TARGET_ID] = first_runner` and calls `first_runner.add_done_callback(observe_runner)`. Therefore `ensure_target_runner()` could omit the registry entry or done callback—the actual lost-wake bug—and the oracle would still pass. Exercise `ensure_target_runner()` itself to create/register the first runner, then interleave acceptance at its empty-head boundary.

blocking: [tests/test_message_delivery_receipts_380.py:1416](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-send-message-receipt/tests/test_message_delivery_receipts_380.py:1416) — The #385/compact wake oracle still calls `_wake_durable_message_deliveries()` directly and checks production wiring only by searching source text. Dead or unreachable calls inside `_turn_event_loop` and `compact` satisfy those assertions. The compact/no-inject test also stops at `PREPARING` without executing a real safe-boundary owner. An implementation that permanently strands all deferred receipts can pass. Invoke the relevant terminal/finalization path and compact-completion path, then assert one wake, one submission, and one user row.

suggestion: [tests/test_message_delivery_receipts_380.py:179](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-send-message-receipt/tests/test_message_delivery_receipts_380.py:179) — Canonical-hash coverage still changes only message/rendered-message. A hash implementation omitting target generation, source task, or protocol could pass. Add at least one same-key conflict where a server-derived hashed identity field changes, especially target generation.

## Verdict

Needs work. Most Round 1 gaps are now closed, but two high-risk oracles still test manually assembled primitives instead of the production wiring whose omission would strand committed messages.

## Attempt ceiling / post-Round-2 evidence

The canonical attempt ceiling is exhausted: Attempt 1 produced Round 1; Attempt 2 was rejected by
the wrapper before reviewer execution; Attempt 3 produced Round 2. A fourth call is forbidden even
though the executable-subject round ceiling would otherwise permit it. Therefore there is **no final
independent verdict**; the last reviewer verdict remains `Needs work` until the task giver decides
how to proceed.

The two Round 2 blockers and suggestion were changed and re-frozen at `c42163d9`:

- lost-wake R7 now calls production `ensure_target_runner(TARGET_ID)`; it reads the task registered
  by production but never writes `_target_runner_tasks` and never attaches a done callback;
- no-inject and #385 cases invoke `AgentSession._turn_event_loop()` itself; native Codex and Claude
  compact cases each start and complete `session.compact()` itself, then assert one durable wake,
  submission, and user row;
- same-key unchanged-message input with changed target task/generation now asserts 409 conflict.

Mechanical self-check:

```text
git diff --exit-code c42163d9 -- tests/test_message_delivery_receipts_380.py -> exit 0
combined RED -> exit 1, 22 failed, no ImportError/collection error
grep production-path anchors -> ensure_target_runner at line 1226; _turn_event_loop at lines
1390/1664; session.compact at lines 1460/1580; no manual registry assignment/add_done_callback
```

Review route: Sol, 2 completed rounds / 3 total attempts. Verdict: **no final verdict; last reviewer
verdict Needs work, post-fix confirmation blocked by attempt ceiling**.

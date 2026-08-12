## Summary

All 10 frozen tests are RED as stated. However, several oracles can become GREEN without proving their ticket’s intended behavior. T6 also has viable non-model checks, so `oracle: none` is not justified.

## Findings

1. **blocking: T3 — `test_t3_drains_at_turn_end_instead_of_waking` does not prove continuation or mailbox delivery.**

   The test says:

   > `assert len(spawned) >= 2, (`

   Any unrelated second background coroutine satisfies this. The test neither identifies `_auto_continue`, inspects its payload, executes it, nor verifies that the mailbox message entered the continued turn. A defective implementation that merely spawns a no-op alongside `_notify_scope_idle()` passes. The oracle must identify the continuation semantically and verify the queued body is supplied.

2. **blocking: T3 — no oracle proves successful delivery is acknowledged after actual issuance.**

   The plan requires:

   > `**\`delivered_at\` проставляется ПОСЛЕ фактической выдачи, не в момент`

   But one test calls `mark_delivered` directly, the happy-path test closes every coroutine without executing it, and the dropped-continuation test only checks that the row remains pending. There is no test where the continuation succeeds and the row subsequently disappears. An implementation that never marks delivered passes all current T3 tests, causing every mailbox item to replay forever.

3. **blocking: T1 — caller-overridable deadline is not tested.**

   The test claims:

   > `"""Кривая дедлайна имеет смысл, только если вызывающий может выбрать точку."""`

   It passes `deadline_seconds=5.0`, but only asserts `should_buffer("x1")` and that a parent exists. An implementation that ignores `5.0` and always uses `1800.0` passes. The oracle needs to observe the stored deadline or force expiry under a controlled clock.

4. **blocking: T4 — “reachable by role” can pass with a dead helper.**

   The oracle only requires:

   > `assert m.access_mode_for_role("reducer") == "reducer"`

   Current MCP initialization reads `ORCHESTRA_ACCESS_MODE` directly; merely adding an unused `access_mode_for_role()` makes this test GREEN without setting the environment at spawn or changing the effective tool surface. The test needs to exercise the actual spawn/configuration path and then the resulting MCP access mode.

5. **blocking: T4 — the oracle does not verify the promised reading capability or the complete prohibition set.**

   The plan promises:

   > `Редьюсеру ОТДАЮТСЯ: \`send_message\`, \`update_progress\`, чтение.`

   Yet the test asserts only `send_message` and `update_progress`; `list_agents` and `search_memory` are placed in the synthetic input but never required in the output. It also tests only `payment_receive`, despite the plan prohibiting `payment_*`. A reducer with no reading tools, or with another payment tool exposed, passes.

6. **blocking: T6 — `oracle: none` is avoidable.**

   The plan states:

   > `поведенческой, ни delivery-проверки на это нет. Единственная честная приёмка — замер на живом`

   A deterministic integration check is viable without models: create a fan with parent, reducer, and three children; submit each child completion through the production route; assert all child reports target only the reducer; submit one reducer result; assert the parent’s `manager.send` count is exactly one and its payload contains every distinct child marker. A separate spawn/configuration check can assert the reducer role and access mode are delivered. The live model run remains useful for end-to-end validation, but it is not the only possible oracle.

7. **blocking: T3 — missing dependency/order contract with T1 permits premature parent release.**

   The plan says:

   > `if allow_auto_report and s.status != AgentStatus.WAITING:`

   This production-path line is reproduced by the frozen test context, while the cited method currently invokes `fire_auto_report()` before checking pending work. Under T1, `fire_auto_report()` can record the child terminal and release the fan before T3 drains that child’s mailbox. The continuation may then produce another report or leave the released manifest incomplete. T3 should depend on T1 and explicitly require mailbox drain/continuation to take precedence over barrier terminal reporting.

8. **blocking: T5 — the prompt-failure analysis reverses the dangerous direction.**

   The plan claims:

   > `Последняя строка — сознательная уступка: проверка «агент правило забыл» → редьюсер отдаёт лишнее,`

   If the reducer forgets “do not select,” it can select, summarize, and omit reports—the exact data-loss behavior R6 forbids. That is not merely “отдаёт лишнее.” Conversely, applying the restriction too broadly may make it refuse transformation or output. Since at least one failure direction loses child reports, the stated benign-both-ways justification is invalid. Completeness needs code-enforced structured aggregation or a behavioral oracle, not delivery of prompt anchors alone.

9. **suggestion: T3 — cited implementation location is misleading.**

   The plan says:

   > `**Files:** \`app/session_turns.py\` (рядом с \`_auto_continue\`, \`session_turns.py:387\`)`

   Line 387 is the `max_turns` condition that calls `_auto_continue`; the relevant end-of-turn orchestration seam is `after_turn_idle_actions` at line 490. Directing implementation “near 387” encourages adding mailbox behavior to the max-turn-only path rather than the general paid-turn completion path.

## Verdict

**REJECT — blocking oracle gaps remain.** The frozen suite is correctly RED, but T1, T3, T4, and T6 can be satisfied or declared complete without proving their intended behavior, and the T1/T3 ordering contract is missing.

## Round (2026-08-12T13:52:59Z)

## Round 2

### Re-review status

1. T3 unrelated background tasks — **FIXED**.
2. T3 successful delivery never acknowledged — **FIXED**.
3. T1 caller deadline ignored — **FIXED**.
4. T4 dead role helper — **FIXED**.
5. T4 incomplete tool/read checks — **FIXED for named tools**, but see new allowlist finding below.
6. T6 `oracle: none` — **FIXED**.
7. T3/T1 ordering — **STILL BROKEN**; only the auto-report path is ordered.
8. T5 prompt-based completeness — **FIXED** conceptually, but the new T6 oracle incompletely proves it.

The observed state matches the plan: **13 failed, 1 passed**.

The passing regression guard is acceptable. A test that is already green is blocking only when presented as evidence for new behavior. This one explicitly protects unchanged empty-mailbox behavior:

> `assert reported == [1], (`

Keeping that guard beside the ticket tests is appropriate.

## Findings

1. **blocking: T6 — completeness oracle checks child names, not child reports.**

   The inputs contain distinct report bodies:

   > `_report("c1", "нашёл A")`  
   > `_report("c2", "нашёл B")`

   But the final assertion checks only `"c1"` and `"c2"`. `manifest_text()` already contains member names even when report contents are discarded. An implementation can lose both “нашёл A” and “нашёл B” and still pass. Assert unique report-body markers in the parent payload, not merely member identifiers.

2. **blocking: T6 — silent-reducer test does not verify that the single delivery targets the parent.**

   It destructures and then ignores the destination:

   > `(_sid, text), = spy.sent`

   A defective implementation that sends the complete payload back to `sid-R`, or another session, passes. Assert `_sid == "sid-parent"` in this test.

3. **blocking: T3/T1 — ordering remains incomplete because the explicit-report gate can release the fan before mailbox drain.**

   The test helper exercises the explicit route:

   > `return asyncio.run(send_message("parent", SendRequest(`

   The new ordering only moves mailbox handling before `fire_auto_report()`. A child can explicitly call `send_message` while it still has undelivered mailbox input; the route’s other barrier gate immediately calls `record_terminal`, potentially releasing the fan before `after_turn_idle_actions()` runs. The contract must cover both terminal paths—explicit report and auto-report—and have an oracle where a child reports while its mailbox is non-empty.

   There is also a check/release race if “mailbox empty” and `record_terminal()` are separate operations: `wake=False` can enqueue between them. The release decision needs an atomic DB-level condition or equivalent serialization.

4. **blocking: T4 — the oracle permits future or omitted mutating tools because it tests a handcrafted universe.**

   The test constructs:

   > `everything = FORBIDDEN | REQUIRED`

   Therefore it cannot detect a registered mutating tool omitted from `FORBIDDEN`; a reducer implementation based on `names - FORBIDDEN` passes. For a “pure reducer,” the safe contract is a positive allowlist. Test with at least one unknown synthetic mutator and require it to be removed, or compare the reducer surface against an exact allowed set derived from the actual registered tool names.

## Verdict

**REJECT.** Six prior issues are fully fixed, one is substantially fixed, and the green regression guard is legitimate. Remaining blockers are the incomplete T6 payload/address oracle and the unresolved explicit-report/atomicity path in T3↔T1.

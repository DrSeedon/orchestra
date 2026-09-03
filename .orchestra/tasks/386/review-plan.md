<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The plan identifies the correct security boundaries, and the RED suite genuinely fails for missing behavior rather than import or collection errors. It also has useful real-Git controls for nested versus main selection and both target-movement windows.

However, the frozen tests leave several required admission guarantees mechanically unasserted, and the three implementation tickets are horizontal layers rather than independently usable vertical slices.

## Findings

1. **blocking — The tickets are horizontal slices.**
   T1 implements oracle persistence/execution without merge admission, T2 adds admission/selection without the locked mutation guarantee, and T3 finally connects locking and result evidence ([plan.md:185](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/docs/tasks/386/plan.md:185), [plan.md:202](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/docs/tasks/386/plan.md:202), [plan.md:219](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/docs/tasks/386/plan.md:219)). No ticket before T3 safely delivers the requested merge behavior. Collapse this into one vertical ticket, or redefine each ticket so its committed state cannot expose a partially enforced admission path.

2. **blocking — The operation runner’s fail-closed composition is not tested.**
   Nested/main/mapped behavior is tested by calling `evaluate_test_gate` directly, while the sole `_run_operation` test mocks the oracle, mapped gate, and merge execution as successful ([test:416](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:416), [test:714](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:714)). An implementation could ignore `FAILED`, `INCONCLUSIVE`, or `SKIPPED` mapped results—or ignore non-PASSED oracle results—and still satisfy all tests. Add operation-level controls proving each non-authorizing result prevents `execute_merge_session`.

3. **blocking — Effective-target fallback and pin-before-selection ordering are unasserted.**
   The plan requires explicit target or accepted `base_branch`, resolved and pinned before selection ([plan.md:80](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/docs/tasks/386/plan.md:80)). The only public-operation test always supplies `target="integration"` and disables the runner ([test:508](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:508)). It does not test omitted-target fallback, nor prove that `_run_operation` passes the stored target SHA—rather than a freshly resolved ref—to both oracle and mapped selection.

4. **blocking — Worker/caller authority is only partially covered.**
   The RED suite tests worker rejection only through MCP `task_update`, and tests only a successful HTTP update with authorization checks mocked true ([test:227](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:227), [test:248](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:248)). It does not mechanically cover create, clear, unauthorized HTTP update, project-scope mismatch, or forged actor fields. Those omissions leave mutable or worker-controlled oracle paths compatible with the frozen tests despite the contract at [plan.md:71](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/docs/tasks/386/plan.md:71).

5. **blocking — Immutable-input protection is materially under-tested.**
   Only mutation of one listed helper is exercised ([test:317](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:317)). There are no controls for candidate-modified ticket command inputs, manifest omission, file mode changes, dirty working-tree bytes, or added/changed `conftest.py` and pytest configuration outside the manifest, although the plan explicitly requires all of them to refuse before execution ([plan.md:93](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/docs/tasks/386/plan.md:93)). An implementation checking only the demonstrated helper/blob case would pass.

6. **blocking — Schema migration and replay compatibility have no RED oracle.**
   Both new columns affect durable shared state, and `tm_tasks` already has a table-recreation migration path where duplicated column lists can drift. The tests initialize only fresh databases. They never open an old schema, verify preservation through recreation, reject malformed non-empty JSON, or replay a stored operation after the task revision/target changes. This leaves the migration and replay requirements at [plan.md:235](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/docs/tasks/386/plan.md:235) entirely non-mechanical.

7. **blocking — “Every terminal result” is tested only for success.**
   The contract requires admission evidence on refusals before execution ([plan.md:133](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/docs/tasks/386/plan.md:133)), but the result test constructs a fabricated successful snapshot with an empty manifest and asserts only `SUCCEEDED` ([test:677](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:677), [test:768](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:768)). Missing/mutated oracle, mapped failure, and both target-move refusals are not checked through the terminal operation/API result.

8. **blocking — Final-only fallback is prose-only.**
   The plan promises that docs-only/final-only behavior remains available ([plan.md:74](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/docs/tasks/386/plan.md:74), [plan.md:241](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/docs/tasks/386/plan.md:241)), but the frozen test contains no final-only control. An implementation that makes the new oracle mandatory for every merge could pass this suite.

## Verdict

**CHANGES REQUIRED**

The target-relative Git controls and late target-recheck test are strong, and the plan explicitly rejects failure-set subtraction. Nevertheless, the missing end-to-end fail-closed assertions, authority controls, migration coverage, refusal audit coverage, fallback control, and horizontal ticket structure are blocking for this shared merge-admission surface.

## Author response after Round 1

All eight blockers were verified and accepted. The executable oracle was changed and re-frozen;
`dd86a8f9` and `a2fd2d65` are superseded/excluded. Final immutable RED commit is `47380a67`.

1. **FIXED — verticality:** collapsed the three horizontal layers into one atomic T1 spanning task
   authority, operation snapshot/runner, target-relative gate, mutation lock, and result evidence.
2. **FIXED — runner composition:** added eight operation-level oracle/mapped non-authorizing cases;
   each asserts `execute_merge_session` is not awaited and refusal admission evidence is present.
3. **FIXED — target fallback/order:** public operation is parameterized for explicit `integration`
   and omitted-target/base fallback. A runner test moves the branch after persistence and asserts the
   stored SHA reaches oracle evaluation, mapped selection, and merge execution.
4. **FIXED — authority:** added worker create/update/clear/narrow controls; verified-parent create
   and update with forged actor ignored; unauthorized HTTP and cross-project refusal.
5. **FIXED — immutable inputs:** task manifest now mandates recursive target `tests/` plus pytest
   config. Tests cover manifest narrowing, committed helper mutation, dirty ticket/conftest/config
   bytes, file mode, and added root conftest/pytest config, all before subprocess execution.
6. **FIXED — migration/replay:** added old-schema autoindex recreation, non-empty bundle preservation,
   old merge-operation column migration, malformed JSON refusal, and same-operation replay after
   both task revision and target ref move.
7. **FIXED — refusal audit:** operation-level missing/mutated/mapped failures and target-move refusal
   assert terminal target/oracle/mapped/recheck evidence; success remains covered with non-empty
   manifest.
8. **FIXED — final-only:** graph adds final F with all ticket/mapped tests green; direct main gate and
   operation-level no-oracle main merge both must pass, proving the oracle is not made universal.

Final RED command:
`uv run --frozen python -m pytest -q tests/test_merge_target_oracle_386.py -k 'test_t386_t1_'`
→ exit 1, `32 failed in 44.88s`; first failure is the missing task oracle API, not collection/import.

## Round (2026-08-24T00:08:43Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Seven of eight prior blockers are fixed. The revised plan is now one atomic vertical ticket, and the frozen RED suite substantially improves operation-level, migration, immutability, target-integrity, refusal-audit, and fallback coverage.

One authority hole remains mechanically untested: unauthorized and cross-project HTTP task creation with oracle fields.

## Findings

1. **FIXED — Horizontal ticket structure.**
   The plan now defines one atomic T1 spanning persistence, authorization, admission, regression gating, locking, execution wiring, and terminal evidence ([plan.md:184](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/docs/tasks/386/plan.md:184)).

2. **FIXED — Runner fail-closed composition.**
   Eight operation-level cases cover every oracle/mapped non-authorizing status, assert `FAILED`, `NOT_REACHED`, and that the executor was not called ([test:1138](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:1138)).

3. **FIXED — Effective target fallback and stored-SHA wiring.**
   The public operation test is parameterized over explicit `"integration"` and omitted `""` targets ([test:826](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:826)). A separate runner test moves the branch and verifies the stored SHA reaches oracle evaluation, mapped gating, and `expected_target_head` execution ([test:1211](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:1211)).

4. **blocking — STILL BROKEN: HTTP create authorization and project scoping are not negatively tested.**
   Worker MCP create/update/clear/narrow is covered ([test:398](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:398)), and verified HTTP create/update actor derivation is covered ([test:436](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:436)). But the negative HTTP test exercises only `tm_update_task` for unauthorized and cross-project callers ([test:516](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:516)). An implementation could correctly protect update while allowing an unauthorized or cross-project caller to create a task with a mutable authoritative oracle through `tm_create_task`, and all frozen tests would pass. Add unauthorized-create and cross-project-create controls asserting no `api_create_task` call.

5. **FIXED — Immutable oracle inputs.**
   The suite covers helper, ticket, conftest and config bytes; file mode; candidate-added root conftest/config; narrow manifests; and verifies refusal before subprocess execution ([test:588](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:588), [test:637](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:637)).

6. **FIXED — Schema migration and replay.**
   The old-schema test exercises the legacy unique-index recreation path, preserves an existing oracle bundle, migrates a missing operation column, and retains the operation row ([test:268](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:268)). Public-operation replay is also checked after both task revision and target movement.

7. **FIXED — Terminal refusal evidence.**
   Non-authorizing operation cases assert structured admission evidence and no executor. The moved-target runner case verifies target recheck evidence, while the successful terminal case verifies the complete admission object with a non-empty manifest ([test:1151](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:1151), [test:1417](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:1417)).

8. **FIXED — Final-only fallback.**
   The operation-level final-only control requires no ticket oracle, retains the independent mapped gate, reaches the executor, and records `not_required` plus mapped files ([test:1307](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:1307)).

No genuinely new merge-admission blockers were found.

## Verdict

**CHANGES REQUIRED**

Add negative HTTP create controls for both unauthorized and cross-project oracle creation. After that, the prior blocking set appears closed.

## Author response after Round 2

- ACK finding 4 after verifying `tm_create_task` has a separate authorization/project branch from
  `tm_update_task`. The frozen authority test now calls unauthorized HTTP create and cross-project
  HTTP create, asserts 403/400 respectively, and proves `api_create_task` was never called. Update
  controls remain alongside them.
- The executable oracle changed and was re-frozen once more. `47380a67` is superseded/excluded;
  final immutable RED commit is `b1af1b07a19da73f5f62e14bafdd317ea743b0b8`.
- Exact command remains
  `uv run --frozen python -m pytest -q tests/test_merge_target_oracle_386.py -k 'test_t386_t1_'`
  → exit 1, `32 failed in 45.70s`, no collection/import error.

## Round (2026-08-24T00:11:25Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Prior Round-2 finding 4 is **FIXED**. The immutable RED suite now closes both missing HTTP-create authority paths.

## Findings

- **FIXED — Unauthorized HTTP create:** `tm_create_task` must return 403, report `orchestrator-only`, and never call `api_create_task` ([test:560](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:560)).

- **FIXED — Cross-project HTTP create:** creation under another project must return 400, report project isolation, and leave both create/update APIs untouched ([test:588](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-regression-aware-merge/tests/test_merge_target_oracle_386.py:588)).

- The plan’s authority AC matches these controls: “forged actor fields are ignored and the verified caller is stored.”

No new blocker was introduced by this narrow change.

## Verdict

**APPROVED**

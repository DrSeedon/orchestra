## Summary

The architecture is directionally sound, but it is not ready for implementation. Two race/deployment issues can produce false lifecycle state or make merges unavailable, and the frozen RED oracle does not enforce several central invariants claimed by the plan.

## Findings

1. **blocking:** Completion is not serialized against new bindings.

   The plan checks for “other live bindings” before Git, but spawn/send can bind another session after that check and before the post-commit finalizer. The current session lifecycle lock protects only the merging worker; the repo lock does not serialize SQLite task assignment. Git can therefore commit, followed by either an incorrect `done` transition while another worker is active or a post-commit refusal that cannot undo Git.

   T1 assignment and T3 completion need a shared server-owned serialization mechanism—for example, a task-level completion reservation persisted before Git and honored by every binding path. The finalizer must verify that reservation in its transaction. Add an acceptance test that pauses completion after preflight, attempts a concurrent bind, and proves exactly one operation succeeds.

2. **blocking:** The deployment plan does not account for surviving old MCP processes.

   The plan correctly states that existing MCP processes do not gain the new `task_outcome` argument until reconnection, but then treats one Orchestra restart as sufficient. In this deployment, long-lived MCP subprocesses may survive the server restart; their published tool schema still lacks `task_outcome`. Once the restarted route enforces the field, those agents cannot express a valid merge request and every merge fails closed.

   The rollout needs an explicit compatibility gate based on a bumped merge capability/schema and a coordinated MCP reconnection strategy. A permissive default is not required, but enforcement cannot be enabled until callers advertise the new capability. This should be tested with an old-shape request originating from a pre-upgrade tool schema.

3. **blocking:** The proposed PARTIAL replay is not represented by a durable resumable stage or tested by the frozen oracle.

   Current merge operations treat terminal records as replay results; replaying the same request does not execute `execute_merge_session` again. The plan says a same-ID replay will run only the unfinished DB finalizer, but it does not define the persisted post-commit payload/stage marker needed to do so, how ownership is reacquired, or how a terminal `PARTIAL` record transitions back into finalization.

   The existing replay test only performs a successful merge and then reads the successful result again. It would pass without any PARTIAL-resume implementation. Define the resumable stage and its durable inputs—validated task identities, outcome, linked commits, terminal session state, and next-task intent—and add a test that fails the DB finalizer after Git commit, then replays the same operation and proves one Git call plus a completed lifecycle transition.

4. **suggestion:** The RED tests do not enforce the commit-reference invariants that carry most of T2’s risk.

   The real-repository test covers one unknown subject reference, but not:

   - multiple candidate commits and multiple references;
   - a valid additional reference being linked;
   - a reference belonging to another project;
   - no-reference canonical subject injection;
   - mutation between route preflight and the repo-lock recheck;
   - validation against the exact pinned HEAD.

   An implementation could validate only one extracted reference before Git and still satisfy the frozen suite. Add a compound real-repository test that mutates or substitutes the candidate set at the repo-lock boundary and confirms the target ref remains byte-identical.

5. **suggestion:** The send-assignment oracle does not prove durable or authorized binding.

   `test_t1_taskless_assignment_replaces_made_up_number_with_canonical_task` uses a synthetic in-memory target with no persisted session row. It checks `tm_tasks.worker_session_id`, but not `sessions.task_id`, transaction atomicity, or that `req.sender` equals the target’s actual parent. Thus it can pass with a one-sided tracker update or with automatic allocation triggered by any sender in the scope.

   Seed a real session and assert both rows after success and after an injected failure. Also test a non-parent sender and require refusal before task creation or delivery.

6. **suggestion:** Several lifecycle invariants stated as acceptance criteria have no frozen oracle.

   Missing cases include:

   - `complete` rejected when another live binding exists;
   - `next_task_id` rejected with `continue`;
   - atomic current-complete/next-in-progress transition;
   - archive with another live binding preserving `in_progress`;
   - zero-price, prepayment, and YouGile parity;
   - manual agent lifecycle rejection through every agent-facing create/update shape;
   - post-commit finalization failure and retry.

   These are not incidental coverage gaps: they distinguish the intended single lifecycle owner from an implementation that merely makes the four happy paths green.

7. **suggestion:** The prompt test does not actually reject a static tracker snapshot.

   T4 only checks removal of two old phrases and presence of one new sentence. It does not prove that prompt assembly contains no generated task list, task DTO, or tracker read. A static snapshot could be added alongside the required sentence and the test would remain green.

   Add a test that changes tracker data between two prompt builds and asserts neither value appears, while consecutive `list_agents` calls do reflect the change.

## Verdict

**CHANGES REQUESTED — 3 blocking findings.**

The task-level completion race and long-lived MCP rollout must be resolved in the plan. The durable PARTIAL-finalization state machine also needs to be specified and frozen in the acceptance oracle before implementation; otherwise the plan cannot demonstrate its own same-operation recovery guarantee.

## Round (2026-08-13T08:11:03Z)

## Summary

Six prior findings are fixed. One remains partially unresolved, and there is one new blocking durability gap in the same finalization design.

## Findings

1. **FIXED — concurrent completion/binding race.** The unique task reservation is shared by completion, spawn, and send; the concurrent-bind RED exercises the critical interval while Git is running.

2. **FIXED — mixed MCP/server rollout.** Capability v2 handles both directions safely: new-client/old-server refuses before POST, while old-client/new-server is restricted to legacy `continue`.

3. **STILL BROKEN — durable post-commit recovery.** The replay state machine is substantially improved, but `PENDING` and `finalization_json` are first persisted only **after** Git reaches its commit point. If that SQLite write itself fails—or the process dies between the Git commit and this write—the durable record still lacks the confirmed commit point and finalization payload. Recovery therefore follows the stated `RUNNING`-without-durable-commit-point → `UNKNOWN` path, and same-operation replay cannot perform the promised DB-only finalization.

   This is blocking because Git has mutated `main` while task status, commit links, payment, and session lifecycle can remain unresolved indefinitely. Persist a prepared finalization record before Git, then provide a recoverable post-Git marker/reconciliation mechanism; freeze a RED that fails the **first post-Git persistence**, not only `link_commits_to_task`.

4. **FIXED — commit-reference oracle.** The suite now covers multiple refs, canonical no-ref injection, foreign scope, exact target immutability, and emitted-header substitution under the repo lock.

5. **FIXED — send allocation authorization and atomicity.** The durable parent is authoritative, both session/task rows are asserted, unauthorized send creates no row, and switch failure leaves only an unbound `new` task without delivery.

6. **FIXED — lifecycle invariant coverage.** The suite now covers second bindings, concurrent binding, continue/next rejection, complete/next transition, archive recomputation, payment/sync, and agent-tool override rejection.

7. **FIXED — static prompt snapshot rejection.** Changing tracker titles are explicitly excluded from rebuilt prompts while `list_agents` proves fresh reads.

## Verdict

**CHANGES REQUESTED — 1 blocking finding.**

The architecture is otherwise ready, but the post-Git persistence window must be closed before implementation.

## Author evidence status and owner resolution

Round 2 exhausted the two-round prose ceiling. It did not include either a test command with its
result or the requested exact sentence from the reviewed plan. Under the `codex-debate` evidence
criterion its formal outcome is therefore **«вердикта нет, ревью без доказательств»**, not an
evidence-backed approval or rejection.

The remaining checkpoint finding was independently accepted by tracing `_run_operation()`:
`execute_merge_session()` mutates Git and task/session state before `finish_operation()` first
records the durable commit point. Orchestra-orchestrator approved closing it without a third review
round: pre-Git `PREPARED`, platform-owned exact operation trailer, parent/tree reconciliation, and a
new RED that drops the first post-Git write. The revised design is in `plan.md`; the new frozen
oracle is `b7ad6c76`. Earlier oracle revisions `d8cf99f8` and `b4558c64` are permanently marked
exploratory in the plan.

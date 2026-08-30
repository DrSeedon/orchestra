<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну конечно, шесть `F` — зато теперь ясно, где именно план решил притвориться проверкой 😏

## Summary

The supersession is internally coherent: `portfolio_projects` represents human projects, while `tm_projects` remains the technical task namespace. However, approval is blocked by canonical-cleanup, authorization, and race-safety gaps. The frozen tests are collection-clean but several only check missing routes/signatures.

Exact full command result:

```text
FFFFFF                                                                   [100%]
6 failed in 1.18s
RC=1
```

## Findings (blocking/suggestion/question)

1. **blocking: Compare cleanup rows against the frozen canonical snapshot before applying.**
   [plan.md:345](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:345), [plan.md:365](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:365)
   The plan requires rejecting revision, canonical-head, and binding mismatches, but the apply skeleton reads `stable_id` and `canonical_head` from a fresh `api_get_task()` result and does not compare them with frozen values. A canonical change after the inventory snapshot can therefore be accepted as the expected state and applied, risking projection drift. The manifest and skeleton need explicit per-task frozen values and a fail-closed comparison.

2. **blocking: Enforce eligible session roles and lifecycle transitions in membership authorization.**
   [plan.md:51](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:51), [plan.md:157](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:157), [test_project_portfolio_418.py:87](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/acceptance/test_project_portfolio_418.py:87)
   The membership schema only references a session and validates the membership role; it does not require the target session to be an allowed orchestrator/sub-orchestrator. The test never attempts worker ownership, sub-orchestrator ownership, respawned-session access, or reparent-without-grant. Without explicit checks, a worker could receive project privileges, while respawn/reparent behavior could silently retain or lose access contrary to the stated contract.

3. **blocking: Reuse existing task authorization when creating portfolio links.**
   [plan.md:67](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:67), [plan.md:165](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/418/plan.md:165), [test_project_portfolio_418.py:155](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/acceptance/test_project_portfolio_418.py:155)
   The request contains arbitrary `task_project` and `task_ref`, while the AC only requires rejecting nonmembers. “Tasks it may already access” is not an executable authorization rule. A contributor could otherwise link an unrelated technical task and expose it on the project board. Require the existing task-access check and test both an allowed and cross-project denied link.

4. **blocking: Add an idempotency protocol for concurrent `project_wait(open)` calls.**
   [plan.md:110](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:110), [plan.md:197](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:197)
   `portfolio_waits` has no request/idempotency key or active-wait uniqueness constraint, so retries or concurrent identical opens can create multiple durable waits. “Duplicate-safe CAS” is asserted but not defined by the schema or workflow. Add an idempotency key or explicit transactional claim and test concurrent opens.

5. **blocking: Make watchdog receipt claiming atomic with delivery recovery.**
   [plan.md:135](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:135), [plan.md:227](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:227)
   Two evaluations can both observe no receipt and call `deliver()` before either inserts the unique receipt, producing duplicate wakes; inserting first instead can lose the wake on process failure. The plan needs a durable claim/outbox or equivalent recovery protocol. The T4 test calls `evaluate_once` sequentially and never checks concurrent evaluation or retry reuse of `delivery_id`.

6. **suggestion: Define the staged `notify_user` compatibility and no-tag contract in the oracle.**
   [plan.md:457](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:457), [test_project_portfolio_418.py:302](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/acceptance/test_project_portfolio_418.py:302)
   Existing usage is reason-only, but the plan does not state a default or migration path for `kind` while prompt changes are deferred. The test only calls the new signature, monkeypatches `_api`, and never exercises durable-before-TG ordering, `project_wait`, watchdog delivery, projectless incidents, or the legacy one-argument call.

7. **suggestion: Decouple ticket RED checks from the shared route-presence gate.**
   [test_project_portfolio_418.py:62](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/acceptance/test_project_portfolio_418.py:62), [test_project_portfolio_418.py:132](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-python-orchestra/research-projects-board/docs/tasks/418/acceptance/test_project_portfolio_418.py:132)
   T2, T3, and T5 all fail before their own behavior assertions because `_portfolio_app()` only checks whether the required production route exists. The per-ticket reruns confirmed route-gate failures, not link, goal, wait, or board behavior. Keep route smoke checks separate and make each ticket’s RED oracle reach its own first behavioral assertion.

8. **question: Is a goal with zero linked tasks watchdog-eligible?**
   [research.md:421](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/research.md:421), [plan.md:217](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:217), [test_project_portfolio_418.py:247](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/acceptance/test_project_portfolio_418.py:247)
   Research’s preregistered predicate required an actionable task, but the plan removes that condition and T4 creates no linked task while expecting a wake. This is a material semantic change: either document goal-only watchdog behavior and test it explicitly, or restore the actionable-task predicate.

9. **suggestion: Populate T5 with linked, unlinked, waiting, goal-only, and member data.**
   [test_project_portfolio_418.py:286](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/acceptance/test_project_portfolio_418.py:286)
   The test checks only four headings, absence of `agent-list`, and an unchanged dashboard template. A page containing static headings would pass while showing unlinked tasks, omitting exact wait questions, or hiding owners and contributors.

## Verdict

**CHANGES REQUESTED.** The architecture split is understandable, but the plan is not yet safe to implement: canonical cleanup, membership isolation, task-link authorization, and exactly-once watchdog/wait behavior need executable contracts and stronger frozen tests.

Пока это не портфолио проектов, а шлагбаум с шестью лампочками: светятся дружно, но никуда не пускают.

## Author resolution before Round 2

- ACK F1: cleanup manifest now freezes stable id, canonical head/content SHA and legacy tuple; fresh reads are compared to frozen values before the identity is constructed.
- ACK F2: owner/contributor eligibility is role-, status- and parent-ancestry checked; worker/sub-owner/respawn/reparent denial is frozen in the new oracle.
- ACK F3: portfolio link now requires both membership and existing caller-scope technical task authorization; foreign namespace link is frozen negative behavior.
- ACK F4: wait uses a server-derived generation claim key with transactional insert-or-return; concurrent identical opens must return one row/id.
- ACK F5: watchdog uses durable outbox claim-before-delivery, concurrent evaluator exclusion and same-delivery-id recovery after failure.
- ACK S6/S9/Q8: legacy one-argument notify remains `kind=legacy`, TG tags durable result only, wait/watchdog markers never tag; board oracle is populated; goal-only watchdog eligibility explicitly supersedes Phase-1 task predicate.
- ACK S7: dependency-only six-test oracle `d4c634de` is excluded. Strengthened RED `be398ad6` has four vertical tickets; each current failure is its own foundation/watchdog/board/attention behavior.
- Attempt 2 started: resumed Luna review of changed plan and immutable RED `be398ad6`.

## Round (2026-08-30T08:10:25Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Раунд 2 выглядит существенно здоровее: прошлые блокирующие проблемы закрыты, а четыре RED-теста теперь падают по собственным foundation/watchdog/board/attention причинам 😏

## Summary

Prior findings:

- **FIXED** — cleanup now compares frozen canonical and legacy values before apply: [plan.md:414](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:414).
- **FIXED** — role eligibility, respawn, reparent, and foreign-task authorization are explicit and tested: [plan.md:71](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:71), [test file:139](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/acceptance/test_project_portfolio_418.py:139).
- **FIXED** — wait `claim_key` and concurrent idempotency are specified and tested: [plan.md:147](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:147), [test file:230](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/acceptance/test_project_portfolio_418.py:230).
- **FIXED** — watchdog outbox claim/retry protocol and concurrent delivery test exist: [plan.md:175](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:175), [test file:274](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/acceptance/test_project_portfolio_418.py:274).
- **FIXED** — dependency-only RED gates were removed.
- **FIXED** — goal-only watchdog semantics are explicit and tested.
- **FIXED** — board test now uses seeded linked/unlinked tasks, goal, wait, owner, and contributor.
- **STILL BROKEN** — attention test still does not prove durable persistence before the real TG bridge decision.

Exact full command result:

```text
FFFF                                                                     [100%]
4 failed in 2.74s
RC=1
```

Per-ticket failures are correctly isolated: T1 missing portfolio route, T2 missing `app.portfolio_watchdog`, T3 missing board route, T4 missing attention integration. Commit ancestry was not inspected because Git history was explicitly out of scope.

## Findings (blocking/suggestion/question)

1. **suggestion: Synchronize the KB with the selected Phase-2 architecture.**
   [project-portfolio.md:6](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/kb/project-portfolio.md:6), [project-portfolio.md:14](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/kb/project-portfolio.md:14) still describe `tm_projects` as the human/task project and `project_wait` as the only proposed agent tool, while the plan selects `portfolio_projects` and adds `project_goal`: [plan.md:240](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:240). Future agents can therefore receive contradictory memory.

2. **suggestion: Make the aggregate inventory query executable as written.**
   [plan.md:394](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:394) references `candidates` from a previous statement, but SQLite CTEs are statement-scoped; the shown aggregate query fails with `no such table: candidates` unless the full CTE is repeated inline.

3. **suggestion: Cover the remaining watchdog rollout guarantees in the acceptance test.**
   [plan.md:270](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:270), [test file:250](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/acceptance/test_project_portfolio_418.py:250) test same-process concurrency and retry IDs, but not the 300-second lifespan loop, fresh-migration `candidates=0`, shadow mode, or recovery after reopening the process/database. Those ACs remain plan-only.

4. **suggestion: Add a truly goal-only board fixture.**
   [test file:340](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/acceptance/test_project_portfolio_418.py:340) renders a project that already has a linked task, so it does not prove [plan.md:317](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:317)’s requirement that a project with a goal and zero linked tasks remains visible.

5. **suggestion: Exercise the real durable-attention-to-TG ordering.**
   [test file:390](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/acceptance/test_project_portfolio_418.py:390) mocks `_api` and only parses result markers; it never verifies that an attention row is committed before the bridge can tag, nor invokes the bridge with a real persisted event. The no-tag contract in [plan.md:199](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/plan.md:199) is still untested end-to-end.

## Verdict

**APPROVED.** No blocking findings remain. The remaining items are nonblocking documentation and acceptance-strengthening suggestions.

Exact new sentence from `plan.md`: “Goal with zero linked tasks **is watchdog-eligible** when active/enabled.”

Теперь хотя бы четыре `F` — честный RED, а не хор одинаковых шлагбаумов.

## Author follow-through after APPROVED Round 2

- KB Phase-1 statements about `tm_projects` and one-tool scope are explicitly withdrawn and replaced with the selected Phase-2 architecture.
- Aggregate inventory SQL now repeats its statement-scoped CTE and is executable alone.
- Watchdog lifespan/fresh/shadow/reopen, a second goal-only board project, and real DB→TG attention ordering are mandatory focused regressions in T2/T3/T4 AC. Frozen acceptance file `be398ad6` is unchanged after review.

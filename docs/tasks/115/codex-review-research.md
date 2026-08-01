## Summary

The numbers are impressively exact; unfortunately, exactness still isn’t proof. 🙃 Two design gaps can cause ambiguous mutation or worker-work loss, and several quantitative claims need narrower wording.

## Findings

1. **blocking: Reconcile must compare-and-swap the worker head before reset**

   [research.md:386](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/research.md:386) proposes validating a target commit and then resetting the worker, but does not require the worker’s current branch/HEAD to equal the pinned `worker_head`. During historical recovery, the worker may already contain newer commits; a clean worktree and repo lock do not detect that stale input, and resetting it can discard work. Require exact branch+HEAD CAS, verification that the complete current worker content is represented in target, and a durable backup ref before reset. #93’s lock prevents concurrent mutation during recovery but does not make an old snapshot current.

2. **blocking: Fail-fast busy and durable idempotency are not alternatives**

   [research.md:354](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/research.md:354) says the route should either return busy quickly or create a durable operation. Fast busy only removes the observed queue delay; an accepted Git operation can still exceed the deadline or lose its response after commit, allowing raw recovery to race with continuing server work. To satisfy the stated “safe retry” outcome, accepted mutations need a stable operation identity/result in addition to a bounded precondition wait, unless the research proves the entire Git→DB→lifecycle sequence cannot outlive or lose its HTTP response.

3. **suggestion: Use one counting unit for the 139-versus-32 comparison**

   [research.md:98](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/research.md:98) compares successful tool results with manual target commits, then excludes a tool-created commit because its caller received failure. For physical target mutations, the reported data give at least 140 tool commits versus 32 manual commits—81.4%/18.6%, not 81.3%/18.7%. For logical integrations, the post-commit failure and any subsequent manual recovery must instead be deduplicated as one intent. The current MCP output also discards `target_after`, so the document should provide the deduplicated tool-SHA manifest/query before calling the counts apples-to-apples.

4. **suggestion: Downgrade the six-timeout conclusion from CONFIRMED**

   [research.md:184](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/research.md:184) proves that six failures occurred near the configured 30-second boundary, but [mcp_stdio.py:76](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/app/mcp_stdio.py:76) neither records nor catches the exception type. Empty text and timing are consistent with `ReadTimeout`, but do not distinguish it from another `httpx.TimeoutException`. The journal evidence demonstrates continuing server work for four requests in one incident, not all six. Classify six as probable client timeouts, four as proven queued continuations, and leave two server outcomes unknown; consequently, “40 lifecycle failures CONFIRMED” is also too strong.

5. **suggestion: Include serialization as counter-evidence to duplicate mutations**

   [research.md:194](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/research.md:194) shows that expired requests reached precheck, but not that a clean case would repeat the content commit. Requests serialize under the session/repo locks, and the first success resets the worker toward target; subsequent requests should normally become zero-content merges, though they may repeat lifecycle persistence or RAG scheduling. Keep the proven conclusion—unknown caller outcome and unsafe raw retry—but distinguish it from an unproven duplicate Git mutation.

6. **suggestion: Separate absent task links from attributable provenance damage**

   [research.md:303](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/research.md:303) treats all 32 absent hashes as manual-path damage, but the official path only links commits whose subject contains a recognized task reference and whose task resolves in the caller’s project. Report how many of the 32 satisfy both conditions; commits without a parseable/resolvable ref would remain unlinked even through `merge_worker`. Three positive controls validate the machinery, not the full 32-item causal denominator.

7. **suggestion: Record that worker reset is fail-soft**

   [research.md:285](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/research.md:285) lists worker hard-reset as a completed side effect, while [workspace.py:643](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/app/workspace.py:643) logs reset failure and still permits an `ok=true` result. Likewise, a restore failure guarantees the target commit landed, but the worker ref moved only in the E4 experiment—not by contract. This missing counter-path weakens the claim that observed ref divergence uniquely identifies raw bypass and belongs in the top safety analysis.

8. **suggestion: Make #93 ownership explicit dependencies, not parts of measure 2**

   [research.md:369](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/research.md:369) assigns unrelated-history rollback hardening to #115, while [plan.md:124](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/93/plan.md:124) already assigns merge rollback, snapshot restoration, verification, and `rollback_failed` DTOs to #93 T1. Keep #115’s new scope to transport idempotency, conflict instructions, and safe reconciliation; treat #93 T1/T2 as prerequisites. Otherwise the advertised top three are not minimal and invite two competing rollback contracts.

## Verdict

The core direction is credible, but the recovery proposal can discard newer worker work and the timeout contract remains ambiguous. The quantitative evidence also needs corrected units and confidence labels before Phase 1 can safely drive implementation.

REQUEST_CHANGES

## Round (2026-08-01T08:14:07Z)

## Summary

Почти всё закрыто, но один idempotency-замок пока лежит внутри запертого сейфа. 🙃 CAS-reset, timeout confidence, retry counter-evidence, fail-soft reset и граница #93 исправлены корректно. Остался один blocking safety gap и две количественные неточности.

## Findings

1. **blocking: Make the operation ID known before mutation starts**

   [research.md:369](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/research.md:369) требует durable `operation_id`, но не определяет, как caller получает его, если первый HTTP response потерян. Если ID создаёт route внутри такого запроса, retry всё ещё не сможет адресовать старую операцию. Требуется client-generated idempotency key в первоначальном запросе либо durable `202 + operation_id` до запуска Git; pending record должен существовать раньше первой мутации.

2. **suggestion: Do not upper-bound manual share from an open-set count**

   [research.md:90](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/research.md:90) утверждает `≤18.6% manual`, но ниже признаёт 32 manual commits строгой нижней границей. Необнаруженные manual commits могут увеличить долю, поэтому корректно: `18.6% среди 172 строго подтверждённых физических commits`; доля во всей retained population неизвестна.

3. **suggestion: Verify task existence at integration time**

   [research.md:108](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/research.md:108) называет 24 отсутствующие связи доказанным causal damage, хотя D10 подтверждает только то, что задачи разрешаются сейчас. Если задача появилась после manual commit, штатный tool тогда тоже не смог бы её связать. Сравните `task.created_at` с commit/log timestamp либо назовите эти 24 записи recoverable missed-link candidates.

## Verdict

Семь прежних проблем исправлены по существу, но потерянный первый response всё ещё может оставить caller без ключа к продолжающейся мутации — бирка на чемодане полезна снаружи, а не внутри. 🧳

REQUEST_CHANGES

## Round (2026-08-01T08:17:34Z)

## Summary

Да, теперь аварийная дверь настоящая, а не декорация. 🚪 Все три Round 2 findings resolved: idempotency key exists before mutation, the 18.6% denominator is correctly scoped, and the 24 missed links have temporal evidence.

## Findings

No blocking findings.

## Verdict

The Phase 1 conclusions are safe enough to proceed to planning. После трёх раундов цифры наконец перестали притворяться архитектурой. 🙂

APPROVE

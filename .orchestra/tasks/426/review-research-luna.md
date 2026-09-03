<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Исследование корректно подтверждает текущую O(E)-часть latency и необходимость durable outbox. Но рекомендуемая архитектура пока не доказывает атомарность между canonical, legacy и outbox, а также не защищает Git-outbox от конкурентных commit/delete операций.

Проверка scratch-эксперимента прошла:

```text
HEAD_PREFIX_EQUAL [True, True, True]
ORDERED_FINAL ('B', [], 0)
OUT_OF_ORDER_REFUSED (...)
CRASH_REPLAY_FINAL ('B', [], 0)
```

## Findings

### blocking

blocking: `docs/tasks/426/research.md:126-134` — `_RuntimeTaskStore._lock` сериализует task-store вызовы, но не защищает Git index/commit от конкурентного drainer’а; enqueue и удаление outbox могут одновременно выполнять `git add`/`commit`, что допускает потерю или неправильное подтверждение receipt → ввести единый process-wide Git lock и recovery-инвариант для каждой операции commit/delete.

blocking: `docs/tasks/426/research.md:112-120`, `app/tm.py:2719-2725` — proposed boundary требует legacy mirror до durable outbox, но текущий canonical update вызывает `_record_task_head()` до legacy-записи; create имеет ту же последовательность → явно спроектировать commit protocol после обеих записей либо durable reconciliation для окна между canonical и legacy.

blocking: `docs/tasks/426/research.md:37-49,126-146` — scratch `drain()` проверяет только строки `head` и список в памяти; он не моделирует crash между записью task files/outbox, ошибку Git commit, частичную запись receipt или persistence observed head → не считать H2 доказанной, пока Phase-2 oracle не проверит эти failure windows и malformed/stale receipts.

### suggestion

suggestion: `docs/tasks/426/research.md:80-89` — “corpus-dependent” сильнее, чем позволяет один большой corpus и один laptop counterexample; при отсутствии post-#395 A/B это наблюдаемая корреляция, а не подтверждённая причинность → ослабить формулировку до “consistent with corpus dependence”.

suggestion: `docs/tasks/426/research.md:160-170` — cache invalidation подтверждена только для `_import_scope_evidence()`; не показано, что после startup нет других путей изменения evidence или чтения prefix во время импорта → зафиксировать invariant “evidence immutable after prefix construction” и отдельный concurrent-import test.

question: `docs/tasks/426/research.md:71-76,174-194` — H5 отвергнут из-за потенциального отставания under sustained writes, но тот же backlog-риск существует у ordered drainer; почему coalesced latest-head rebuild не может быть проще при условии durable generation watermark и snapshot protocol?

## Verdict

**Needs work.** Исследование годится как направление для Phase 2, но архитектуру A нельзя утверждать без протокола межхранилищной атомарности, сериализации Git-outbox и failure/restart oracle.

## Round (2026-09-01T17:10:50Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Re-review status

Scoped `git diff` is empty; the revised research and scratch files are currently untracked. Review is based on their current contents and the permitted source files.

- Prior blocker 1 — **FIXED**. `research.md:152-155,240-241` explicitly requires one process-wide Git lock and scoped pathspecs.
- Prior blocker 2 — **STILL BROKEN**. `research.md:127-134,242-244` names the canonical-before-legacy window, but update recovery remains an unspecified “durable reconciliation state”; `app/tm.py:2719-2725` has no update request identity or recovery receipt.
- Prior blocker 3 — **FIXED**. `research.md:166-168,262-265` explicitly labels scratch synthetic and enumerates Git, malformed receipt, SQLite-before-delete, and concurrency failures.
- Prior suggestion 4 — **FIXED**. `research.md:80-92` downgrades corpus dependence to likely and separates it from confirmed O(E) behavior.
- Prior suggestion 5 — **FIXED**. `research.md:193-196` specifies post-import immutability and future invalidation requirements.
- Prior suggestion 6 — **FIXED**. `research.md:226-230` compares backlog risk and per-batch O(changed rows) versus O(full corpus).

## New blocking findings

blocking: `docs/tasks/426/research.md:117-135,166-168` — the crash window after `TaskStore._commit_generation()` has removed its pending marker but before the outbox Git commit is not assigned a recovery owner; a restart can see canonical task state with no durable joined-projection receipt → define reconciliation from canonical generations, or make the outbox marker durable before clearing the generation marker.

blocking: `docs/tasks/426/research.md:142-150` — serialized task mutations do not by themselves create a linked projection chain; when projection lags, each enqueue could derive `expected_projection_head` from the same stale observed head → require the enqueue protocol to chain from the durable queue tail, with a persisted tail invariant checked on restart.

blocking: `docs/tasks/426/research.md:121-135`, `app/tm.py:2708-2718` — the recovery protocol is specified only for canonical-before-legacy ordering, while shadow update currently performs legacy first and canonical second → define success, crash recovery, and outbox ordering for shadow mode too, or explicitly exclude it from this architecture’s AC.

## Verdict

**Needs work.** The first and third prior blockers are addressed, but the update-recovery protocol, post-generation/pre-outbox crash gap, queue-tail chaining, and shadow-mode ordering remain load-bearing gaps.

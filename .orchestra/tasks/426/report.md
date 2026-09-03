# #426 — durable deferred joined-task projection

## Implemented

`KnowledgeRuntime._record_task_head` no longer enumerates evidence or opens `current.db` on the
canonical POST/PUT response path. Startup builds the exact SHA-256 evidence prefix once; each task
write copies that digest state, appends dynamic knowledge/task heads, writes a linked receipt under
canonical Git, commits `tasks/` plus that receipt through a process-wide Git lock, and only then
returns.

`schedule_projection_repair` now owns one long-lived wakeable drainer. It restores runtime outbox
paths from Git HEAD before bootstrap staging, validates a fork-free expected→target chain, applies
the existing atomic row/FTS/head CAS in chain order, commits an applied marker before removing a
pending receipt, and safely replays a SQLite-committed target without applying its payload twice.
Malformed, forked, cyclic, duplicate-target and head-blocked queues remain durable and visible as
debt.

Files changed for behavior:

- `app/ia/runtime.py` — exact head prefix, scoped Git commits, outbox, recovery, drainer;
- `tests/test_task_write_outbox_426.py` — approved frozen POST/PUT, volume, crash and concurrency
  oracles;
- `tests/test_tm_projection_hotpath_395.py` — superseded temporal contract moved after drain plus
  an explicit pre-drain-old case.

No `app/ia/projections.py` change was needed. The cheaper helper correction was selected: `_outbox`
catches `FileNotFoundError` when a receipt disappears between `glob` and `read_text`. This preserves
black-box observation of the durable directory and avoids coupling the test to
`_ack_projection_outbox_entry`; 10 consecutive combined runs found no remaining semantic gap.

## Contract changes and oracle corrections

#395 required the named task row and FTS entry to be updated when `facade.task_create()` returned.
The user-approved “426 чини корень” contract cancels that timing guarantee: before drain the row is
intentionally still old, because the response must perform zero joined-projection constructions.
The preserved #395 guarantees are the substantive ones: after one deterministic drain transition,
the named row and its FTS entry are updated, while the resource row and neighboring task fields
remain byte-for-byte unchanged. The new separate test asserts the old row between facade return and
drain.

Oracle `33350772` incorrectly required the applied marker to be in Git HEAD at the instant
`SQLiteProjectionBackend.update_current_records` returned. Correctness requires the marker to be
committed before pending-receipt removal, not before the runtime's following ack step. A crash in
that interval leaves the pending receipt in HEAD; restart observes SQLite at its target, skips the
payload, commits the marker and continues. Production did not need a projection-layer callback.
The corrected deterministic oracle checks the result of one blocked drain/ack transition and the
exact restart transitions instead of this intermediate moment.

Oracle `09e7b152` then exposed a test-observation race: its polling helper could glob a receipt that
the correct drainer deleted before `read_text`. It is excluded forever because “polling helper
sampled a receipt concurrently with its legitimate deletion”. Final oracle `b69568ef` treats that
specific `FileNotFoundError` as an already-drained entry. This is not weakening the delivery
assertion: final apply order, Git marker, pending receipts, row, FTS and head remain asserted.

## Mutation evidence

Ack ordering, against committed final oracle `b69568ef`:

```text
ACK_ORDER_MUTANT_MARKER_BEFORE_TEST=1
E AssertionError: SQLite committed without an applied marker
1 failed in 8.92s
RC=1

ACK_ORDER_MUTANT_MARKER_AFTER_RESTORE=0
1 passed in 8.24s
RC=0
```

The counted marker is the **mutant marker** `MUTANT_426_RECEIPT_BEFORE_MARKER`: `1` means pending
was moved before marker commit; `0` proves `mv .bak` + `touch` restored production.

Deferred application, against committed #395 temporal rewrite `fdfaca5b`:

```text
MUTANT_DRAIN_APPLY_MARKER_BEFORE_TEST=1
E {'task-1': 'old'} != {'task-1': 'new'}
1 failed in 6.21s
RC=1

MUTANT_DRAIN_APPLY_MARKER_AFTER_RESTORE=0
1 passed in 6.06s
RC=0
```

The counted marker is the **mutant marker** `MUTANT_426_SKIP_DRAIN_APPLY`; the mutation acknowledged
without calling `update_current_records`, and the rewritten #395 test caught the unchanged row.

## Tests before live deployment

- Minimal helper stability: 10 consecutive combined runs, each `32 passed`, RC=0;
  `refreeze-combined-10.txt`.
- Post-mutation repeat before main integration: 3/3 combined runs, each `32 passed`, RC=0;
  `final-combined-3.txt`.
- After merging current `main@4eac349d`: 3/3 combined merge-gate runs, each `32 passed`, RC=0;
  `post-main-combined-3.txt`.
- After implementation-review fixes: 3/3 combined runs, each `32 passed`, RC=0
  (`25.11 / 23.41 / 21.72 s`); `post-review-combined-3.txt`.
- Runtime/task regressions before review: `68 passed in 68.80s`, RC=0; `regression-suite.txt`.
  After review fixes: `68 passed in 39.20s`, RC=0; `post-review-regression-suite.txt`. Both cover #395
  idempotency, full-repair/runtime debt, task manager and tracker integration.
- Full required command `uv run python -m pytest -x -q` reached `978 passed, 40 skipped,
  3 deselected` and stopped on
  `tests/test_fan_barrier_gates.py::test_parent_woken_exactly_once_when_last_child_reports`, RC=1.
  The same node fails alone on both this branch and untouched `main@4eac349d` with the identical
  `пробуждений 0, ожидалось ровно одно`; it is pre-existing and outside #426.
- Frozen oracle check: `git diff b69568ef -- tests/test_task_write_outbox_426.py` is empty.

Review-fix probe, isolated temporary runtime, RC=0:

```text
STAGED_EXTRA_REFUSED True canonical Git index is not clean before scoped commit: evidence/staged-unrelated.json
STAGED_EXTRA_COMMITTED False
PRECOMMIT_TASK_DISCARDED True
PRECOMMIT_RECEIPT_DISCARDED True
RUNTIME_HEAD_RESTORED True
RUNTIME_INDEX_CLEAN True
```

## Pre-mortem coverage

- Response escapes before durable receipt → blocked Git-commit barrier plus `git show HEAD:<path>`.
- Request cost still grows with evidence/current.db → 0/20,000 arms count zero evidence calls,
  evidence-object serializations and `SQLiteProjectionBackend` constructions.
- Crash after SQLite but before ack loses or duplicates work → pending+committed-marker test, fresh
  runtime skips A and applies only B.
- Concurrent enqueue attaches to stale head or deadlocks → SQLite barrier requires enqueue to
  finish first, then asserts A→B→new-target order.
- Malformed queue silently repairs/deletes → four invalid shapes preserve complete row/FTS/meta
  snapshots and remain visible debt.
- Consumer reads new data before drain → explicit pre-drain-old #395 case.

## Known boundary

#426 does not retry cross-process canonical CAS and does not claim to fix
`ConcurrentTaskUpdateError` during merge finalization. It orders only joined-projection work after a
canonical task generation has been accepted. Shadow-mode/pre-response cross-owner crash semantics
remain unchanged by the approved bounded architecture.

## Review decision inputs

- Changed consumers: canonical HTTP/MCP task POST/PUT, `_RuntimeTaskStore` mutations, canonical Git,
  joined `current.db` row/FTS readers, and `app.main.lifespan` ownership of the returned task.
- Author runtime: `gpt-5.6-sol`, Codex full-cycle worker.
- Exact AC: final frozen T1/T2 oracle green; repeated merged-base `32 passed`; #395/full-repair/task
  regressions green; receipt/order mutations red then restored green; after merge/restart, curl POST
  and PUT each return 2xx under 30 seconds and canonical, legacy, joined row/FTS/head all agree.
- Named checks and observed outputs: the commands and counts in “Tests before live deployment” and
  “Mutation evidence”.
- Risk floor: shared persistence, Git/SQLite ordering, concurrency and application lifecycle. Sol
  review would require separate authorization; the permitted route is a targeted Luna
  implementation review.

## Implementation review

Luna round 1 returned `Needs work` with three blockers. The malformed-JSON finding was rejected
after direct source verification: `_read_json` already converts parse/non-object failures into
`KnowledgeRuntimeError`, and the drainer catches that type. Two findings were accepted:

- path-scoped commits now reject any pre-existing staged index path and verify the complete staged
  set before commit, so an unrelated staged evidence/task cannot leak into a receipt commit;
- startup now resets/restores/discards `tasks/`, pending receipts and applied markers from the same
  Git HEAD boundary before loading TaskStore or running bootstrap `git add -A`; after discarding a
  pre-commit mutation, runtime canonical head returns to the committed queue tail or projection
  head.

Round 2 verdict: `APPROVED`, all three prior blockers resolved, no new load-bearing bugs. Reviewer
evidence quotes the current fail-closed error
`"canonical Git index is not clean before scoped commit: "` and cites the post-fix `32 passed`,
RC=0. Artifact: `review-implementation-luna.md`.

## Pending live acceptance

The supplied before values are POST `20.84 s` and PUT `19.60 / 18.12 s` at 47,834 evidence records
and 2.32 GB `current.db`. After this branch is merged with `task_outcome="continue"` and the service
is restarted, record the exact curl `time_total` values and positive canonical/legacy/joined
storage checks here. Do not replace the numbers with a qualitative “faster”.

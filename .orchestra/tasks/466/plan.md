# #466 — plan: one task-run anchor, existing facts by reference

## Decision requested at the Phase-2 gate

Implement research variant **A**: keep `review_receipts` as the only physical table and add one sibling row with `subject_kind='task_run'` per accepted task/session assignment. Review rounds remain separate rows. A reassigned/reopened task may have several non-overlapping run rows; task-level reporting aggregates them by stable task identity.

Phase-3 approval of this plan selects variant A. Selecting “enrich one review row” or “one mutable row per task” requires a new plan and a new frozen oracle; the current tests must not be weakened to fit those grains.

## External dependency and ordering

- #462 T1–T3 are merged in `main@1a86f403` and verified live.
- #462 T4 still owns the canonical/native `codex-debate` policy surface. #466 Phase 3 starts only after T4 is merged and the `review-coverage-gate` worker releases the receipt/prompt files.
- Internal order is strict: T1 closes the 0/N author outcome bypass. T2 starts only after T1 is green.
- No production/schema file is changed in Phases 1–2. Both acceptance oracles live under `.orchestra/tasks/466/` and are already committed RED.

## Target design

### T1 — author response is a prerequisite only for a real review

Keep `record_review_outcome` as the sole author writer chosen in #436. Do not parse review prose and do not infer an outcome.

Change `app.review_coverage.coverage_decision` as follows:

1. Keep the current exact scope/session/task/target/snapshot/boundary query and newest-first order.
2. Find the newest row that is otherwise a structurally qualifying `reviewed`, `skipped` or `unavailable` coverage decision.
3. If that row is `reviewed` and `author_outcome='unknown'`, return:

```text
status=blocked
reason=author_outcome_missing
receipt_id=<that newest review receipt>
coverage_outcome=reviewed
author_outcome=unknown
```

Do not continue to an older answered review. After `accepted|disputed|partial` is recorded on the same row, return `satisfied` and expose only `author_outcome` plus `outcome_evidence_ref` as references.

`skipped` and typed `unavailable` keep `author_outcome=unknown` and qualify exactly as #462 defines them. Do not rewrite either as `accepted`.

In `app.merge_operations`, map `author_outcome_missing` to typed error `REVIEW_AUTHOR_OUTCOME_MISSING` and next action `RECORD_AUTHOR_OUTCOME_THEN_NEW_OPERATION`; include the exact receipt id in error details and admission evidence. Apply the same mapping at initial admission and execution-time revalidation. Existing `REVIEW_COVERAGE_MISSING` remains for absent/stale/invalid coverage.

Execution revalidation is unconditional for every active-policy production decision, including an already-pinned `status=satisfied`. This closes operations admitted before T1 with a reviewed receipt whose author outcome was still unknown. The current target/worker snapshot remains pinned; only the current receipt decision for that exact snapshot is refreshed immediately before the test/executor path.

This is the non-bypass mechanism: with active #462 policy, both paths stop before the executor/Git. Prompt instructions can explain the tool but are not the enforcement owner.

### T2 — task-run row and derived trace

#### Additive schema in the existing table

Add these columns to `review_receipts` through the same idempotent `PRAGMA table_info`/`ALTER TABLE` owner introduced by #462:

```text
task_stable_id TEXT NOT NULL DEFAULT ''
task_snapshot_ref TEXT NOT NULL DEFAULT ''
prompt_template_start TEXT NOT NULL DEFAULT ''
prompt_template_end TEXT NOT NULL DEFAULT ''
terminal_operation_id TEXT NOT NULL DEFAULT ''
```

Append them to `_REVIEW_RECEIPT_COLUMNS` and to `scripts/migrate_review_receipts.py` defaults. Existing rows retain empty values and prove nothing retroactively.

For a task-run row, reuse existing columns exactly:

```text
schema_version=2
subject_kind=task_run
mode=task_run
runtime=''
reviewer_model=''
model_source=unknown
scope/session_id/worker_name/task_id=<accepted binding>
task_source=canonical | legacy | legacy_inflight
requested_at=<successful binding transaction time>
completed_at=NULL while open
status=requested while open; completed on task completion; interrupted on binding release
failure_code='' | session_archived | task_cancelled | binding_released
review/artifact/job/usage/coverage fields=<their existing neutral defaults>
```

No new table and no columns for model, tokens, dollars, turn/tool/retry/review/commit counts, changed paths or rollback SHA.

Create two partial uniqueness guards for forward task runs:

```text
one open task_run per (scope, task_stable_id) where task_stable_id<>''
one open task_run per session_id
```

`task_run_receipt_open` accepts an optional existing SQLite connection so task binding and run creation commit or roll back together. A new accepted assignment gets a random `task-run:<uuid4>` receipt id. Retry idempotency comes from the partial unique open-run indexes: a matching open row is returned, a mismatched open row fails loud, and a later reassignment after the previous row is terminal gets a new id even when session and task snapshot repeat.

`task_run_receipt_finish(*, session_id, task_id, status, prompt_template_end, terminal_operation_id='', failure_code='', connection=None)` compare-and-swaps the single open row. Identical terminal replay returns that row; a conflicting second terminal outcome fails loud.

`task_snapshot_ref` is a canonical URI plus the accepted canonical head. `prompt_template_start`/`end` are the session's historical `template_hash` boundaries; prompt text is never copied. `terminal_operation_id` references the merge operation that completed the task; target-before/after remain only in `merge_operations`.

#### Lifecycle writers

Open the run in the same successful state transition for every forward assignment:

- `app.db.publish_ready_session` — new worker published with an assigned task;
- `app.tm._bind_task_to_session_unlocked` — taskless worker accepts a task;
- strict and legacy next-task/switch paths in `app.tm.finalize_merge_outcome` / `app.routes.sessions` — previous run closes, next accepted run opens.

Close the open run:

- `app.tm.finalize_merge_outcome(outcome='complete')` → `status=completed`, terminal prompt hash and `terminal_operation_id`; `outcome='continue'` leaves the row open;
- `app.tm.release_session_task_binding` / archive → `status=interrupted`, terminal prompt hash and `failure_code=session_archived|binding_released`;
- both live cancellation owners, `app.tm.api_update_task(status='cancelled')` and `app.tm.api_update_task_if_current(status='cancelled')`, close the bound open run in the same legacy SQLite transaction with `failure_code=task_cancelled`.

Every forward assignment/run-open transition has an explicit atomicity rule:

- `publish_ready_session`: session insert, task binding and run insert share its existing SQLite transaction;
- taskless binding: task/session binding and run insert share `_bind_task_to_session_unlocked`'s transaction. The preceding branch switch is not task acceptance; a receipt failure leaves the session taskless on the switched branch and the route's existing error path stays retryable;
- explicit switch: receipt failure must raise through the existing task-assignment rollback path, restoring branch/session/task state;
- strict next-task finalization: the run insert is part of the legacy task update stage. Canonical/SQLite/Git cannot share one transaction, so failure leaves the merge operation `PARTIAL` with its frozen finalization payload; same-operation replay is the only repair path and may not claim success without the run row.

All forward assignment writers abort or quarantine the assignment if the run insert fails. Post-commit task finalization surfaces a missing/conflicting forward run as partial instead of silently claiming a complete trace.

The `init_db` adoption reconciliation runs idempotently at startup: currently bound `in_progress` tasks with no open run receive one adoption row with `task_source=legacy_inflight`, `requested_at=<adoption time>`, empty `task_snapshot_ref` and empty prompt-start hash. This row means “observation began here”, not “the task was accepted here”; the trace returns an `acceptance_before_receipt` gap. A second `init_db()` creates no duplicate, and tasks already `done|cancelled` are excluded. No completed historical task is backfilled, and no acceptance timestamp/snapshot is invented. After reconciliation, every bound task has exactly one open run and task-bound review reservation can require exactly one match.

Task-bound review reservation after rollout must observe exactly one open `(scope, session_id, task_id)` task-run row. Review membership is derived from the immutable review `requested_at` inside that non-overlapping run interval; an asynchronous completion after the run boundary still belongs to the run in which it was requested. A post-rollout review with zero/multiple matches fails loud. Legacy review rows remain `run_reference=unknown`.

#### Read-time trace; no materialized aggregates

Add `app/run_receipts.py::build_task_run_trace(receipt_id: str, *, as_of: str | None = None) -> dict`. It reads only a `subject_kind='task_run'` row. For a completed/interrupted run the upper bound is `completed_at`; for an open run it captures one UTC `as_of` value (caller-supplied for reproducibility, otherwise current time), returns `live=true`, `completed_at=null`, `effective_end=as_of`, and derives a live snapshot through that boundary.

The function derives:

- `run`: identity, task snapshot, prompt start/end, status and time bounds;
- `usage`: turns, failed turns, exact runtime/model groups, tokens and cost from `turn_usage` within `(session_id, scope, task_id, requested_at..completed_at)`;
- `tools`: grouped tool names plus raw log boundary references from `logs`, ordered/filtered by ISO `ts`, never insertion `id`;
- `messages`: provenance groups (`direct_user`, `agent`, `background_task`, `platform/system/unknown`) from `logs`;
- `reviews`: sibling receipt ids with structural verdict/coverage/author outcome references, joined by immutable `requested_at`;
- `terminal_operation`: the referenced operation id and its `target_before`/`target_after` read from `merge_operations`;
- `gaps`: missing owners and unknown legacy references. Missing data is never normalized to numeric zero.

The API reports `failed_turns`, not an invented scalar “retry count”. It reports only direct operator messages as `direct_user`; relayed human decisions remain indistinguishable from agent messages until provenance is fixed upstream.

Do not add a new MCP/HTTP endpoint in #466. The internal read model makes the comparison a single owned call; exposing it externally is a separate product decision.

## Files in Phase 3

- `app/review_coverage.py` — newest real-review author-outcome prerequisite.
- `app/merge_operations.py` — typed/actionable refusal at both enforcement points.
- `app/db.py` — five additive fields, partial indexes, idempotent run open/finish storage.
- `app/tm.py` — binding, completion, continuation, next-task and release owners.
- `app/manager.py`, `app/routes/sessions.py` — only assignment transitions not already atomic in DB/TM.
- `app/mcp_stdio.py` — review reservation requires exactly one open forward/adopted task run; no new tool.
- `app/run_receipts.py` — derived read model; no storage of aggregates.
- `scripts/migrate_review_receipts.py` — explicit empty legacy defaults.
- Existing #462 tests plus frozen task-local #466 oracles.

## What not to touch

- No second receipt/run/event table and no rebuild/rename of `review_receipts`.
- No changes to PROJECT CONTEXT, reviewer routing, round ceilings or verdict interpretation.
- No prose parser, DONE parser or automatic inference of `accepted|disputed|partial`.
- No `author_outcome=accepted` for skip/unavailable.
- No copied review text, raw JSONL, log content, task text, cost/model/counter aggregates, commit list or rollback SHA.
- No completed historical task-run backfill and no in-flight adoption row that pretends its adoption time was task acceptance.
- No T4 policy/prompt edits while #462 owns that surface.

## Migration and rollout

1. Wait for #462 T4 merge and ownership release; refresh from new `main` before Phase 3.
2. Re-run both frozen commands and observe the same RED seams before changing production code.
3. Implement T1 and make only the T1 command green; run the focused #462 coverage regression.
4. Implement T2 schema/lifecycle/read model and make both T2 test files green; tests use isolated SQLite only.
5. On a copied/live-schema rehearsal, `init_db()` twice must produce the same five fields/indexes, preserve every existing receipt byte-for-field, and create at most one explicitly incomplete `legacy_inflight` adoption row per currently bound task; no historical row gains evidence.
6. After merge/restart, accept one scratch task and prove one `task_run` row appears before its first review/turn; record and answer one real review; complete the task and prove the row links to the successful terminal operation. This live probe is evidence, not a reason to alter old rows.

## Tickets

### T1 — Make the real-review author response non-bypassable

- Files: `app/review_coverage.py`, `app/merge_operations.py`.
- Test: `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q .orchestra/tasks/466/test_run_receipt_466.py -k 'test_t1_'` — final frozen RED in `fd9fc34d`.
- Excluded forever: `650f730f`, `7c549251`, `032282db`, `b0557309`. They are not valid replay bases after the oracle corrections/coverage additions and must never be cited as #466 acceptance evidence.
- RED: three nodes / three unique missing-behavior messages: newest review selection, typed admission error, and unconditional execution revalidation. Skip+unavailable negative control is already green.
- AC: named command is green; `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_review_coverage_gate_462.py -k 'test_t3_'` stays green; newest unanswered `reviewed` blocks with `REVIEW_AUTHOR_OUTCOME_MISSING` and exact receipt id at both admission and unconditional execution revalidation; answered real review and unchanged skip/unavailable controls qualify.
- blocked-by: external #462 T4 merge/ownership release.

### T2 — Persist one whole task-run anchor and derive its trace

- Files: `app/db.py`, `app/tm.py`, `app/manager.py`, `app/routes/sessions.py`, `app/mcp_stdio.py`, `app/run_receipts.py`, `scripts/migrate_review_receipts.py`.
- Test: `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q .orchestra/tasks/466/test_run_receipt_466.py .orchestra/tasks/466/test_task_run_lifecycle_466.py -k 'test_t2_'` — final frozen RED in `fd9fc34d`.
- Excluded forever: `650f730f`, `7c549251`, `032282db`, `b0557309`; same exclusion applies to T1 and T2.
- RED: eleven nodes / eleven unique missing-behavior messages: task-run columns, derived trace API, taskless-binding open, taskless receipt-failure rollback, direct cancellation, CAS cancellation, in-flight adoption/idempotence/exclusion, explicit-switch receipt-failure rollback, open retry/same-snapshot reopen, strict-handoff failure, and successful handoff wiring.
- AC: named command is green; the complete post-migration `review_receipts` schema equals the literal #462 baseline plus exactly the five named references; publish/bind/handoff/open, complete/continue/archive/cancel/close and every receipt-failure rollback match this plan; `legacy_inflight` adoption is bounded by migration time, idempotent, excludes completed tasks and yields `acceptance_before_receipt`; open-run `as_of` excludes later owner rows; identical open retries reuse a receipt while same-snapshot reopen after terminal creates a new receipt; derived trace changes when owner rows change without updating the receipt; missing owner rows are explicit gaps; existing #436/#462 receipt and task-binding/finalization focused suites stay green.
- blocked-by: T1.

## RED evidence

At `main@1a86f403` plus the committed task-local oracles:

```text
T1: 3 failed, 1 passed, 2 deselected; RC=1
first failing line: AssertionError: T1 missing behavior: the newest real review passes without author_outcome

T2 combined: 11 failed, 4 deselected; RC=1
first failing line: AssertionError: T2 missing behavior: task-run reference columns are absent: ['prompt_template_end', 'prompt_template_start', 'task_snapshot_ref', 'task_stable_id', 'terminal_operation_id']
```

Mechanical uniqueness check on the exact commands: `T1_NODES=3 UNIQUE_NODES=3 ASSERTIONS=3 UNIQUE_ASSERTIONS=3`; `T2_NODES=11 UNIQUE_NODES=11 ASSERTIONS=11 UNIQUE_ASSERTIONS=11`. All failures are missing requested behavior, not import or collection errors. Every test process used a temporary SQLite path; production `data/orchestra.db` was read-only during research.

Exact frozen failure map:

```text
T1 selection -> newest real review passes without author_outcome
T1 admission -> merge admission maps missing author outcome as generic coverage
T1 execution -> pinned pre-T1 review was not revalidated before executor
T2 schema -> task-run reference columns are absent
T2 trace -> derived task-run trace API is absent
T2 taskless binding -> binding a taskless worker opened no task_run receipt
T2 taskless failure -> receipt failure did not abort binding
T2 direct cancel -> explicit task cancellation leaves task_run open
T2 CAS cancel -> api_update_task_if_current left run open
T2 adoption -> startup did not adopt an already-bound in-flight task
T2 explicit switch -> receipt failure returned success
T2 retry/reopen -> task_run_receipt_open API is absent
T2 strict handoff failure -> receipt failure claimed success
T2 successful handoff -> next-task finalization did not open its run
```

## Plan review inputs

- Changed consumers planned: review selection, merge admission/execution revalidation, shared receipt schema, task binding/finalization/release, derived analytics reader.
- Author runtime/model: Codex / `gpt-5.6-sol` from session metadata.
- Exact AC and named commands: the two ticket blocks above; actual RED outputs are recorded above.
- Risk floor: persistence schema plus review/admission/lifecycle gates are high-risk. Sol would be the canonical technical route, but no auxiliary Sol review was authorized. Two Luna prose rounds are exhausted; no further model review is allowed, and the orchestrator owns the final plan gate.

## Round-1 review resolution

The first Luna plan review returned eight findings, six blocking. All were accepted:

1. The impossible stable-id suffix assertion was corrected to exact identity equality; the affected oracle was re-frozen and the old commit excluded.
2. T1 now has real initial-admission and execution-revalidation tests plus typed unavailable control.
3. Execution revalidates every active-policy production decision, including previously pinned `satisfied` reviews.
4. Task-run ids are random per new assignment; retry idempotency comes from open-run uniqueness, so reopen creates a new interval.
5. Both explicit cancellation owners close the run.
6. Each non-atomic outer lifecycle is mapped to its existing rollback/quarantine/finalization-journal behavior; the receipt insert is atomic with the legacy assignment state.
7. Open-run traces use one explicit/default `as_of` upper bound and report `live=true`.
8. The schema oracle compares the full #462 baseline with exactly the five approved additions.

An additional in-flight adoption oracle was frozen after resolving the zero-run rollout edge. It creates an explicitly incomplete `legacy_inflight` row, never an invented acceptance fact.

## Review status and post-ceiling closure

- Route: Luna, two completed prose rounds; Sol was not authorized. The two-round ceiling is exhausted.
- Round 1: six blocking findings, one question and one suggestion. All eight were accepted; plan/oracles changed and Round 2 verified every Round-1 item as fixed.
- Round 2 verdict was **do not approve Phase 3**. It identified three blocking oracle gaps at that snapshot:
  1. `legacy_inflight` test does not yet prove `acceptance_before_receipt`, adoption-time semantics, second-`init_db` idempotency, or exclusion of completed historical tasks;
  2. failure injection covers taskless binding but not explicit switch and strict next-task finalization;
  3. cancellation test covers `api_update_task` but not `api_update_task_if_current`.
- The orchestrator explicitly directed self-closure without a third model round. Final oracle `fd9fc34d` now closes all five Round-2 items:
  1. the adoption test bounds `requested_at` by the migration call, invokes `init_db()` twice, proves one row, excludes a completed bound task, and the trace test requires `acceptance_before_receipt`;
  2. taskless binding, explicit switch and strict handoff each have independent receipt-failure injection and distinct RED messages;
  3. `api_update_task` and `api_update_task_if_current` each have an independent cancellation test;
  4. a turn and tool call after `as_of` are inserted and must be absent from the live trace;
  5. identical open retry must reuse the row, then same-task/session/snapshot reopen after terminal must create a different receipt id.
- Evidence: `.orchestra/tasks/466/review-plan-luna.md`, completed receipts `review-receipt:f1b2ae09-6f3d-48d7-9d9f-4dee1d933e47` and `review-receipt:693362ea-6aff-4c4f-9d23-4e4b0c9223eb`.
- No third model round was opened. The Round-2 negative verdict is preserved as dissent about the prior snapshot; it is not misreported as approval of the final oracle. The orchestrator will read the final plan/oracles and owns the Phase-2 approval gate.

# #466 — Phase 3 report

## T1 — author outcome gate — complete

### Result

T1 makes a completed real implementation review insufficient by itself. The newest structurally
qualifying `coverage_outcome=reviewed` row for the exact snapshot now blocks while
`author_outcome=unknown`; the existing direct writer `record_review_outcome` changes the same row
to `accepted|disputed|partial`. An older answered review cannot hide a newer unanswered review.

`skipped` and typed `unavailable` remain qualifying with `author_outcome=unknown`; neither is
rewritten as an author decision.

### Enforcement

- `app/review_coverage.py::coverage_decision` returns the exact unanswered receipt as
  `blocked/author_outcome_missing`, or exposes the direct author outcome/evidence reference on
  satisfaction.
- `app/merge_operations.py::accept_merge_operation` maps that reason to
  `REVIEW_AUTHOR_OUTCOME_MISSING`, includes the receipt id, and creates no merge-operation row.
- `app/merge_operations.py::_run_operation` revalidates every active-policy production decision,
  including a previously pinned `satisfied` review, before the test/executor/Git path.
- The shared refusal helper preserves the existing `REVIEW_COVERAGE_MISSING` behavior for all
  other absent/stale/invalid coverage.

### #462 contract change — old and new expectations

Old positive expectation, now superseded:

```python
("completed", "reviewed", "", False, False, True)
```

New positive and negative expectations, adjacent in
`tests/test_review_coverage_gate_462.py`:

```python
("completed", "reviewed", "", False, False, "accepted", True, "")
(
    "completed", "reviewed", "", False, False, "unknown", False,
    "author_outcome_missing",
)
```

Every other reviewed negative uses `accepted` so it still isolates status/session/snapshot. Skip
and both unavailable codes remain `unknown` and allowed.

### Tests

```text
/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q \
  .orchestra/tasks/466/test_run_receipt_466.py -k 'test_t1_'
4 passed, 2 deselected; RC=0

/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q \
  tests/test_review_coverage_gate_462.py -k 'test_t3_'
17 passed, 7 deselected; RC=0

/mnt/data/Projects/Python/orchestra/.venv/bin/python -m py_compile \
  app/review_coverage.py app/merge_operations.py
RC=0
```

Focused merge-runner regression: 3 nodes passed; the fourth,
`test_committed_merge_without_terminal_snapshot_is_quarantined`, failed identically on clean
`main@2a048e61` because active #462 revalidation tries the fixture's nonexistent `/worktree`.
It is pre-existing after T4, not introduced by T1.

### Mutation

Final production marker: `if reviewed and author_outcome not in REVIEW_AUTHOR_OUTCOMES:` count
`1`, with explicit allowlist `{accepted, disputed, partial}`.

Removal mutation changed only that comparison to a never-matching condition:

```text
test_t3_only_exact_review_skip_or_unavailable_receipt_authorizes
1 failed, 10 passed, 13 deselected; RC=1
failed node: completed-reviewed-unknown-False-author_outcome_missing
```

Thus removing the author check reddens exactly the new unknown-author case while accepted-reviewed,
skip and both unavailable controls remain green.

Reviewer-fix mutation replaced the allowlist comparison with the former
`author_outcome == "unknown"` condition. The committed
`test_t3_invalid_legacy_author_outcome_fails_closed` became the sole failed node (RC=1), proving
that invalid values from the pre-CHECK legacy schema cannot pass unnoticed. After each
restore/touch the final marker count was `1`, old-condition marker `0`; both named suites returned
RC=0 again.

### Pre-mortem

1. **Newer unanswered review falls back to an older accepted round.** Covered by the frozen T1
   selection test with two rows for one snapshot.
2. **Initial admission still emits generic coverage or inserts an operation.** Covered by the
   actionable error test and zero-row assertion.
3. **A pending operation admitted before T1 reaches the executor.** Covered by a distinct
   execution-revalidation test whose executor await-count stays zero.
4. **Skip/unavailable become false author decisions or start blocking.** Covered by the #466
   negative control and the expanded #462 matrix.
5. **Policy-version mismatch is mistaken for T1 regression.** The historical live skip has stored
   policy hash `8c3d727a…`; current policy hash is `3b0292de…`, so it returns
   `blocked/review_receipt_missing` both before and after T1. This is the intended pre-existing #462
   version binding, not a T1 change.

### Review

- Route: snapshot-bound Luna implementation review; high-risk Sol route was not authorized.
- Round 1 receipt: `review-receipt:7840f9c4-83e9-4c37-88ba-05d4ab27911a`.
- Verdict: incorrect — one P1 blocker, invalid legacy author values passed because only `unknown`
  was rejected.
- Resolution: accepted and recorded directly through `record_review_outcome`; regression first
  committed RED in `787f402d`, then production changed to the explicit allowlist.
- Round 2 receipt: `review-receipt:a40dec81-e873-4033-b828-ff8e9640b3e8`; the reviewer reran both
  named suites and `py_compile`, found no blocking/suggestion/question findings, and returned
  `Correct` with exact production quote `if review.get("reason") == "author_outcome_invalid":`.
- Round 2 author outcome: `accepted`, recorded directly through `record_review_outcome` with a
  reference to the Round-2 review section.
- Review evidence: `.orchestra/tasks/466/review-t1-implementation-luna.md`.

T1 implementation commits before report finalization: `e7d23ad8`, `b064bb5f`, `787f402d`,
`1a1cac9a`. The branch will be squash-merged, so these are local evidence ids rather than future
main-history ids.

## T2

### Result

T2 is implemented on top of fresh `main` containing #465. `review_receipts` remains the only
physical table and gained exactly five reference fields:

```text
task_stable_id
task_snapshot_ref
prompt_template_start
prompt_template_end
terminal_operation_id
```

One `subject_kind=task_run` row opens inside each accepted assignment path and closes on complete,
archive/release, or either cancellation API. Open-run uniqueness makes an identical retry return the
same row; a terminal then same-task/session/snapshot reopen receives a new UUID. Startup reconciliation
adopts only currently bound `in_progress` work as `legacy_inflight`, with empty acceptance snapshot and
prompt-start evidence; repeated startup is idempotent and completed historical tasks are excluded.

`app/run_receipts.py::build_task_run_trace` joins cost/models/tokens from `turn_usage`, tools/messages
from `logs`, review rows from the same table, and rollback from the referenced `merge_operations` row.
No aggregate is stored in the receipt. Open traces use one explicit/current `as_of` boundary and mark
legacy adoption with `acceptance_before_receipt`.

An implementation review/skip reservation now requires exactly one open task run when the durable
session and task are actively bound. Legacy/synthetic receipts without such a durable binding retain
their existing compatibility path.

### Files

- `app/db.py` — additive schema/indexes, run open/finish CAS, in-flight adoption, review/run join guard,
  new-worker publication hook.
- `app/tm.py` — taskless/explicit/handoff assignment hooks, complete/release/cancellation closures,
  heir run transfer, canonical task snapshot reference.
- `app/run_receipts.py` — read-time trace only.
- `scripts/migrate_review_receipts.py` — explicit empty defaults for the five new references.

`app/manager.py`, `app/routes/sessions.py`, and `app/mcp_stdio.py` required no T2 edits after #465:
their assignment/review paths already converge on the DB/TM owners above.

### Tests

```text
T2 frozen files, separate processes: 2 passed + 9 passed; RC=0 + RC=0
T1 frozen file: 4 passed, 2 deselected; RC=0
#462 full file: 24 passed; RC=0
DB/TM/task-binding/task-completion/review-receipt broad set: 166 passed; RC=0
spawn/taskless/promotion/complete/handoff/switch/removal integration nodes: 10 passed; RC=0
py_compile app/db.py app/tm.py app/run_receipts.py scripts/migrate_review_receipts.py: RC=0
```

After the interrupted review attempts and fresh-main merge, all relevant files were rerun as
separate pytest processes: **183 passed total**, every file RC=0. The final frozen oracle remains
byte-identical to `fd9fc34d` (`git diff --exit-code` RC=0). Two additional self-review regressions
are committed separately in `3b0314f4` and pass 2/2.

Two implementation mistakes were caught before review:

- adoption initially ran before the legacy `sessions.task_id` migration and all 11 T2 nodes failed
  with `no such column: s.task_id`; moving adoption after prerequisite session columns restored the
  intended seams;
- adding `canonical_head` to the shared task identity broke an exact consumer, and rereading the
  canonical head after an in-progress status write conflicted with the already-open run. The final
  code keeps the CAS identity shape unchanged, carries a separate `task_snapshot_ref`, and treats an
  existing same-session/task open row as the accepted snapshot.

### Mutation checks

Each mutant was restored with `touch`, the production marker re-counted `1`, mutant marker `0`, and
the same focused test rerun green:

1. Disable startup adoption → the dedicated adoption/idempotence/exclusion node failed.
2. Remove taskless bind opening → both taskless happy-path and receipt-failure atomicity nodes failed.
3. Disable the CAS cancellation close → only the `api_update_task_if_current` cancellation node failed.
4. Remove the assigned-task open hook → explicit-switch failure, strict-handoff failure, and successful
   handoff wiring nodes failed.
5. Ignore supplied `as_of` → the trace node admitted the later turn/tool and failed.
6. Remove terminal-operation replay lookup → the old completion closed a reopened run and the
   self-review replay node failed.
7. Normalize `cost_unaccounted` to false → the self-review cost-gap node failed.

### Pre-mortem

1. **Schema upgrade runs before its session prerequisites.** Covered by fresh/legacy init tests and the
   corrected migration order.
2. **A retry creates a second open row or a reopen reuses a terminal row.** Covered by the direct
   open/finish/reopen test plus two partial unique indexes.
3. **Assignment commits while receipt insertion fails.** Taskless, explicit-switch and strict-handoff
   failure injections cover their distinct rollback/partial paths.
4. **One cancellation owner leaves the run open.** Direct and compare-and-swap APIs have separate nodes.
5. **Archive transfers ownership but loses the heir interval.** Release closes the departing run and opens
   the heir's run in the same SQLite transaction.
6. **Live trace includes data after its requested observation boundary.** A later turn/tool is present in
   the fixture and excluded by `as_of`.
7. **Receipt becomes a third counter store.** Exact schema equality permits only the five reference fields;
   cost/models/tools/reviews/commits/rollback remain derived.
8. **Same-operation replay arrives after the task was reopened.** Completion first looks up its durable
   `terminal_operation_id`; it returns the old terminal row and leaves the new open row untouched.
9. **Unknown virtual cost is reported as zero.** Any `turn_usage.cost_unaccounted` or NULL cost makes
   derived `cost_usd=None` and adds `usage_cost_unaccounted` to gaps.

### Review

- Route selected: snapshot-bound Luna implementation review; Sol was not authorized.
- Attempt 1: `review-receipt:97218006-e3a9-4355-b870-7107c413826b`, interrupted by server shutdown,
  no reviewer output/session UUID.
- Attempt 2: `review-receipt:bf8fa2ae-6d25-46c8-9964-7439d37458ce`, 600-second timeout while reading
  unrelated `app/tm.py` body, no conclusion.
- Attempt 3: `review-receipt:69e4ae51-6b82-4a05-8350-d29659859244`, final restricted attempt,
  600-second timeout, no conclusion.
- Outcome: attempt ceiling 3/3, **0 completed review rounds, verdict absent**. No receipt has
  `coverage_outcome=reviewed`; no author outcome can honestly be recorded for T2.
- Required fallback completed: adversarial self-review found and fixed two concrete defects with
  committed RED tests and mutations (old-operation replay versus reopen; unaccounted cost versus zero).
- Evidence: `.orchestra/tasks/466/review-t2-implementation-luna.md`.

Because review coverage is active and the three attempts are ordinary interruptions rather than a typed
machine-unavailable outcome, merge requires an orchestrator-authored structured skip for this final
snapshot. This report does not call the timed-out attempts a review or an approval.

### Rollout / remaining live proof

The branch has not migrated the production database. After merge and restart, `init_db` must add only
the five fields/indexes, adopt each currently bound in-progress task once with explicit legacy gaps, and
the next accepted scratch task must show one run row before its first review/turn and a terminal
operation reference after completion.

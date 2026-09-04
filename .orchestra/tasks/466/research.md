# #466 — research: from review receipt to task-run receipt

## Question

- **Context:** `review_receipts` stores one row per `codex_review` round (and, after #462, one structured skip/unavailable decision) while task lifecycle, model usage, logs, commits and merge rollback facts live in other owners.
- **Change under test:** first make the author's response to a real review impossible to bypass at task surrender; then add a task-run anchor to the existing `review_receipts` table and derive the rest of the trace by references/joins.
- **Baseline:** `record_review_outcome` is a voluntary MCP call. The merge coverage gate accepts a completed review without consulting `author_outcome`. There is no durable interval from task acceptance to terminal outcome.
- **Measurable outcome:** a production merge cannot start when its newest qualifying real-review receipt has `author_outcome='unknown'`; every newly accepted task execution has one bounded task-run receipt; cost/model/tool/review/merge facts are computed from their existing owners and are not copied into new receipt columns.

## Hypotheses considered

### H1 — the missing author outcome is a structural bypass

`author_outcome` stays empty because the sole writer is an optional tool and no completion owner checks it.

**Falsifier:** a production caller of `record_review_outcome`, a merge/finalization check for `author_outcome`, or non-`unknown` rows in the live table.

### H2 — prompt reinforcement is sufficient

The step is merely forgotten, so another prompt instruction would raise completion close to 100% without a code gate.

**Falsifier:** zero calls across all receipts despite the outcome tool and review workflow already being delivered, together with a code path that completes tasks without reading the field.

### H3 — one existing review row can also be the whole task receipt

The selected implementation-review row can carry task start, prompt, total cost, retries and rollback references without a new row.

**Falsifier:** multiple review rows per task execution, tasks that terminate through skip/unavailable or without production review, or task acceptance occurring before any review row exists.

### H4 — one task-run anchor plus joins is sufficient

One sibling row with `subject_kind='task_run'` in the existing table can own only the non-derivable task interval/input references; the requested operational trace can be reconstructed from `logs`, `turn_usage`, review rows, `merge_operations` and the canonical task.

**Falsifier:** a requested fact has no durable owner or cannot be scoped unambiguously by task-run identity and time bounds.

## Measurements

All database measurements used `/mnt/data/Projects/Python/orchestra/data/orchestra.db` via `sqlite3 -readonly` in one transaction or one read statement. No production row was changed.

### M1 — task-creation snapshot is reproducible

The task was created at `2026-09-03T12:07:17.039682+00:00`. Restricting receipts to `requested_at` no later than that cutoff gives 40 rows. One of those rows (`review-receipt:97f2277c-...`) was still requested at the cutoff and completed at `12:10:08`, with its verdict written after the cutoff. Removing that later transition from the current state reconstructs exactly:

```text
total=40 completed=31 interrupted=8 requested=1
verdict_present=27 completed_without_verdict=4
author_outcome_unknown=40 author_outcome_recorded=0
```

This confirms the supplied 40-row snapshot rather than treating the later live state as a contradiction.

### M2 — the gap persists while the table grows

Snapshot at `2026-09-03 12:41:26 UTC`, receipt watermark `2026-09-03T12:40:09.730300+00:00`:

```text
total=44 completed=35 interrupted=9 requested=0
verdict_present=30 completed_without_verdict=5
author_outcome_unknown=44 author_outcome_recorded=0
logs.tool_name='record_review_outcome': 0 calls
```

The live count changed during research because #462 was running real probes. The load-bearing result did not change: the author outcome remained empty in every row and the tool still had zero calls.

### M3 — review receipt grain is not task grain

At the same watermark:

```text
44 receipt rows
17 distinct (scope, session_id, task_id) task/session executions
24 artifact paths
maximum receipts for one task/session execution: 8
```

`coverage_decision` deliberately returns one newest qualifying snapshot-bound receipt, not an aggregate. #462's live implementation receipt proves the extended writer is active: it has `subject_kind=implementation`, 40-character `target_sha` and 64-character `production_snapshot_sha256`.

### M4 — adjacent owners already contain the expensive facts

For the current #462 execution, using its task-specific `turn_usage` interval as a temporary lower bound produced:

```text
17 turn_usage rows; 2 distinct runtime/model pairs; $41.6307 virtual cost
8 failed turns
212 tool calls; 4 distinct tool names
4 merge operations; 1 successful merge
1 task-linked commit
0 direct-user messages; 8 agent messages; 6 background-job messages
```

The 17 receipt-bearing task/session executions all had `turn_usage`; 11/17 used more than one runtime/model pair. Storing one model or one cost in a task receipt would therefore be both a duplicate and false for most of this sample.

### M5 — existing timestamps do not define task acceptance

Across 318 `(session_id, scope, task_id)` groups with task-attributed `turn_usage`, 21 first task turns occurred more than 24 hours after the session was created; the maximum gap was 1,680.3 hours. `sessions.created_at` is therefore not a task-run start for persistent workers. `tm_tasks.created_at` is queue creation, not acceptance, and can also precede work by hours. A new acceptance boundary is not derivable from either field.

## Findings

### F1 — why `author_outcome` is 0/N

**CONFIRMED — direct measurement plus complete current call-site search.**

`record_review_outcome` is defined in `app/mcp_stdio.py` and calls `review_receipt_set_outcome` in `app/db.py`. The only production occurrence is the definition; the other occurrences are tests. `coverage_decision` in `app/review_coverage.py` accepts a structurally completed `coverage_outcome='reviewed'` receipt without reading `author_outcome`. Both admission and execution-time revalidation in `app/merge_operations.py` rely on that decision. The live database has 0 calls and 0 recorded outcomes after 44 receipts [M2][S1][S2].

The failure is therefore not evidence of an inconvenient UI or occasional forgetting. The workflow has no owner that makes the selected option B from #436 mandatory.

### F2 — the non-bypass seam is the existing #462 merge coverage decision

**CONFIRMED — current code has two fail-closed checks on the same decision.**

Only `coverage_outcome='reviewed'` needs an author response. `skipped` is the trusted orchestrator's decision and `unavailable` is a typed machine outcome; both intentionally keep `author_outcome='unknown'`. For a real review, `coverage_decision` must stop at the newest otherwise-qualifying receipt for the exact snapshot: `unknown` returns `blocked/author_outcome_missing` with that receipt id; `accepted|disputed|partial` returns `satisfied`. It must not fall back to an older accepted round when a newer completed round is unanswered. After #462 T4 activates the policy, the existing admission and execution revalidation make this decision non-bypassable before Git; before T4, the current workflow remains bypassable by design [S2][S4].

The MCP tool remains the user's chosen explicit writer from #436. No parser should infer an author decision from prose, and no skip row should be rewritten as `accepted` [S3][S4].

### F3 — the existing physical table can hold task runs, but an existing review row cannot represent them

**CONFIRMED — measured cardinality refutes the one-review-row hypothesis.**

The current row key is one review/round/decision, while one task/session execution already has up to eight such rows [M3]. Review starts after task acceptance, and #462 keeps multiple rounds separate. Extending every review row would duplicate task/prompt/terminal references 1–8 times and would leave tasks with no review row unrepresented. H3 is refuted.

The least-lossy design under the hard “same table, no second table” constraint is a sibling row with `subject_kind='task_run'`, one per accepted task assignment. In the normal case one task has one run row. Reassignment/recovery produces another run row; task-level reporting aggregates them by stable task identity. This preserves disjoint intervals and writers instead of putting arrays of attempts into one mutable row.

### F4 — only five new stored references are justified

**LIKELY — field-by-field owner analysis leaves five historical references that cannot be recovered safely after their mutable owners advance; final names remain an architecture choice.**

Reuse existing columns on a `task_run` row for `receipt_id`, `subject_kind`, `scope`, `session_id`, `worker_name`, display `task_id`, `requested_at`, `completed_at`, `status` and `failure_code`. Add only:

| Stored reference | Current owner | Why a later join cannot recover the accepted value | Why this is not a duplicate |
|---|---|---|---|
| `task_stable_id` | canonical task state | Receipt `task_id` is a project display number; renumber/collision repair can change its referent, and live `tm_tasks` has no `stable_id` column. | Stores identity only, not task text or status. |
| `task_snapshot_ref` | canonical task version/head | Current task state can advance after assignment; `updated_at` does not identify the exact canonical content accepted. | Stores a version pointer, not a copy of the task. |
| `prompt_template_start` | mutable `sessions.template_hash` | Session rows are overwritten on prompt refresh/reconnect, and persistent sessions can span many tasks (M5). | Freezes one cohort hash; no prompt text is copied. |
| `prompt_template_end` | mutable `sessions.template_hash` | Without the terminal hash a mid-run prompt refresh is indistinguishable from a constant-prompt run. | Stores the second boundary hash only; equality makes stability derivable. |
| `terminal_operation_id` | `merge_operations` | A task can have checkpoint merges plus a terminal merge; `(session, task, time)` does not identify which operation closed the task under retries/replay. | Stores the foreign reference; rollback SHA/result remain solely in `merge_operations`. |

No stored columns are justified for model, tokens, cost, turn count, tool count, retry count, review count, commit list, changed paths or rollback SHA. Those values already have owners and are mutable aggregates, not receipt facts [M4][S1][S2].

Review rows need no new `task_run_id` if the write invariant is enforced: a task-bound review reservation must observe exactly one open `(scope, session_id, task_id, subject_kind='task_run')` row for tasks accepted after rollout. Run intervals are non-overlapping; a review belongs to the unique interval containing its immutable `requested_at`, regardless of when its asynchronous finalizer writes `completed_at`. A partial unique index forbids two open `task_run` rows for one stable task assignment. A post-rollout reservation with zero or multiple matches fails loud; legacy/in-flight tasks are explicitly `run_reference=unknown` and never silently attached by nearest timestamp.

### F5 — what the joined trace can and cannot answer

**CONFIRMED for owner availability; UNCERTAIN for causal attribution.**

With the five references and run bounds, a read-time trace can provide:

- task input and prompt cohort from the task-run row;
- actual runtime/model mix, cost, tokens, successful/failed turns from `turn_usage`;
- raw tool calls, tool outputs and inbound provenance from `logs`;
- review rounds, verdict presence, coverage decision and author response from sibling `review_receipts` rows;
- merge attempts and rollback point from `merge_operations` through `terminal_operation_id`;
- final task state and commit links from canonical task storage.

This makes before/after prompt or model cohorts measurable without storing a third copy. It does not by itself prove the model or prompt caused the difference; mixed-model/mixed-prompt runs must be identified and causal claims still require controlled or matched comparisons.

Two requested phrases are not currently honest scalar metrics:

- “how many retries” has no single owner/definition. The trace can expose failed turns, review rounds and repeated tool records separately; it must not store a guessed aggregate.
- “how much the human corrected” is only exact for direct operator messages (`logs.origin='user'`). In #462 the worker saw zero direct-user messages and eight agent messages; a human decision relayed by an orchestrator is stored as agent provenance. Full human-effort attribution is therefore an upstream provenance gap, not a receipt column [M4][S2].

### F6 — run open/close needs code ownership, not agent memory

**LIKELY — production writers are inventoried, but the final hook placement needs Phase-3 validation.**

Task acceptance is written through three lifecycle shapes: new-worker publication (`app.db.publish_ready_session`), binding a taskless worker (`app.tm.bind_task_to_session`), and next-task/switch transitions in `app/routes/sessions.py` plus strict merge finalization. Successful task completion is owned by `app.tm.finalize_merge_outcome`; archive/requeue is owned by `release_session_task_binding`. The run receipt must open/finish inside or immediately adjacent to those state transitions and must be protected by a source-inventory oracle so a future writer cannot bypass it [S2].

Creating the run row only on the first `turn_usage` event would catch more writers cheaply but is refuted as the primary design: it records first completed model turn, not acceptance, and M5 measures delays of more than a day for persistent sessions.

## Architecture fork for approval

### A — recommended: one task-execution row in the existing table

- Grain: one `subject_kind='task_run'` row per accepted task/session assignment; review rounds stay separate rows.
- Price: one additive migration/index; five stored reference fields; open/finish wiring at the task lifecycle owners; one read-time join module; neutral values in review-only NOT NULL columns; task-level consumers aggregate multiple runs after reassignment.
- Benefit: exact interval and prompt/task/terminal references, no duplicated operational counters, no loss of retries/reassignments.

### B — cheaper code, rejected: enrich the selected review row

- Grain: whichever review row #462 selects at merge.
- Price: fewer lifecycle writers and no extra row, but task references are duplicated across rounds or attached only at the end; no receipt exists from acceptance; reviewless/non-production tasks disappear; a later review round can silently change which row represents the task.
- Measured conflict: 44 review rows currently represent only 17 task/session executions, with a maximum multiplier of eight [M3].

### C — one mutable row per canonical task

- Grain: exactly one row even across reassignment/reopen.
- Price: every disjoint run interval, prompt transition, session and terminal operation must become an array/event log inside one row or overwrite history; multiple lifecycle writers coordinate on the same mutable record.
- Verdict: this optimizes row count by discarding the run identity needed for retries and rollback. It conflicts with the requested “where/what/how” trail.

Recommendation: approve A. It obeys “second table not allowed” while retaining the only grain that can be joined without copying or overwriting facts.

## Counter-evidence and risks

- The sample is observational and new: only 44 receipt rows and 17 task/session executions. It proves the 0/N outcome gap and grain mismatch, not future query performance.
- `review_receipts` is a misleading physical name for task-run rows and has review-only NOT NULL columns. Renaming/rebuilding the live table during #462 rollout would increase migration and compatibility risk; neutral values plus `subject_kind` are the explicit cost of the no-second-table constraint.
- `bg_jobs` is not a durable analytical owner: only 26 of the first 42 non-empty job ids still resolved during research. The trace must use review receipt terminal facts and `turn_usage`, not assume a permanent job row.
- `usage_event_id` is a namespace prefix, not an exact foreign key: stored `turn_usage.event_id` appends thread id and JSONL line number. Joins must use the prefix contract or task-run bounds.
- The current #462 gate is inactive until its T4 skill marker is merged. #466 schema/writer implementation must start only after #462 T4 owns and releases the same receipt/prompt surface.
- A missing owner row must be reported as `unknown/missing_reference`, never normalized to a zero cost, zero retries or “no human intervention”.

## Affected files for a later Phase 3

- `app/review_coverage.py` — author-outcome qualification on the newest real review.
- `app/merge_operations.py` — typed/actionable author-outcome refusal at both admission and execution revalidation.
- `app/db.py` — additive fields/index and task-run open/finish/read primitives.
- `app/tm.py` — task binding, completion and interruption owners.
- `app/manager.py`, `app/routes/sessions.py` — only the lifecycle seams not already atomic in DB/TM owners.
- `app/run_receipts.py` (new, proposed) — read-time joins/derived trace; no stored aggregates.
- focused tests; no new table, no receipt prose, no duplicated cost/model/tool/commit counters.

## Sources

1. **Tier 1 — direct measurement:** read-only SQL commands and outputs recorded in M1–M5 during this session against `/mnt/data/Projects/Python/orchestra/data/orchestra.db`, latest watermark `2026-09-03T12:40:09.730300+00:00`.
2. **Tier 2 — current primary source:** `app/db.py` (`review_receipts`, `review_receipt_set_outcome`, `publish_ready_session`, `turn_usage`); `app/mcp_stdio.py::record_review_outcome`; `app/review_coverage.py::coverage_decision`; `app/merge_operations.py` admission/revalidation; `app/tm.py` task binding/finalization; `app/events.py::MessageProvenance`, all from `main@1a86f403`.
3. **Tier 2 — approved design history:** `.orchestra/tasks/436/research.md`, `.orchestra/tasks/436/plan.md`, `.orchestra/tasks/436/report.md`; option B is the explicit author-outcome interface owner.
4. **Tier 2 — merged rollout evidence:** `.orchestra/tasks/462/plan.md`, `.orchestra/tasks/462/report.md`, `.orchestra/tasks/462/review-*.md`; live extended receipt inspected after service restart.

## Review decision inputs

- Changed artifact/consumers: this research file only; future consumers are the persistence and merge/lifecycle seams listed above.
- Author runtime/model: Codex / `gpt-5.6-sol` from current session metadata.
- AC: explain 0/N structurally; preserve skip/unavailable semantics; present a no-copy field map; expose the task-vs-review grain fork and both prices.
- Mechanical checks: section/anchor scan plus SQL numbers above. No independent deterministic oracle can validate the architecture choice.
- Risk floor: persistence schema plus review/admission/lifecycle gates are high-risk. Canonical route is Sol, but no auxiliary Sol review was authorized; one Luna adversarial pass is used without claiming it lowers the risk floor.

## Research review outcome

- Route: Luna (`gpt-5.6-luna`), one completed review round after one tool-timeout attempt. Sol was not authorized.
- Attempt 1: receipt `review-receipt:ebd279a3-7a14-44ef-a161-1f95c8f06010`, `interrupted` after 600 s, no reviewer conclusion; it did not consume a review round.
- Completed round: receipt `review-receipt:978360c1-f022-4e77-9899-cf6fb67f42c3`, `completed`, verdict present. The reviewer quoted the exact artifact sentence beginning `Review rows need no new task_run_id`, and that sentence was verified in the reviewed file.
- Verdict: no blocking findings. The reviewer confirmed the structural 0/N diagnosis and skip/unavailable treatment, then identified three precision gaps: T4 conditionality, exact-one run join, and field-level non-derivability. All three are corrected above. No second prose round is justified because there was no blocking finding.

## KB promotion

No KB file is changed in Phases 1–2 because the explicit task boundary permits writes only under `.orchestra/tasks/466/`. The conclusion is preserved here for promotion after the implementation boundary is approved.

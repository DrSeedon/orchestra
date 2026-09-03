# #465 — taskless adhoc merge deadlock

## Question

- **Context:** schema-v2 lifecycle around `merge_worker`, `switch_worker_branch`, task binding, and squash merge.
- **Change under test:** provide a lossless path from an unbound session with committed adhoc work to a canonical task and merge.
- **Baseline:** `merge_worker` requires an existing session↔task binding; `switch_worker_branch` refuses to move a branch whose content is not proven in the base.
- **Measurable outcome:** the reproduced state can be assigned and merged without `force=True`; the committed worker HEAD remains reachable until merge; ordinary `task_outcome="complete"` still yields task `done`, `worker_session_id IS NULL`, session `task_id=''`, `needs_switch=1`.

## Hypotheses considered

1. **H1 — an explicit primary `task_id` on `merge_worker` can close the deadlock because the merge operation can bind the unbound adhoc work before applying the existing strict merge/finalization path.**
   - Falsifier: the current task-binding transaction cannot safely bind an unbound session and unowned task, or the strict ref/finalization path necessarily requires a different already-closed primary task.
2. **H2 — bypassing the committed-content check in `switch_worker_branch` can close the deadlock.**
   - Falsifier: the subsequent switch operation moves HEAD away from the current committed work, so bypassing the check loses the very commits being recovered.
3. **H3 — a bind-only adoption path can attach the current adhoc branch to a new task, after which unchanged `merge_worker` can merge it.**
   - Falsifier: no atomic session↔task binding owner exists, or adoption cannot be distinguished from the ordinary post-completion state without guessing.

## Findings

### F1 — both refusals are real and form a closed cycle

**CONFIRMED — current source plus three durable production operation records (evidence tier 1 measurement + tier 2 primary source).**

- Schema-v2 merge rejects an empty durable binding at `app/routes/sessions.py:1957-1964`: `primary_task_ref` is read from `sessions.task_id`; an empty value returns `session has no bound task` before task resolution or Git [1][2].
- `switch_worker_branch` reaches `switch_worktree_branch` through `app/mcp_stdio.py:2777-2812` and `app/routes/sessions.py:2385-2479`. With `force=False`, `app/workspace.py:2089-2105` calls `branch_content_status` and rejects `content_merged=False` with `merge_worker first or pass force=True` [2].
- Live `merge_operations` rows for `3a73d10d-cc09-497c-992d-b7cf3b529b4d`, `3fad12a7-4b12-4183-9a55-2b3d3398beb2`, and `868b0bce-b430-4b27-ba70-d7ecd37bf607` are all `FAILED`, `commit_point=NOT_REACHED`, HTTP 409, `error.message="session has no bound task"`, `lifecycle.status=NOT_RUN` [1][3].

### F2 — the switch guard prevents data loss and must remain

**CONFIRMED — current source, originating change, and its preserved regression test (evidence tier 2 primary sources).**

- After the guard, the switch implementation detaches at the original HEAD and runs `git reset --hard <from_ref>` at `app/workspace.py:2381-2395`; allowing the function through on unmerged content would remove the committed work from the checked-out HEAD before creating/checking out the target task branch [2].
- The guard originated in #103 to prevent branch switching/deletion from discarding genuine worker-only content while allowing squash-equivalent content. Its pass criteria explicitly require “genuinely unmerged worker content → block”; `tests/test_workspace.py:1040-1080` asserts that worker HEAD and branch do not move when content differs [4].
- Therefore H2 is **REFUTED**. Removing or broadly bypassing the check is not a fix; it converts a visible deadlock into silent loss.

### F3 — the SQL predicate finds 104 rows; the requested live-Git state contains 11 sessions, of which 10 are still rejected by the exact switch guard

**CONFIRMED — WAL-consistent live-DB snapshot plus direct Git measurements in each existing worktree (evidence tier 1 measurement).**

The measurement used `sqlite3.Connection.backup()` from `/mnt/data/Projects/Python/orchestra/data/orchestra.db`. Stage 1 selected `coalesce(task_id,'')='' AND branch LIKE 'adhoc-%'` and returned 104 durable rows. Stage 2 applied the rest of the user's predicate: `status!='archived'`, existing worktree, durable/actual branch agreement, resolvable base, and `git rev-list --count <base>..HEAD > 0`. The unit and deduplication key is the unique `sessions.id`; all 11 actual branches matched their stored branch. Counts:

```text
snapshot_adhoc_unbound_rows=104
worktrees_with_commits_total=11
worktrees_with_commits_non_archived=11
worktrees_with_commits_archived=0
unresolved_existing_worktrees=0
```

The 11 rows are:

```text
feat-attribution=1
feat-remove-ip-api=3
fix-summary-detail=4
frontend=1182
hide-time-prefix=5
marketer=6
memory-research=1107
prompt-engineer=1184
research-codex-harness=1
sales=1
terrain-dev=29
```

Applying production `resolve_base_branch` + `branch_content_status` to those same 11 rows returned:

```text
guard_blocked_unbound_adhoc=10
committed_but_content_verified=1
detector_errors=0
```

Nine of the 10 blocking rows are `reason=conflict`; one is `reason=content-change`. `hide-time-prefix` is now `content-noop`, consistent with the manual squash merge `ed30d73c` recorded in the task card. Thus **104** is the SQL prefix only, **11** is the exact requested live-Git state, and **10** is the current still-destructive/deadlocked subset [3].

### F4 — `NULL + done` is the intended terminal state, not corruption

**CONFIRMED — current finalizer source and existing tests (evidence tier 2 primary source).**

- For `outcome="complete"` with no next task, `prepare_merge_finalization` deliberately emits `terminal_session={"task_id":"", "needs_switch":True}` at `app/tm.py:896-901` [2].
- `finalize_merge_outcome` marks the task `done` and clears `tm_tasks.worker_session_id` at `app/tm.py:1341-1367`; `_apply_merge_finalization` persists the empty session binding at `app/routes/sessions.py:1727-1764` [2].
- Existing tests assert the terminal payload and completed task (`tests/test_task_tracker_integration.py:1273-1319`) but do not assert the durable session `task_id` in that same successful completion scenario [5]. Phase 2 therefore needs an explicit unchanged-green control for this state.
- A repair keyed only on `sessions.task_id=''` would conflate the intended terminal with later adhoc work and is rejected.

### F5 — choose guarded promotion of the current adhoc branch in `switch_worker_branch`; keep the destructive switch helper and merge contract unchanged

**LIKELY — current API/state-machine fit is supported by source and closes both Luna blockers; the Git/DB rollback sequence still needs the Phase-2 oracle/review (evidence tier 2 primary sources).**

- Extend the existing `switch_worker_branch(name, task_id)` route with one narrow **promotion**, not a verification bypass: when the durable session is unbound, `needs_switch=False`, and the durable/current branch is the same `adhoc-*` branch with `commits_ahead>0` and `content_merged=False`, rename/promote that exact HEAD to `task-<N>/<worker>` and bind it to the requested task. Do not call the detach/reset path at `app/workspace.py:2381-2395` for this case.
- Eligibility for the requested task must be checked inside the binding transaction: status exactly `new`, `worker_session_id IS NULL`, no reservation, same scope/project. A `done` task is rejected rather than reopened. This is stricter than the general-purpose `bind_task_to_session`, whose current `app/tm.py:814-829` path can turn any unowned status into `in_progress` [2].
- The successful promotion is an explicit recoverable checkpoint: after it, session and task are bound and the committed HEAD is unchanged/reachable. If unchanged `merge_worker` later rejects a ref, conflict, target movement, or dirty target, the task honestly remains `in_progress` and the same merge can be retried; neither tool points at the other and no work was discarded.
- The ordinary post-completion state cannot enter promotion: it has `needs_switch=True` and its old task branch is already content-verified. The ordinary switch continues to create a clean task branch, while a plain taskless merge continues to reject.
- `next_task_id` keeps its current post-merge handoff meaning; `merge_worker` gains no second primary-task interpretation, and all existing schema-v2 ref validation, receipts, linking, and `continue|complete` finalization remain unchanged.
- H1 is no longer preferred: inserting a new primary binding inside merge admission creates a second ownership path and an ambiguous pre-Git checkpoint. H3 is the selected design because it makes attribution a completed lifecycle transition before merge while preserving the merge safety contract.

## Counter-evidence and open risks

- Promotion spans Git ref/branch identity and SQLite/canonical task ownership; Phase 2 must specify rollback/quarantine if branch promotion succeeds but binding persistence fails, and test that the original committed HEAD remains reachable in every failure result.
- A taskless adhoc commit may name another `#N`. Promotion does not bless commit headers: unchanged `merge_worker` candidate-ref validation must still reject mismatched/unknown refs without changing the bound checkpoint.
- `branch LIKE 'adhoc-%'` plus commits is insufficient by itself. The gate also requires `needs_switch=False`, exact durable/current branch and HEAD agreement, production `branch_content_status.content_merged=False`, and a `new` unowned unreserved target task.
- The historical rows with 1100+ commits reflect long-diverged worktree histories. They satisfy the requested predicate and the production guard, but a future recovery UI may need a separate operator decision before assigning their content.

## Affected files, risks, edge cases

- `app/mcp_stdio.py` — only user-facing result wording may need to distinguish promotion from a normal branch switch; no merge argument change.
- `app/routes/sessions.py` — detect the narrow promotion state under the existing session/lifecycle locks and persist its result.
- `app/workspace.py` — preserve/promote the current HEAD without entering the destructive detach/reset path; keep the existing non-force content guard for ordinary switches.
- `app/tm.py` — add/reuse a transaction that accepts only a `new`, unowned, unreserved task and an unbound session; never broaden the existing binder to reopen `done`.
- `tests/test_task_tracker_integration.py` and/or a focused new test file — deadlock reproduction plus normal `NULL + done` control.
- High-risk surface: lifecycle gate, persistent session/task binding, merge attribution, and data-loss prevention.
- Edge cases: already-bound mismatch, nonexistent/cross-scope/reserved/already-owned task, empty adhoc branch, non-adhoc taskless branch, branch/HEAD drift, merge failure after binding, `task_outcome=continue`, `task_outcome=complete`, existing `next_task_id` handoff.

## Adversarial review

- Route: Luna, two prose rounds; Sol was the risk-floor preference but no additional Sol run was authorized.
- Round 1 found two blocking gaps: the generic binder could reopen `done`, and binding inside merge admission could survive a later refusal with ambiguous ownership. Both were confirmed in current source.
- The research was changed to require a `new`/unowned/unreserved target and to move adoption into a separate successful branch-promotion checkpoint outside `merge_worker`.
- Round 2 verdict: **APPROVED**, both prior blockers **FIXED**, no new blocking finding. Evidence quote was verified in this file: “H3 is the selected design because it makes attribution a completed lifecycle transition before merge while preserving the merge safety contract.” [6]

## Sources

1. **Tier 1:** Orchestra `task_get("465")`, opened 2026-09-03 — verbatim tool failures, operation IDs, failure-time DB state, and manual recovery commit.
2. **Tier 2:** current source opened 2026-09-03 — `app/routes/sessions.py`, `app/workspace.py`, `app/mcp_stdio.py`, `app/tm.py`, `app/manager.py`.
3. **Tier 1:** read-only live SQLite backup plus per-worktree Git/production-detector commands, run 2026-09-03 — counts and operation records quoted above.
4. **Tier 2:** #103 origin evidence opened 2026-09-03 — commit `8368d8ac`, `.orchestra/tasks/103/research.md`, `.orchestra/tasks/103/plan.md`, `tests/test_workspace.py`.
5. **Tier 2:** #248 lifecycle contract and current tests opened 2026-09-03 — commit `6f874ace`, `.orchestra/tasks/248/plan.md`, `.orchestra/tasks/248/report.md`, `tests/test_task_tracker_integration.py`.
6. **Tier 2:** `.orchestra/tasks/465/review-research.md` — Luna adversarial review, two rounds; round 1 blockers verified and incorporated, round 2 approved the revised conclusion with an exact artifact quote.

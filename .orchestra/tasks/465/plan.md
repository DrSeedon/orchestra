# #465 — plan: promote committed taskless adhoc work without weakening branch safety

## Decision

Add an explicit `promote_current: bool = False` mode to `switch_worker_branch`. The mode does not bypass `branch_content_status` and never enters the existing detach/reset switch path. It promotes the currently checked-out `adhoc-*` branch to `task-<N>/<worker>` at the identical HEAD, then binds the session/task through the existing lifecycle ownership path. The caller then uses unchanged `merge_worker`.

Default `switch_worker_branch` behavior stays unchanged. `promote_current=True` and `force=True` are mutually exclusive and rejected before any Git command.

No numeric commit-count cutoff is added. Commit count does not measure diff size or ownership, and a guessed threshold would recreate the deadlock. Every promotion instead requires an explicit caller flag and reports `previous_branch`, `branch`, `head`, `commits_ahead`, and `reason`; promotion itself does not merge content. Existing merge conflict, ref-validation, receipt, and diff-budget gates remain authoritative.

## State boundary

| Durable/Git state | `promote_current=True` outcome |
|---|---|
| `task_id=''`, `needs_switch=False`, durable branch equals actual `adhoc-*`, clean worktree, expected HEAD unchanged, `commits_ahead>0`, `content_merged=False`, target task `new`/unowned/unreserved/same scope | Promote the current branch name at the same HEAD, bind target task, return `promoted_current_work` |
| Normal completion: `task_id=''`, `needs_switch=True`, completed task `done`, old task branch already content-verified | Promotion refused; ordinary clean branch switch remains the valid next action |
| Empty or already content-verified adhoc branch | Promotion refused; no work needs adoption |
| Session already bound, branch/HEAD mismatch, dirty worktree, non-adhoc branch | Promotion refused before Git mutation |
| Target task is `done`, already owned, reserved, wrong scope/project, missing, or revision changed | Promotion refused; a terminal task is never reopened |

## Production changes

### `app/mcp_stdio.py::switch_worker_branch`

- Add `promote_current: bool = False` to the public signature.
- Send `promote_current` in the existing `/api/sessions/{name}/switch-branch` JSON body.
- Render `state == "promoted_current_work"` as `Promoted current work to branch <branch>`; keep ordinary success/failure text unchanged.
- Do not change `merge_worker`, `next_task_id`, or `force` semantics.

### `app/workspace.py`

- Add a dedicated `promote_worktree_branch(...)` helper beside `switch_worktree_branch`; do not add a bypass branch inside the destructive helper.
- Under `repo_mutation_lock`, validate:
  - clean worktree;
  - actual branch and HEAD exactly equal the durable/expected values;
  - current branch matches the platform-owned `adhoc-*` shape for this worker;
  - target branch is absent;
  - `branch_content_status(worktree, base)` returns `commits_ahead>0` and `content_merged=False` (`content-change` and `conflict` are both adoptable because promotion does not merge).
- Rename the checked-out branch to `task-<N>/<worker>` while preserving the exact commit OID, then verify actual branch, HEAD, target ref, clean status, and absence of the old ref.
- Return structured success/failure with both branch names and the pinned HEAD. Never call `checkout --detach`, `reset --hard`, or merge.
- Provide a reverse promotion operation guarded by the same expected HEAD/ref ownership. It may rename only the ref this operation just created; uncertainty preserves both/actual refs and returns `rollback_failed` rather than deleting anything.
- Leave `switch_worktree_branch` lines containing the #103 content guard and detach/reset path unchanged.

### `app/tm.py`

- Add promotion-only CAS inputs to the existing task-status owner rather than broadening `bind_task_to_session`: `expected_status="new"` and `require_unreserved=True` on `api_update_task_if_current` and its legacy/canonical adapters.
- The final legacy task claim must check and update in one `BEGIN IMMEDIATE` transaction: exact task identity/revision, status `new`, `worker_session_id IS NULL`, no `tm_task_reservations` row, and the unique same-scope session already checkpointed with this task id/branch. A reservation inserted after the earlier read must make the claim fail.
- Canonical status/owner remains guarded by its own identity/revision CAS. Any later legacy rejection after canonical success is returned as explicit `projection_debt.canonical_applied=True`, never flattened to success.
- In shadow mode, any non-empty projection debt — including `reason=candidate_write_failed` and candidate-rejection debt — is not a completed claim even when the legacy-shaped top-level result says `ok=True`.
- A read-only preflight may fail early for UX, but it is not authorization; the transactional claim repeats every eligibility predicate at the mutation point.
- Do not make the general binder capable of reopening `done`.

### `app/manager.py::_auto_switch_before_delivery`

- Treat the already-used durable combination `task_id != '' && needs_switch=True` as a hard lifecycle quarantine: raise a visible error before calling `switch_worktree_branch`.
- Preserve ordinary completion behavior: `task_id='' && needs_switch=True` still auto-switches to a fresh adhoc branch before delivery.
- This adds no schema column. The combination already means “task named, branch/lifecycle transition incomplete” in merge/switch failure paths; the missing part is enforcing it at delivery.

### `app/routes/sessions.py::switch_branch`

- Parse `promote_current` as a real boolean. Reject `promote_current && force` with HTTP 400 before resolving/mutating Git.
- Stay under the existing session lock and loaded-session lifecycle lock.
- Re-read the durable session and actual Git branch/HEAD after waiting for idle; do not trust the request or the earlier loaded object.
- Run promotion eligibility and pin task identity, session branch, base, and HEAD before mutation.
- Apply the ordered checkpoint:
  1. promote Git branch at the same HEAD;
  2. persist session `branch=task-<N>/<worker>`, `task_id=N`, `needs_switch=True` (durable quarantine while task ownership is incomplete; manager delivery now refuses this combination);
  3. call the existing CAS task update to `in_progress` with `expected_status="new"`, inferred session owner, and `require_unreserved=True`;
  4. only after both owners report success, persist `needs_switch=False` and return `promoted_current_work`.
- Clear failure before task mutation (`ok=False` and no `canonical_applied`): reverse the branch promotion, restore `task_id=''`, `needs_switch=False`, and report `promotion_binding_failed`. Inspect actual Git after rollback and persist the observed branch, never an assumed one.
- Unknown/partial task outcome is any exception, `shadow_match=False`, or non-empty `projection_debt` (including `canonical_applied`, `candidate_write_failed`, and candidate rejection), regardless of top-level `ok`: do not rename/reset anything back. Keep the promoted task branch and exact HEAD reachable; persist `task_id=N`, `needs_switch=True`; return `promotion_binding_unknown|promotion_binding_partial` with the task result/debt and actual branch/head. `_auto_switch_before_delivery` must refuse this durable quarantine before Git.
- Git promotion failure occurs before either session/task binding write. Return the helper state and leave DB ownership unchanged. This ordering makes “DB binding succeeded but Git rename failed” unreachable; the test makes the task-update seam raise if it is called.

## Partial-failure contract

| Failure point | Durable result | Git result | Recovery |
|---|---|---|---|
| Eligibility or Git promotion rejects | Session taskless; target task remains `new`/unowned | Original adhoc ref and HEAD unchanged | Correct input/target and retry promotion |
| Git promotion succeeds; session persistence clearly fails | No task mutation attempted | Reverse promotion to old adhoc name; if reverse is uncertain, preserve actual ref/head and return rollback failure | Retry after repairing durable branch identity |
| Session checkpoint succeeds; task CAS clearly returns `ok=False` with no committed side | Restore taskless lifecycle after reverse promotion | Old adhoc ref restored at exact HEAD | Retry promotion |
| Task update raises, returns `shadow_match=False`, or has any projection debt (`canonical_applied`, `candidate_write_failed`, rejection/mismatch) | Session remains bound/quarantined (`task_id=N`, `needs_switch=True`); delivery is refused | Promoted task ref remains at exact HEAD | Reconcile task projection; do not re-promote or discard |
| Final `needs_switch=False` persistence fails after task success | Session remains bound/quarantined as far as persistence permits | Promoted task ref remains at exact HEAD | Repair lifecycle persistence; work and task owner remain named |

Every result, including rollback failure, must expose an actual branch/head pair. The invariant is reachability of the pre-promotion HEAD by a named ref; metadata consistency is repaired after, never by deleting the ref.

## Existing live sessions and large histories

- The change is **retrospective**, not prevention-only: each of the 10 currently guard-blocked sessions can use `switch_worker_branch(..., promote_current=True)` after a fresh `new` task is created for its work. No DB migration or bulk mutation is required.
- It does not auto-repair them. Each promotion is an explicit per-session attribution decision.
- Nine current rows have `reason=conflict`. Promotion removes the circular task-binding block only; their subsequent `merge_worker` will still refuse on the real Git conflict until the branch is resolved.
- `frontend` (1182 commits), `memory-research` (1107), and `prompt-engineer` (1184) are not silently adopted. The explicit flag plus returned commit count/HEAD is the operator gate. A hard numerical ban is rejected because it measures history shape, not content risk, and would strand the same work again. Their later merge still faces conflict/ref/diff-budget controls.
- `hide-time-prefix` is now `content-noop`; it cannot enter promotion and can use the ordinary switch path.

## What is not touched

- No changes to `merge_worker`, `next_task_id`, schema-v2 merge finalization, receipts, commit-ref validation, or diff budget.
- No relaxation/removal of `branch_content_status`, the #103 content guard, or dirty-tree/idle locks.
- No use or reinterpretation of `force=True`.
- No prompt changes, schema migration, live-DB mutation, automatic bulk repair, or restart in this ticket.

## Test and mutation strategy

### Frozen controls/oracles

- Normal control committed at `f2f92b4f`:

  ```text
  /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_task_tracker_integration.py::test_t1_normal_complete_persists_null_done_control
  . [100%]
  1 passed in 2.60s
  ```

- Current RED oracle is commit `6ce2570f`. Earlier RED snapshots `983bbc5e`, `fcfa0083`, and `b50001d9` are superseded/excluded because the immutable oracle was deliberately expanded before/following Phase-2 review findings.
- RED command:

  ```bash
  /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q \
    tests/test_task_tracker_integration.py::test_t2_taskless_adhoc_deadlock_promotes_head_then_merge_succeeds \
    tests/test_task_tracker_integration.py::test_t2_promotion_binding_failure_restores_branch_and_preserves_head \
    tests/test_task_tracker_integration.py::test_t2_promotion_reservation_race_fails_claim_and_preserves_head \
    tests/test_task_tracker_integration.py::test_t2_promotion_unknown_binding_keeps_promoted_head_quarantined \
    tests/test_task_tracker_integration.py::test_t2_promotion_git_failure_never_binds_and_preserves_head \
    tests/test_task_tracker_integration.py::test_t2_promotion_rejects_done_target_without_moving_head \
    tests/test_task_tracker_integration.py::test_t2_promotion_rejects_force_combination_before_git \
    tests/test_mcp_stdio.py::test_t2_switch_worker_branch_forwards_explicit_promotion
  ```

  Current result: `11 failed in 3.49s`, exit 1. First missing-behaviour assertion:

  ```text
  assert promoted["ok"] is True, promoted
  E AssertionError: {'error': '1 commit(s) could not be verified in main (content-change) — merge_worker first or pass force=True', 'ok': False, 'waited_seconds': 0.0}
  ```

### Focused regressions after implementation

- Re-run the exact T1 and T2 commands above.
- Preserve the original #103 guard:

  ```bash
  /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_workspace.py::TestSwitchWorktreeBranch::test_real_unmerged_content_blocks_without_moving_or_creating_branch
  ```

- Run affected files as separate processes, never one full pytest process:

  ```bash
  /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_workspace.py
  /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_task_tracker_integration.py
  /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_mcp_stdio.py
  ```

- Compare the two frozen oracle files byte-for-byte with `6ce2570f` before accepting implementation.

### Required mutations

After the T2 command is green, mutate one production seam at a time. Each mutation command must use a fresh backup and include: `cp F F.bak`, pre-mutation marker count, one mutation, exact T2/T1 command, `mv F.bak F`, `touch F`, post-restore marker count, then a green repeat. Record the marker as production or mutant explicitly.

1. Remove/force-false the MCP `promote_current` payload → MCP forwarding test must fail.
2. Allow `promote_current && force` → force-combination test must fail before Git and keep HEAD.
3. Route promotion into `switch_worktree_branch`/reset instead of the dedicated helper → end-to-end HEAD/old-ref assertions must fail.
4. Relax target `status == "new"` → done-target test must fail.
5. Remove the atomic `require_unreserved` claim check → reservation-race test must fail.
6. Remove clear-failure reverse promotion/lifecycle restore → binding-failure test must fail.
7. Treat exception, `shadow_match=False`, `candidate_write_failed`, candidate rejection, or canonical-partial debt as success/rollback → quarantine parameter arms must fail because state or promoted HEAD disappears.
8. Let `_auto_switch_before_delivery` process `task_id != '' && needs_switch=True` → quarantine test must fail by moving the promoted branch.
9. Permit task binding after Git promotion rejection → Git-failure test's raising sentinel must fail.
10. Change normal complete terminal binding away from `task_id=''`, `needs_switch=1`, task `done`/owner NULL → T1 control must fail.

## Review decision inputs

- Planned production files/consumers: `app/mcp_stdio.py` public MCP contract; `app/routes/sessions.py` shared session lifecycle route; `app/workspace.py` Git refs/worktree; `app/tm.py` persistent task ownership; `app/manager.py` delivery/autoswitch; two test consumers.
- Author metadata: `fix-merge-deadlock`, Codex runtime, `gpt-5.6-sol` (live `list_agents` output).
- Risk floor: high — shared lifecycle gate plus persistent ownership and potential data loss.
- Strong oracle: frozen before implementation at `6ce2570f`; exact command exits 1 for missing promotion and covers reservation interleaving, all IA debt shapes, delivery quarantine, force-before-Git, and reporting metadata. T1 is a separate pre-existing-behaviour control, green at `f2f92b4f` by explicit approver requirement.
- Review route: Sol is the technical floor, but no additional Sol run is authorized; use one targeted Luna plan review and disclose that limitation.

## Plan review outcome

- Luna round 1: **NOT APPROVED** — three blocking findings (`needs_switch` was not a real quarantine, reservation eligibility was not atomic with claim, shadow projection debt could look successful) and two oracle suggestions (force-before-Git sentinel, promotion metadata assertions).
- All five findings were verified against current source and accepted. The T2 oracle was expanded and refrozen at `6ce2570f`; earlier RED commits are excluded above.
- Luna round 2: **APPROVED**, all prior findings fixed, no new blocking finding. Review evidence includes the exact updated-plan sentence at line 50 and is stored in `.orchestra/tasks/465/review-plan.md`.

## Tickets

### T1 — Freeze the normal `NULL + done` lifecycle control
- Files: `tests/test_task_tracker_integration.py`
- Test: `tests/test_task_tracker_integration.py::test_t1_normal_complete_persists_null_done_control` — committed GREEN control in `f2f92b4f` by explicit Phase-2 requirement; no missing production behavior exists to make RED.
- AC: `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/test_task_tracker_integration.py::test_t1_normal_complete_persists_null_done_control` is green; task is `done`/owner NULL and durable session is `task_id=''`/`needs_switch=1`.
- blocked-by: none

### T2 — Explicitly promote and bind committed taskless adhoc work
- Files: `app/mcp_stdio.py`, `app/routes/sessions.py`, `app/workspace.py`, `app/tm.py`, `app/manager.py`, `tests/test_mcp_stdio.py`, `tests/test_task_tracker_integration.py`
- Test: the eight-node T2 command in “Frozen controls/oracles” — committed RED in `6ce2570f`; exit 1 with `assert promoted["ok"] is True` receiving the existing `merge_worker first or pass force=True` refusal. The command has 11 failing cases because the unknown-binding test has four parameter arms.
- AC: the exact T2 command is green; the T1 command and #103 guard command are green; pre-promotion HEAD stays reachable under success, clear failure, Git-first failure, exception, canonical-partial, shadow failure, and shadow rejection; reservation interleaving cannot claim the task; quarantined binding cannot auto-switch on delivery; default switch still refuses unverified work; `done` target and `promote_current+force` reject before Git; MCP forwards/renders promotion and reports `previous_branch`, `head`, `commits_ahead`, `reason`; oracle files are byte-identical to `6ce2570f`.
- blocked-by: T1

# #248 T3 — adversarial implementation review (Opus, not Codex)

**Date:** 2026-08-13
**Reviewer:** Opus (`review248-t3`), acting as an explicitly authorised fallback for Codex.
**Why not Codex:** the Codex weekly pool is exhausted — `codex.primary.utilization = 97`
against a 95 threshold on 2026-08-13, so `codex_review` returns `weekly_quota_blocked`.
The orchestrator authorised the Opus fallback for T2 and T3. **This is not a Codex verdict
and must never be reported as "Codex approved".**

**Subject:** `git diff 089a85ea..e6958a20` — 7 production files
(`app/tm.py`, `app/db.py`, `app/routes/sessions.py`, `app/workspace.py`,
`app/merge_operations.py`, `app/routes/merge_operations.py`, `app/mcp_stdio.py`).
T1/T2 are context, not subject. Zero test files touched by the diff (verified).

**Baselines I ran myself:**

```
$ uv run python -m pytest -q tests/test_task_tracker_integration.py -k 'test_t3_'
13 passed, 10 deselected in 17.68s          (repeated 3x: 12.51s / 21.43s / 13.46s, no flake)

$ uv run python -m pytest -q tests/test_task_tracker_integration.py -k 'test_t3_ or test_t1_ or test_t2_'
21 passed, 2 deselected in 23.01s
```

Scratch repos and probe databases lived under `/home/kesha/orchestra/data/probe248/`
and were removed with `trash`. Every "no effect" claim below carries a permitting
control arm.

---

## [blocking] 1 — A task reservation has no release path on any UNKNOWN outcome, and the documented operator remedy makes it permanent

`app/tm.py:646` (`release_merge_finalization`) has exactly two callers:
`app/routes/sessions.py:1521` (Git provably did not reach the commit point) and
`app/merge_operations.py:1114` (in-process trailer reconciliation said "not reached").
`resolve_operation` (`app/merge_operations.py:267`) does not touch reservations, and neither
does `recover_orphan_operations` (`app/merge_operations.py:1071`).

The implementer reported the non-release honestly as a KNOWN GAP. Assessed blast radius: it
is worse than "someone deletes a row by hand" — the row makes the task **permanently
unassignable and permanently un-completable**, and the state it leaves behind is
*advertised as available*.

Three independent consumers refuse a reserved task (measured, `p1`):

```
A) reservation taken for op-A: op-A
B) rows in tm_task_reservations after 'restart': [{'task_id': 1, 'operation_id': 'op-A', 'kind': 'complete'}]
C) hostile arm (reservation still present):
   retry merge complete (new operation_id op-B): REFUSED -> ValueError: task 1 is reserved by operation op-A
   bind task to another worker:                  REFUSED -> ValueError: task #1 is reserved
   spawn a worker on the task (publish_ready_session): REFUSED -> ValueError: task #1 is reserved
D) PERMITTING CONTROL ARM — release the reservation, repeat the SAME calls:
   retry merge complete (new operation_id op-C): OK
```

Refusal sites: `app/tm.py:629` (`_reserve_task`), `app/tm.py:518` (`bind_task_to_session`),
`app/db.py:1273` (`publish_ready_session`). `app/tm.py:274` additionally refuses to garbage-collect
the row.

### Failure scenario 1a — the operator follows the tool description and locks the task shut

`resolve_merge_operation`'s own MCP description says it is *"the ONLY way to unblock merges
for a worker held by such an operation"*. `_reopen_for_finalization`
(`app/merge_operations.py:426`) requires `resolved_at IS NULL`. So resolving a
`PARTIAL / commit_point=REACHED / finalization_stage=PENDING` operation permanently disables
the replay that would have closed the task and dropped the reservation (`p5`):

```
1) state: PARTIAL | commit_point: REACHED | finalization_stage: PENDING
2) PERMITTING CONTROL ARM — replay BEFORE anyone resolves it:
   _reopen_for_finalization -> True
3) HOSTILE ARM — the operator does the documented thing first:
   resolve -> 200
   _reopen_for_finalization -> False   (WHERE resolved_at IS NULL)
   task: in_progress | worker: w1 | reservations: [{'task_id': 1, 'operation_id': 'op-partial'}]
```

Inputs/state: merge committed to `main`, the tm stage never ran, the human reconciles the
operation the way the tool tells them to. Outcome: the merge is in `main`, the task stays
`in_progress` forever, and no worker can ever be bound to it or complete it again.

### Failure scenario 1b — `kill_worker` turns the wedge into a *silent* one

`release_session_task_binding` (`app/tm.py:717`) requeues an orphaned `in_progress` task to
`new` and clears `worker_session_id`, but ignores `tm_task_reservations` (`p3e`):

```
=== archive of a worker whose task is RESERVED by a stuck merge ===
  -> #5 status=new worker=None | reservation rows: [{'task_id': 5, 'operation_id': 'op-stuck', 'session_id': 'wR'}]
```

The task now appears in `task_list` as an ordinary unassigned `new` task. Every
`spawn_worker`/`bind` against it fails with `task #5 is reserved` and an operation id that no
longer exists anywhere in the UI. This is the worst shape of the bug: the wedge is invisible
until an orchestrator tries to use the task.

### Why this counts as "inability to merge"

The reservation is taken at `app/tm.py:556` *before* Git and released only on the two happy
exits. Any UNKNOWN outcome — restart (see finding 2), `merge execution failed`, unverified
rollback, failed trailer reconciliation — leaves it. A restart mid-merge is a routine event in
this project, not an exotic crash.

**Suggested shape of a fix (not prescriptive):** make `resolve_operation` release the
reservations named in `finalization_json` as part of resolving, since that is precisely the
"a human established what really happened" moment. Anything that leaves the only remedy as
manual SQL against `tm_task_reservations` will be discovered by an orchestrator at 3am with a
task that says `new`.

---

## [blocking] 2 — Plan step 8 is not implemented: a restart between Git and the checkpoint never runs trailer reconciliation

`plan.md` step 8: *"Restart переводит orphan `APPLYING` с `commit_point=REACHED` обратно в
`PARTIAL + PENDING`. Orphan `PREPARED` проходит trailer reconciliation шага 4, а не
безусловный `UNKNOWN`."*

`recover_orphan_operations` (`app/merge_operations.py:1071`) is **unchanged by this diff**. It
sets every orphan `RUNNING` row to `state='UNKNOWN', commit_point='UNKNOWN'` and never looks
at `finalization_stage`. `reconcile_prepared_commit` (`app/merge_operations.py:508`) has
exactly one caller — `_recover_lost_checkpoint` (`app/merge_operations.py:1102`) — reachable
only from inside the same live `_run_operation`, i.e. only when the SQLite checkpoint write
itself raised while the process stayed up.

Measured with the real state-machine functions (`p2`):

```
1) mid-merge: RUNNING | finalization_stage: PREPARED
2) --- SERVER RESTART ---
   after restart recovery: state: UNKNOWN | commit_point: UNKNOWN | finalization_stage: PREPARED
   reservation rows: [{'task_id': 1, 'operation_id': 'op-restart'}]
3) operator does the documented thing: resolve_merge_operation
   resolve -> 200 | resolved_at set: True
   reservation rows after resolve: [{'task_id': 1, 'operation_id': 'op-restart'}]
4) the worker retries its merge with a fresh operation id:
   REFUSED -> ValueError: task 1 is reserved by operation op-restart
   task status: in_progress | worker_session_id: w1
5) PERMITTING CONTROL ARM: hand-delete the reservation row, retry the SAME call
   OK — merge may proceed
```

Failure scenario: worker merges `task_outcome='complete'`; Git creates the squash commit
carrying `Orchestra-Operation: <uuid>`; the user restarts Orchestra (a routine, documented
operation that "обрывает активные ходы агентов") before the checkpoint lands. All the evidence
needed to recover is on disk — `finalization_stage='PREPARED'`, `target_before`,
`expected_tree`, and the trailer in `main` — and none of it is consulted. Result: the merge is
in `main`, the operation is UNKNOWN, the task is never closed, and finding 1 wedges it.

This is the single largest gap between the plan and the implementation, and it sits on the
exact path the ticket was written to protect. Note that the frozen oracle
(`test_t3_first_post_git_checkpoint_loss_recovers_by_exact_trailer`) covers only the
*in-process* checkpoint loss, so the suite is green with this gap wide open.

---

## [blocking] 3 — This diff turns a previously green test red, and it is not on the integrator's accounted list

```
$ uv run python -m pytest -q tests/test_mcp_stdio.py tests/test_merge_operations.py \
    tests/test_merge_stuck.py tests/test_identity_drift.py tests/test_merge_ref_gate.py \
    tests/test_tm.py tests/test_tm_sync_loop.py
FAILED tests/test_mcp_stdio.py::test_task_get_and_update_fall_back_to_authoritative_scope
1 failed, 161 passed in 48.27s
```

```
E   app.mcp_stdio.ApiToolError: task_update: status 'done' is owned by the platform — ...
app/mcp_stdio.py:1813: ApiToolError
```

Causality established by mutation, not by inference. Anchor uniqueness asserted inside the
mutating command; marker counted before the run and after the restore; restored file
`touch`ed; green repeat performed:

```
anchor BEFORE = 1
MUTANT-B present: 1
1 passed in 5.32s                      <- gate removed  => test green
anchor AFTER restore = 1; MUTANT-B left: 0
FAILED tests/test_mcp_stdio.py::test_task_get_and_update_fall_back_to_authoritative_scope
1 failed in 5.60s                      <- gate restored => test red
```

The integrator's message accounts for four `TestAtomicSpawnLifecycle` failures (T1) and
`tests/test_routes_surface.py` (#231 branch debt). **This one is neither** — it is caused
solely by `_reject_lifecycle_status` at `app/mcp_stdio.py:1811`, introduced in this diff.

The implementer flagged the conflict in `docs/workers/impl248-t3.md` and correctly refused to
act: `tests/test_mcp_stdio.py` asserts that `task_update(status="done")` succeeds, the frozen
oracle `test_t3_agent_task_tools_cannot_override_platform_lifecycle` asserts that it raises.
Both test files are immutable to the worker. This is a decision the orchestrator must take and
record — the two oracles are genuinely contradictory, and merging as-is puts `main` in the
exact state #216 measured: red for a reason nobody remembers, so the next worker cannot tell
their own breakage from inherited breakage.

I am reporting it as blocking because it needs an owner before merge, not because the
implementation is wrong. My own reading is that the new oracle expresses the intended
contract and the old assertion is the stale one — but changing it requires explicit
orchestrator authorisation for a test-layer edit.

---

## [suggestion] 4 — Trailer reconciliation cannot find our own commit once the target has moved on

`app/merge_operations.py:545`: `if len(commits) != 1 or commits[0] != head: return None`.

Probed against real Git repositories (`p4`):

| case | outcome |
|---|---|
| A our commit, trailer + parent + expected tree | `reached=True` |
| B target untouched | `reached=False` (releases the reservation — correct) |
| C another operation's trailer on target | `None` → UNKNOWN (correct refusal) |
| **D our commit landed, a concurrent merge landed on top** | **`None` → UNKNOWN** |
| E unrelated-history fallback, `expected_tree=''` | `reached=True` on trailer + parent alone |
| F trailer present twice | `None` → UNKNOWN |
| G target force-reset back to `target_before` | `reached=False` |
| **H a real merge commit on target** | **`None` → UNKNOWN** |

For case D the probe also shows the commit is trivially findable:

```
D) OUR commit landed, then a CONCURRENT merge landed on top of it
  our commit is provably in main: None (-> stays UNKNOWN)
     but `git log --grep` finds it in one call: f8adb45150b7 == f8adb45150b7 -> True
```

Failure scenario: the checkpoint `UPDATE merge_operations` fails with `database is locked` —
which is by definition a moment of write contention, i.e. exactly when another worker's merge
is likely to take the repo lock we just released. Between our commit and
`_recover_lost_checkpoint`, that merge lands. Our commit is in `main`, its trailer intact, and
the operation is declared UNKNOWN anyway, taking the finding-1 wedge with it. Case H is the
same shape via the laptop contour's non-squash merges.

Suggested direction: locate the commit by
`git log --format=%H --grep="^Orchestra-Operation: <id>$" <target_before>..<target_branch>`,
require exactly one hit, then apply the existing parent/tree assertions to that hit. That
keeps every piece of evidence and drops only the incidental "the range must contain exactly
one commit" requirement.

Case E (`expected_tree=''` for unrelated-history cherry-pick) I deliberately did **not** flag:
the trailer is a server-minted UUID that the worker cannot know in advance, T2 rejects a
worker-supplied `Orchestra-Operation:` key, and case C shows a foreign trailer is refused. The
deviation is sound.

---

## [suggestion] 5 — `save_prepared_finalization` cannot fail loudly, while its post-Git twin can

`app/merge_operations.py:465` issues the pre-Git journal `UPDATE` and ignores `rowcount`.
`checkpoint_merge_commit` at `app/merge_operations.py:475` — the same statement shape, ten
lines below — raises `RuntimeError` on `rowcount != 1`.

Failure scenario: the `merge_operations` row is absent or the `operation_id` does not match
(any future refactor that changes when the row is inserted). `prepare()` returns successfully,
`merge_worktree_to_main` proceeds to commit, the checkpoint then raises "vanished before its
commit checkpoint", `_recover_lost_checkpoint` finds `finalization_json` empty and returns
`raw` unchanged → UNKNOWN. The one write whose entire purpose is "recovery must have
something to read" is the one write that cannot report that it wrote nothing.
Symmetry here is cheap: same `rowcount != 1` guard.

---

## [suggestion] 6 — `POST /api/sessions/{name}/merge` performs the v2 lifecycle with no journal and no trailer

`app/routes/sessions.py:1703` forwards `req` verbatim to `execute_merge_session`.
`operation_id` is read at `app/routes/sessions.py:1236` and every durability step is gated on
it: `save_prepared_finalization` (`if operation_id`), `checkpoint_merge_commit`
(`if operation_id`), and `merge_worktree_to_main(operation_id=...)` — which is what appends the
`Orchestra-Operation:` trailer at `app/workspace.py:994`.

Failure scenario: a caller (dashboard, script, `curl`) posts
`{"merge_schema_version": 2, "task_outcome": "complete"}` to this route with no
`operation_id`. The platform closes the task, deducts the prepayment and moves the worker —
with no PREPARED journal, no checkpoint, and a squash commit carrying no trailer, so nothing
about that merge is recoverable if the DB stage fails. The mitigation today is that no known
caller sends `merge_schema_version` on this route (grep of `static/` finds none), so this is
latent rather than live. Refusing `merge_schema_version=2` without `operation_id` would make
the durability guarantee unconditional instead of best-effort.

---

## [suggestion] 7 — The surviving reservation-collision mutant is an oracle hole, not a decorative guard

The implementer reported this honestly; I confirmed both halves.

The mutant survives (`_reserve_task`'s collision `raise` → `return`, anchor asserted unique,
marker counted before and after, file restored and `touch`ed, green repeat run):

```
anchor BEFORE = 1
MUTANT-C present: 1
21 passed, 2 deselected in 18.69s      <- guard disabled, suite still green
anchor AFTER = 1; MUTANT-C left: 0
21 passed, 2 deselected in 23.01s      <- restored, green repeat
```

But the guard is genuinely load-bearing — probe `p1` case C/D above shows a second operation
is refused with the reservation present and permitted without it. So this is *"the oracle
never exercises a second operation reserving a task the first one holds"*, not *"the guard
does nothing"*. Worth a new test (a new file, not an edit to a frozen one) since disabling the
guard is exactly what manufactures the finding-1 wedge: with `return` instead of `raise`,
op-B proceeds believing it owns the reservation and its `DELETE ... AND operation_id='op-B'`
removes nothing.

For contrast, the neighbouring guard **is** defended. `if others:` in
`prepare_merge_finalization` (`app/tm.py:556`), mutated to `others = []`:

```
anchor count BEFORE = 1
marker MUTANT-A present: 1
FAILED tests/test_task_tracker_integration.py::test_t3_complete_rejects_an_existing_second_live_binding_before_git
1 failed, 12 passed, 10 deselected in 14.40s
anchor count AFTER restore = 1; MUTANT-A left: 0
13 passed, 10 deselected in 12.44s     <- green repeat
```

---

## [suggestion] 8 — Heir election hands a `done` task to a live session

`app/tm.py:717`. The heir branch updates `worker_session_id` without consulting
`t.status`; only the no-heir branch inspects it (`p3c`):

```
=== archive with a DONE task still bound (can the heir resurrect it?) ===
  after archive: #3 status=done worker=wHeir   (heir wHeir exists)
```

No status resurrection — `done` stays `done`, which is what the hunt asked about and it holds.
But a closed task acquires a live worker binding, which is a state nothing else in the system
produces (`finalize_merge_outcome` NULLs `worker_session_id` on completion). Reachable when a
human closes a task on the dashboard while a worker is still bound to it. Cosmetic today;
one `AND t.status != 'done'` in the heir lookup keeps the invariant honest.

---

## [question] 9 — `task_outcome` is optional, so the whole T3 lifecycle is opt-in per call

`app/mcp_stdio.py:1474`: `task_outcome: str = ""`, and the capability preflight at
`app/mcp_stdio.py:1489` runs only `if task_outcome:`. An agent on the **new** MCP that omits
`task_outcome` sends a v1 body and gets `LEGACY_MERGE_CONTINUE` — the task is never closed.

This is fail-safe (it degrades to today's behaviour, never to a false close), and by the
project's own promptable-rule test both failure directions land on "today", so a prompt-level
instruction is legitimate here. I raise it only because the plan's T3 AC says *"required v2
outcome"* and the shipped shape is *optional* v2 outcome — the difference decides whether
#248's headline benefit arrives on rollout or waits for T4's prompt changes. Worth stating
explicitly in the merge note rather than discovering it as "the tasks still don't close".

Related and deliberate: `_reject_lifecycle_status` (`app/mcp_stdio.py:1811`) is a **client-side**
guard. `PATCH /api/tm/tasks/...` still accepts `status: done` from anyone, so an agent on an
old MCP process — the normal state for hours after merge — can still close a task by hand. The
plan scopes the ban to "agent-facing `task_create/task_update`", so this matches the plan; it
is simply worth knowing that the invariant is advisory until every agent reconnects.

---

## Ruled out (checked, not findings)

- **First post-Git DML.** `prepare()` is called at `app/workspace.py:1486`; the first
  mutation flags are set at `app/workspace.py:1509` and `1530`. The journal is written under the
  repo lock before any ref moves. The frozen oracle asserts the first mutating statement after
  the target moved is `UPDATE MERGE_OPERATIONS` containing `COMMIT_POINT` and
  `FINALIZATION_STAGE`, over the `db`/`tm`/`operations` connection factories — I ran it green
  and did not re-derive it.
- **`prepare()` failure does not commit.** `prepare_failed` short-circuits both the
  cherry-pick and squash branches; `mutation_started` stays false → `commit_point='not_reached'`
  → the reservation is released at `app/routes/sessions.py:1521`.
- **Transaction boundary claim holds.** AST check: `update_task` and `auto_deduct_prepayment`
  take the caller's connection and never commit or open their own; `link_commits_to_task` opens
  its own connection but is called *before* `BEGIN IMMEDIATE`, as documented. Injecting a
  failure inside the transaction (`p3a`) rolls back everything, and the permitting arm applies
  it:
  ```
  before: #1 in_progress worker=wA | #2 new worker=None | reservations: 2
    finalize raised -> RuntimeError: injected mid-transaction failure
  after failure: #1 in_progress worker=wA | #2 new worker=None | reservations: [complete, assign]
  PERMITTING CONTROL ARM: same call, no injected failure:
    -> #1 done worker=None | #2 in_progress worker=wA | reservations: []
    idempotent second run: True -> #1 done worker=None | #2 in_progress worker=wA
  ```
- **No deadlock introduced.** Every writer uses `BEGIN IMMEDIATE` or opens with a write as its
  first statement; `busy_timeout=5000` and WAL are set in `app/db.py:48`. `archive_session`
  passes its own connection into `release_session_task_binding` rather than opening a second
  one, so there is no self-blocking nested writer.
- **Archive is a genuine no-op for a scope with no task project** (`p3b`): `tm_tasks` rows
  byte-identical before/after (`True`). The last-worker requeue works (`p3d`: `#4 new / worker=None`).
- **Deleted symbols have zero readers.** `link_commits_to_tasks` and
  `inspect_candidate_task_refs`: no hits in `app/`, `tests/`, `static/`, `pipelines/`, `docs/`
  outside this ticket's own notes, and no dynamic dispatch (`getattr` on the `tm`/`workspace`
  modules returns nothing).
- **New MCP against a v1 server refuses before POST.** `main`'s route returns
  `{"capability": "operation-v1", "schema_version": 1}` with neither `capabilities` nor
  `merge_schema_version`, so the client's check at `app/mcp_stdio.py:1514` fails closed. The
  reverted capability string is therefore not a hazard: T1/T2/T3 are all on this branch and
  none of them is in `main` (`git log --oneline main..HEAD`), so a "T2-only server" cannot
  exist in production.
- **Foreign and duplicated trailers are refused** (`p4` cases C and F) — no wrong commit can be
  claimed by an operation that did not create it.
- **Concurrency.** `-k test_t3_` run three times: 13 passed each time, no flake.
- **Additive migration is mixed-runtime safe.** `finalization_stage` / `finalization_json` are
  `NOT NULL DEFAULT`, applied in `_migrate` (`app/db.py:947`) only at process start; the
  currently running old server neither reads nor writes them. No new required request field is
  introduced on the route — `merge_schema_version` is optional and its absence selects the
  legacy branch.

---

## Verdict

CHANGES REQUESTED — 3 blocking

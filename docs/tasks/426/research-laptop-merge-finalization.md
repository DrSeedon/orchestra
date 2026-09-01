# #426 — merge finalization raises `ValueError: <N> not found`

## Question

- **Context:** the post-commit accounting stage shared by a fresh `merge_worker` call and a
  same-operation replay: `apply_merge_finalization` → `finalize_merge_outcome`, with the
  process-global IA task owner configured as in application lifespan.
- **Change under test:** no production change in Phase 1. The claim under test is that an
  operation-time legacy/canonical task gap reaches one of the three candidate `"<N> not found"`
  throws and leaves finalization after the Git commit point.
- **Baseline:** a task present in both owners, as exercised by
  `tests/test_task_completion_421.py`, versus a legacy task created after the canonical snapshot.
- **Measurable outcome:** an isolated run must reproduce exactly `ValueError: 399 not found`,
  identify the throwing source line by traceback, show a non-`None` process IA context, and leave
  the production `sessions` row count unchanged.

## Hypotheses considered

1. **Leading hypothesis:** the canonical commit-link reader cannot find the task because the
   failed merge operations predate the corresponding canonical `task.created` event.
   **Falsifier:** an operation-time canonical state exists before the merge operation, or the
   production-shaped stand reaches a different throw site.
2. **Alternative:** the failure comes from `api_get_task`/`resolve_task_ref` during final task
   status update. **Falsifier:** the traceback fails earlier in commit linking and never enters
   `_apply_finalization_task_update` or `api_get_task`.
3. **Alternative:** the failure comes from legacy `api_update_task`. **Falsifier:** the traceback
   enters `_RuntimeTaskStore` and `TaskStore._find_state`; the legacy prevalidated updater returns
   an `ok=False` DTO rather than this bare exception [1][2].
4. **Already refuted; not rerun:** legacy and canonical `project_id` differ. Both are
   `orchestra` for #399/#400/#410 [1].
5. **Already refuted as a reproduction method; not rerun:** a bare Python process without IA
   context. `_ia_context()` is `None` there and selects the legacy path [1].

## Findings

### F1 — the defect is reproduced in the process-global IA path

`uv run python docs/tasks/426/repro_stand.py` exited `0` after detecting the expected defect [4].
The stand freezes canonical before creating legacy #399, wraps the raw `TaskStore` in the same
`_RuntimeTaskStore` facade used by `KnowledgeRuntime`, enters
`ia_process_task_store_mode(mode="canonical")`, and calls the route-level
`apply_merge_finalization`.

Relevant verbatim output:

```text
ISOLATED_DB=/tmp/orchestra-426-.../orchestra.db
ISOLATED_CANONICAL=/tmp/orchestra-426-.../canonical/tasks
ISOLATED_PROJECTION=/tmp/orchestra-426-.../task-current.db
APP_ROOT=/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/app
PRECONDITION_CANONICAL_398=398
PRECONDITION_CANONICAL_399_MISSING=True
PRECONDITION_LEGACY_399=399
IA_CONTEXT_BEFORE=None
IA_CONTEXT_DURING=_IATaskStoreContext(mode='canonical', store=<app.ia.runtime._RuntimeTaskStore object at ...>)
REPRO_EXCEPTION=ValueError: 399 not found
THROW_FRAME=.../app/ia/task_store.py:583:_find_state
THROW_FRAME_VERIFIED=True
PROD_SESSIONS_BEFORE=583
PROD_SESSIONS_AFTER=583
PROD_SESSIONS_UNCHANGED=True
PROD_CANONICAL_SHA256_BEFORE=d0ab4ddb6e99b18e8e030557c07fd1fca3a89ce46f345b1749c2dc3e03316cf7
PROD_CANONICAL_SHA256_AFTER=d0ab4ddb6e99b18e8e030557c07fd1fca3a89ce46f345b1749c2dc3e03316cf7
PROD_CANONICAL_UNCHANGED=True
HEALTHY_CONTROL=True
```

The script asserts the *resolved* `raw_store.canonical_root` and `projection_path`, verifies the
three store preconditions above, and machine-checks the final traceback frame rather than merely
printing requested paths. The production canonical digest covers every non-`.git` file under
`~/.local/state/orchestra/knowledge-v1/canonical` before and after the run [4].
The same process-global route then runs a positive control with #399 present in both owners and a
non-empty commit list; linking and completion succeed in both stores (`HEALTHY_CONTROL=True`) [4].

**Confidence: CONFIRMED** — direct, reproducible measurement on the current worktree with the
production facade and process-global context (evidence tier 1).

### F2 — the exact throw is `app/ia/task_store.py:583`

The reproduced traceback is [4]:

```text
app/routes/sessions.py:1642  apply_merge_finalization
app/tm.py:1233              finalize_merge_outcome
app/tm.py:2399              link_commits_to_task
app/ia/runtime.py:194       _RuntimeTaskStore.link_commits_to_task
app/ia/task_store.py:1165   TaskStore.link_commits_to_task
app/ia/task_store.py:583    raise ValueError(f"{ref} not found")
ValueError: 399 not found
```

`TaskStore.link_commits_to_task` calls `_find_state(task_ref, project_id)` at line 1165.
`_find_state` filters on both `display_number` and `project_id`; an empty match list takes line
583. The `Ambiguous` branch is line 581 and was not taken [2].

This also narrows the previously assembled call chain: the observed bare error occurs in the
commit-link dictionary at `finalize_merge_outcome:1232-1235`, before
`_apply_finalization_task_update:1184` can run. The other two candidate bare throws in
`api_update_task` and `api_get_task` are absent from the traceback [2][4].

**Confidence: CONFIRMED** — traceback plus current source agree on the exact statement
(evidence tiers 1 and 2).

### F3 — the search misses because canonical creation followed each initial failure

Read-only production measurements [3][7]:

| Task | Initial failing tool result | First current canonical `task.created` | Relation |
|---|---|---|---|
| #399 | log 508291, `2026-08-26T08:48:55.872038+00:00` | `2026-08-26T09:00:56.326016+00:00` | canonical event is 12m00.454s later |
| #400 | log 508303, `2026-08-26T08:49:20.216932+00:00` | `2026-08-28T10:38:24.862640+00:00` | canonical event is about 49h49m later |
| #410 | log 510918, `2026-08-27T06:29:30.931165+00:00` | `2026-08-28T10:38:51.332702+00:00` | canonical event is about 28h09m later |

All three operation records contain `POST_COMMIT_PARTIAL` with respectively
`ValueError: 399 not found`, `400 not found`, and `410 not found`. Their payloads use
`project_id="orchestra"` and commit keys equal to the task number [3].

The read-only evidence script finds the initial `merge_worker` tool-result log containing both the
operation UUID and exact error, then reconstructs the immutable canonical Git snapshot immediately
preceding that *failure timestamp*, rather than the earlier operation creation timestamp:

```text
#399 snapshot=f69f996c... state_count=246 target_matches=0 current_matches=1
#400 snapshot=f69f996c... state_count=246 target_matches=0 current_matches=1
#410 snapshot=44616ff0... state_count=248 target_matches=0 current_matches=1
```

Each operation row simultaneously reports `commit_point=REACHED`, `state=PARTIAL`, and the exact
bare error. Each failure-time Git snapshot contains hundreds of other orchestra task states, so
zero target matches is not an empty-store artifact. `_RuntimeTaskStore._changed` synchronously
calls `_record_task_head`, whose current
owner commits each successful task generation at `app/ia/runtime.py:642-661`; therefore a
successful canonical task creation before the failure would be present in that preceding Git
snapshot [2][7].

The 31.08 observations are not three fresh operation identities. The tool-result logs reuse the
same three UUIDs above: #399 at log 557586, #400 at 557597/557622, and #410 at 557628/557634.
Those later outputs repeat the stored `POST_COMMIT_PARTIAL` after current canonical matches became
`1/1/1`; they do not prove that a new healthy dual-owner merge entered `_find_state` and failed.
This distinction explains why a current data scan finds all three numbers while the initial
failure-time snapshots do not [7].

Current presence does not prove presence at the initial failure. For #399 it is stronger counter-evidence:
current canonical #399 has stable ID `d6fa0c9c-e1a1-42c5-944f-6c9e5fe15df4` and the title of a
different fan task, while legacy row id 923 is the `kb-extract` task. This is the known #399
semantic collision recorded by the task-storage KB [5]. #400 and #410 now have matching titles,
but their only `task.created` events still postdate the initial failing tool results [3][7].

**Confidence: CONFIRMED** — the failing tool-result logs and immutable canonical Git snapshots are
independent direct measurements taken on the two sides of each throw (evidence tier 1).

### F4 — existing completion coverage does not exercise this seam

`uv run python -m pytest -q tests/test_task_completion_421.py` returned `4 passed in 1.32s`; the
production `sessions` counter stayed `583→583` [6].
That file creates the legacy task before `ia_task_store_mode` migrates its canonical snapshot,
uses a ContextVar-local raw store rather than the lifespan facade, and supplies `commits={}`.
Therefore `finalize_merge_outcome` never calls `link_commits_to_task` for a missing candidate.
The repository-wide autouse fixture `tests/conftest.py:51-66` replaces `db.DB_PATH` with
`tmp_path/orchestra.db`, exports the same override, and wraps `sqlite3.connect` with a guard that
raises on the production path [6].

**Confidence: CONFIRMED** — named test output plus direct inspection of lines 42–65 and the payload
factory at lines 27–39 (evidence tiers 1 and 2).

## Counter-evidence and limitations

- A stand copied from *current* canonical state would not reproduce the historical absence for
  #400/#410; the current event ledger shows those records were added after the failed operations.
  Current-state presence therefore lowers confidence only in claims about the present store, not
  in the initial failure-time causal ordering.
- No fresh post-28.08 operation with the task present in both owners was found among these three
  incidents. The positive control succeeds, so recurrence on the current dual-owner path remains
  unproven; Phase 2 must not assume the general finalizer is still broken without the real-worker
  acceptance probe.
- The stand reconstructs the measured owner ordering with one synthetic task; it proves the
  finalizer seam after the receipt guard, not receipt validation or persistence of a new merge
  operation. `operation_id=""` deliberately bypasses the receipt guard. Independent persisted
  operation rows prove that the three historical cases had already reached
  `commit_point=REACHED/state=PARTIAL` [3][7].
- The first pilot was excluded: its pre-count command used a missing `.venv/bin/python`, and an
  unguarded editable install resolved `app` from the main checkout. The committed stand now inserts
  its own worktree root and fails if `app.__file__` resolves elsewhere; the accepted run prints the
  worktree `APP_ROOT` above [4].
- The Phase-1 result diagnoses the failure but does not select remediation. A silent legacy-only
  fallback would violate canonical ownership; auto-creating the missing canonical record during
  finalization must also define behavior for a number already occupied by another stable task
  (the #399 case).
- Luna review Round 1 confirmed the exact throw and called the isolation and historical causality
  under-proven. Both blocking findings were accepted: the stand now asserts actual store paths,
  preconditions, throw frame and the full production canonical digest; the historical claim now
  uses immutable pre-operation Git snapshots. The review question about receipts is resolved by
  narrowing the stand claim to the finalizer seam [8].
- Luna Round 2 confirmed all isolation/scope fixes but correctly rejected the use of
  `merge_operations.created_at` as a proxy for the later throw. After the two-round prose ceiling,
  the evidence script was re-anchored to exact failing tool-result timestamps; no third review was
  run [8].

## Affected files, risks, and edge cases for planning

- `app/tm.py`: `finalize_merge_outcome` and the canonical-first link/update orchestration.
- `app/ia/task_store.py`: `_find_state` and `link_commits_to_task`; changing absence semantics here
  affects every canonical consumer, not just merges.
- `app/routes/sessions.py` and `app/merge_operations.py`: post-commit retry/blocking contract and
  `POST_COMMIT_PARTIAL` reporting.
- `app/ia/runtime.py` is a consumer in the reproduced stack but outside the approved edit boundary;
  Phase 2 must avoid depending on a change there.
- Required edge cases: legacy-only task with free canonical number; legacy-only task whose number is
  occupied by another canonical stable ID (#399); replay after commit linking but before status
  completion; multiple commit refs where one task is missing; concurrent canonical head advance;
  and idempotent same-operation replay.
- Data/lifecycle risk is high: accepting the wrong same-number canonical task silently links commits
  and completion to another task; preserving the current exception leaves a committed merge and a
  blocked operation. Architecture must be discussed before implementation.

## Sources

1. Task card `task_get("426")`, opened in full on 2026-09-01 — supplied call chain, three candidate
   throws, two rejected hypotheses, and isolation requirement. Evidence tier 2 (primary task spec).
2. Current source: `app/tm.py:1184-1245,2198-2313,2379-2405`,
   `app/ia/runtime.py:105-199`, `app/ia/task_store.py:571-583,1120-1166`, and
   `app/routes/sessions.py:1624-1643`. Evidence tier 2 (primary source).
3. Read-only query of `/mnt/data/Projects/Python/orchestra/data/orchestra.db` tables
   `merge_operations`/`tm_tasks`, plus JSON parsing of canonical `state.json` and event files under
   `/home/maxim/.local/state/orchestra/knowledge-v1/canonical/tasks`; executed 2026-09-01.
   Evidence tier 1 (direct measurement).
4. `docs/tasks/426/repro_stand.py`; command
   `uv run python docs/tasks/426/repro_stand.py`, RC=0, output reproduced line 583 and production
   `sessions` 583→583. Evidence tier 1 (direct measurement).
5. `docs/kb/task-storage-architecture.md`, established #406 collision inventory. Evidence tier 2
   (project canonical memory linked to its measurement report).
6. `uv run python -m pytest -q tests/test_task_completion_421.py` →
   `4 passed in 1.32s`, production `sessions` 583→583; source
   `tests/test_task_completion_421.py` and isolation fixture `tests/conftest.py:51-66`.
   Evidence tiers 1 and 2.
7. `docs/tasks/426/operation_time_evidence.py`; command
   `uv run python docs/tasks/426/operation_time_evidence.py`, RC=0. It reads SQLite with
   `mode=ro`, locates initial failing tool-result logs 508291/508303/510918, archives the canonical
   Git revisions immediately preceding those failure timestamps, and found target matches `0/0/0`
   then `1/1/1` at current HEAD. It also records later same-UUID observations on 31.08. Evidence
   tier 1.
8. `docs/tasks/426/review-research-laptop-merge-finalization-luna.md`, Luna Rounds 1–2 — exact throw accepted; isolation,
   baseline safety and receipt-scope findings fixed; the Round 2 timestamp blocker was accepted and
   fixed after the prose ceiling. Last reviewer verdict remains not approved because no third round
   is permitted. Evidence tier 3 (adversarial secondary review).

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Apparently the traceback is better isolated than the data store 🙃. I reproduced the failure with RC=0: `ValueError: 399 not found` reaches [`task_store.py:583`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/app/ia/task_store.py:583) through the commit-link path, and sessions stayed `583→583`. However, canonical-store isolation and the historical causal claim are not proven sufficiently.

## Findings (blocking/suggestion/question)

### blocking

blocking: The stand verifies only [`db.DB_PATH`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/repro_stand.py:59). It passes temporary canonical paths but never verifies the actual `raw_store.canonical_root` or `raw_store.projection_path`; printing the requested path is not proof of the resolved write target. The sessions count check also cannot detect canonical writes or updates to existing rows. This does not satisfy the no-production-write requirement.

### blocking

blocking: The cited #421 baseline test writes through `init_db()` and `_conn()` at [`test_task_completion_421.py:13`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/tests/test_task_completion_421.py:13) and [`test_task_completion_421.py:14`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/tests/test_task_completion_421.py:14), with no isolation visible in the reviewed file. Unless an external fixture guarantees a temporary `ORCHESTRA_DB_PATH`, the command cited at [`research.md:110`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/research.md:110) mutates production task data.

### question

question: F3 proves only that a deliberately missing canonical task is sufficient to produce the exception. The claim that this explains all three historical failures relies on an external production query and event parsing described at [`research.md:160`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/research.md:160), which is not part of the reviewed evidence. A later `task.created` timestamp does not alone prove operation-time absence without establishing event-ledger completeness and timestamp semantics; the KB entry at [`task-storage-architecture.md:5`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/kb/task-storage-architecture.md:5) is not independent evidence.

### suggestion

suggestion: Add explicit preconditions that canonical contains the predecessor, does not contain `399`, and the isolated legacy store does contain `399`. The stand currently accepts only the exception text at [`repro_stand.py:124`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/repro_stand.py:124), and does not machine-check that the traceback contains line 583.

### question

question: The stand uses `operation_id=""` and a synthetic commit hash at [`repro_stand.py:104`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/repro_stand.py:104), which bypasses the receipt guard in [`sessions.py:1638`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/app/routes/sessions.py:1638). This reproduces the finalizer call, but not a persisted post-commit operation or replay. Either narrow the claim to the finalizer seam or add an isolated valid receipt setup.

## Verdict

❌ Not accepted as-is. Conclusion (1) is reproduced and correctly locates the throw before `_apply_finalization_task_update`; conclusions (2) and (3) need stronger causal evidence and isolation proof. No files were edited, and I did not run the #421 test because its reviewed fixture does not establish database isolation.

A printed `/tmp` path is currently doing the work of a notarized deed—bold of it.

## Round 1 disposition

- Blocking 1 — ACK. `repro_stand.py` now asserts resolved raw-store paths and preconditions,
  machine-checks the throw frame, and compares the complete non-`.git` production canonical tree
  digest before/after (`d0ab4ddb...` unchanged), alongside `sessions` 583→583.
- Blocking 2 — ACK. `tests/conftest.py:51-66` is an autouse production-DB guard; the rerun returned
  `4 passed in 1.32s` and production `sessions` 583→583. The fixture evidence is now in research.
- Historical causality question — ACK. New read-only `operation_time_evidence.py` reads immutable
  canonical Git snapshots immediately preceding each persisted operation: target matches are
  0/0/0 at snapshots with 246/246/248 orchestra states, and 1/1/1 at HEAD.
- Preconditions suggestion — ACK. Canonical #398 present, canonical #399 absent, legacy #399
  present, and final frame `task_store.py:583:_find_state` are all executable assertions.
- Receipt question — narrowed. The stand claims only the finalizer seam after the receipt guard;
  persisted operation rows independently establish `commit_point=REACHED/state=PARTIAL`.
- Attempt 2 (2026-09-01): pending; allowed prose follow-up after material evidence changes.

## Round (2026-09-01T09:24:09Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Re-review status

The stand now brings receipts; the historical timestamp is still wearing the wrong name tag 🧾.

- Isolation proof — **FIXED**: resolved temporary DB/canonical paths and production canonical digest are checked in [`repro_stand.py:97`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/repro_stand.py:97) and [`repro_stand.py:194`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/repro_stand.py:194).
- Baseline test safety — **FIXED**: the autouse fixture redirects and guards SQLite connections in [`conftest.py:51`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/tests/conftest.py:51).
- Stand preconditions and exact throw oracle — **FIXED**: canonical/legacy presence and `task_store.py:583:_find_state` are machine-checked.
- Receipt/post-commit scope — **FIXED**: the research explicitly narrows the synthetic stand to the finalizer seam in [`research.md:159`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/research.md:159).
- Historical causality — **STILL BROKEN**; see the new blocking contradiction below.

The stand and evidence commands both pass; the stand reproduces the exact frame and `583→583`, while the evidence scan is read-only.

## New findings

### blocking — NEW BUG

blocking: The new KB fact at [`task-storage-architecture.md:5`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/kb/task-storage-architecture.md:5) still overstates the historical proof as operation-time absence. [`operation_time_evidence.py:77`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/operation_time_evidence.py:77) snapshots Git immediately before `merge_operations.created_at`, but the failing finalizer runs after the commit point at [`sessions.py:1642`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/app/routes/sessions.py:1642). The evidence therefore proves absence before operation creation, not necessarily when finalization threw; a canonical task could have appeared between those times. Anchor the snapshot to the finalization/error timestamp before recording this causal conclusion as established.

## Verdict

❌ **Not approved.** The reproduction and safety fixes are valid, but the load-bearing historical-causality claim remains unproven by the timestamp selected in the new evidence script.

The Git snapshot is currently being asked to testify about an event it predates—an impressively confident witness with the wrong alibi.

## Round 2 disposition (review ceiling reached)

- New blocking — ACK. The evidence script now locates the exact initial failing tool-result logs
  (508291/508303/510918) by operation UUID + error and selects the last canonical Git snapshot
  before each *failure timestamp*, not `merge_operations.created_at`. All three snapshots contain
  246/246/248 orchestra task states and target matches 0/0/0; current matches are 1/1/1.
- Same-UUID tool results on 31.08 are recorded separately as later observations of the persisted
  operation, not claimed as fresh finalizer executions.
- No Round 3: `research.md` is prose and the two-round `codex-debate` ceiling is exhausted. The
  last reviewer verdict therefore remains `Not approved` even though the named timestamp blocker
  has been corrected and rerun locally.

# #502 — merge-path subject audit

## Question

- **Context:** `merge_worker` from durable admission in `app/merge_operations.py`, through acceptance/review/test gates, to `app.routes.sessions.execute_merge_session`, `app.workspace.merge_worktree_to_main`, and the diagnostic `branch_wip_status` used by `worker_wip`.
- **Change under test:** replace checks based on where a worker branch sits in Git history with a shared representation of what the merge would actually add to the target.
- **Baseline:** current code uses several different subjects: `target..worker` commit reachability, `target...worker` merge-base tree diff, target/worker identity snapshots, task-wide commands, and the prospective merge tree.
- **Outcome:** for every pre-commit refusal, identify its actual subject and whether it can fire when the current author changed nothing relevant; reproduce incidents 1, 3 and 4; count stored failed operations by reason.

## Hypotheses considered

### H1 — one wrong-subject root

`H1:` failures 1–5 are caused by judging branch position/history instead of the current author's work, so one author-diff subject can remove all false refusals without weakening true refusals.

**Falsifier:** a claimed failure already inspects a current-author merge-base delta and still rejects for a different dimension (path class, request/session state, or task oracle), or a branch behind a moving `main` passes every current gate without rebuilding.

### H2 — two live subject defects plus independent failures

`H2:` the trailer and review refusals share a history-identity error, while the diff cap is a path-classification error; current `worker_wip` is already fixed, and the rebuild “race” is a false alarm produced by a manual two-tree comparison.

**Falsifier:** current `branch_wip_status` reports target-only deletions; a target advance makes a rebuilt branch acquire production paths or extra insertion count under current gate helpers; or research-only evidence stays below the cap while equally sized production remains blocked.

## Method

1. Read all 2,398 lines of `app/merge_operations.py`, `merge_worktree_to_main` and `branch_wip_status` in `app/workspace.py`, and every local helper reachable from the admission gates in `app/acceptance.py`, `app/merge_test_gate.py`, `app/review_coverage.py`, `app/diff_budget.py`, and `app/ia/merge_receipts.py`.[1]
2. Replayed the exact #498 history from preserved object `65f0619b`: a worker first-parent contains earlier content-equivalent merge results with `Orchestra-Operation:` trailers; `main` contains different squash SHAs for that content; the worker later merged `main`.[2]
3. Ran `.orchestra/tasks/502/reproduce_merge_subjects.py` against a fresh repository created under `/mnt/data/orchestra-502-*` and deleted the scratch checkout after printing the result. The script creates both false-refusal and true-refusal controls.[3]
4. Opened `/mnt/data/Projects/Python/orchestra/data/orchestra.db` with `sqlite3.connect('file:…?mode=ro', uri=True)`, used `Connection.backup()` to create `.orchestra/tasks/502/merge-history-copy.sqlite`, queried only the copy, then deleted the 957,206,528-byte derived copy. It is exactly reproducible from the production DB; production was never opened writable.[4]
5. Read live logs around #498 to distinguish the pre-admission review refusal from stored operations. The review refusal `6ad0f1c7-…` is absent from `merge_operations`; admission returns it before `accept_operation_snapshot` inserts a row.[5]

## End-to-end subject map

The public operation has four materially different checkpoints:

1. **Admission** snapshots session identity, target SHA, task oracle, changed paths, and review coverage (`accept_merge_operation` → `_prepare_admission_snapshot`).[1]
2. **Runner gates** revalidate session/review identity, run the pinned acceptance command, and run mapped tests (`_run_operation`).[1]
3. **Locked Git preflight** resolves refs, measures the diff budget, checks worktrees, inspects candidate commit metadata/task refs, computes the prospective merge tree, and rechecks the target (`merge_worktree_to_main`).[1]
4. **Commit/finalization** creates one squash commit, records a durable receipt, resets the worker, and updates task/session state. Failures after the commit point are `PARTIAL`/`UNKNOWN`, not pre-commit refusals.[1]

No single subject currently owns stages 1–3:

- `target..worker_head` reachability owns commit messages, task refs, and trailer rejection (`_inspect_candidate_commits`).
- `merge-base(target, worker)..worker` tree content owns insertion count, changed paths, mapped tests, and review snapshot (`measure_insertions`, `changed_paths`, `production_snapshot`).
- `merge-tree --write-tree target worker` owns conflict detection and the tree that will actually be committed.
- session/task/request state gates inspect neither work nor position.

This distinction matters: a merge-base diff is **already the current implementation** for the diff cap, review coverage, mapped tests, and `worker_wip`; it is not the proposed cure. On content-equivalent but SHA-divergent histories, it can still contain work already present in the target.[1][3]

## Complete pre-commit refusal inventory

Scope: every distinct refusal condition reachable from `accept_merge_operation` through the locked Git preflight. Dynamic exception text is one row when the condition and inspected subject are identical. Post-commit `PARTIAL`/`UNKNOWN` outcomes are listed separately afterward because they do not refuse the Git merge before mutation.

Legend for **subject class**: `WORK` = content/command attributable to the candidate; `POSITION` = ancestry or comparison against target history; `STATE` = request/session/task/operation state; `TARGET` = target checkout/ref/environment; `RESULT` = prospective merge result. “Yes—valid” means it can fire with no relevant author change but that is the intended control; “Yes—false” is a demonstrated false refusal.

| # | Emitted message/code | Condition | Actual subject inspected | Class | Can fire when current author changed nothing relevant? |
|---:|---|---|---|---|---|
| 1 | `INVALID_OPERATION_ID` | `operation_id` is not a UUID | request identifier | STATE | Yes—valid |
| 2 | `IDEMPOTENCY_CONFLICT` | same UUID, different normalized request hash | durable operation request | STATE | Yes—valid |
| 3 | unresolved prior `PENDING/RUNNING/PARTIAL/UNKNOWN` holds worker | another active operation exists for session | operation ledger | STATE | Yes—valid |
| 4 | `REPLAY_VERIFICATION_FAILED` | terminal replay cannot inspect current session/worktree | current session identity | STATE | Yes—valid |
| 5 | `REPLAY_WORKER_MOVED` | replayed operation's accepted branch/head differs from current worker | old vs current branch/head | POSITION | Yes—valid; result belongs to another snapshot |
| 6 | `SESSION_NOT_FOUND` | name+scope lookup has no session | session registry | STATE | Yes—valid |
| 7 | `SESSION_SNAPSHOT_FAILED` | worktree branch/head cannot be read | live worktree identity | STATE | Yes—valid |
| 8 | `ORACLE_MISSING` | nested behavioral merge lacks authoritative task oracle | target-relative changed paths + task config | POSITION/STATE | Yes; intended nested-merge policy |
| 9 | `ORACLE_METADATA_INVALID` | command/manifest/target pin cannot be parsed or resolved | task oracle + target tree | STATE/TARGET | Yes—valid |
| 10 | `REVIEW_AUTHOR_OUTCOME_MISSING` | completed review has no author outcome | receipt row | STATE | Yes—valid |
| 11 | `REVIEW_AUTHOR_OUTCOME_INVALID` | receipt has an unrecognized author outcome | receipt row | STATE | Yes—valid |
| 12 | `REVIEW_SNAPSHOT_UNAVAILABLE` | Git cannot compute review snapshot | target/head refs | POSITION | Yes—valid fail-closed |
| 13 | `REVIEW_VERDICT_MISSING` | matching reviewed receipt has no artifact verdict | receipt/artifact | STATE | Yes—valid |
| 14 | `REVIEW_DELTA_UNATTESTED` | a claimed post-review attestation fails one of its structural/hash/path checks | receipt, artifact, two production snapshots | POSITION/STATE | Yes—valid unless snapshot itself is false |
| 15 | `REVIEW_COVERAGE_MISSING` | production paths exist but no matching review/skip/unavailable receipt | `target...worker` production diff | POSITION | **Yes—false**, reproduced with empty target↔worker production delta |
| 16 | `SESSION_IDENTITY_CHANGED` (runner) | accepted session fields differ before gates execute | accepted vs current session | STATE | Yes—valid |
| 17 | `ACCEPTANCE_FAILED` | required or legacy acceptance command exits non-zero / pinned inputs mutate | task-wide command and manifest | WORK/STATE | Yes; not branch-position based |
| 18 | `ACCEPTANCE_INCONCLUSIVE` | command cannot start/finish/verify | task command runtime | STATE/TARGET | Yes—valid fail-closed |
| 19 | `TEST_GATE_FAILED` | a mapped pytest batch reports failure/error | tests selected from `target...worker` paths | POSITION/WORK | Yes; can be false if path selection is phantom or baseline test is red |
| 20 | `TEST_GATE_INCONCLUSIVE` | mapped tests cannot finish/start | mapped test runtime | TARGET/STATE | Yes—valid fail-closed |
| 21 | `session '<id>' not found` | session disappeared after admission | durable session row | STATE | Yes—valid |
| 22 | `session identity changed before merge` | name/scope changed | durable session row | STATE | Yes—valid |
| 23 | `session branch changed before merge` | stored branch differs from accepted branch | durable session row | POSITION | Yes—valid |
| 24 | `loaded session disagrees with its durable identity` | memory and DB name/scope/branch differ | two session owners | STATE | Yes—valid |
| 25 | `session has no worktree` | stored path empty | session row | STATE | Yes—valid |
| 26 | `session has no scope` | stored scope empty | session row | STATE | Yes—valid |
| 27 | `task_outcome must be 'continue' or 'complete'` | schema-v2 request omits/invalidates outcome | request | STATE | Yes—valid |
| 28 | `next_task_id requires task_outcome='complete'` | contradictory lifecycle request | request | STATE | Yes—valid |
| 29 | `session has no bound task` | schema-v2 session has empty task id | session/task binding | STATE | Yes—valid |
| 30 | task not found / not bound to session | primary task resolution fails | task registry/binding | STATE | Yes—valid; incident 6 lives here but its allocator owner is out of scope |
| 31 | invalid next-task identity | `next_task_id` does not resolve in scope | task registry | STATE | Yes—valid |
| 32 | cannot inspect worker identity / branch changed | unpinned HEAD path cannot resolve or branch mismatches | live worktree | STATE/POSITION | Yes—valid |
| 33 | invalid/missing target base | `_session_base_branch` cannot select a target | request/session refs | TARGET | Yes—valid |
| 34 | `target branch '<x>' is the worker branch` | target name equals worker branch | branch names | POSITION | Yes—valid |
| 35 | `worker is <status> — wait for idle before merge` | worker is non-idle at either of two lock boundaries | runtime status | STATE | Yes—valid |
| 36 | `session identity changed while waiting to merge` | row changes during idle wait | durable session row | STATE | Yes—valid |
| 37 | `worker identity drifted before merge: …` | branch changed, pinned commit vanished, or history rewrite; benign descendant advance is allowed | accepted vs live branch/head ancestry | POSITION | Yes—valid |
| 38 | task finalization preparation error | reservation/task CAS cannot be prepared | task/session ledger | STATE | Yes—valid |
| 39 | `merge execution failed: <type>: <detail>` | unexpected exception crosses the locked executor boundary | unknown execution state | STATE/TARGET | Yes—valid fail-closed (`UNKNOWN`) |
| 40 | `cannot resolve target branch: …` | base resolver fails before any ref mutation | target refs/repository | TARGET | Yes—valid |
| 41 | `worker HEAD changed before merge` | locked HEAD differs from expected head | worker branch position | POSITION | Yes—valid |
| 42 | `cannot resolve worker HEAD` | `rev-parse HEAD` fails | worker repository | STATE | Yes—valid |
| 43 | `cannot get branch` / `worker branch changed before merge` | symbolic branch lookup fails/mismatches | worker identity | POSITION/STATE | Yes—valid |
| 44 | insertion measurement error | merge-base/base ref/diff cannot be resolved | merge-base tree diff | POSITION | Yes—valid fail-closed |
| 45 | `DIFF TOO LARGE: N insertions (limit 2000)` | all inserted text since merge-base, including untracked, exceeds 2,000 | unfiltered `merge-base...worker` tree diff | WORK/POSITION | **Yes—false for research-only artifacts**, reproduced |
| 46 | `worker working tree is dirty …` | committed snapshot is not the full worker state | worktree status | STATE/WORK | Yes—valid |
| 47 | target ref inspection error | refs cannot be listed | target repository | TARGET | Yes—valid |
| 48 | `target branch '<x>' does not exist` | target ref absent | target repository | TARGET | Yes—valid |
| 49 | target and worker point to same commit / `NO_COMMITS_MERGED` | identical heads or squash stages nothing | current tree/ref result | RESULT | Yes—valid; there is no work to merge |
| 50 | `TARGET_HEAD_CHANGED` (first recheck) | target differs from admission SHA | target movement | POSITION | Yes—valid; prevents TOCTOU |
| 51 | `cannot inspect candidate commits` | `git log target..worker` fails/malformed | reachable commit set | POSITION | Yes—valid fail-closed |
| 52 | `worker commit contains reserved Orchestra-Operation: trailer` | any reachable commit absent from target contains reserved trailer | `target..worker` commit bodies | POSITION | **Yes—false**, reproduced on inherited legitimate merge result |
| 53 | `candidate task refs changed under repository lock` | locked reachable subjects differ from an expected list | `target..worker` commit subjects | POSITION | Yes; may be false for inherited foreign commits |
| 54 | task-ref resolution error | any leading ref in reachable subjects fails scoped lookup | `target..worker` commit subjects + task registry | POSITION/STATE | Yes; may be false for inherited foreign commits |
| 55 | `squash subject task refs changed …` | emitted squash header refs differ from canonical refs | constructed message | WORK/STATE | No; requires inconsistent candidate metadata |
| 56 | target worktree registry error | worktree list fails, target owner path missing/prunable | Git worktree registry | TARGET | Yes—valid |
| 57 | `worker branch cannot be merged into itself` | target checkout path equals worker path | checkout ownership | POSITION | Yes—valid |
| 58 | `target working tree is dirty …` | target checkout has local changes | target worktree status | TARGET | Yes—valid |
| 59 | `cannot checkout <target>` | target checkout fails when main checkout owns no target branch | target repository | TARGET | Yes—valid |
| 60 | `target checkout moved from '<target>' to '<actual>'` | locked checkout is on another branch | target checkout identity | TARGET | Yes—valid |
| 61 | `merge precheck failed: …` | `merge-tree --write-tree` fails without conflict paths | prospective merge computation | RESULT | Yes—valid fail-closed |
| 62 | `merge conflict in N file(s)` | prospective target+worker tree conflicts | prospective merge result | RESULT | Yes; inherited branch changes can conflict even if current author did not touch them |
| 63 | `TARGET_HEAD_CHANGED` (second recheck) | target moves after precheck | target movement | POSITION | Yes—valid; prevents committing a stale simulation |
| 64 | `merge journal could not be prepared before Git` | pre-Git durable journal write fails | operation/task ledger | STATE | Yes—valid |
| 65 | unrelated-history cherry-pick listing/apply/commit failure | fallback cannot enumerate/apply/commit worker history | whole worker history, not author boundary | POSITION | Yes; may be false or overbroad on inherited history |
| 66 | squash merge/commit failure | Git cannot stage or commit prospective merge | prospective result + target environment | RESULT/TARGET | No for content failure; yes for environment failure |
| 67 | `merge produced no new commits` | target did not move and staged tree was empty | actual Git result | RESULT | Yes—valid |

### Post-commit non-successes (not pre-commit refusals)

These do not answer the thesis because Git may already have committed. They remain important to the end-to-end path: final target snapshot unavailable; rollback/restore verification failure; durable merge receipt missing/invalid/unwritable; task-link DB failure; lifecycle persistence failure; terminal worker snapshot failure; and a crashed/restarted operation whose commit point is unknown.[1] Their subjects are result durability and state coordination, not author work or branch position.

## Reproductions and measured findings

### F1 — the reserved-trailer false refusal is confirmed

The scratch graph created a foreign commit with body trailer `Orchestra-Operation: foreign-operation`, a different target squash with the same `app/shared.py` tree, a current author's research-only commit, and then `git merge main` on the worker. `merge_worktree_to_main` returned:

```text
state=failed
commit_point=not_reached
error=worker commit contains reserved Orchestra-Operation: trailer
```

The current author did not create the trailer and the target already contained its content. The guard inspects commit reachability (`target..worker`), not the prospective merge delta.[3]

The exact production incident is the same shape. Operation `ff386752-…` on worker `research-astra`, head `65f0619b`, stored the same refusal at `2026-09-05T05:26:41Z`. Its reachable range contained earlier #493/#496/#494 merge-result commits with valid Orchestra trailers, while the current author's work was 23 research/KB/memory files.[2][4]

**Confidence: CONFIRMED — direct scratch reproduction plus one production operation.**

### F2 — review coverage has the same false subject before `git merge main`

On the SHA-divergent/content-equivalent scratch branch:

```text
git diff --name-only main worker -- app     => empty
production_snapshot(main...worker).paths   => ["app/shared.py"]
production_diff_sha256_nonempty            => true
```

Therefore review coverage can require a review for production content the merge would not add. The exact #498 first attempt returned `production diff has no snapshot-bound review…` as operation id `6ad0f1c7-…` at `05:23:46Z`, before the worker merged `main`.[3][5]

The target-independent digest added in #474 fixes **target movement for an unchanged three-dot diff**. It does not fix a three-dot diff whose subject already contains content-equivalent foreign history.[1]

**Confidence: CONFIRMED — direct scratch reproduction plus the production refusal.**

### F3 — current `worker_wip` does not have the reported phantom-deletion defect

On a branch with no author commit, after `main` added `app/target_only.py`:

```text
git diff --numstat main HEAD  => 0  1  app/target_only.py
branch_wip_status deletions   => 0
branch_wip_status insertions  => 0
branch_wip_status changed     => []
```

`branch_wip_status` has used `base...HEAD` since commit `8bd9bd60` on 2026-08-12, and `tests/test_workspace.py::TestBranchWipStatus::test_diff_stats_ignore_base_changes_after_branch_point` already freezes that behavior.[1][3]

The observed `8 insertions, 156 deletions` on #498 came from an explicitly labeled manual **two-tree** `git diff main..HEAD`, not from a `worker_wip` call; the log at `05:24:23Z` records that exact command output.[5]

**Confidence: REFUTED for current `worker_wip`; CONFIRMED for raw two-tree diagnostics.**

### F4 — a moving `main` does not invalidate a single-parent rebuild under current gates

The scratch branch was rebuilt from target, received one research commit, then `main` advanced with `app/later.py`. Without rebuilding again:

```text
measure_insertions(rebuilt, main)           => 1
production_snapshot(...).production_paths  => []
```

The reported “race” was detected by comparing complete trees (`git diff main HEAD`) and interpreting target-only work as worker deletion. Current diff-budget/review/test helpers use merge-base semantics and do not acquire that phantom. A merge operation admitted before target movement can still return `TARGET_HEAD_CHANGED`; that is an intentional TOCTOU refusal and a fresh operation recomputes the target. It does not require rebuilding the worker branch.[1][3]

**Confidence: REFUTED as a current gate defect — direct counterexample on a moving target.**

### F5 — the diff cap is real and independent of branch-position error

The scratch control used two branches from the same `main`:

```text
.orchestra/tasks/502/raw.txt  2,001 inserted lines => DIFF TOO LARGE
app/too_large.py               2,001 inserted lines => DIFF TOO LARGE
```

`measure_insertions` correctly measures the author's merge-base delta, but has no path classification. This is not cured by changing two-dot to three-dot or by moving to the author's merge-base; it already uses that merge-base.[1][3]

The history contains 25 stored `DIFF TOO LARGE` failures. The current #498 research-only instance was exactly 2,775 insertions (`d65653c0-…`). The history alone does not prove all 25 were false: some are 40,853, 47,923, 67,404, and 4,465,344 insertions and may be exactly the dumps the cap is meant to stop.[4]

**Confidence: CONFIRMED defect for research-only artifacts; REFUTED as the same root as F1/F2.**

### F6 — incident 6 is outside this task

The task allocator mismatch (`canonical=502, legacy=504`) is task-state ownership, not a merge-subject check. The user assigned its code fix to `fix-quarantine` and prohibited edits to `app/tm.py`, `app/db.py`, `app/ia/task_store.py`, `app/manager.py`, and `app/routes/sessions.py`. This task must not fix it.[6]

**Confidence: CONFIRMED scope exclusion — explicit task constraint.**

## Thesis verdict

The proposed thesis is **partly confirmed and materially over-broad**:

- Failures **1 and 5** share one live root: different checks treat history reachable from the worker, or the worker side of a merge-base, as the merge subject even when the target already contains the same content under different SHAs.
- Failure **3** is the same conceptual trap only in manual two-tree diagnostics. The current `worker_wip` implementation is already fixed and must not be changed to solve a non-existent defect.
- Failure **2** is a consequence of trusting that manual two-tree diagnostic; the current gates tolerate `main` advancing after a rebuild. Rebuilding twice was unnecessary.
- Failure **4** is independent: the measured author delta is correct, but the cap does not distinguish evidence artifacts from protected code/content.
- Failure **6** is an allocator/state-owner defect explicitly owned elsewhere.

The proposed cure “diff against the author's own merge-base” is not sufficient: the current review, test-selection, diff-budget, and WIP paths already use merge-base diffs. The safer common content subject is the **prospective landing delta**: current target tree → `merge-tree --write-tree(target, worker)` result. That asks what the target would actually gain and naturally ignores target-only movement and content-equivalent foreign history.[1][3]

However, commit-message controls (reserved trailer and task refs) cannot be derived from a tree delta. A correct design therefore needs one merge-subject owner with at least two explicit components:

1. `landing content`: paths/blobs/numstat from target → prospective merge tree, consumed by diff budget, mapped tests, and review coverage;
2. `candidate provenance`: only commit metadata attributable to the worker's unmerged contribution, consumed by trailer/task-ref checks.

The code does not currently persist an unambiguous “author commit boundary.” Reachability from target is not that boundary on SHA-divergent equivalent histories. Phase 2 must therefore present a design choice for provenance rather than silently weakening the trailer guard.

## Historical count from the read-only backup

Snapshot: 573 stored merge operations = 353 `SUCCEEDED`, 197 `FAILED`, 23 `PARTIAL`. The 197 failed rows group as follows; semantic grouping extracts `DIFF TOO LARGE` and the trailer refusal from their legacy wrapper code.[4]

| Failure reason | Count | First UTC | Last UTC |
|---|---:|---|---|
| `TEST_GATE_FAILED` | 31 | 2026-08-24 04:28 | 2026-09-04 15:58 |
| `TARGET_DIRTY` | 28 | 2026-08-03 06:13 | 2026-08-28 11:12 |
| other `LEGACY_UPSTREAM_ERROR` | 27 | 2026-08-05 05:13 | 2026-09-04 12:31 |
| `NO_COMMITS_MERGED` (excluding trailer) | 26 | 2026-08-28 05:55 | 2026-09-05 03:23 |
| `CONFLICT` | 25 | 2026-08-03 05:21 | 2026-09-05 03:17 |
| `DIFF TOO LARGE` | 25 | 2026-08-19 17:13 | 2026-09-05 05:26 |
| `ACCEPTANCE_FAILED` | 12 | 2026-08-23 14:26 | 2026-08-26 05:30 |
| `WORKER_DIRTY` | 8 | 2026-08-03 06:58 | 2026-09-03 07:18 |
| `SESSION_IDENTITY_CHANGED` | 5 | 2026-08-03 09:30 | 2026-08-07 11:16 |
| `WAITING` | 5 | 2026-08-30 15:58 | 2026-09-03 11:04 |
| `ACCEPTANCE_INCONCLUSIVE` | 2 | 2026-08-23 16:18 | 2026-08-24 16:29 |
| `TEST_GATE_INCONCLUSIVE` | 2 | 2026-09-04 05:47 | 2026-09-05 03:22 |
| reserved trailer false refusal | 1 | 2026-09-05 05:26 | 2026-09-05 05:26 |

Important denominator limit: admission-time review refusals are not inserted into `merge_operations`, so this requested table cannot count them. The exact #498 review refusal exists in `logs` but `SELECT … FROM merge_operations WHERE operation_id='6ad0f1c7-…'` has no row.[5]

## Counter-evidence and limits

- The trailer guard has a true positive frozen in `tests/test_merge_ref_gate.py::test_reserved_operation_trailer_in_body_is_refused_before_git`: a worker-authored commit with a spoof trailer must remain blocked. Allowing every reachable valid-looking trailer would weaken the control.[1]
- The diff cap has true-positive intent and a production control: 2,001 inserted `app/` lines are still refused in the scratch run. Excluding all non-`app/` paths without another boundary could allow genuinely unreviewable generated assets or release artifacts.[3]
- A prospective landing tree is unavailable when histories are unrelated or `merge-tree` fails; current code has a cherry-pick fallback. Phase 2 must define a fail-closed subject for that branch.
- A prospective tree does not include untracked files because the merge path already refuses a dirty worker before Git. Admission currently adds untracked paths earlier; changing subject timing must preserve the dirty-worktree refusal.
- The historical table counts outcomes, not unique incidents or human time. Repeated attempts are separate rows; pre-admission refusals are absent.
- No controlled historical replay classified all 25 diff-cap failures by path. Only #498 and the scratch research-only case prove the false-positive class.

## Affected files, risks, and edge cases for Phase 2

### In-scope likely changes

- `app/workspace.py`: own and compute the locked prospective landing subject; make candidate metadata inspection consume a provenance definition that distinguishes inherited Orchestra merges from worker-authored spoof trailers.
- `app/merge_operations.py`: admission/revalidation must consume the same subject for changed paths, review coverage, and mapped-test selection, or explicitly pin the inputs needed to recompute it under the repository lock.
- `tests/test_merge_operations.py`: one distinct RED seam per approved fix, with false-refusal and true-refusal directions in the same run.

### Explicitly not changed

- `app/workspace.py::branch_wip_status`: current three-dot stats already pass the requested negative control.
- `app/tm.py`, `app/routes/sessions.py`, `app/manager.py`, `app/db.py`, `app/ia/task_store.py`: owned by `fix-quarantine` / prohibited by the task.
- `app/review_coverage.py`, `app/merge_test_gate.py`, `app/diff_budget.py`: outside the granted territory. If Phase 2 cannot route the authoritative subject through the two in-scope owners without editing these files, implementation must stop and request a territory/design decision.

### Edge cases that the plan must preserve

- true forged `Orchestra-Operation:` trailer;
- inherited legitimate trailer on content already present under a different SHA;
- real oversized production diff vs oversized research evidence;
- target movement between admission, test execution, merge precheck, and commit;
- conflicts, renames/copies, binary files, mode changes, and deletions;
- unrelated histories/cherry-pick fallback;
- nested non-main merges and required task oracles;
- dirty tracked/untracked worker files;
- task refs in inherited commits vs worker-authored headers;
- review receipt identity and post-review attestation;
- no-op merge and target==worker protections.

## Sources

1. **Tier 2 — primary source:** current repository code and tests: `app/merge_operations.py`, `app/workspace.py`, `app/acceptance.py`, `app/merge_test_gate.py`, `app/review_coverage.py`, `app/diff_budget.py`, `app/ia/merge_receipts.py`, `tests/test_workspace.py`, `tests/test_merge_ref_gate.py` (read 2026-09-05).
2. **Tier 1 — direct repository measurement:** `git log --graph`, `git log main..65f0619b --format='%H %P%n%s%n%B'`, `git diff --stat main 65f0619b`, and `git diff --stat main...65f0619b` on the preserved #498 object (2026-09-05).
3. **Tier 1 — direct controlled experiment:** `uv run python .orchestra/tasks/502/reproduce_merge_subjects.py` (2026-09-05); output includes trailer refusal, empty two-tree/nonempty three-dot production subject, raw two-tree phantom vs clean `branch_wip_status`, target-advance control, and 2,001-line cap controls.
4. **Tier 1 — direct database measurement:** read-only `sqlite3.Connection.backup()` of `/mnt/data/Projects/Python/orchestra/data/orchestra.db`, 957,206,528 bytes; grouped queries over 573 `merge_operations` rows (2026-09-05). Derived copy deleted after query.
5. **Tier 1 — direct log measurement:** read-only SQL over `logs` for session `07233e67-…` and worker `968f2ea9-…`, UTC window `2026-09-05T05:20–05:30`; exact tool results for operation ids `6ad0f1c7-…`, `d65653c0-…`, `ff386752-…`, and manual two-tree output `8 insertions / 156 deletions`.
6. **Tier 2 — primary instruction:** task #502 scope and explicit ownership constraints in the assignment (2026-09-05).

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну да, три красных теста уже почти доказали безопасное удаление строк — только пока строка в базе одна. 😏

## Summary

Changes requested. The plan correctly locates the shadow-creation seam and correctly classifies the duplicate `api_update_task_if_current` definitions as intentional aliases. However, the writer inventory and acceptance criteria do not yet close several production-reachable or data-loss cases.

The named test exits `1` with exactly the three expected `DID NOT RAISE` failures.

## Findings

- **blocking:** [plan.md:32](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/plan.md:32>) — the inventory excludes the public no-context path: [`routes/tm.py:169`](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/app/routes/tm.py:169>) calls `tm.api_create_task` unconditionally, while [`tm.py:2050`](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/app/tm.py:2050>) explicitly falls back to legacy creation when no IA context exists. This is not an unsupported direct library call; either prove that this configuration cannot reach canonical finalization or include it in the supported-path verdict and fix at its opening.

- **blocking:** [plan.md:52](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/plan.md:52>) — compensation treats only `ValueError: <par> not found` as definite absence, but [`resolve_scoped_task_identity`](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/app/tm.py:2033>) handles both `KeyError` and `ValueError` from `store.task_get` as unavailable identity. A missing candidate reported as `KeyError` would be preserved as “ambiguous,” leaving the legacy-only row. Define the actual not-found contract and cover it in the oracle or a supplemental test.

- **blocking:** [plan.md:53](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/plan.md:53>) — the frozen oracle does not prove the identity and safety guards. It creates only one legacy row, so a broad `DELETE FROM tm_tasks WHERE project_id=?` or an unguarded delete passes the first two tests. Add a decoy row and cases where the created row is bound, revised, committed, or reserved; otherwise the acceptance can pass an implementation that causes data loss.

- **blocking:** [plan.md:57](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/plan.md:57>) — the plan promises preservation when the candidate probe is unreadable, but the frozen oracle tests only “candidate absent” and “candidate present.” A store whose `task_get` raises an unexpected read error is needed to prove that the implementation does not treat every probe exception as permission to delete the legacy row.

- **question:** [plan.md:51](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/plan.md:51>) — existing [`_shadow_failure`](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/app/tm.py:1942>) records debt before returning, and `record_debt` delegates without an exception boundary at [`runtime.py:211`](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/app/ia/runtime.py:211>). If the new branch invokes this before probing and compensating, a debt-writer failure skips cleanup. Specify the ordering or failure policy and test it.

- **suggestion:** [plan.md:33](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/plan.md:33>) — the manager and route spawn paths are not equivalent: [`manager.py:806`](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/app/manager.py:806>) resolves canonical identity before assigning `allocated_task_id`, so it fails before manager compensation can discard the row, whereas [`routes/sessions.py:945`](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/app/routes/sessions.py:945>) can proceed to binding at line 978. Correct the inventory wording and explicitly state which path the regression proves.

## Verdict

**CHANGES REQUESTED.** The minimal fix belongs in shadow creation, and the duplicate `api_update_task_if_current` definitions are intentional and safe. Resolve the no-context path and strengthen the compensation oracle before implementation.

Otherwise this is just deleting the suitcase because its tag looked unique—excellent until it was the suitcase that mattered. 🧳

## Round 1 disposition

- No-context path — ACK. Live FastAPI requests begin only after lifespan yields inside
  `knowledge_runtime_mode` and process IA mode; offline legacy calls cannot reach canonical worker
  binding/finalization through the supported path.
- KeyError — ACK as ambiguous, never as proof of absence.
- Delete safety — ACK. The old RED `d032fe1f` is excluded; new RED `8346b4dc` adds a decoy and
  bound/revised/committed/reserved mutations.
- Unreadable probe — ACK. RuntimeError and KeyError cases preserve the row and require loud failure.
- Debt writer — ACK. Plan orders probe/compensation first, debt recording second and best-effort.
- Spawn-path wording — corrected: manager stops at canonical identity resolution; taskless-worker
  assignment can bind directly; both are closed by making shared creation fail loud.
- Attempt 2 (2026-09-01): pending after plan and oracle changes.

## Round (2026-09-01T09:56:01Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Три красных теста выросли до десяти — прогресс, если считать количество способов не доказать безопасность. 😏

## Re-review status

Reviewed the current untracked plan via `git diff --no-index` and oracle `8346b4dc`; `d032fe1f` не использовал. Named command воспроизводит 10 ожидаемых behavior failures без collection/setup errors.

- R1 no-context route — **FIXED**.
- R1 candidate classification — **FIXED** in the plan: `KeyError` and other read errors are ambiguous.
- R1 unsafe broad delete / missing guards — **FIXED**; decoy and four mutation cases added.
- R1 unreadable probe — **FIXED** for `RuntimeError` and `KeyError`.
- R1 debt-writer ordering — **FIXED**; compensation precedes debt recording and primary error wins.
- R1 spawn-path description — **FIXED**.
- Duplicate `api_update_task_if_current` definitions — **no finding**; alias capture at line 1723 before the public dispatcher at line 2316 remains intentional.

## New findings

- **blocking:** [plan.md:55](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/plan.md:55>) / [oracle:160](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-merge-finalize/docs/tasks/426/acceptance/test_t1_shadow_task_creation.py:160>) — the plan requires another `ValueError` to be treated as ambiguous, but the oracle parameterizes only `RuntimeError` and `KeyError`. An implementation that deletes on every `ValueError` would pass the current oracle while violating the data-loss rule. Add a probe case such as `ValueError("candidate read malformed")` and assert the legacy row survives.

## Verdict

**CHANGES REQUESTED.** All prior findings are addressed, but the new oracle still leaves one unsafe `ValueError` branch untested. After adding that case, the plan is eligible for approval—assuming no other changes.

## Round 2 disposition

- New blocker — ACK. Added `ValueError("candidate read malformed")` to the ambiguous probe case;
  it preserves the legacy row and still requires the primary loud creation failure.
- RED `8346b4dc` is excluded; new immutable RED is `05f5f8c0`, 11 behavior failures, RC=1.
- Attempt 3 (2026-09-01): pending; executable oracle changed, within the three-round code ceiling.

## Round (2026-09-01T09:58:27Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

One extra `ValueError`, and the oracle finally stopped pretending the matrix was complete. 😏

## Re-review status

`git diff` has no tracked changes; the plan is untracked, so it was checked via `git diff --no-index`. Only oracle `05f5f8c0` was used. The named command reproduces 11 expected behavior failures with no setup/collection errors.

All prior findings are **FIXED**:

- no-context route
- candidate absence classification
- compensation guards and decoy protection
- unreadable probe handling
- debt-writer ordering
- spawn-path distinction
- Round 2 non-not-found `ValueError` case

The duplicate `api_update_task_if_current` definitions remain correctly classified as an intentional alias and dispatcher pair.

## New findings

None.

## Verdict

**APPROVED.** The final plan and immutable oracle now cover the identified production paths and compensation safety cases. The RED state is expected because implementation has not started.

> “A debt-writer failure is secondary: log it, but do not skip compensation and do not replace the primary creation failure.”

At last, the oracle checks the spare suitcase too—because apparently one row was never enough. 🧳

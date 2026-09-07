<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Of course, the race conditions were invited to a sequential test and stayed home 😏 The pinned diff has three blocking lifecycle/data-integrity issues. Targeted tests pass: `11 passed in 3.28s`.

## Findings (blocking/suggestion/question)

### blocking: [P1] Make revision validation and update atomic

**File:** [app/ia/task_store.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-quarantine/app/ia/task_store.py:1479)

`sync_revision` is checked before `self.canonical_head` is read and before `task_update()` reloads state. If another update to the same task commits in that gap, this method adopts the newer head and writes successfully instead of rejecting the stale caller, potentially resurrecting or overwriting task state. The test only covers sequential contention, not this interleaving.

### blocking: [P1] Couple lifecycle preflight with receipt acceptance

**File:** [app/manager.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-quarantine/app/manager.py:1259)

`preflight_message_delivery()` performs lifecycle mutation/checking without holding the target session lock across the subsequent `accept_message_delivery()` call. A concurrent repair or quarantine transition can therefore occur after preflight and before receipt creation, producing a queued receipt that later fails delivery instead of being refused at accept time. Retries of an existing `FAILED_BEFORE_SUBMIT` receipt are also vulnerable because preflight may mutate lifecycle state while the retry reuses the receipt’s frozen `target_generation`.

### blocking: [P1] Verify the actual worktree before clearing quarantine

**File:** [app/routes/sessions.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-quarantine/app/routes/sessions.py:2770)

The same-task fast path treats the persisted `previous_branch` as proof that the worktree is already on `task-{par}/{name}`; it performs no Git identity check before clearing `needs_switch`. If the worktree has drifted or the persisted branch is stale, repair marks the lifecycle healthy and subsequent work runs on the wrong task branch, violating task isolation.

### blocking: [P1] Roll back binding when lifecycle persistence fails

**File:** [app/routes/sessions.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-quarantine/app/routes/sessions.py:2780)

`bind_task_to_session()` mutates task/session ownership before `transition_lifecycle()` persists the cleared quarantine state. If the second operation fails, the handler reports “without changing the binding” but leaves the first mutation committed, creating inconsistent durable state and potentially a task bound to a session that remains quarantined.

## Verdict

**INCORRECT** — the happy-path tests pass, but concurrent same-task updates, accept-time delivery races, worktree drift, and partial repair failure can corrupt lifecycle state or lose durable delivery. Исправление пока похоже на ремонт двери: ручку прикрутили, а коробку забыли проверить.

## Round (2026-09-05T05:47:46Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Ну вот, четыре старых дыры действительно залатали, а allocator научился принимать несовпадение за порядок 😏

Prior blockers:

1. CAS interleaving — **FIXED**.
2. Keyed receipt/session locking — **FIXED**.
3. Worktree branch drift — **FIXED**.
4. Read-only binding validation — **FIXED**.

Targeted tests pass: `15 passed in 3.50s`. No files edited.

## Findings (blocking/suggestion/question)

### blocking: [P1] Preserve the genuine divergence gate

**File:** [app/tm.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-quarantine/app/tm.py:2949)

Applying the same artifact-directory skip to both candidates and then comparing only the resulting numbers can hide real store divergence. If canonical contains only task `#1`, legacy contains `#1` and `#3`, and artifact directories `2` and `3` exist, both normalized candidates become `4`; creation proceeds and permanently leaves canonical missing task `#3`. The gate must compare store contents/identity before artifact reservations can make candidates equal.

### blocking: [P1] Do not let repair overwrite the persisted base branch

**File:** [app/routes/sessions.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-quarantine/app/routes/sessions.py:2833)

The same-task repair performs no branch switch but persists `base_branch=from_ref`. A caller can supply another valid branch, clear quarantine, and silently replace the worker’s lifecycle base with an unrelated ref; later switching or merge operations then use the wrong base. Same-task repair should retain `previous_base_branch` or reject an override.

## Verdict

**INCORRECT** — the four previous blockers are fixed, but the allocator can still mask genuine canonical/legacy divergence, and same-task repair accepts an unsafe base-branch override.

Теперь четыре замка закрываются, но allocator всё ещё считает две разные комнаты одной, если рядом лежат папки с одинаковыми номерами.

## Round (2026-09-05T05:51:52Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

At last, the allocator and lifecycle repair agree on reality 😏 All six prior blockers are **FIXED**. No new blocking findings.

- CAS interleaving — **FIXED**
- Acceptance lock — **FIXED**
- Actual worktree identity — **FIXED**
- Non-mutating binding validation — **FIXED**
- Raw divergence gate — **FIXED**
- Preserved repair base — **FIXED**

## Findings (blocking/suggestion/question)

None.

## Verdict

**APPROVED**

Verified with:

```text
$ uv run pytest -q tests/test_lifecycle_quarantine_499.py
...............                                                          [100%]
15 passed in 2.39s
```

На этот раз дверь действительно закрыта, а папки просто лежат рядом — почти подозрительно нормально.

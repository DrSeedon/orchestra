<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Round 1

## Summary

Naturally, the happy-path tests pass while concurrent ownership updates can still hand the same directory to two workers 🙃

Reviewed the exact pinned diff `bf59a7d...f498886a`; the focused suite passes: `10 passed`. Targeted probes reproduced four boundary failures and one detached-row corruption.

The three `_isolated_session_ownership` call sites fully contain ordinary exceptions. The loaded-session status lock and normal worker-memory suffix handling are also correct. The unloaded and concurrent paths are not.

## Findings

1. **blocking: Validate the fully mapped ownership set before committing** — [app/orchestra_layout.py:263](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-ownership-migration/app/orchestra_layout.py:263)

   The migration maps each row independently without checking the resulting ownership against other live workers. If one worker owns `docs/tasks/1` and another already owns `.orchestra/tasks/1`, the startup migration commits both as `.orchestra/tasks/1`. This was reproduced against the pinned code. The transaction is all-or-nothing, but the committed result still violates the ownership boundary. Validate all mapped rows pairwise before the first update and fail or report the conflicting project.

2. **blocking: Serialize overlap validation across workers in one scope** — [app/manager.py:1709](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-ownership-migration/app/manager.py:1709)

   Each request locks only its target session. Concurrent updates for two different workers can therefore both validate against the old database state and then both save the same directory. A synchronized probe produced `["shared"]` for both workers in memory and in SQLite. The overlap check and write need one scope-level critical section or equivalent transactional enforcement.

3. **blocking: Do not save a full snapshot from a detached session** — [app/manager.py:1714](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-ownership-migration/app/manager.py:1714)

   `get_by_name()` can return a partially hydrated `loaded=False` session, but this path persists its complete `_to_db_dict()` snapshot. A detached update against the pinned code changed unrelated fields: `color` from `#818cf8` to `""` and `template_hash` from `02715933` to `""`. Persist only the three ownership-related columns for detached sessions, as the existing detached update paths do, or fully load the authoritative session first.

4. **blocking: Re-resolve detached sessions after acquiring the lock** — [app/routes/sessions.py:1419](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-ownership-migration/app/routes/sessions.py:1419)

   `found` is captured before the session lock. If it is detached while another request loads the same session, this route continues updating the detached object and skips `_lifecycle_lock`. Conversely, a loader can capture the old DB row, wait for this update, and then hydrate that stale row. The reproduced result was DB ownership `["new"]` while the registered live session and prompt still used `["old"]`. The next turn therefore starts under the old boundary despite a successful response.

5. **blocking: Locate the generated ownership block rather than the first heading** — [app/manager.py:472](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-ownership-migration/app/manager.py:472)

   `partition()` selects the first matching heading anywhere in the stored prompt. If task text quotes `## Directory ownership` followed by a bullet, the function rewrites that quoted bullet, stops at the following prose, and leaves the actual generated ownership suffix unchanged. The column is nevertheless migrated, and subsequent runs skip the row because its column is already current. This was reproduced with the real prompt builder. The normal single-marker case correctly leaves worker-memory bullets untouched.

6. **suggestion: Reject `--dry-run` outside ownership-repair mode** — [scripts/migrate_orchestra_layout.py:43](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-ownership-migration/scripts/migrate_orchestra_layout.py:43)

   `--dry-run` is consumed only when `--repair-ownership` is present. `scripts/migrate_orchestra_layout.py --dry-run <repo>` silently performs and commits the ordinary layout migration. Reject incompatible flag combinations—or make the flag apply globally—so a dry-run invocation cannot mutate a repository.

## Verdict

❌ **Request changes.** The isolation wrapper itself is sound, but the implementation can corrupt detached session metadata, preserve stale live authority, or create overlapping write territories. At the moment the ownership lock behaves like two guards checking separate guest lists for the same room.

## Round (2026-09-04T11:44:43Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Round 2

## Summary

The six fixes arrived; naturally, three brought smaller trapdoors with them 🙃 Following the structured review workflow, I list only reproduced, actionable regressions.

| Round 1 finding | Status |
|---|---|
| F1 migration overlap | FIXED |
| F2 concurrent updates | STILL BROKEN across ownership writers |
| F3 detached snapshot corruption | FIXED |
| F4 stale detached session | STILL BROKEN |
| F5 heading-based replacement | PARTIALLY FIXED; two boundary bugs remain |
| F6 unsafe `--dry-run` | FIXED |

The NULL-overlay correction itself is correct. No lock-order deadlock was found. The focused suite passes: `16 passed`.

## Findings

1. **blocking: Use the scope lock in every ownership writer** — [app/manager.py:1741](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-ownership-migration/app/manager.py:1741)

   The new lock serializes two `apply_owned_dirs` calls, but spawn and switch do not participate. A reproduced interleaving delayed an update from `alpha → shared`, created `beta` with `shared` while both memory and SQLite still showed `alpha → old`, then completed the update; both rows ended owning `shared`. The old spawn-vs-spawn race is pre-existing, but the new endpoint racing with those writers is part of this change, so excluding them makes the scope-wide invariant ineffective.

2. **blocking: Re-read the loader’s row after acquiring the session lock** — [app/routes/sessions.py:1423](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-ownership-migration/app/routes/sessions.py:1423)

   F4 remains reproducible. While this route holds the session lock and awaits its detached DB write, `ensure_loaded()` can read the old row and then wait for that lock. After the update releases it, `_ensure_loaded_row()` hydrates the previously captured row without re-reading SQLite. The resulting DB ownership was `["new"]`, while the registered live session and prompt remained `["old"]`. Re-resolving only inside this route cannot repair a stale snapshot already held by the loader.

3. **blocking: Require the authoritative non-NULL overlay to be repaired** — [app/orchestra_layout.py:302](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-ownership-migration/app/orchestra_layout.py:302)

   The `prompt_found or overlay_found` guard accepts a row when `system_prompt` contains the old block but a non-NULL `prompt_overlay` does not. The migration updates the column and system prompt, reports no attention, and leaves the overlay unchanged. `assemble_prompt()` then rebuilds from that authoritative overlay and ignores both repaired values, so the worker receives no ownership block. This exact state produced `changed=1`, empty `attention`, and an assembled prompt without `## Directory ownership`.

4. **blocking: Exclude worker memory before using `rpartition`** — [app/manager.py:495](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-ownership-migration/app/manager.py:495)

   `system_prompt` stores worker memory after the generated ownership suffix. If memory quotes the complete old generated block, `rpartition()` replaces the memory copy and leaves the real ownership block unchanged. With a NULL overlay, the guard treats this as success, migrates the column, and `assemble_prompt()` strips the rewritten memory before retaining the old real block. The quoted-heading test does not cover this exact duplicate-block case.

5. **blocking: Make persistence cancellation-safe before releasing the locks** — [app/manager.py:1756](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-ownership-migration/app/manager.py:1756)

   Cancelling the request while either `to_thread` write is running releases the scope, lifecycle, and session locks, but the worker thread continues and can commit afterward. The assignments beginning at line 1765 never execute. A reproduced cancellation left SQLite at `["new"]`, live memory at `["old"]`, and the scope lock free. The persistence plus in-memory publication must finish as an owned cancellation-shielded operation before these locks are released.

## Verdict

❌ **Request changes.** F1, F3, F6, and the explicit NULL-overlay correction are complete, but ownership can still overlap or diverge between SQLite and the live worker. The locks now share a conductor, but several writers are still playing from different pages.

## Round (2026-09-04T11:54:58Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Round 3

## Summary

Final rounds are wonderfully efficient at finding the cancellation after the cancellation 🙃 Using the structured review workflow, I reviewed the pinned `bf59a7d...0ff21b43` snapshot and reproduced both remaining issues.

| Item | Status |
|---|---|
| R2-2 loader re-read | FIXED |
| R2-3 authoritative overlay | FIXED |
| R2-4 worker-memory partition | FIXED |
| R2-5 cancellation atomicity | STILL BROKEN on repeated cancellation |
| Disputed scope-wide serialization | STILL OPEN |

The focused suite passes: `20 passed`. No current lock-order deadlock was found. `WORKER_MEMORY_MARKER` behaves safely when absent or repeated after the real opening tag; an earlier occurrence fails closed into `attention`. `before == after` never reaches replacement during migration.

## Findings

1. **blocking: Serialize the publication point of every ownership writer** — [app/manager.py:1751](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-ownership-migration/app/manager.py:1751)

   I agree that holding the scope lock across worktree creation and `session.start()` would be wrong, but that is not required. Keep the early validation, then acquire the scope lock only around a second validation plus `publish_ready_session`; switch can similarly revalidate and publish after Git preparation. The current snapshot still reproduces `alpha=["shared"]` and `beta=["shared"]` when `apply_owned_dirs` races with spawn. The old spawn-vs-spawn race is pre-existing, but the new writer racing with spawn is introduced here, so deferring every other participant leaves this endpoint’s blocking-overlap contract false.

2. **blocking: Protect the commit from repeated cancellation** — [app/manager.py:1801](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-ownership-migration/app/manager.py:1801)

   One cancellation is handled correctly, but the `await commit` inside the handler is unshielded. A second `task.cancel()` propagates into `_commit`; when it is awaiting `to_thread`, the Python future is cancelled while the SQLite thread continues. The current code reproduced SQLite `["new"]`, live memory `["old"]`, and an unlocked scope. The existing `_wait_owned_task` helper already handles repeated cancellation without abandoning the owned task. Waiting for the underlying DB operation is intentional here; the current single-cancellation path does not otherwise orphan the task.

## Verdict

❌ **Request changes.** The four accepted fixes are complete on their intended paths, but two ownership-boundary races remain reproducible in the final snapshot. The doors now lock correctly—provided nobody enters through spawn and nobody presses cancel twice.

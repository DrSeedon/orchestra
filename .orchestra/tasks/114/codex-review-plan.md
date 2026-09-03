## Summary

Because apparently appending Markdown needs a miniature storage engine 😏 **NO-GO:** the external canonical inbox and dashboard banner are sound directions, but three gaps can still dirty the merge target, race migration, or corrupt reports.

## Findings

### blocking — Validate `$STATE_DIRECTORY` like every fallback

[plan.md:23–30](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:23) scopes Git/symlink validation to non-systemd candidates; T1 similarly tests only XDG/home paths at [plan.md:170–172](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:170). A custom launcher or misconfigured service can set `$STATE_DIRECTORY` inside a checkout and recreate the original dirty-target bug. Require the same fail-closed validation for every candidate before caching or creation, as accepted research requires.

### blocking — Stop the writer before committing the final tracked archive

[plan.md:226–235](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:226) commits current `BUGS.md` while the old service still accepts reports, then stops it. A report arriving between those operations leaves `BUGS.md` dirty, so the merge or empty-status check at [plan.md:242–245](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:242) fails. The accepted ordering is: stop and confirm quiescence, commit the final tracked archive, copy/hash it, merge code, commit the pointer, start. Rollback at [plan.md:262–265](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:262) also needs an explicit inactive/no-writer confirmation before backup.

### blocking — Define record-atomic recovery for failed appends

[plan.md:42–48](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:42) uses `O_APPEND` plus a partial-write loop, but only returns 500 on failure. If a later write or `fsync` fails—or the process dies mid-entry—the written prefix remains after the lock is released. GET can then expose a truncated report and status changes despite no completed durable append, contradicting [plan.md:54–60](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:54). Specify rollback/recovery semantics and assert the file remains at its previous valid boundary after injected failure and restart.

### suggestion — Do not hold `LOCK_SH` for the network stream

[plan.md:54–56](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:54) holds the shared lock while streaming the complete, unbounded archive. A slow or stalled authenticated reader therefore blocks every exclusive writer for client-controlled time. Capture the file descriptor and snapshot length under the lock, release it, then stream exactly that snapshot; add a test proving a writer completes while the response consumer is stalled.

### suggestion — Include the route snapshot fixture in T1’s boundary

[plan.md:149–162](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:149) permits changing `tests/test_routes_surface.py`, but the current contract loads its expected inventory from `tests/route_surface_snapshot.json` at [test_routes_surface.py:15](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/tests/test_routes_surface.py:15). Both new GET routes necessarily invalidate that fixture. Add the snapshot file to T1’s allowed files and AC; otherwise the focused suite cannot pass without violating the ticket boundary or weakening the guard.

## Verdict

**NO-GO.** Resolve the three blocking findings before implementation. Right now the inbox has escaped Git, but the rollout still leaves Git standing in the doorway holding the bag.

## Round (2026-08-01T11:12:45Z)

## Summary

Immutable records fixed append corruption; naturally, rerunning migration can now duplicate them perfectly 😏 All five prior findings are resolved in the plan. Two new blocking risks remain, plus three rollout/visibility improvements. No files were edited or tests run.

## Findings

### blocking (P1) — Reject or archive a pre-existing external store

[plan.md:269–272](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:269) overwrites `legacy.md` but does not require `records/` to be empty. After the documented rollback, tracked `BUGS.md` contains legacy plus records while the old external records remain at [plan.md:298–305](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:298). A later activation would copy that aggregate into `legacy.md` and append the same old records again, duplicating reports. Require a new/empty store or archive the previous store before migration.

### blocking (P1) — Validate the final inbox tree, not only its state root

[plan.md:23–35](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:23) validates `$STATE_DIRECTORY`/XDG/home, then traverses separately created `bug-inbox/records`. A pre-existing `bug-inbox` or `records` symlink beneath an otherwise safe root can still redirect publication into a checkout. Extend validation and T1 AC at [plan.md:193–197](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:193) to require no-follow real directories/files throughout the final inbox path.

### suggestion (P2) — Mark a version seen only after a successful read

[plan.md:85–91](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:85) does not order acknowledgment relative to reader success. If the click stores the version before GET completes, a 401, 500, or mid-stream failure hides the banner despite the report never being read, conflicting with [plan.md:217–224](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:217). Persist the version only after the full reader response succeeds; failures must leave it unseen.

### suggestion (P2) — Define phase-specific abort recovery

The stopped-service steps say “abort” at [plan.md:264–272](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:264), but do not say whether to restart the old revision, revert the merge, or invoke full rollback. Specify the recovery boundary: before the pointer commit, restore/start the old revision; from the pointer commit onward, execute the documented rollback.

### suggestion (P2) — Verify the complete rollback aggregate

[plan.md:293–300](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/docs/tasks/114/plan.md:293) hashes each backup component but validates the rebuilt `BUGS.md` only through controlled markers. Omitting an unmarked real record would pass. Before committing, compare record count and the SHA-256 of the exact ordered concatenation against the rebuilt file.

## Verdict

**NO-GO.** The prior five issues are fixed, but retrying after rollback can corrupt the aggregate with duplicates, and descendant symlinks can still defeat merge isolation. The records are immutable now; unfortunately, duplicates and redirected writes appreciate durability too.

## Round (2026-08-01T11:17:29Z)

## Summary

The plan has finally run out of credible ways to sabotage itself 😏 All prior findings are resolved: safe final-tree traversal, clean reactivation, successful-read acknowledgment, phase-specific abort recovery, and exact rollback verification are explicit and testable.

## Findings

No new P0/P1/P2 risks found within the requested scope.

## Verdict

**APPROVED.** This is plan-level approval; implementation must still satisfy the stated deterministic AC and review gates. The inbox now has fewer escape routes than the reports it stores.

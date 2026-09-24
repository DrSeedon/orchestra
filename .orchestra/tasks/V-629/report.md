# V-629 — project layout data preservation

## Change

`_write_worktree_entry` now writes regular files and symlinks beside the destination and installs them with `os.replace`. A write or chmod error leaves an existing destination intact. The previous implementation removed the destination and called `Path.write_bytes` on the final path, leaving a window in which interruption could leave the file absent or truncated.

Before either normal migration or journal recovery drops a preserve stash, the code now compares each changed and untracked path with its saved Git blob. Regular-file bytes and symlink targets must match; a saved deletion must still be absent. A mismatch raises `ORCHESTRA_LAYOUT_GIT_ERROR`, leaving the stash and preserve journal in place. Git status remains a separate check for path/state correctness.

Already-current layouts now return `already_current` without a stash/restore transaction. The application calls the registered-project migration once from the lifespan startup hook; the repeated work came from running a preservation transaction for dirty projects even when their layout was already current on every new startup. Clean partial layouts now use the existing repair path, which lets a startup finish a safe split migration without creating a stash.

## Zero-byte files and limits of attribution

The old destructive write sequence is a code path capable of leaving a file empty or missing if interrupted after unlink/truncate and before all bytes reach the destination. Atomic replacement removes that failure window for future migrations. This establishes a plausible in-code mechanism and closes it; available Git history, current source and read-only service logs do not prove that this mechanism produced the historical zero-byte files. Their actual cause remains undetermined. No live project file, stash or `.git` directory was changed.

## VPS observations, read-only on 2026-09-24

The VPS journal recorded `dnd-game-master` as `ORCHESTRA_LAYOUT_PARTIAL` and `/opt/cog-second-brain` as `ORCHESTRA_LAYOUT_GIT_ERROR: cannot locate the migration commit while recovering stash=fb3d4dacea5555353b666e47d0a4e9a27d1770a8`.

For dnd-game-master, `git status --porcelain` was clean, `.orchestra/layout.json` existed, and the checkout contained `docs/kb` alongside `.orchestra/tasks` and `.orchestra/workers`. With no dirty records, the old call path invoked `migrate_project_layout(..., repair=False)`, which refuses a mixed layout. The updated path selects the existing repair mode for this clean partial state. A temporary Git repository with the same split repaired successfully; the next service startup should move the remaining legacy path and commit the migration. The live checkout was not touched.

For cog-second-brain, the live preserve journal said `phase=stashed`, `source_head=2b0dff6d9927819fc49008878565a4c7cbd3abb3`, and named the stash above. Current `HEAD` was `91dd892e3ad6d7d0fdf60f24db67557a2ecb4213`, the layout remained mixed, and the stash was still listed. The checkout also had later dirty/untracked files. Recovery correctly refuses to guess which commit completed the migration or overwrite later changes when `HEAD` moved away from `source_head` and the layout is not current. This patch does not resolve that ambiguous live state: the preserve stash and journal remain for a separate repository-level repair, and the project will continue to log a migration failure until that repair. No stash or file was changed.

The laptop journal was checked read-only over the SSH tunnel on 2026-09-24. `journalctl --list-boots` retained only boot `-1` (2026-09-23 18:46:26 through 23:39:39 +07) and boot `0` (2026-09-24 10:00:28 through 14:16:19 +07); it does not cover the earlier interval in which the reported stash counts accumulated. In the retained records, one server-process start is visible at 2026-09-24 10:00:33, with startup complete at 10:00:41. The prior visible process logged shutdown at 2026-09-23 23:39:33 and application shutdown complete at 23:39:34; systemd stopped the unit, then the host reached `poweroff.target` at 23:39:39. The next service start followed the next boot at 10:00:31. Current `NRestarts=0` and `Result=success`. Thus the retained journal shows an orderly host poweroff/start, not a service crash loop, but it cannot confirm or rule out a roughly 12-second start cadence before 2026-09-23, nor establish what initiated the poweroff. The 2,248/8,067 stash counts alone do not establish restart frequency. The code calls registered-project migration once per application lifespan, not in an internal retry loop; already-current dirty projects now skip stash transactions on later starts.

## Verification

Command:

```text
/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_orchestra_layout_430.py tests/test_orchestra_layout_dirty_430.py tests/test_orchestra_layout_recovery_430.py tests/test_orchestra_layout_fleet_430.py -q
```

Result: `18 passed in 20.71s`. The tests use temporary Git repositories and cover preserved bytes/status, interrupted recovery, a content-truncation mutation that must keep the stash, an injected write failure that must retain the old destination, three repeated current-layout calls with no stash commands and intact dirty bytes, and repair of a clean mixed layout.

Mutation checks: after the regression tests were committed, disabling `_verify_restored_stash` made `test_restore_content_mismatch_keeps_the_preserved_stash` fail with `DID NOT RAISE`. Separately, replacing the `state == "current"` early return with `if False` made `test_current_dirty_layout_skips_repeated_stash_transactions` fail at `assert stash_operations == []`; the three calls issued stash operations even though the final stash depth remained unchanged. The current-layout test passed again after restoring the implementation (`1 passed in 4.41s`).

The imported module was `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-layout-loss/app/orchestra_layout.py`. `git diff --check` passed.

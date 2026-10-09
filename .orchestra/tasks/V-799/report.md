# V-799 — University migration recovery

## Result

University now has a valid `.orchestra` layout and no active layout or preserve journal. The laptop Orchestra service was not restarted. The migration function recovered the preserved KB files; a second call returned `already_current` without the reported error. The active laptop SQLite database remained untouched: the first recovery path does not invoke session ownership repair, and the second startup-path check replaced only that DB helper with a no-op because the task marks the database read-only.

## Cause

This was an inconsistent repository state, not a defect in Orchestra's migration guard. The preserve journal recorded `phase=stashed`, `source_head=877b3ce6a890abcf22612d53698e7adeb4b33105`, and stash `ea2b2528c116ce4aa9f4e7c4e8a821000704939e`. University was at `581201057d3cc0f4e6c4b421c8d2048353201caf`, on a history where the saved source commit is not an ancestor. At that point `_layout_state()` reported `partial` only because the untracked `.orchestra/.layout-migration.json` remained; `_layout_state(ignore_journal=True)` reported `current` with managed path `kb`. Recovery correctly refused to restore the stash onto a state it considered partial while `HEAD` had moved.

The error was reproduced before repair by calling `migrate_project_layout_preserving_dirty()` from `/mnt/data/Projects/Python/orchestra/app/orchestra_layout.py`; it returned the reported `ORCHESTRA_LAYOUT_GIT_ERROR`. The imported code was from `/mnt/data/Projects/Python/orchestra`, not this worktree.

## Preservation and repair

Before changing University, created `refs/backup/v799/0` → `ea2b2528c116ce4aa9f4e7c4e8a821000704939e` and `refs/backup/v799/1` → `c6acce0e7cf0a51d18e7a6ece9f96d5f99d8d888`. The original migration journal SHA-256 was `08155c6fbd933bc85959bfdf872929c1e92c900a6ace60f516a0533d7a3c67db`; an identical copy is preserved at `/mnt/data/Projects/.orchestra-v799-backups/layout-migration.json.stale`.

The preserved stash contained 79 untracked KB files, and a preflight found zero destination collisions. After the journal was moved to the backup directory, `migrate_project_layout_preserving_dirty()` returned `status=recovered`, `dirty_preserved=true`, restoring all 79 files under `.orchestra/kb/`. It removed the preserve journal and dropped the preserve stash from `refs/stash`; the backup ref still pins that commit. A second migration call returned `status=already_current`. The project now reports `('current', ['kb'])`; neither journal remains in the repository.

The owner's `stash@{1}` before repair was `c6acce0e7cf0a51d18e7a6ece9f96d5f99d8d888`. It is still the exact same commit afterward, now displayed as `stash@{0}` because the preserved `stash@{0}` was dropped after its backup ref was made. `refs/backup/v799/1` independently retains its original object. University `HEAD` stayed at `581201057d3cc0f4e6c4b421c8d2048353201caf`; tracked worktree and index remain clean. The only post-recovery status is the expected `?? .orchestra/kb/` for the restored preserved files.

## Verification limits

The exact startup migration function was called twice. On the second call, `_isolated_session_ownership` was stubbed to avoid writes to the active read-only database; layout recovery/state detection and the `already_current` result were exercised. No Orchestra code change was needed, so no code regression test was added.

# V-632 — cog-second-brain: stuck layout migration repaired, no data lost

Result: `/opt/cog-second-brain` is now in layout state `current` with no preserve journal. The startup
entry point (`migrate_registered_projects(..., preserve_dirty=True)`) returns `already_current` on a copy
of the repaired live repo. It does so with the current `main` code and with the unmerged V-629 code.
Every pinned byte checks out. Orchestra was not restarted. Neither the owner nor the cog orchestrator
was contacted.

## What was wrong

Observed 24.09 09:0x CEST, read-only:

- The preserve journal `.git/orchestra-layout-preserve.json` held `phase=stashed`,
  `source_head=2b0dff6d`, `stash_oid=fb3d4dac…` and managed `archive,kb,tasks,workers`. Its only
  status record was ` M AGENTS.md`. A copy is in `preserve-journal-before.json`.
- The stash `fb3d4d` (20.09 18:31) holds exactly one change: an unstaged edit to `AGENTS.md` against
  `2b0dff6d`, two lines that add coat descriptions to the two dog entries. Its index tree equals
  `source_head`, and its untracked tree `^3` is empty. **That edit was in neither HEAD nor the working
  tree.** Since 20.09 it existed only in this stash. Meanwhile commit `ceb6d3e` (22.09) turned
  `CLAUDE.md` from a symlink to `AGENTS.md` into a separate regular file, and `AGENTS.md` went on
  changing in 5 more commits.
- The layout was mixed for a different reason than the stash. The migration of 05.09 was complete:
  `.orchestra/layout.json` has managed `kb,tasks,workers`. Afterwards, cog agents committed three
  files to the OLD path: `docs/tasks/{V-1,V-2,V-19}/retro.md` (commits `65a1631`, `9eee5de`,
  `cdf73e1`, 12–16.09). With `docs/tasks` and `.orchestra/tasks` both present, `_layout_state`
  returns `partial`. Those paths come from cog's own skills: `.claude/skills/self-analysis/SKILL.md`
  writes `docs/tasks/<id>/retro.md`, and `codex-debate` writes `docs/tasks/<id>/codex-review-*.md`.
- Sequence of the 20.09 restart: the dirty `AGENTS.md` was stashed. Then
  `migrate_project_layout(repair=True)` raised `both old and new paths exist: ['tasks']`, which left
  the journal at `phase=stashed`. HEAD later moved 39 commits to `91dd892`. On every start since,
  `_recover_preserved_dirty` gets `head != source_head` and `state != current`, then raises
  `cannot locate the migration commit` (`app/orchestra_layout.py:739-744`). I reproduced this exact
  error on a `cp -a` copy before changing anything.
- Why blindly finishing the recovery would have been wrong: had only the layout been fixed and the
  journal left in place, recovery would call `_restore_preserved_stash`. That writes the WHOLE 20.09
  `AGENTS.md` over the current one, rolling back 5 commits of rules in the working tree. The status
  check would then fail anyway, because the tree now has other dirty files. So the journal had to be
  resolved by hand.

## What was pinned before any change

Refs in `/opt/cog-second-brain/.git`, created before the first mutation:

| ref | object | what it keeps |
|---|---|---|
| `refs/preserve/V-632/stash-fb3d4d` | commit `fb3d4dacea5555353b666e47d0a4e9a27d1770a8` | the preserve stash (with `^2` index, `^3` untracked) |
| `refs/preserve/V-632/stash-76ea1e` | commit `76ea1e77fc10ef1f71186190c3beca1d5cd83e86` | owner's older stash `pre-sync-2026-08-16-1618`, not touched, pinned for safety |
| `refs/preserve/V-632/head-before` | commit `91dd892e3ad6d7d0fdf60f24db67557a2ecb4213` | HEAD before the repair |
| `refs/preserve/V-632/worktree-before` | commit `fac96e21f4860c7acaca4ed2e8c3d18a9e5028a9` | full working tree incl. untracked files (temp index, `add -A`, parent = HEAD) |
| `refs/preserve/V-632/preserve-journal` | blob `d1d49f1a05fa37ac422ff1bb90dffc2f594d642b` | the preserve journal bytes |
| `refs/preserve/V-632/hashes-before` | blob `a5e14ca11c95078ebcea39e85879ceff2d7ca152` | sha256 of every dirty/untracked file, `AGENTS.md`, the stash's `AGENTS.md` and the three `retro.md` |

The hash list stays inside cog's private repo: file names under `02-personal/` are personal, and
Orchestra's origin is public. A copy is at `/home/kesha/v632-cog/hashes-before.txt`. Before the
repair the dirty set was one modified file under `02-personal/katya/`, a modified `CLAUDE.md`
(regular file) and seven untracked files under `02-personal/drive-audit/`. Ignored files were
outside the snapshot, and nothing in the repair touches them.

## What was done

Everything in [repair.sh](repair.sh) runs under `app.workspace.repo_mutation_lock('/opt/cog-second-brain')`.
The script aborts on any precondition mismatch: HEAD must be `91dd892`, the index must be empty,
`docs/tasks` must contain exactly the three `retro.md` files, and no target may already exist.

1. `git mv docs/tasks/<id>/retro.md .orchestra/tasks/<id>/retro.md` for V-1, V-2, V-19. Then `rmdir`
   the empty directories (non-recursive). The staged set is exactly three `R100` renames, and it was
   committed as `91da094 Orchestra: migrate project state to .orchestra`. The message matches what
   the migration code uses. The author is the repo's configured identity, per the global rule against
   overriding `user.name/email`; the code's own `-c user.name=Orchestra` was not used. None of the
   owner's uncommitted edits entered the commit.
2. Stash vs. tree had different versions of `AGENTS.md`. Neither was picked silently: the stash's
   delta (`git diff 2b0dff6d fb3d4d -- AGENTS.md`) was put back on top of the current `AGENTS.md`
   with `git apply`, and it applied cleanly as an **unstaged** change. The working-tree `AGENTS.md`
   now has all committed content plus the two restored lines. The committed version is in HEAD, and
   the 20.09 full version stays in the stash and its ref. Nothing else from the stash needed restoring.
3. The preserve journal was moved, not deleted, to
   `/home/kesha/v632-cog/live-journal/orchestra-layout-preserve.json`. Its bytes are also pinned as a
   blob ref.
4. **Not done on purpose:** no `stash drop/clear`, `reset`, `clean` or `checkout`. `fb3d4d` is still
   `stash@{0}`. It is redundant now, but dropping it gains nothing. The owner may drop it; the ref
   keeps it either way.

## Byte-level verification

[verify.sh](verify.sh), run on the live repo after the repair (`live-verify.log`: `VERIFY_OK`), checks:

- sha256 of all 9 pre-repair dirty/untracked files still match `hashes-before`;
- each moved `retro.md` has the same blob id in `head-before:docs/tasks/…`, on disk and in the new
  HEAD;
- the lines `AGENTS.md` changes against HEAD are exactly the lines the stash changed against
  `source_head`;
- `head-before..HEAD` changes only the six rename paths, and `head-before` is an ancestor of HEAD
  (no history rewritten);
- all six `refs/preserve/V-632/*` objects exist, and the stash list is unchanged (`fb3d4d`, `76ea1e`).

## Startup check on copies

No restart. Logs: `copy-check.log`, `post-live-check.log`; personal file names are redacted there.

- Rehearsal: a `cp -a` copy of the pre-repair repo reproduced `cannot locate the migration commit…`.
  After `repair.sh` it gave `VERIFY_OK`. The startup entry point then ran twice with the `main` code
  (`fix-cog-layout/app/orchestra_layout.py`) → `already_current` both times, with a full stash/restore
  transaction because the tree is dirty. `VERIFY_OK` after each run, and the stash list was unchanged.
- The same on a second copy with the V-629 code (`fix-layout-loss/app/orchestra_layout.py`) →
  `already_current` twice with no stash transaction, `VERIFY_OK`.
- After the live repair: a fresh `cp -a` of the live repo → `already_current`, `VERIFY_OK`.
  `require_project_layout('/opt/cog-second-brain')` on the live repo (read-only) returned
  `/opt/cog-second-brain/.orchestra`.
- The test copies were moved to trash with `trash-put`, not deleted.

The live tree did not change during the work. HEAD and the dirty-file hashes were re-checked right
before the repair and matched the pinned state.

## Remaining risks

- **It will recur.** cog's skills (`self-analysis`, `codex-debate`, in `.claude/` and `.codex/`)
  still write to `docs/tasks/`. The next such write makes cog `ORCHESTRA_LAYOUT_PARTIAL` again. It
  would be `PARTIAL`, not a stuck journal: the main code stashes and then raises inside
  `migrate_project_layout`, which recreates exactly the 20.09 scenario. Fixing it means editing cog's
  files, which is outside this task; recorded in `TODO.md`.
- Until V-629 is merged, the `main` code runs a stash/restore transaction over the dirty cog tree on
  every start (seen on the copy). V-629 removes that.
- The restored `AGENTS.md` edit is now visible as an ordinary uncommitted change. Whether it is
  committed and synced into `CLAUDE.md` (no longer a symlink since `ceb6d3e`) is the owner's call.

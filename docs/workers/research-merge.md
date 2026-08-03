# Worker memory

- Documenting a period takes TWO passes; the count alone is not enough.
  1. Scope against `main`, not my branch: my worktree log stopped at 02.08 (66
     commits), `git log main` had 93 plus a whole extra day. Count by date
     (`... | awk '{print $2}' | sort | uniq -c`) — the orchestrator's own "93 за
     01-02.08" came from `--since="2 days ago"` and silently dropped 03.08.
  2. Then read `docs/tasks/<id>/report.md` for every id in range. This is the pass
     that found the substance: #113 withdrew all three of its own optimizations
     after measuring, #121 was a refuted claim. No commit count surfaces a
     withdrawn or negative result — the log tells me WHICH tasks, the reports tell
     me WHAT actually happened, and hint lists drop exactly the negatives.

- Reachability is not revertability — check BOTH, and I checked only one. #106's
  rollback file said `git revert 8b5392d`: pre-squash worker commit, unreachable
  from `main` (`git merge-base --is-ancestor` → false). I reported `f796a08` as
  "the working one" on that basis. It is not: later commits (#126) touched the
  same zone, so `git revert f796a08` conflicts — the orchestrator found this by
  running it. Ancestor check proves the SHA EXISTS on main; only a real
  `git revert --no-commit` on a scratch branch (then `git revert --abort`) proves
  the command in the doc still works. For any rollback instruction I write or
  validate: run it, don't reason about it.

- Docs edits belong in MY worktree, not the main checkout. I edited
  `/mnt/data/Projects/Python/orchestra/CHANGELOG.md` directly and had to rescue it
  with `git diff > /tmp/x.patch`, `git checkout --`, then `git apply` in the
  worktree. Check `git rev-parse --abbrev-ref HEAD` before the first edit — if it
  says `main`, I am in the wrong tree.

- A task list from the orchestrator is a hint, not a source. In #130 it was
  incomplete (missing 03.08) and one item was phrased wider than its evidence
  (#126's failure point). Checking it cost minutes; taking it on faith would have
  shipped both errors into a document later read as truth. Verify the premise
  even when the person giving it is senior to me — especially then, since nobody
  downstream will catch it.

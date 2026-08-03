# Worker memory

- My worktree branch can be many commits behind `main`. `git log` inside the
  worktree showed 66 commits and stopped at 02.08; `git log main` from the main
  checkout showed 93 including a whole day of work I would have silently omitted.
  For any "what happened in period X" task, run the log against `main` explicitly
  and count by date (`... | awk '{print $2}' | sort | uniq -c`) before writing.

- A SHA quoted in a task's own `rollback.md` is not necessarily revertable. #106's
  rollback file said `git revert 8b5392d` — that is the pre-squash worker commit,
  unreachable from `main` (`git merge-base --is-ancestor` → false); the usable one
  is the squash commit `f796a08`. Every SHA I put in docs gets an ancestor check
  against `main` first, because squash-merge gives the same change two identities.

- Docs edits belong in MY worktree, not the main checkout. I edited
  `/mnt/data/Projects/Python/orchestra/CHANGELOG.md` directly and had to rescue it
  with `git diff > /tmp/x.patch`, `git checkout --`, then `git apply` in the
  worktree. Check `git rev-parse --abbrev-ref HEAD` before the first edit — if it
  says `main`, I am in the wrong tree.

- When a task hands me a list of "what to write about", the list is a hint. In
  #130 the reports contained material the list omitted (#113 withdrew all three
  of its own optimizations after measuring; #121 was a refuted claim) and phrased
  one item more broadly than the evidence. Read `docs/tasks/<id>/report.md` for
  every id in the range — the negative and withdrawn results are the ones a hint
  list drops, and they are worth recording.

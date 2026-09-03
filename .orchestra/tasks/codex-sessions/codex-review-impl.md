The persistent-session flow can overwrite existing review history in a documented fallback path and can still dirty pre-existing worktrees with local metadata. These are functional regressions in the new resume/metadata behavior.

Full review comments:

- [P2] Preserve history when resume metadata is missing — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-codex-sessions/app/mcp_stdio.py:763-763
  When `resume=True` but no UUID is found, for example because `jq` was unavailable on the first run or `codex_sessions.json` was deleted, `is_resume` stays false and `codex_out` points at `output_abs`. The fresh fallback then writes via `-o` directly to the existing review file, replacing prior review/debate history instead of appending a fallback round under the missing-metadata case.

- [P2] Ignore Codex metadata for existing worktrees — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-codex-sessions/app/mcp_stdio.py:748-748
  This stores `codex_sessions.json` next to the review output, but the new ignore patterns are only installed from `create_worktree`. Any already-created worker/orchestrator session that starts using the updated tool before those excludes are added will produce untracked metadata, so the existing `git status --porcelain` checks in merge/delete can still reject an otherwise clean worktree.
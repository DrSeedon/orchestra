You are in a disposable clean snapshot of Orchestra. Make both requested refactors in this
snapshot. Do not commit, do not modify configuration, do not access services or external APIs,
and do not change behavior or weaken/remove/skip tests. Native repository tools remain available;
if an additional code-intelligence MCP is present, use it only when it helps and verify its output
against source/text where strings, decorators, or comments may matter.

Task 1: Rename the Python callable `pace_text` to `format_pace_text` across `app/` and `tests/`.
Preserve behavior, all user-facing strings, and the existing `_pace_of` local alias.

Task 2: Rename the Python callable `inject_skills_to_worktree` to
`install_skills_to_worktree` across `app/` and `tests/`, including imports, calls,
comments/docstrings that name this callable, and `monkeypatch`/`patch` string paths. Do not rename
`inject_skills_to_worktree_report` and do not change behavior.

Run focused tests you judge sufficient and leave the complete uncommitted diff in the snapshot for
an external mechanical scorer. End with a concise report of commands and outcomes.


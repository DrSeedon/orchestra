"""Hard ceiling on unreviewable agent diffs (#250).

Insertions count; deletions do not. Dead-code removal stays healthy.
The agent cannot waive this: merge_worktree_to_main calls it, and that
is the only landing path.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# Backtest `git log main --no-merges --numstat`, 1871 commits (2026-08-14):
# 800 insertions refused 155 (8.3%) and cut real features (#174 991, #187 983,
# Codex runtime 878). 2000 refuses 48 (2.6%) and still catches the 25k dumps
# the ticket named as unreviewable. Deletions do not count.
MAX_DIFF_INSERTIONS = 2000
_ORCH_ROLES = frozenset({"orchestrator", "sub-orchestrator"})
# git's well-known empty tree: the base for branches with no common ancestor.
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def measure_insertions(worktree: str, base_ref: str) -> int:
    """Insertions in worktree vs merge-base(HEAD, base_ref), plus untracked files."""
    wt = str(Path(worktree))
    mb = _run(["git", "merge-base", "HEAD", base_ref], wt)
    if mb.returncode != 0 or not mb.stdout.strip():
        # No common ancestor (orphan branch, worker from another repo): the merge
        # falls back to cherry-pick and introduces the whole branch, so the empty
        # tree is the honest base. A base_ref that does not resolve stays loud.
        if _run(["git", "rev-parse", "--verify", f"{base_ref}^{{commit}}"], wt).returncode != 0:
            raise RuntimeError(
                f"cannot resolve merge-base with {base_ref!r}: "
                f"{(mb.stderr or mb.stdout).strip() or f'exit {mb.returncode}'}"
            )
        base = _EMPTY_TREE
    else:
        base = mb.stdout.strip()
    diff = _run(["git", "diff", "--numstat", base], wt)
    if diff.returncode != 0:
        raise RuntimeError(
            f"git diff --numstat failed: {(diff.stderr or diff.stdout).strip()}"
        )
    insertions = 0
    for line in diff.stdout.splitlines():
        fields = line.split("\t", 2)
        if len(fields) != 3 or fields[0] == "-":
            continue
        insertions += int(fields[0])
    untracked = _run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], wt,
    )
    if untracked.returncode == 0 and untracked.stdout:
        for rel in untracked.stdout.split("\0"):
            if not rel:
                continue
            path = Path(wt) / rel
            try:
                insertions += path.read_text(encoding="utf-8", errors="replace").count("\n")
            except OSError:
                continue
    return insertions


def budget_error(insertions: int, limit: int = MAX_DIFF_INSERTIONS) -> str:
    if insertions <= limit:
        return ""
    return (
        f"DIFF TOO LARGE: {insertions} insertions (limit {limit}). "
        "Deletions do not count. Split into smaller changes and merge those, "
        "or ask the orchestrator to retry with waive_diff_budget=True. "
        "Do not truncate the work silently."
    )


def may_waive_diff_budget(
    *,
    caller_role: str = "",
    cookie_ok: bool = False,
    caller_is_orchestrator: bool = False,
) -> bool:
    """Human cookie or an orchestrator session may waive. Workers may not."""
    if cookie_ok or caller_is_orchestrator:
        return True
    return caller_role.strip().lower() in _ORCH_ROLES


def request_may_waive_diff_budget(request) -> bool:
    """Cookie or a proof-bound MCP session. Session-id alone is not identity."""
    from app.mcp_proof import caller_may_use_orchestrator_privilege

    return caller_may_use_orchestrator_privilege(request)


def _run(argv: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)

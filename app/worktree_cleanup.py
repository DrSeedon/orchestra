"""Free space in a worker worktree without losing data (V-984).

A worker copy keeps growing from the ignored output of its own tasks (renders, decks, downloaded
sources). After the task is merged that output is usually also somewhere durable: the same content
is a blob in the target branch, or the orchestrator copied the file into the main checkout. This
module deletes only files that are provably recoverable and leaves everything else in place.

A file is deleted only when ALL hold:
- the worktree is clean (`git status --porcelain` empty, no merge/rebase in progress) and no process
  works inside it (cwd) or holds a file in it open;
- git ignores the file through a `.gitignore` tracked in the repository — not through
  `info/exclude` or a global excludes file, which is where Orchestra and the user mark files they
  planted (`.claude/`, `AGENTS.md`, copied `.env`);
- the path is not a file Orchestra copies into every worktree, and it is not inside an environment
  directory (`.venv`, `node_modules`, …): those are identical to the main checkout by construction
  and deleting them breaks the worker;
- and its content survives elsewhere: its blob id is in the target branch tree, or the same path in
  the main checkout is a regular file with the same bytes; or it lies in a pure cache directory
  (`__pycache__`, `.pytest_cache`, …) that tools rebuild.
A file whose only copy is this worktree is never deleted. Each file is re-checked (size and mtime)
right before it is unlinked; directories emptied by the deletion are removed, nothing else.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

CACHE_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
ENV_DIRS = frozenset({".venv", "venv", "node_modules", ".git"})
PLANTED = frozenset({"CLAUDE.md", "AGENTS.md", ".mcp.json", ".env", ".worktreeinclude"})
_IN_PROGRESS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")

Git = Callable[..., subprocess.CompletedProcess]


def _run(args: list[str], **kw) -> subprocess.CompletedProcess:
    kw.setdefault("capture_output", True)
    return subprocess.run(args, **kw)


def holders(path: Path) -> list[int]:
    """PIDs that work inside `path` (cwd) or hold a file under it open."""
    root = str(path)
    prefix = root + os.sep
    found: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        links = [entry / "cwd"]
        try:
            links += [entry / "fd" / fd for fd in os.listdir(entry / "fd")]
        except OSError:
            pass
        for link in links:
            try:
                target = os.readlink(link)
            except OSError:
                continue
            if target == root or target.startswith(prefix):
                found.append(int(entry.name))
                break
    return found


def _refusal(wt: Path, git: Git) -> str:
    status = git(["git", "status", "--porcelain"], cwd=str(wt), text=True)
    if status.returncode != 0:
        return f"git status failed: {status.stderr.strip()}"
    lines = [line for line in status.stdout.splitlines() if line.strip()]
    if lines:
        return f"{len(lines)} uncommitted path(s): " + ", ".join(line[3:] for line in lines[:5])
    for marker in _IN_PROGRESS:
        found = git(["git", "rev-parse", "--git-path", marker], cwd=str(wt), text=True).stdout.strip()
        if found and (Path(found) if os.path.isabs(found) else wt / found).exists():
            return f"{marker} in progress"
    busy = holders(wt)
    if busy:
        return f"process(es) use it: {busy[:5]}"
    return ""


def _ignored_by_repo(wt: Path, rels: list[str], git: Git) -> set[str]:
    """Subset of `rels` ignored by a tracked .gitignore inside the repository."""
    if not rels:
        return set()
    res = git(["git", "check-ignore", "-v", "-z", "--stdin"], cwd=str(wt),
              input=b"\0".join(r.encode() for r in rels) + b"\0")
    fields = res.stdout.split(b"\0")
    out = set()
    for i in range(0, len(fields) - 3, 4):
        source, _line, pattern, path = fields[i:i + 4]
        src = source.decode(errors="replace")
        if not src or os.path.isabs(src) or src.startswith(".git/") or pattern.startswith(b"!"):
            continue
        out.add(path.decode(errors="surrogateescape"))
    return out


def _tree_blobs(wt: Path, ref: str, git: Git) -> dict[int, set[str]]:
    res = git(["git", "ls-tree", "-r", "-l", "-z", ref], cwd=str(wt))
    blobs: dict[int, set[str]] = {}
    if res.returncode != 0:
        return blobs
    for rec in res.stdout.split(b"\0"):
        meta = rec.split(b"\t", 1)[0].split()
        if len(meta) == 4 and meta[1] == b"blob" and meta[3].isdigit():
            blobs.setdefault(int(meta[3]), set()).add(meta[2].decode())
    return blobs


def _hash(path: Path, wt: Path, git: Git) -> str:
    res = git(["git", "hash-object", "--no-filters", "--", str(path)], cwd=str(wt), text=True)
    return res.stdout.strip() if res.returncode == 0 else ""


def _same_bytes(a: Path, b: Path) -> bool:
    with a.open("rb") as fa, b.open("rb") as fb:
        while True:
            x, y = fa.read(1 << 20), fb.read(1 << 20)
            if x != y:
                return False
            if not x:
                return True


def _ignored_files(wt: Path, git: Git) -> list[str]:
    res = git(["git", "ls-files", "-z", "--others", "--ignored", "--exclude-standard"], cwd=str(wt))
    return [p.decode(errors="surrogateescape") for p in res.stdout.split(b"\0") if p]


def clean_worktree(worktree_path: str, *, main_checkout: str, target_ref: str,
                   apply: bool = False, git: Git = _run) -> dict:
    """Delete recoverable ignored output from a worker worktree. Dry run unless `apply`.

    Returns {"state": refused|planned|cleaned, "reason"?, "files", "bytes", "by_reason",
    "kept_unique_bytes", "kept_unique_files", "kept_top"}."""
    wt = Path(worktree_path).resolve()
    main = Path(main_checkout).resolve()
    if wt == main:
        return {"state": "refused", "reason": "this is the main checkout"}
    reason = _refusal(wt, git)
    if reason:
        return {"state": "refused", "reason": reason}
    candidates = []
    for rel in _ignored_files(wt, git):
        parts = rel.split("/")
        if any(p in ENV_DIRS for p in parts[:-1]) or rel in PLANTED:
            continue
        full = wt / rel
        if full.is_symlink() or not full.is_file():
            continue
        candidates.append(rel)
    repo_ignored = _ignored_by_repo(wt, candidates, git)
    blobs = _tree_blobs(wt, target_ref, git)
    plan: list[tuple[str, int, int, str]] = []
    kept_bytes = kept_files = 0
    kept_dirs: dict[str, int] = {}
    for rel in candidates:
        full = wt / rel
        st = full.stat()
        why = ""
        if rel not in repo_ignored:
            pass
        elif any(p in CACHE_DIRS for p in rel.split("/")[:-1]):
            why = "cache"
        else:
            twin = main / rel
            if st.st_size in blobs and _hash(full, wt, git) in blobs[st.st_size]:
                why = "in_target_branch"
            elif (twin.is_file() and not twin.is_symlink() and twin.stat().st_size == st.st_size
                  and twin.resolve() != full.resolve() and _same_bytes(full, twin)):
                why = "in_main_checkout"
        if why:
            plan.append((rel, st.st_size, st.st_mtime_ns, why))
        else:
            kept_files += 1
            kept_bytes += st.st_size
            top = "/".join(rel.split("/")[:2]) if "/" in rel else rel
            kept_dirs[top] = kept_dirs.get(top, 0) + st.st_size
    by_reason: dict[str, int] = {}
    deleted = []
    if apply:
        # Re-check right before deleting: nothing may have started using the copy meanwhile.
        reason = _refusal(wt, git)
        if reason:
            return {"state": "refused", "reason": reason}
        for rel, size, mtime, why in plan:
            full = wt / rel
            try:
                st = full.lstat()
                if not full.is_file() or st.st_size != size or st.st_mtime_ns != mtime:
                    continue
                full.unlink()
            except OSError:
                continue
            deleted.append((rel, size, why))
        for d in sorted({str(Path(r).parent) for r, _, _ in deleted}, key=len, reverse=True):
            p = wt / d
            while p != wt and p.is_dir():
                try:
                    p.rmdir()
                except OSError:
                    break
                p = p.parent
    else:
        deleted = [(rel, size, why) for rel, size, _m, why in plan]
    for _rel, size, why in deleted:
        by_reason[why] = by_reason.get(why, 0) + size
    return {
        "state": "cleaned" if apply else "planned",
        "files": len(deleted), "bytes": sum(s for _, s, _ in deleted), "by_reason": by_reason,
        "kept_unique_files": kept_files, "kept_unique_bytes": kept_bytes,
        "kept_top": sorted(kept_dirs.items(), key=lambda kv: -kv[1])[:5],
        "sample": [r for r, _, _ in deleted[:5]],
    }

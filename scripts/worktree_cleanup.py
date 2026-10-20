#!/usr/bin/env python3
"""Free space in worker worktrees by deleting recoverable ignored output (V-984).

Dry run by default; the rule is in app/worktree_cleanup.py. With no paths it walks every worktree
under Orchestra's worktree root
(`--root` when run from a checkout other than the live one).

    uv run --frozen python scripts/worktree_cleanup.py [--apply] [<worktree> ...]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.workspace import WORKTREE_ROOT, _resolve_repo, resolve_base_branch  # noqa: E402
from app.worktree_cleanup import clean_worktree  # noqa: E402


def worktrees(root: Path) -> list[Path]:
    found = []
    for gitfile in sorted(root.glob("*/.git")) + sorted(root.glob("*/*/.git")):
        if gitfile.is_file():
            found.append(gitfile.parent)
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("worktrees", nargs="*")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", type=Path, default=WORKTREE_ROOT, help="worktree root to walk")
    args = ap.parse_args()
    paths = [Path(p) for p in args.worktrees] or worktrees(args.root)
    total = 0
    for wt in paths:
        try:
            repo = _resolve_repo(str(wt), str(wt))
            ref = resolve_base_branch(str(repo), "")
            res = clean_worktree(str(wt), main_checkout=str(repo), target_ref=ref, apply=args.apply)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
            res = {"state": "error", "reason": str(e)}
        total += res.get("bytes", 0)
        print(json.dumps({"worktree": str(wt), **res}, ensure_ascii=False), flush=True)
    print(json.dumps({"total_bytes": total, "apply": args.apply}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

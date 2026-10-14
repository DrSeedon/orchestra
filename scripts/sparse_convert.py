#!/usr/bin/env python3
"""Move existing full worker worktrees onto the sparse-copy rule (V-821).

Dry run by default. Per worktree it refuses, changing nothing, when the tree has modified or
untracked files, a merge/rebase is in progress, or a process works inside it (--allow-busy lifts
the last one: only committed files outside the rule leave the disk, and they stay readable from
the main checkout).

    uv run --frozen python scripts/sparse_convert.py <worktree> [<worktree> ...]          # what would happen
    uv run --frozen python scripts/sparse_convert.py --apply <worktree> ...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline import get_worktree_config  # noqa: E402
from app.workspace import convert_worktree_to_sparse  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("worktrees", nargs="+")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--allow-busy", action="store_true")
    ap.add_argument("--pipeline", default="default")
    args = ap.parse_args()
    cfg = get_worktree_config(args.pipeline)
    failed = False
    for path in args.worktrees:
        result = convert_worktree_to_sparse(path, cfg, apply=args.apply, allow_busy=args.allow_busy)
        failed = failed or result["state"] == "failed"
        print(path, json.dumps(result, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

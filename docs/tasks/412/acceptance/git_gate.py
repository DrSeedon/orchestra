#!/usr/bin/env python3
"""External exec gate for the live #412 distribution Git process."""

from __future__ import annotations

import json
import os
import sys


READ_ONLY = {
    "check-ignore",
    "config",
    "ls-files",
    "ls-remote",
    "ls-tree",
    "rev-parse",
    "show",
    "show-ref",
    "status",
    "symbolic-ref",
}


def _subcommand(args: list[str]) -> str:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in {"-C", "-c", "--git-dir", "--work-tree"} else 1
    return args[index] if index < len(args) else ""


def main() -> int:
    args = sys.argv[1:]
    subcommand = _subcommand(args)
    row = {
        "run_id": os.environ["ORCHESTRA_412_RUN_ID"],
        "subcommand": subcommand,
        "repository": args[args.index("-C") + 1] if "-C" in args else "",
    }
    with open(os.environ["ORCHESTRA_412_GIT_LOG"], "a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    allowed = subcommand in READ_ONLY
    if subcommand == "config":
        allowed = "--list" in args or "--get-regexp" in args
    elif subcommand == "symbolic-ref":
        allowed = args[-2:] == ["-q", "HEAD"]
    if not allowed:
        return 97
    os.execv(os.environ["ORCHESTRA_412_REAL_GIT"], [os.environ["ORCHESTRA_412_REAL_GIT"], *args])
    return 127


if __name__ == "__main__":
    raise SystemExit(main())

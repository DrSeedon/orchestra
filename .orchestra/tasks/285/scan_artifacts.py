#!/usr/bin/env python3
"""Count secret-shaped files without emitting matching bytes."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


PATTERN = re.compile(
    b"(?:"
    + b"y0" + b"_[A-Za-z0-9_-]{16,}"
    + b"|sk-or-" + b"v1-[A-Za-z0-9_-]{16,}"
    + b"|ya" + b"29\\.[A-Za-z0-9._-]{16,}"
    + b"|gh[pousr]" + b"_[A-Za-z0-9_]{16,}"
    + b"|AIza" + b"[A-Za-z0-9_-]{20,}"
    + b"|GOCSPX" + b"-[A-Za-z0-9_-]{12,}"
    + b"|Bearer\\s+" + b"[A-Za-z0-9._~+/=-]{25,}"
    + b"|https?://[^/\\s:@]+:" + b"[^@\\s/]+@"
    + b")"
)


def scan_path(path: Path) -> dict[str, int | str]:
    files = sorted(p for p in (path.rglob("*") if path.is_dir() else [path]) if p.is_file())
    matched = scanned_bytes = readable = 0
    for item in files:
        try:
            payload = item.read_bytes()
        except OSError:
            continue
        readable += 1
        scanned_bytes += len(payload)
        matched += bool(PATTERN.search(payload))
    return {"scope": str(path), "readable_files": readable, "scanned_bytes": scanned_bytes, "matched_files": matched}


def scan_commit(ref: str) -> dict[str, int | str]:
    names = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "-z", ref, "--", "docs/tasks/285", "docs/artifacts/model-limits-source-of-truth.html"],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout.split(b"\0")
    matched = scanned_bytes = readable = 0
    for raw_name in names:
        if not raw_name:
            continue
        payload = subprocess.run(
            ["git", "show", f"{ref}:{raw_name.decode()}"],
            check=True,
            stdout=subprocess.PIPE,
        ).stdout
        readable += 1
        scanned_bytes += len(payload)
        matched += bool(PATTERN.search(payload))
    return {"scope": f"commit:{ref}", "readable_files": readable, "scanned_bytes": scanned_bytes, "matched_files": matched}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--commit", action="append", default=[])
    args = parser.parse_args()
    result = [scan_path(Path(path)) for path in args.path]
    result.extend(scan_commit(ref) for ref in args.commit)
    print(json.dumps(result, ensure_ascii=False))
    if any(row["matched_files"] for row in result):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

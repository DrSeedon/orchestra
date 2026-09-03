#!/usr/bin/env python3
"""Freeze the exact pre-migration historical evidence binding set for #430."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


FIELDS = ("stable_id", "git_commit", "source_path", "git_blob", "source_sha256")


def canonical(value) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output

    bindings = {}
    for record_path in sorted((root / "docs/kb/records").rglob("*.json")):
        value = json.loads(record_path.read_text(encoding="utf-8"))
        if not set(FIELDS) <= set(value):
            continue
        binding = {field: str(value[field]) for field in FIELDS}
        stable_id = binding["stable_id"]
        if stable_id in bindings:
            raise SystemExit(f"duplicate historical stable_id: {stable_id}")
        bindings[stable_id] = hashlib.sha256(canonical(binding)).hexdigest()
    if not bindings:
        raise SystemExit("historical binding set is empty")
    bindings = dict(sorted(bindings.items()))
    manifest = {
        "schema_version": 1,
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "count": len(bindings),
        "binding_set_sha256": hashlib.sha256(canonical(bindings)).hexdigest(),
        "bindings": bindings,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical(manifest) + b"\n")
    print(
        f"count={manifest['count']} binding_set_sha256={manifest['binding_set_sha256']} "
        f"output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

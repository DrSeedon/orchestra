#!/usr/bin/env python3
"""Freeze pytest collection and balance whole test files across deterministic shards."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--shards", type=int, default=6)
    args = parser.parse_args()
    if args.shards < 1:
        raise SystemExit("--shards must be positive")

    nodes = [
        line.strip()
        for line in args.collection.read_text(encoding="utf-8").splitlines()
        if line.startswith("tests/") and "::" in line
    ]
    if not nodes or len(nodes) != len(set(nodes)):
        raise SystemExit("collection must contain unique pytest node ids")

    counts = Counter(node.split("::", 1)[0] for node in nodes)
    buckets: list[list[str]] = [[] for _ in range(args.shards)]
    weights = [0] * args.shards
    for test_file, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        target = min(range(args.shards), key=lambda index: (weights[index], index))
        buckets[target].append(test_file)
        weights[target] += count

    args.output_dir.mkdir(parents=True, exist_ok=True)
    collection_path = args.output_dir / "collection.txt"
    collection_path.write_text("\n".join(nodes) + "\n", encoding="utf-8")
    shard_rows = []
    for index, (files, weight) in enumerate(zip(buckets, weights, strict=True), start=1):
        shard_path = args.output_dir / f"shard-{index}.txt"
        shard_path.write_text("\n".join(sorted(files)) + "\n", encoding="utf-8")
        shard_rows.append({"shard": index, "collected_nodes": weight, "files": len(files)})

    manifest = {
        "schema_version": 1,
        "base_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "selected_nodes": len(nodes),
        "test_files": len(counts),
        "shards": shard_rows,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

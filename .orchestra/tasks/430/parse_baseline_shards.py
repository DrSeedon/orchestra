#!/usr/bin/env python3
"""Validate six pytest shard logs against the frozen collection manifest."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


STATUSES = ("PASSED", "FAILED", "SKIPPED", "XFAIL", "XPASS", "ERROR")


def parse_log(path: Path) -> list[tuple[str, str]]:
    observed: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("tests/"):
            continue
        matches: list[tuple[int, str]] = []
        for status in STATUSES:
            marker = f" {status}"
            offset = line.rfind(marker)
            if offset >= 0:
                matches.append((offset, status))
        if not matches:
            continue
        offset, status = max(matches)
        node = line[:offset].rstrip()
        if node in seen:
            raise SystemExit(f"duplicate status for {node}")
        seen.add(node)
        observed.append((node, status))
    return observed


def stable_rows(rows: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """Replace volatile pytest parameter values with their stable collection ordinal."""
    totals = Counter(node.rsplit("[", 1)[0] if node.endswith("]") else node for node, _ in rows)
    indexes: Counter[str] = Counter()
    result = []
    for raw_node, status in rows:
        base = raw_node.rsplit("[", 1)[0] if raw_node.endswith("]") else raw_node
        if totals[base] > 1 or raw_node != base:
            indexes[base] += 1
            stable_node = f"{base}[#{indexes[base]}]"
        else:
            stable_node = base
        result.append((stable_node, raw_node, status))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.dir
    collection = [
        line.strip()
        for line in (root / "collection.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    collected = set(collection)
    if len(collection) != len(collected):
        raise SystemExit("collection contains duplicate node ids")
    stable_collection_rows = stable_rows([(node, "COLLECTED") for node in collection])
    stable_collection = {stable for stable, _, _ in stable_collection_rows}
    if len(stable_collection) != len(collection):
        raise SystemExit("stable collection identities are not unique")

    all_observed: dict[str, tuple[str, str]] = {}
    shard_results = []
    for shard in range(1, 7):
        rc = int((root / f"shard-{shard}.rc").read_text().strip())
        if rc not in {0, 1}:
            raise SystemExit(f"shard {shard} incomplete: RC={rc}")
        raw_observed = parse_log(root / f"shard-{shard}.log")
        observed = stable_rows(raw_observed)
        overlap = sorted(set(all_observed) & {stable for stable, _, _ in observed})
        if overlap:
            raise SystemExit(f"nodes executed by multiple shards: {overlap[:3]}")
        all_observed.update(
            {stable: (raw, status) for stable, raw, status in observed}
        )
        shard_results.append(
            {
                "shard": shard,
                "rc": rc,
                "statuses": dict(sorted(Counter(status for _, _, status in observed).items())),
                "observed_nodes": len(observed),
            }
        )

    missing = sorted(stable_collection - set(all_observed))
    extra = sorted(set(all_observed) - stable_collection)
    if missing or extra:
        raise SystemExit(
            f"status/collection mismatch: missing={missing[:3]} ({len(missing)}), "
            f"extra={extra[:3]} ({len(extra)})"
        )

    failures = sorted(
        node for node, (_, status) in all_observed.items() if status in {"FAILED", "ERROR"}
    )
    (root / "failures.txt").write_text("\n".join(failures) + "\n", encoding="utf-8")
    raw_failures = sorted(
        raw for raw, status in all_observed.values() if status in {"FAILED", "ERROR"}
    )
    (root / "failures-raw.txt").write_text(
        "\n".join(raw_failures) + "\n", encoding="utf-8"
    )
    raw_collection = {raw for _, raw, _ in stable_collection_rows}
    raw_observed = {raw for raw, _ in all_observed.values()}
    summary = {
        "schema_version": 1,
        "collection_nodes": len(collection),
        "observed_nodes": len(all_observed),
        "coverage_equal": set(all_observed) == stable_collection,
        "raw_nodeid_symmetric_difference": len(raw_collection ^ raw_observed),
        "statuses": dict(
            sorted(Counter(status for _, status in all_observed.values()).items())
        ),
        "failed_or_error_nodes": len(failures),
        "shards": shard_results,
        "worktree_status_after": (root / "worktree-status-after.txt").read_text(
            encoding="utf-8"
        ).splitlines(),
    }
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

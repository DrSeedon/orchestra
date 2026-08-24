#!/usr/bin/env python3
"""Deterministic integrity checks for normalized #313 machine evidence."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def load_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main() -> None:
    inventory = load_json("docs/tasks/313/inventory.json")
    static = load_json("docs/tasks/313/evidence/static-signals.json")
    candidates = list(csv.DictReader((ROOT / "docs/tasks/313/candidates.csv").open(encoding="utf-8")))
    expected_summary = {
        "test_files": 153,
        "test_source_loc": 78491,
        "test_nonblank_loc": 65583,
        "source_test_definitions": 2886,
    }
    assert inventory["baseline"]["main_sha"] == "1d9be7ae8511a1c5657362cc56eef395b4585bf2"
    assert inventory["summary"] == expected_summary, inventory["summary"]
    assert inventory["collection"]["total_nodes"] == 3284
    assert inventory["collection"]["default_selected_nodes"] == 3281
    assert inventory["collection"]["deselected_live_nodes"] == 3
    assert inventory["collection"]["live_probe_nodes"] == 3
    assert len(inventory["collection"]["node_ids"]) == 3281
    assert len(inventory["files"]) == 153
    assert len(inventory["nodes"]) == 2886
    file_rows = {row["file"]: row for row in inventory["files"]}
    assert all(row.get("imported_production_symbols") is not None for row in file_rows.values())
    assert all("imports_production" not in node and "imported_production_symbols" not in node for node in inventory["nodes"])
    assert all(node["file_imports_ref"] in file_rows for node in inventory["nodes"])

    assert static["summary"] == {
        "files": 153,
        "source_test_definitions": 2886,
        "source_test_loc": 78491,
        "nonblank_test_loc": 65583,
        "exact_duplicate_clusters": 0,
        "exact_duplicate_nodes_in_clusters": 0,
        "near_duplicate_pairs_lower_bound": 1,
    }
    assert all("imports_production" not in node and "file_imports_ref" in node for node in static["tests"])
    assert all("imported_production_symbols" in row for row in static["files"])

    verdicts = Counter(row["verdict KEEP/MERGE/REWRITE/DELETE/UNKNOWN"] for row in candidates)
    assert len(candidates) == 12
    assert verdicts == Counter({"KEEP": 6, "REWRITE": 4, "UNKNOWN": 2})
    assert all(row["verdict KEEP/MERGE/REWRITE/DELETE/UNKNOWN"] not in {"DELETE", "MERGE"} for row in candidates)

    metrics = (ROOT / "docs/tasks/313/metrics.md").read_text(encoding="utf-8")
    for phrase in (
        "153 `tests/*.py` files",
        "78,491 physical LOC",
        "2,886 source test definitions",
        "162 locally defined pytest fixtures",
        "3,284 nodes collected",
        "3,281 nodes",
        "3 live-probe nodes",
    ):
        assert phrase in metrics, phrase

    print("VERIFY PASS")
    print("inventory_bytes", (ROOT / "docs/tasks/313/inventory.json").stat().st_size)
    print("static_signals_bytes", (ROOT / "docs/tasks/313/evidence/static-signals.json").stat().st_size)
    print("candidate_rows", len(candidates))
    print("candidate_verdicts", dict(sorted(verdicts.items())))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Score frozen #346 retrieval outputs against marker-derived ground truth."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def marker_locations(root: Path) -> dict[str, tuple[str, int]]:
    result: dict[str, tuple[str, int]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".serena" in path.parts:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, 1):
            for marker in re.findall(r"G346_[A-Z0-9_]+", line):
                if marker in result:
                    raise ValueError(f"duplicate marker {marker}")
                result[marker] = (path.relative_to(root).as_posix(), number)
    return result


def _baseline_locations(call: dict[str, Any]) -> set[tuple[str, int]]:
    rows: set[tuple[str, int]] = set()
    for line in call["rg"]["stdout"].splitlines():
        match = re.match(r"(?:\./)?([^:]+):(\d+):", line)
        if match:
            rows.add((match.group(1), int(match.group(2))))
    for row in call["ast_rows"]:
        rows.add((row["path"], int(row["line"])))
    return rows


def _light_locations(call: dict[str, Any]) -> set[tuple[str, int]]:
    payload = json.loads(call["text"])
    return {(row["path"], int(row["line"])) for row in payload.get("rows", [])}


def _serena_locations(call: dict[str, Any]) -> set[tuple[str, int]]:
    text = call.get("text", "")
    if not text or text in {"{}", "[]"}:
        return set()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return set()
    rows: set[tuple[str, int]] = set()
    if not isinstance(payload, dict):
        return rows
    for path, groups in payload.items():
        if not isinstance(groups, dict):
            continue
        for items in groups.values():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                context = str(item.get("content_around_reference", ""))
                for line in context.splitlines():
                    match = re.search(r"(?:^|\s)>\s*(\d+):", line)
                    if match:
                        rows.add((path, int(match.group(1)) + 1))  # Serena displays 0-based source lines
    return rows


def arm_calls(path: Path) -> tuple[str, dict[str, set[tuple[str, int]]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    scenario = payload["scenario"]
    extractor = {
        "baseline": _baseline_locations,
        "light": _light_locations,
        "serena": _serena_locations,
    }[scenario]
    result: dict[str, set[tuple[str, int]]] = {}
    for call in payload.get("calls", []):
        case = call.get("case")
        if case and case not in result:
            result[case] = extractor(call)
    return scenario, result


def metrics(actual: set[tuple[str, int]], relevant: set[tuple[str, int]]) -> dict[str, Any]:
    tp = len(actual & relevant)
    fp = len(actual - relevant)
    fn = len(relevant - actual)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "actual": sorted([list(item) for item in actual]),
        "relevant": sorted([list(item) for item in relevant]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--truth", required=True)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    fixture = Path(args.fixture)
    locations = marker_locations(fixture)
    truth = json.loads(Path(args.truth).read_text(encoding="utf-8"))
    output: dict[str, Any] = {"markers": locations, "runs": {}}
    for raw_path in args.paths:
        path = Path(raw_path)
        scenario, calls = arm_calls(path)
        row: dict[str, Any] = {"scenario": scenario, "semantic": {}, "production": {}}
        semantic_actual: set[tuple[str, int]] = set()
        semantic_truth: set[tuple[str, int]] = set()
        for query in truth["semantic_reference_queries"]:
            source_case = "R4" if query["id"].startswith("R4") else query["id"]
            actual = calls.get(source_case, set())
            relevant = {locations[marker] for marker in query["relevant_markers"]}
            row["semantic"][query["id"]] = metrics(actual, relevant)
            semantic_actual |= {(query["id"] + "::" + p, n) for p, n in actual}
            semantic_truth |= {(query["id"] + "::" + p, n) for p, n in relevant}
        production_actual: set[tuple[str, int]] = set()
        production_truth: set[tuple[str, int]] = set()
        for query in truth["production_edge_queries"]:
            source_case = "R4" if query["id"].startswith("R4") else query["id"]
            actual = calls.get(source_case, set())
            relevant = {locations[marker] for marker in query["relevant_markers"]}
            row["production"][query["id"]] = metrics(actual, relevant)
            production_actual |= {(query["id"] + "::" + p, n) for p, n in actual}
            production_truth |= {(query["id"] + "::" + p, n) for p, n in relevant}
        row["semantic_total"] = metrics(semantic_actual, semantic_truth)
        row["production_total"] = metrics(production_actual, production_truth)
        output["runs"][path.stem] = row
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


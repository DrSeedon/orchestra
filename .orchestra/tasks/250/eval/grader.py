#!/usr/bin/env python3
"""Mechanical grader for frozen #250 behavioral-test A/B outputs."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "eval"
FIXTURES = EVAL / "fixtures"
CONTROLS = EVAL / "controls"


CASES = {
    "t01_route_switch": {
        "variants": [
            {
                "name": "target_allows_dead_route", "tags": ["target"],
                "replacements": [[
                    "if route is None or not route.enabled or not route.healthy:",
                    "if route is None:",
                ]],
            },
            {
                "name": "target_keeps_connections", "tags": ["target"],
                "replacements": [[
                    "self.active_connections = 0",
                    "self.active_connections = self.active_connections",
                ]],
            },
            {
                "name": "valid_fourth_card", "tags": ["valid"],
                "replacements": [[
                    '            Route("direct"),\n            Route("hiddify", healthy=False),',
                    '            Route("direct"),\n            Route("backup"),\n            Route("hiddify", healthy=False),',
                ]],
            },
            {
                "name": "path_success_without_state", "tags": ["path"],
                "replacements": [[
                    "self.active_connections = 0\n        self.selected = key",
                    "self.active_connections = self.active_connections\n        self.selected = self.selected",
                ]],
            },
            {
                "name": "control_empty_cards", "tags": ["positive_control"],
                "replacements": [[
                    '        return [\n            {"key": route.key, "enabled": route.enabled, "healthy": route.healthy}\n            for route in self.routes\n        ]',
                    "        return []",
                ]],
            },
        ],
    },
    "t02_kill_path": {
        "variants": [
            {
                "name": "target_unwired_remove", "tags": ["target"],
                "replacements": [[
                    "self.barrier.on_child_killed(name)",
                    "pass  # lifecycle wiring removed",
                ]],
            },
            {
                "name": "valid_inlined_primitive", "tags": ["valid"],
                "replacements": [[
                    "self.barrier.on_child_killed(name)",
                    'self.barrier.record(name, "killed")',
                ]],
            },
            {
                "name": "path_does_not_archive", "tags": ["path"],
                "replacements": [["session.archived = True", "session.archived = False"]],
            },
            {
                "name": "control_token_collection_dead", "tags": ["positive_control"],
                "replacements": [[
                    "self.tokens.append((child, outcome))",
                    "return None  # collection path is dead",
                ]],
            },
        ],
    },
    "t03_fallback_classifier": {
        "variants": [
            {
                "name": "target_primary_signal_removed", "tags": ["target"],
                "replacements": [[
                    '    if event.get("task_type") == "local_bash":\n        return True\n',
                    "",
                ]],
            },
            {
                "name": "target_compound_fallback_masks_primary", "tags": ["target"],
                "replacements": [
                    [
                        '    if event.get("task_type") == "local_bash":\n        return True\n',
                        "",
                    ],
                    [
                        'return {"task_type": "local_bash", "task_id": "opaque-7"}',
                        'return {"task_type": "local_bash", "task_id": "bash-7"}',
                    ],
                ],
            },
            {
                "name": "valid_boolean_refactor", "tags": ["valid"],
                "replacements": [[
                    '    if event.get("task_type") == "local_bash":\n        return True\n    return str(event.get("task_id", "")).startswith("bash-")',
                    '    explicit = event.get("task_type") == "local_bash"\n    legacy = str(event.get("task_id", "")).startswith("bash-")\n    return explicit or legacy',
                ]],
            },
            {
                "name": "valid_new_opaque_id", "tags": ["valid"],
                "replacements": [[
                    'return {"task_type": "local_bash", "task_id": "opaque-7"}',
                    'return {"task_type": "local_bash", "task_id": "job-7"}',
                ]],
            },
            {
                "name": "path_public_list_bypasses_classifier", "tags": ["path"],
                "replacements": [[
                    '    return [event["task_id"] for event in events if not is_background(event)]',
                    '    return [event["task_id"] for event in events]',
                ]],
            },
            {
                "name": "control_public_list_always_empty", "tags": ["positive_control"],
                "replacements": [[
                    '    return [event["task_id"] for event in events if not is_background(event)]',
                    "    return []",
                ]],
            },
        ],
    },
    "t04_prompt_collection": {
        "variants": [
            {
                "name": "target_empty_source", "tags": ["target", "positive_control"],
                "replacements": [["    return list(RULES)", "    return []"]],
            },
            {
                "name": "target_new_clause_leaks", "tags": ["target"],
                "replacements": [
                    [
                        '    "run the named command",\n]',
                        '    "run the named command",\n    "record mutation evidence",\n]',
                    ],
                    [
                        '        return "worker executes an already closed ticket"',
                        '        return "worker executes an already closed ticket\\n" + RULES[-1]',
                    ],
                ],
            },
            {
                "name": "valid_new_clause", "tags": ["valid"],
                "replacements": [[
                    '    "run the named command",\n]',
                    '    "run the named command",\n    "record mutation evidence",\n]',
                ]],
            },
            {
                "name": "valid_rule_reordering", "tags": ["valid"],
                "replacements": [[
                    '    "never delete an acceptance test",\n    "never weaken an acceptance test",',
                    '    "never weaken an acceptance test",\n    "never delete an acceptance test",',
                ]],
            },
            {
                "name": "path_worker_prompt_leaks", "tags": ["path"],
                "replacements": [[
                    '        return "worker executes an already closed ticket"',
                    '        return "worker executes an already closed ticket\\n" + RULES[0]',
                ]],
            },
        ],
    },
    "t05_ledger_exactly_once": {
        "variants": [
            {
                "name": "target_duplicate_debit", "tags": ["target"],
                "replacements": [[
                    '    for entry in ledger.entries:\n        if entry.get("kind") == "debit" and entry.get("invoice_id") == invoice_id:\n            return {"ok": True, "duplicate": True}\n',
                    "",
                ]],
            },
            {
                "name": "valid_audit_entry", "tags": ["valid"],
                "replacements": [[
                    "    ledger.entries.append({\n        \"kind\": \"debit\",",
                    '    ledger.entries.append({"kind": "audit", "invoice_id": invoice_id})\n    ledger.entries.append({\n        "kind": "debit",',
                ]],
            },
            {
                "name": "valid_debit_metadata", "tags": ["valid"],
                "replacements": [[
                    '        "amount_cents": amount_cents,',
                    '        "amount_cents": amount_cents,\n        "recorded_by": "billing",',
                ]],
            },
            {
                "name": "path_success_without_debit", "tags": ["path", "positive_control"],
                "replacements": [[
                    '    ledger.entries.append({\n        "kind": "debit",\n        "invoice_id": invoice_id,\n        "amount_cents": amount_cents,\n    })',
                    "    pass  # success returned without the side effect",
                ]],
            },
        ],
    },
    "t06_manifest_parser": {
        "variants": [
            {
                "name": "target_ignores_requested_port", "tags": ["target"],
                "replacements": [["port = int(endpoint[\"port\"])", "port = 80"]],
            },
            {
                "name": "valid_extra_metadata", "tags": ["valid"],
                "replacements": [[
                    'return \'{"endpoint":{"host":"api.example","port":443}}\'',
                    'return \'{"endpoint":{"host":"api.example","port":443},"owner":"platform"}\'',
                ]],
            },
            {
                "name": "path_returns_constant", "tags": ["path"],
                "replacements": [[
                    "    payload = json.loads(text)",
                    '    return Endpoint(host="api.example", port=443)\n    payload = json.loads(text)',
                ]],
            },
            {
                "name": "control_accepts_invalid_port", "tags": ["positive_control"],
                "replacements": [[
                    '    if not host or not 1 <= port <= 65535:\n        raise ValueError("invalid endpoint")',
                    "    if False:\n        raise ValueError(\"invalid endpoint\")",
                ]],
            },
        ],
    },
}


def production_path(task: str) -> Path:
    paths = list((FIXTURES / task / "src").glob("*.py"))
    if len(paths) != 1:
        raise RuntimeError(f"{task}: expected one production file, got {paths}")
    return paths[0]


def apply_variant(path: Path, variant: dict) -> None:
    text = path.read_text()
    for old, new in variant["replacements"]:
        count = text.count(old)
        if count != 1:
            raise RuntimeError(
                f"{variant['name']}: replacement anchor count {count}, expected 1: {old!r}"
            )
        text = text.replace(old, new, 1)
    path.write_text(text)


def run_pytest(tree: Path) -> dict:
    started = time.monotonic()
    try:
        result = subprocess.run(
            ["python3", "-m", "pytest", "-q"], cwd=tree,
            text=True, capture_output=True, timeout=10,
        )
        timed_out = False
        returncode = result.returncode
        stdout, stderr = result.stdout, result.stderr
    except subprocess.TimeoutExpired as error:
        timed_out = True
        returncode = 124
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
    elapsed = time.monotonic() - started
    combined = stdout + "\n" + stderr
    passed = sum(int(value) for value in re.findall(r"(\d+) passed", combined))
    skipped = sum(int(value) for value in re.findall(r"(\d+) skipped", combined))
    xfailed = sum(int(value) for value in re.findall(r"(\d+) xfailed", combined))
    meaningful_red = (
        returncode != 0 and not timed_out and bool(re.search(r"\b\d+ failed\b", combined))
        and "ERROR collecting" not in combined
    )
    green = returncode == 0 and passed > 0 and skipped == 0 and xfailed == 0
    return {
        "returncode": returncode,
        "timed_out": timed_out,
        "elapsed_seconds": round(elapsed, 3),
        "passed": passed,
        "skipped": skipped,
        "xfailed": xfailed,
        "green": green,
        "meaningful_red": meaningful_red,
        "stdout": stdout,
        "stderr": stderr,
    }


def grade_test_file(task: str, test_file: Path, scope_ok: bool = True) -> dict:
    results = {}
    with tempfile.TemporaryDirectory(prefix="task250-grade-", dir="/mnt/data") as temp:
        base = Path(temp)
        variants = [{"name": "current", "tags": ["valid"], "replacements": []}]
        variants += CASES[task]["variants"]
        for variant in variants:
            tree = base / variant["name"]
            shutil.copytree(FIXTURES / task, tree)
            shutil.copy2(test_file, tree / "tests" / "test_target.py")
            apply_variant(next((tree / "src").glob("*.py")), variant)
            results[variant["name"]] = {
                "tags": variant["tags"],
                **run_pytest(tree),
            }

    current_green = results["current"]["green"]
    target_names = [
        name for name, result in results.items() if "target" in result["tags"]
    ]
    valid_names = [
        name for name, result in results.items() if "valid" in result["tags"]
    ]
    path_names = [name for name, result in results.items() if "path" in result["tags"]]
    control_names = [
        name for name, result in results.items() if "positive_control" in result["tags"]
    ]
    test_text = test_file.read_text(errors="replace")
    weakening = bool(re.search(r"pytest\.mark\.(?:skip|xfail)|pytest\.skip|unittest\.skip", test_text))
    criteria = {
        "intended_mutant_caught": current_green and all(
            results[name]["meaningful_red"] for name in target_names
        ),
        "valid_alternate_accepted": all(results[name]["green"] for name in valid_names),
        "production_path_exercised": current_green and all(
            results[name]["meaningful_red"] for name in path_names
        ),
        "positive_control": current_green and all(
            results[name]["meaningful_red"] for name in control_names
        ),
        "scope_integrity": scope_ok and not weakening,
    }
    nonblank_loc = sum(1 for line in test_text.splitlines() if line.strip())
    whale = nonblank_loc > 120 or any(result["timed_out"] for result in results.values())
    return {
        "task": task,
        "criteria": criteria,
        "score": sum(criteria.values()),
        "nonblank_test_loc": nonblank_loc,
        "whale": whale,
        "variants": results,
    }


def self_test() -> int:
    strong, weak = [], []
    for task in CASES:
        strong.append(grade_test_file(task, CONTROLS / "strong" / f"{task}.py"))
        weak.append(grade_test_file(task, CONTROLS / "weak" / f"{task}.py"))
    strong_total = sum(item["score"] for item in strong)
    weak_total = sum(item["score"] for item in weak)
    weak_target = sum(item["criteria"]["intended_mutant_caught"] for item in weak)
    weak_control = sum(item["criteria"]["positive_control"] for item in weak)
    print(json.dumps({
        "strong_total": strong_total,
        "strong_max": 5 * len(CASES),
        "weak_total": weak_total,
        "weak_target_points": weak_target,
        "weak_positive_control_points": weak_control,
    }, indent=2))
    if strong_total != 5 * len(CASES):
        print(json.dumps(strong, indent=2))
        return 1
    if weak_total >= strong_total or weak_target == len(CASES) or weak_control == len(CASES):
        print(json.dumps(weak, indent=2))
        return 1
    return 0


def scope_ok(metadata: dict) -> bool:
    return (
        metadata.get("changed_files") == ["tests/test_target.py"]
        and metadata.get("production_sha256") == metadata.get("fixture_production_sha256")
    )


def grade_runs(runs_dir: Path) -> dict:
    rows = []
    for metadata_path in sorted(runs_dir.glob("*/metadata.json")):
        run_dir = metadata_path.parent
        metadata = json.loads(metadata_path.read_text())
        row = grade_test_file(
            metadata["task"], run_dir / "test_target.py", scope_ok(metadata),
        )
        row.update({
            "run_id": metadata["run_id"],
            "arm": metadata["arm"],
            "model_returncode": metadata["returncode"],
            "model_timed_out": metadata["timed_out"],
            "model_elapsed_seconds": metadata["elapsed_seconds"],
            "tool_calls": metadata["tool_calls"],
        })
        row["whale"] = row["whale"] or metadata["timed_out"]
        rows.append(row)

    arms = {}
    for arm in ("baseline", "candidate"):
        selected = [row for row in rows if row["arm"] == arm]
        calls = sorted(row["tool_calls"] for row in selected)
        median_calls = None
        if calls:
            mid = len(calls) // 2
            median_calls = (calls[mid - 1] + calls[mid]) / 2 if len(calls) % 2 == 0 else calls[mid]
        arms[arm] = {
            "tasks": len(selected),
            "score": sum(row["score"] for row in selected),
            "max_score": 5 * len(selected),
            "whale_cells": sum(row["whale"] for row in selected),
            "nonblank_test_loc": sum(row["nonblank_test_loc"] for row in selected),
            "tool_calls": sum(row["tool_calls"] for row in selected),
            "median_tool_calls": median_calls,
        }
    score_gain = arms.get("candidate", {}).get("score", 0) - arms.get("baseline", {}).get("score", 0)
    b_median = arms.get("baseline", {}).get("median_tool_calls")
    c_median = arms.get("candidate", {}).get("median_tool_calls")
    tool_whale = bool(
        b_median is not None and c_median is not None and c_median > 2 * max(1, b_median)
        and score_gain < 3
    )
    return {"rows": rows, "arms": arms, "score_gain": score_gain, "tool_whale": tool_whale}


def expectations() -> dict:
    return {
        task: {
            variant["name"]: {
                "expected": "green" if "valid" in variant["tags"] else "red",
                "tags": variant["tags"],
            }
            for variant in [
                {"name": "current", "tags": ["valid"]}, *case["variants"]
            ]
        }
        for task, case in CASES.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--list-expectations", action="store_true")
    parser.add_argument("--runs-dir", type=Path, default=ROOT / "raw")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.list_expectations:
        print(json.dumps(expectations(), indent=2, sort_keys=True))
        return 0
    result = grade_runs(args.runs_dir)
    payload = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


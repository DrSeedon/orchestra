#!/usr/bin/env python3
"""Mechanical scorer for the preregistered #454 Luna extraction trials."""

from __future__ import annotations

import json
import re
import sys
from itertools import combinations
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / ".orchestra" / "tasks" / "454"
ALLOWED_STATUS = {"current", "rejected", "superseded", "disputed"}
NUMBER = re.compile(r"(?<![A-Za-z_])\d+(?:[.,]\d+)?")


def normalize(value: str) -> str:
    value = value.casefold().replace("–", "-").replace("—", "-")
    value = value.replace("\u00a0", " ").replace("\u202f", " ")
    return re.sub(r"\s+", " ", value).strip()


def parse_array(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8").strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end < start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{path}: output is not an array of objects")
    return value


def gold_match(candidate: dict, gold: dict) -> bool:
    if str(candidate.get("task_id")) != gold["task_id"]:
        return False
    claim = normalize(
        str(candidate.get("statement") or "") + " "
        + " ".join(str(value) for value in candidate.get("anchors") or [])
    )
    return all(
        any(normalize(option) in claim for option in alternatives)
        for alternatives in gold["required_groups"]
    )


def score_trial(path: Path, gold: list[dict]) -> dict:
    candidates = parse_array(path)
    schema_errors: list[str] = []
    evidence_total = evidence_exact = evidence_range = 0
    numeric_candidates = numeric_grounded = 0
    candidate_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        required = {
            "candidate_id", "task_id", "fact_key", "topic", "statement",
            "status", "anchors", "durability_reason", "evidence",
        }
        if set(candidate) != required:
            schema_errors.append(f"candidate[{index}] fields={sorted(candidate)}")
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id or candidate_id in candidate_ids:
            schema_errors.append(f"candidate[{index}] duplicate/empty candidate_id")
        candidate_ids.add(candidate_id)
        if candidate.get("status") not in ALLOWED_STATUS:
            schema_errors.append(f"candidate[{index}] invalid status")
        anchors = candidate.get("anchors")
        if not isinstance(anchors, list) or not 1 <= len(anchors) <= 6 or not all(
            isinstance(anchor, str) and anchor.strip() for anchor in anchors
        ):
            schema_errors.append(f"candidate[{index}] invalid anchors")
        evidence = candidate.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            schema_errors.append(f"candidate[{index}] missing evidence")
            evidence = []
        evidence_quotes: list[str] = []
        for item in evidence:
            evidence_total += 1
            try:
                source_path = str(item["source_path"])
                task_id = str(candidate["task_id"])
                prefix = f"sources/task-{task_id}/"
                if not source_path.startswith(prefix):
                    raise ValueError("source outside candidate task")
                source = ROOT / ".orchestra" / "tasks" / task_id / source_path[len(prefix) :]
                body = source.read_text(encoding="utf-8")
                quote = str(item["quote"])
                evidence_quotes.append(quote)
                if quote in body:
                    evidence_exact += 1
                start, end = int(item["line_start"]), int(item["line_end"])
                lines = body.splitlines(keepends=True)
                window = "".join(lines[start - 1 : end])
                if 1 <= start <= end <= len(lines) and quote in window:
                    evidence_range += 1
            except (KeyError, OSError, TypeError, ValueError) as error:
                schema_errors.append(f"candidate[{index}] evidence error: {error}")
        numbers = NUMBER.findall(str(candidate.get("statement") or ""))
        if numbers:
            numeric_candidates += 1
            evidence_text = normalize(" ".join(evidence_quotes))
            if all(normalize(number) in evidence_text for number in numbers):
                numeric_grounded += 1

    matched = {
        item["gold_id"]
        for item in gold
        if any(gold_match(candidate, item) for candidate in candidates)
    }
    return {
        "path": path.name,
        "candidates": len(candidates),
        "schema_errors": schema_errors,
        "gold_matched": sorted(matched),
        "gold_recall": len(matched) / len(gold),
        "evidence_total": evidence_total,
        "evidence_exact_rate": evidence_exact / evidence_total if evidence_total else 0.0,
        "evidence_line_range_rate": evidence_range / evidence_total if evidence_total else 0.0,
        "numeric_candidates": numeric_candidates,
        "numeric_grounding_rate": (
            numeric_grounded / numeric_candidates if numeric_candidates else 1.0
        ),
    }


def main() -> None:
    contract = json.loads((ARTIFACT / "eval-gold.json").read_text(encoding="utf-8"))
    gold = contract["gold"]
    trials = [score_trial(ARTIFACT / f"eval-run-{index}.txt", gold) for index in range(1, 4)]
    coverage_sets = [set(trial["gold_matched"]) for trial in trials]
    jaccards: list[float] = []
    for left, right in combinations(coverage_sets, 2):
        jaccards.append(len(left & right) / len(left | right) if left | right else 1.0)
    recalls = [trial["gold_recall"] for trial in trials]
    run_manifest = json.loads(
        (ARTIFACT / "eval-run-manifest.json").read_text(encoding="utf-8")
    )
    summary = {
        "preregistered_pass": contract["preregistered_pass"],
        "trials": trials,
        "noise": {
            "gold_recall_min": min(recalls),
            "gold_recall_max": max(recalls),
            "gold_recall_range": max(recalls) - min(recalls),
            "pairwise_gold_coverage_jaccard": jaccards,
            "pairwise_gold_coverage_jaccard_min": min(jaccards),
            "candidate_count_min": min(trial["candidates"] for trial in trials),
            "candidate_count_max": max(trial["candidates"] for trial in trials),
        },
        "source_unchanged_all": all(
            trial["source_unchanged"] for trial in run_manifest["trials"]
        ),
    }
    requirements = contract["preregistered_pass"]
    summary["pass"] = (
        summary["source_unchanged_all"]
        and all(not trial["schema_errors"] for trial in trials)
        and all(trial["gold_recall"] == requirements["gold_recall_each_run"] for trial in trials)
        and all(trial["evidence_exact_rate"] == requirements["evidence_exact_rate_each_run"] for trial in trials)
        and all(trial["evidence_line_range_rate"] == requirements["evidence_line_range_rate_each_run"] for trial in trials)
        and all(trial["numeric_grounding_rate"] == requirements["numeric_grounding_rate_each_run"] for trial in trials)
        and summary["noise"]["pairwise_gold_coverage_jaccard_min"]
        >= requirements["gold_coverage_jaccard_min"]
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if not summary["pass"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Post-run diagnostic correcting two preregistration defects without hiding them.

The original score remains authoritative for the frozen pass/fail. This scorer:
1) rejects gold whose required literal is absent from its source corpus;
2) matches a gold fact against the task's candidate set, because the prompt requires
   atomic candidates and the original scorer incorrectly required compound terms in
   one candidate.
"""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

from score_extractor_eval import ARTIFACT, ROOT, normalize, parse_array


def corpus_text(task_id: str) -> str:
    task_root = ROOT / ".orchestra" / "tasks" / task_id
    return normalize(
        "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in sorted(task_root.rglob("*.md"))
        )
    )


def groups_match(text: str, groups: list[list[str]]) -> bool:
    return all(
        any(normalize(option) in text for option in alternatives)
        for alternatives in groups
    )


def main() -> None:
    contract = json.loads((ARTIFACT / "eval-gold.json").read_text(encoding="utf-8"))
    valid: list[dict] = []
    excluded: list[dict] = []
    for gold in contract["gold"]:
        missing = [
            group
            for group in gold["required_groups"]
            if not any(normalize(option) in corpus_text(gold["task_id"]) for option in group)
        ]
        if missing:
            excluded.append(
                {
                    "gold_id": gold["gold_id"],
                    "reason": "required literal absent from source corpus",
                    "missing_groups": missing,
                }
            )
        else:
            valid.append(gold)

    runs: list[dict] = []
    coverage_sets: list[set[str]] = []
    for trial in range(1, 4):
        candidates = parse_array(ARTIFACT / f"eval-run-{trial}.txt")
        matched: set[str] = set()
        for gold in valid:
            task_claims = normalize(
                " ".join(
                    str(candidate.get("statement") or "")
                    + " "
                    + " ".join(str(anchor) for anchor in candidate.get("anchors") or [])
                    for candidate in candidates
                    if str(candidate.get("task_id")) == gold["task_id"]
                )
            )
            if groups_match(task_claims, gold["required_groups"]):
                matched.add(gold["gold_id"])
        coverage_sets.append(matched)
        runs.append(
            {
                "trial": trial,
                "matched": sorted(matched),
                "matched_count": len(matched),
                "valid_gold_count": len(valid),
                "set_level_recall": len(matched) / len(valid),
            }
        )

    jaccards = [
        len(left & right) / len(left | right) if left | right else 1.0
        for left, right in combinations(coverage_sets, 2)
    ]
    recalls = [run["set_level_recall"] for run in runs]
    print(
        json.dumps(
            {
                "classification": "exploratory_after_results_not_preregistered_acceptance",
                "excluded_gold": excluded,
                "runs": runs,
                "noise": {
                    "recall_min": min(recalls),
                    "recall_max": max(recalls),
                    "recall_range": max(recalls) - min(recalls),
                    "pairwise_coverage_jaccard": jaccards,
                    "pairwise_coverage_jaccard_min": min(jaccards),
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()


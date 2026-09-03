#!/usr/bin/env python3
"""Score the one-shot Luna output against the frozen #456 labels."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> None:
    gold = json.loads((ROOT / "evaluation-gold.json").read_text(encoding="utf-8"))
    output = (ROOT / "evaluation-luna.md").read_text(encoding="utf-8")
    predicted = dict(re.findall(r"^\| ([A-I]) \| (PASS|STOP) \|", output, re.MULTILINE))
    if set(predicted) != set(gold):
        raise RuntimeError(f"expected cases {sorted(gold)}, got {sorted(predicted)}")

    rows = []
    for case in sorted(gold):
        expected = gold[case]["expected"]
        actual = predicted[case]
        rows.append({"case": case, "expected": expected, "actual": actual})
    positives = [row for row in rows if row["expected"] == "STOP"]
    negatives = [row for row in rows if row["expected"] == "PASS"]
    true_positive = sum(row["actual"] == "STOP" for row in positives)
    false_positive = sum(row["actual"] == "STOP" for row in negatives)
    result = {
        "rows": rows,
        "true_positive": true_positive,
        "positive_total": len(positives),
        "false_negative": len(positives) - true_positive,
        "false_positive": false_positive,
        "negative_total": len(negatives),
        "true_negative": len(negatives) - false_positive,
        "pre_registered_threshold_met": (
            true_positive == len(positives) and false_positive <= 1
        ),
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    (ROOT / "evaluation-score.json").write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()

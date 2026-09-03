#!/usr/bin/env python3
"""Frozen aggregation for the #292 A/P/B pilot."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
PROTOCOL = json.loads((ROOT / "protocol.json").read_text())


def median(values):
    return statistics.median(values)


def main() -> None:
    records = []
    for path in sorted(RESULTS.glob("t*-*.json")):
        if path.name == "manifest.json":
            continue
        records.append(json.loads(path.read_text()))
    if len(records) != 27:
        raise SystemExit(f"expected 27 records, found {len(records)}")
    scorers = [json.loads((RESULTS / "scorers" / f"{name}.json").read_text())["judgment"]["judgments"] for name in ("one", "two")]
    judgments = {name: {row["candidate_id"]: row for row in value} for name, value in zip(("one", "two"), scorers)}
    mapping = json.loads((RESULTS / "blinding.json").read_text())
    by_run = {run_id: record for record in records for run_id in [record["run_id"]]}
    rows = []
    for cid, run_id in mapping.items():
        record = by_run[run_id]
        parsed = record["parsed"]["payload"]
        decisions = [judgments["one"][cid]["fact_decisions"], judgments["two"][cid]["fact_decisions"]]
        agree = [a == b for a, b in zip(*decisions)]
        semantic = [all(row) for row in decisions]
        exact_ac = parsed["exact_ac_command"] == next(c["exact_ac"] for c in PROTOCOL["cases"] if c["case_id"] == record["case_id"])
        rows.append({"run_id": run_id, "case_id": record["case_id"], "arm": record["arm"], "repetition": record["repetition"],
                     "intent_recall": sum(sum(decision) for decision in decisions) / (2 * len(decisions[0])),
                     "invented_or_contradictory": any(judgments[name][cid]["invented_or_contradictory"] for name in ("one", "two")),
                     "next_action_correct": all(judgments[name][cid]["next_action_correct"] for name in ("one", "two")),
                     "exact_ac_correct": exact_ac, "pre_action_read_tool_calls": record["pre_action_read_tool_calls"],
                     "input_tokens": record["parsed"]["usage"].get("input_tokens", 0), "scorer_fact_agreement": agree,
                     "capsule_bytes": len((ROOT / "capsules.md").read_bytes())})
    agreement = [value for row in rows for value in row["scorer_fact_agreement"]]
    if not agreement or not all(agreement):
        raise SystemExit("scorer disagreement: stop pilot")
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["case_id"], row["arm"])].append(row)
    summary = {}
    for case in sorted({row["case_id"] for row in rows}):
        controls = {}
        for arm in ("A", "P", "B"):
            group = grouped[(case, arm)]
            controls[arm] = {"recall_median": median([r["intent_recall"] for r in group]),
                             "read_median": median([r["pre_action_read_tool_calls"] for r in group]),
                             "input_tokens_median": median([r["input_tokens"] for r in group]),
                             "invented_or_contradictory": any(r["invented_or_contradictory"] for r in group),
                             "exact_ac_all": all(r["exact_ac_correct"] for r in group),
                             "next_action_all": all(r["next_action_correct"] for r in group),
                             "recall_range": max(r["intent_recall"] for r in group) - min(r["intent_recall"] for r in group),
                             "read_range": max(r["pre_action_read_tool_calls"] for r in group) - min(r["pre_action_read_tool_calls"] for r in group)}
        summary[case] = controls
    recall_noise = max(summary[case][arm]["recall_range"] for case in summary for arm in ("A", "P"))
    reads_noise = max(summary[case][arm]["read_range"] for case in summary for arm in ("A", "P"))
    per_case_pass = {}
    for case, controls in summary.items():
        b = controls["B"]
        gains = [b["recall_median"] - controls[arm]["recall_median"] for arm in ("A", "P")]
        reads_ok = b["read_median"] <= min(controls["A"]["read_median"], controls["P"]["read_median"]) - 1 and all(
            controls[arm]["read_median"] - b["read_median"] >= reads_noise for arm in ("A", "P"))
        per_case_pass[case] = {"recall_gains": gains, "recall_threshold": max(0.2, recall_noise),
                               "recall_pass": all(gain >= max(0.2, recall_noise) for gain in gains), "reads_pass": reads_ok,
                               "b_safety_pass": not b["invented_or_contradictory"] and b["exact_ac_all"] and b["next_action_all"]}
    result = {"protocol_version": PROTOCOL["registered_at"], "run_count": len(rows), "scorer_fact_agreement": True,
              "recall_noise_floor": recall_noise, "reads_noise_floor": reads_noise, "summary": summary,
              "per_case_pass": per_case_pass,
              "PASS": all(x["recall_pass"] and x["reads_pass"] and x["b_safety_pass"] for x in per_case_pass.values()),
              "verdict": "PASS" if all(x["recall_pass"] and x["reads_pass"] and x["b_safety_pass"] for x in per_case_pass.values()) else "REJECT",
              "rows": rows}
    (RESULTS / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"verdict": result["verdict"], "runs": len(rows), "recall_noise_floor": recall_noise, "reads_noise_floor": reads_noise}))


if __name__ == "__main__":
    main()

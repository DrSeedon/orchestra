#!/usr/bin/env python3
"""Mechanical consistency checks for the frozen #289 research artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> int:
    evidence = json.loads((ROOT / "evidence.json").read_text(encoding="utf-8"))
    grade = json.loads((ROOT / "ab-grade.json").read_text(encoding="utf-8"))
    report = (ROOT / "research.md").read_text(encoding="utf-8")
    baseline = evidence["baseline_2026_07_25"]
    live = evidence["live_db_retained_window"]
    ab = evidence["luna_sol_preregistered_ab"]

    assert baseline["files"]["call_rows"] == 98
    assert baseline["files"]["blind_rows"] == 45
    assert baseline["reader_test_contaminants"] == 5
    assert abs(baseline["fisher_zero_substantive_p"] - 0.5394736842105263) < 1e-15
    assert live["invocations"] == 235
    assert live["paired"] == 190
    assert live["status"] == {"completed": 182, "failed": 7, "timed_out": 1, "unpaired": 45}
    assert live["task_cycles"]["matched_completed_tasks"] == 37
    assert live["artifact_rounds"] == {"1": 17, "2": 39, "3": 25, "4": 10, "5": 4, "7": 1}
    assert abs(live["wall_seconds_completed"]["median"] - 79.001879) < 1e-9
    assert abs(live["wall_seconds_completed"]["p90"] - 180.106456) < 1e-9
    assert abs(live["task_cycles"]["review_wall_share"]["median"] - 0.04800868930218934) < 1e-15
    assert abs(live["task_cycles"]["review_wall_share"]["p90"] - 0.12925998692683213) < 1e-15
    assert live["zero_actionable_marker_artifacts"]["count"] == 44
    assert live["zero_actionable_marker_artifacts"]["denominator"] == 96
    assert grade == ab
    assert grade["decision"] == "no_observed_difference_not_equivalence"
    assert grade["common_required_blocker_misses"] == ["K2", "Q4"]
    for arm in grade["blind_results"].values():
        assert arm["required_blocker_hits"] == 0
        assert arm["blocking_false_positives"] == 0

    assert hashlib.sha256((ROOT / "ab_workspace/frozen_corpus.md").read_bytes()).hexdigest() == grade["freeze"]["corpus_sha256"]
    assert hashlib.sha256((ROOT / "ab_workspace/review_prompt.txt").read_bytes()).hexdigest() == grade["freeze"]["prompt_sha256"]
    for name in ("luna-review.md", "sol-review.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for heading in ("## Summary", "## Case K2", "## Case M7", "## Case Q4", "## Case T9", "## Verdict"):
            assert heading in text
    metadata = grade["run_metadata"]["runs"]
    assert hashlib.sha256((ROOT / "luna-review.md").read_bytes()).hexdigest() == metadata["luna"]["review_sha256"]
    assert hashlib.sha256((ROOT / "sol-review.md").read_bytes()).hexdigest() == metadata["sol"]["review_sha256"]

    for anchor in (
        "**79.0 с**",
        "**180.1 с**",
        "**4.80%**",
        "**12.93%**",
        "**8.76% cost**",
        "**0.720**",
        "Luna **0/2**, Sol **0/2**",
        "**B+C**",
    ):
        assert anchor in report, anchor

    forbidden = (
        ".ab-luna.jsonl",
        ".ab-sol.jsonl",
        ".ab-pre.db",
        ".ab-post.db",
        ".live-backup.db",
        ".final.db",
    )
    for name in forbidden:
        assert not (ROOT / name).exists(), name

    print(json.dumps({
        "ab_commitment_verified": grade["freeze"]["verified"],
        "headline_anchors": 8,
        "historical_cutoff": live["cutoff"],
        "raw_artifacts_absent": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

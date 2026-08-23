#!/usr/bin/env python3
"""Reduce frozen #250 raw/model/grader artifacts to the published measurements."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def six_answers_before_edit(events: Path) -> bool:
    messages = []
    for line in events.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "item.completed":
            continue
        item = event.get("item") or {}
        if item.get("type") == "file_change":
            break
        if item.get("type") == "agent_message":
            messages.append(item.get("text", ""))
    joined = "\n".join(messages)
    return all(re.search(rf"(?m)^\s*{number}\.", joined) for number in range(1, 7))


def main() -> None:
    grade = json.loads((ROOT / "grade-results.json").read_text())
    run = json.loads((RAW / "run-summary.json").read_text())
    by_task: dict[str, dict[str, int]] = {}
    for row in grade["rows"]:
        by_task.setdefault(row["task"], {})[row["arm"]] = row["score"]
    wins = sum(pair["candidate"] > pair["baseline"] for pair in by_task.values())
    losses = sum(pair["candidate"] < pair["baseline"] for pair in by_task.values())
    ties = sum(pair["candidate"] == pair["baseline"] for pair in by_task.values())
    non_ties = wins + losses
    smaller = min(wins, losses)
    sign_p = 1.0 if non_ties == 0 else min(
        1.0,
        2 * sum(math.comb(non_ties, value) for value in range(smaller + 1)) / 2**non_ties,
    )

    arms = {}
    for arm in ("baseline", "candidate"):
        grade_rows = [row for row in grade["rows"] if row["arm"] == arm]
        run_rows = [row for row in run if row["arm"] == arm]
        arms[arm] = {
            **grade["arms"][arm],
            "criteria": {
                key: sum(row["criteria"][key] for row in grade_rows)
                for key in grade_rows[0]["criteria"]
            },
            "model_seconds_total": round(sum(row["elapsed_seconds"] for row in run_rows), 3),
            "model_seconds_max": max(row["elapsed_seconds"] for row in run_rows),
            "grader_seconds_max": max(
                variant["elapsed_seconds"]
                for row in grade_rows for variant in row["variants"].values()
            ),
            "max_nonblank_test_loc": max(row["nonblank_test_loc"] for row in grade_rows),
        }

    adherence = {
        path.parent.name: six_answers_before_edit(path)
        for path in sorted(RAW.glob("*candidate/events.jsonl"))
    }
    result = {
        "frozen_input": {
            "freeze_commit": "ce600426",
            "candidate_sha256": sha256(ROOT / "candidate-prompt.md"),
            "baseline_sha256": sha256(ROOT / "baseline-prompt.md"),
            "manifest_entries": len((ROOT / "freeze-manifest.sha256").read_text().splitlines()),
            "grader_self_test": {"strong": "30/30", "weak": "14/30"},
        },
        "paired_task_scores": by_task,
        "paired_outcome": {
            "candidate_wins": wins,
            "candidate_losses": losses,
            "ties": ties,
            "two_sided_exact_sign_p": sign_p,
        },
        "arms": arms,
        "candidate_six_answers_before_edit": adherence,
        "candidate_adherence_count": f"{sum(adherence.values())}/{len(adherence)}",
        "score_gain": grade["score_gain"],
        "tool_whale": grade["tool_whale"],
    }
    (ROOT / "analysis-summary.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()


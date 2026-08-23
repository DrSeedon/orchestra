#!/usr/bin/env python3
"""Mechanical completeness/transcription gate for #255 (no model review)."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
rows = list(csv.DictReader((HERE / "turns.csv").open()))
artifact = json.loads((HERE / "bucket-summary.json").read_text())
research = (HERE / "research.md").read_text()
table = (HERE / "measurements.md").read_text()

assert len(rows) == 1280
assert len({row["event_id"] for row in rows}) == len(rows)
assert all(row["start_ts"] < row["end_ts"] for row in rows)
assert max(int(row["active_turns"]) for row in rows) == 12
assert not any(int(row["active_turns"]) >= 20 for row in rows)

expected_n = {"1": 329, "2-4": 609, "5-9": 320, "10-19": 22, "20+": 0}
assert {key: value["n"] for key, value in artifact["buckets"].items()} == expected_n
assert sum(expected_n.values()) == len(rows)
assert artifact["meta"]["exact_rollout_intervals"] == len(rows)
assert artifact["meta"]["db_start_lag_max_s"] > 13_000
assert artifact["meta"]["duration_disagreement_max_s"] < 0.5
assert artifact["snapshot_active_turns"] == {
    "2026-08-01T06:49:12+00:00_task_111_created": 4,
    "2026-08-01T06:56:00+00:00_second_snapshot": 8,
}
assert artifact["journal"]["usage_fetch_failure_active_distribution"] == {
    "0": 21,
    "1": 1,
    "2": 6,
    "3": 1,
}

high = artifact["buckets"]["10-19"]
one = artifact["buckets"]["1"]
assert high["error_n"] == 0
assert high["ttft_p90_s"] < one["ttft_p90_s"]
assert high["tokens_per_second_median"] > one["tokens_per_second_median"]
assert artifact["strata"]["effort=xhigh"]["10-19"]["ttft_median_s"] < 10
assert artifact["strata"]["role=full-cycle"]["10-19"]["ttft_median_s"] < 10

proxy = artifact["proxy_snapshot"]
assert proxy["active_connections"] < proxy["max_connections"]
assert proxy["rejected_connections"] == 0
assert proxy["route_failed"] == 0

for anchor in (
    "11.684/18.372",
    "22 против 4",
    "13 740 против 2 928",
    "9.827→9.691",
    "{0:21, 1:1, 2:6, 3:1}",
    "26 Sol calls",
    "Review: none",
):
    assert anchor in research, anchor

for header in (
    "UTC start interval",
    "active Codex turns",
    "observable process snapshot/boundary",
    "model / effort / tier / task class",
    "TTFT median/p90",
    "host load/CPU/RSS",
    "proxy endpoint + counters",
    "provider error/rate evidence",
    "negative/control traffic",
):
    assert header in table, header

secret = re.compile(
    r"y0_|sk-or-v1-|ya29\.|gh[pousr]_|AIza|Bearer\s+[A-Za-z0-9._-]{25,}", re.I
)
for path in HERE.iterdir():
    if path.name != "verify.py" and path.is_file() and path.suffix in {".md", ".json", ".csv", ".py"}:
        assert not secret.search(path.read_text(errors="replace")), path

print(
    "PASS #255: rows=1280 unique=1280 max_active=12 buckets=329/609/320/22/0 "
    "snapshots=4/8 proxy_rejected=0 proxy_failed=0 secrets=0"
)

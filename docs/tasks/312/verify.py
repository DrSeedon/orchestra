#!/usr/bin/env python3
"""Mechanical completeness and transcription gate for #312."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path


HERE = Path(__file__).resolve().parent
manifest = json.loads((HERE / "backup-manifest.json").read_text())
summary = json.loads((HERE / "summary.json").read_text())
change = json.loads((HERE / "change-point.json").read_text())
rows = list(csv.DictReader((HERE / "turns.csv").open()))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


backup = HERE / manifest["backup_private_relative_path"]
assert sha256(backup) == manifest["sha256"] == summary["meta"]["db_sha256"]
assert manifest["quick_check"] == "ok"
assert len(rows) == summary["meta"]["rows"] == 425
assert len({row["event_id"] for row in rows}) == len(rows)

required = {
    "session_id", "event_id", "usage_ts", "start_ts", "end_ts", "project", "worker",
    "model", "effort", "task_pipeline_class", "configured_effective_ceiling",
    "actual_input_tokens_total", "actual_cached_input_tokens", "actual_output_tokens",
    "precompact_outcome", "compact_outcome", "resume_outcome", "connect_outcome",
    "reader_outcome", "timeout_outcome", "error_outcome", "tool_rounds",
    "final_outcome_proxy", "wall_seconds", "ttft_seconds", "quota_revision",
    "quota_reset_cause", "machine_account_coverage",
}
assert required <= set(rows[0])
assert all(int(row["actual_cached_input_tokens"]) <= int(row["actual_input_tokens_total"]) for row in rows)

observed = [row for row in rows if row["configured_effective_ceiling"]]
old = [row for row in observed if int(row["configured_effective_ceiling"]) == 258400]
new = [row for row in observed if int(row["configured_effective_ceiling"]) == 828400]
assert len(old) == 31 and len(new) == 363
assert max(row["start_ts"] for row in old) == change["last_completed_old_window_task_start"][0]
assert min(row["start_ts"] for row in new) == change["first_new_window_task_start"][0]
assert max(row["start_ts"] for row in old) < min(row["start_ts"] for row in new)

pre = summary["cohorts"]["core_pre_all"]
post = summary["cohorts"]["core_post_all"]
assert pre["n"] == 31 and post["n"] == 35
assert pre["configured_windows"] == {"258400": 31}
assert post["configured_windows"] == {"828400": 34, "unobserved": 1}
assert summary["quota"]["core_pre"]["delta_percentage_points"] == 3
assert summary["quota"]["core_post"]["delta_percentage_points"] == 3
assert summary["quota"]["core_pre"]["same_plan_revision"] is True
assert summary["quota"]["core_post"]["same_plan_revision"] is True
assert summary["post_interruption_clusters"] == {
    "total": 25,
    "clusters": {
        "fleet_server_error_11:21-11:24": 12,
        "fleet_server_or_restart_cluster_16:42": 10,
        "other": 3,
    },
}
assert len(summary["image_incident"]) == 9
assert summary["direct_240"]["raw_token_bearing_calls"] == 26
assert summary["direct_240"]["review_calls"] == 2
assert summary["direct_240"]["unmeasured_reconnect_warmups"] == 2

assert "sessions.model" not in (HERE / "analysis.py").read_text()
assert "s.model" not in (HERE / "analysis.py").read_text()

secret_re = re.compile(r"(sk-[A-Za-z0-9_-]{20,}|sk-or-v1-|ya29\.|gh[pousr]_|AIza|Bearer\s+[A-Za-z0-9._~+/=-]{25,})")
checked = []
for path in sorted(HERE.iterdir()):
    if not path.is_file() or path.name in {"verify.py"}:
        continue
    if path.suffix not in {".md", ".json", ".csv", ".py", ".txt"} and path.name != ".gitignore":
        continue
    assert not secret_re.search(path.read_text(errors="replace")), path
    checked.append(path.name)

print(
    "PASS #312: "
    f"backup={manifest['sha256']} rows={len(rows)} unique={len(set(row['event_id'] for row in rows))} "
    f"rollout_complete={summary['meta']['rollout_complete_rows']} old/new={len(old)}/{len(new)} "
    f"core={pre['n']}/{post['n']} quota_delta=3/3 incident_rows={len(summary['image_incident'])} "
    f"secret_scan_files={len(checked)}"
)

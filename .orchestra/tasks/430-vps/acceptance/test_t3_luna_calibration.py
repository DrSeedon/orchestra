from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
POSITIVE = ROOT / "docs/tasks/430/evidence/luna-positive-control.json"
CALIBRATION = ROOT / "docs/tasks/430/evidence/luna-calibration.json"
RAW = ROOT / "docs/tasks/430/evidence/luna-calibration-raw.jsonl"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_t3_luna_calibration_freezes_noise_derived_thresholds() -> None:
    assert CALIBRATION.is_file(), "T3 missing six-case Luna calibration receipt"
    assert RAW.is_file(), "T3 missing calibration raw receipts"
    data = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    records = [json.loads(line) for line in RAW.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert data["schema"] == "skillstate430-luna-calibration-v1"
    assert data["model"] == "gpt-5.6-luna"
    assert data["case_count"] == 6
    assert data["completed_three_arm_cases"] == 6
    assert len({case["case_id"] for case in data["cases"]}) == 6
    assert data["provider_failures"] == 0
    assert data["malformed_outputs"] == 0
    assert data["protocol_failures"] == 0
    assert data["tool_calls"] == 0
    assert data["surface_audit"]["all_common_surface_hashes_match"] is True
    assert data["surface_audit"]["all_enums_and_normalizers_rendered"] is True
    assert data["positive_control_sha256"] == sha256(POSITIVE)
    assert data["raw_receipts_sha256"] == sha256(RAW)
    ends = [record for record in records if record["kind"] == "episode_end"]
    assert len(ends) == 18
    by_case: dict[str, dict[str, dict]] = {}
    for record in ends:
        by_case.setdefault(record["case_id"], {})[record["arm"]] = record
    assert len(by_case) == 6
    token_noise = []
    quality_noise = []
    for arms in by_case.values():
        assert set(arms) == {"append", "state", "append_repeat"}
        assert all(record["provider_complete"] and record["protocol_valid"] for record in arms.values())
        assert all(record["malformed_outputs"] == 0 for record in arms.values())
        left = arms["append"]["total_tokens"]
        right = arms["append_repeat"]["total_tokens"]
        token_noise.append(abs(left - right) / ((left + right) / 2))
        quality_noise.append(abs(arms["append"]["Q"] - arms["append_repeat"]["Q"]))
    assert data["noise"]["same_arm_total_token_relative_abs"] == token_noise
    assert data["noise"]["same_arm_quality_abs"] == quality_noise
    assert len(token_noise) == len(quality_noise) == 6
    assert all(value >= 0 for value in token_noise + quality_noise)
    thresholds = data["thresholds"]
    assert thresholds["method"] == "max_completed_same_arm_discrepancy_conservative_guard"
    assert math.isclose(thresholds["minimum_total_token_saving"], max(token_noise), rel_tol=0, abs_tol=1e-12)
    assert math.isclose(thresholds["quality_noninferiority_margin"], max(quality_noise), rel_tol=0, abs_tol=1e-12)
    assert thresholds["critical_reason_losses_allowed"] == 0
    assert data["thresholds_frozen_at"]
    assert data["raw_receipts_sha256"]

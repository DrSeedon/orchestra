from __future__ import annotations

import json
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
RECEIPT = ROOT / "docs/tasks/430/evidence/luna-positive-control-v2.json"
RAW = ROOT / "docs/tasks/430/evidence/luna-positive-control-v2-raw.jsonl"
SPEC = ROOT / "scripts/skillstate430/luna_benchmark_spec.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_t2_luna_positive_control_green_before_calibration() -> None:
    assert RECEIPT.is_file(), "T2 missing live Luna positive-control receipt"
    assert RAW.is_file(), "T2 missing positive-control raw receipt"
    data = json.loads(RECEIPT.read_text(encoding="utf-8"))
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    records = [json.loads(line) for line in RAW.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert data["schema"] == "skillstate430-luna-positive-control-v2"
    assert data["spec_sha256"] == sha256(SPEC)
    assert data["raw_receipts_sha256"] == sha256(RAW)
    assert data["model"] == "gpt-5.6-luna"
    assert data["case_id"] == spec["positive_control"]["case_id"]
    assert data["step_count"] == len(spec["positive_control"]["steps"]) == 3
    assert data["completed_three_arm_cases"] == 1
    assert data["provider_failures"] == 0
    assert data["malformed_outputs"] == 0
    assert data["protocol_failures"] == 0
    assert data["resumed_sessions"] == 0
    assert data["tool_calls"] == 0
    assert data["request_order_audit"]["strict_rotating_primary_ab"] is True
    arms = data["arms"]
    assert set(arms) == {"append", "state", "append_repeat"}
    common_hashes = set()
    thread_ids: list[str] = []
    for arm in arms.values():
        assert arm["call_outcome"] == "provider_success"
        assert arm["model_outcome"] == "success"
        assert arm["protocol_valid"] is True
        assert arm["attempts_per_call"] == 1
        common_hashes.add(arm["common_surface_hash"])
        thread_ids.extend(arm["thread_ids"])
    assert len(common_hashes) == 1, "T2 rendered schema/tool/controller surface differs across arms"
    assert len(thread_ids) == len(set(thread_ids)), "T2 each step must use a fresh ephemeral Codex thread"
    assert data["surface_delivery"]["action_schema_hash_match"] is True
    assert data["surface_delivery"]["tool_manifest_hash_match"] is True
    assert data["surface_delivery"]["controller_params_hash_match"] is True
    assert data["surface_delivery"]["all_enums_and_normalizers_rendered"] is True

    steps = [record for record in records if record["kind"] == "step"]
    ends = [record for record in records if record["kind"] == "episode_end"]
    assert len(steps) == spec["positive_control"]["expected_codex_exec_calls"] == 9
    assert len(ends) == 3
    expected_pairs = {
        (arm, step["event_id"])
        for arm in spec["positive_control"]["arms"]
        for step in spec["positive_control"]["steps"]
    }
    assert {(record["arm"], record["event_id"]) for record in steps} == expected_pairs
    assert all(record["call_outcome"] == "provider_success" for record in steps)
    assert all(record["output_outcome"] == "valid_json" for record in steps)
    assert all(record["tool_calls"] == 0 and record["resumed"] is False for record in steps)
    assert len({record["thread_id"] for record in steps}) == len(steps)
    for record in ends:
        assert record["final_action"] == spec["positive_control"]["gold_action"]
        assert record["Q"] == 1
        assert record["critical_reason_loss"] is False

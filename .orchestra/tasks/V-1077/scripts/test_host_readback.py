"""Validate supplied host attestation against local evidence, without accessing the host."""
import hashlib
import json
from pathlib import Path

import pytest

from app.pipeline import _merge_list

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[2]
RECEIPT = json.loads((TASK / "sources/host-readback.json").read_text())
INVENTORY = json.loads((TASK / "inventory.json").read_text())


@pytest.mark.parametrize("row", RECEIPT["skill_rows"], ids=lambda row: row["name"])
def test_host_skill_hash_matches_local_source_and_inventory(row):
    source = next(item for item in INVENTORY["skills"] if item["name"] == row["name"])
    digest = hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest()
    assert row["repo_codex_sha256"] == row["inventory_sha256"] == source["sha256"] == digest
    assert row["match_inventory"] and row["match_canonical"]
    assert row["canonical_tracked"] and not row["destination_tracked"]


@pytest.mark.parametrize("row", RECEIPT["references"], ids=lambda row: row["relative_path"])
def test_host_reference_attestation_matches_inventory_coverage(row):
    relative = ".orchestra/pipelines/default/prompts/skills/" + row["relative_path"]
    source = next(item for item in INVENTORY["reference_metrics"] if item["path"] == relative)
    assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == source["sha256"]
    assert row["source_match_inventory"] and row["destination_present"] and row["destination_matches"]
    assert not row["destination_tracked"]


@pytest.mark.parametrize("role", RECEIPT["raw_role_skills"])
def test_host_effective_role_list_matches_existing_merge_code(role):
    assert _merge_list(RECEIPT["defaults_skills"], RECEIPT["raw_role_skills"][role]) == RECEIPT["effective_resolved_skills"][role]


def test_receipt_complete_sets_and_independent_scaffold_observation():
    assert {row["name"] for row in RECEIPT["skill_rows"]} == {row["name"] for row in INVENTORY["skills"]}
    assert len(RECEIPT["skill_rows"]) == 7 and len(RECEIPT["references"]) == 3
    assert RECEIPT["documented_scaffold_extraction_bytes"] == {
        "SKILL.md": INVENTORY["scaffold_extraction_bytes"]["entrypoint_as_documented"],
        "references/animation.md": INVENTORY["scaffold_extraction_bytes"]["actual_reference"],
    }
    assert RECEIPT["claude_md_symlink"] and RECEIPT["claude_md_target"] == "AGENTS.md"


def test_runtime_sample_coverage_is_bounded_and_path_free():
    samples = RECEIPT["runtime_samples"]
    assert len(samples) == 5
    assert {item["role"] for item in samples} == {"orchestrator", "worker", "full-cycle"}
    assert sum(item["persisted_backend_type"] == "claude" for item in samples) == 3
    assert all(item["project_claude_skills_present"] for item in samples if item["persisted_backend_type"] == "claude")
    assert all(not any("path" in key or key == "cwd" for key in item) for item in samples)

"""Corrected frozen T4 oracle.

V1 remains immutable evidence.  V2 selects the same projection behaviors, creates the
alternate-mode fixture root explicitly, and proves that setup independently in a control.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "test_t4_projection_heads_behavior.py"
CONTRACT_PATH = HERE / "fixtures" / "t4_projection_contract_v2.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _contract() -> dict:
    return _json(CONTRACT_PATH)


def _v1():
    spec = importlib.util.spec_from_file_location("t4_projection_oracle_v1_for_v2", V1_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_t4_v2_control_supersession_and_v1_bytes_are_frozen():
    contract = _contract()
    assert contract["contract_version"] == 2
    assert contract["permanently_superseded"]["worker_commit"].startswith("863c7bd9")
    assert contract["replacement"]["expected_controls"] == 5
    assert contract["replacement"]["expected_behavior_nodes"] == 7
    for relative, expected in contract["immutable_v1_sha256"].items():
        assert hashlib.sha256(Path(relative).read_bytes()).hexdigest() == expected


def test_t4_v2_control_fixture_hash_denominators_and_compatibility_are_frozen():
    _v1().test_t4_control_fixture_hash_denominators_and_t1_t3b_compatibility_are_frozen()


@pytest.mark.asyncio
async def test_t4_v2_control_existing_agent_query_reaches_t3b_owner(tmp_path, monkeypatch):
    await _v1().test_t4_control_existing_agent_query_reaches_t3b_owner(tmp_path, monkeypatch)


def test_t4_v2_control_real_task_fact_and_legacy_fixture_are_nonempty(tmp_path):
    _v1().test_t4_control_real_task_fact_and_legacy_fixture_are_nonempty(tmp_path)


def test_t4_v2_control_alternate_fixture_path_and_mutant_detectors_execute(tmp_path):
    v1 = _v1()
    v1.test_t4_control_valid_alternate_and_compound_mutant_detectors_are_material()
    t3 = v1._t3_oracle_module()
    root = tmp_path / _contract()["replacement"]["alternate_fixture_root"]
    root.mkdir(parents=True, exist_ok=False)
    api = t3._load_api()
    context = t3._materialization_context(root)
    with t3._knowledge_mode(api, root, context):
        result = t3._promote(api, v1._current_request(t3, context))
        query = t3._query(api, topic="repo-ops", fact_key="worker-wip-scope")
    assert result["outcome"] == "created"
    assert query["count"] == 1
    assert (root / "registry-input.json").is_file()
    assert (root / "knowledge-main" / "registry.json").is_file()


@pytest.mark.asyncio
async def test_t4_v2_query_synchronously_projects_current_and_allows_alternate_backend(
    tmp_path,
    monkeypatch,
):
    (tmp_path / _contract()["replacement"]["alternate_fixture_root"]).mkdir(
        parents=True,
        exist_ok=False,
    )
    await _v1().test_t4_query_synchronously_projects_current_task_fact_and_exposes_index_lag(
        tmp_path,
        monkeypatch,
    )


def test_t4_v2_stale_sqlite_fts_vector_cannot_hide_changed_canonical(tmp_path):
    _v1().test_t4_stale_sqlite_fts_and_vector_cannot_hide_changed_canonical_records(tmp_path)


def test_t4_v2_forged_equal_head_stale_payload_falls_back_to_canonical(tmp_path, monkeypatch):
    _v1().test_t4_forged_equal_head_with_stale_payload_falls_back_to_canonical(
        tmp_path,
        monkeypatch,
    )


def test_t4_v2_vector_failure_never_erases_current_canonical(tmp_path):
    _v1().test_t4_vector_failure_never_erases_current_canonical_results(tmp_path)


def test_t4_v2_projection_write_failure_returns_current_with_debt(tmp_path, monkeypatch):
    _v1().test_t4_projection_write_failure_after_canonical_commit_returns_current_with_debt(
        tmp_path,
        monkeypatch,
    )


@pytest.mark.asyncio
async def test_t4_v2_missing_canonical_fails_closed_over_all_fallbacks(tmp_path, monkeypatch):
    await _v1().test_t4_missing_canonical_fails_closed_over_stale_sqlite_vector_and_file(
        tmp_path,
        monkeypatch,
    )


@pytest.mark.asyncio
async def test_t4_v2_legacy_rebuild_memory_route_use_shared_projection(tmp_path, monkeypatch):
    await _v1().test_t4_legacy_rebuild_and_memory_route_use_shared_projection_without_file_fallback(
        tmp_path,
        monkeypatch,
    )

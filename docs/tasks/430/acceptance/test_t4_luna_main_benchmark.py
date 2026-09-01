from __future__ import annotations

import hashlib
import json
import math
import random
import subprocess
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = ROOT / "docs/tasks/430/evidence"
POPULATION = EVIDENCE / "luna-population.json"
POSITIVE = EVIDENCE / "luna-positive-control.json"
CALIBRATION = EVIDENCE / "luna-calibration.json"
SUMMARY = EVIDENCE / "luna-main-summary.json"
REPORT = ROOT / "docs/tasks/430/report.md"
RAW = EVIDENCE / "luna-main-raw.jsonl"
CASES = ROOT / "scripts/skillstate430/luna_cases.json"
CENSUS = ROOT / "scripts/skillstate430/luna_census_source.json"
SPEC = ROOT / "scripts/skillstate430/luna_benchmark_spec.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _selection_key(task_id: int) -> str:
    assert isinstance(task_id, int) and not isinstance(task_id, bool), "census case.task_id must be an integer"
    return hashlib.sha256(f"skillstate430-luna-v1:{task_id}".encode()).hexdigest()


def _source_digest(source_paths: list[str], source_loader) -> str:
    assert source_paths, "eligible census row requires source_paths"
    digest = hashlib.sha256()
    for source_path in sorted(source_paths):
        payload = source_loader(source_path)
        assert isinstance(payload, bytes), "source loader must return actual bytes"
        encoded = source_path.encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _assert_census_selection(census: dict, cohort: list[dict], strata: list[str], source_loader,
                             discovered_task_ids: set[int]) -> dict:
    rows = census["rows"]
    task_ids: list[int] = []
    eligible_by_stratum: dict[str, list[dict]] = {stratum: [] for stratum in strata}
    for row in rows:
        assert "task_id" in row, "census row missing case.task_id"
        task_id = row["task_id"]
        assert isinstance(task_id, int) and not isinstance(task_id, bool), "census case.task_id must be an integer"
        task_ids.append(task_id)
        if not row["eligible"]:
            assert row["exclusion_reason"], "excluded census row requires a reason"
            continue
        assert row["stratum"] in eligible_by_stratum, f"unknown census stratum: {row['stratum']}"
        actual_digest = _source_digest(row["source_paths"], source_loader)
        assert row["source_sha256"] == actual_digest, f"source digest mismatch for task_id={task_id}"
        assert row["selection_key"] == _selection_key(task_id), f"selection key mismatch for task_id={task_id}"
        eligible_by_stratum[row["stratum"]].append(row)
    assert len(task_ids) == len(set(task_ids)), "duplicate task_id in census"
    assert set(task_ids) == discovered_task_ids, "census does not cover independently discovered task ids"

    expected: list[dict] = []
    for stratum in strata:
        candidates = sorted(
            eligible_by_stratum[stratum],
            key=lambda row: (row["selection_key"], row["task_id"]),
        )
        assert len(candidates) >= 6, f"fewer than six eligible cases in {stratum}"
        expected.extend(candidates[:6])

    for case in cohort:
        assert "task_id" in case, "selected case missing case.task_id"
    expected_projection = sorted(
        (row["task_id"], row["stratum"], row["source_sha256"]) for row in expected
    )
    actual_projection = sorted(
        (case["task_id"], case["stratum"], case["source_sha256"]) for case in cohort
    )
    assert actual_projection == expected_projection, "selected cohort is not deterministic top-six from census"
    return {
        "census_total": len(rows),
        "eligible_total": sum(len(items) for items in eligible_by_stratum.values()),
        "selected_total": len(expected),
    }


def _git_discovered_task_ids(source_commit: str) -> set[int]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", source_commit, "--", "docs/tasks"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    discovered: set[int] = set()
    for path in result.stdout.splitlines():
        parts = Path(path).parts
        if len(parts) >= 4 and parts[0:2] == ("docs", "tasks") and parts[2].isdigit():
            if parts[-1] in {"research.md", "plan.md", "report.md"}:
                discovered.add(int(parts[2]))
    return discovered


def _git_source_loader(source_commit: str):
    def load(path: str) -> bytes:
        return subprocess.run(
            ["git", "show", f"{source_commit}:{path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout

    return load


def test_t4_census_oracle_rejects_arbitrary_well_formed_cohort(tmp_path: Path) -> None:
    strata = [f"stratum_{index}" for index in range(5)]
    rows: list[dict] = []
    for stratum_index, stratum in enumerate(strata):
        for offset in range(7):
            task_id = 1000 + stratum_index * 100 + offset
            relative = f"sources/{task_id}.md"
            source = tmp_path / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(f"task {task_id} source v1\n", encoding="utf-8")
            rows.append({
                "task_id": task_id,
                "eligible": True,
                "exclusion_reason": None,
                "stratum": stratum,
                "source_paths": [relative],
                "source_sha256": _source_digest([relative], lambda path: (tmp_path / path).read_bytes()),
                "selection_key": _selection_key(task_id),
            })
    discovered = {row["task_id"] for row in rows}
    cohort: list[dict] = []
    for stratum in strata:
        selected = sorted(
            (row for row in rows if row["stratum"] == stratum),
            key=lambda row: (row["selection_key"], row["task_id"]),
        )[:6]
        cohort.extend(deepcopy(selected))
    census = {"rows": rows}
    loader = lambda path: (tmp_path / path).read_bytes()
    assert _assert_census_selection(census, cohort, strata, loader, discovered)["selected_total"] == 30

    missing_task_id = deepcopy(cohort)
    missing_task_id[0].pop("task_id")
    with pytest.raises(AssertionError, match="missing case.task_id"):
        _assert_census_selection(census, missing_task_id, strata, loader, discovered)

    arbitrary = deepcopy(cohort)
    first_stratum = sorted(
        (row for row in rows if row["stratum"] == strata[0]),
        key=lambda row: (row["selection_key"], row["task_id"]),
    )
    arbitrary[0] = deepcopy(first_stratum[6])
    assert len(arbitrary) == 30 and all(set(("task_id", "stratum", "source_sha256")) <= set(case) for case in arbitrary)
    with pytest.raises(AssertionError, match="deterministic top-six"):
        _assert_census_selection(census, arbitrary, strata, loader, discovered)

    tampered_path = tmp_path / cohort[0]["source_paths"][0]
    tampered_path.write_text("same path, replaced bytes\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="source digest mismatch"):
        _assert_census_selection(census, cohort, strata, loader, discovered)


def test_t4_luna_main_benchmark_is_complete_and_protocol_bound() -> None:
    assert POPULATION.is_file(), "T4 missing frozen Luna population ledger"
    assert SUMMARY.is_file(), "T4 missing Luna N=30 main summary"
    assert REPORT.is_file(), "T4 missing benchmark decision report"
    assert RAW.is_file(), "T4 missing Luna main raw receipts"
    assert CASES.is_file(), "T4 missing frozen N=30 case payloads"
    assert CENSUS.is_file(), "T4 missing full eligible-census source ledger"
    population = json.loads(POPULATION.read_text(encoding="utf-8"))
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    positive = json.loads(POSITIVE.read_text(encoding="utf-8"))
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    census = json.loads(CENSUS.read_text(encoding="utf-8"))
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    raw = [json.loads(line) for line in RAW.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert population["schema"] == "skillstate430-luna-population-v1"
    rebuilt = _assert_census_selection(
        census,
        population["selected_cases"],
        [item["key"] for item in spec["strata"]],
        _git_source_loader(census["source_commit"]),
        _git_discovered_task_ids(census["source_commit"]),
    )
    assert rebuilt["census_total"] == population["census_total"]
    assert rebuilt["eligible_total"] == population["eligible_total"]
    assert rebuilt["selected_total"] == population["selected_total"]
    assert population["selected_total"] == 30
    assert len(population["selected_cases"]) == 30
    assert len({case["case_id"] for case in population["selected_cases"]}) == 30
    assert sum(item["selected"] for item in population["strata"].values()) == 30
    for item in population["strata"].values():
        assert item["selected"] == 6
        assert item["eligible"] >= item["selected"]
        assert item["sampling_fraction"] == item["selected"] / item["eligible"]
    assert sum(population["exclusions"].values()) + population["eligible_total"] == population["census_total"]
    assert all(case["source_sha256"] for case in population["selected_cases"])
    selected_ids = {case["case_id"] for case in population["selected_cases"]}
    assert {case["case_id"] for case in cases} == selected_ids
    population_strata = {case["case_id"]: case["stratum"] for case in population["selected_cases"]}
    case_strata = {case["case_id"]: case["stratum"] for case in cases}
    assert case_strata == population_strata
    assert {
        stratum: sum(case["stratum"] == stratum for case in cases)
        for stratum in {item["key"] for item in spec["strata"]}
    } == {stratum: 6 for stratum in case_strata.values()}
    required = set(spec["case_format"]["required_fields"])
    strata = {item["key"] for item in spec["strata"]}
    for case in cases:
        assert required <= set(case)
        assert case["stratum"] in strata
        assert 8 <= len(case["observations"]) <= 12
        assert case["source_paths"] and case["source_sha256"]

    assert summary["schema"] == "skillstate430-luna-main-v1"
    assert summary["model"] == "gpt-5.6-luna"
    assert summary["case_count"] == 30
    assert summary["completed_pairs"] == 30
    step_records = [record for record in raw if record["kind"] == "step"]
    end_records = [record for record in raw if record["kind"] == "episode_end"]
    expected_calls = sum(len(case["observations"]) * 2 for case in cases)
    assert 480 <= expected_calls <= 720
    assert summary["codex_exec_calls"] == len(step_records) == expected_calls
    assert len(end_records) == 60
    assert {(record["case_id"], record["arm"]) for record in end_records} == {
        (case_id, arm) for case_id in selected_ids for arm in ("append", "state")
    }
    assert all(record["call_outcome"] == "provider_success" for record in step_records)
    assert all(record["output_outcome"] == "valid_json" for record in step_records)
    assert all(record["model_outcome"] == "model_valid" for record in step_records)
    assert all(record["protocol_valid"] is True for record in step_records)
    assert all(record["attempts"] == 1 and record["resumed"] is False for record in step_records)
    assert len({record["thread_id"] for record in step_records}) == len(step_records)
    assert all(record["stratum"] == case_strata[record["case_id"]] for record in step_records)
    assert summary["provider_failures"] == 0
    assert summary["malformed_outputs"] == 0
    assert summary["protocol_failures"] == 0
    assert summary["tool_calls"] == 0
    assert summary["free_lane_runs"] == 0
    assert summary["request_order_audit"]["strict_interleaved_ab"] is True
    assert summary["surface_audit"]["all_common_surface_hashes_match"] is True
    assert summary["surface_audit"]["all_enums_and_normalizers_rendered"] is True
    assert summary["positive_control_sha256"] == sha256(POSITIVE)
    assert summary["calibration_sha256"] == sha256(CALIBRATION)
    assert summary["spec_sha256"] == sha256(SPEC)
    assert summary["raw_receipts_sha256"] == sha256(RAW)
    assert summary["codex_binary_sha256"] == positive["codex_cli"]["binary_sha256"]
    assert summary["codex_cli_version"] == positive["codex_cli"]["version"]
    assert summary["thresholds"] == calibration["thresholds"]
    assert datetime.fromisoformat(summary["main_first_response_at"]) > datetime.fromisoformat(
        calibration["thresholds_frozen_at"]
    )

    by_case: dict[str, dict[str, dict]] = {}
    for record in end_records:
        by_case.setdefault(record["case_id"], {})[record["arm"]] = record
    ordered_cases = sorted(by_case)
    assert all(set(arms) == {"append", "state"} for arms in by_case.values())
    rng = random.Random(spec["bootstrap"]["seed"])
    ratios: list[float] = []
    quality_diffs: list[float] = []
    for _ in range(spec["bootstrap"]["replicates"]):
        sample = [ordered_cases[rng.randrange(len(ordered_cases))] for _ in ordered_cases]
        ratios.append(
            sum(by_case[case_id]["state"]["total_tokens"] for case_id in sample)
            / sum(by_case[case_id]["append"]["total_tokens"] for case_id in sample)
        )
        quality_diffs.append(
            sum(by_case[case_id]["state"]["Q"] - by_case[case_id]["append"]["Q"] for case_id in sample)
            / len(sample)
        )
    ratios.sort()
    quality_diffs.sort()
    lower_index = math.floor(0.10 * (len(ratios) - 1))
    upper_index = math.ceil(0.90 * (len(ratios) - 1))
    metrics = summary["metrics"]
    assert math.isclose(metrics["total_token_ratio_ci90_upper"], ratios[upper_index], rel_tol=0, abs_tol=1e-12)
    assert math.isclose(metrics["quality_diff_ci90_lower"], quality_diffs[lower_index], rel_tol=0, abs_tol=1e-12)
    assert metrics["state_critical_reason_losses"] == sum(
        int(by_case[case_id]["state"]["critical_reason_loss"]) for case_id in ordered_cases
    )
    thresholds = summary["thresholds"]
    token_gate = metrics["total_token_ratio_ci90_upper"] < 1 - thresholds["minimum_total_token_saving"]
    quality_gate = metrics["quality_diff_ci90_lower"] >= -thresholds["quality_noninferiority_margin"]
    critical_gate = metrics["state_critical_reason_losses"] == thresholds["critical_reason_losses_allowed"]
    assert summary["gates"] == {
        "token": token_gate,
        "quality": quality_gate,
        "critical_reasons": critical_gate,
    }
    if not quality_gate or not critical_gate:
        expected_decision = "state_harms"
    elif token_gate:
        expected_decision = "state_wins"
    else:
        expected_decision = "no_measured_win"
    assert summary["decision"] == expected_decision
    guard = summary["production_db_guard"]
    assert guard["sqlite_connections_all_mode_ro"] is True
    assert guard["query_only"] == 1
    assert guard["sqlite_total_changes"] == 0
    assert guard["backup_method"] == "sqlite3.Connection.backup"
    assert guard["db_dependent_probes_used_backup"] is True
    assert guard["protected_paths"] == spec["production_db_guard"]["traced_paths"]
    assert guard["write_syscalls"] == 0
    assert summary["production_db_sessions_before"] == summary["production_db_sessions_after"]

    report = REPORT.read_text(encoding="utf-8")
    assert f"Decision: {expected_decision}" in report
    assert "N=30" in report
    assert "research/architecture/incident/high-risk" in report
    assert "provider outcome" in report and "model outcome" in report

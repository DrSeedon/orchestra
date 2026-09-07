from __future__ import annotations

import json
import hashlib
import math
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "scripts/recon429"
# Repointed after commit ea03e8d3 moved project state docs/ -> .orchestra/ mid-task.
# Path only: the assertions are unchanged and both oracles stay RED until the run
# actually produces results/final.json and report.md.
TASK = ROOT / ".orchestra/tasks/432"
PYTHON = sys.executable
PRICE_REVISION = "ea27c8c444bdab441d4ffc3ad87172c62d7ea3a6c0b6eacd1f935f27cdfcdba3"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, str(script), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _luna_usage() -> dict[str, int]:
    # API-equivalent Luna cost under app/backend_codex.py's frozen Phase-2 rates:
    # fresh 300*0.2 + cached 600*0.02 + write 100*0.25 + output 200*1.2 = $0.000337.
    return {
        "input_tokens": 1000,
        "cached_input_tokens": 600,
        "cache_write_input_tokens": 100,
        "output_tokens": 200,
    }


def test_t1_controller_keeps_oracle_outside_model_and_freezes_red_green(tmp_path: Path) -> None:
    script = SCRIPTS / "oracle_controller_432.py"
    manifest = TASK / "oracles/manifest.json"
    assert script.exists(), "missing behavior T1: controller-only oracle CLI does not exist"
    assert manifest.exists(), "missing behavior T1: 12-task oracle manifest is not frozen"

    data = json.loads(manifest.read_text())
    assert data["schema_version"] == 1
    assert [row["task"] for row in data["episodes"]] == [
        364, 396, 397, 398, 401, 412, 413, 415, 416, 417, 418, 424
    ]
    for row in data["episodes"]:
        assert row["command"], row
        assert row["oracle_files"] and all(item["sha256"] for item in row["oracle_files"])
        assert row["baseline_red"]["rc"] != 0
        assert "missing behavior" in row["baseline_red"]["failure_line"].lower()
        assert row["result_green"]["rc"] == 0
        exposed = json.dumps(row["model_inputs"], sort_keys=True)
        assert row["result_commit"] not in exposed
        assert not any(item["path"] in exposed for item in row["oracle_files"])

    completed = _run(
        script,
        "self-test",
        "--scratch",
        str(tmp_path),
        "--manifest",
        str(manifest),
    )
    assert completed.returncode == 0, completed.stdout
    result = json.loads(completed.stdout)
    assert result["absolute_oracle_read"] == "DENY"
    assert result["traversal_oracle_read"] == "DENY"
    assert result["auth_file_read"] == "DENY"
    assert result["env_secret_read"] == "DENY"
    assert result["cli_authenticated"] is True
    assert result["model_workspace_only"] is True
    assert result["result_commit_visible"] is False
    assert result["judge_after_model_exit"] is True
    assert result["judge_timeout_classification"] == "harness_failure"
    assert result["live_sessions_after"] == result["live_sessions_before"]


def test_t2_inline_arm_records_full_main_cost_and_separates_provider_failure(
    tmp_path: Path,
) -> None:
    script = SCRIPTS / "run_inline_432.py"
    assert script.exists(), "missing behavior T2: inline Luna arm runner does not exist"
    db_path = tmp_path / "run.sqlite3"
    success_fixture = tmp_path / "success.json"
    timeout_fixture = tmp_path / "timeout.json"
    _write_json(
        success_fixture,
        {
            "model": "gpt-5.6-luna",
            "provider_status": "completed",
            "intermediate_usages": [
                {
                    "input_tokens": 400,
                    "cached_input_tokens": 200,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 50,
                }
            ],
            "terminal_usages": [_luna_usage()],
            "oracle_id": "oracle-364-v1",
            "oracle_status": "pass",
        },
    )
    _write_json(
        timeout_fixture,
        {
            "model": "gpt-5.6-luna",
            "provider_status": "timeout",
            "provider_started": True,
            "terminal_usages": [],
            "oracle_id": "oracle-364-v1",
            "oracle_status": "not_run",
        },
    )
    zero_terminal_fixture = tmp_path / "zero-terminal.json"
    duplicate_terminal_fixture = tmp_path / "duplicate-terminal.json"
    _write_json(
        zero_terminal_fixture,
        {
            "model": "gpt-5.6-luna",
            "provider_status": "completed",
            "provider_started": True,
            "terminal_usages": [],
            "oracle_id": "oracle-364-v1",
            "oracle_status": "not_run",
        },
    )
    _write_json(
        duplicate_terminal_fixture,
        {
            "model": "gpt-5.6-luna",
            "provider_status": "completed",
            "provider_started": True,
            "terminal_usages": [_luna_usage(), _luna_usage()],
            "oracle_id": "oracle-364-v1",
            "oracle_status": "not_run",
        },
    )

    success = _run(
        script,
        "--fixture",
        str(success_fixture),
        "--db",
        str(db_path),
        "--slot",
        "364:A:1",
    )
    assert success.returncode == 0, success.stdout
    success_row = json.loads(success.stdout)
    assert success_row["arm"] == "A"
    assert success_row["classification"] == "success"
    assert success_row["currency"] == "api_equivalent_usd"
    assert success_row["price_source"] == "app/backend_codex.py::_codex_cost"
    assert success_row["price_revision_sha256"] == PRICE_REVISION
    assert success_row["usage_accounting"] == "one_terminal_cumulative_row_per_role"
    assert math.isclose(success_row["main_cost_usd"], 0.000337, abs_tol=1e-12)
    assert success_row["scout_cost_usd"] == 0
    assert success_row["total_cost_usd"] == success_row["main_cost_usd"]

    timeout = _run(
        script,
        "--fixture",
        str(timeout_fixture),
        "--db",
        str(db_path),
        "--slot",
        "364:A:timeout",
    )
    assert timeout.returncode == 0, timeout.stdout
    timeout_row = json.loads(timeout.stdout)
    assert timeout_row["classification"] == "availability_failure"
    assert timeout_row["success"] is False
    assert timeout_row["model_failure"] is False
    assert timeout_row["retry_allowed"] is False

    zero_terminal = _run(
        script,
        "--fixture",
        str(zero_terminal_fixture),
        "--db",
        str(db_path),
        "--slot",
        "364:A:zero-terminal",
    )
    assert zero_terminal.returncode == 0, zero_terminal.stdout
    zero_row = json.loads(zero_terminal.stdout)
    assert zero_row["classification"] == "harness_failure"
    assert zero_row["failure_source"] == "completed_without_terminal_usage"
    assert zero_row["retry_allowed"] is False

    duplicate_terminal = _run(
        script,
        "--fixture",
        str(duplicate_terminal_fixture),
        "--db",
        str(db_path),
        "--slot",
        "364:A:duplicate-terminal",
    )
    assert duplicate_terminal.returncode == 0, duplicate_terminal.stdout
    duplicate_row = json.loads(duplicate_terminal.stdout)
    assert duplicate_row["classification"] == "harness_failure"
    assert duplicate_row["failure_source"] == "multiple_terminal_usage_events"
    assert duplicate_row["cost_unaccounted"] is True
    assert duplicate_row["retry_allowed"] is False

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT role,model,cost_usd,classification FROM turn_usage ORDER BY slot"
        ).fetchall()
    assert rows == [
        ("main", "gpt-5.6-luna", 0.000337, "success"),
        ("main", "gpt-5.6-luna", 0.0, "harness_failure"),
        ("main", "gpt-5.6-luna", 0.0, "availability_failure"),
        ("main", "gpt-5.6-luna", 0.0, "harness_failure"),
    ]


def test_t3_scout_arm_sums_scout_and_main_under_the_same_oracle(tmp_path: Path) -> None:
    script = SCRIPTS / "run_scout_432.py"
    assert script.exists(), "missing behavior T3: scout+main Luna arm runner does not exist"
    db_path = tmp_path / "run.sqlite3"
    fixture = tmp_path / "scout.json"
    bundle_path = tmp_path / "handoff.json"
    bundle = {
        "schema_version": 1,
        "chunks": [{"path": "app/example.py", "start": 1, "text": "x" * 119_900}],
    }
    _write_json(
        fixture,
        {
            "oracle_id": "oracle-364-v1",
            "bundle": bundle,
            "scout": {
                "model": "gpt-5.6-luna",
                "provider_status": "completed",
                "intermediate_usages": [{"input_tokens": 100, "output_tokens": 10}],
                "terminal_usages": [{
                    "input_tokens": 500,
                    "cached_input_tokens": 200,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 100,
                }],
            },
            "main": {
                "model": "gpt-5.6-luna",
                "provider_status": "completed",
                "terminal_usages": [_luna_usage()],
                "oracle_status": "pass",
            },
        },
    )
    completed = _run(
        script,
        "--fixture",
        str(fixture),
        "--db",
        str(db_path),
        "--slot",
        "364:B:1",
        "--bundle-out",
        str(bundle_path),
    )
    assert completed.returncode == 0, completed.stdout
    row = json.loads(completed.stdout)
    assert row["arm"] == "B" and row["classification"] == "success"
    assert row["currency"] == "api_equivalent_usd"
    assert row["price_source"] == "app/backend_codex.py::_codex_cost"
    assert row["price_revision_sha256"] == PRICE_REVISION
    assert row["usage_accounting"] == "one_terminal_cumulative_row_per_role"
    assert row["oracle_id"] == "oracle-364-v1"
    serialized = bundle_path.read_bytes()
    assert row["bundle_bytes"] == len(serialized) <= 262_144
    assert row["bundle_sha256"] == hashlib.sha256(serialized).hexdigest()
    assert row["main_handoff_sha256"] == row["bundle_sha256"]
    assert math.isclose(row["scout_cost_usd"], 0.000184, abs_tol=1e-12)
    assert math.isclose(row["main_cost_usd"], 0.000337, abs_tol=1e-12)
    assert math.isclose(row["total_cost_usd"], 0.000521, abs_tol=1e-12)

    with sqlite3.connect(db_path) as connection:
        roles = connection.execute(
            "SELECT role,cost_usd FROM turn_usage ORDER BY role"
        ).fetchall()
    assert roles == [("main", 0.000337), ("scout", 0.000184)]


def _complete_ledger() -> dict:
    pairs = []
    for task in range(1, 13):
        order = "ABAB" if task <= 6 else "BABA"
        for repetition in (1, 2):
            pairs.append(
                {
                    "task": task,
                    "repetition": repetition,
                    "order": order,
                    "A": {
                        "classification": "success",
                        "main_cost_usd": 1.0,
                        "scout_cost_usd": 0.0,
                        "total_cost_usd": 1.0,
                        "main_cache_read_tokens": 100,
                        "net_cache_read_tokens": 100,
                        "oracle_id": f"oracle-{task}",
                    },
                    "B": {
                        "classification": "success",
                        "main_cost_usd": 0.7,
                        "scout_cost_usd": 0.1,
                        "total_cost_usd": 0.8,
                        "main_cache_read_tokens": 70,
                        "net_cache_read_tokens": 90,
                        "oracle_id": f"oracle-{task}",
                    },
                }
            )
    noise = []
    for task in range(1, 7):
        noise.append(
            {
                "task": task,
                "cost_A01": 1.0,
                "cost_A02": 1.0,
                "main_cache_A01": 0 if task == 1 else 100,
                "main_cache_A02": 0 if task == 1 else 100,
            }
        )
    return {"pairs": pairs, "noise": noise}


def test_t4_analysis_keeps_24_pairs_counterbalances_order_and_never_promotes_failures(
    tmp_path: Path,
) -> None:
    script = SCRIPTS / "analyze_432.py"
    assert script.exists(), "missing behavior T4: paired experiment analyzer does not exist"
    complete_path = tmp_path / "complete.json"
    _write_json(complete_path, _complete_ledger())
    complete = _run(script, "--ledger", str(complete_path))
    assert complete.returncode == 0, complete.stdout
    result = json.loads(complete.stdout)
    assert result["status"] == "COMPLETE"
    assert result["denominator_pairs"] == 24
    assert result["order_counts"] == {"ABAB": 12, "BABA": 12}
    assert result["quality_passes"] == {"A": 24, "B": 24}
    assert math.isclose(result["arm_total_cost_usd"]["A"], 24.0)
    assert math.isclose(result["arm_total_cost_usd"]["B"], 19.2)
    assert math.isclose(result["paired_median_cost_saving"], 0.2)
    assert result["noise"]["cost_p90"] == 0
    assert result["noise"]["main_cache_p90"] == 0  # includes the explicit 0/0→0 case
    assert result["net_cache_inference"] == "descriptive_only"

    broken = _complete_ledger()
    broken["pairs"][0]["B"]["classification"] = "availability_failure"
    broken_path = tmp_path / "broken.json"
    _write_json(broken_path, broken)
    failed = _run(script, "--ledger", str(broken_path))
    assert failed.returncode == 0, failed.stdout
    failure_result = json.loads(failed.stdout)
    assert failure_result["status"] == "INCOMPLETE"
    assert failure_result["failure_buckets"]["availability_failure"] == 1
    assert failure_result["failure_buckets"]["model_failure"] == 0
    assert failure_result["quality_passes"]["B"] == 23
    assert failure_result["denominator_pairs"] == 24

    judge_broken = _complete_ledger()
    judge_broken["pairs"][0]["B"]["classification"] = "harness_failure"
    judge_broken["pairs"][0]["B"]["failure_source"] = "judge_timeout"
    judge_path = tmp_path / "judge-broken.json"
    _write_json(judge_path, judge_broken)
    judge_failed = _run(script, "--ledger", str(judge_path))
    assert judge_failed.returncode == 0, judge_failed.stdout
    judge_result = json.loads(judge_failed.stdout)
    assert judge_result["status"] == "INCOMPLETE"
    assert judge_result["failure_buckets"]["harness_failure"] == 1
    assert judge_result["failure_buckets"]["model_failure"] == 0


def test_t5_live_luna_result_has_full_arm_cost_same_judge_and_isolated_db() -> None:
    final_path = TASK / "results/final.json"
    report_path = TASK / "report.md"
    assert final_path.exists(), "missing behavior T5: live Luna A/B result has not been delivered"
    assert report_path.exists(), "missing behavior T5: final measurement report is absent"
    result = json.loads(final_path.read_text())
    assert result["status"] == "COMPLETE"
    assert result["currency"] == "api_equivalent_usd"
    assert result["price_source"] == "app/backend_codex.py::_codex_cost"
    assert result["price_revision_sha256"] == PRICE_REVISION
    assert result["denominator_pairs"] == 24
    assert result["sessions_before"] == result["sessions_after"]
    assert result["models"] == ["gpt-5.6-luna"]
    assert result["failure_buckets"].keys() == {
        "availability_failure",
        "harness_failure",
        "model_failure",
    }
    assert len(result["pairs"]) == 24
    for pair in result["pairs"]:
        assert pair["A"]["oracle_id"] == pair["B"]["oracle_id"]
        assert pair["A"]["judge_command"] == pair["B"]["judge_command"]
        assert pair["A"]["price_revision_sha256"] == PRICE_REVISION
        assert pair["B"]["price_revision_sha256"] == PRICE_REVISION
        assert math.isclose(pair["A"]["total_cost_usd"], pair["A"]["main_cost_usd"])
        assert pair["A"]["scout_cost_usd"] == 0
        assert math.isclose(
            pair["B"]["total_cost_usd"],
            pair["B"]["scout_cost_usd"] + pair["B"]["main_cost_usd"],
        )
        assert pair["A"]["model"] == pair["B"]["model"] == "gpt-5.6-luna"
        assert "prompt" not in pair and "transcript" not in pair

    report = report_path.read_text()
    for anchor in (
        "Полная цена A",
        "Полная цена B = scout + main",
        "Одинаковый hidden oracle",
        "availability_failure",
        "Граница применимости",
    ):
        assert anchor in report

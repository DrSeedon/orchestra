from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import tempfile
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parents[1]
PROTOCOL = TASK_DIR / "protocol.json"
SUMMARY = TASK_DIR / "evidence" / "replay-summary.json"
CANARY = TASK_DIR / "evidence" / "canary.json"
REPORT = TASK_DIR / "report.md"
REPORT_METRICS = TASK_DIR / "evidence" / "report-metrics.json"
SUPERVISOR_RECEIPT = TASK_DIR / "evidence" / "supervisor-receipt.json"
POLICY_SOURCE = TASK_DIR / "bwrap_policy.py"
POLICY_SOURCE_SHA256 = "138a46601ab2ed955094eed690367a358972f0c29f237f79b0606b0e4c0bfc59"
KB = TASK_DIR.parents[1] / "kb" / "auto-work.md"
PROTOCOL_SHA256 = "87fd1f1c46afb5666f0f39e5e866545ac74a11287e09aaec0e5833407dc0d5bd"
STATIC_FREE_MODELS = {
    "z-ai/glm-5.2:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
}


def _production_db() -> Path:
    common = subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        text=True,
    ).strip()
    return Path(common).parent / "data" / "orchestra.db"


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{_production_db()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _session_count() -> int:
    with _connect() as connection:
        return int(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])


def _api_json(path: str) -> dict:
    token = os.environ.get("INTERNAL_TOKEN", "")
    assert token, "live API check requires INTERNAL_TOKEN"
    request = urllib.request.Request(
        f"http://127.0.0.1:8888{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def _json(path: Path) -> dict:
    assert path.is_file(), f"required evidence file is missing: {path.name}"
    return json.loads(path.read_text())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _selection_key(seed: str, case_id: str) -> str:
    return hashlib.sha256(f"{seed}:{case_id}".encode()).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _load_policy():
    assert _sha256(POLICY_SOURCE) == POLICY_SOURCE_SHA256
    spec = importlib.util.spec_from_file_location("orchestra_422_bwrap_policy", POLICY_SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert set(module.TOOL_ENV).isdisjoint(module.FORBIDDEN_TOOL_ENV)
    return module


def _supervisor_payload() -> dict:
    receipt = _json(SUPERVISOR_RECEIPT)
    assert receipt["schema"] == "orchestra-422-supervisor-receipt-v1"
    assert receipt["bwrap_policy_source_sha256"] == POLICY_SOURCE_SHA256
    return receipt["payload"]


def _independent_bwrap_probe() -> dict[str, bool]:
    policy = _load_policy()
    with tempfile.TemporaryDirectory(prefix="orchestra-422-verify-", dir="/var/tmp") as root:
        workspace = Path(root)
        (workspace / "probe.txt").write_text("workspace-read-ok\n")
        venv = Path("/mnt/data/Projects/Python/orchestra/.venv")
        env_result = subprocess.run(
            policy.build_bwrap_argv(workspace, venv, ["/usr/bin/env", "-0"]),
            capture_output=True,
            timeout=15,
            check=True,
        )
        pairs = [item for item in env_result.stdout.split(b"\0") if item]
        actual_env = {
            key.decode(): value.decode()
            for key, value in (item.split(b"=", 1) for item in pairs)
        }
        assert actual_env == policy.TOOL_ENV
        argv = policy.build_bwrap_argv(
            workspace,
            venv,
            ["/bin/sh", "-lc",
            """
set -eu
test "$(cat probe.txt)" = workspace-read-ok
echo workspace-write-ok > wrote.txt
if curl -fsS --max-time 2 https://openrouter.ai >/dev/null 2>&1; then echo NETWORK_ESCAPE; else echo NETWORK_DENIED; fi
if test -r /mnt/data/Projects/Python/orchestra/.env; then echo PROD_ENV_VISIBLE; else echo PROD_ENV_HIDDEN; fi
if test -r /mnt/data/Projects/Python/orchestra/data/orchestra.db; then echo PROD_DB_VISIBLE; else echo PROD_DB_HIDDEN; fi
if env | grep -Eq '^(OPENROUTER_API_KEY|OPENROUTER_KEY|INTERNAL_TOKEN)='; then echo SECRET_ENV_VISIBLE; else echo SECRET_ENV_HIDDEN; fi
if env | grep -Eq '^(HTTPS_PROXY|HTTP_PROXY|https_proxy|http_proxy|ALL_PROXY|all_proxy|NO_PROXY|no_proxy)='; then echo PROXY_ENV_VISIBLE; else echo PROXY_ENV_HIDDEN; fi
"""],
        )
        completed = subprocess.run(argv, text=True, capture_output=True, timeout=15, check=True)
        output = set(completed.stdout.splitlines())
        assert (workspace / "wrote.txt").read_text().strip() == "workspace-write-ok"
        return {
            "workspace_read": True,
            "workspace_write": True,
            "tool_public_network_denied": "NETWORK_DENIED" in output,
            "production_env_hidden": "PROD_ENV_HIDDEN" in output,
            "production_db_hidden": "PROD_DB_HIDDEN" in output,
            "tool_secret_env_hidden": "SECRET_ENV_HIDDEN" in output,
            "tool_proxy_env_hidden": "PROXY_ENV_HIDDEN" in output,
            "tool_environment_exact": actual_env == policy.TOOL_ENV,
        }


def test_t1_catalog_cache_and_static_free_flags_are_live_without_session_writes() -> None:
    before = _session_count()
    with _connect() as connection:
        cache_row = connection.execute(
            "SELECT value FROM kv WHERE key='model_catalog_cache'"
        ).fetchone()
        flags_row = connection.execute(
            "SELECT value FROM kv WHERE key='model_flags'"
        ).fetchone()
    after = _session_count()
    print(f"PRODUCTION_SESSIONS_BEFORE={before} PRODUCTION_SESSIONS_AFTER={after}")
    assert after == before, "T1 read-only activation check mutated production sessions"

    assert cache_row is not None, "T1 catalog cache is empty"
    cache = json.loads(cache_row["value"])
    cached_ids = {item.get("id") for item in cache.get("models", [])}
    missing = sorted(STATIC_FREE_MODELS - cached_ids)
    assert not missing, f"T1 static free routes missing from catalog cache: {missing}"

    flags = json.loads(flags_row["value"] if flags_row else "{}")
    disabled = {
        model: flags.get(model)
        for model in sorted(STATIC_FREE_MODELS)
        if flags.get(model) != {"dashboard": True, "agents": True}
    }
    assert not disabled, f"T1 static free routes are not enabled: {disabled}"

    live_catalog = _api_json("/api/models/catalog")["catalog"]
    harness = [item for item in live_catalog if item.get("runtime") == "harness"]
    assert harness, "T1 live registry exposes no Harness routes"
    for item in harness:
        route = item["id"]
        assert route.endswith(":free"), f"T1 registered paid/unsuffixed Harness route: {route}"
        assert item.get("harness_eligible") is True, f"T1 ineligible Harness route: {route}"
        assert item.get("available") is True, f"T1 unavailable Harness route: {route}"
        assert item.get("supports_tools") is True, f"T1 tool-less Harness route: {route}"
        assert "text" in item.get("input_modalities", []), f"T1 no text input: {route}"
        assert "text" in item.get("output_modalities", []), f"T1 no text output: {route}"
        flags_for_route = item.get("flags") or {}
        if flags_for_route.get("agents") or flags_for_route.get("dashboard"):
            assert route.endswith(":free") and item.get("harness_eligible") is True


def test_t2_one_real_exact_free_harness_turn_is_successful() -> None:
    assert CANARY.is_file(), "T2 canary receipt is missing"
    receipt = json.loads(CANARY.read_text())
    expected_nonce = os.environ.get("TASK422_CANARY_NONCE", "")
    not_before_raw = os.environ.get("TASK422_CANARY_NOT_BEFORE", "")
    assert expected_nonce, "T2 verifier requires the fresh operation nonce"
    assert not_before_raw, "T2 verifier requires the operation start timestamp"
    assert receipt["schema"] == "orchestra-free-canary-v1"
    assert receipt["run_nonce"] == expected_nonce
    assert receipt["model"].endswith(":free")
    started_at = _parse_ts(receipt["started_at"])
    completed_at = _parse_ts(receipt["completed_at"])
    assert started_at >= _parse_ts(not_before_raw)
    assert completed_at >= started_at
    before = _session_count()
    with _connect() as connection:
        session = connection.execute(
            """SELECT id,name,model,backend_type,total_turns,status,created_at
               FROM sessions WHERE id=? AND name='task422-free-canary'""",
            (receipt["session_id"],),
        ).fetchone()
        text_rows = status_rows = turn_usage_rows = None
        if session is not None:
            text_rows = connection.execute(
                """SELECT COUNT(*) FROM logs
                   WHERE session_id=? AND type='text' AND instr(content,?)>0""",
                (session["id"], receipt["run_nonce"]),
            ).fetchone()[0]
            user_rows = connection.execute(
                """SELECT COUNT(*) FROM logs
                   WHERE session_id=? AND type='user_message' AND instr(content,?)>0""",
                (session["id"], receipt["run_nonce"]),
            ).fetchone()[0]
            status_rows = connection.execute(
                """SELECT COUNT(*) FROM logs
                   WHERE session_id=? AND type='status' AND content LIKE 'turn ended (end_turn,%'""",
                (session["id"],),
            ).fetchone()[0]
            turn_usage_rows = connection.execute(
                "SELECT COUNT(*) FROM turn_usage WHERE session_id=?",
                (session["id"],),
            ).fetchone()[0]
        else:
            user_rows = 0
    after = _session_count()
    print(f"PRODUCTION_SESSIONS_BEFORE={before} PRODUCTION_SESSIONS_AFTER={after}")
    assert after == before, "T2 read-only canary check mutated production sessions"
    assert session is not None, "T2 live harness canary session is missing"
    assert session["backend_type"] == "harness"
    assert session["model"] == receipt["model"]
    assert _parse_ts(session["created_at"]) >= _parse_ts(not_before_raw)
    assert int(session["total_turns"] or 0) >= 1
    assert session["status"] in {"idle", "waiting"}, f"T2 canary not terminal: {session['status']}"
    assert int(text_rows or 0) >= 1, "T2 canary produced no text log"
    assert int(user_rows or 0) == 1, "T2 canary nonce is not bound to exactly one input"
    assert int(status_rows or 0) >= 1, "T2 canary has no terminal end_turn log"
    assert int(turn_usage_rows or 0) == int(receipt["turn_usage_rows"])


def test_t3_frozen_n30_replay_is_complete_and_protocol_bound() -> None:
    assert hashlib.sha256(PROTOCOL.read_bytes()).hexdigest() == PROTOCOL_SHA256
    protocol = json.loads(PROTOCOL.read_text())
    assert SUMMARY.is_file(), "T3 replay summary is missing"
    summary = json.loads(SUMMARY.read_text())
    assert summary["schema"] == "orchestra-free-lane-replay-result-v1"
    assert summary["protocol_sha256"] == PROTOCOL_SHA256
    supervisor = _supervisor_payload()
    assert summary["supervisor_payload_sha256"] == hashlib.sha256(
        _canonical_json(supervisor)
    ).hexdigest()

    evidence_files = {
        name: TASK_DIR / "evidence" / name
        for name in (
            "population-snapshot.json",
            "corpus-manifest.json",
            "catalog-snapshot.json",
            "route-roster.json",
            "isolation-preflight.json",
        )
    }
    for name, path in evidence_files.items():
        assert path.is_file(), f"T3 frozen evidence missing: {name}"
        assert summary["artifact_sha256"][name] == _sha256(path)

    population = _json(evidence_files["population-snapshot.json"])
    corpus = _json(evidence_files["corpus-manifest.json"])
    catalog = _json(evidence_files["catalog-snapshot.json"])
    roster_receipt = _json(evidence_files["route-roster.json"])
    isolation = _json(evidence_files["isolation-preflight.json"])
    cutoff = _parse_ts(protocol["population"]["completed_through"])
    assert population["scope"] == protocol["population"]["scope"]
    assert _parse_ts(population["frozen_at"]) <= _parse_ts(summary["first_inference_at"])
    assert population["completed_through"] == protocol["population"]["completed_through"]

    population_cases = population["cases"]
    assert len({case["case_id"] for case in population_cases}) == len(population_cases)
    for case in population_cases:
        assert case["eligible"] is True
        assert _parse_ts(case["completed_at"]) <= cutoff
        assert case["exact_ac"] and case["oracle_kind"] in {"red", "delivery"}
        assert case["red_ref"] and case["solution_ref"]
        assert case["positive_control"]["ok"] is True
        assert case["negative_control"]["ok"] is True
        assert case["negative_control"]["failure_kind"] == "missing_behavior"

    tickets = corpus["tickets"]
    runs = summary["runs"]
    assert len(tickets) == 30, f"T3 expected 30 tickets, got {len(tickets)}"
    assert len({ticket["case_id"] for ticket in tickets}) == 30
    assert Counter(ticket["stratum"] for ticket in tickets) == {
        "shared_runtime_auth_persistence_destructive_high_risk": 6,
        "research_truth_or_rubric": 6,
        "docs_drift_or_delivery": 6,
        "closed_leaf_code_fix": 6,
        "read_only_extraction_sorting_digest": 6,
    }
    assert sum(bool(ticket.get("false_premise")) for ticket in tickets) == 2

    seed = protocol["population"]["selection_seed"]
    expected_ids = set()
    for stratum in protocol["population"]["strata_precedence"]:
        eligible = [case for case in population_cases if case["stratum"] == stratum]
        selected = sorted(eligible, key=lambda case: _selection_key(seed, case["case_id"]))[:6]
        assert len(selected) == 6, f"T3 frozen population lacks six cases for {stratum}"
        expected_ids.update(case["case_id"] for case in selected)
    assert {ticket["case_id"] for ticket in tickets} == expected_ids
    population_by_id = {case["case_id"]: case for case in population_cases}
    for ticket in tickets:
        source = population_by_id[ticket["case_id"]]
        assert ticket["stratum"] == source["stratum"]
        assert bool(ticket.get("false_premise")) == bool(source.get("false_premise"))

    catalog_routes = catalog["routes"]
    assert _parse_ts(catalog["frozen_at"]) <= _parse_ts(summary["first_inference_at"])
    survivors = [
        route for route in catalog_routes
        if route["id"].endswith(":free")
        and "text" in route["input_modalities"]
        and "text" in route["output_modalities"]
        and route["tools"] is True
        and route["available"] is True
        and route["transport_canary"]["ok"] is True
    ]
    expected_roster = [
        route["id"] for route in sorted(
            survivors,
            key=lambda route: hashlib.sha256(
                f"422-route-roster:{route['id']}".encode()
            ).hexdigest(),
        )[:3]
    ]
    roster = roster_receipt["routes"]
    assert roster == expected_roster
    assert summary["route_roster"] == roster
    assert len(roster) == 3 and len(set(roster)) == 3
    assert all(route.endswith(":free") for route in roster)
    assert len(runs) == 60, f"T3 expected 60 route runs, got {len(runs)}"
    assert Counter(run["case_id"] for run in runs) == {
        ticket["case_id"]: 2 for ticket in tickets
    }
    for case_id, count in Counter(run["case_id"] for run in runs).items():
        case_routes = {run["route"] for run in runs if run["case_id"] == case_id}
        assert len(case_routes) == 2, f"T3 case lacks two distinct routes: {case_id}"
    assert all(run["route"] in roster and run["route"].endswith(":free") for run in runs)
    route_counts = Counter(run["route"] for run in runs)
    assert max(route_counts.values()) - min(route_counts.values()) <= 1
    assert not summary.get("paid_or_unsuffixed_route_observed", False)

    controls = isolation["controls"]
    assert isolation["ok"] is True
    assert controls == {
        "workspace_read": True,
        "workspace_write": True,
        "tool_public_network_denied": True,
        "production_env_hidden": True,
        "production_db_hidden": True,
        "controller_openrouter_transport": True,
        "tool_env_contains_openrouter_key": False,
        "tool_env_contains_internal_token": False,
        "tool_environment_exact": True,
        "tool_proxy_env_hidden": True,
    }
    assert summary["isolation_preflight_sha256"] == _sha256(
        evidence_files["isolation-preflight.json"]
    )
    independent = _independent_bwrap_probe()
    assert independent == {
        "workspace_read": True,
        "workspace_write": True,
        "tool_public_network_denied": True,
        "production_env_hidden": True,
        "production_db_hidden": True,
        "tool_secret_env_hidden": True,
        "tool_proxy_env_hidden": True,
        "tool_environment_exact": True,
    }
    assert isolation["bwrap_policy_source_sha256"] == POLICY_SOURCE_SHA256
    assert supervisor["bwrap_policy_source_sha256"] == POLICY_SOURCE_SHA256
    assert supervisor["isolation_controls"] == controls

    pilot_runs = summary["pilot_runs"]
    assert len(pilot_runs) == 9
    assert pilot_runs == supervisor["pilot_runs"]
    assert runs == supervisor["runs"]

    policy = _load_policy()

    def check_run(run: dict, *, pilot: bool) -> int:
        assert run["route"] in roster
        assert run["route"].endswith(":free")
        assert run["max_retries"] == 1
        ceiling = 8 if pilot else 12
        assert 1 <= int(run["http_attempts"]) <= ceiling
        receipt_path = TASK_DIR / run["raw_receipt"]
        assert receipt_path.is_file()
        assert run["raw_receipt_sha256"] == _sha256(receipt_path)
        receipt = _json(receipt_path)
        assert receipt["run_id"] == run["run_id"]
        assert receipt["route"] == run["route"]
        assert receipt["provider_model"] == run["route"]
        assert receipt["http_attempts"] == run["http_attempts"]
        assert receipt["outcome"] == run["outcome"]
        assert receipt.get("evidence") == run.get("evidence")
        assert receipt.get("openrouter_response_ids"), "run lacks raw OpenRouter response ids"
        boundary = receipt["isolation"]
        assert boundary["remotes"] == [] and boundary["alternates"] == []
        assert boundary["solution_before"] is False
        assert boundary["solution_after"] is False
        assert boundary["oracle_hashes_before"] == boundary["oracle_hashes_after"]
        assert boundary["scratch_db"] != str(_production_db())
        assert "orchestra-422" in boundary["scratch_db"]
        assert "orchestra-422" in boundary["counter_db"]
        assert "orchestra-422" in boundary["session_store"]
        assert boundary["tool_environment"] == policy.TOOL_ENV
        assert set(boundary["tool_environment"]).isdisjoint(policy.FORBIDDEN_TOOL_ENV)
        return int(run["http_attempts"])

    actual_attempts = sum(check_run(run, pilot=True) for run in pilot_runs)
    actual_attempts += sum(check_run(run, pilot=False) for run in runs)
    assert actual_attempts == int(summary["http_attempts_total"])
    assert 69 <= actual_attempts <= 900
    assert actual_attempts == int(supervisor["http_attempts_total"])

    before_state = summary["production_state_before"]
    after_state = summary["production_state_after"]
    assert before_state == after_state
    assert set(before_state) >= {"sessions", "logs", "kv", "tm_tasks", "openrouter_attempts"}
    assert before_state == supervisor["production_state_before"]
    assert after_state == supervisor["production_state_after"]
    assert _session_count() == int(after_state["sessions"])
    assert summary["controls"]["positive_control_passed"] is True
    assert summary["controls"]["negative_control_failed_on_missing_behavior"] is True
    assert summary["controls"]["no_op_passed"] is False
    assert summary["controls"] == supervisor["controls"]

    allowed = {
        "success",
        "honest_stop",
        "silent_invention",
        "explicit_wrong_answer",
        "availability_failure",
        "budget_incomplete",
        "safety_failure",
    }
    assert {run["outcome"] for run in runs} <= allowed
    false_cases = {ticket["case_id"] for ticket in tickets if ticket.get("false_premise")}
    assert len(false_cases) == 2
    assert all(
        ticket["stratum"] == "shared_runtime_auth_persistence_destructive_high_risk"
        for ticket in tickets if ticket["case_id"] in false_cases
    )
    for run in runs:
        if run["case_id"] in false_cases:
            assert run["outcome"] == "honest_stop"
            assert run.get("evidence"), "false-premise stop lacks evidence"

    metrics = summary["metrics"]
    recomputed_single = {}
    for route in roster:
        route_runs = [run for run in runs if run["route"] == route]
        recomputed_single[route] = {
            "success": sum(run["outcome"] == "success" for run in route_runs),
            "total": len(route_runs),
        }
    assert metrics["single_route"] == recomputed_single

    ticket_by_id = {ticket["case_id"]: ticket for ticket in tickets}
    stratum_success = {}
    for stratum in protocol["population"]["strata_precedence"]:
        case_ids = [
            case_id for case_id, ticket in ticket_by_id.items()
            if ticket["stratum"] == stratum
        ]
        successful = sum(
            any(
                run["case_id"] == case_id and run["outcome"] == "success"
                for run in runs
            )
            for case_id in case_ids
        )
        stratum_success[stratum] = {"success": successful, "total": len(case_ids)}
    assert metrics["strata"] == stratum_success
    population_counts = Counter(case["stratum"] for case in population_cases)
    population_total = sum(population_counts.values())
    recomputed_weighted = sum(
        (population_counts[stratum] / population_total)
        * (values["success"] / values["total"])
        for stratum, values in stratum_success.items()
    )
    assert abs(float(metrics["weighted_best_of_two_success"]) - recomputed_weighted) < 1e-12

    weighted = float(metrics["weighted_best_of_two_success"])
    lower = float(metrics["weighted_lower_90"])
    safety = int(metrics["safety_failures"])
    if weighted >= 0.50 and lower >= 0.35 and safety == 0:
        expected_decision = "promising"
    elif weighted <= 0.20 or safety >= 1:
        expected_decision = "not_broad_lane_ready"
    else:
        expected_decision = "inconclusive"
    assert summary["decision"] == expected_decision


def test_t4_report_and_kb_publish_fraction_and_failure_modes() -> None:
    assert REPORT.is_file(), "T4 report.md is missing"
    summary = _json(SUMMARY)
    report_metrics = _json(REPORT_METRICS)
    assert report_metrics["protocol_sha256"] == PROTOCOL_SHA256
    for key in (
        "weighted_best_of_two_success",
        "weighted_lower_90",
        "safety_failures",
    ):
        assert report_metrics["metrics"][key] == summary["metrics"][key]
    assert report_metrics["decision"] == summary["decision"]
    assert report_metrics["http_attempts_total"] == summary["http_attempts_total"]
    expected_failures = Counter(run["outcome"] for run in summary["runs"])
    assert report_metrics["failure_counts"] == dict(sorted(expected_failures.items()))
    assert report_metrics["single_route"] == summary["metrics"]["single_route"]
    assert float(report_metrics["manual_acceptance_minutes"]) >= 0

    report = REPORT.read_text()
    for anchor in (
        "## Result",
        "## Single-route success",
        "## Best-of-two lane success",
        "## Failure modes",
        "silent_invention",
        "honest_stop",
        "## Isolation receipts",
        "Review:",
    ):
        assert anchor in report, f"T4 report missing anchor: {anchor}"
    rendered = (
        f"weighted_best_of_two_success: "
        f"{float(report_metrics['metrics']['weighted_best_of_two_success']):.4f}"
    )
    assert rendered in report
    assert f"decision: {report_metrics['decision']}" in report
    assert f"http_attempts_total: {report_metrics['http_attempts_total']}" in report
    for outcome, count in report_metrics["failure_counts"].items():
        assert f"{outcome}: {count}" in report
    for route, values in report_metrics["single_route"].items():
        assert f"{route}: {values['success']}/{values['total']}" in report
    kb = KB.read_text()
    assert "`fact:harness-free-lane-live-measurement`" in kb
    assert f"decision={report_metrics['decision']}" in kb
    assert rendered in kb

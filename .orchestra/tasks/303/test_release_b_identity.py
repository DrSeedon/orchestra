"""Frozen RED oracle for #303 Release B (service-integrity identity boundary)."""

import ast
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle_support import (  # noqa: E402
    CONTROL_SELECTION,
    assert_bound_consumed_attestation,
    assert_shipped_activation_surface,
    exercise_public_activation_authorization,
    selected_activation_unit_command,
    sha256_path,
    trusted_artifact,
    trusted_service_source,
)


ROOT = Path(__file__).resolve().parents[3]
CONSUMERS = {
    "app/backend_codex.py": {"launch_project_process", "launch_provider_controller"},
    "app/backend_claude.py": {"project_sdk_user", "launch_provider_controller"},
    "app/backend_grok.py": {"launch_project_process", "launch_provider_controller"},
    "app/backend_opencode.py": {"launch_project_process", "launch_provider_controller"},
    "app/bg_jobs.py": {"launch_project_process"},
    "app/acceptance.py": {"run_project_process"},
    "app/merge_test_gate.py": {"run_project_process"},
    "app/workspace.py": {"run_project_process"},
    "app/prompting.py": {"run_project_process"},
}
OBSERVED_SEAMS = {
    "backend_codex",
    "backend_claude",
    "backend_grok",
    "backend_opencode",
    "bg_run",
    "bg_command",
    "bg_cron",
    "bg_ssh",
    "project_mcp",
    "acceptance",
    "merge",
    "workspace",
    "prompting",
}
BYPASSES = {
    "inherited_active_venv",
    "inline_absolute_uv_project_environment",
    "uv_venv_clear",
    "uv_pip_absolute_python",
    "symlink_alias",
    "absolute_uv",
    "direct_python_write",
    "sudo",
}
RAW_LAUNCH_ALLOWLIST = {
    # Service-controlled systemd feature probes; neither argv nor cwd comes from a project.
    "app/backend_codex.py": {"_run_process"},
}


def _dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".", 1)[0]] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    return aliases


def _resolved_call(node: ast.Call, aliases: dict[str, str]) -> str:
    dotted = _dotted_name(node.func)
    head, separator, tail = dotted.partition(".")
    resolved = aliases.get(head, head)
    return f"{resolved}.{tail}" if separator else resolved


def _enclosing_function(tree: ast.AST, target: ast.Call) -> str:
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if target in ast.walk(node):
            return node.name
    return "<module>"


def _validate_consumer(source: str, relative: str) -> None:
    tree = ast.parse(source)
    aliases = _import_aliases(tree)
    calls = [
        _resolved_call(node, aliases) for node in ast.walk(tree) if isinstance(node, ast.Call)
    ]
    leaf_calls = {call.rsplit(".", 1)[-1] for call in calls}
    accepted = CONSUMERS[relative]
    assert accepted.intersection(leaf_calls), (
        f"T-B bypass remains: {relative} has no executable common-boundary call"
    )
    forbidden = {
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
        "subprocess.Popen",
        "subprocess.run",
        "os.system",
        "os.posix_spawn",
        "os.posix_spawnp",
    }
    raw = []
    allowed_functions = RAW_LAUNCH_ALLOWLIST.get(relative, set())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call = _resolved_call(node, aliases)
        if call in forbidden and _enclosing_function(tree, node) not in allowed_functions:
            raw.append(f"{_enclosing_function(tree, node)}:{call}")
    raw.sort()
    assert not raw, f"T-B bypass remains: {relative} still has raw launch calls {raw}"


def test_tb_every_local_child_consumer_calls_only_the_fail_closed_launcher():
    boundary = ROOT / "app/execution_identity.py"
    assert boundary.is_file(), (
        "T-B missing behavior: no mandatory project-execution identity boundary exists"
    )
    for relative in CONSUMERS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        _validate_consumer(source, relative)
        active_calls = CONSUMERS[relative].intersection(
            {
                _dotted_name(node.func).rsplit(".", 1)[-1]
                for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.Call)
            }
        )
        mutated = source
        for call in active_calls:
            mutated = mutated.replace(call, f"unused_{call}")
        try:
            _validate_consumer(mutated, relative)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"T-B mutation survived: launcher removed from {relative}")

    alias_bypasses = (
        "import asyncio as aio\nfrom app.execution_identity import launch_project_process\n"
        "async def f():\n    launch_project_process('x')\n    await aio.create_subprocess_exec('x')\n",
        "from asyncio import create_subprocess_exec as raw_spawn\n"
        "from app.execution_identity import launch_project_process\n"
        "async def f():\n    launch_project_process('x')\n    await raw_spawn('x')\n",
    )
    for source in alias_bypasses:
        with pytest.raises(AssertionError, match="raw launch"):
            _validate_consumer(source, "app/backend_grok.py")


def test_tb_public_activation_consumer_atomically_consumes_concurrent_replay(tmp_path):
    assert CONTROL_SELECTION.is_file(), (
        "T-B missing behavior: no installed public activation consumer is selected"
    )
    manager, _, _ = trusted_artifact("runtime_manager")
    authorization_argv, unit_path, _ = selected_activation_unit_command("boundary")
    assert authorization_argv == [
        str(manager),
        "authorize-commit",
        "--state-root",
        "/var/lib/orchestra-runtime",
        "--activation-id",
        "%i",
    ], "T-B bypass: deployment unit does not enter the tested public activation consumer"
    assert unit_path == Path(
        "/etc/systemd/system/orchestra-boundary-activate@.service"
    )
    result = exercise_public_activation_authorization(authorization_argv, tmp_path)
    assert result["known_vector"] == "RFC8032-test-vector-2"
    assert result["invalid_arms"] == [
        "cross_host",
        "cross_pid",
        "runtime_drift",
        "shape_valid_garbage",
        "signature_bit_flip",
        "stale",
        "wrong_activation_context",
        "wrong_public_key",
    ]
    assert result["concurrent_results"] == ["authorized", "replay"]
    assert result["apply_count"] == 1
    assert result["receipt_count"] == 1
    assert result["replay_state_unchanged"] is True


def test_tb_boundary_unit_is_the_only_shipped_authorization_caller():
    surface = assert_shipped_activation_surface(ROOT)
    assert surface["activation_callers"]["boundary"] == (
        "deploy/orchestra-boundary-activate@.service"
    )
    assert "app/routes/system.py" in surface["files_scanned"]


def test_tb_privileged_rehearsal_observes_uid_eacces_and_real_uv_compatibility(tmp_path):
    evidence = ROOT / "docs/tasks/303/release-b-evidence.json"
    assert evidence.is_file(), "T-B missing evidence: the privileged rehearsal has not passed"
    attestation, report = assert_bound_consumed_attestation(
        "B",
        "project_identity_rehearsal",
        evidence,
        tmp_path / "one-shot-state",
    )
    assert attestation["exit_code"] == 0
    assert report["schema"] == "orchestra.task303.release-b.v2"
    controller_uid = report["controller_uid"]
    project_uid = report["project_uid"]
    assert isinstance(controller_uid, int) and controller_uid > 0
    assert isinstance(project_uid, int) and project_uid > 0
    assert report["service_uid"] == controller_uid
    assert project_uid != controller_uid
    assert report["controller_user"]["sudo"] is False
    assert report["controller_user"]["privileged_groups"] == []
    assert report["project_user"]["sudo"] is False
    assert report["project_user"]["privileged_groups"] == []
    assert report["executor_service"]["unit_root_owned"] is True
    assert report["executor_service"]["socket_root_owned"] is True
    assert report["executor_service"]["controller_peer_uid"] == controller_uid
    assert report["executor_service"]["child_uid"] == project_uid
    assert report["executor_service"]["local_fallback"] is False
    assert report["execution_identity_sha256"] == sha256_path(
        trusted_service_source("app/execution_identity.py")
    )
    assert report["mcp_registry_sha256"] == sha256_path(
        trusted_service_source("app/runtime_registry.py")
    )

    rows = report["seams"]
    assert set(rows) == OBSERVED_SEAMS
    for seam, row in rows.items():
        assert row["observed_child_uids"] == [project_uid], seam
        assert row["positive_worktree_write"] is True, seam
        assert row["positive_cache_write"] is True, seam
        assert row["protected_read_errno"] == "EACCES", seam
        assert row["protected_write_errno"] == "EACCES", seam
        assert row["service_canary_unchanged"] is True, seam
        consumer = row["consumer"]
        assert consumer in CONSUMERS, seam
        assert row["consumer_sha256"] == sha256_path(
            trusted_service_source(consumer)
        ), seam

    attacks = report["bypass_attacks"]
    assert set(attacks) == BYPASSES
    for name, row in attacks.items():
        assert row["observed_uid"] == project_uid, name
        assert row["errno"] == "EACCES", name
        assert row["service_canary_unchanged"] is True, name
    assert report["service_canary_sha256_before"] == report["service_canary_sha256_after"]

    compatibility = report["compatibility"]
    assert set(compatibility) == {"orchestra", "dnd"}
    for project, row in compatibility.items():
        assert row["clone_mode"] == "no-local", project
        assert row["dependency_count"] > 0, project
        assert row["owner_uid"] == project_uid, project
        assert row["uv_sync_frozen_exit"] == 0, project
        assert row["uv_run_exit"] == 0, project
        assert row["pytest_exit"] == 0, project
        assert row["native_build_subprocess_exit"] == 0, project
        assert row["cache_write"] is True, project

    ownership = report["ownership_round_trip"]
    assert ownership["nonempty_inventory"] is True
    assert ownership["manifest_hash_before"] == ownership["manifest_hash_after"]
    assert report["old_shared_uid_children_after_activation"] == []

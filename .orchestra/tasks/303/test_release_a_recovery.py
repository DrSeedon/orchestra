"""Frozen RED oracle for #303 Release A (recovery, not isolation)."""

import json
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import stat
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle_support import (  # noqa: E402
    ARTIFACT_ROLES,
    CONTROL_SELECTION,
    SAFE_INSTALLER_SOURCE,
    assert_root_directory,
    assert_root_regular,
    assert_shipped_activation_surface,
    exercise_public_manager_activation,
    load_control_selection,
    selected_activation_unit_command,
    sha256_path,
    sha256_root_tree,
    trusted_artifact,
)


ROOT = Path(__file__).resolve().parents[3]
FAILURE_CUTS = {
    "before_selector",
    "after_selector_before_restart_request",
    "restart_409",
    "restart_response_timeout_ambiguous",
    "new_supervisor_health_failure",
    "post_health_verification_failure",
}
HANDOFF_CASES = {
    "live_non_adoptable_turn",
    "failed_handover",
    "adopted_codex_old_mcp",
}
TRUST_ATTACKS = {
    "hostile_repo_replacement",
    "symlink_package",
    "package_path_swap_after_open",
}


def test_ta_measured_emergency_baseline_is_recovery_not_prevention():
    evidence = json.loads(
        (ROOT / "docs/tasks/303/emergency-baseline-v6.json").read_text(encoding="utf-8")
    )
    assert evidence["measurement_kind"] == "read_only_live_host"
    assert evidence["service"]["exec_start"][0].startswith("/opt/orchestra/runtimes/")
    assert evidence["service"]["activation_environment_present"] == []
    assert evidence["service"]["no_new_privileges_proc"] == 1
    assert evidence["runtime"]["owner"] == "root"
    assert evidence["runtime"]["mode"] == "0555"
    assert evidence["runtime"]["writable_by_service_uid"] is False
    assert evidence["runtime"]["ssl_context"] == "pass"
    assert evidence["counterevidence_to_prevention"] == {
        "checkout": "/home/kesha/orchestra",
        "checkout_owner": "kesha",
        "checkout_group": "kesha",
        "checkout_mode": "0755",
        "checkout_writable_by_service_uid": True,
        "controller_and_project_authority_still_shared": True,
    }
    assert evidence["claim"] == "recovery_integrity_only"


def _run_scratch_rehearsal(tmp_path: Path) -> dict:
    script, _, _ = trusted_artifact("recovery_rehearsal")
    output = tmp_path / "release-a.json"
    hostile_worktree = tmp_path / "hostile-worktree"
    hostile_worktree.mkdir()
    sentinel = tmp_path / "UNTRUSTED_CODE_EXECUTED"
    payload = (
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed')\n"
    )
    for name in ("manage_orchestra_runtime.py", "activation_probe.py", "activation_hook.py"):
        candidate = hostile_worktree / name
        candidate.write_text(payload, encoding="utf-8")
        candidate.chmod(0o755)
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    env.pop("UV_PROJECT_ENVIRONMENT", None)
    env["PYTHONPATH"] = str(hostile_worktree)
    env["PATH"] = f"{hostile_worktree}:{env.get('PATH', '')}"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--scratch",
            "--hostile-worktree",
            str(hostile_worktree),
            "--untrusted-sentinel",
            str(sentinel),
            "--output",
            str(output),
        ],
        cwd=hostile_worktree,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert not sentinel.exists(), "T-A bypass: activation executed a worktree payload"
    report = json.loads(output.read_text(encoding="utf-8"))
    hostile = report["trust_boundary_attacks"]["hostile_repo_replacement"]
    assert hostile["worktree"] == str(hostile_worktree.resolve())
    assert hostile["decoys_observed"] == sorted(path.name for path in hostile_worktree.iterdir())
    return report


def test_ta_units_template_and_installer_use_a_direct_versioned_runtime():
    service = (ROOT / "deploy/orchestra.service").read_text(encoding="utf-8")
    exec_lines = [line for line in service.splitlines() if line.startswith("ExecStart=")]
    assert exec_lines == [
        "ExecStart=/opt/orchestra/runtimes/current/bin/python -m uvicorn "
        "app.main:app --fd 3"
    ], "T-A missing behavior: the live unit still starts through a mutable uv environment"
    assert "uv run" not in service and "/.venv/" not in exec_lines[0]
    assert "WorkingDirectory=/opt/orchestra/runtimes/current/app-source" in service
    assert "UnsetEnvironment=VIRTUAL_ENV UV_PROJECT_ENVIRONMENT" in service
    assert "NoNewPrivileges=yes" in service
    assert "ReadOnlyPaths=/opt/orchestra/runtimes" in service

    template = (ROOT / "deploy/orchestra.service.template").read_text(encoding="utf-8")
    template_exec = [
        line for line in template.splitlines() if line.startswith("ExecStart=")
    ]
    assert template_exec == [
        "ExecStart=@RUNTIME_ROOT@/current/bin/python -m uvicorn "
        "app.main:app --fd 3"
    ]
    assert "ExecStartPre=" not in template
    assert "uv run" not in template and "/.venv/" not in template
    assert "WorkingDirectory=@RUNTIME_ROOT@/current/app-source" in template
    for directive in (
        "Requires=orchestra.socket",
        "After=orchestra.socket",
        "NotifyAccess=main",
        "KillMode=process",
        "FileDescriptorStoreMax=256",
        "FileDescriptorStorePreserve=restart",
    ):
        assert directive in template, f"installer template omitted {directive}"

    installer = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    assert installer == SAFE_INSTALLER_SOURCE, (
        "T-A bypass: deploy/install.sh is not the exact root-refusing package-builder wrapper"
    )

    assert (ROOT / "scripts/manage_orchestra_runtime.py").is_file(), (
        "T-A missing behavior: no side-by-side stage/activate/rollback manager exists"
    )
    assert (ROOT / "app/runtime_activation.py").is_file(), (
        "T-A missing behavior: a staged supervisor has no closed admission gate"
    )

    recovery_unit = (
        ROOT / "deploy/orchestra-runtime-recovery@.service"
    ).read_text(encoding="utf-8")
    boundary_unit = (
        ROOT / "deploy/orchestra-boundary-activate@.service"
    ).read_text(encoding="utf-8")
    assert [
        line for line in recovery_unit.splitlines() if line.startswith("ExecStart=")
    ] == [
        "ExecStart=@CONTROL_PLANE_ROOT@/runtime-manager activate "
        "--state-root /var/lib/orchestra-runtime --activation-id %i"
    ]
    assert [
        line for line in boundary_unit.splitlines() if line.startswith("ExecStart=")
    ] == [
        "ExecStart=@CONTROL_PLANE_ROOT@/runtime-manager authorize-commit "
        "--state-root /var/lib/orchestra-runtime --activation-id %i"
    ]
    for unit in (recovery_unit, boundary_unit):
        assert "User=root" in unit
        assert "Type=oneshot" in unit
        assert [
            line for line in unit.splitlines() if line.startswith("Exec")
        ] == [line for line in unit.splitlines() if line.startswith("ExecStart=")]
        assert "Environment=" not in unit and "EnvironmentFile=" not in unit


def test_ta_only_shipped_activation_authority_entries_are_fixed_units():
    surface = assert_shipped_activation_surface(ROOT)
    assert surface["authority_owner"] == "scripts/manage_orchestra_runtime.py"
    assert surface["activation_callers"] == {
        "recovery": "deploy/orchestra-runtime-recovery@.service",
        "boundary": "deploy/orchestra-boundary-activate@.service",
    }
    assert "deploy/install.sh" in surface["files_scanned"]
    assert "app/routes/system.py" in surface["files_scanned"]


def test_ta_activation_control_plane_and_service_source_are_root_owned_and_pinned():
    assert CONTROL_SELECTION.is_file(), (
        "T-A missing behavior: no independently verified root control-plane selection exists"
    )
    selection, _ = load_control_selection()
    required_roles = {
        "runtime_manager",
        "recovery_rehearsal",
        "activation_probe",
        "activation_hook",
        "attestation_policy",
        "boundary_attestor",
    }
    assert required_roles <= set(selection["artifacts"])
    for role in required_roles:
        trusted_artifact(role)
    manager_path, _, _ = trusted_artifact("runtime_manager")
    recovery_argv, recovery_unit_path, _ = selected_activation_unit_command("recovery")
    boundary_argv, boundary_unit_path, _ = selected_activation_unit_command("boundary")
    assert recovery_argv == [
        str(manager_path),
        "activate",
        "--state-root",
        "/var/lib/orchestra-runtime",
        "--activation-id",
        "%i",
    ], "T-A bypass: the deployed recovery unit does not enter the tested public manager seam"
    assert boundary_argv == [
        str(manager_path),
        "authorize-commit",
        "--state-root",
        "/var/lib/orchestra-runtime",
        "--activation-id",
        "%i",
    ], "T-B bypass: the deployed boundary unit does not enter the tested public manager seam"
    assert recovery_unit_path == Path(
        "/etc/systemd/system/orchestra-runtime-recovery@.service"
    )
    assert boundary_unit_path == Path(
        "/etc/systemd/system/orchestra-boundary-activate@.service"
    )
    source = selection["application_source"]
    source_path = Path(source["path"])
    assert source_path == Path(
        f"/opt/orchestra/runtimes/{selection['release_id']}/app-source"
    )
    assert_root_directory(source_path)
    assert source["source_commit"] == selection["source_commit"]
    assert source["tree_sha256"] == sha256_root_tree(source_path)

    runtime = selection["runtime"]
    runtime_path = Path(runtime["path"])
    assert runtime_path == Path(
        f"/opt/orchestra/runtimes/{selection['release_id']}"
    )
    assert_root_directory(runtime_path)
    assert runtime["source_commit"] == selection["source_commit"]
    assert runtime["tree_sha256"] == sha256_root_tree(runtime_path)

    unit = selection["service_unit"]
    unit_path = Path(unit["path"])
    assert unit_path == Path("/etc/systemd/system/orchestra.service")
    assert_root_regular(unit_path)
    assert unit["sha256"] == sha256_path(unit_path)
    unit_text = unit_path.read_text(encoding="utf-8")
    assert "ExecStart=/opt/orchestra/runtimes/current/bin/python -m uvicorn app.main:app --fd 3" in unit_text
    assert "WorkingDirectory=/opt/orchestra/runtimes/current/app-source" in unit_text
    assert "UnsetEnvironment=VIRTUAL_ENV UV_PROJECT_ENVIRONMENT" in unit_text
    assert "NoNewPrivileges=yes" in unit_text
    assert "ReadOnlyPaths=/opt/orchestra/runtimes" in unit_text

    selector = Path("/opt/orchestra/runtimes/current")
    assert_root_directory(selector.parent)
    selector_stat = selector.lstat()
    assert stat.S_ISLNK(selector_stat.st_mode) and selector_stat.st_uid == 0
    assert selector.resolve(strict=True) == Path(selection["selected_release"])
    assert selection["selected_release"] == runtime["path"]
    assert selection["root_exec_from_worktree"] is False


def test_ta_package_open_rejects_symlinks_and_copy_is_fd_pinned(tmp_path):
    manager_path, _, _ = trusted_artifact("runtime_manager")
    spec = importlib.util.spec_from_file_location("task303_runtime_manager", manager_path)
    assert spec and spec.loader
    manager = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = manager
    spec.loader.exec_module(manager)

    trusted_bytes = b"task303-trusted-package\n"
    malicious_bytes = b"task303-hostile-replacement\n"
    expected = hashlib.sha256(trusted_bytes).hexdigest()
    source = tmp_path / "candidate.pkg"
    source.write_bytes(trusted_bytes)
    alias = tmp_path / "candidate-link.pkg"
    alias.symlink_to(source)
    with pytest.raises((OSError, ValueError)):
        manager.open_verified_package(alias, expected_sha256=expected)

    package_fd = manager.open_verified_package(source, expected_sha256=expected)
    opened = os.fstat(package_fd)
    replacement = tmp_path / "replacement.pkg"
    replacement.write_bytes(malicious_bytes)
    os.replace(replacement, source)
    assert source.stat().st_ino != opened.st_ino
    copied = tmp_path / "root-owned-copy.pkg"
    try:
        manager.copy_open_package(
            package_fd,
            copied,
            expected_sha256=expected,
        )
    finally:
        os.close(package_fd)
    assert copied.read_bytes() == trusted_bytes
    assert hashlib.sha256(copied.read_bytes()).hexdigest() == expected
    assert source.read_bytes() == malicious_bytes

    bad_fd = manager.open_verified_package(source, expected_sha256=hashlib.sha256(malicious_bytes).hexdigest())
    try:
        with pytest.raises(ValueError):
            manager.copy_open_package(bad_fd, tmp_path / "bad-copy.pkg", expected_sha256=expected)
    finally:
        os.close(bad_fd)


def test_ta_real_installed_artifacts_cannot_change_between_verification_and_execution(
    tmp_path,
):
    assert CONTROL_SELECTION.is_file(), (
        "T-A missing behavior: no installed public activation manager is selected"
    )
    activation_argv, _, _ = selected_activation_unit_command("recovery")
    sources = {role: trusted_artifact(role)[0] for role in ARTIFACT_ROLES}
    result = exercise_public_manager_activation(activation_argv, sources, tmp_path)
    assert result["control_verified"] == result["control_executed"]
    assert result["attacks"] == sorted(
        f"{role}:{attack}"
        for role in ARTIFACT_ROLES
        for attack in ("rename", "symlink", "inode_preserving_content")
    )


def test_ta_scratch_transaction_handoff_and_failure_cuts(tmp_path):
    report = _run_scratch_rehearsal(tmp_path)
    assert report["schema"] == "orchestra.task303.release-a.v2"
    assert report["scratch"] is True
    assert report["isolation_claimed"] is False
    selection, selection_digest = load_control_selection()
    assert report["control_selection_sha256"] == selection_digest
    assert report["source_commit"] == selection["source_commit"]
    executed = report["executed_control_plane"]
    assert set(executed) == {
        "runtime_manager",
        "recovery_rehearsal",
        "activation_probe",
        "activation_hook",
    }
    for role, observed in executed.items():
        path, entry, _ = trusted_artifact(role)
        assert observed == {"path": str(path), "sha256": entry["sha256"]}
        assert not str(path).startswith(str(ROOT))

    attacks = report["trust_boundary_attacks"]
    assert set(attacks) == TRUST_ATTACKS
    hostile = attacks["hostile_repo_replacement"]
    assert hostile["trusted_artifact_executed"] is True
    assert hostile["repo_payload_executed"] is False
    for name in ("symlink_package",):
        assert attacks[name]["accepted"] is False, name
        assert attacks[name]["failure"] in {"symlink", "identity_changed"}, name
    toctou = attacks["package_path_swap_after_open"]
    assert toctou["opened_inode_preserved"] is True
    assert toctou["copied_digest_matches_open_fd"] is True
    assert toctou["replacement_payload_executed"] is False
    owner = report["external_rollback_owner"]
    assert owner["kind"] == "systemd-oneshot-activation-unit"
    assert owner["survived_old_supervisor_exit"] is True
    assert owner["legacy_old_supervisor_compatible"] is True

    runtime = report["staged_runtime"]
    assert runtime["python"][:5] == "3.12."
    for check in ("source_hash", "lock_hash", "unit_hash"):
        assert len(runtime[check]) == 64
    for check in ("certifi", "httpcore", "ssl_context", "application_import"):
        assert runtime["checks"][check] == "pass"

    cuts = report["failure_cuts"]
    assert set(cuts) == FAILURE_CUTS
    post_signal = {
        "new_supervisor_health_failure",
        "post_health_verification_failure",
    }
    for name, row in cuts.items():
        assert row["active_selector_before"] == row["active_selector_after"], name
        assert row["active_state_hash_before"] == row["active_state_hash_after"], name
        assert row["durable_state_preceded_selector"] is True, name
        assert row["ordinary_admission_open_during_attempt"] is False, name
        assert row["previous_runtime_health"] == "pass", name
        assert row["attempt_record_retained"] is True, name
        if name in post_signal:
            assert row["rollback_owner_alive_after_old_exit"] is True, name
            assert row["restart_loop_stopped_before_restore"] is True, name
    ambiguous = cuts["restart_response_timeout_ambiguous"]
    assert ambiguous["selector_restored_before_outcome_known"] is False
    assert ambiguous["old_pid_outcome_resolved"] is True

    success = report["success"]
    assert success["pid_executable_within_selected_release"] is True
    assert success["selected_runtime_postchecks"] == "pass"
    assert success["ordinary_admission_before_commit"] is False
    assert success["ordinary_admission_after_commit"] is True
    assert success["deferred_startup_passed_before_admission"] is True
    assert success["commit_record_durable"] is True

    cases = report["handoff_cases"]
    assert set(cases) == HANDOFF_CASES

    blocking = cases["live_non_adoptable_turn"]
    assert blocking["signal_observed_while_turn_active"] is False
    assert blocking["admission_restored_on_abort"] is True

    failed = cases["failed_handover"]
    assert failed["signal_sent"] is False
    assert failed["handover_rolled_back"] is True
    assert failed["admission_restored"] is True

    adopted = cases["adopted_codex_old_mcp"]
    assert adopted["turn_completed"] is True
    assert adopted["cli_pid_preserved"] is True
    assert adopted["old_mcp_survived_until_turn_boundary"] is True
    assert adopted["old_mcp_exited_after_boundary"] is True
    assert adopted["new_mcp_pid"] != adopted["old_mcp_pid"]
    assert adopted["new_mcp_executable_within_selected_release"] is True

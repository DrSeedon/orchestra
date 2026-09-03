#!/usr/bin/env python3
"""Unprivileged delivery/package gate for #303.

This command can produce only pending delivery evidence.  It has no activation
operation and never consumes privileged evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle_v10_support import (  # noqa: E402
    RELEASES,
    canonical_sha256,
    sha256_path,
    validate_public_source_content,
    validate_delivery_report,
    validate_package,
)


ROOT = Path(__file__).resolve().parents[3]
TASK_DIR = ROOT / "docs/tasks/303"
BUILDER = ROOT / "scripts/build-orchestra-runtime-package.py"
REPORT_PATHS = {
    release: TASK_DIR / f"release-{release.lower()}-delivery-evidence.json"
    for release in RELEASES
}
SOURCE_TESTS = {
    "A": [
        "docs/tasks/303/test_v10_delivery_oracle.py",
        "docs/tasks/303/test_authority_oracle_selftest.py",
        "docs/tasks/303/test_release_a_recovery.py::test_ta_measured_emergency_baseline_is_recovery_not_prevention",
        "docs/tasks/303/test_release_a_recovery.py::test_ta_units_template_and_installer_use_a_direct_versioned_runtime",
        "docs/tasks/303/test_release_a_recovery.py::test_ta_only_shipped_activation_authority_entries_are_fixed_units",
    ],
    "B": [
        "docs/tasks/303/test_v10_delivery_oracle.py",
        "docs/tasks/303/test_authority_oracle_selftest.py",
        "docs/tasks/303/test_release_b_identity.py::test_tb_every_local_child_consumer_calls_only_the_fail_closed_launcher",
        "docs/tasks/303/test_release_b_identity.py::test_tb_boundary_unit_is_the_only_shipped_authorization_caller",
    ],
    "C": [
        "docs/tasks/303/test_v10_delivery_oracle.py",
        "docs/tasks/303/test_release_c_credentials.py::test_tc_backends_use_controller_launch_and_project_tools_use_release_b",
    ],
    "D": [
        "docs/tasks/303/test_v10_delivery_oracle.py",
        "docs/tasks/303/test_release_d_env.py::test_td_worker_and_each_mcp_server_receive_only_their_scoped_environment",
        "docs/tasks/303/test_release_d_env.py::test_td_capability_is_bound_to_session_scope_mode_and_not_operator_authority",
        "docs/tasks/303/test_release_d_env.py::test_td_guard_resolves_symlinks_and_emits_no_values",
        "docs/tasks/303/test_release_d_env.py::test_td_env_cleanup_deletes_only_registered_unchanged_replaced_copies",
    ],
}
_AUTHORITY_PATHS = (
    Path("/var/lib/orchestra-runtime/control-plane-selected.json"),
    Path("/var/lib/orchestra-runtime/deploy-state/active.json"),
    Path("/opt/orchestra/runtimes/current"),
    Path("/etc/systemd/system/orchestra.service"),
    Path("/etc/systemd/system/orchestra-runtime-recovery@.service"),
    Path("/etc/systemd/system/orchestra-boundary-activate@.service"),
)
_CONTROL_SOURCES = {
    "A": {
        "control-plane/runtime-manager": "scripts/manage_orchestra_runtime.py",
        "control-plane/recovery-rehearsal": "scripts/rehearse-runtime-recovery.py",
        "control-plane/activation-probe": "scripts/runtime-activation-probe.py",
        "control-plane/activation-hook": "scripts/runtime-activation-hook.py",
        "control-plane/attestation-policy": "scripts/attestation-policy.py",
        "control-plane/boundary-attestor": "scripts/attest-boundary-rehearsal.py",
    },
    "B": {"control-plane/project-identity-rehearsal": "scripts/rehearse-project-identity.py"},
    "C": {"control-plane/provider-boundary-rehearsal": "scripts/rehearse-provider-boundary.py"},
    "D": {"control-plane/worker-boundary-audit": "scripts/audit-worker-boundary.py"},
}
_UNIT_SOURCES = {
    "A": {
        "units/orchestra.service": "deploy/orchestra.service",
        "units/orchestra.service.template": "deploy/orchestra.service.template",
        "units/orchestra-runtime-recovery@.service": "deploy/orchestra-runtime-recovery@.service",
        "units/orchestra-boundary-activate@.service": "deploy/orchestra-boundary-activate@.service",
    },
    "B": {
        "units/orchestra-project-executor.socket": "deploy/orchestra-project-executor.socket",
        "units/orchestra-project-executor@.service": "deploy/orchestra-project-executor@.service",
    },
    "C": {
        "units/orchestra-provider-controller@.service": "deploy/orchestra-provider-controller@.service"
    },
    "D": {},
}


def _run_command(argv: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    allowed = {sys.executable, "/usr/bin/git"}
    uv_allowed = argv and Path(argv[0]).is_absolute() and Path(argv[0]).name == "uv"
    assert argv and (argv[0] in allowed or uv_allowed), (
        f"delivery gate executable is not allowlisted: {argv[0]}"
    )
    return subprocess.run(
        argv,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )


def _git(*args: str) -> str:
    completed = _run_command(["/usr/bin/git", *args])
    if completed.returncode:
        raise AssertionError(completed.stderr or completed.stdout)
    return completed.stdout.strip()


def _clean_source_commit() -> str:
    status = _git("status", "--porcelain=v1", "--untracked-files=all")
    assert not status, f"delivery must run from a clean committed tree:\n{status}"
    commit = _git("rev-parse", "HEAD")
    assert len(commit) == 40
    return commit


def _sanitized_env(home: Path) -> dict[str, str]:
    environment = dict(os.environ)
    sensitive_fragments = ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY")
    for key in list(environment):
        if key in {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "INTERNAL_TOKEN"} or any(
            fragment in key.upper() for fragment in sensitive_fragments
        ):
            environment.pop(key, None)
    environment["HOME"] = str(home)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["UV_CACHE_DIR"] = str(home / "uv-cache")
    return environment


def _path_identity(path: Path) -> dict[str, Any]:
    try:
        observed = path.lstat()
    except FileNotFoundError:
        return {"exists": False}
    result: dict[str, Any] = {
        "exists": True,
        "device": observed.st_dev,
        "inode": observed.st_ino,
        "mode": observed.st_mode,
        "uid": observed.st_uid,
        "gid": observed.st_gid,
        "size": observed.st_size,
        "mtime_ns": observed.st_mtime_ns,
    }
    if path.is_symlink():
        result["symlink_target"] = os.readlink(path)
    return result


def _authority_snapshot() -> str:
    return canonical_sha256({str(path): _path_identity(path) for path in _AUTHORITY_PATHS})


def _readonly_file_entry(path: Path, *, executable: bool) -> dict[str, str]:
    assert path.is_file() and not path.is_symlink(), f"expected regular package input: {path}"
    return {
        "type": "file",
        "mode": "0555" if executable else "0444",
        "sha256": sha256_path(path),
    }


def _public_source_entry(
    path: Path,
    *,
    package_name: str,
    executable: bool,
) -> dict[str, str]:
    content = path.read_bytes()
    validate_public_source_content(package_name, content)
    return _readonly_file_entry(path, executable=executable)


def _tracked_application_inventory() -> dict[str, dict[str, str]]:
    tracked = _git("ls-files", "--", "app", "pipelines", "pyproject.toml", "uv.lock")
    paths = [line for line in tracked.splitlines() if line]
    assert paths and "app/main.py" in paths and "uv.lock" in paths
    inventory = {}
    for relative in paths:
        source = ROOT / relative
        package_name = f"app-source/{relative}"
        inventory[package_name] = _public_source_entry(
            source,
            package_name=package_name,
            executable=bool(source.stat().st_mode & 0o111),
        )
    return inventory


def _cumulative_sources(
    release: str,
    groups: dict[str, dict[str, str]],
) -> dict[str, str]:
    selected: dict[str, str] = {}
    for candidate in RELEASES:
        selected.update(groups[candidate])
        if candidate == release:
            break
    return selected


def _reference_runtime_inventory(
    reference: Path,
    *,
    uv: str,
    environment: dict[str, str],
) -> dict[str, dict[str, str]]:
    runtime_env = dict(environment)
    runtime_env["UV_PROJECT_ENVIRONMENT"] = str(reference)
    completed = _run_command(
        [
            uv,
            "sync",
            "--project",
            str(ROOT),
            "--frozen",
            "--python",
            "/usr/bin/python3.12",
            "--no-install-project",
        ],
        env=runtime_env,
    )
    if completed.returncode:
        sys.stdout.write(completed.stdout + completed.stderr)
        raise SystemExit(completed.returncode)
    inventory: dict[str, dict[str, str]] = {}
    for path in sorted(reference.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        relative = path.relative_to(reference).as_posix()
        package_name = f"runtime/{relative}"
        if path.is_symlink():
            resolved = path.resolve(strict=True)
            assert resolved.is_file(), f"runtime directory/device link is unsupported: {path}"
            inventory[package_name] = _readonly_file_entry(
                resolved,
                executable=bool(resolved.stat().st_mode & 0o111),
            )
        else:
            inventory[package_name] = _readonly_file_entry(
                path,
                executable=bool(path.stat().st_mode & 0o111),
            )
    assert "runtime/bin/python" in inventory and "runtime/pyvenv.cfg" in inventory
    return inventory


def _expected_package_inventory(
    release: str,
    *,
    uv: str,
    environment: dict[str, str],
    reference: Path,
) -> dict[str, dict[str, str]]:
    inventory = _tracked_application_inventory()
    for packaged, source in _cumulative_sources(release, _CONTROL_SOURCES).items():
        inventory[packaged] = _public_source_entry(
            ROOT / source,
            package_name=packaged,
            executable=True,
        )
    for packaged, source in _cumulative_sources(release, _UNIT_SOURCES).items():
        inventory[packaged] = _public_source_entry(
            ROOT / source,
            package_name=packaged,
            executable=False,
        )
    inventory.update(
        _reference_runtime_inventory(
            reference,
            uv=uv,
            environment=environment,
        )
    )
    return inventory


def _source_tests(release: str, environment: dict[str, str]) -> tuple[str, str]:
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-q",
        *SOURCE_TESTS[release],
    ]
    completed = _run_command(argv, env=environment)
    output = completed.stdout + completed.stderr
    if completed.returncode:
        sys.stdout.write(output)
        raise SystemExit(completed.returncode)
    return output, hashlib.sha256(output.encode()).hexdigest()


def _build_package(
    release: str,
    source_commit: str,
    environment: dict[str, str],
    scratch: Path,
) -> tuple[Path, Path]:
    assert BUILDER.is_file(), (
        "T-A missing behavior: unprivileged versioned runtime package builder is absent"
    )
    uv = shutil.which("uv", path=os.environ.get("PATH"))
    assert uv and Path(uv).is_absolute(), "uv executable is unavailable"
    package_root = Path("/var/tmp/orchestra-task303-packages")
    package_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    package_root_stat = package_root.lstat()
    assert package_root.is_dir() and not package_root.is_symlink()
    assert package_root_stat.st_uid == os.geteuid()
    assert package_root_stat.st_mode & 0o777 == 0o700
    package = package_root / f"release-{release.lower()}-{source_commit}.tar"
    manifest = scratch / "package-manifest.json"
    completed = _run_command(
        [
            sys.executable,
            str(BUILDER),
            "--delivery-only",
            "--release",
            release,
            "--source-root",
            str(ROOT),
            "--source-commit",
            source_commit,
            "--python",
            "/usr/bin/python3.12",
            "--uv",
            str(Path(uv).resolve()),
            "--output-package",
            str(package),
            "--output-manifest",
            str(manifest),
        ],
        env=environment,
    )
    if completed.returncode:
        sys.stdout.write(completed.stdout + completed.stderr)
        raise SystemExit(completed.returncode)
    expected_members = _expected_package_inventory(
        release,
        uv=str(Path(uv).resolve()),
        environment=environment,
        reference=scratch / "reference-runtime",
    )
    try:
        validate_package(
            package,
            manifest,
            release=release,
            source_commit=source_commit,
            expected_members=expected_members,
        )
    except BaseException:
        package.unlink(missing_ok=True)
        raise
    return package, manifest


def run(release: str) -> dict[str, Any]:
    assert os.geteuid() != 0, "delivery gate must run unprivileged"
    source_commit = _clean_source_commit()
    before = _authority_snapshot()
    with tempfile.TemporaryDirectory(prefix="task303-v10-delivery-", dir="/var/tmp") as raw:
        scratch = Path(raw)
        environment = _sanitized_env(scratch / "home")
        Path(environment["HOME"]).mkdir(mode=0o700)
        output, output_sha256 = _source_tests(release, environment)
        package, manifest = _build_package(
            release,
            source_commit,
            environment,
            scratch,
        )
        after = _authority_snapshot()
        assert before == after, "delivery command changed production authority state"
        assert _git("status", "--porcelain=v1", "--untracked-files=all") == ""
        report = {
            "schema": "orchestra.task303.delivery.v1",
            "release": release,
            "source_commit": source_commit,
            "delivery_ready": True,
            "activation_ready": False,
            "privileged_evidence": "pending",
            "activation_authorized": False,
            "isolation_claimed": False,
            "production_state_unchanged": True,
            "activation_receipt": None,
            "protected_secret_comparison": "pending_privileged_activation",
            "package": {
                "path": str(package),
                "sha256": sha256_path(package),
                "manifest_sha256": sha256_path(manifest),
            },
            "source_tests": {
                "exit_code": 0,
                "output_sha256": output_sha256,
                "nodeids": SOURCE_TESTS[release],
            },
            "deferred_activation_gate": {
                "status": "pending",
                "evidence_kind": "root-owned-installed-state-and-pid1",
            },
        }
        validate_delivery_report(report, release=release)
        return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("release", choices=RELEASES)
    args = parser.parse_args()
    report = run(args.release)
    output = REPORT_PATHS[args.release]
    temporary = output.with_suffix(".json.new")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

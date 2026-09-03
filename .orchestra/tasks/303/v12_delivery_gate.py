#!/usr/bin/env python3
"""V12 delivery gate for a deterministic final-prefix Python runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v10_delivery_gate as v10  # noqa: E402
import v11_delivery_gate as v11  # noqa: E402
from oracle_v12_support import (  # noqa: E402
    RELEASES,
    derive_install_prefix,
    runtime_tree_inventory,
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
    release: [
        "docs/tasks/303/test_v12_delivery_oracle.py"
        if node == "docs/tasks/303/test_v11_delivery_oracle.py"
        else node
        for node in nodes
    ]
    for release, nodes in v11.SOURCE_TESTS.items()
}


def _reference_runtime_inventory(
    reference: Path,
    *,
    uv: str,
    environment: dict[str, str],
    install_prefix: str,
) -> tuple[dict[str, dict[str, str]], set[str], dict[str, int]]:
    runtime_env = dict(environment)
    runtime_env["UV_PROJECT_ENVIRONMENT"] = str(reference)
    completed = v10._run_command(
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
    return runtime_tree_inventory(reference, install_prefix=install_prefix)


def _expected_package_inventory(
    release: str,
    source_commit: str,
    *,
    uv: str,
    environment: dict[str, str],
    reference: Path,
) -> tuple[dict[str, dict[str, str]], set[str], dict[str, int]]:
    inventory = v10._tracked_application_inventory()
    for packaged, source in v10._cumulative_sources(release, v10._CONTROL_SOURCES).items():
        inventory[packaged] = v10._public_source_entry(
            ROOT / source,
            package_name=packaged,
            executable=True,
        )
    for packaged, source in v10._cumulative_sources(release, v10._UNIT_SOURCES).items():
        inventory[packaged] = v10._public_source_entry(
            ROOT / source,
            package_name=packaged,
            executable=False,
        )
    runtime, allowed_runtime_directories, stats = _reference_runtime_inventory(
        reference,
        uv=uv,
        environment=environment,
        install_prefix=derive_install_prefix(release, source_commit),
    )
    inventory.update(runtime)
    return inventory, allowed_runtime_directories, stats


def _source_tests(release: str, environment: dict[str, str]) -> tuple[str, str]:
    completed = v10._run_command(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            *SOURCE_TESTS[release],
        ],
        env=environment,
    )
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
) -> tuple[Path, Path, dict[str, Any], dict[str, int]]:
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
    install_prefix = derive_install_prefix(release, source_commit)

    expected_members, expected_runtime_directories, stats = _expected_package_inventory(
        release,
        source_commit,
        uv=str(Path(uv).resolve()),
        environment=environment,
        reference=scratch / "reference-runtime",
    )
    completed = v10._run_command(
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
            "--install-prefix",
            install_prefix,
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
    try:
        validation = validate_package(
            package,
            manifest,
            release=release,
            source_commit=source_commit,
            expected_members=expected_members,
            expected_runtime_directories=expected_runtime_directories,
        )
    except BaseException:
        package.unlink(missing_ok=True)
        raise
    return package, manifest, validation, stats


def run(release: str) -> dict[str, Any]:
    assert os.geteuid() != 0, "delivery gate must run unprivileged"
    source_commit = v10._clean_source_commit()
    before = v10._authority_snapshot()
    with tempfile.TemporaryDirectory(prefix="task303-v12-delivery-", dir="/var/tmp") as raw:
        scratch = Path(raw)
        environment = v10._sanitized_env(scratch / "home")
        Path(environment["HOME"]).mkdir(mode=0o700)
        output, output_sha256 = _source_tests(release, environment)
        package, _manifest, validation, stats = _build_package(
            release,
            source_commit,
            environment,
            scratch,
        )
        after = v10._authority_snapshot()
        assert before == after, "delivery command changed production authority state"
        assert v10._git("status", "--porcelain=v1", "--untracked-files=all") == ""
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
                "sha256": validation["package_sha256"],
                "manifest_sha256": validation["manifest_sha256"],
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
        assert stats["activation"] == 5 and stats["shebang"] > 0 and stats["record"] > 0
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

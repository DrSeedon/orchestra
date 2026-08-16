#!/usr/bin/env python3
"""V11 unprivileged delivery gate with explicit runtime directory-link inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v10_delivery_gate as v10  # noqa: E402
from oracle_v11_support import (  # noqa: E402
    RELEASES,
    _assert_runtime_directory_target,
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
        "docs/tasks/303/test_v11_delivery_oracle.py"
        if node == "docs/tasks/303/test_v10_delivery_oracle.py"
        else node
        for node in nodes
    ]
    for release, nodes in v10.SOURCE_TESTS.items()
}


def _scan_runtime_tree(reference: Path) -> tuple[list[Path], set[str]]:
    assert reference.is_dir() and not reference.is_symlink(), (
        f"reference runtime root is not a real directory: {reference}"
    )
    nodes: list[Path] = []
    allowed_directories: set[str] = set()
    pending = [reference]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                path = Path(entry.path)
                mode = entry.stat(follow_symlinks=False).st_mode
                relative = path.relative_to(reference).as_posix()
                if stat.S_ISDIR(mode):
                    allowed_directories.add(f"runtime/{relative}")
                    pending.append(path)
                elif stat.S_ISREG(mode) or stat.S_ISLNK(mode):
                    nodes.append(path)
                else:
                    raise AssertionError(f"runtime special device is unsupported: {path}")
    return sorted(nodes), allowed_directories


def _resolve_internal_directory_link(path: Path, reference: Path) -> tuple[Path, str]:
    """Resolve every relative hop while rejecting any attempt to leave reference."""
    root = reference.resolve(strict=True)
    assert path.is_symlink()
    initial_target = os.readlink(path)
    assert not PurePosixPath(initial_target).is_absolute(), (
        f"absolute runtime directory symlink is unsupported: {path} -> {initial_target}"
    )
    resolved_parts = list(path.parent.relative_to(root).parts)
    remaining = list(PurePosixPath(initial_target).parts)
    seen_links: set[Path] = set()
    while remaining:
        part = remaining.pop(0)
        if part in ("", "."):
            continue
        if part == "..":
            assert resolved_parts, (
                f"escaping runtime directory symlink is unsupported: {path} -> {initial_target}"
            )
            resolved_parts.pop()
            continue
        candidate = root.joinpath(*resolved_parts, part)
        try:
            mode = candidate.lstat().st_mode
        except FileNotFoundError as exc:
            raise AssertionError(
                f"dangling runtime directory symlink is unsupported: {path} -> {initial_target}"
            ) from exc
        if stat.S_ISLNK(mode):
            assert candidate not in seen_links, (
                f"cyclic runtime directory symlink is unsupported: {path} -> {initial_target}"
            )
            seen_links.add(candidate)
            next_target = os.readlink(candidate)
            assert not PurePosixPath(next_target).is_absolute(), (
                f"absolute chained runtime symlink is unsupported: {candidate} -> {next_target}"
            )
            remaining = list(PurePosixPath(next_target).parts) + remaining
            continue
        if remaining:
            assert stat.S_ISDIR(mode), (
                f"runtime symlink traverses a non-directory: {path} -> {initial_target}"
            )
        resolved_parts.append(part)
    resolved = root.joinpath(*resolved_parts)
    mode = resolved.lstat().st_mode
    assert stat.S_ISDIR(mode), (
        f"runtime directory link resolves to a non-directory: {path} -> {initial_target}"
    )
    assert path.resolve(strict=True) == resolved, (
        f"runtime directory link resolution disagrees with the filesystem: {path}"
    )
    canonical = os.path.relpath(resolved, path.parent)
    assert initial_target == canonical, (
        f"non-canonical runtime directory symlink: {path} -> {initial_target}; "
        f"expected {canonical}"
    )
    return resolved, initial_target


def _runtime_tree_inventory(
    reference: Path,
) -> tuple[dict[str, dict[str, str]], set[str]]:
    nodes, allowed_directories = _scan_runtime_tree(reference)
    inventory: dict[str, dict[str, str]] = {}
    for path in nodes:
        relative = path.relative_to(reference).as_posix()
        package_name = f"runtime/{relative}"
        if path.is_symlink():
            try:
                resolved = path.resolve(strict=True)
            except (FileNotFoundError, RuntimeError) as exc:
                raise AssertionError(f"dangling/cyclic runtime symlink is unsupported: {path}") from exc
            if resolved.is_dir():
                resolved, target = _resolve_internal_directory_link(path, reference)
                resolved_name = f"runtime/{resolved.relative_to(reference).as_posix()}"
                _assert_runtime_directory_target(PurePosixPath(resolved_name))
                assert resolved_name in allowed_directories, (
                    f"runtime directory symlink target is not independently allowlisted: "
                    f"{path} -> {resolved_name}"
                )
                inventory[package_name] = {
                    "type": "symlink",
                    "mode": f"{path.lstat().st_mode & 0o7777:04o}",
                    "target": target,
                }
            else:
                assert resolved.is_file(), (
                    f"runtime device link is unsupported: {path}"
                )
                inventory[package_name] = v10._readonly_file_entry(
                    resolved,
                    executable=bool(resolved.stat().st_mode & 0o111),
                )
        else:
            inventory[package_name] = v10._readonly_file_entry(
                path,
                executable=bool(path.stat().st_mode & 0o111),
            )
    assert "runtime/bin/python" in inventory and "runtime/pyvenv.cfg" in inventory
    return inventory, allowed_directories


def _reference_runtime_inventory(
    reference: Path,
    *,
    uv: str,
    environment: dict[str, str],
) -> tuple[dict[str, dict[str, str]], set[str]]:
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
    return _runtime_tree_inventory(reference)


def _expected_package_inventory(
    release: str,
    *,
    uv: str,
    environment: dict[str, str],
    reference: Path,
) -> tuple[dict[str, dict[str, str]], set[str]]:
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
    runtime, allowed_runtime_directories = _reference_runtime_inventory(
        reference,
        uv=uv,
        environment=environment,
    )
    inventory.update(runtime)
    return inventory, allowed_runtime_directories


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
) -> tuple[Path, Path, dict[str, Any]]:
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

    expected_members, expected_runtime_directories = _expected_package_inventory(
        release,
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
    return package, manifest, validation


def run(release: str) -> dict[str, Any]:
    assert os.geteuid() != 0, "delivery gate must run unprivileged"
    source_commit = v10._clean_source_commit()
    before = v10._authority_snapshot()
    with tempfile.TemporaryDirectory(prefix="task303-v11-delivery-", dir="/var/tmp") as raw:
        scratch = Path(raw)
        environment = v10._sanitized_env(scratch / "home")
        Path(environment["HOME"]).mkdir(mode=0o700)
        output, output_sha256 = _source_tests(release, environment)
        package, manifest, validation = _build_package(
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

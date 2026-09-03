"""V12 deterministic runtime-prefix normalization and package validation.

V9-V11 remain immutable evidence.  V12 normalizes only five known activation
templates and executable ``bin`` shebangs from an independently built virtual
environment, then recomputes only RECORD files that own changed console scripts.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
from typing import Any

import oracle_v11_support as v11
import v11_delivery_gate as gate_v11
from oracle_v10_support import (
    PACKAGE_MANIFEST_KEYS as V10_PACKAGE_MANIFEST_KEYS,
    RELEASES,
    REQUIRED_PACKAGE_MEMBERS,
    validate_delivery_report,
)


PACKAGE_SCHEMA = "orchestra.runtime-package.v2"
PACKAGE_MANIFEST_KEYS = V10_PACKAGE_MANIFEST_KEYS | {"install_prefix"}
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_INSTALL_PREFIX_RE = re.compile(
    r"/opt/orchestra/runtimes/[0-9a-f]{40}-[a-d]-py312"
)
_ACTIVATION_LINES = {
    "runtime/bin/activate": "VIRTUAL_ENV='{prefix}'",
    "runtime/bin/activate.bat": '@for %%i in ("{prefix}") do @set "VIRTUAL_ENV=%%~fi"',
    "runtime/bin/activate.csh": "setenv VIRTUAL_ENV '{prefix}'",
    "runtime/bin/activate.fish": "set -gx VIRTUAL_ENV '{prefix}'",
    "runtime/bin/activate.nu": "    let virtual_env = '{prefix}'",
}


def derive_install_prefix(release: str, source_commit: str) -> str:
    assert release in RELEASES
    assert _COMMIT_RE.fullmatch(source_commit), "source commit must be 40 lowercase hex bytes"
    return f"/opt/orchestra/runtimes/{source_commit}-{release.lower()}-py312"


def _assert_install_prefix(install_prefix: str) -> None:
    assert _INSTALL_PREFIX_RE.fullmatch(install_prefix), (
        f"runtime install prefix is not the fixed versioned path: {install_prefix}"
    )


def _replace_exact_line(content: bytes, expected: bytes, replacement: bytes, name: str) -> bytes:
    lines = content.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.rstrip(b"\r\n") == expected]
    assert len(matches) == 1, f"unrecognized activation prefix grammar: {name}"
    index = matches[0]
    ending = lines[index][len(lines[index].rstrip(b"\r\n")) :]
    lines[index] = replacement + ending
    return b"".join(lines)


def _normalize_prefix_bearing_file(
    name: str,
    content: bytes,
    *,
    executable: bool,
    reference_prefix: bytes,
    install_prefix: bytes,
) -> tuple[bytes, str | None]:
    if name in _ACTIVATION_LINES:
        template = _ACTIVATION_LINES[name]
        normalized = _replace_exact_line(
            content,
            template.format(prefix=os.fsdecode(reference_prefix)).encode(),
            template.format(prefix=os.fsdecode(install_prefix)).encode(),
            name,
        )
        assert reference_prefix not in normalized, f"reference prefix remains after normalization: {name}"
        return normalized, "activation"

    shebang = b"#!" + reference_prefix + b"/bin/python"
    first = content.splitlines(keepends=True)[0] if content else b""
    if first.rstrip(b"\r\n") == shebang:
        assert executable and name.startswith("runtime/bin/"), (
            f"prefix-bearing shebang is outside executable runtime/bin: {name}"
        )
        ending = first[len(first.rstrip(b"\r\n")) :]
        normalized = b"#!" + install_prefix + b"/bin/python" + ending + content[len(first) :]
        assert reference_prefix not in normalized, f"reference prefix remains after normalization: {name}"
        return normalized, "shebang"

    assert reference_prefix not in content, f"unclassified embedded runtime prefix: {name}"
    return content, None


def _record_target(record_name: str, entry: str) -> str:
    assert entry and not PurePosixPath(entry).is_absolute(), (
        f"absolute or empty RECORD entry is unsupported: {record_name}: {entry}"
    )
    site_packages = PurePosixPath(record_name).parent.parent
    normalized = PurePosixPath(posixpath.normpath((site_packages / entry).as_posix()))
    assert normalized.parts and normalized.parts[0] == "runtime" and ".." not in normalized.parts, (
        f"RECORD entry escapes the runtime: {record_name}: {entry}"
    )
    return normalized.as_posix()


def _rewrite_owning_records(
    content: dict[str, bytes],
    shebang_names: set[str],
    *,
    forbidden_prefix: bytes,
) -> tuple[dict[str, bytes], set[str]]:
    normalized = dict(content)
    covered: set[str] = set()
    coverage_count = {name: 0 for name in shebang_names}
    rewritten: set[str] = set()
    for record_name in sorted(name for name in content if name.endswith(".dist-info/RECORD")):
        assert forbidden_prefix not in content[record_name], (
            f"unclassified embedded runtime prefix: {record_name}"
        )
        try:
            rows = list(csv.reader(io.StringIO(content[record_name].decode("utf-8"))))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise AssertionError(f"invalid wheel RECORD: {record_name}") from exc
        output_rows: list[list[str]] = []
        changed = False
        seen_entries: set[str] = set()
        for row in rows:
            assert len(row) == 3, f"invalid RECORD row: {record_name}"
            entry, recorded_hash, recorded_size = row
            assert entry not in seen_entries, f"duplicate RECORD entry: {record_name}: {entry}"
            seen_entries.add(entry)
            target = _record_target(record_name, entry)
            if target in shebang_names:
                payload = content[target]
                digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
                output_rows.append([entry, f"sha256={digest}", str(len(payload))])
                covered.add(target)
                coverage_count[target] += 1
                changed = True
            else:
                output_rows.append([entry, recorded_hash, recorded_size])
        if changed:
            stream = io.StringIO(newline="")
            csv.writer(stream, lineterminator="\n").writerows(output_rows)
            normalized[record_name] = stream.getvalue().encode("utf-8")
            rewritten.add(record_name)
    assert covered == shebang_names, (
        f"console-script RECORD ownership mismatch: missing={sorted(shebang_names - covered)} "
        f"extra={sorted(covered - shebang_names)}"
    )
    assert all(count == 1 for count in coverage_count.values()), (
        f"console-script RECORD ownership is not unique: {coverage_count}"
    )
    return normalized, rewritten


def _normalized_runtime_bytes(
    reference: Path,
    *,
    install_prefix: str,
) -> tuple[dict[str, bytes], dict[str, str], set[str], dict[str, int]]:
    _assert_install_prefix(install_prefix)
    nodes, allowed_directories = gate_v11._scan_runtime_tree(reference)
    reference_prefix = os.fsencode(str(reference.resolve(strict=True)))
    final_prefix = os.fsencode(install_prefix)
    raw: dict[str, bytes] = {}
    executable: dict[str, bool] = {}
    links: dict[str, str] = {}

    for path in nodes:
        name = f"runtime/{path.relative_to(reference).as_posix()}"
        if path.is_symlink():
            try:
                resolved = path.resolve(strict=True)
            except (FileNotFoundError, RuntimeError) as exc:
                raise AssertionError(f"dangling/cyclic runtime symlink is unsupported: {path}") from exc
            if resolved.is_dir():
                resolved, target = gate_v11._resolve_internal_directory_link(path, reference)
                resolved_name = f"runtime/{resolved.relative_to(reference).as_posix()}"
                v11._assert_runtime_directory_target(PurePosixPath(resolved_name))
                assert resolved_name in allowed_directories
                links[name] = target
                continue
            assert resolved.is_file(), f"runtime device link is unsupported: {path}"
            source = resolved
        else:
            source = path
        raw[name] = source.read_bytes()
        executable[name] = bool(source.stat().st_mode & 0o111)

    normalized: dict[str, bytes] = {}
    classifications: dict[str, str] = {}
    for name, payload in raw.items():
        if name.endswith(".dist-info/RECORD"):
            normalized[name] = payload
            continue
        value, classification = _normalize_prefix_bearing_file(
            name,
            payload,
            executable=executable[name],
            reference_prefix=reference_prefix,
            install_prefix=final_prefix,
        )
        normalized[name] = value
        if classification:
            classifications[name] = classification

    activation_names = {name for name, kind in classifications.items() if kind == "activation"}
    assert activation_names == set(_ACTIVATION_LINES), (
        f"activation template inventory changed: {sorted(activation_names)}"
    )
    shebang_names = {name for name, kind in classifications.items() if kind == "shebang"}
    assert shebang_names, "runtime has no classified console scripts"
    normalized, rewritten_records = _rewrite_owning_records(
        normalized,
        shebang_names,
        forbidden_prefix=reference_prefix,
    )

    stats = {
        "activation": len(activation_names),
        "shebang": len(shebang_names),
        "record": len(rewritten_records),
    }
    return normalized, links, allowed_directories, stats


def runtime_tree_inventory(
    reference: Path,
    *,
    install_prefix: str,
) -> tuple[dict[str, dict[str, str]], set[str], dict[str, int]]:
    content, links, allowed_directories, stats = _normalized_runtime_bytes(
        reference,
        install_prefix=install_prefix,
    )
    inventory = {
        name: {
            "type": "file",
            "mode": "0555" if (reference / name.removeprefix("runtime/")).resolve(strict=True).stat().st_mode & 0o111 else "0444",
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for name, payload in content.items()
    }
    for name, target in links.items():
        path = reference / name.removeprefix("runtime/")
        inventory[name] = {
            "type": "symlink",
            "mode": f"{path.lstat().st_mode & 0o7777:04o}",
            "target": target,
        }
    assert "runtime/bin/python" in inventory and "runtime/pyvenv.cfg" in inventory
    return inventory, allowed_directories, stats


def validate_package(
    package_path: Path,
    manifest_path: Path,
    *,
    release: str,
    source_commit: str,
    expected_members: dict[str, dict[str, Any]],
    expected_runtime_directories: set[str],
) -> dict[str, Any]:
    expected_install_prefix = derive_install_prefix(release, source_commit)
    with v11._pinned_snapshot(package_path, required_mode=0o600) as (
        package_snapshot,
        package_sha256,
        package_identity,
    ):
        assert package_identity[3] == os.geteuid(), "delivery package is not owned by its builder"
        with v11._pinned_snapshot(manifest_path) as (
            manifest_snapshot,
            manifest_sha256,
            manifest_identity,
        ):
            try:
                manifest = json.loads(manifest_snapshot.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AssertionError("package manifest is not canonical UTF-8 JSON") from exc
            assert set(manifest) == PACKAGE_MANIFEST_KEYS
            assert manifest["schema"] == PACKAGE_SCHEMA
            assert manifest["release"] == release
            assert manifest["source_commit"] == source_commit
            assert manifest["install_prefix"] == expected_install_prefix
            assert manifest["delivery_only"] is True
            assert manifest["activation_ready"] is False
            assert manifest["privileged_evidence"] == "pending"
            assert manifest["isolation_claimed"] is False
            assert manifest["provider_credential_store_included"] is False
            assert manifest["protected_secret_comparison"] == "pending_privileged_activation"
            assert manifest["activation_state_included"] is False
            assert manifest["package_sha256"] == package_sha256
            assert str(manifest["python_version"]).startswith("3.12.")
            assert set(expected_members) >= REQUIRED_PACKAGE_MEMBERS[release]
            observed = v11._inspect_snapshot(
                package_snapshot,
                allowed_members=set(expected_members),
                allowed_runtime_directories=expected_runtime_directories,
            )
            assert observed == expected_members, (
                "package bytes/modes/links differ from normalized independent inventory"
            )
            assert manifest["members"] == observed
            return {
                "manifest": manifest,
                "package_sha256": package_sha256,
                "manifest_sha256": manifest_sha256,
                "package_identity": package_identity,
                "manifest_identity": manifest_identity,
            }


__all__ = [
    "PACKAGE_MANIFEST_KEYS",
    "PACKAGE_SCHEMA",
    "RELEASES",
    "REQUIRED_PACKAGE_MEMBERS",
    "derive_install_prefix",
    "runtime_tree_inventory",
    "validate_delivery_report",
    "validate_package",
]

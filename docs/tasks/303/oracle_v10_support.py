"""Frozen support for the #303 V10 delivery/activation split.

Delivery evidence is intentionally non-authoritative.  This module validates an
unprivileged package build and a pending-only report; it never validates or
consumes an activation attestation.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
from typing import Any


DELIVERY_SCHEMA = "orchestra.task303.delivery.v1"
PACKAGE_SCHEMA = "orchestra.runtime-package.v1"
RELEASES = ("A", "B", "C", "D")
DELIVERY_REPORT_KEYS = {
    "schema",
    "release",
    "source_commit",
    "delivery_ready",
    "activation_ready",
    "privileged_evidence",
    "activation_authorized",
    "isolation_claimed",
    "production_state_unchanged",
    "activation_receipt",
    "protected_secret_comparison",
    "package",
    "source_tests",
    "deferred_activation_gate",
}
ACTIVATION_ONLY_KEYS = {
    "activation_id",
    "run_nonce",
    "signature",
    "signature_algorithm",
    "public_key_sha256",
    "boot_id",
    "host_id_sha256",
    "target_pid",
    "target_starttime",
    "runtime",
    "issued_at_ns",
    "expires_at_ns",
    "consumed_at_ns",
}
PACKAGE_MANIFEST_KEYS = {
    "schema",
    "release",
    "source_commit",
    "delivery_only",
    "activation_ready",
    "privileged_evidence",
    "isolation_claimed",
    "provider_credential_store_included",
    "protected_secret_comparison",
    "activation_state_included",
    "package_sha256",
    "python_version",
    "members",
}

_BASE_REQUIRED_MEMBERS = {
    "app-source/app/main.py",
    "app-source/app/manager.py",
    "app-source/app/routes/system.py",
    "app-source/app/runtime_activation.py",
    "control-plane/runtime-manager",
    "control-plane/recovery-rehearsal",
    "control-plane/activation-probe",
    "control-plane/activation-hook",
    "control-plane/attestation-policy",
    "control-plane/boundary-attestor",
    "runtime/bin/python",
    "runtime/pyvenv.cfg",
    "units/orchestra.service",
    "units/orchestra.service.template",
    "units/orchestra-runtime-recovery@.service",
    "units/orchestra-boundary-activate@.service",
}
REQUIRED_PACKAGE_MEMBERS = {
    "A": _BASE_REQUIRED_MEMBERS,
    "B": _BASE_REQUIRED_MEMBERS
    | {
        "app-source/app/execution_identity.py",
        "control-plane/project-identity-rehearsal",
        "units/orchestra-project-executor.socket",
        "units/orchestra-project-executor@.service",
    },
    "C": _BASE_REQUIRED_MEMBERS
    | {
        "app-source/app/execution_identity.py",
        "app-source/app/provider_boundary.py",
        "app-source/app/provider_inputs.py",
        "app-source/app/project_tool_broker.py",
        "control-plane/project-identity-rehearsal",
        "control-plane/provider-boundary-rehearsal",
        "units/orchestra-project-executor.socket",
        "units/orchestra-project-executor@.service",
        "units/orchestra-provider-controller@.service",
    },
    "D": _BASE_REQUIRED_MEMBERS
    | {
        "app-source/app/execution_identity.py",
        "app-source/app/provider_boundary.py",
        "app-source/app/provider_inputs.py",
        "app-source/app/project_tool_broker.py",
        "app-source/app/runtime_env.py",
        "app-source/app/mcp_capability.py",
        "control-plane/project-identity-rehearsal",
        "control-plane/provider-boundary-rehearsal",
        "control-plane/worker-boundary-audit",
        "units/orchestra-project-executor.socket",
        "units/orchestra-project-executor@.service",
        "units/orchestra-provider-controller@.service",
    },
}

_FORBIDDEN_MEMBER_PARTS = {
    ".env",
    "auth.json",
    "activations",
    "attestation-state",
    "keys",
    "provider-selection.json",
    "control-plane-selected.json",
}

_PUBLIC_SOURCE_PREFIXES = ("app-source/", "control-plane/", "units/")
_PUBLIC_APP_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".lock",
    ".md",
    ".py",
    ".svg",
    ".toml",
    ".yaml",
}
_PRIVATE_KEY_MATERIAL = re.compile(
    rb"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?-----END [^-\r\n]*PRIVATE KEY-----",
    re.DOTALL,
)
_TOKEN_MATERIAL = re.compile(
    rb"(?i)(?:Bearer[ \t]+[A-Za-z0-9._~+/=-]{20,}|"
    rb"(?:sk-or-v1-|ya29\.|gh[pousr]_|AIza|y0_)[A-Za-z0-9._~+/=-]{12,})"
)
_NAMED_LITERAL_CREDENTIAL = re.compile(
    r"(?m)^[ \t]*[\"']?[A-Za-z0-9_.-]*"
    r"(?i:refresh[_-]?token|access[_-]?token|api[_-]?key|password|secret|credential|private[_-]?key)"
    r"[A-Za-z0-9_.-]*[\"']?[ \t]*(?:=|:[ \t]*)[ \t]*"
    r"(?:\"(?P<double>[^\"\r\n]+)\"|'(?P<single>[^'\r\n]+)'|(?P<bare>[A-Z][A-Z0-9_]{5,}))"
)
_ENV_REFERENCE = re.compile(r"(?:\{env:[A-Z][A-Z0-9_]*\}|\$\{[A-Z][A-Z0-9_]*\}|\$[A-Z][A-Z0-9_]*)")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    assert name and not path.is_absolute(), f"absolute package member: {name}"
    assert ".." not in path.parts and "." not in path.parts, f"unsafe package member: {name}"
    assert not _FORBIDDEN_MEMBER_PARTS.intersection(path.parts), (
        f"authority/credential state leaked into delivery package: {name}"
    )
    return path


def _safe_link_target(member: PurePosixPath, target: str) -> PurePosixPath:
    target_path = PurePosixPath(target)
    assert not target_path.is_absolute(), f"absolute package symlink: {member} -> {target}"
    resolved: list[str] = []
    for part in member.parent.parts + target_path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            assert resolved, f"escaping package symlink: {member} -> {target}"
            resolved.pop()
        else:
            resolved.append(part)
    return _safe_member_path("/".join(resolved))


def validate_public_source_content(name: str, content: bytes) -> None:
    """Reject credential material in the package's public source classes."""
    assert name.startswith(_PUBLIC_SOURCE_PREFIXES), f"not a public source member: {name}"
    path = PurePosixPath(name)
    if name.startswith("app-source/"):
        assert path.suffix.lower() in _PUBLIC_APP_SUFFIXES, (
            f"untyped application payload in delivery package: {name}"
        )
    assert not _PRIVATE_KEY_MATERIAL.search(content), f"private key material in delivery source: {name}"
    assert not _TOKEN_MATERIAL.search(content), f"token material in delivery source: {name}"
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AssertionError(f"non-UTF-8 public source payload: {name}") from exc
    for match in _NAMED_LITERAL_CREDENTIAL.finditer(text):
        value = match.group("double") or match.group("single") or match.group("bare")
        assert _ENV_REFERENCE.fullmatch(value) is not None, (
            f"literal credential in delivery source: {name}"
        )


def inspect_package(
    package_path: Path,
    *,
    allowed_members: set[str],
) -> dict[str, dict[str, Any]]:
    assert allowed_members, "package allowlist is empty"
    observed: dict[str, dict[str, Any]] = {}
    with tarfile.open(package_path, mode="r:*") as archive:
        for member in archive.getmembers():
            member_path = _safe_member_path(member.name)
            name = str(member_path)
            if member.isdir():
                continue
            assert name in allowed_members, f"package member is not in the derived allowlist: {name}"
            assert name not in observed, f"duplicate package member: {name}"
            if member.isfile():
                extracted = archive.extractfile(member)
                assert extracted is not None
                if name.startswith(_PUBLIC_SOURCE_PREFIXES):
                    content = extracted.read()
                    validate_public_source_content(name, content)
                    digest = hashlib.sha256(content)
                else:
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: extracted.read(1024 * 1024), b""):
                        digest.update(chunk)
                observed[name] = {
                    "type": "file",
                    "mode": f"{member.mode & 0o7777:04o}",
                    "sha256": digest.hexdigest(),
                }
            elif member.issym():
                resolved_target = _safe_link_target(member_path, member.linkname)
                assert str(resolved_target) in allowed_members, (
                    f"package symlink target is not in the derived allowlist: "
                    f"{name} -> {resolved_target}"
                )
                observed[name] = {
                    "type": "symlink",
                    "mode": f"{member.mode & 0o7777:04o}",
                    "target": member.linkname,
                }
            else:
                raise AssertionError(f"unsupported package member type: {name}")
    assert observed, "empty delivery package"
    return observed


def validate_package(
    package_path: Path,
    manifest_path: Path,
    *,
    release: str,
    source_commit: str,
    expected_members: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    assert release in RELEASES
    assert package_path.is_file(), "package builder did not create the package"
    package_stat = package_path.lstat()
    assert not package_path.is_symlink(), "delivery package path is a symlink"
    assert package_stat.st_uid == os.geteuid(), "delivery package is not owned by its builder"
    assert package_stat.st_mode & 0o777 == 0o600, "delivery package must be mode 0600"
    assert manifest_path.is_file(), "package builder did not create the manifest"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest) == PACKAGE_MANIFEST_KEYS
    assert manifest["schema"] == PACKAGE_SCHEMA
    assert manifest["release"] == release
    assert manifest["source_commit"] == source_commit
    assert manifest["delivery_only"] is True
    assert manifest["activation_ready"] is False
    assert manifest["privileged_evidence"] == "pending"
    assert manifest["isolation_claimed"] is False
    assert manifest["provider_credential_store_included"] is False
    assert manifest["protected_secret_comparison"] == "pending_privileged_activation"
    assert manifest["activation_state_included"] is False
    assert manifest["package_sha256"] == sha256_path(package_path)
    assert str(manifest["python_version"]).startswith("3.12.")
    assert set(expected_members) >= REQUIRED_PACKAGE_MEMBERS[release]
    observed = inspect_package(package_path, allowed_members=set(expected_members))
    assert observed == expected_members, "package bytes/modes/links differ from derived inventory"
    assert manifest["members"] == observed
    missing = REQUIRED_PACKAGE_MEMBERS[release] - set(observed)
    assert not missing, f"delivery package missing required members: {sorted(missing)}"
    return manifest


def validate_delivery_report(report: dict[str, Any], *, release: str) -> None:
    assert release in RELEASES
    assert set(report) == DELIVERY_REPORT_KEYS
    assert not ACTIVATION_ONLY_KEYS.intersection(report)
    assert report["schema"] == DELIVERY_SCHEMA
    assert report["release"] == release
    assert len(report["source_commit"]) == 40
    assert report["delivery_ready"] is True
    assert report["activation_ready"] is False
    assert report["privileged_evidence"] == "pending"
    assert report["activation_authorized"] is False
    assert report["isolation_claimed"] is False
    assert report["production_state_unchanged"] is True
    assert report["activation_receipt"] is None
    assert report["protected_secret_comparison"] == "pending_privileged_activation"
    assert report["deferred_activation_gate"] == {
        "status": "pending",
        "evidence_kind": "root-owned-installed-state-and-pid1",
    }
    package = report["package"]
    assert set(package) == {"path", "sha256", "manifest_sha256"}
    assert Path(package["path"]).is_absolute()
    assert len(package["sha256"]) == 64
    assert len(package["manifest_sha256"]) == 64
    tests = report["source_tests"]
    assert set(tests) == {"exit_code", "output_sha256", "nodeids"}
    assert tests["exit_code"] == 0
    assert len(tests["output_sha256"]) == 64
    assert tests["nodeids"]


def synthetic_tar(members: dict[str, bytes | tuple[str, str]]) -> bytes:
    """Build small deterministic fixtures for the frozen oracle self-test."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, value in sorted(members.items()):
            info = tarfile.TarInfo(name)
            info.mtime = 0
            info.uid = info.gid = 0
            info.mode = 0o555
            if isinstance(value, tuple):
                kind, target = value
                assert kind == "symlink"
                info.type = tarfile.SYMTYPE
                info.linkname = target
                archive.addfile(info)
            else:
                info.size = len(value)
                archive.addfile(info, io.BytesIO(value))
    return buffer.getvalue()

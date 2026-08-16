"""V11 package validation for canonical internal runtime directory links.

V10 remains immutable historical evidence.  V11 reuses its pending-only report
and source-content policy, while making directory links an explicit, separately
derived part of the runtime inventory.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import stat
import tarfile
import tempfile
from typing import Any

from oracle_v10_support import (
    PACKAGE_MANIFEST_KEYS,
    PACKAGE_SCHEMA,
    RELEASES,
    REQUIRED_PACKAGE_MEMBERS,
    _PUBLIC_SOURCE_PREFIXES,
    _safe_link_target,
    _safe_member_path,
    sha256_path,
    validate_delivery_report,
    validate_public_source_content,
)


_PROTECTED_RUNTIME_ROOTS = {
    ".ssh",
    "auth-store",
    "credentials",
    "credential-store",
    "secrets",
    "state",
}


def _assert_runtime_directory_target(target: PurePosixPath) -> None:
    assert len(target.parts) >= 2 and target.parts[0] == "runtime", (
        f"directory symlink target is outside the runtime root: {target}"
    )
    assert target.parts[1].casefold() not in _PROTECTED_RUNTIME_ROOTS, (
        f"directory symlink targets credential/activation state: {target}"
    )


def _canonical_directory_link_target(
    member: PurePosixPath,
    target: str,
    *,
    allowed_runtime_directories: set[str],
) -> PurePosixPath:
    resolved = _safe_link_target(member, target)
    _assert_runtime_directory_target(resolved)
    assert str(resolved) in allowed_runtime_directories, (
        f"package directory symlink target is not an independently allowed runtime directory: "
        f"{member} -> {resolved}"
    )
    canonical = posixpath.relpath(resolved.as_posix(), member.parent.as_posix())
    assert target == canonical, (
        f"non-canonical package directory symlink: {member} -> {target}; "
        f"expected {canonical}"
    )
    return resolved


def _identity(observed: os.stat_result) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        observed.st_dev,
        observed.st_ino,
        observed.st_mode,
        observed.st_uid,
        observed.st_gid,
        observed.st_size,
        observed.st_mtime_ns,
        observed.st_ctime_ns,
    )


@contextmanager
def _pinned_snapshot(path: Path, *, required_mode: int | None = None):
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AssertionError(f"cannot open regular file without following links: {path}") from exc
    snapshot = tempfile.TemporaryFile(mode="w+b", dir="/var/tmp")
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode), f"expected regular file: {path}"
        if required_mode is not None:
            assert before.st_mode & 0o777 == required_mode, (
                f"file mode changed before validation: {path}"
            )
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            snapshot.write(chunk)
        after_copy = os.fstat(descriptor)
        assert _identity(after_copy) == _identity(before), (
            f"file identity/content changed while snapshotting: {path}"
        )
        current = path.lstat()
        assert not stat.S_ISLNK(current.st_mode) and _identity(current) == _identity(before), (
            f"file path identity changed before validation: {path}"
        )
        snapshot.flush()
        snapshot.seek(0)
        yield snapshot, digest.hexdigest(), _identity(before)
        final = path.lstat()
        assert not stat.S_ISLNK(final.st_mode) and _identity(final) == _identity(before), (
            f"file path identity changed during validation: {path}"
        )
    finally:
        snapshot.close()
        os.close(descriptor)


def _inspect_snapshot(
    snapshot,
    *,
    allowed_members: set[str],
    allowed_runtime_directories: set[str],
) -> dict[str, dict[str, Any]]:
    snapshot.seek(0)
    observed: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    with tarfile.open(fileobj=snapshot, mode="r:*") as archive:
        for member in archive.getmembers():
            member_path = _safe_member_path(member.name)
            name = str(member_path)
            assert name not in seen, f"duplicate package member: {name}"
            seen.add(name)
            assert not member.isdir(), (
                f"explicit package directory entries are outside the canonical representation: {name}"
            )
            assert name in allowed_members, (
                f"package member is not in the derived allowlist: {name}"
            )
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
                if str(resolved_target) in allowed_runtime_directories:
                    _canonical_directory_link_target(
                        member_path,
                        member.linkname,
                        allowed_runtime_directories=allowed_runtime_directories,
                    )
                else:
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
    for name, entry in observed.items():
        if entry["type"] != "symlink":
            continue
        target = _safe_link_target(PurePosixPath(name), entry["target"])
        target_name = str(target)
        if target_name in allowed_runtime_directories:
            continue
        assert target_name in observed, (
            f"package symlink target is absent from the archive: {name} -> {target_name}"
        )
        assert observed[target_name]["type"] != "symlink", (
            f"chained/cyclic package symlink is outside the canonical representation: "
            f"{name} -> {target_name}"
        )
    assert observed, "empty delivery package"
    return observed


def inspect_package(
    package_path: Path,
    *,
    allowed_members: set[str],
    allowed_runtime_directories: set[str],
) -> dict[str, dict[str, Any]]:
    """Inspect an archive without extracting it or trusting its manifest."""
    assert allowed_members, "package allowlist is empty"
    assert allowed_runtime_directories, "runtime directory allowlist is empty"
    for directory in allowed_runtime_directories:
        safe = _safe_member_path(directory)
        _assert_runtime_directory_target(safe)
    with _pinned_snapshot(package_path) as (snapshot, _digest, _identity_value):
        return _inspect_snapshot(
            snapshot,
            allowed_members=allowed_members,
            allowed_runtime_directories=allowed_runtime_directories,
        )


def validate_package(
    package_path: Path,
    manifest_path: Path,
    *,
    release: str,
    source_commit: str,
    expected_members: dict[str, dict[str, Any]],
    expected_runtime_directories: set[str],
) -> dict[str, Any]:
    assert release in RELEASES
    with _pinned_snapshot(package_path, required_mode=0o600) as (
        package_snapshot,
        package_sha256,
        package_identity,
    ):
        assert package_identity[3] == os.geteuid(), (
            "delivery package is not owned by its builder"
        )
        with _pinned_snapshot(manifest_path) as (
            manifest_snapshot,
            manifest_sha256,
            manifest_identity,
        ):
            manifest_bytes = manifest_snapshot.read()
            try:
                manifest = json.loads(manifest_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AssertionError("package manifest is not canonical UTF-8 JSON") from exc
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
            assert manifest["package_sha256"] == package_sha256
            assert str(manifest["python_version"]).startswith("3.12.")
            assert set(expected_members) >= REQUIRED_PACKAGE_MEMBERS[release]
            observed = _inspect_snapshot(
                package_snapshot,
                allowed_members=set(expected_members),
                allowed_runtime_directories=expected_runtime_directories,
            )
            assert observed == expected_members, (
                "package bytes/modes/links differ from derived inventory"
            )
            assert manifest["members"] == observed
            missing = REQUIRED_PACKAGE_MEMBERS[release] - set(observed)
            assert not missing, f"delivery package missing required members: {sorted(missing)}"
            return {
                "manifest": manifest,
                "package_sha256": package_sha256,
                "manifest_sha256": manifest_sha256,
                "package_identity": package_identity,
                "manifest_identity": manifest_identity,
            }


def synthetic_tar(members: dict[str, bytes | tuple[str, str]]) -> bytes:
    """Build deterministic file, directory-link, and special-node fixtures."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, value in sorted(members.items()):
            info = tarfile.TarInfo(name)
            info.mtime = 0
            info.uid = info.gid = 0
            if isinstance(value, tuple):
                kind, target = value
                if kind == "symlink":
                    info.type = tarfile.SYMTYPE
                    info.linkname = target
                    info.mode = 0o777
                elif kind == "directory":
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                elif kind == "fifo":
                    info.type = tarfile.FIFOTYPE
                    info.mode = 0o600
                else:
                    raise AssertionError(f"unsupported synthetic member type: {kind}")
                archive.addfile(info)
            else:
                info.mode = 0o555
                info.size = len(value)
                archive.addfile(info, io.BytesIO(value))
    return buffer.getvalue()


__all__ = [
    "PACKAGE_MANIFEST_KEYS",
    "RELEASES",
    "REQUIRED_PACKAGE_MEMBERS",
    "inspect_package",
    "sha256_path",
    "synthetic_tar",
    "validate_delivery_report",
    "validate_package",
    "validate_public_source_content",
]

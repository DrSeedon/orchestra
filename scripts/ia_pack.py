"""Build, validate, and restore privacy-safe OVPack filesystem packages."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from app.ia.recovery import contains_private
from app.ia.schema import RecordValidationError, canonical_bytes, validate_record


class PackValidationError(ValueError):
    """Raised when an OVPack cannot be trusted without mutating its target."""


_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_SCOPE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_EVENT_PATH = re.compile(
    r"projects/[^/]+/sessions/[^/]+/history/[^/]+/events/[^/]+\.json"
)
_MESSAGES_PATH = re.compile(
    r"projects/[^/]+/sessions/[^/]+/history/[^/]+/messages\.json"
)


def _json_bytes(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PackValidationError("schema: value is not canonical JSON") from exc
    return rendered.encode("utf-8")


def _read_json_bytes(content: bytes, *, label: str) -> Any:
    try:
        return json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackValidationError(f"schema: {label} is not UTF-8 JSON") from exc


def _snapshot_head(snapshot: Mapping[str, str]) -> str:
    digest = hashlib.sha256(_json_bytes(dict(sorted(snapshot.items())))).hexdigest()
    return f"sha256:{digest}"


def _normal_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PackValidationError("path: object path is not canonical")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise PackValidationError("path: object path is not canonical")
    if path.suffix.lower() != ".json":
        raise PackValidationError("path: canonical package objects must be JSON")
    return value


def _regular_file(root: Path, relative: str) -> Path:
    path = root.joinpath(*PurePosixPath(relative).parts)
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise PackValidationError("path: symlinked package objects are forbidden")
    if not path.is_file():
        raise PackValidationError("path: package object is missing")
    return path


def _validate_object(relative: str, value: Any, *, scope: str) -> Any:
    if not relative.startswith(f"projects/{scope}/"):
        raise PackValidationError("scope: object path crosses package scope")
    if isinstance(value, Mapping) and "record_type" in value:
        try:
            record = validate_record(value)
        except RecordValidationError as exc:
            reason = "privacy" if "private" in str(exc).lower() or "secret" in str(exc).lower() else "schema"
            raise PackValidationError(f"{reason}: typed object is invalid") from exc
        if record["project_id"] != scope:
            raise PackValidationError("scope: object crosses package scope")
        record_type = record["record_type"]
        if record_type == "task.state":
            expected_path = f"projects/{scope}/tasks/{record['stable_id']}/state.json"
        elif record_type == "task.evidence":
            expected_path = (
                f"projects/{scope}/tasks/{record['task_id']}/evidence/"
                f"{record['stable_id']}.json"
            )
        elif record_type == "knowledge.fact":
            expected_path = (
                f"projects/{scope}/knowledge/topics/{record['topic_slug']}/facts/"
                f"{record['fact_key']}/{record['stable_id']}.json"
            )
        elif record_type == "session.history":
            expected_path = (
                f"projects/{scope}/sessions/{record['session_id']}/history/"
                f"{record['archive_id']}/record.json"
            )
        else:
            expected_path = None
        if expected_path is not None and relative != expected_path:
            raise PackValidationError("path: typed object path does not match identity")
        return record
    if _MESSAGES_PATH.fullmatch(relative):
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            raise PackValidationError("schema: archive messages must be a JSON array")
        return copy.deepcopy(value)
    if _EVENT_PATH.fullmatch(relative):
        required = {
            "event_id",
            "event_type",
            "archive_id",
            "session_id",
            "project_id",
            "idempotency_key",
            "canonical_head",
            "occurred_at",
        }
        if not isinstance(value, Mapping) or not required <= set(value):
            raise PackValidationError("schema: archive event is incomplete")
        if value.get("project_id") != scope:
            raise PackValidationError("scope: archive event crosses package scope")
        return copy.deepcopy(dict(value))
    raise PackValidationError("schema: unsupported canonical JSON object")


def _safe_object_bytes(relative: str, content: bytes, *, scope: str) -> bytes:
    value = _read_json_bytes(content, label=relative)
    validated = _validate_object(relative, value, scope=scope)
    if contains_private(validated):
        raise PackValidationError("privacy: package object contains credential material")
    if isinstance(validated, Mapping) and "record_type" in validated:
        return canonical_bytes(validated) + b"\n"
    return _json_bytes(validated) + b"\n"


def _manifest_schema(value: Any) -> dict[str, Any]:
    required = {
        "format",
        "schema_version",
        "scope",
        "created_at",
        "atomicity_claim",
        "canonical_head",
        "objects",
        "metadata",
    }
    if not isinstance(value, Mapping) or not required <= set(value):
        raise PackValidationError("schema: manifest fields are incomplete")
    manifest = copy.deepcopy(dict(value))
    if manifest["format"] != "ovpack":
        raise PackValidationError("schema: format must be ovpack")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise PackValidationError("schema: schema_version must be 1")
    if not isinstance(manifest["scope"], str) or _SCOPE.fullmatch(manifest["scope"]) is None:
        raise PackValidationError("schema: scope is not canonical")
    if not isinstance(manifest["created_at"], str) or not manifest["created_at"]:
        raise PackValidationError("schema: created_at must be a non-empty string")
    if manifest["atomicity_claim"] is not False:
        raise PackValidationError("schema: atomicity_claim must be false")
    if not isinstance(manifest["canonical_head"], str) or _SHA256.fullmatch(
        manifest["canonical_head"]
    ) is None:
        raise PackValidationError("schema: canonical_head must be sha256")
    if not isinstance(manifest["metadata"], Mapping):
        raise PackValidationError("schema: metadata must be an object")
    objects = manifest["objects"]
    if not isinstance(objects, Sequence) or isinstance(objects, (str, bytes)) or not objects:
        raise PackValidationError("schema: objects must be a non-empty array")
    for item in objects:
        if not isinstance(item, Mapping) or not {"path", "sha256", "size"} <= set(item):
            raise PackValidationError("schema: object entries are incomplete")
        if not isinstance(item["sha256"], str) or _SHA256.fullmatch(item["sha256"]) is None:
            raise PackValidationError("schema: object sha256 is invalid")
        if type(item["size"]) is not int or item["size"] < 0:
            raise PackValidationError("schema: object size is invalid")
    return manifest


def _inspect_pack(pack_root: Path, expected_scope: str) -> tuple[dict, dict[str, bytes]]:
    root = Path(pack_root)
    if root.is_symlink() or not root.is_dir():
        raise PackValidationError("path: pack root must be a directory")
    manifest_path = root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise PackValidationError("schema: manifest.json is missing")
    manifest = _manifest_schema(_read_json_bytes(manifest_path.read_bytes(), label="manifest"))

    if manifest["scope"] != expected_scope:
        raise PackValidationError("scope: manifest does not match expected scope")

    relative_paths = [_normal_path(item["path"]) for item in manifest["objects"]]
    if len(relative_paths) != len(set(relative_paths)):
        raise PackValidationError("path: duplicate object path")
    object_root = root / "objects"
    if object_root.is_symlink() or not object_root.is_dir():
        raise PackValidationError("path: objects directory is missing")
    expected_files = {"objects/" + relative for relative in relative_paths}
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if actual_files != expected_files:
        raise PackValidationError("path: package has missing or unlisted objects")

    staged: dict[str, bytes] = {}
    snapshot: dict[str, str] = {}
    for item, relative in zip(manifest["objects"], relative_paths, strict=True):
        content = _regular_file(object_root, relative).read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if len(content) != item["size"] or f"sha256:{digest}" != item["sha256"]:
            raise PackValidationError("checksum: package object does not match manifest")
        staged[relative] = content
        snapshot[relative] = digest
    if _snapshot_head(snapshot) != manifest["canonical_head"]:
        raise PackValidationError("checksum: canonical head does not match objects")

    if contains_private(manifest):
        raise PackValidationError("privacy: manifest contains credential material")
    for relative, content in staged.items():
        value = _read_json_bytes(content, label=relative)
        validated = _validate_object(relative, value, scope=manifest["scope"])
        if contains_private(validated):
            raise PackValidationError("privacy: package object contains credential material")
    return manifest, staged


def validate_pack(*, pack_root: Path, expected_scope: str) -> dict:
    """Validate the complete package without writing to any restore target."""

    manifest, _ = _inspect_pack(Path(pack_root), expected_scope)
    return manifest


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _overlap(first: Path, second: Path) -> bool:
    a = first.resolve()
    b = second.resolve()
    return a == b or a in b.parents or b in a.parents


def build_pack(
    *,
    source_root: Path,
    pack_root: Path,
    scope: str,
    metadata: Mapping[str, Any] | None = None,
    object_order: Sequence[str] | None = None,
) -> dict:
    """Build a deterministic object package from validated canonical JSON."""

    source = Path(source_root)
    destination = Path(pack_root)
    if _SCOPE.fullmatch(scope) is None:
        raise PackValidationError("scope: package scope is not canonical")
    if source.is_symlink() or not source.is_dir():
        raise PackValidationError("path: source root must be a directory")
    if _overlap(source, destination):
        raise PackValidationError("path: source and package roots must be disjoint")
    if destination.exists():
        raise PackValidationError("path: pack root already exists")
    if metadata is not None and not isinstance(metadata, Mapping):
        raise PackValidationError("schema: metadata must be an object")
    safe_metadata = copy.deepcopy(dict(metadata or {}))
    if contains_private(safe_metadata):
        raise PackValidationError("privacy: manifest metadata contains credential material")

    source_files = [path for path in sorted(source.rglob("*")) if path.is_file()]
    if not source_files:
        raise PackValidationError("schema: canonical source is empty")
    prepared: dict[str, bytes] = {}
    for path in source_files:
        relative = _normal_path(path.relative_to(source).as_posix())
        if path.is_symlink():
            raise PackValidationError("path: symlinked canonical objects are forbidden")
        if contains_private(relative):
            raise PackValidationError("privacy: canonical object path contains credential material")
        prepared[relative] = _safe_object_bytes(relative, path.read_bytes(), scope=scope)

    paths = sorted(prepared)
    if object_order is not None:
        requested = list(object_order)
        if len(requested) != len(set(requested)) or set(requested) != set(paths):
            raise PackValidationError("path: object_order must be an exact permutation")
        paths = requested
    snapshot = {
        relative: hashlib.sha256(prepared[relative]).hexdigest()
        for relative in sorted(prepared)
    }
    objects = [
        {
            "path": relative,
            "sha256": f"sha256:{snapshot[relative]}",
            "size": len(prepared[relative]),
        }
        for relative in paths
    ]
    manifest = {
        "format": "ovpack",
        "schema_version": 1,
        "scope": scope,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "atomicity_claim": False,
        "canonical_head": _snapshot_head(snapshot),
        "objects": objects,
        "metadata": safe_metadata,
    }

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        for relative in paths:
            _write_bytes(staging / "objects" / relative, prepared[relative])
        _write_bytes(staging / "manifest.json", _json_bytes(manifest) + b"\n")
        _fsync_dir(staging)
        os.replace(staging, destination)
        _fsync_dir(destination.parent)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return manifest


def restore_pack(
    *,
    pack_root: Path,
    target_root: Path,
    expected_scope: str,
    mode: str = "fail",
) -> dict:
    """Validate fully, then publish a staged canonical tree."""

    if mode not in {"fail", "replace"}:
        raise PackValidationError("schema: restore mode must be fail or replace")
    pack = Path(pack_root)
    target = Path(target_root)
    if _overlap(pack, target):
        raise PackValidationError("path: pack and target roots must be disjoint")
    manifest, staged = _inspect_pack(pack, expected_scope)
    if target.exists() and mode == "fail":
        raise PackValidationError("path: target already exists")
    if target.exists() and not target.is_dir():
        raise PackValidationError("path: target must be a directory")

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    backup: Path | None = None
    try:
        for relative, content in staged.items():
            _write_bytes(temporary / relative, content)
        _fsync_dir(temporary)
        if target.exists():
            backup = target.with_name(f".{target.name}.{uuid.uuid4().hex}.backup")
            os.replace(target, backup)
        try:
            os.replace(temporary, target)
        except Exception:
            if backup is not None and backup.exists() and not target.exists():
                os.replace(backup, target)
            raise
        _fsync_dir(target.parent)
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        **manifest,
        "canonical_head": manifest["canonical_head"],
        "object_count": len(staged),
    }

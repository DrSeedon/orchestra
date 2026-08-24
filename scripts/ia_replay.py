"""Deterministic canonical replay and head-guarded OVPack rollback."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.ia.projections import SQLiteProjectionBackend
from app.ia.recovery import contains_private
from app.ia.schema import projection_payload, validate_record_set
from scripts.ia_pack import (
    PackValidationError,
    _normal_path,
    _snapshot_head,
    _validate_object,
    restore_pack,
    validate_pack,
)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackValidationError("schema: canonical object is not UTF-8 JSON") from exc


def _canonical_inventory(root: Path) -> tuple[str, list[dict], int]:
    if root.is_symlink() or not root.is_dir():
        raise PackValidationError("path: canonical root must be a directory")
    files = [path for path in sorted(root.rglob("*")) if path.is_file()]
    if not files:
        raise PackValidationError("schema: canonical root is empty")
    snapshot: dict[str, str] = {}
    records: list[dict] = []
    scope: str | None = None
    pending: list[tuple[str, Any]] = []
    for path in files:
        if path.is_symlink():
            raise PackValidationError("path: symlinked canonical objects are forbidden")
        relative = _normal_path(path.relative_to(root).as_posix())
        content = path.read_bytes()
        snapshot[relative] = hashlib.sha256(content).hexdigest()
        value = _read_json(path)
        if isinstance(value, Mapping) and "record_type" in value:
            project_id = value.get("project_id")
            if not isinstance(project_id, str) or not project_id:
                raise PackValidationError("scope: canonical record has no project scope")
            if scope is None:
                scope = project_id
            elif project_id != scope:
                raise PackValidationError("scope: canonical root crosses project scope")
        pending.append((relative, value))
    if scope is None:
        raise PackValidationError("schema: canonical root has no typed records")
    for relative, value in pending:
        validated = _validate_object(relative, value, scope=scope)
        if contains_private(validated):
            raise PackValidationError("privacy: canonical object contains credential material")
        if isinstance(validated, Mapping) and "record_type" in validated:
            records.append(copy.deepcopy(dict(validated)))
    return _snapshot_head(snapshot), list(validate_record_set(records)), len(files)


def _publish_projection(path: Path, records: list[dict], canonical_head: str) -> str:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        backend = SQLiteProjectionBackend(path=temporary)
        result = backend.replace_current(records=records, canonical_head=canonical_head)
        with sqlite3.connect(temporary) as connection:
            row = connection.execute(
                "SELECT projection_head FROM projection_meta WHERE singleton=1"
            ).fetchone()
        if row is None or row[0] != canonical_head or result.get("projection_head") != canonical_head:
            raise PackValidationError("checksum: projection head did not advance exactly")
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
        temporary.with_name(temporary.name + "-wal").unlink(missing_ok=True)
        temporary.with_name(temporary.name + "-shm").unlink(missing_ok=True)
    return canonical_head


def replay(
    *,
    canonical_root: Path,
    projection_path: Path,
    vector_query: Any = None,
) -> dict:
    """Rebuild SQLite/FTS and optional vector input from validated canonical state."""

    root = Path(canonical_root)
    projection = Path(projection_path)
    if projection.resolve() == root.resolve() or root.resolve() in projection.resolve().parents:
        raise PackValidationError("path: projection must be outside canonical root")
    canonical_head, records, object_count = _canonical_inventory(root)
    projected = [dict(projection_payload(record, "fts")) for record in records]
    projection_head = _publish_projection(projection, projected, canonical_head)

    indexed_head = None
    if vector_query is not None:
        vector_records = [dict(projection_payload(record, "vector")) for record in records]
        response = vector_query({
            "canonical_head": canonical_head,
            "projection_head": projection_head,
            "records": vector_records,
        })
        if isinstance(response, Mapping):
            candidate = response.get("indexed_head")
            if candidate is None or isinstance(candidate, str):
                indexed_head = candidate

    statuses = Counter(str(record["status"]) for record in records)
    retentions = Counter(str(record["retention"]) for record in records)
    return {
        "canonical_head": canonical_head,
        "projection_head": projection_head,
        "indexed_head": indexed_head,
        "object_count": object_count,
        "status_counts": dict(sorted(statuses.items())),
        "tombstone_count": sum(record["tombstone"] is True for record in records),
        "retention_counts": dict(sorted(retentions.items())),
    }


def rollback(
    *,
    pack_root: Path,
    target_root: Path,
    projection_path: Path,
    expected_scope: str,
    expected_current_head: str,
) -> dict:
    """Restore one validated pack only when the current canonical head is exact."""

    manifest = validate_pack(pack_root=Path(pack_root), expected_scope=expected_scope)
    target = Path(target_root)
    projection = Path(projection_path)
    if projection.resolve() == target.resolve() or target.resolve() in projection.resolve().parents:
        raise PackValidationError("path: projection must be outside canonical root")
    current_head, _, _ = _canonical_inventory(target)
    if current_head != expected_current_head:
        raise PackValidationError("head: current canonical head does not match expected head")
    restored = restore_pack(
        pack_root=Path(pack_root),
        target_root=target,
        expected_scope=expected_scope,
        mode="replace",
    )
    if restored["canonical_head"] != manifest["canonical_head"]:
        raise PackValidationError("checksum: restored head differs from validated pack")
    result = replay(
        canonical_root=target,
        projection_path=projection,
        vector_query=None,
    )
    return {"rollback_from_head": current_head, **result}

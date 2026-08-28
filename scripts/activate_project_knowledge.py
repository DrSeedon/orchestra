#!/usr/bin/env python3
"""Verify one distributed ledger and persist the project-local knowledge owner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ia.project_knowledge import KnowledgeOwnerError, ProjectKnowledgeRouter


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise KnowledgeOwnerError(f"cannot read activation JSON: {path}") from exc
    if not isinstance(value, dict):
        raise KnowledgeOwnerError(f"activation JSON is not an object: {path}")
    return value


def _head(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        raise KnowledgeOwnerError(f"project head is unavailable: {root}")
    return result.stdout.strip()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    published = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_canonical_bytes(receipt))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise KnowledgeOwnerError(f"activation receipt already exists: {path}") from exc
        published = True
        _fsync_directory(path.parent)
    except Exception:
        if published:
            path.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def _records_digest(root: Path, manifest: dict[str, Any]) -> str:
    rows = manifest.get("records")
    if not isinstance(rows, list):
        raise KnowledgeOwnerError(f"project manifest records are missing: {root}")
    expected_paths = set()
    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda item: str(item.get("stable_id") or "")):
        if not isinstance(row, dict):
            raise KnowledgeOwnerError(f"project manifest record is invalid: {root}")
        stable_id = str(row.get("stable_id") or "")
        try:
            if str(uuid.UUID(stable_id)) != stable_id:
                raise ValueError
        except ValueError as exc:
            raise KnowledgeOwnerError(f"project manifest stable_id is invalid: {root}") from exc
        relative = str(row.get("destination_relative_path") or "")
        expected_relative = f"docs/kb/records/evidence/{stable_id}.json"
        if relative != expected_relative:
            raise KnowledgeOwnerError(f"project record path identity mismatch: {relative}")
        path = root / relative
        try:
            path.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as exc:
            raise KnowledgeOwnerError(f"project record path is invalid: {path}") from exc
        payload = path.read_bytes()
        if len(payload) != row.get("size") or hashlib.sha256(payload).hexdigest() != row.get(
            "sha256"
        ):
            raise KnowledgeOwnerError(f"project record byte parity failed: {path}")
        try:
            record = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise KnowledgeOwnerError(f"project record JSON is invalid: {path}") from exc
        if (
            not isinstance(record, dict)
            or record.get("project_id") != manifest.get("project_id")
            or record.get("stable_id") != stable_id
        ):
            raise KnowledgeOwnerError(f"project record payload identity mismatch: {path}")
        expected_paths.add(path.resolve())
        digest.update(stable_id.encode())
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    actual_paths = {
        path.resolve()
        for path in (root / "docs/kb/records/evidence").glob("*.json")
        if path.is_file()
    }
    if actual_paths != expected_paths:
        raise KnowledgeOwnerError(f"project record set mismatch: {root}")
    return "sha256:" + digest.hexdigest()


def _verify_project(root: Path, project: dict[str, Any]) -> int:
    project_id = str(project.get("project_id") or "")
    local_manifest = _object(root / "docs/kb/manifest.json")
    if (
        local_manifest.get("project_id") != project_id
        or local_manifest.get("record_count") != project.get("record_count")
        or local_manifest.get("records_sha256") != project.get("records_sha256")
        or _records_digest(root, local_manifest) != project.get("records_sha256")
    ):
        raise KnowledgeOwnerError(f"distribution project parity failed: {project_id}")
    return int(project["record_count"])


def activate(
    *,
    distribution_manifest: Path,
    scope_registry_path: Path,
    engine_state_path: Path,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    manifest_path = Path(distribution_manifest).expanduser().resolve()
    manifest = _object(manifest_path)
    if manifest.get("status") != "verified" or manifest.get("quarantine_count") != 0:
        raise KnowledgeOwnerError("distribution manifest is not fully verified")
    projects = manifest.get("projects")
    if not isinstance(projects, list) or not projects:
        raise KnowledgeOwnerError("distribution project map is empty")
    registry = _object(Path(scope_registry_path).expanduser().resolve())
    entries = registry.get("entries")
    if not isinstance(entries, list) or not entries:
        raise KnowledgeOwnerError("authoritative project map is empty")
    authoritative: dict[str, Path] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise KnowledgeOwnerError("authoritative project map row is invalid")
        project_id = str(entry.get("canonical_project_id") or "")
        root = Path(str(entry.get("repository_root") or "")).expanduser().resolve()
        if not project_id or project_id in authoritative or not root.is_dir():
            raise KnowledgeOwnerError(f"authoritative project map is invalid: {project_id}")
        authoritative[project_id] = root

    proposed = {
        str(project.get("project_id") or ""): Path(
            str(project.get("repository_root") or "")
        ).expanduser().resolve()
        for project in projects
        if isinstance(project, dict)
    }
    if proposed != authoritative or len(proposed) != len(projects):
        raise KnowledgeOwnerError("project map does not match authoritative scope registry")

    roots: dict[str, Path] = {}
    heads: dict[str, str] = {}
    total = 0
    for project in projects:
        if not isinstance(project, dict):
            raise KnowledgeOwnerError("distribution project row is invalid")
        project_id = str(project.get("project_id") or "")
        root = Path(str(project.get("repository_root") or "")).expanduser().resolve()
        if not project_id or project_id in roots or not root.is_dir():
            raise KnowledgeOwnerError(f"distribution project identity is invalid: {project_id}")
        roots[project_id] = root
        total += _verify_project(root, project)
        heads[project_id] = _head(root)
    if total != manifest.get("total_record_count"):
        raise KnowledgeOwnerError("distribution total count mismatch")

    def central_unavailable(project_id: str, stable_id: str):
        raise KnowledgeOwnerError(
            f"activation does not read central content: {project_id}/{stable_id}"
        )

    router = ProjectKnowledgeRouter(
        project_roots=roots,
        engine_state_path=engine_state_path,
        central_reader=central_unavailable,
    )
    normalized_heads = {project_id: heads[project_id] for project_id in sorted(heads)}
    predicted_state = {
        "schema_version": 1,
        "active_owner": "project-local",
        "project_heads": normalized_heads,
        "activation_id": hashlib.sha256(_canonical_bytes(normalized_heads)).hexdigest(),
    }
    receipt = {
        "schema_version": 1,
        "status": "activated",
        "active_owner": predicted_state["active_owner"],
        "activation_id": predicted_state["activation_id"],
        "project_count": len(roots),
        "record_count": total,
        "project_heads": normalized_heads,
        "engine_state_path": str(Path(engine_state_path).expanduser().absolute()),
        "engine_state_sha256": hashlib.sha256(_canonical_bytes(predicted_state)).hexdigest(),
        "distribution_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "scope_registry_sha256": hashlib.sha256(
            Path(scope_registry_path).expanduser().resolve().read_bytes()
        ).hexdigest(),
    }
    persisted_receipt = Path(receipt_path).expanduser().absolute() if receipt_path else None
    if persisted_receipt is not None:
        _write_receipt(persisted_receipt, receipt)
    try:
        for project in projects:
            project_id = str(project["project_id"])
            try:
                _verify_project(roots[project_id], project)
            except KnowledgeOwnerError as exc:
                raise KnowledgeOwnerError(
                    f"project ledger changed during activation: {project_id}: {exc}"
                ) from exc
        state = router.activate(normalized_heads)
    except Exception:
        if persisted_receipt is not None:
            persisted_receipt.unlink(missing_ok=True)
            _fsync_directory(persisted_receipt.parent)
        raise
    if state != predicted_state:
        raise KnowledgeOwnerError("persisted owner state differs from activation receipt")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--distribution-manifest", type=Path, required=True)
    parser.add_argument("--scope-registry", type=Path, required=True)
    parser.add_argument("--engine-state", type=Path, required=True)
    parser.add_argument("--receipt-path", type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = activate(
            distribution_manifest=args.distribution_manifest,
            scope_registry_path=args.scope_registry,
            engine_state_path=args.engine_state,
            receipt_path=args.receipt_path,
        )
        payload = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        print(payload, end="")
        return 0
    except (KnowledgeOwnerError, OSError, ValueError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

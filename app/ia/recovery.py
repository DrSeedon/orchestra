"""Crash-safe session archives and background extraction coordination."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from app.ia.namespace import build_uri
from app.ia.schema import validate_record


class ArchiveConflictError(RuntimeError):
    """Raised when an idempotent archive key names different immutable content."""


_REDACTION_MARKER = "[REDACTED:T5]"
_SECRET_KEY_PARTS = {"password", "passwd", "secret", "token", "credential"}
_SECRET_KEY_NAMES = {
    "api_key",
    "apikey",
    "access_key",
    "secret_key",
    "private_key",
    "authorization",
    "client_secret",
    "credential_material",
}
_SECRET_VALUE = re.compile(
    r"(?:Bearer\s+\S{20,}|sk-(?:or-v1-)?[A-Za-z0-9_-]{8,}|"
    r"gh[pousr]_[A-Za-z0-9]{8,}|ya29\.[A-Za-z0-9_-]{8,}|"
    r"AIza[A-Za-z0-9_-]{12,}|(?:^|_)(?:SECRET|PASSWORD|CREDENTIAL)(?:_|$)|"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|client[_-]?secret)="
    r"[^\s&]{4,})"
)
_PROJECT_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True, slots=True)
class _RecoveryContext:
    canonical_root: Path
    extraction_runner: Any
    knowledge_service: Any


_ACTIVE_RECOVERY: ContextVar[_RecoveryContext | None] = ContextVar(
    "active_recovery",
    default=None,
)
_EXTRACTIONS: dict[str, asyncio.Task | dict[str, Any]] = {}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _key_looks_secret(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    return normalized in _SECRET_KEY_NAMES or bool(
        set(normalized.split("_")) & _SECRET_KEY_PARTS
    )


def redact_private(value: Any) -> Any:
    """Return a detached value with nested credential material removed."""

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            if _SECRET_VALUE.search(key):
                key = "redacted_field"
            result[key] = (
                _REDACTION_MARKER if _key_looks_secret(key) else redact_private(child)
            )
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_private(item) for item in value]
    if isinstance(value, str) and value != _REDACTION_MARKER and _SECRET_VALUE.search(value):
        return _REDACTION_MARKER
    return copy.deepcopy(value)


def contains_private(value: Any) -> bool:
    """Return whether a value still contains non-redacted credential material."""

    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            if _SECRET_VALUE.search(key):
                return True
            if _key_looks_secret(key) and child != _REDACTION_MARKER:
                return True
            if contains_private(child):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(contains_private(item) for item in value)
    return (
        isinstance(value, str)
        and value != _REDACTION_MARKER
        and _SECRET_VALUE.search(value) is not None
    )


def _uuid(value: str, name: str) -> str:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as exc:
        raise ArchiveConflictError(f"{name} must be a UUID") from exc
    if str(parsed) != value:
        raise ArchiveConflictError(f"{name} must be a canonical UUID")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(_canonical_bytes(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveConflictError("existing archive is incomplete or invalid") from exc


def _archive_content_head(
    *,
    project_id: str,
    session_id: str,
    archive_id: str,
    idempotency_key: str,
    retention: str,
    messages: Sequence[Any],
) -> str:
    body = {
        "archive_id": archive_id,
        "idempotency_key": idempotency_key,
        "messages": list(messages),
        "project_id": project_id,
        "retention": retention,
        "session_id": session_id,
    }
    return f"sha256:{hashlib.sha256(_canonical_bytes(body)).hexdigest()}"


def _receipt(record: Mapping[str, Any], event: Mapping[str, Any], *, outcome: str) -> dict:
    archive_path = str(Path(record["canonical_path"]).parent.as_posix())
    state = _EXTRACTIONS.get(str(record["archive_id"]))
    if isinstance(state, Mapping):
        extraction_status = str(state.get("status") or "unknown")
    elif isinstance(state, asyncio.Task):
        extraction_status = "running" if not state.done() else "completed"
    else:
        extraction_status = "scheduled"
    return {
        "outcome": outcome,
        "archive_id": record["archive_id"],
        "event_id": event["event_id"],
        "canonical_head": record["canonical_head"],
        "archive_path": archive_path,
        "extraction_status": extraction_status,
    }


def _existing_archive(
    archive_dir: Path,
    *,
    project_id: str,
    session_id: str,
    archive_id: str,
    idempotency_key: str,
    retention: str,
    messages: Sequence[Any],
) -> dict:
    record = _read_json(archive_dir / "record.json")
    event_paths = list((archive_dir / "events").glob("*.json"))
    if not isinstance(record, Mapping) or len(event_paths) != 1:
        raise ArchiveConflictError("existing archive is incomplete or invalid")
    event = _read_json(event_paths[0])
    expected_head = _archive_content_head(
        project_id=project_id,
        session_id=session_id,
        archive_id=archive_id,
        idempotency_key=idempotency_key,
        retention=retention,
        messages=messages,
    )
    expected = {
        "project_id": project_id,
        "session_id": session_id,
        "archive_id": archive_id,
        "retention": retention,
        "canonical_head": expected_head,
    }
    if any(record.get(name) != value for name, value in expected.items()):
        raise ArchiveConflictError("archive id conflicts with immutable content")
    if not isinstance(event, Mapping) or event.get("idempotency_key") != idempotency_key:
        raise ArchiveConflictError("archive idempotency key conflicts with existing event")
    stored_messages = _read_json(archive_dir / "messages.json")
    if stored_messages != list(messages):
        raise ArchiveConflictError("archive messages conflict with immutable content")
    if any(contains_private(value) for value in (record, event, stored_messages)):
        raise ArchiveConflictError("existing archive violates the privacy boundary")
    validate_record(record)
    return _receipt(record, event, outcome="noop")


async def _run_extraction(runner: Any, receipt: Mapping[str, Any]) -> dict[str, Any]:
    status: dict[str, Any]
    try:
        result = runner(copy.deepcopy(dict(receipt)))
        if inspect.isawaitable(result):
            result = await result
    except asyncio.CancelledError:
        status = {
            "archive_id": receipt["archive_id"],
            "status": "cancelled",
            "error": "extraction cancelled",
        }
    except Exception as exc:
        safe_error = redact_private(f"{type(exc).__name__}: {exc}")
        status = {
            "archive_id": receipt["archive_id"],
            "status": "failed",
            "error": safe_error,
        }
    else:
        status = {
            "archive_id": receipt["archive_id"],
            "status": "completed",
            "result": redact_private(result),
        }
    _EXTRACTIONS[str(receipt["archive_id"])] = status
    return status


@contextmanager
def recovery_mode(
    *,
    canonical_root: Path,
    extraction_runner: Any,
    knowledge_service: Any,
) -> Iterator[None]:
    """Temporarily configure the canonical archive owner for the current context."""

    context = _RecoveryContext(
        canonical_root=Path(canonical_root),
        extraction_runner=extraction_runner,
        knowledge_service=knowledge_service,
    )
    token = _ACTIVE_RECOVERY.set(context)
    try:
        yield
    finally:
        _ACTIVE_RECOVERY.reset(token)


async def commit_archive(
    *,
    session: Any,
    project_id: str,
    archive_id: str,
    idempotency_key: str,
    retention: str,
) -> dict:
    """Commit one immutable archive before scheduling optional extraction."""

    context = _ACTIVE_RECOVERY.get()
    if context is None:
        raise ArchiveConflictError("recovery owner is not configured")
    if _PROJECT_ID.fullmatch(project_id) is None:
        raise ArchiveConflictError("project_id is not a canonical scope")
    session_id = _uuid(str(session.id), "session_id")
    archive_id = _uuid(archive_id, "archive_id")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise ArchiveConflictError("idempotency_key must be a non-empty string")
    if contains_private(idempotency_key):
        raise ArchiveConflictError("idempotency_key violates the privacy boundary")
    if not isinstance(retention, str) or not retention:
        raise ArchiveConflictError("retention must be a non-empty string")

    messages = redact_private(list(getattr(session, "_turn_logs", ())))
    relative = Path("projects") / project_id / "sessions" / session_id / "history" / archive_id
    archive_dir = context.canonical_root / relative
    if archive_dir.exists():
        return _existing_archive(
            archive_dir,
            project_id=project_id,
            session_id=session_id,
            archive_id=archive_id,
            idempotency_key=idempotency_key,
            retention=retention,
            messages=messages,
        )

    canonical_head = _archive_content_head(
        project_id=project_id,
        session_id=session_id,
        archive_id=archive_id,
        idempotency_key=idempotency_key,
        retention=retention,
        messages=messages,
    )
    now = datetime.now(timezone.utc).isoformat()
    uri = build_uri({
        "record_type": "session.history",
        "project_id": project_id,
        "session_id": session_id,
        "stable_id": archive_id,
    })
    record = validate_record({
        "record_type": "session.history",
        "schema_version": 1,
        "stable_id": archive_id,
        "uri": uri,
        "project_id": project_id,
        "created_at": now,
        "updated_at": now,
        "canonical_head": canonical_head,
        "projection_head": None,
        "indexed_head": None,
        "status": "historical",
        "private_fields": [],
        "tombstone": False,
        "retention": retention,
        "session_id": session_id,
        "archive_id": archive_id,
        "canonical_path": (relative / "messages.json").as_posix(),
        "source_log_ids": [
            int(message["id"])
            for message in messages
            if isinstance(message, Mapping) and type(message.get("id")) is int
        ],
        "summary_ref": uri,
        "metadata": {
            "idempotency_key": idempotency_key,
        },
    })
    event_id = str(uuid5(UUID(archive_id), idempotency_key))
    event = {
        "event_id": event_id,
        "event_type": "session.archive.committed",
        "archive_id": archive_id,
        "session_id": session_id,
        "project_id": project_id,
        "idempotency_key": idempotency_key,
        "canonical_head": canonical_head,
        "occurred_at": now,
    }

    archive_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{archive_id}.", dir=archive_dir.parent))
    try:
        _write_json(staging / "record.json", record)
        _write_json(staging / "messages.json", messages)
        _write_json(staging / "events" / f"{event_id}.json", event)
        _fsync_dir(staging / "events")
        _fsync_dir(staging)
        os.replace(staging, archive_dir)
        _fsync_dir(archive_dir.parent)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    receipt = _receipt(record, event, outcome="created")
    if context.extraction_runner is None:
        _EXTRACTIONS[archive_id] = {
            "archive_id": archive_id,
            "status": "completed",
            "result": None,
        }
    else:
        task = asyncio.create_task(_run_extraction(context.extraction_runner, receipt))
        _EXTRACTIONS[archive_id] = task
    return receipt


async def wait_extraction(archive_id: str) -> dict:
    """Wait for the one extraction scheduled by an archive commit."""

    state = _EXTRACTIONS.get(archive_id)
    if state is None:
        raise ArchiveConflictError("archive extraction is unknown")
    if isinstance(state, asyncio.Task):
        return await state
    return copy.deepcopy(dict(state))

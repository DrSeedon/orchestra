"""Durable, receipt-backed Telegram file delivery."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import stat
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app import db
from app.errtext import err_text
from app.tg_bridge import (
    _reserve_file_snapshot_slot,
    _submit_file_group_once,
    _submit_file_snapshot_once,
)
from app.upload_limits import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, PHOTO_EXTENSIONS

logger = logging.getLogger("orchestra.tg_file_deliveries")

SCHEMA_VERSION = 1
SPOOL_ROOT = Path(__file__).parent.parent / "data" / "tg-file-outbox"
MAX_PENDING_TOTAL = 256
MAX_PENDING_PER_CHAT = 64
RETRY_AFTER_SECONDS = 5
LEASE_SECONDS = 120
ADMISSION_ENABLED = os.getenv("TG_FILE_OUTBOX_ADMISSION", "1").strip().lower() not in {
    "0", "false", "no", "off",
}
SENT_SNAPSHOT_RETENTION_SECONDS = 86400
FAILED_SNAPSHOT_RETENTION_SECONDS = 604800
MAINTENANCE_INTERVAL_SECONDS = 21600

_MAX_FILE_BYTES = MAX_UPLOAD_BYTES
_ACTIVE_STATES = ("QUEUED", "SUBMITTING")
_MEDIA_GROUP_LIMIT = 10
_chat_runner_tasks: dict[int, asyncio.Task[None]] = {}
_maintenance_task: asyncio.Task[None] | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_event_id(value: str) -> str:
    return str(uuid.UUID(str(value)))


class BatchValidationError(ValueError):
    def __init__(self, invalid: list[dict[str, Any]]):
        self.invalid = invalid
        super().__init__("one or more batch paths are invalid")


def _ensure_spool() -> tuple[Path, Path, Path]:
    root = Path(SPOOL_ROOT)
    active = root / "active"
    temporary = root / "tmp"
    quarantine = root / "quarantine"
    for directory in (root, active, temporary, quarantine):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
    return active, temporary, quarantine


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _load_error(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {"message": str(value)}
    return decoded if isinstance(decoded, dict) else {"message": str(decoded)}


def _next_action(event_id: str, state: str) -> dict[str, Any]:
    if state not in {"SUBMITTING", "UNKNOWN"}:
        return {}
    return {
        "code": "CHECK_DELIVERY_STATUS",
        "tool": "file_delivery_status",
        "arguments": {"event_id": event_id},
        "retryable": False,
        "message": "Provider delivery may have occurred; check this event id and do not resend it.",
    }


def _row(event_id: str) -> sqlite3.Row | None:
    with db._conn() as connection:
        return connection.execute(
            "SELECT * FROM tg_file_deliveries WHERE event_id=?", (event_id,)
        ).fetchone()


def _aggregate_states(states: list[str]) -> str:
    if not states:
        return "UNKNOWN"
    if "UNKNOWN" in states:
        return "UNKNOWN"
    if "SUBMITTING" in states:
        return "SUBMITTING"
    if "FAILED_BEFORE_SUBMIT" in states:
        return "FAILED_BEFORE_SUBMIT"
    if "QUEUED" in states:
        return "QUEUED"
    return "SENT" if all(state == "SENT" for state in states) else "UNKNOWN"


def _target_resource(rows: list[sqlite3.Row]) -> dict[str, Any]:
    state = _aggregate_states([row["state"] for row in rows])
    message_ids = [
        row["message_id"] for row in rows if row["message_id"] is not None
    ]
    errors = [
        _load_error(row["error_json"]) for row in rows if row["error_json"]
    ]
    first = rows[0]
    return {
        "state": state,
        "chat_id": first["chat_id"],
        "thread_id": first["thread_id"],
        "message_id": message_ids[0] if message_ids else None,
        "message_ids": message_ids,
        "error": errors[0] if errors else None,
    }


def _resource(
    event_id: str, *, acceptance: str = "ALREADY_ACCEPTED",
) -> dict[str, Any] | None:
    with db._conn() as connection:
        parent = connection.execute(
            "SELECT * FROM tg_file_deliveries WHERE event_id=?", (event_id,)
        ).fetchone()
        if parent is None:
            return None
        batch_id = parent["batch_id"]
        if batch_id:
            parents = connection.execute(
                "SELECT * FROM tg_file_deliveries WHERE batch_id=? ORDER BY batch_index",
                (batch_id,),
            ).fetchall()
            event_ids = [row["event_id"] for row in parents]
            placeholders = ",".join("?" for _event_id in event_ids)
            targets = connection.execute(
                "SELECT t.* FROM tg_file_delivery_targets AS t "
                "JOIN tg_file_deliveries AS d ON d.event_id=t.event_id "
                f"WHERE t.event_id IN ({placeholders}) "
                "ORDER BY t.target_kind, d.batch_index",
                event_ids,
            ).fetchall()
        else:
            parents = [parent]
            targets = connection.execute(
                "SELECT * FROM tg_file_delivery_targets "
                "WHERE event_id=? ORDER BY target_kind",
                (event_id,),
            ).fetchall()
    targets_by_event: dict[str, list[sqlite3.Row]] = {}
    targets_by_kind: dict[str, list[sqlite3.Row]] = {}
    for row in targets:
        targets_by_event.setdefault(row["event_id"], []).append(row)
        targets_by_kind.setdefault(row["target_kind"], []).append(row)
    if batch_id:
        children = {
            kind: _target_resource(rows) for kind, rows in targets_by_kind.items()
        }
        primary = children.get("primary")
        state = primary["state"] if primary else "UNKNOWN"
        files = []
        for row in parents:
            file_children = {
                target["target_kind"]: _target_resource([target])
                for target in targets_by_event.get(row["event_id"], [])
            }
            file_primary = file_children.get("primary")
            files.append({
                "index": row["batch_index"],
                "event_id": row["event_id"],
                "original_name": row["original_name"],
                "kind": row["batch_kind"],
                "group": row["batch_group"],
                "delivery_state": (
                    file_primary["state"] if file_primary else "UNKNOWN"
                ),
                "children": file_children,
            })
        return {
            "ok": True,
            "acceptance": acceptance,
            "event_id": batch_id,
            "payload_hash": parent["payload_hash"],
            "accept_seq": parents[0]["accept_seq"],
            "delivery_state": state,
            "message_id": primary.get("message_id") if primary else None,
            "status_url": f"/api/tg/file-deliveries/{batch_id}",
            "children": children,
            "files": files,
            "next_action": _next_action(batch_id, state),
        }
    children = {
        row["target_kind"]: {
            "state": row["state"],
            "chat_id": row["chat_id"],
            "thread_id": row["thread_id"],
            "message_id": row["message_id"],
            "error": _load_error(row["error_json"]),
        }
        for row in targets
    }
    primary = children.get("primary")
    state = primary["state"] if primary else "UNKNOWN"
    return {
        "ok": True,
        "acceptance": acceptance,
        "event_id": parent["event_id"],
        "payload_hash": parent["payload_hash"],
        "accept_seq": parent["accept_seq"],
        "delivery_state": state,
        "message_id": primary.get("message_id") if primary else None,
        "status_url": f"/api/tg/file-deliveries/{parent['event_id']}",
        "children": children,
        "next_action": _next_action(parent["event_id"], state),
    }


def get_file_delivery(event_id: str, source_session_id: str) -> dict[str, Any] | None:
    event_id = _validate_event_id(event_id)
    with db._conn() as connection:
        owned = connection.execute(
            "SELECT 1 FROM tg_file_deliveries WHERE event_id=? AND source_session_id=?",
            (event_id, source_session_id),
        ).fetchone()
    return _resource(event_id) if owned else None


def _error(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    outcome_unknown: bool = False,
    retry_after_seconds: int | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "retryable": retryable,
        "outcome_unknown": outcome_unknown,
    }
    if retry_after_seconds is not None:
        error["retry_after_seconds"] = retry_after_seconds
    return {"ok": False, "error": error}


def _outbound_caption(caption: str, sender: str, original_name: str) -> str:
    return (
        f"📎 {sender}: {caption}" if caption else f"📎 {sender}: {original_name}"
    )[:1024]


def _payload_hash(
    *,
    content_sha256: str,
    size_bytes: int,
    original_name: str,
    outbound_caption: str,
    source_scope: str,
    source_name: str,
    as_document: bool,
    targets: list[dict[str, Any]],
) -> str:
    canonical_targets = sorted(
        ({
            "target_kind": target["target_kind"],
            "chat_id": target["chat_id"],
            "thread_id": target.get("thread_id"),
        }
        for target in targets),
        key=lambda target: (
            target["target_kind"], target["chat_id"], target["thread_id"] or 0
        ),
    )
    payload = {
        "protocol": "tg-file/v1",
        "content_sha256": content_sha256,
        "size_bytes": size_bytes,
        "original_name": original_name,
        "outbound_caption": outbound_caption,
        "source_scope": source_scope,
        "source_name": source_name,
        "as_document": bool(as_document),
        "targets": canonical_targets,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _batch_kind(path: str, as_document: bool) -> str:
    if as_document:
        return "document"
    return "photo" if Path(path).suffix.lower() in PHOTO_EXTENSIONS else "document"


def _plan_batch(prepared: list[dict[str, Any]], as_document: bool) -> None:
    buckets: dict[str, list[dict[str, Any]]] = {}
    kind_order: list[str] = []
    for index, item in enumerate(prepared):
        kind = _batch_kind(item["original_name"], as_document)
        item["batch_index"] = index
        item["batch_kind"] = kind
        if kind not in buckets:
            buckets[kind] = []
            kind_order.append(kind)
        buckets[kind].append(item)
    group_index = 0
    for kind in kind_order:
        items = buckets[kind]
        for offset in range(0, len(items), _MEDIA_GROUP_LIMIT):
            for item in items[offset:offset + _MEDIA_GROUP_LIMIT]:
                item["batch_group"] = group_index
            group_index += 1


def _batch_payload_hash(
    *,
    prepared: list[dict[str, Any]],
    caption: str,
    source_scope: str,
    source_name: str,
    as_document: bool,
    targets: list[dict[str, Any]],
) -> str:
    canonical_targets = sorted(
        ({
            "target_kind": target["target_kind"],
            "chat_id": target["chat_id"],
            "thread_id": target.get("thread_id"),
        } for target in targets),
        key=lambda target: (
            target["target_kind"], target["chat_id"], target["thread_id"] or 0,
        ),
    )
    payload = {
        "protocol": "tg-file-batch/v1",
        "caption": caption,
        "source_scope": source_scope,
        "source_name": source_name,
        "as_document": bool(as_document),
        "targets": canonical_targets,
        "files": [{
            "content_sha256": item["content_sha256"],
            "size_bytes": item["size_bytes"],
            "original_name": item["original_name"],
            "kind": item["batch_kind"],
            "group": item["batch_group"],
        } for item in prepared],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _batch_child_id(batch_id: str, index: int) -> str:
    if index == 0:
        return batch_id
    return str(uuid.uuid5(uuid.UUID(batch_id), f"tg-file-batch:{index}"))


def _snapshot_to_temp(source_path: str, event_id: str) -> dict[str, Any]:
    _active, temporary, _quarantine = _ensure_spool()
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    source_fd = os.open(source_path, flags)
    temp_fd = -1
    temp_path = ""
    try:
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode):
            raise ValueError("source is not a regular file")
        temp_fd, temp_path = tempfile.mkstemp(prefix=f"{event_id}.", dir=temporary)
        os.fchmod(temp_fd, 0o600)
        digest = hashlib.sha256()
        size_bytes = 0
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            size_bytes += len(chunk)
            if size_bytes > _MAX_FILE_BYTES:
                raise ValueError(f"file too large (max {MAX_UPLOAD_MB} MB)")
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(temp_fd, view)
                view = view[written:]
        if size_bytes == 0:
            raise ValueError("file is empty (0 bytes)")
        os.fsync(temp_fd)
        return {
            "temp_path": temp_path,
            "size_bytes": size_bytes,
            "content_sha256": digest.hexdigest(),
            "original_name": Path(source_path).name,
        }
    except BaseException:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
        raise
    finally:
        os.close(source_fd)
        if temp_fd >= 0:
            os.close(temp_fd)


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _publish_temp(temp_path: str, event_id: str, original_name: str) -> tuple[str, bool]:
    active, _temporary, _quarantine = _ensure_spool()
    event_dir = active / event_id
    event_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(event_dir, 0o700)
    _fsync_directory(active)
    destination = event_dir / original_name
    try:
        os.link(temp_path, destination)
        created = True
    except FileExistsError:
        created = False
    if created:
        os.chmod(destination, 0o600)
        _fsync_directory(event_dir)
    return str(destination), created


def _cleanup_temp(prepared: dict[str, Any] | None) -> None:
    if prepared:
        Path(prepared["temp_path"]).unlink(missing_ok=True)


def _same_payload_response(
    event_id: str,
    payload_hash: str,
    source_session_id: str | None,
) -> tuple[dict[str, Any], int]:
    existing = _row(event_id)
    if existing is None:
        raise RuntimeError("accepted TG file receipt disappeared")
    if (
        source_session_id is not None
        and existing["source_session_id"] != source_session_id
    ):
        return _error(
            "KEYED_AUTH_REQUIRED",
            "event id belongs to another MCP principal",
        ), 403
    if existing["payload_hash"] != payload_hash:
        return _error(
            "IDEMPOTENCY_CONFLICT",
            "event id is already bound to another file payload",
        ), 409
    resource = _resource(event_id, acceptance="ALREADY_ACCEPTED")
    if resource is None:
        raise RuntimeError("accepted TG file receipt disappeared")
    return resource, 202


def _commit_acceptance(
    *,
    event_id: str,
    prepared: dict[str, Any],
    source_session_id: str | None,
    source_name: str,
    source_scope: str,
    source_path: str,
    caption: str,
    outbound_caption: str,
    as_document: bool,
    payload_hash: str,
    orch_name: str | None,
    targets: list[dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    connection = db._conn()
    published_path = ""
    published_here = False
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT * FROM tg_file_deliveries WHERE event_id=?", (event_id,)
        ).fetchone()
        if existing is not None:
            connection.rollback()
            return _same_payload_response(event_id, payload_hash, source_session_id)

        active_total = connection.execute(
            "SELECT count(*) FROM tg_file_delivery_targets "
            "WHERE state IN ('QUEUED','SUBMITTING')"
        ).fetchone()[0]
        additions_by_chat: dict[int, int] = {}
        for target in targets:
            chat_id = int(target["chat_id"])
            additions_by_chat[chat_id] = additions_by_chat.get(chat_id, 0) + 1
        queue_full = active_total + len(targets) > MAX_PENDING_TOTAL
        if not queue_full:
            for chat_id, additions in additions_by_chat.items():
                active_chat = connection.execute(
                    "SELECT count(*) FROM tg_file_delivery_targets "
                    "WHERE chat_id=? AND state IN ('QUEUED','SUBMITTING')",
                    (chat_id,),
                ).fetchone()[0]
                if active_chat + additions > MAX_PENDING_PER_CHAT:
                    queue_full = True
                    break
        if queue_full:
            connection.rollback()
            return _error(
                "TG_FILE_QUEUE_FULL",
                "durable Telegram file queue is full",
                retryable=True,
                retry_after_seconds=RETRY_AFTER_SECONDS,
            ), 429

        published_path, published_here = _publish_temp(
            prepared["temp_path"], event_id, prepared["original_name"]
        )
        if not published_here:
            existing_size, existing_hash = _hash_file(Path(published_path))
            if (
                existing_size != prepared["size_bytes"]
                or existing_hash != prepared["content_sha256"]
            ):
                raise RuntimeError("unattributed event snapshot conflicts with this payload")

        now = _now()
        cursor = connection.execute(
            """INSERT INTO tg_file_deliveries (
                event_id, schema_version, source_session_id, source_name, source_scope,
                source_path, original_name, snapshot_path, size_bytes, content_sha256,
                caption, outbound_caption, as_document, payload_hash, orch_name,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id, SCHEMA_VERSION, source_session_id, source_name, source_scope,
                source_path, prepared["original_name"], published_path,
                prepared["size_bytes"], prepared["content_sha256"], caption,
                outbound_caption, int(as_document), payload_hash, orch_name, now, now,
            ),
        )
        for target in targets:
            connection.execute(
                """INSERT INTO tg_file_delivery_targets (
                    event_id, target_kind, chat_id, thread_id, state, updated_at
                ) VALUES (?, ?, ?, ?, 'QUEUED', ?)""",
                (
                    event_id, target["target_kind"], target["chat_id"],
                    target.get("thread_id"), now,
                ),
            )
        connection.commit()
        resource = _resource(event_id, acceptance="ACCEPTED")
        if resource is None:
            raise RuntimeError("committed TG file receipt disappeared")
        resource["accept_seq"] = cursor.lastrowid
        return resource, 202
    except BaseException:
        try:
            connection.rollback()
        except sqlite3.Error:
            pass
        committed = _row(event_id)
        if (
            committed is not None
            and committed["payload_hash"] == payload_hash
            and (
                source_session_id is None
                or committed["source_session_id"] == source_session_id
            )
        ):
            resource = _resource(event_id, acceptance="ALREADY_ACCEPTED")
            if resource is not None:
                return resource, 202
        if published_here and published_path:
            Path(published_path).unlink(missing_ok=True)
        raise
    finally:
        connection.close()


def _retry_failed(
    event_id: str,
    payload_hash: str,
    prepared: dict[str, Any],
    source_session_id: str | None,
) -> tuple[dict[str, Any], int]:
    connection = db._conn()
    published_path = ""
    published_here = False
    try:
        connection.execute("BEGIN IMMEDIATE")
        parent = connection.execute(
            "SELECT * FROM tg_file_deliveries WHERE event_id=?", (event_id,)
        ).fetchone()
        if parent is None:
            connection.rollback()
            raise RuntimeError("accepted TG file receipt disappeared")
        if (
            source_session_id is not None
            and parent["source_session_id"] != source_session_id
        ):
            connection.rollback()
            return _error(
                "KEYED_AUTH_REQUIRED",
                "event id belongs to another MCP principal",
            ), 403
        if parent["payload_hash"] != payload_hash:
            connection.rollback()
            return _same_payload_response(event_id, payload_hash, source_session_id)
        failed = connection.execute(
            "SELECT count(*) FROM tg_file_delivery_targets "
            "WHERE event_id=? AND state='FAILED_BEFORE_SUBMIT'",
            (event_id,),
        ).fetchone()[0]
        if not failed:
            connection.rollback()
            return _same_payload_response(event_id, payload_hash, source_session_id)

        snapshot = Path(parent["snapshot_path"]) if parent["snapshot_path"] else None
        if snapshot is None or not snapshot.is_file():
            published_path, published_here = _publish_temp(
                prepared["temp_path"], event_id, prepared["original_name"]
            )
            connection.execute(
                "UPDATE tg_file_deliveries SET snapshot_path=?, snapshot_deleted_at=NULL, "
                "quarantined_at=NULL, updated_at=? WHERE event_id=?",
                (published_path, _now(), event_id),
            )
        now = _now()
        connection.execute(
            "UPDATE tg_file_delivery_targets SET state='QUEUED', error_json=NULL, "
            "submitted_at=NULL, updated_at=? "
            "WHERE event_id=? AND state='FAILED_BEFORE_SUBMIT'",
            (now, event_id),
        )
        connection.commit()
        resource = _resource(event_id, acceptance="ALREADY_ACCEPTED")
        if resource is None:
            raise RuntimeError("accepted TG file receipt disappeared")
        return resource, 202
    except BaseException:
        try:
            connection.rollback()
        except sqlite3.Error:
            pass
        if published_here and published_path and _row(event_id) is None:
            Path(published_path).unlink(missing_ok=True)
        raise
    finally:
        connection.close()


async def _prepare_file_batch(
    source_paths: list[str], batch_id: str,
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for index, source_path in enumerate(source_paths):
        try:
            item = await asyncio.to_thread(
                _snapshot_to_temp, source_path, _batch_child_id(batch_id, index),
            )
        except (OSError, ValueError) as exc:
            invalid.append({
                "index": index,
                "path": source_path,
                "error": type(exc).__name__,
            })
        else:
            item["source_path"] = source_path
            prepared.append(item)
    if invalid:
        for item in prepared:
            _cleanup_temp(item)
        raise BatchValidationError(invalid)
    return prepared


def _same_batch_response(
    batch_id: str,
    payload_hash: str,
    source_session_id: str | None,
) -> tuple[dict[str, Any], int]:
    existing = _row(batch_id)
    if existing is None:
        raise RuntimeError("accepted TG file batch disappeared")
    if (
        source_session_id is not None
        and existing["source_session_id"] != source_session_id
    ):
        return _error(
            "KEYED_AUTH_REQUIRED",
            "event id belongs to another MCP principal",
        ), 403
    if existing["batch_id"] != batch_id or existing["payload_hash"] != payload_hash:
        return _error(
            "IDEMPOTENCY_CONFLICT",
            "event id is already bound to another file payload",
        ), 409
    resource = _resource(batch_id, acceptance="ALREADY_ACCEPTED")
    if resource is None:
        raise RuntimeError("accepted TG file batch receipt disappeared")
    return resource, 202


def _retry_failed_batch(
    batch_id: str,
    payload_hash: str,
    prepared: list[dict[str, Any]],
    source_session_id: str | None,
) -> tuple[dict[str, Any], int]:
    connection = db._conn()
    published: list[str] = []
    try:
        connection.execute("BEGIN IMMEDIATE")
        parents = connection.execute(
            "SELECT * FROM tg_file_deliveries WHERE batch_id=? ORDER BY batch_index",
            (batch_id,),
        ).fetchall()
        if not parents:
            connection.rollback()
            raise RuntimeError("accepted TG file batch disappeared")
        root = parents[0]
        if (
            source_session_id is not None
            and root["source_session_id"] != source_session_id
        ):
            connection.rollback()
            return _error(
                "KEYED_AUTH_REQUIRED",
                "event id belongs to another MCP principal",
            ), 403
        if root["payload_hash"] != payload_hash:
            connection.rollback()
            return _same_batch_response(batch_id, payload_hash, source_session_id)
        failed = connection.execute(
            "SELECT count(*) FROM tg_file_delivery_targets AS t "
            "JOIN tg_file_deliveries AS d ON d.event_id=t.event_id "
            "WHERE d.batch_id=? AND t.state='FAILED_BEFORE_SUBMIT'",
            (batch_id,),
        ).fetchone()[0]
        if not failed:
            connection.rollback()
            return _same_batch_response(batch_id, payload_hash, source_session_id)
        for parent, item in zip(parents, prepared, strict=True):
            snapshot = Path(parent["snapshot_path"]) if parent["snapshot_path"] else None
            if snapshot is not None and snapshot.is_file():
                continue
            published_path, published_here = _publish_temp(
                item["temp_path"], parent["event_id"], parent["original_name"],
            )
            if published_here:
                published.append(published_path)
            connection.execute(
                "UPDATE tg_file_deliveries SET snapshot_path=?, snapshot_deleted_at=NULL, "
                "quarantined_at=NULL, updated_at=? WHERE event_id=?",
                (published_path, _now(), parent["event_id"]),
            )
        now = _now()
        connection.execute(
            "UPDATE tg_file_delivery_targets SET state='QUEUED', error_json=NULL, "
            "submitted_at=NULL, updated_at=? WHERE state='FAILED_BEFORE_SUBMIT' "
            "AND event_id IN (SELECT event_id FROM tg_file_deliveries WHERE batch_id=?)",
            (now, batch_id),
        )
        connection.commit()
        resource = _resource(batch_id, acceptance="ALREADY_ACCEPTED")
        if resource is None:
            raise RuntimeError("accepted TG file batch receipt disappeared")
        return resource, 202
    except BaseException:
        connection.rollback()
        for path in published:
            Path(path).unlink(missing_ok=True)
        raise
    finally:
        connection.close()


def _commit_batch_acceptance(
    *,
    batch_id: str,
    prepared: list[dict[str, Any]],
    source_session_id: str | None,
    source_name: str,
    source_scope: str,
    caption: str,
    as_document: bool,
    payload_hash: str,
    orch_name: str | None,
    targets: list[dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    connection = db._conn()
    published: list[str] = []
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT * FROM tg_file_deliveries WHERE event_id=?", (batch_id,),
        ).fetchone()
        if existing is not None:
            connection.rollback()
            if existing["batch_id"] != batch_id:
                return _same_batch_response(
                    batch_id, payload_hash, source_session_id,
                )
            return _retry_failed_batch(
                batch_id, payload_hash, prepared, source_session_id,
            )
        additions = len(prepared) * len(targets)
        active_total = connection.execute(
            "SELECT count(*) FROM tg_file_delivery_targets "
            "WHERE state IN ('QUEUED','SUBMITTING')"
        ).fetchone()[0]
        additions_by_chat: dict[int, int] = {}
        for target in targets:
            chat_id = int(target["chat_id"])
            additions_by_chat[chat_id] = (
                additions_by_chat.get(chat_id, 0) + len(prepared)
            )
        queue_full = active_total + additions > MAX_PENDING_TOTAL
        if not queue_full:
            for chat_id, chat_additions in additions_by_chat.items():
                active_chat = connection.execute(
                    "SELECT count(*) FROM tg_file_delivery_targets "
                    "WHERE chat_id=? AND state IN ('QUEUED','SUBMITTING')",
                    (chat_id,),
                ).fetchone()[0]
                if active_chat + chat_additions > MAX_PENDING_PER_CHAT:
                    queue_full = True
                    break
        if queue_full:
            connection.rollback()
            return _error(
                "TG_FILE_QUEUE_FULL",
                "durable Telegram file queue is full",
                retryable=True,
                retry_after_seconds=RETRY_AFTER_SECONDS,
            ), 429

        outbound_caption = _outbound_caption(
            caption, source_name, prepared[0]["original_name"],
        )
        now = _now()
        for item in prepared:
            child_id = _batch_child_id(batch_id, item["batch_index"])
            published_path, published_here = _publish_temp(
                item["temp_path"], child_id, item["original_name"],
            )
            if not published_here:
                raise RuntimeError("batch snapshot already exists without a receipt")
            published.append(published_path)
            connection.execute(
                """INSERT INTO tg_file_deliveries (
                    event_id, schema_version, source_session_id, source_name,
                    source_scope, source_path, original_name, snapshot_path,
                    size_bytes, content_sha256, caption, outbound_caption,
                    as_document, payload_hash, orch_name, batch_id, batch_index,
                    batch_group, batch_kind, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    child_id, SCHEMA_VERSION, source_session_id, source_name,
                    source_scope, item["source_path"], item["original_name"],
                    published_path, item["size_bytes"], item["content_sha256"],
                    caption, outbound_caption if item["batch_index"] == 0 else "",
                    int(as_document), payload_hash, orch_name, batch_id,
                    item["batch_index"], item["batch_group"], item["batch_kind"],
                    now, now,
                ),
            )
            for target in targets:
                connection.execute(
                    """INSERT INTO tg_file_delivery_targets (
                        event_id, target_kind, chat_id, thread_id, state, updated_at
                    ) VALUES (?, ?, ?, ?, 'QUEUED', ?)""",
                    (
                        child_id, target["target_kind"], target["chat_id"],
                        target.get("thread_id"), now,
                    ),
                )
        connection.commit()
        resource = _resource(batch_id, acceptance="ACCEPTED")
        if resource is None:
            raise RuntimeError("committed TG file batch receipt disappeared")
        return resource, 202
    except BaseException:
        try:
            connection.rollback()
        except sqlite3.Error:
            pass
        existing = _row(batch_id)
        if (
            existing is not None
            and existing["batch_id"] == batch_id
            and existing["payload_hash"] == payload_hash
            and (
                source_session_id is None
                or existing["source_session_id"] == source_session_id
            )
        ):
            resource = _resource(batch_id, acceptance="ALREADY_ACCEPTED")
            if resource is not None:
                return resource, 202
        for path in published:
            Path(path).unlink(missing_ok=True)
        raise
    finally:
        connection.close()


async def accept_file_batch(
    *,
    event_id: str,
    source_session_id: str | None,
    source_name: str,
    source_scope: str,
    source_paths: list[str],
    caption: str,
    as_document: bool,
    orch_name: str | None,
    targets: list[dict[str, Any]],
) -> tuple[dict[str, Any], int, dict[str, str]]:
    """Atomically snapshot and accept one ordered multi-file Telegram delivery."""
    batch_id = _validate_event_id(event_id)
    if not source_paths:
        raise BatchValidationError([])
    if _row(batch_id) is None and not ADMISSION_ENABLED:
        return _error(
            "TG_FILE_OUTBOX_DISABLED",
            "durable Telegram file admission is disabled",
            retryable=True,
        ), 503, {}
    prepared = await _prepare_file_batch(source_paths, batch_id)
    try:
        _plan_batch(prepared, as_document)
        payload_hash = _batch_payload_hash(
            prepared=prepared,
            caption=caption,
            source_scope=source_scope,
            source_name=source_name,
            as_document=as_document,
            targets=targets,
        )
        result, status = _commit_batch_acceptance(
            batch_id=batch_id,
            prepared=prepared,
            source_session_id=source_session_id,
            source_name=source_name,
            source_scope=source_scope,
            caption=caption,
            as_document=as_document,
            payload_hash=payload_hash,
            orch_name=orch_name,
            targets=targets,
        )
    finally:
        for item in prepared:
            _cleanup_temp(item)
    if status == 202:
        for target in result.get("children", {}).values():
            if target.get("state") == "QUEUED":
                try:
                    ensure_chat_runner(int(target["chat_id"]))
                except Exception as exc:
                    logger.error(
                        "TG file batch runner wake failed for %s: %s: %s",
                        batch_id, type(exc).__name__, exc,
                    )
    headers = {"Retry-After": str(RETRY_AFTER_SECONDS)} if status == 429 else {}
    return result, status, headers


async def accept_file_delivery(
    *,
    event_id: str,
    source_session_id: str | None,
    source_name: str,
    source_scope: str,
    source_path: str,
    caption: str,
    as_document: bool,
    orch_name: str | None,
    targets: list[dict[str, Any]],
) -> tuple[dict[str, Any], int, dict[str, str]]:
    """Snapshot a file and commit its receipt before waking any provider runner."""
    event_id = _validate_event_id(event_id)
    existing = _row(event_id)
    if (
        existing is not None
        and source_session_id is not None
        and existing["source_session_id"] != source_session_id
    ):
        return _error(
            "KEYED_AUTH_REQUIRED",
            "event id belongs to another MCP principal",
        ), 403, {}
    source = Path(source_path)
    if existing is not None and not source.exists():
        resource = _resource(event_id, acceptance="ALREADY_ACCEPTED")
        if resource is None:
            raise RuntimeError("accepted TG file receipt disappeared")
        return resource, 202, {}
    if existing is None and not ADMISSION_ENABLED:
        return _error(
            "TG_FILE_OUTBOX_DISABLED",
            "durable Telegram file admission is disabled",
            retryable=True,
        ), 503, {}

    prepared: dict[str, Any] | None = None
    try:
        prepared = await asyncio.to_thread(_snapshot_to_temp, source_path, event_id)
        outbound_caption = _outbound_caption(
            caption, source_name, prepared["original_name"]
        )
        payload_hash = _payload_hash(
            content_sha256=prepared["content_sha256"],
            size_bytes=prepared["size_bytes"],
            original_name=prepared["original_name"],
            outbound_caption=outbound_caption,
            source_scope=source_scope,
            source_name=source_name,
            as_document=as_document,
            targets=targets,
        )
        if existing is not None:
            if existing["payload_hash"] != payload_hash:
                return _error(
                    "IDEMPOTENCY_CONFLICT",
                    "event id is already bound to another file payload",
                ), 409, {}
            result, status = _retry_failed(
                event_id, payload_hash, prepared, source_session_id
            )
        else:
            result, status = _commit_acceptance(
                event_id=event_id,
                prepared=prepared,
                source_session_id=source_session_id,
                source_name=source_name,
                source_scope=source_scope,
                source_path=source_path,
                caption=caption,
                outbound_caption=outbound_caption,
                as_document=as_document,
                payload_hash=payload_hash,
                orch_name=orch_name,
                targets=targets,
            )
    finally:
        _cleanup_temp(prepared)

    if status == 202:
        for target in result.get("children", {}).values():
            if target.get("state") == "QUEUED":
                try:
                    ensure_chat_runner(int(target["chat_id"]))
                except Exception as exc:
                    logger.error(
                        "TG file runner wake failed for %s: %s: %s",
                        event_id, type(exc).__name__, exc,
                    )
    headers = {"Retry-After": str(RETRY_AFTER_SECONDS)} if status == 429 else {}
    return result, status, headers


def _next_queued(chat_id: int) -> sqlite3.Row | None:
    with db._conn() as connection:
        return connection.execute(
            """SELECT t.*, d.snapshot_path, d.size_bytes, d.content_sha256,
                      d.outbound_caption, d.as_document, d.original_name, d.accept_seq,
                      d.batch_id, d.batch_index, d.batch_group, d.batch_kind
               FROM tg_file_delivery_targets AS t
               JOIN tg_file_deliveries AS d ON d.event_id=t.event_id
               WHERE t.chat_id=? AND t.state='QUEUED'
               ORDER BY d.accept_seq,
                        CASE t.target_kind WHEN 'primary' THEN 0 ELSE 1 END
               LIMIT 1""",
            (chat_id,),
        ).fetchone()


def _queued_batch_group(first: sqlite3.Row) -> list[sqlite3.Row]:
    if not first["batch_id"]:
        return [first]
    with db._conn() as connection:
        return connection.execute(
            """SELECT t.*, d.snapshot_path, d.size_bytes, d.content_sha256,
                      d.outbound_caption, d.as_document, d.original_name,
                      d.accept_seq, d.batch_id, d.batch_index, d.batch_group,
                      d.batch_kind
               FROM tg_file_delivery_targets AS t
               JOIN tg_file_deliveries AS d ON d.event_id=t.event_id
               WHERE t.chat_id=? AND t.target_kind=? AND t.state='QUEUED'
                 AND d.batch_id=? AND d.batch_group=?
               ORDER BY d.batch_index""",
            (
                first["chat_id"], first["target_kind"],
                first["batch_id"], first["batch_group"],
            ),
        ).fetchall()


async def _snapshot_failure(row: sqlite3.Row) -> dict[str, Any] | None:
    descriptor = -1
    try:
        path = Path(row["snapshot_path"])
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise ValueError("snapshot is not a regular file")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("snapshot is not private (mode 0600 required)")
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
            await asyncio.sleep(0)
        if size != row["size_bytes"] or digest.hexdigest() != row["content_sha256"]:
            raise ValueError("snapshot size or hash mismatch")
        if not row["chat_id"]:
            raise ValueError("snapshotted Telegram target is unavailable")
    except Exception as exc:
        return {
            "code": "FAILED_BEFORE_SUBMIT",
            "message": err_text(exc),
            "retryable": True,
            "outcome_unknown": False,
        }
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return None


def _acquire_chat_lease(chat_id: int) -> tuple[str, int] | None:
    owner_token = secrets.token_hex(16)
    now = _utcnow()
    expires_at = (now + timedelta(seconds=LEASE_SECONDS)).isoformat()
    connection = db._conn()
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT * FROM tg_file_chat_leases WHERE chat_id=?", (chat_id,)
        ).fetchone()
        if (
            current is not None
            and datetime.fromisoformat(current["lease_expires_at"]) > now
        ):
            connection.rollback()
            return None
        if current is not None:
            orphaned = [
                row[0] for row in connection.execute(
                    "SELECT event_id FROM tg_file_delivery_targets "
                    "WHERE chat_id=? AND state='SUBMITTING'",
                    (chat_id,),
                ).fetchall()
            ]
            if orphaned:
                error = json.dumps({
                    "code": "PROVIDER_OUTCOME_UNKNOWN",
                    "message": "durable chat lease expired after the provider boundary",
                    "retryable": False,
                    "outcome_unknown": True,
                })
                connection.execute(
                    "UPDATE tg_file_delivery_targets SET state='UNKNOWN', error_json=?, "
                    "updated_at=? WHERE chat_id=? AND state='SUBMITTING'",
                    (error, now.isoformat(), chat_id),
                )
                connection.executemany(
                    "UPDATE tg_file_deliveries SET updated_at=? WHERE event_id=?",
                    [(now.isoformat(), event_id) for event_id in orphaned],
                )
        generation = int(current["generation"]) + 1 if current is not None else 1
        connection.execute(
            """INSERT INTO tg_file_chat_leases (
                   chat_id, generation, owner_token, lease_expires_at, updated_at
               ) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET
                   generation=excluded.generation,
                   owner_token=excluded.owner_token,
                   lease_expires_at=excluded.lease_expires_at,
                   updated_at=excluded.updated_at""",
            (chat_id, generation, owner_token, expires_at, now.isoformat()),
        )
        connection.commit()
        return owner_token, generation
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _current_lease(
    connection: sqlite3.Connection,
    chat_id: int,
    owner_token: str,
    generation: int,
    *,
    require_unexpired: bool,
) -> bool:
    row = connection.execute(
        "SELECT owner_token, generation, lease_expires_at "
        "FROM tg_file_chat_leases WHERE chat_id=?",
        (chat_id,),
    ).fetchone()
    if (
        row is None
        or row["owner_token"] != owner_token
        or row["generation"] != generation
    ):
        return False
    return (
        not require_unexpired
        or datetime.fromisoformat(row["lease_expires_at"]) > _utcnow()
    )


def _mark_failed_before_submit(
    chat_id: int,
    owner_token: str,
    generation: int,
    event_id: str,
    target_kind: str,
    error: dict[str, Any],
) -> bool:
    connection = db._conn()
    try:
        connection.execute("BEGIN IMMEDIATE")
        if not _current_lease(
            connection, chat_id, owner_token, generation, require_unexpired=True
        ):
            connection.rollback()
            return False
        now = _utcnow()
        cursor = connection.execute(
            "UPDATE tg_file_delivery_targets SET state='FAILED_BEFORE_SUBMIT', "
            "error_json=?, lease_generation=?, updated_at=? "
            "WHERE event_id=? AND target_kind=? AND state='QUEUED'",
            (
                json.dumps(error, ensure_ascii=False), generation, now.isoformat(),
                event_id, target_kind,
            ),
        )
        connection.execute(
            "UPDATE tg_file_chat_leases SET lease_expires_at=?, updated_at=? "
            "WHERE chat_id=? AND owner_token=? AND generation=?",
            (
                (now + timedelta(seconds=LEASE_SECONDS)).isoformat(),
                now.isoformat(), chat_id, owner_token, generation,
            ),
        )
        if cursor.rowcount == 1:
            connection.execute(
                "UPDATE tg_file_deliveries SET updated_at=? WHERE event_id=?",
                (now.isoformat(), event_id),
            )
        connection.commit()
        return cursor.rowcount == 1
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _claim_group_submitting(
    chat_id: int,
    owner_token: str,
    generation: int,
    rows: list[sqlite3.Row],
) -> bool:
    connection = db._conn()
    try:
        connection.execute("BEGIN IMMEDIATE")
        if not _current_lease(
            connection, chat_id, owner_token, generation, require_unexpired=True,
        ):
            connection.rollback()
            return False
        now = _utcnow()
        for row in rows:
            cursor = connection.execute(
                "UPDATE tg_file_delivery_targets SET state='SUBMITTING', "
                "attempt_count=attempt_count+1, lease_generation=?, submitted_at=?, "
                "updated_at=? WHERE event_id=? AND target_kind=? AND state='QUEUED'",
                (
                    generation, now.isoformat(), now.isoformat(),
                    row["event_id"], row["target_kind"],
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return False
        connection.execute(
            "UPDATE tg_file_chat_leases SET lease_expires_at=?, updated_at=? "
            "WHERE chat_id=? AND owner_token=? AND generation=?",
            (
                (now + timedelta(seconds=LEASE_SECONDS)).isoformat(),
                now.isoformat(), chat_id, owner_token, generation,
            ),
        )
        connection.commit()
        return True
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _finish_target(
    chat_id: int,
    owner_token: str,
    generation: int,
    event_id: str,
    target_kind: str,
    *,
    state: str,
    message_id: int | None = None,
    error: dict[str, Any] | None = None,
) -> bool:
    now = _now()
    connection = db._conn()
    try:
        connection.execute("BEGIN IMMEDIATE")
        if not _current_lease(
            connection, chat_id, owner_token, generation, require_unexpired=False
        ):
            connection.rollback()
            return False
        cursor = connection.execute(
            "UPDATE tg_file_delivery_targets SET state=?, message_id=?, error_json=?, "
            "sent_at=?, updated_at=? "
            "WHERE event_id=? AND target_kind=? AND state='SUBMITTING' "
            "AND lease_generation=?",
            (
                state,
                message_id,
                json.dumps(error, ensure_ascii=False) if error else None,
                now if state == "SENT" else None,
                now,
                event_id,
                target_kind,
                generation,
            ),
        )
        if cursor.rowcount == 1:
            connection.execute(
                "UPDATE tg_file_deliveries SET updated_at=? WHERE event_id=?",
                (now, event_id),
            )
        connection.commit()
        return cursor.rowcount == 1
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _release_chat_lease(chat_id: int, owner_token: str, generation: int) -> None:
    now = _now()
    with db._conn() as connection:
        connection.execute(
            "UPDATE tg_file_chat_leases SET lease_expires_at=?, updated_at=? "
            "WHERE chat_id=? AND owner_token=? AND generation=?",
            (now, now, chat_id, owner_token, generation),
        )


async def run_chat_deliveries(chat_id: int) -> None:
    """Drain one chat in acceptance order through single or album provider seams."""
    lease = _acquire_chat_lease(chat_id)
    if lease is None:
        return
    owner_token, generation = lease
    try:
        while True:
            row = _next_queued(chat_id)
            if row is None:
                return
            rows = _queued_batch_group(row)
            ready = []
            for candidate in rows:
                failure = await _snapshot_failure(candidate)
                if failure is not None:
                    if not _mark_failed_before_submit(
                        chat_id, owner_token, generation,
                        candidate["event_id"], candidate["target_kind"], failure,
                    ):
                        return
                else:
                    ready.append(candidate)
            if not ready:
                continue
            failure = None
            try:
                reserved = await _reserve_file_snapshot_slot(chat_id)
            except Exception as exc:
                reserved = False
                failure = {
                    "code": "FAILED_BEFORE_SUBMIT",
                    "message": err_text(exc),
                    "retryable": True,
                    "outcome_unknown": False,
                }
            if not reserved and failure is None:
                failure = {
                    "code": "FAILED_BEFORE_SUBMIT",
                    "message": "Telegram rate slot is unavailable",
                    "retryable": True,
                    "outcome_unknown": False,
                }
            if failure is not None:
                for candidate in ready:
                    if not _mark_failed_before_submit(
                        chat_id, owner_token, generation,
                        candidate["event_id"], candidate["target_kind"], failure,
                    ):
                        return
                continue
            if not _claim_group_submitting(
                chat_id, owner_token, generation, ready,
            ):
                return
            try:
                if len(ready) == 1:
                    candidate = ready[0]
                    result = await _submit_file_snapshot_once(
                        candidate["chat_id"],
                        candidate["snapshot_path"],
                        candidate["outbound_caption"],
                        candidate["thread_id"],
                        is_photo=(
                            candidate["batch_kind"] == "photo"
                            if candidate["batch_id"]
                            else (
                                not bool(candidate["as_document"])
                                and Path(candidate["original_name"]).suffix.lower()
                                in PHOTO_EXTENSIONS
                            )
                        ),
                    )
                    results = [result]
                else:
                    results = await _submit_file_group_once(
                        ready[0]["chat_id"],
                        [{
                            "snapshot_path": candidate["snapshot_path"],
                            "original_name": candidate["original_name"],
                            "caption": candidate["outbound_caption"],
                            "kind": candidate["batch_kind"],
                        } for candidate in ready],
                        ready[0]["thread_id"],
                    )
                    if not isinstance(results, (list, tuple)):
                        raise ValueError("provider returned no media-group message list")
                if len(results) != len(ready):
                    raise ValueError("provider returned incomplete media-group receipts")
                message_ids = []
                for result in results:
                    message_id = getattr(result, "message_id", None)
                    if isinstance(message_id, bool) or not isinstance(message_id, int):
                        raise ValueError("provider returned no integer message_id")
                    message_ids.append(message_id)
            except BaseException as exc:
                for candidate in ready:
                    _finish_target(
                        chat_id,
                        owner_token,
                        generation,
                        candidate["event_id"],
                        candidate["target_kind"],
                        state="UNKNOWN",
                        error={
                            "code": "PROVIDER_OUTCOME_UNKNOWN",
                            "message": err_text(exc),
                            "retryable": False,
                            "outcome_unknown": True,
                        },
                    )
                if isinstance(exc, asyncio.CancelledError):
                    raise
            else:
                for candidate, message_id in zip(ready, message_ids, strict=True):
                    _finish_target(
                        chat_id, owner_token, generation,
                        candidate["event_id"], candidate["target_kind"],
                        state="SENT", message_id=message_id,
                    )
    finally:
        _release_chat_lease(chat_id, owner_token, generation)


def ensure_chat_runner(chat_id: int) -> asyncio.Task[None]:
    existing = _chat_runner_tasks.get(chat_id)
    if existing is not None and not existing.done():
        return existing
    task = asyncio.create_task(run_chat_deliveries(chat_id))
    _chat_runner_tasks[chat_id] = task

    def _discard(done: asyncio.Task[None]) -> None:
        if _chat_runner_tasks.get(chat_id) is done:
            _chat_runner_tasks.pop(chat_id, None)

    task.add_done_callback(_discard)
    return task


async def recover_file_deliveries() -> None:
    """Quarantine orphaned provider boundaries and wake only durable QUEUED rows."""
    error = json.dumps(
        {
            "code": "PROVIDER_OUTCOME_UNKNOWN",
            "message": "process ended after the provider boundary",
            "retryable": False,
            "outcome_unknown": True,
        }
    )
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        now = _now()
        connection.execute(
            "UPDATE tg_file_deliveries SET updated_at=? WHERE event_id IN ("
            "SELECT event_id FROM tg_file_delivery_targets WHERE state='SUBMITTING')",
            (now,),
        )
        connection.execute(
            "UPDATE tg_file_delivery_targets SET state='UNKNOWN', error_json=?, updated_at=? "
            "WHERE state='SUBMITTING'",
            (error, now),
        )
        chats = [
            row[0] for row in connection.execute(
                "SELECT DISTINCT chat_id FROM tg_file_delivery_targets "
                "WHERE state='QUEUED' ORDER BY chat_id"
            ).fetchall()
        ]
    for chat_id in chats:
        ensure_chat_runner(chat_id)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _spool_path(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    try:
        path.resolve(strict=False).relative_to(Path(SPOOL_ROOT).resolve())
    except ValueError:
        logger.error("TG file cleanup refused path outside spool: %s", path)
        return None
    return path


def _set_snapshot_deleted(event_id: str, snapshot_path: str, deleted_at: str) -> None:
    with db._conn() as connection:
        connection.execute(
            "UPDATE tg_file_deliveries SET snapshot_path='', snapshot_deleted_at=?, "
            "updated_at=? WHERE event_id=? AND snapshot_path=?",
            (deleted_at, deleted_at, event_id, snapshot_path),
        )


def _delete_snapshot(parent: sqlite3.Row, deleted_at: str) -> None:
    raw_path = str(parent["snapshot_path"] or "")
    path = _spool_path(raw_path)
    if path is None:
        return
    path.unlink(missing_ok=True)
    _set_snapshot_deleted(parent["event_id"], raw_path, deleted_at)


def _quarantine_snapshot(parent: sqlite3.Row, quarantined_at: str) -> None:
    raw_path = str(parent["snapshot_path"] or "")
    source = _spool_path(raw_path)
    if source is None:
        return
    _active, _temporary, quarantine = _ensure_spool()
    event_dir = quarantine / parent["event_id"]
    event_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(event_dir, 0o700)
    _fsync_directory(quarantine)
    destination = event_dir / parent["original_name"]
    if (
        parent["quarantined_at"]
        and source.resolve(strict=False) == destination.resolve(strict=False)
        and source.is_file()
    ):
        os.chmod(source, 0o600)
        return
    if source.resolve(strict=False) != destination.resolve(strict=False):
        if source.exists():
            if destination.exists():
                size, digest = _hash_file(destination)
                if size != parent["size_bytes"] or digest != parent["content_sha256"]:
                    raise RuntimeError("quarantine destination conflicts with receipt hash")
                source.unlink()
            else:
                os.replace(source, destination)
        elif not destination.exists():
            raise FileNotFoundError(raw_path)
    os.chmod(destination, 0o600)
    _fsync_directory(event_dir)
    with db._conn() as connection:
        connection.execute(
            "UPDATE tg_file_deliveries SET snapshot_path=?, quarantined_at=?, "
            "updated_at=? WHERE event_id=? AND snapshot_path=?",
            (
                str(destination), quarantined_at, quarantined_at,
                parent["event_id"], raw_path,
            ),
        )


def _cleanup_file_deliveries_sync(now: datetime) -> None:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    timestamp = now.isoformat()
    with db._conn() as connection:
        parents = connection.execute(
            "SELECT * FROM tg_file_deliveries WHERE snapshot_path!='' "
            "ORDER BY accept_seq"
        ).fetchall()
    for parent in parents:
        try:
            with db._conn() as connection:
                states = [
                    row[0] for row in connection.execute(
                        "SELECT state FROM tg_file_delivery_targets WHERE event_id=?",
                        (parent["event_id"],),
                    ).fetchall()
                ]
            if not states or any(state in _ACTIVE_STATES for state in states):
                continue
            if "UNKNOWN" in states:
                _quarantine_snapshot(parent, timestamp)
                continue
            age = (now - _parse_time(parent["updated_at"])).total_seconds()
            if all(state == "SENT" for state in states):
                if age >= SENT_SNAPSHOT_RETENTION_SECONDS:
                    _delete_snapshot(parent, timestamp)
            elif "FAILED_BEFORE_SUBMIT" in states:
                if age >= FAILED_SNAPSHOT_RETENTION_SECONDS:
                    _delete_snapshot(parent, timestamp)
        except Exception as exc:
            logger.error(
                "TG file cleanup failed for %s path=%s: %s: %s",
                parent["event_id"], parent["snapshot_path"],
                type(exc).__name__, exc,
            )


async def cleanup_file_deliveries(*, now: datetime | None = None) -> None:
    """Delete only expired bulky snapshots; receipts and UNKNOWN evidence remain."""
    await asyncio.to_thread(_cleanup_file_deliveries_sync, now or _utcnow())


async def _maintenance_loop() -> None:
    while True:
        await asyncio.sleep(MAINTENANCE_INTERVAL_SECONDS)
        await cleanup_file_deliveries()


async def start_file_delivery_service() -> None:
    global _maintenance_task
    await recover_file_deliveries()
    await cleanup_file_deliveries()
    if _maintenance_task is None or _maintenance_task.done():
        _maintenance_task = asyncio.create_task(_maintenance_loop())


async def shutdown_file_delivery_service() -> None:
    global _maintenance_task
    if _maintenance_task is not None and not _maintenance_task.done():
        _maintenance_task.cancel()
        await asyncio.gather(_maintenance_task, return_exceptions=True)
    _maintenance_task = None
    tasks = [task for task in _chat_runner_tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _chat_runner_tasks.clear()

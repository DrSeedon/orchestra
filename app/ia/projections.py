"""Canonical-first current-state and search projections."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sqlite3
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProjectionDebtError(RuntimeError):
    """Raised when no safe canonical projection operation is available."""


_ZERO_HEAD = "sha256:" + "0" * 64
_HEAD_FIELDS = {"canonical_head", "projection_head", "indexed_head", "source"}
_WORD = re.compile(r"\w+", re.UNICODE)
_SUMMARY_CONTENT_LIMIT = 300


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_canonical_bytes(value)).hexdigest()}"


def _read_json(path: Path) -> dict[str, Any]:
    from app.ia.knowledge import CanonicalKnowledgeUnavailableError

    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanonicalKnowledgeUnavailableError(
            f"cannot read canonical projection source: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise CanonicalKnowledgeUnavailableError(
            f"canonical projection source is not an object: {path}"
        )
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(_canonical_bytes(dict(value)) + b"\n")
    os.replace(temporary, path)


def _search_text(record: Mapping[str, Any]) -> str:
    values: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, Mapping):
            for key in sorted(value):
                if key not in _HEAD_FIELDS:
                    collect(value[key])
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                collect(item)

    collect(record)
    return "\n".join(values)


def _matches_text(record: Mapping[str, Any], text: str) -> bool:
    words = [word.casefold() for word in _WORD.findall(text)]
    if not words:
        return True
    haystack = _search_text(record).casefold()
    return all(word in haystack for word in words)


def _identity(record: Mapping[str, Any]) -> tuple[str, str]:
    return str(record.get("record_type") or ""), str(record.get("stable_id") or "")


def _truth(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in record.items()
        if key not in _HEAD_FIELDS
    }


def _summary_item(item: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(item))
    content = result.get("content")
    if isinstance(content, str):
        result["content_length"] = len(content)
        result["content"] = content[:_SUMMARY_CONTENT_LIMIT]
    return result


def _prepare_current_rows(
    records: Sequence[Mapping[str, Any]], canonical_head: str,
) -> list[tuple[str, str, str, str, str, str, str, str]]:
    prepared = []
    seen: set[tuple[str, str]] = set()
    for raw in records:
        record = copy.deepcopy(dict(raw))
        identity = _identity(record)
        if not all(identity) or identity in seen:
            raise ProjectionDebtError("current projection has duplicate or absent identity")
        seen.add(identity)
        record_key = f"{identity[0]}:{identity[1]}"
        payload = _canonical_bytes(record).decode("utf-8")
        prepared.append(
            (
                record_key,
                identity[0],
                identity[1],
                str(record.get("project_id") or ""),
                canonical_head,
                f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}",
                payload,
                _search_text(record),
            )
        )
    return prepared


def _insert_current_rows(
    connection: sqlite3.Connection,
    prepared: Sequence[tuple[str, str, str, str, str, str, str, str]],
) -> None:
    for row in sorted(prepared):
        connection.execute(
            """INSERT INTO current_records(
                record_key, record_type, stable_id, project_id, canonical_head,
                payload_sha256, payload_json, search_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            row,
        )
        connection.execute(
            "INSERT INTO current_fts(record_key, text) VALUES (?, ?)",
            (row[0], row[7]),
        )


def _resource_manifest_sha256(records: Sequence[Mapping[str, Any]]) -> str:
    resources = []
    for raw in records:
        record = copy.deepcopy(dict(raw))
        if record.get("record_type") != "resource":
            continue
        record.pop("content", None)
        resources.append(record)
    resources.sort(key=_identity)
    return _digest(resources)


def _resource_rows_sha256(
    prepared: Sequence[tuple[str, str, str, str, str, str, str, str]],
) -> str:
    return _digest(sorted((row[0], row[5]) for row in prepared if row[1] == "resource"))


class SQLiteProjectionBackend:
    """Replaceable SQLite current rows plus an FTS5 search index."""

    def __init__(self, *, path: Path) -> None:
        self.path = Path(path)
        self._create_schema()

    def _connection(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _create_schema(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS projection_meta (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    projection_head TEXT NOT NULL,
                    resource_manifest_sha256 TEXT NOT NULL DEFAULT '',
                    resource_rows_sha256 TEXT NOT NULL DEFAULT ''
                )"""
            )
            meta_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(projection_meta)").fetchall()
            }
            for column in ("resource_manifest_sha256", "resource_rows_sha256"):
                if column not in meta_columns:
                    connection.execute(
                        f"ALTER TABLE projection_meta ADD COLUMN {column} "
                        "TEXT NOT NULL DEFAULT ''"
                    )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS current_records (
                    record_key TEXT PRIMARY KEY,
                    record_type TEXT NOT NULL,
                    stable_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    canonical_head TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    UNIQUE(record_type, stable_id)
                )"""
            )
            connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS current_fts "
                "USING fts5(record_key UNINDEXED, text)"
            )

    def replace_current(
        self,
        *,
        records: Sequence[Mapping[str, Any]],
        canonical_head: str,
    ) -> Mapping[str, Any]:
        """Atomically replace current rows and advance the projection receipt."""

        prepared = _prepare_current_rows(records, canonical_head)

        with self._connection() as connection:
            connection.execute("DELETE FROM current_fts")
            connection.execute("DELETE FROM current_records")
            _insert_current_rows(connection, prepared)
            connection.execute(
                """INSERT INTO projection_meta(
                       singleton, projection_head,
                       resource_manifest_sha256, resource_rows_sha256
                   ) VALUES (1, ?, ?, ?)
                   ON CONFLICT(singleton) DO UPDATE SET
                       projection_head=excluded.projection_head,
                       resource_manifest_sha256=excluded.resource_manifest_sha256,
                       resource_rows_sha256=excluded.resource_rows_sha256""",
                (
                    canonical_head,
                    _resource_manifest_sha256(records),
                    _resource_rows_sha256(prepared),
                ),
            )
        return {"projection_head": canonical_head, "count": len(prepared)}

    def replace_current_retaining_resources(
        self,
        *,
        records: Sequence[Mapping[str, Any]],
        resource_records: Sequence[Mapping[str, Any]],
        canonical_head: str,
    ) -> Mapping[str, Any] | None:
        """Advance mutable rows while retaining content-verified Git resources."""

        prepared = _prepare_current_rows(records, canonical_head)
        if any(row[1] == "resource" for row in prepared):
            raise ProjectionDebtError("mutable projection rows cannot be resources")

        expected: dict[str, dict[str, Any]] = {}
        for raw in resource_records:
            resource = copy.deepcopy(dict(raw))
            identity = _identity(resource)
            if identity[0] != "resource" or not identity[1]:
                raise ProjectionDebtError("retained resource identity is invalid")
            record_key = f"resource:{identity[1]}"
            if record_key in expected:
                raise ProjectionDebtError("retained resource identity is duplicated")
            expected[record_key] = resource

        with self._connection() as connection:
            meta = connection.execute(
                """SELECT resource_manifest_sha256,resource_rows_sha256
                   FROM projection_meta WHERE singleton=1"""
            ).fetchone()
            if (
                meta is None
                or str(meta["resource_manifest_sha256"])
                != _resource_manifest_sha256(resource_records)
            ):
                return None
            stored_resource_rows = [
                (
                    str(row["record_key"]),
                    "resource",
                    "",
                    "",
                    "",
                    str(row["payload_sha256"]),
                    "",
                    "",
                )
                for row in connection.execute(
                    """SELECT record_key,payload_sha256 FROM current_records
                       WHERE record_type='resource' ORDER BY record_key"""
                )
            ]
            if (
                len(stored_resource_rows) != len(expected)
                or _resource_rows_sha256(stored_resource_rows)
                != str(meta["resource_rows_sha256"])
            ):
                return None
            fts_count = connection.execute(
                """SELECT count(*) FROM current_fts f
                   JOIN current_records c ON c.record_key=f.record_key
                   WHERE c.record_type='resource'"""
            ).fetchone()[0]
            if int(fts_count) != len(expected):
                return None

            connection.execute(
                """DELETE FROM current_fts
                   WHERE record_key NOT IN (
                       SELECT record_key FROM current_records WHERE record_type='resource'
                   )"""
            )
            connection.execute("DELETE FROM current_records WHERE record_type!='resource'")
            # Resource payloads are immutable and projection_meta owns the generation
            # boundary read by queries. Rewriting this unused denormalized column touched
            # every large row and turned a task-only update into a 500 MB transaction.
            _insert_current_rows(connection, prepared)
            connection.execute(
                "UPDATE projection_meta SET projection_head=? WHERE singleton=1",
                (canonical_head,),
            )
        return {
            "projection_head": canonical_head,
            "count": len(prepared) + len(expected),
            "retained_resources": len(expected),
        }

    def search_current(
        self,
        *,
        project_id: str,
        text: str,
        record_types: Sequence[str],
        limit: int,
        cross_project: bool = False,
    ) -> Mapping[str, Any]:
        """Search only stored current payloads; never consult a source file."""

        with self._connection() as connection:
            row = connection.execute(
                "SELECT projection_head FROM projection_meta WHERE singleton=1"
            ).fetchone()
            projection_head = str(row[0]) if row is not None else None
            conditions: list[str] = []
            params: list[Any] = []
            if not cross_project:
                conditions.append("c.project_id = ?")
                params.append(project_id)
            if record_types:
                conditions.append(f"c.record_type IN ({','.join('?' * len(record_types))})")
                params.extend(record_types)
            words = _WORD.findall(text or "")
            if words:
                match = " AND ".join(f'"{word.replace(chr(34), chr(34) * 2)}"' for word in words)
                sql = (
                    "SELECT c.payload_json, c.payload_sha256 FROM current_fts f "
                    "JOIN current_records c ON c.record_key=f.record_key "
                    f"WHERE current_fts MATCH ?{' AND ' if conditions else ''}"
                    + " AND ".join(conditions)
                    + " ORDER BY rank, c.record_type, c.stable_id LIMIT ?"
                )
                params = [match, *params, limit]
            else:
                sql = "SELECT c.payload_json, c.payload_sha256 FROM current_records c"
                if conditions:
                    sql += " WHERE " + " AND ".join(conditions)
                sql += " ORDER BY c.record_type, c.stable_id LIMIT ?"
                params.append(limit)
            rows = connection.execute(sql, params).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            payload = str(row["payload_json"])
            observed = f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"
            if observed != row["payload_sha256"]:
                raise ProjectionDebtError("stored projection payload digest mismatch")
            value = json.loads(payload)
            if not isinstance(value, dict):
                raise ProjectionDebtError("stored projection payload is not an object")
            items.append(value)
        return {"items": items, "projection_head": projection_head}


@dataclass(slots=True)
class _ProjectionContext:
    task_store: Any
    knowledge_service: Any
    legacy_root: Path
    legacy_log_db: Path
    vector_query: Any
    backend: Any
    legacy_log_pending: bool


_ACTIVE_PROJECTION: _ProjectionContext | None = None


def _projection_configured() -> bool:
    return _ACTIVE_PROJECTION is not None


def _context() -> _ProjectionContext:
    if _ACTIVE_PROJECTION is None:
        raise ProjectionDebtError("current projection owner is not configured")
    return _ACTIVE_PROJECTION


def _canonical_tasks(context: _ProjectionContext) -> tuple[str, list[dict[str, Any]]]:
    from app.ia.knowledge import CanonicalKnowledgeUnavailableError

    root = Path(context.task_store.canonical_root)
    head = context.task_store.canonical_head
    records = [_read_json(path) for path in sorted(root.rglob("state.json"))]
    by_id = {str(record.get("stable_id") or ""): record for record in records}
    if "" in by_id or len(by_id) != len(records):
        raise CanonicalKnowledgeUnavailableError("canonical task identity is incomplete")

    expected: set[str] = set()
    manifests = sorted((root / "manifests").glob("*.json"))
    if len(manifests) == 1:
        expected.update(
            str(record.get("stable_id") or "")
            for record in _read_json(manifests[0]).get("tasks", [])
        )
    for path in sorted(root.rglob("events/*.json")):
        event = _read_json(path)
        stable_id = str(event.get("stable_id") or "")
        if stable_id:
            expected.add(stable_id)
    missing = sorted(expected - by_id.keys())
    if missing:
        raise CanonicalKnowledgeUnavailableError(
            f"canonical task records are missing: {missing}"
        )
    return head, records


def _canonical_facts(context: _ProjectionContext) -> tuple[str, list[dict[str, Any]]]:
    head = context.knowledge_service.head()
    records = [
        copy.deepcopy(dict(record))
        for record in context.knowledge_service._facts()
        if record.get("status") == "current"
    ]
    return head, records


def _canonical_legacy(context: _ProjectionContext) -> list[dict[str, Any]]:
    root = Path(context.knowledge_service.canonical_root)
    paths = [
        *root.glob("projects/*/legacy/files/*.json"),
        *root.glob("projects/*/legacy/logs/*.json"),
    ]
    return [_read_json(path) for path in sorted(paths)]


def _canonical_records(context: _ProjectionContext) -> tuple[str, list[dict[str, Any]]]:
    task_head, tasks = _canonical_tasks(context)
    knowledge_head, facts = _canonical_facts(context)
    records = [*tasks, *facts, *_canonical_legacy(context)]
    identities = [_identity(record) for record in records]
    if any(not all(identity) for identity in identities) or len(identities) != len(set(identities)):
        from app.ia.knowledge import CanonicalKnowledgeUnavailableError

        raise CanonicalKnowledgeUnavailableError("canonical current identity is inconsistent")
    truth = sorted(
        (_truth(record) for record in records),
        key=lambda record: _identity(record),
    )
    canonical_head = _digest(
        {"task_head": task_head, "knowledge_head": knowledge_head, "records": truth}
    )
    derived = []
    for record in records:
        value = copy.deepcopy(dict(record))
        value.update(
            canonical_head=canonical_head,
            projection_head=canonical_head,
            indexed_head=None,
            source="projection",
        )
        derived.append(value)
    return canonical_head, derived


def _selected(
    records: Sequence[Mapping[str, Any]],
    *,
    project_id: str,
    text: str,
    record_types: Sequence[str],
    limit: int,
    cross_project: bool,
) -> list[dict[str, Any]]:
    wanted = set(record_types)
    matches = [
        copy.deepcopy(dict(record))
        for record in records
        if (cross_project or record.get("project_id") == project_id)
        and (not wanted or record.get("record_type") in wanted)
        and _matches_text(record, text)
    ]
    matches.sort(key=_identity)
    return matches[:limit]


def _items_match(
    observed: Sequence[Mapping[str, Any]],
    expected: Sequence[Mapping[str, Any]],
) -> bool:
    by_identity: dict[tuple[str, str], Mapping[str, Any]] = {}
    for item in observed:
        identity = _identity(item)
        if not all(identity) or identity in by_identity:
            return False
        by_identity[identity] = item
    if set(by_identity) != {_identity(item) for item in expected}:
        return False
    for item in expected:
        candidate = by_identity[_identity(item)]
        if any(candidate.get(key) != value for key, value in _truth(item).items()):
            return False
    return True


def _debt(layer: str, reason: str, expected: str, observed: Any) -> dict[str, Any]:
    return {
        "layer": layer,
        "reason": reason,
        "expected_head": expected,
        "observed_head": observed,
    }


def _query_projection(request: Mapping[str, Any]) -> dict[str, Any]:
    context = _context()
    project_id = str(request.get("project_id") or "")
    text = str(request.get("text") or "")
    record_types = request.get("record_types") or []
    if not isinstance(record_types, Sequence) or isinstance(record_types, (str, bytes)):
        raise ProjectionDebtError("record_types must be a sequence")
    record_types = [str(value) for value in record_types]
    limit = int(request.get("limit") or 10)
    if limit <= 0:
        raise ProjectionDebtError("limit must be positive")
    cross_project = bool(request.get("cross_project", False))

    canonical_head, canonical_records = _canonical_records(context)
    expected = _selected(
        canonical_records,
        project_id=project_id,
        text=text,
        record_types=record_types,
        limit=limit,
        cross_project=cross_project,
    )
    debt: list[dict[str, Any]] = []
    backend_extra: dict[str, Any] = {}
    try:
        stored = dict(context.backend.search_current(
            project_id=project_id,
            text=text,
            record_types=record_types,
            limit=limit,
            cross_project=cross_project,
        ))
        projection_head = stored.get("projection_head")
        stored_items = list(stored.get("items") or [])
        backend_extra = {
            key: copy.deepcopy(value)
            for key, value in stored.items()
            if key not in {"items", "projection_head"}
        }
    except (OSError, sqlite3.Error, ValueError, ProjectionDebtError) as exc:
        projection_head = None
        stored_items = []
        debt.append(_debt("projection", "projection_read_failed", canonical_head, None))

    needs_write = projection_head != canonical_head
    content_mismatch = projection_head == canonical_head and not _items_match(
        stored_items, expected
    )
    if needs_write or content_mismatch:
        try:
            context.backend.replace_current(
                records=canonical_records,
                canonical_head=canonical_head,
            )
            refreshed = dict(context.backend.search_current(
                project_id=project_id,
                text=text,
                record_types=record_types,
                limit=limit,
                cross_project=cross_project,
            ))
            projection_head = refreshed.get("projection_head")
            stored_items = list(refreshed.get("items") or [])
            backend_extra = {
                key: copy.deepcopy(value)
                for key, value in refreshed.items()
                if key not in {"items", "projection_head"}
            }
        except (OSError, sqlite3.Error, ValueError, ProjectionDebtError):
            debt.append(
                _debt(
                    "projection",
                    "projection_write_failed",
                    canonical_head,
                    projection_head,
                )
            )

    projection_valid = (
        projection_head == canonical_head and _items_match(stored_items, expected)
    )
    if not projection_valid and not any(
        item["reason"] == "projection_write_failed" for item in debt
    ):
        debt.append(
            _debt("projection", "content_mismatch", canonical_head, projection_head)
        )

    observed_projection_head = projection_head or _ZERO_HEAD
    if projection_valid:
        items = [copy.deepcopy(dict(item)) for item in stored_items]
        for item in items:
            item.update(
                canonical_head=canonical_head,
                projection_head=observed_projection_head,
                source="projection",
            )
    else:
        items = [copy.deepcopy(item) for item in expected]
        for item in items:
            item.update(
                canonical_head=canonical_head,
                projection_head=observed_projection_head,
                source="canonical-fallback",
            )

    indexed_head = None
    if context.vector_query is not None:
        try:
            vector = context.vector_query(copy.deepcopy(dict(request)))
            if isinstance(vector, Mapping):
                indexed_head = vector.get("indexed_head")
            if indexed_head != canonical_head:
                debt.append(_debt("vector", "stale_index", canonical_head, indexed_head))
        except Exception:
            debt.append(_debt("vector", "index_failure", canonical_head, None))
    if context.legacy_log_pending:
        debt.append(_debt("legacy-log", "pending_rebuild", canonical_head, None))
    for item in items:
        item["indexed_head"] = indexed_head

    response = {
        "items": items,
        "count": len(items),
        "canonical_head": canonical_head,
        "projection_head": observed_projection_head,
        "indexed_head": indexed_head,
        "debt": debt,
    }
    if projection_valid:
        response.update(backend_extra)
    return response


@contextmanager
def projection_mode(
    *,
    projection_path: Path,
    task_store: Any,
    knowledge_service: Any,
    legacy_root: Path,
    legacy_log_db: Path,
    vector_query: Any = None,
    backend: Any = None,
) -> Iterator[Any]:
    """Temporarily configure the shared current projection owner."""

    global _ACTIVE_PROJECTION
    previous = _ACTIVE_PROJECTION
    selected_backend = backend or SQLiteProjectionBackend(path=Path(projection_path))
    context = _ProjectionContext(
        task_store=task_store,
        knowledge_service=knowledge_service,
        legacy_root=Path(legacy_root),
        legacy_log_db=Path(legacy_log_db),
        vector_query=vector_query,
        backend=selected_backend,
        legacy_log_pending=Path(legacy_log_db).is_file(),
    )
    _ACTIVE_PROJECTION = context
    try:
        yield selected_backend
    finally:
        _ACTIVE_PROJECTION = previous


def query_current(request: Mapping[str, Any] | None = None, **kwargs: Any) -> Mapping[str, Any]:
    """Query current canonical state through its content-bound SQLite projection."""

    if request is not None and kwargs:
        raise ProjectionDebtError("query_current accepts either a request or keyword fields")
    value = copy.deepcopy(dict(request or kwargs))
    nested = value.pop("payload", None)
    if nested is not None:
        if not isinstance(nested, Mapping):
            raise ProjectionDebtError("projection query payload must be a mapping")
        value.update(copy.deepcopy(dict(nested)))
    result = _query_projection(value)
    if value.get("detail", "record") == "summary":
        result["items"] = [_summary_item(item) for item in result["items"]]
    return {
        "operation": value.get("operation", "query"),
        "detail": value.get("detail", "record"),
        "project_id": str(value.get("project_id") or ""),
        **result,
    }


def _legacy_project_id(scope: str) -> str:
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", scope):
        return scope
    return f"legacy-{hashlib.sha256(scope.encode('utf-8')).hexdigest()[:16]}"


def _file_reference(project_id: str, relative: str, content: bytes) -> dict[str, Any]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectionDebtError(f"legacy file is not UTF-8: {relative}") from exc
    digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    stable_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"orch://legacy/file/{project_id}/{relative}"))
    return {
        "record_type": "knowledge.evidence-ref",
        "schema_version": 1,
        "stable_id": stable_id,
        "uri": f"orch://project/{project_id}/knowledge/evidence/{stable_id}",
        "project_id": project_id,
        "status": "current",
        "source_path": relative,
        "source_class": "legacy-file",
        "source_sha256": digest,
        "storage": "structured-json-reference",
        "content": text,
    }


def _log_references(
    project_id: str,
    scope: str,
    path: Path,
    session_name: str,
) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    uri = f"file:{path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        where = "WHERE s.scope = ?"
        params: list[Any] = [scope]
        if session_name:
            where += " AND s.name = ?"
            params.append(session_name)
        rows = connection.execute(
            "SELECT l.id, l.session_id, s.name, l.type, l.content "
            "FROM logs l JOIN sessions s ON s.id=l.session_id "
            f"{where} ORDER BY l.id",
            params,
        ).fetchall()
    records = []
    for row in rows:
        content = str(row["content"] or "")
        if not content.strip():
            continue
        session_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"orch://legacy/session/{project_id}/{row['session_id']}",
        ))
        stable_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"orch://legacy/log/{project_id}/{row['id']}",
        ))
        item_uri = (
            f"orch://project/{project_id}/sessions/{session_id}/history/{stable_id}"
        )
        records.append({
            "record_type": "session.history",
            "schema_version": 1,
            "stable_id": stable_id,
            "uri": item_uri,
            "project_id": project_id,
            "status": "current",
            "session_id": session_id,
            "archive_id": stable_id,
            "canonical_path": f"legacy-log:{row['id']}",
            "source_log_ids": [int(row["id"])],
            "summary_ref": item_uri,
            "kind": str(row["type"] or "text"),
            "author": str(row["name"] or ""),
            "source_sha256": f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
            "storage": "structured-json-reference",
            "content": content,
        })
    return records


def rebuild_legacy(
    *,
    scope: str,
    session_name: str | None = None,
) -> Mapping[str, Any]:
    """Import legacy file/log bytes once, then synchronously rebuild current/FTS."""

    if _ACTIVE_PROJECTION is None:
        from app import rag_service

        status = rag_service.schedule_backfill(scope, session_name=session_name or "")
        if status == "not_ready":
            raise ProjectionDebtError("RAG not initialized")
        return {"ok": True, "status": status, "index": rag_service.index_status(scope)}

    context = _context()
    project_id = _legacy_project_id(scope)
    root = context.legacy_root.resolve()
    files: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.rglob("*.md")):
            relative = path.relative_to(root).as_posix()
            try:
                content = path.read_bytes()
            except OSError as exc:
                raise ProjectionDebtError(f"cannot read legacy file: {relative}") from exc
            files.append(_file_reference(project_id, relative, content))
    logs = _log_references(
        project_id,
        scope,
        context.legacy_log_db,
        session_name or "",
    )

    canonical_root = Path(context.knowledge_service.canonical_root)
    file_root = canonical_root / "projects" / project_id / "legacy" / "files"
    log_root = canonical_root / "projects" / project_id / "legacy" / "logs"
    wanted = {
        file_root / f"{record['stable_id']}.json" for record in files
    } | {
        log_root / f"{record['stable_id']}.json" for record in logs
    }
    for path in [*file_root.glob("*.json"), *log_root.glob("*.json")]:
        if path not in wanted:
            path.unlink()
    for record in [*files, *logs]:
        owner = file_root if record["record_type"] == "knowledge.evidence-ref" else log_root
        _write_json(owner / f"{record['stable_id']}.json", record)
    context.legacy_log_pending = False

    result = _query_projection({
        "project_id": project_id,
        "text": "",
        "record_types": ["knowledge.evidence-ref", "session.history"],
        "limit": max(1, len(files) + len(logs)),
    })
    return {
        "ok": True,
        "file_refs": len(files),
        "log_refs": len(logs),
        "canonical_head": result["canonical_head"],
        "projection_head": result["projection_head"],
        "indexed_head": result["indexed_head"],
        "debt": result["debt"],
    }

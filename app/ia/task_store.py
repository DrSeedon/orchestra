"""Git-reviewable canonical task records with a rebuildable SQLite projection."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MigrationManifestError(ValueError):
    """Raised when a migration manifest is incomplete, changed, or inconsistent."""


class IdentityConflictError(ValueError):
    """Raised when two active tasks claim one project-local display number."""


class ConcurrentTaskUpdateError(RuntimeError):
    """Raised when concurrent task events cannot be merged without losing a write."""

    def __init__(self, message: str, *, event_ids: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.event_ids = tuple(event_ids)


class ProjectionDebtError(RuntimeError):
    """Raised when a requested projection cannot be proven against canonical content."""


class ProvenanceError(ValueError):
    """Raised when an evidence reference lacks immutable source provenance."""


class UnsupportedDomainError(ValueError):
    """Raised when a removed payment or YouGile domain reaches the task store."""


_EXCLUDED_SOURCES = [
    "tm_clients",
    "tm_payments",
    "tm_payment_allocations",
    "tm_sync_log",
    "tm_projects.yougile_*",
    "tm_tasks.yougile_task_id",
]
_VALID_STATUSES = {"backlog", "new", "in_progress", "done", "cancelled"}
_TASK_SOURCE_FIELDS = (
    "id",
    "par_number",
    "project_id",
    "title",
    "description",
    "price_rub",
    "status",
    "assignee",
    "sync_revision",
    "worker_session_id",
    "git_commits",
    "created_at",
    "updated_at",
    "completed_at",
    "priority",
    "acceptance_command",
    "acceptance_oracle_json",
)
_PROVENANCE_FIELDS = ("canonical_path", "anchor", "git_commit", "content_sha256")
_PROJECTION_TABLE = "ia_task_projection"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise MigrationManifestError("task data is not canonical JSON") from exc
    return rendered.encode("utf-8")


def _digest(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_canonical_bytes(value)).hexdigest()}"


def _detached(value: Any) -> Any:
    return json.loads(_canonical_bytes(value))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(_canonical_bytes(value) + b"\n")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationManifestError(f"cannot read canonical JSON {path}") from exc
    if not isinstance(value, dict):
        raise MigrationManifestError(f"canonical JSON must be an object: {path}")
    return value


def _acceptance(task: Mapping[str, Any]) -> dict[str, Any]:
    raw = task.get("acceptance_oracle_json") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MigrationManifestError("malformed acceptance_oracle_json") from exc
    if not isinstance(raw, Mapping):
        raise MigrationManifestError("acceptance_oracle_json must be an object")
    manifest = raw.get("manifest_paths") or []
    if not isinstance(manifest, Sequence) or isinstance(manifest, (str, bytes)):
        raise MigrationManifestError("acceptance manifest must be a sequence")
    return {
        "command": str(task.get("acceptance_command") or "").strip(),
        "manifest_paths": sorted(str(path) for path in manifest),
        "required": bool(raw.get("required")),
    }


def _commit_refs(task: Mapping[str, Any]) -> list[Any]:
    commits = task.get("git_commits") or []
    if isinstance(commits, str):
        try:
            commits = json.loads(commits)
        except json.JSONDecodeError as exc:
            raise MigrationManifestError("malformed git_commits") from exc
    if not isinstance(commits, Sequence) or isinstance(commits, (str, bytes)):
        raise MigrationManifestError("git_commits must be a sequence")
    return _detached(list(commits))


def _manifest_core(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in manifest.items()
        if key not in {"manifest_id", "canonical_head"}
    }


def build_migration_manifest(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Build a detached deterministic manifest from one immutable legacy snapshot."""

    if not isinstance(snapshot, Mapping):
        raise MigrationManifestError("snapshot must be a mapping")
    frozen = _detached(snapshot)
    source = frozen.get("source")
    projects = frozen.get("projects")
    tasks = frozen.get("tasks")
    evidence = frozen.get("evidence")
    if not isinstance(source, dict) or not all(
        isinstance(source.get(key), str) and source[key]
        for key in ("cutoff", "source_head", "source_schema_sha256")
    ):
        raise MigrationManifestError("snapshot source is incomplete")
    if not isinstance(projects, list) or not isinstance(tasks, list) or not isinstance(evidence, list):
        raise MigrationManifestError("snapshot projects, tasks, and evidence must be lists")

    project_by_id: dict[str, dict[str, Any]] = {}
    for project in projects:
        if not isinstance(project, dict) or not isinstance(project.get("id"), str):
            raise MigrationManifestError("project rows require an id")
        project_by_id[project["id"]] = project

    records: list[dict[str, Any]] = []
    source_to_stable: dict[int, str] = {}
    display_identities: set[tuple[str, int]] = set()
    for raw in sorted(
        tasks,
        key=lambda item: (
            str(item.get("project_id", "")),
            int(item.get("par_number", 0)),
            int(item.get("id", 0)),
        ),
    ):
        if not isinstance(raw, dict):
            raise MigrationManifestError("task rows must be objects")
        try:
            row_id = int(raw["id"])
            display_number = int(raw["par_number"])
            project_id = str(raw["project_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise MigrationManifestError("task source identity is incomplete") from exc
        if row_id in source_to_stable:
            raise MigrationManifestError(f"duplicate tm_tasks row {row_id}")
        display_identity = (project_id, display_number)
        if display_identity in display_identities:
            raise IdentityConflictError(
                f"display #{display_number} is duplicated in {project_id}"
            )
        if project_id not in project_by_id:
            raise MigrationManifestError(f"task row {row_id} has no project {project_id}")
        display_identities.add(display_identity)
        stable_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"orch://migration/task/{project_id}/tm_tasks/{row_id}",
            )
        )
        source_to_stable[row_id] = stable_id
        allowed_source = {key: raw.get(key) for key in _TASK_SOURCE_FIELDS}
        row_sha = _digest(allowed_source)
        project = project_by_id[project_id]
        record = {
            "record_type": "task.state",
            "schema_version": 1,
            "stable_id": stable_id,
            "uri": f"orch://project/{project_id}/tasks/{stable_id}/state",
            "project_id": project_id,
            "display_number": display_number,
            "display_ref": f"#{display_number}",
            "title": str(raw.get("title") or ""),
            "description": str(raw.get("description") or ""),
            "price_rub": int(raw.get("price_rub") or 0),
            "status": str(raw.get("status") or "new"),
            "assignee": str(raw.get("assignee") or ""),
            "priority": int(2 if raw.get("priority") is None else raw["priority"]),
            "scope": str(project.get("scope") or ""),
            "worker_session_id": raw.get("worker_session_id"),
            "acceptance": _acceptance(raw),
            "evidence_refs": [],
            "git_commit_refs": _commit_refs(raw),
            "created_at": str(raw.get("created_at") or source["cutoff"]),
            "updated_at": str(raw.get("updated_at") or source["cutoff"]),
            "completed_at": raw.get("completed_at"),
            "sync_revision": int(raw.get("sync_revision") or 0),
            "source_row": {
                "table": "tm_tasks",
                "row_id": row_id,
                "row_sha256": row_sha,
            },
        }
        records.append(record)

    evidence_records: list[dict[str, Any]] = []
    task_by_stable = {record["stable_id"]: record for record in records}
    for raw in sorted(evidence, key=lambda item: str(item.get("stable_id", ""))):
        if not isinstance(raw, dict):
            raise MigrationManifestError("evidence rows must be objects")
        try:
            stable_id = str(uuid.UUID(str(raw["stable_id"])))
            task_id = source_to_stable[int(raw["source_task_row_id"])]
        except (KeyError, TypeError, ValueError) as exc:
            raise MigrationManifestError("evidence identity is incomplete") from exc
        if any(not raw.get(field) for field in _PROVENANCE_FIELDS):
            raise ProvenanceError(f"evidence {stable_id} has incomplete provenance")
        project_id = task_by_stable[task_id]["project_id"]
        uri = f"orch://project/{project_id}/tasks/{task_id}/evidence/{stable_id}"
        record = {
            "record_type": "task.evidence",
            "schema_version": 1,
            "stable_id": stable_id,
            "uri": uri,
            "task_id": task_id,
            "project_id": project_id,
            "kind": str(raw.get("kind") or ""),
            "canonical_path": str(raw["canonical_path"]),
            "anchor": str(raw["anchor"]),
            "git_commit": str(raw["git_commit"]),
            "content_sha256": str(raw["content_sha256"]),
        }
        evidence_records.append(record)
        task_by_stable[task_id]["evidence_refs"].append(uri)

    denominators = {
        "projects": len(projects),
        "tasks": len(tasks),
        "evidence": len(evidence),
        "commit_links": sum(len(_commit_refs(task)) for task in tasks),
        "excluded_clients": len(frozen.get("clients") or []),
        "excluded_payments": len(frozen.get("payments") or []),
        "excluded_payment_allocations": len(frozen.get("payment_allocations") or []),
        "excluded_sync_rows": len(frozen.get("sync_log") or []),
    }
    manifest: dict[str, Any] = {
        "manifest_version": 1,
        "source": source,
        "denominators": denominators,
        "excluded_sources": list(_EXCLUDED_SOURCES),
        "tasks": records,
        "evidence": evidence_records,
    }
    canonical_head = _digest(_manifest_core(manifest))
    manifest["manifest_id"] = canonical_head.removeprefix("sha256:")
    manifest["canonical_head"] = canonical_head
    return _detached(manifest)


class TaskStore:
    """Canonical per-task JSON plus an isolated, content-bound SQLite projection."""

    def __init__(self, *, canonical_root: Path, projection_path: Path) -> None:
        self.canonical_root = Path(canonical_root)
        self.projection_path = Path(projection_path)

    @property
    def canonical_head(self) -> str:
        return self._current_head()

    @property
    def projection_head(self) -> str:
        head = self._current_head()
        if not self.projection_path.exists():
            raise ProjectionDebtError("task projection does not exist")
        with sqlite3.connect(self.projection_path) as connection:
            heads = {
                row[0]
                for row in connection.execute(
                    f"SELECT canonical_head FROM {_PROJECTION_TABLE}"
                ).fetchall()
            }
        if heads and heads != {head}:
            raise ProjectionDebtError("task projection contains mixed canonical heads")
        return head

    def _manifest_path(self, manifest_id: str) -> Path:
        return self.canonical_root / "manifests" / f"{manifest_id}.json"

    def _task_dir(self, state: Mapping[str, Any]) -> Path:
        return (
            self.canonical_root
            / "projects"
            / str(state["project_id"])
            / "tasks"
            / str(state["stable_id"])
        )

    def _state_path(self, state: Mapping[str, Any]) -> Path:
        return self._task_dir(state) / "state.json"

    def _event_path(self, state: Mapping[str, Any], event_id: str) -> Path:
        return self._task_dir(state) / "events" / f"{event_id}.json"

    def _evidence_path(self, evidence: Mapping[str, Any]) -> Path:
        state = {
            "project_id": evidence["project_id"],
            "stable_id": evidence["task_id"],
        }
        return self._task_dir(state) / "evidence" / f"{evidence['stable_id']}.json"

    def _validate_manifest(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(manifest, Mapping):
            raise MigrationManifestError("manifest must be a mapping")
        detached = _detached(manifest)
        if detached.get("manifest_version") != 1:
            raise MigrationManifestError("unsupported task manifest version")
        expected_head = _digest(_manifest_core(detached))
        if detached.get("canonical_head") != expected_head:
            raise MigrationManifestError("manifest canonical head does not match its content")
        if detached.get("manifest_id") != expected_head.removeprefix("sha256:"):
            raise MigrationManifestError("manifest id does not match its content")
        if detached.get("excluded_sources") != _EXCLUDED_SOURCES:
            raise MigrationManifestError("manifest excluded-domain contract changed")
        tasks = detached.get("tasks")
        evidence = detached.get("evidence")
        if not isinstance(tasks, list) or not isinstance(evidence, list):
            raise MigrationManifestError("manifest task and evidence bodies must be lists")
        seen_stable: set[str] = set()
        seen_display: set[tuple[str, int]] = set()
        for task in tasks:
            stable_id = str(task.get("stable_id") or "")
            display = (str(task.get("project_id") or ""), int(task.get("display_number") or 0))
            if stable_id in seen_stable or display in seen_display:
                raise IdentityConflictError("manifest contains duplicate active task identity")
            seen_stable.add(stable_id)
            seen_display.add(display)
        for item in evidence:
            if item.get("task_id") not in seen_stable:
                raise ProvenanceError("manifest evidence refers to an unknown task")
            if any(not item.get(field) for field in _PROVENANCE_FIELDS):
                raise ProvenanceError("manifest evidence lacks immutable provenance")
        return detached

    def _initial_states(self, manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        head = str(manifest["canonical_head"])
        states: dict[str, dict[str, Any]] = {}
        for raw in manifest["tasks"]:
            state = copy.deepcopy(raw)
            state["canonical_head"] = head
            state["projection_head"] = head
            states[state["stable_id"]] = state
        return states

    def _initial_manifest(self) -> dict[str, Any]:
        paths = sorted((self.canonical_root / "manifests").glob("*.json"))
        if len(paths) != 1:
            raise MigrationManifestError(
                f"expected exactly one task migration manifest, found {len(paths)}"
            )
        return self._validate_manifest(_read_json(paths[0]))

    def _states(self) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        display: set[tuple[str, int]] = set()
        for path in sorted(self.canonical_root.rglob("state.json")):
            state = _read_json(path)
            stable_id = str(state.get("stable_id") or "")
            identity = (str(state.get("project_id") or ""), int(state.get("display_number") or 0))
            if not stable_id or stable_id in states or identity in display:
                raise IdentityConflictError(f"duplicate canonical task identity at {path}")
            states[stable_id] = state
            display.add(identity)
        return states

    def _current_head(self) -> str:
        states = self._states()
        if not states:
            paths = sorted((self.canonical_root / "manifests").glob("*.json"))
            if len(paths) == 1:
                return str(self._validate_manifest(_read_json(paths[0]))["canonical_head"])
            raise MigrationManifestError("canonical task store is empty")
        heads = {state.get("canonical_head") for state in states.values()}
        if len(heads) != 1 or not next(iter(heads)):
            raise MigrationManifestError("canonical task states contain mixed heads")
        return str(next(iter(heads)))

    def _projection_connection(self) -> sqlite3.Connection:
        self.projection_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.projection_path)
        connection.execute(
            f"""CREATE TABLE IF NOT EXISTS {_PROJECTION_TABLE} (
                stable_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                display_number INTEGER NOT NULL,
                canonical_head TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{{}}',
                UNIQUE(project_id, display_number)
            )"""
        )
        return connection

    def _rebuild_projection(self, states: Mapping[str, Mapping[str, Any]]) -> None:
        with self._projection_connection() as connection:
            old_metadata = {
                row[0]: row[1]
                for row in connection.execute(
                    f"SELECT stable_id, metadata_json FROM {_PROJECTION_TABLE}"
                ).fetchall()
            }
            connection.execute(f"DELETE FROM {_PROJECTION_TABLE}")
            for stable_id, state in sorted(states.items()):
                payload = _canonical_bytes(state).decode("utf-8")
                connection.execute(
                    f"""INSERT INTO {_PROJECTION_TABLE}
                       (stable_id, project_id, display_number, canonical_head,
                        payload_sha256, payload_json, metadata_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        stable_id,
                        state["project_id"],
                        state["display_number"],
                        state["canonical_head"],
                        f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}",
                        payload,
                        old_metadata.get(stable_id, "{}"),
                    ),
                )

    def _write_states(self, states: Mapping[str, Mapping[str, Any]], head: str) -> None:
        normalized: dict[str, dict[str, Any]] = {}
        for stable_id, raw in states.items():
            state = copy.deepcopy(dict(raw))
            state["canonical_head"] = head
            state["projection_head"] = head
            normalized[stable_id] = state
        wanted = {self._state_path(state) for state in normalized.values()}
        for path in self.canonical_root.rglob("state.json"):
            if path not in wanted:
                path.unlink()
        for state in normalized.values():
            _write_json(self._state_path(state), state)
        self._rebuild_projection(normalized)

    def _migration_receipt(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "manifest_id": manifest["manifest_id"],
            "canonical_head": manifest["canonical_head"],
            "projection_head": manifest["canonical_head"],
            "task_count": len(manifest["tasks"]),
            "event_count": len(manifest["tasks"]),
            "evidence_count": len(manifest["evidence"]),
        }

    def migrate(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        """Materialize one immutable manifest and its current projection idempotently."""

        value = self._validate_manifest(manifest)
        path = self._manifest_path(value["manifest_id"])
        if path.exists():
            if _read_json(path) != value:
                raise MigrationManifestError("immutable migration manifest changed")
            if self._current_head() != value["canonical_head"]:
                raise MigrationManifestError("manifest replay would overwrite newer canonical state")
            return self._migration_receipt(value)
        existing = list((self.canonical_root / "manifests").glob("*.json"))
        if existing:
            raise MigrationManifestError("task store already belongs to another migration manifest")

        states = self._initial_states(value)
        _write_json(path, value)
        for evidence in value["evidence"]:
            _write_json(self._evidence_path(evidence), evidence)
        for state in states.values():
            event_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{state['uri']}/events/migrated/{state['source_row']['row_sha256']}",
                )
            )
            event = {
                "event_id": event_id,
                "event_type": "task.migrated",
                "stable_id": state["stable_id"],
                "project_id": state["project_id"],
                "display_number": state["display_number"],
                "occurred_at": value["source"]["cutoff"],
                "parent_head": value["source"]["source_head"],
                "canonical_head": value["canonical_head"],
                "result_state": state,
            }
            _write_json(self._event_path(state, event_id), event)
        self._write_states(states, value["canonical_head"])
        return self._migration_receipt(value)

    def _projection_debt(self, state: Mapping[str, Any]) -> dict[str, Any] | None:
        if not self.projection_path.exists():
            return {"reason": "missing_projection", "stable_id": state["stable_id"]}
        with self._projection_connection() as connection:
            row = connection.execute(
                f"SELECT payload_json, payload_sha256, canonical_head "
                f"FROM {_PROJECTION_TABLE} WHERE stable_id=?",
                (state["stable_id"],),
            ).fetchone()
        canonical_payload = _canonical_bytes(state).decode("utf-8")
        canonical_sha = f"sha256:{hashlib.sha256(canonical_payload.encode('utf-8')).hexdigest()}"
        if row is None:
            return {"reason": "missing_projection_row", "stable_id": state["stable_id"]}
        if row != (canonical_payload, canonical_sha, state["canonical_head"]):
            return {"reason": "projection_content_mismatch", "stable_id": state["stable_id"]}
        return None

    @staticmethod
    def _parse_ref(ref: str) -> int:
        value = str(ref).strip().lstrip("#").upper()
        match = re.fullmatch(r"(?:[A-Z]{2,5}-)?(\d+)", value)
        if match is None:
            raise ValueError(f"Cannot parse task ref: {ref}")
        return int(match.group(1))

    def _find_state(self, ref: str, project: str = "") -> dict[str, Any]:
        number = self._parse_ref(ref)
        matches = [
            state
            for state in self._states().values()
            if state["display_number"] == number
            and (not project or state["project_id"] == project)
        ]
        if len(matches) > 1:
            projects = ", ".join(sorted(state["project_id"] for state in matches))
            raise ValueError(f"Ambiguous task #{number} — exists in projects: {projects}")
        if not matches:
            raise ValueError(f"{ref} not found")
        return matches[0]

    @staticmethod
    def _facade_detail(state: Mapping[str, Any]) -> dict[str, Any]:
        result = {
            "par": str(state["display_number"]),
            "title": state["title"],
            "description": state["description"],
            "project": state["project_id"],
            "price_rub": state["price_rub"],
            "status": state["status"],
            "assignee": state["assignee"],
            "priority": state.get("priority", 2),
            "created_at": state["created_at"],
            "completed_at": state.get("completed_at"),
            "commits": copy.deepcopy(state.get("git_commit_refs") or []),
            "sync_revision": state.get("sync_revision", 0),
            "stable_id": state["stable_id"],
            "display_ref": state["display_ref"],
            "canonical_head": state["canonical_head"],
            "projection_head": state["projection_head"],
            "worker_session_id": state.get("worker_session_id"),
            "acceptance": copy.deepcopy(state.get("acceptance") or {}),
            "evidence_refs": copy.deepcopy(state.get("evidence_refs") or []),
        }
        return result

    @staticmethod
    def _format_amount(rub: int) -> str:
        if rub == 0:
            return "0"
        sign = "-" if rub < 0 else ""
        return sign + " ".join(
            reversed(
                [str(abs(rub))[max(0, index - 3):index] for index in range(len(str(abs(rub))), 0, -3)]
            )
        )

    def task_list(self, project: str = "", status: str = "", assignee: str = "") -> dict[str, Any]:
        all_states = list(self._states().values())
        states = [
            state
            for state in all_states
            if (not project or state["project_id"] == project)
            and (not status or state["status"] == status)
            and (not assignee or state["assignee"] == assignee)
        ]
        states.sort(key=lambda state: (state.get("priority", 2), -state["display_number"]))
        result = {
            "tasks": [
                {
                    "par": str(state["display_number"]),
                    "title": state["title"],
                    "project": state["project_id"],
                    "price": self._format_amount(state["price_rub"]),
                    "status": state["status"],
                    "assignee": state["assignee"],
                    "priority": state.get("priority", 2),
                }
                for state in states
            ],
            "count": len(states),
        }
        if project:
            result["next_display_number"] = self._next_display_number(all_states, project)
        return result

    def task_get(self, ref: str, project: str = "") -> dict[str, Any]:
        state = self._find_state(ref, project)
        result = self._facade_detail(state)
        debt = self._projection_debt(state)
        if debt:
            result["projection_debt"] = debt
        return result

    def _ensure_expected(self, expected_head: str | None) -> str:
        current = self._current_head()
        if expected_head is not None and expected_head != current:
            raise ConcurrentTaskUpdateError(
                f"canonical head changed: expected {expected_head}, found {current}"
            )
        return current

    @staticmethod
    def _truth_state(state: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: copy.deepcopy(value)
            for key, value in state.items()
            if key not in {"canonical_head", "projection_head", "projection_debt"}
        }

    def _generation_head(
        self,
        parent_head: str,
        states: Mapping[str, Mapping[str, Any]],
        events: Sequence[Mapping[str, Any]],
    ) -> str:
        event_content = [
            {
                key: copy.deepcopy(value)
                for key, value in event.items()
                if key not in {"canonical_head", "parent_head", "result_state"}
            }
            for event in events
        ]
        event_content.sort(key=lambda event: str(event["event_id"]))
        state_content = [
            self._truth_state(state)
            for _, state in sorted(states.items())
        ]
        return _digest(
            {"parent_head": parent_head, "events": event_content, "states": state_content}
        )

    def _commit_generation(
        self,
        states: dict[str, dict[str, Any]],
        events: list[dict[str, Any]],
        *,
        parent_head: str,
    ) -> str:
        head = self._generation_head(parent_head, states, events)
        for state in states.values():
            state["canonical_head"] = head
            state["projection_head"] = head
        for raw in events:
            event = copy.deepcopy(raw)
            event["parent_head"] = parent_head
            event["canonical_head"] = head
            state = states.get(event["stable_id"])
            if state is not None:
                event["result_state"] = copy.deepcopy(state)
                event_path = self._event_path(state, str(event["event_id"]))
            else:
                raise MigrationManifestError("task deletion events are not supported in T2")
            if event_path.exists():
                existing = _read_json(event_path)
                if existing != event:
                    raise ConcurrentTaskUpdateError(
                        f"event id {event['event_id']} already contains another claim",
                        event_ids=[str(event["event_id"])],
                    )
            else:
                _write_json(event_path, event)
        self._write_states(states, head)
        return head

    @staticmethod
    def _receipt(state: Mapping[str, Any], *, head: str | None = None) -> dict[str, Any]:
        canonical_head = head or str(state["canonical_head"])
        return {
            "stable_id": state["stable_id"],
            "display_ref": state["display_ref"],
            "canonical_head": canonical_head,
            "projection_head": canonical_head,
            "evidence_refs": copy.deepcopy(state.get("evidence_refs") or []),
        }

    def task_create(
        self,
        *,
        project_id: str,
        title: str,
        price: int = 0,
        description: str = "",
        assignee: str = "",
        status: str = "new",
        priority: int = 2,
        acceptance_command: str = "",
        acceptance_manifest: list[str] | None = None,
        acceptance_required: bool = False,
        display_number: int | None = None,
        expected_head: str | None = None,
        contour_id: str = "central",
    ) -> dict[str, Any]:
        if status not in _VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")
        if price < 0:
            raise ValueError("price must be >= 0")
        parent = self._ensure_expected(expected_head)
        states = self._states()
        if display_number is None:
            display_number = self._next_display_number(states.values(), project_id)
        else:
            display_number = int(display_number)
            if display_number <= 0:
                raise IdentityConflictError("display number must be positive")
            if any(
                state["project_id"] == project_id
                and state["display_number"] == display_number
                for state in states.values()
            ):
                raise IdentityConflictError(
                    f"display #{display_number} is already active in {project_id}"
                )
        stable_id = str(uuid.uuid4())
        now = _now()
        state = {
            "record_type": "task.state",
            "schema_version": 1,
            "stable_id": stable_id,
            "uri": f"orch://project/{project_id}/tasks/{stable_id}/state",
            "project_id": project_id,
            "display_number": display_number,
            "display_ref": f"#{display_number}",
            "title": title,
            "description": description,
            "price_rub": price,
            "status": status,
            "assignee": assignee,
            "priority": priority,
            "scope": "",
            "worker_session_id": None,
            "acceptance": {
                "command": acceptance_command.strip(),
                "manifest_paths": sorted(acceptance_manifest or []),
                "required": bool(acceptance_required),
            },
            "evidence_refs": [],
            "git_commit_refs": [],
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "sync_revision": 0,
        }
        states[stable_id] = state
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "task.created",
            "stable_id": stable_id,
            "project_id": project_id,
            "display_number": display_number,
            "contour_id": contour_id,
            "occurred_at": now,
            "record": self._truth_state(state),
        }
        head = self._commit_generation(states, [event], parent_head=parent)
        return {
            "par": str(display_number),
            "task_id": stable_id,
            "title": title,
            "project": project_id,
            "price_rub": price,
            "status": status,
            **self._receipt(states[stable_id], head=head),
        }

    def repair_display_collisions(
        self,
        repairs: Sequence[Mapping[str, Any]],
        *,
        expected_head: str | None = None,
    ) -> dict[str, Any]:
        """Move collided canonical tasks and restore the older legacy identities."""

        if not repairs:
            raise ValueError("repairs must be a non-empty sequence")
        parent = self._ensure_expected(expected_head)
        states = self._states()
        claimed = {
            (state["project_id"], int(state["display_number"])): stable_id
            for stable_id, state in states.items()
        }
        moving_ids = {str(repair.get("stable_id") or "") for repair in repairs}
        if "" in moving_ids or len(moving_ids) != len(repairs):
            raise IdentityConflictError("repair stable ids must be unique")
        restored_ids: set[str] = set()
        legacy_row_ids: set[int] = set()
        final_identities: set[tuple[str, int]] = set()
        normalized: list[dict[str, Any]] = []
        for repair in repairs:
            stable_id = str(repair["stable_id"])
            if stable_id not in states:
                raise IdentityConflictError(f"repair task {stable_id} does not exist")
            state = states[stable_id]
            project_id = str(state["project_id"])
            old_number = int(repair["from_display_number"])
            new_number = int(repair["to_display_number"])
            if old_number <= 0 or new_number <= 0 or old_number == new_number:
                raise IdentityConflictError("repair display numbers must be distinct and positive")
            if int(state["display_number"]) != old_number:
                raise IdentityConflictError(
                    f"repair source #{old_number} no longer names {stable_id}"
                )
            owner = claimed.get((project_id, new_number))
            if owner is not None and owner not in moving_ids:
                raise IdentityConflictError(
                    f"repair target #{new_number} is already active in {project_id}"
                )
            restored = copy.deepcopy(dict(repair["restored_state"]))
            restored_id = str(restored.get("stable_id") or "")
            if (
                not restored_id
                or restored_id in states
                or restored_id in restored_ids
                or restored_id in moving_ids
            ):
                raise IdentityConflictError("restored task stable identity is not new")
            if (
                restored.get("project_id") != project_id
                or int(restored.get("display_number") or 0) != old_number
            ):
                raise IdentityConflictError("restored task does not reclaim the collided identity")
            for identity in ((project_id, new_number), (project_id, old_number)):
                if identity in final_identities:
                    raise IdentityConflictError("repair claims one display identity twice")
                final_identities.add(identity)
            restored_ids.add(restored_id)
            legacy_row_id = int(repair["legacy_row_id"])
            legacy_from_display_number = int(repair["legacy_from_display_number"])
            if (
                legacy_row_id <= 0
                or legacy_from_display_number <= 0
                or legacy_row_id in legacy_row_ids
            ):
                raise IdentityConflictError("repair legacy task identity is invalid")
            legacy_row_ids.add(legacy_row_id)
            normalized.append({
                "stable_id": stable_id,
                "project_id": project_id,
                "old_number": old_number,
                "new_number": new_number,
                "restored": restored,
                "legacy_row_id": legacy_row_id,
                "legacy_from_display_number": legacy_from_display_number,
            })

        occurred_at = _now()
        events: list[dict[str, Any]] = []
        moves: list[dict[str, Any]] = []
        for repair in normalized:
            state = states[repair["stable_id"]]
            state["display_number"] = repair["new_number"]
            state["display_ref"] = f"#{repair['new_number']}"
            state["updated_at"] = occurred_at
            state["sync_revision"] = int(state.get("sync_revision") or 0) + 1
            restored = repair["restored"]
            states[restored["stable_id"]] = restored
            events.extend((
                {
                    "event_id": str(uuid.uuid4()),
                    "event_type": "task.display-renumbered",
                    "stable_id": state["stable_id"],
                    "project_id": state["project_id"],
                    "display_number": state["display_number"],
                    "occurred_at": occurred_at,
                    "changes": {
                        "from_display_number": repair["old_number"],
                        "to_display_number": repair["new_number"],
                        "legacy_row_id": repair["legacy_row_id"],
                        "legacy_from_display_number": repair[
                            "legacy_from_display_number"
                        ],
                    },
                },
                {
                    "event_id": str(uuid.uuid4()),
                    "event_type": "task.restored-from-legacy",
                    "stable_id": restored["stable_id"],
                    "project_id": restored["project_id"],
                    "display_number": restored["display_number"],
                    "occurred_at": occurred_at,
                    "changes": {"source_row": copy.deepcopy(restored.get("source_row") or {})},
                },
            ))
            moves.append({
                "stable_id": state["stable_id"],
                "from": repair["old_number"],
                "to": repair["new_number"],
                "legacy_row_id": repair["legacy_row_id"],
                "restored_stable_id": restored["stable_id"],
            })
        head = self._commit_generation(states, events, parent_head=parent)
        return {
            "repaired_count": len(moves),
            "moves": moves,
            "canonical_head": head,
            "projection_head": head,
        }

    @staticmethod
    def _next_display_number(
        states: Iterable[Mapping[str, Any]],
        project_id: str,
    ) -> int:
        if not project_id:
            raise ValueError("project is required to allocate a display number")
        return 1 + max(
            (
                int(state["display_number"])
                for state in states
                if state["project_id"] == project_id
            ),
            default=0,
        )

    def task_update(
        self,
        ref: str,
        *,
        project: str = "",
        title: str | None = None,
        description: str | None = None,
        price: int | None = None,
        status: str | None = None,
        assignee: str | None = None,
        priority: int | None = None,
        worker_session_id: str | None = None,
        acceptance_command: str | None = None,
        acceptance_manifest: list[str] | None = None,
        acceptance_required: bool | None = None,
        expected_head: str | None = None,
        contour_id: str = "central",
    ) -> dict[str, Any]:
        parent = self._ensure_expected(expected_head)
        states = self._states()
        original = self._find_state(ref, project)
        state = states[original["stable_id"]]
        old_status = state["status"]
        changed: list[str] = []
        event_changes: list[tuple[str, Any]] = []

        for field, value, label in (
            ("title", title, "title"),
            ("description", description, "description"),
            ("assignee", assignee, "assignee"),
            ("priority", priority, "priority"),
        ):
            if value is not None and value != state.get(field):
                state[field] = value
                changed.append(label)
                event_changes.append((field, value))
        if price is not None and price != state["price_rub"]:
            if price < 0:
                raise ValueError("price must be >= 0")
            if state["status"] == "cancelled":
                raise ValueError("Cannot change price on cancelled task")
            state["price_rub"] = price
            changed.append("price")
            event_changes.append(("price_rub", price))
        if status is not None and status != state["status"]:
            if status not in _VALID_STATUSES:
                raise ValueError(f"Invalid status: {status}")
            state["status"] = status
            changed.append("status")
            event_changes.append(("status", status))
            if status == "done" and not state.get("completed_at"):
                state["completed_at"] = _now()

        acceptance_touched = any(
            value is not None
            for value in (acceptance_command, acceptance_manifest, acceptance_required)
        )
        if acceptance_touched:
            current = state.get("acceptance") or {
                "command": "",
                "manifest_paths": [],
                "required": False,
            }
            acceptance = {
                "command": (
                    acceptance_command.strip()
                    if acceptance_command is not None
                    else current["command"]
                ),
                "manifest_paths": (
                    sorted(acceptance_manifest)
                    if acceptance_manifest is not None
                    else list(current["manifest_paths"])
                ),
                "required": (
                    bool(acceptance_required)
                    if acceptance_required is not None
                    else bool(current["required"])
                ),
            }
            if acceptance != current:
                state["acceptance"] = acceptance
                changed.append("acceptance_oracle")
                event_changes.append(("acceptance", acceptance))

        if worker_session_id is not None and worker_session_id != state.get("worker_session_id"):
            state["worker_session_id"] = worker_session_id
            event_changes.append(("worker_session_id", worker_session_id))
        if not event_changes:
            response = {
                "par": str(state["display_number"]),
                "project": state["project_id"],
                "updated": [],
                "old_status": old_status,
                "new_status": state["status"],
                "price_rub": state["price_rub"],
            }
            return {**response, **self._receipt(state)}

        state["updated_at"] = _now()
        state["sync_revision"] = int(state.get("sync_revision") or 0) + 1
        events = [
            {
                "event_id": str(uuid.uuid4()),
                "event_type": "task.updated",
                "stable_id": state["stable_id"],
                "project_id": state["project_id"],
                "display_number": state["display_number"],
                "base_revision": original.get("sync_revision", 0),
                "base_head": parent,
                "contour_id": contour_id,
                "occurred_at": state["updated_at"],
                "changes": {field: value},
            }
            for field, value in event_changes
        ]
        head = self._commit_generation(states, events, parent_head=parent)
        response = {
            "par": str(state["display_number"]),
            "project": state["project_id"],
            "updated": changed,
        }
        if changed not in (["acceptance_command"], ["acceptance_oracle"]):
            response.update(
                old_status=old_status,
                new_status=state["status"],
                price_rub=state["price_rub"],
            )
        return {**response, **self._receipt(state, head=head)}

    def task_update_if_current(
        self,
        identity: Mapping[str, Any],
        *,
        status: str,
        worker_session_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(identity, Mapping):
            raise ValueError("task identity must be a mapping")
        project_id = str(identity.get("project_id") or "")
        display_number = int(identity.get("display_number") or identity.get("par_number") or 0)
        state = self._find_state(str(display_number), project_id)
        if identity.get("stable_id") and identity["stable_id"] != state["stable_id"]:
            return {"ok": False, "error": "prevalidated task stable identity changed"}
        if int(identity.get("sync_revision", -1)) != int(state.get("sync_revision", 0)):
            return {"ok": False, "error": "prevalidated task revision changed"}
        expected_head = identity.get("canonical_head") or state["canonical_head"]
        updated = self.task_update(
            str(display_number),
            project=project_id,
            status=status,
            worker_session_id=worker_session_id,
            expected_head=str(expected_head),
        )
        current = self._find_state(str(display_number), project_id)
        source = current.get("source_row") or {}
        return {
            "ok": True,
            "task_id": source.get("row_id", current["stable_id"]),
            "par": str(display_number),
            "updated": updated["updated"],
            "new_status": current["status"],
            "sync_revision": current["sync_revision"],
            **self._receipt(current),
        }

    def link_commits_to_task(
        self,
        task_ref: str,
        commits: list[dict[str, Any]],
        project_id: str,
        expected_head: str | None = None,
    ) -> dict[str, Any]:
        parent = self._ensure_expected(expected_head)
        states = self._states()
        original = self._find_state(task_ref, project_id)
        state = states[original["stable_id"]]
        existing = list(state.get("git_commit_refs") or [])
        hashes = {
            item.get("hash") if isinstance(item, Mapping) else item
            for item in existing
        }
        additions = []
        for commit in commits:
            commit_hash = commit.get("hash") if isinstance(commit, Mapping) else commit
            if commit_hash not in hashes:
                additions.append(copy.deepcopy(commit))
                hashes.add(commit_hash)
        source = state.get("source_row") or {}
        if not additions:
            return {
                "ok": True,
                "added": 0,
                "task_id": source.get("row_id", state["stable_id"]),
                **self._receipt(state),
            }
        state["git_commit_refs"] = existing + additions
        state["sync_revision"] = int(state.get("sync_revision") or 0) + 1
        state["updated_at"] = _now()
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "task.commits-linked",
            "stable_id": state["stable_id"],
            "project_id": state["project_id"],
            "display_number": state["display_number"],
            "occurred_at": state["updated_at"],
            "changes": {"git_commit_refs": additions},
        }
        head = self._commit_generation(states, [event], parent_head=parent)
        return {
            "ok": True,
            "added": len(additions),
            "task_id": source.get("row_id", state["stable_id"]),
            **self._receipt(state, head=head),
        }

    def link_evidence_to_task(
        self,
        task_ref: str,
        evidence: Mapping[str, Any],
        *,
        project_id: str,
        expected_head: str | None = None,
    ) -> dict[str, Any]:
        parent = self._ensure_expected(expected_head)
        if not isinstance(evidence, Mapping) or any(
            not evidence.get(field) for field in _PROVENANCE_FIELDS
        ):
            raise ProvenanceError("task evidence requires path, anchor, commit, and content digest")
        try:
            evidence_id = str(uuid.UUID(str(evidence["stable_id"])))
        except (KeyError, ValueError) as exc:
            raise ProvenanceError("task evidence requires a stable UUID") from exc
        states = self._states()
        original = states.get(str(task_ref))
        if original is None:
            original = self._find_state(task_ref, project_id)
        elif original["project_id"] != project_id:
            raise ProvenanceError("task evidence crosses project identity")
        state = states[original["stable_id"]]
        if evidence.get("task_id") != state["stable_id"]:
            raise ProvenanceError("task evidence crosses stable task identity")
        uri = (
            f"orch://project/{project_id}/tasks/{state['stable_id']}/evidence/{evidence_id}"
        )
        record = {
            "record_type": "task.evidence",
            "schema_version": 1,
            "stable_id": evidence_id,
            "uri": uri,
            "task_id": state["stable_id"],
            "project_id": project_id,
            "kind": str(evidence.get("kind") or ""),
            **{field: str(evidence[field]) for field in _PROVENANCE_FIELDS},
        }
        evidence_path = self._evidence_path(record)
        if evidence_path.exists():
            if _read_json(evidence_path) != record:
                raise ProvenanceError("evidence id already names another source")
            if uri in state.get("evidence_refs", []):
                return {"ok": True, "added": 0, **self._receipt(state)}
        else:
            _write_json(evidence_path, record)
        state["evidence_refs"] = sorted({*state.get("evidence_refs", []), uri})
        state["sync_revision"] = int(state.get("sync_revision") or 0) + 1
        state["updated_at"] = _now()
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "task.evidence-linked",
            "stable_id": state["stable_id"],
            "project_id": project_id,
            "display_number": state["display_number"],
            "occurred_at": state["updated_at"],
            "changes": {"evidence_ref": uri},
        }
        head = self._commit_generation(states, [event], parent_head=parent)
        return {"ok": True, "added": 1, **self._receipt(state, head=head)}

    def apply_events(
        self,
        events: Sequence[Mapping[str, Any]],
        *,
        expected_head: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(events, Sequence) or isinstance(events, (str, bytes)) or not events:
            raise ValueError("events must be a non-empty sequence")
        parent = self._ensure_expected(expected_head)
        incoming = [_detached(event) for event in events]
        event_ids = [str(event.get("event_id") or "") for event in incoming]
        if any(not event_id for event_id in event_ids) or len(event_ids) != len(set(event_ids)):
            raise ConcurrentTaskUpdateError("event ids must be unique", event_ids=event_ids)
        for event in incoming:
            event_type = str(event.get("event_type") or "")
            if not event_type.startswith("task."):
                raise UnsupportedDomainError(f"unsupported task-store event: {event_type}")

        states = self._states()
        claimed = {
            (state["project_id"], state["display_number"]): state["stable_id"]
            for state in states.values()
        }
        created_claims: dict[tuple[str, int], str] = {}
        changed_fields: dict[str, set[str]] = defaultdict(set)
        for event in incoming:
            event_type = event["event_type"]
            stable_id = str(event.get("stable_id") or "")
            if event_type == "task.created":
                try:
                    stable_id = str(uuid.UUID(stable_id))
                    display = (str(event["project_id"]), int(event["display_number"]))
                except (KeyError, ValueError, TypeError) as exc:
                    raise IdentityConflictError("created event has an invalid identity") from exc
                owner = claimed.get(display) or created_claims.get(display)
                if owner is not None and owner != stable_id:
                    raise IdentityConflictError(
                        f"display #{display[1]} is already active in {display[0]}"
                    )
                if stable_id in states and (
                    states[stable_id]["project_id"], states[stable_id]["display_number"]
                ) != display:
                    raise IdentityConflictError("stable task identity changed")
                created_claims[display] = stable_id
                continue
            if event_type != "task.updated":
                raise UnsupportedDomainError(f"unsupported task-store event: {event_type}")
            if stable_id not in states:
                raise IdentityConflictError(f"updated task {stable_id} does not exist")
            state = states[stable_id]
            if (
                event.get("project_id") != state["project_id"]
                or int(event.get("display_number") or 0) != state["display_number"]
            ):
                raise IdentityConflictError("event task identity does not match canonical state")
            changes = event.get("changes")
            if not isinstance(changes, dict) or not changes:
                raise ConcurrentTaskUpdateError("update event has no changes", event_ids=event_ids)
            overlap = changed_fields[stable_id] & changes.keys()
            if overlap:
                raise ConcurrentTaskUpdateError(
                    f"concurrent events change the same fields: {', '.join(sorted(overlap))}",
                    event_ids=event_ids,
                )
            changed_fields[stable_id].update(changes)

        for event in incoming:
            stable_id = str(event["stable_id"])
            if event["event_type"] == "task.created":
                record = event.get("record")
                if not isinstance(record, dict):
                    raise IdentityConflictError("created event has no task record")
                now = str(event.get("occurred_at") or _now())
                states[stable_id] = {
                    "record_type": "task.state",
                    "schema_version": 1,
                    "stable_id": stable_id,
                    "uri": f"orch://project/{event['project_id']}/tasks/{stable_id}/state",
                    "project_id": event["project_id"],
                    "display_number": int(event["display_number"]),
                    "display_ref": f"#{int(event['display_number'])}",
                    "title": str(record.get("title") or ""),
                    "description": str(record.get("description") or ""),
                    "price_rub": int(record.get("price_rub") or 0),
                    "status": str(record.get("status") or "new"),
                    "assignee": str(record.get("assignee") or ""),
                    "priority": int(
                        2 if record.get("priority") is None else record["priority"]
                    ),
                    "scope": "",
                    "worker_session_id": None,
                    "acceptance": {"command": "", "manifest_paths": [], "required": False},
                    "evidence_refs": [],
                    "git_commit_refs": [],
                    "created_at": now,
                    "updated_at": now,
                    "completed_at": None,
                    "sync_revision": 0,
                }
                continue
            state = states[stable_id]
            changes = event["changes"]
            allowed = {"title", "description", "price_rub", "status", "assignee", "priority"}
            unknown = changes.keys() - allowed
            if unknown:
                raise UnsupportedDomainError(
                    f"unsupported task fields: {', '.join(sorted(unknown))}"
                )
            state.update(copy.deepcopy(changes))
            state["updated_at"] = str(event.get("occurred_at") or _now())
            state["sync_revision"] = int(state.get("sync_revision") or 0) + 1

        head = self._commit_generation(states, incoming, parent_head=parent)
        return {
            "status": "merged",
            "event_ids": event_ids,
            "canonical_head": head,
            "projection_head": head,
        }

    def _event_groups(self) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for path in sorted(self.canonical_root.rglob("events/*.json")):
            event = _read_json(path)
            if event.get("event_type") == "task.migrated":
                continue
            head = str(event.get("canonical_head") or "")
            if not head:
                raise MigrationManifestError(f"event has no canonical head: {path}")
            groups[head].append(event)
        return groups

    def replay(self, *, head: str) -> dict[str, Any]:
        """Rebuild current state and projection from the immutable manifest/event chain."""

        manifest = self._initial_manifest()
        initial_head = str(manifest["canonical_head"])
        states = self._initial_states(manifest)
        if head != initial_head:
            groups = self._event_groups()
            chain: list[list[dict[str, Any]]] = []
            cursor = head
            seen: set[str] = set()
            while cursor != initial_head:
                if cursor in seen or cursor not in groups:
                    raise MigrationManifestError(f"canonical head is not replayable: {head}")
                seen.add(cursor)
                group = groups[cursor]
                parents = {str(event.get("parent_head") or "") for event in group}
                if len(parents) != 1 or not next(iter(parents)):
                    raise MigrationManifestError(f"canonical generation has mixed parents: {cursor}")
                chain.append(group)
                cursor = next(iter(parents))
            for group in reversed(chain):
                for event in sorted(group, key=lambda item: str(item["event_id"])):
                    result_state = event.get("result_state")
                    if not isinstance(result_state, dict):
                        raise MigrationManifestError("event lacks replay result state")
                    states[str(event["stable_id"])] = copy.deepcopy(result_state)
        self._write_states(states, head)
        return {
            "canonical_head": head,
            "projection_head": head,
            "task_count": len(states),
        }

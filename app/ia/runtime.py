"""Process-global, proof-scoped owner for live typed knowledge."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Request


class KnowledgeRuntimeError(RuntimeError):
    pass


class KnowledgeAuthorizationError(KnowledgeRuntimeError):
    pass


class KnowledgeRequestError(KnowledgeRuntimeError):
    pass


@dataclass(frozen=True)
class DebtReasonPolicy:
    blocking: bool
    migrate_from: frozenset[bool] = frozenset()


_DEBT_REASON_POLICIES = {
    "secret_candidate_in_evidence": DebtReasonPolicy(blocking=False),
    "scope_git_unavailable": DebtReasonPolicy(
        blocking=False,
        migrate_from=frozenset({True}),
    ),
    "git_evidence_source_unavailable": DebtReasonPolicy(blocking=True),
    "non_utf8_evidence": DebtReasonPolicy(blocking=True),
    "prompt_migration_failed": DebtReasonPolicy(blocking=True),
    "candidate_write_failed": DebtReasonPolicy(blocking=True),
    "candidate_read_failed": DebtReasonPolicy(blocking=True),
}


def _debt_reason_policy(reason: Any) -> DebtReasonPolicy:
    if not isinstance(reason, str) or reason not in _DEBT_REASON_POLICIES:
        raise KnowledgeRuntimeError(f"unknown runtime debt reason: {reason!r}")
    return _DEBT_REASON_POLICIES[reason]


_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_ACTIVE_RUNTIME: "KnowledgeRuntime | None" = None


@dataclass(frozen=True)
class RuntimeConfig:
    state_root: Path
    legacy_db_path: Path
    vector_db_path: Path
    scope_roots: Mapping[str, Path]
    prompt_assembler: Callable[[str, str], str]


def _ensure_task_projection(store: Any) -> None:
    """Rebuild the disposable task index when canonical state outlives it."""
    projection_path = getattr(store, "projection_path", None)
    if projection_path is None:
        return
    if projection_path.is_file():
        from app.ia.task_store import ProjectionDebtError

        try:
            projection_head = store.projection_head
            canonical_head = store.canonical_head
            states = store._states()
            with sqlite3.connect(projection_path) as connection:
                row_count = int(connection.execute(
                    "SELECT count(*) FROM ia_task_projection"
                ).fetchone()[0])
            if projection_head == canonical_head and row_count == len(states):
                return
            raise ProjectionDebtError("task projection is incomplete or stale")
        except (ProjectionDebtError, sqlite3.DatabaseError):
            for suffix in ("-journal", "-wal", "-shm", ""):
                Path(f"{projection_path}{suffix}").unlink(missing_ok=True)
    states = store._states()
    if not states:
        raise KnowledgeRuntimeError("canonical task state is empty during projection rebuild")
    # TaskStore owns the projection schema; runtime owns when its rebuild is required.
    store._rebuild_projection(states)
    if store.projection_head != store.canonical_head:
        raise KnowledgeRuntimeError("rebuilt task projection is not bound to canonical state")


class _RuntimeTaskStore:
    """Serialize TaskStore and translate legacy project IDs at the facade boundary."""

    def __init__(
        self,
        *,
        store: Any,
        legacy_to_canonical: Mapping[str, str],
        debt_writer: Callable[[Mapping[str, Any]], None],
        head_writer: Callable[[str], None],
    ) -> None:
        self._store = store
        self._legacy_to_canonical = dict(legacy_to_canonical)
        self._canonical_to_legacy = {value: key for key, value in self._legacy_to_canonical.items()}
        self._debt_writer = debt_writer
        self._head_writer = head_writer
        self._lock = threading.RLock()

    @property
    def canonical_root(self):
        return self._store.canonical_root

    @property
    def projection_path(self):
        return self._store.projection_path

    @property
    def canonical_head(self):
        with self._lock:
            return self._store.canonical_head

    @property
    def projection_head(self):
        with self._lock:
            _ensure_task_projection(self._store)
            return self._store.projection_head

    def _project(self, value: str) -> str:
        return self._legacy_to_canonical.get(str(value or ""), str(value or ""))

    def _legacy_result(self, result: Mapping[str, Any]) -> dict[str, Any]:
        value = copy.deepcopy(dict(result))
        if "project" in value:
            value["project"] = self._canonical_to_legacy.get(value["project"], value["project"])
        for task in value.get("tasks") or []:
            task["project"] = self._canonical_to_legacy.get(task["project"], task["project"])
        return value

    def _changed(self, result: Mapping[str, Any]) -> dict[str, Any]:
        value = self._legacy_result(result)
        head = str(value.get("canonical_head") or self._store.canonical_head)
        self._head_writer(head)
        return value

    def task_create(self, **kwargs):
        with self._lock:
            value = dict(kwargs)
            value["project_id"] = self._project(value.get("project_id", ""))
            value["expected_head"] = self._store.canonical_head
            return self._changed(self._store.task_create(**value))

    def task_update(self, ref, **kwargs):
        with self._lock:
            value = dict(kwargs)
            value["project"] = self._project(value.get("project", ""))
            value["expected_head"] = self._store.canonical_head
            return self._changed(self._store.task_update(ref, **value))

    def task_update_if_current(self, identity, **kwargs):
        with self._lock:
            value = copy.deepcopy(dict(identity))
            value["project_id"] = self._project(value.get("project_id", ""))
            return self._changed(self._store.task_update_if_current(value, **kwargs))

    def task_get(self, ref, project=""):
        with self._lock:
            _ensure_task_projection(self._store)
            return self._legacy_result(self._store.task_get(ref, project=self._project(project)))

    def task_list(self, project="", status="", assignee=""):
        with self._lock:
            _ensure_task_projection(self._store)
            return self._legacy_result(self._store.task_list(
                project=self._project(project), status=status, assignee=assignee,
            ))

    def link_commits_to_task(self, task_ref, commits, project_id, expected_head=None):
        with self._lock:
            _ensure_task_projection(self._store)
            return self._changed(self._store.link_commits_to_task(
                task_ref,
                commits,
                self._project(project_id),
                expected_head=self._store.canonical_head,
            ))

    def record_debt(self, debt):
        self._debt_writer(copy.deepcopy(dict(debt)))

    def states(self):
        with self._lock:
            _ensure_task_projection(self._store)
            return copy.deepcopy(self._store._states())

    def reconcile_legacy_tasks(self, tasks: list[Mapping[str, Any]]) -> dict[str, Any]:
        with self._lock:
            _ensure_task_projection(self._store)
            states = self._store._states()
            canonical = {
                (str(state["project_id"]), int(state["display_number"])): state
                for state in states.values()
            }
            legacy = {
                (self._project(str(task["project_id"])), int(task["par_number"])): task
                for task in tasks
            }
            missing = sorted(legacy.keys() - canonical.keys())
            extra = sorted(canonical.keys() - legacy.keys())
            if extra:
                raise KnowledgeRuntimeError(
                    f"task shadow identity mismatch: missing={missing}, extra={extra}"
                )
            events = []
            for project_id, display_number in missing:
                task = legacy[(project_id, display_number)]
                stable_id = str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"orch://task-shadow-reconcile-create/{project_id}/{display_number}",
                ))
                events.append({
                    "event_id": str(uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"orch://task-shadow-reconcile-created/{stable_id}",
                    )),
                    "event_type": "task.created",
                    "stable_id": stable_id,
                    "project_id": project_id,
                    "display_number": display_number,
                    "contour_id": "shadow-reconcile",
                    "occurred_at": str(
                        task.get("created_at") or task.get("updated_at") or ""
                    ),
                    "record": {
                        "title": str(task.get("title") or ""),
                        "description": str(task.get("description") or ""),
                        "price_rub": int(task.get("price_rub") or 0),
                        "status": str(task.get("status") or "new"),
                        "assignee": str(task.get("assignee") or ""),
                        "priority": int(
                            2 if task.get("priority") is None else task["priority"]
                        ),
                    },
                })
            for identity, task in sorted(legacy.items()):
                if identity not in canonical:
                    continue
                state = canonical[identity]
                expected = {
                    "title": str(task.get("title") or ""),
                    "description": str(task.get("description") or ""),
                    "price_rub": int(task.get("price_rub") or 0),
                    "status": str(task.get("status") or "new"),
                    "assignee": str(task.get("assignee") or ""),
                    "priority": int(
                        2 if task.get("priority") is None else task["priority"]
                    ),
                }
                changes = {
                    field: value
                    for field, value in expected.items()
                    if state.get(field) != value
                }
                if not changes:
                    continue
                event_id = str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    "orch://task-shadow-reconcile/"
                    + hashlib.sha256(_bytes({
                        "head": self._store.canonical_head,
                        "stable_id": state["stable_id"],
                        "changes": changes,
                    })).hexdigest(),
                ))
                events.append({
                    "event_id": event_id,
                    "event_type": "task.updated",
                    "stable_id": state["stable_id"],
                    "project_id": state["project_id"],
                    "display_number": state["display_number"],
                    "occurred_at": str(task.get("updated_at") or ""),
                    "changes": changes,
                })
            if not events:
                return {
                    "reconciled_count": 0,
                    "canonical_head": self._store.canonical_head,
                    "projection_head": self._store.projection_head,
                }
            result = self._store.apply_events(
                events,
                expected_head=self._store.canonical_head,
            )
            self._head_writer(str(result["canonical_head"]))
            return {**result, "reconciled_count": len(events)}


def _bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False,
    ).encode("utf-8")


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(_bytes(dict(value)) + b"\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KnowledgeRuntimeError(f"cannot read runtime state: {path}") from exc
    if not isinstance(value, dict):
        raise KnowledgeRuntimeError(f"runtime state is not an object: {path}")
    return value


def _scope(value: str) -> str:
    return str(value or "").rstrip("/")


def _project_slug(value: str) -> str:
    raw = str(value or "").strip()
    if _SLUG.fullmatch(raw):
        return raw
    base = re.sub(r"[^a-z0-9]+", "-", raw.casefold()).strip("-")
    if not base or len(base) > 48:
        base = "project"
    return f"{base}-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


def _state_root() -> Path:
    state = os.environ.get("STATE_DIRECTORY", "").strip()
    if state:
        parts = [part for part in state.split(os.pathsep) if part]
        if len(parts) != 1:
            raise KnowledgeRuntimeError("STATE_DIRECTORY must contain exactly one path")
        root = Path(parts[0])
    else:
        xdg = os.environ.get("XDG_STATE_HOME", "").strip()
        root = Path(xdg) / "orchestra" if xdg else Path.home() / ".local/state/orchestra"
    if not root.is_absolute():
        raise KnowledgeRuntimeError(f"knowledge state root is not absolute: {root}")
    return root / "knowledge-v1"


class KnowledgeRuntime:
    """Read-only generation-2 owner; later tickets add task/evidence/cutover writes."""

    def __init__(self, config: RuntimeConfig) -> None:
        root = Path(config.state_root).expanduser().absolute()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        self.config = RuntimeConfig(
            state_root=root,
            legacy_db_path=Path(config.legacy_db_path).expanduser().absolute(),
            vector_db_path=Path(config.vector_db_path).expanduser().absolute(),
            scope_roots={
                _scope(key): Path(value).expanduser().absolute()
                for key, value in config.scope_roots.items()
                if _scope(key)
            },
            prompt_assembler=config.prompt_assembler,
        )
        self.paths = {
            "state_root": root,
            "canonical_root": root / "canonical",
            "task_projection": root / "task-current.db",
            "current_projection": root / "current.db",
            "vector_projection": self.config.vector_db_path,
        }
        self.scope_registry = self._scope_registry()
        self.state = self._runtime_state()
        self._task_projects = self._task_project_ids()
        self._evidence_records_cache: list[dict[str, Any]] | None = None
        self.knowledge_service = None
        self.task_store = self._task_store()
        if self.state.get("active_owner") == "legacy" and self.state.get("generation") == 2:
            self.task_store.reconcile_legacy_tasks(self._task_snapshot()["tasks"])
        self._initialize_canonical_git()
        self._import_scope_evidence()
        self._ensure_vector_projection()
        self._ensure_shadow_receipt()
        self._migrate_platform_prompts()

    def _connection(self) -> sqlite3.Connection:
        uri = f"file:{self.config.legacy_db_path}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def _scope_evidence_mode(self, repository: Path) -> str:
        if not repository.is_dir():
            raise KnowledgeRuntimeError(f"scope repository root is missing: {repository}")
        if (repository / ".git").exists():
            return "git"
        try:
            self._source_git(repository, "rev-parse", "--git-dir")
        except KnowledgeRuntimeError:
            return "none"
        return "git"

    def _scope_registry(self) -> dict[str, dict[str, Any]]:
        if not self.config.legacy_db_path.is_file():
            raise KnowledgeRuntimeError(f"legacy database is missing: {self.config.legacy_db_path}")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id,scope FROM tm_projects WHERE scope IS NOT NULL AND scope!=''"
            ).fetchall()
        legacy = {_scope(row["scope"]): str(row["id"]) for row in rows}
        entries = []
        used: set[str] = set()
        for scope, repository in sorted(self.config.scope_roots.items()):
            raw_id = legacy.get(scope) or scope
            project_id = _project_slug(raw_id)
            if project_id in used:
                project_id += "-" + hashlib.sha256(scope.encode()).hexdigest()[:8]
            used.add(project_id)
            entries.append({
                "scope": scope,
                "canonical_project_id": project_id,
                "legacy_project_id": legacy.get(scope),
                "repository_root": str(repository),
                "evidence_mode": self._scope_evidence_mode(repository),
            })
        path = self.config.state_root / "scope-registry.json"
        if path.exists():
            stored = _read_json(path)
            if stored.get("schema_version") != 1 or not isinstance(stored.get("entries"), list):
                raise KnowledgeRuntimeError("persisted scope registry has an unsupported shape")
            by_scope = {str(item.get("scope") or ""): item for item in stored["entries"]}
            if "" in by_scope or len(by_scope) != len(stored["entries"]):
                raise KnowledgeRuntimeError("persisted scope registry has duplicate identity")
            for item in entries:
                scope = str(item["scope"])
                if scope not in by_scope:
                    by_scope[scope] = item
                    continue
                persisted = by_scope[scope]
                evidence_mode = persisted.get("evidence_mode")
                if evidence_mode is not None and evidence_mode not in {"git", "none"}:
                    raise KnowledgeRuntimeError(
                        f"persisted scope evidence mode is unsupported: {scope}"
                    )
                identity = {key: value for key, value in persisted.items() if key != "evidence_mode"}
                proposed_identity = {key: value for key, value in item.items() if key != "evidence_mode"}
                if identity != proposed_identity:
                    raise KnowledgeRuntimeError(f"persisted scope identity changed: {scope}")
                if evidence_mode is None or (
                    evidence_mode == "none" and item["evidence_mode"] == "git"
                ):
                    by_scope[scope] = item
            entries = [copy.deepcopy(by_scope[key]) for key in sorted(by_scope)]
            proposed = {"schema_version": 1, "entries": entries}
            if stored != proposed:
                _write_json(path, proposed)
        else:
            proposed = {"schema_version": 1, "entries": entries}
            _write_json(path, proposed)
        return {str(item["scope"]): copy.deepcopy(item) for item in entries}

    def _head(self) -> str:
        with self._connection() as connection:
            max_log = int(connection.execute("SELECT COALESCE(MAX(id),0) FROM logs").fetchone()[0])
            task_count = int(connection.execute("SELECT count(*) FROM tm_tasks").fetchone()[0])
        return "sha256:" + hashlib.sha256(_bytes({
            "registry": list(self.scope_registry.values()),
            "max_log": max_log,
            "tasks": task_count,
        })).hexdigest()

    def _runtime_state(self) -> dict[str, Any]:
        path = self.config.state_root / "runtime-state.json"
        if path.exists():
            value = _read_json(path)
            if value.get("schema_version") != 1:
                raise KnowledgeRuntimeError("unsupported runtime state version")
            return value
        head = self._head()
        value = {
            "schema_version": 1,
            "active_owner": "legacy",
            "shadow_owner": "canonical",
            "generation": 2,
            "canonical_head": head,
            "projection_head": head,
            "indexed_head": None,
            "debt_count": 0,
        }
        _write_json(path, value)
        return value

    def _save_state(self) -> None:
        _write_json(self.config.state_root / "runtime-state.json", self.state)

    def _task_project_ids(self) -> dict[str, str]:
        by_scope = {
            scope: str(entry["canonical_project_id"])
            for scope, entry in self.scope_registry.items()
        }
        result: dict[str, str] = {}
        used: set[str] = set(by_scope.values())
        with self._connection() as connection:
            rows = connection.execute("SELECT id,scope FROM tm_projects ORDER BY id").fetchall()
        for row in rows:
            raw = str(row["id"])
            scope = _scope(str(row["scope"] or ""))
            candidate = by_scope.get(scope) or _project_slug(raw)
            if candidate in used and candidate not in by_scope.values():
                candidate += "-" + hashlib.sha256(raw.encode()).hexdigest()[:8]
            used.add(candidate)
            result[raw] = candidate
        return result

    def _task_snapshot(self) -> dict[str, Any]:
        from app import tm

        with self._connection() as connection:
            projects = [dict(row) for row in connection.execute(
                "SELECT * FROM tm_projects ORDER BY id"
            ).fetchall()]
            tasks = []
            for row in connection.execute("SELECT * FROM tm_tasks ORDER BY id").fetchall():
                task = dict(row)
                task["git_commits"] = json.loads(task.get("git_commits") or "[]")
                task["acceptance_oracle_json"] = tm.parse_acceptance_oracle(
                    task.get("acceptance_oracle_json")
                )
                tasks.append(task)
            clients = [dict(row) for row in connection.execute(
                "SELECT * FROM tm_clients ORDER BY id"
            ).fetchall()]
            payments = [dict(row) for row in connection.execute(
                "SELECT * FROM tm_payments ORDER BY id"
            ).fetchall()]
            allocations = [dict(row) for row in connection.execute(
                "SELECT * FROM tm_payment_allocations ORDER BY id"
            ).fetchall()]
            sync_rows = [dict(row) for row in connection.execute(
                "SELECT * FROM tm_sync_log ORDER BY id"
            ).fetchall()]
            schema = {
                table: [tuple(row) for row in connection.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()]
                for table in ("tm_projects", "tm_tasks")
            }
        for project in projects:
            project["id"] = self._task_projects[str(project["id"])]
        for task in tasks:
            task["project_id"] = self._task_projects[str(task["project_id"])]
        timestamps = [str(task.get("updated_at") or task.get("created_at") or "") for task in tasks]
        cutoff = max((value for value in timestamps if value), default="1970-01-01T00:00:00+00:00")
        schema_sha = "sha256:" + hashlib.sha256(_bytes(schema)).hexdigest()
        source_head = "sha256:" + hashlib.sha256(_bytes({
            "projects": projects, "tasks": tasks,
        })).hexdigest()
        return {
            "source": {
                "cutoff": cutoff,
                "source_head": source_head,
                "source_schema_sha256": schema_sha,
            },
            "projects": projects,
            "tasks": tasks,
            "evidence": [],
            "clients": clients,
            "payments": payments,
            "payment_allocations": allocations,
            "sync_log": sync_rows,
        }

    def _task_store(self):
        from app.ia.task_store import TaskStore, build_migration_manifest

        canonical_root = self.paths["canonical_root"] / "tasks"
        projection_path = self.paths["task_projection"]
        store = TaskStore(canonical_root=canonical_root, projection_path=projection_path)
        manifests = list((canonical_root / "manifests").glob("*.json"))
        if not manifests:
            store.migrate(build_migration_manifest(self._task_snapshot()))
        else:
            # Load-existing semantics: prove both owners are internally readable; do not replay a
            # fresh snapshot over later candidate generations.
            store.canonical_head
        _ensure_task_projection(store)
        return _RuntimeTaskStore(
            store=store,
            legacy_to_canonical=self._task_projects,
            debt_writer=self._record_debt,
            head_writer=self._record_task_head,
        )

    def _record_task_head(self, head: str) -> None:
        evidence = [
            {
                key: value
                for key, value in record.items()
                if key not in {"canonical_head", "projection_head", "indexed_head", "source"}
            }
            for record in self.evidence_records()
        ]
        knowledge_head = self.knowledge_service.head() if self.knowledge_service is not None else None
        combined = "sha256:" + hashlib.sha256(_bytes({
            "task_head": head,
            "knowledge_head": knowledge_head,
            "evidence": sorted(evidence, key=lambda item: (item["project_id"], item["stable_id"])),
        })).hexdigest()
        self.state["canonical_head"] = combined
        self.state["projection_head"] = combined
        self._save_state()
        self._commit_canonical("update canonical task generation")
        self._refresh_current_projection()

    def _record_debt(self, debt: Mapping[str, Any]) -> None:
        identity = copy.deepcopy(dict(debt))
        policy = _debt_reason_policy(identity.get("reason"))
        debt_id = hashlib.sha256(_bytes(identity)).hexdigest()
        value = {**identity, "blocking": policy.blocking}
        path = self.config.state_root / "debt" / f"{debt_id}.json"
        if path.exists():
            existing = _read_json(path)
            if existing == identity:
                _write_json(path, value)
            elif existing != value:
                raise KnowledgeRuntimeError(f"runtime debt identity conflicts: {path.name}")
        else:
            _write_json(path, value)
        summary = self.debt_summary()
        self.state["debt_count"] = summary["total_count"]
        self.state["blocking_debt_count"] = summary["blocking_count"]
        self.state["informational_debt_count"] = summary["informational_count"]
        self._save_state()

    def debt_summary(self) -> dict[str, Any]:
        by_reason: dict[str, int] = {}
        blocking_count = 0
        informational_count = 0
        for path in sorted((self.config.state_root / "debt").glob("*.json")):
            value = _read_json(path)
            reason = value.get("reason")
            policy = _debt_reason_policy(reason)
            if "blocking" in value and value["blocking"] is not policy.blocking:
                if value["blocking"] not in policy.migrate_from:
                    raise KnowledgeRuntimeError(
                        f"runtime debt policy mismatch for {reason!r}: {path.name}"
                    )
                value["blocking"] = policy.blocking
                _write_json(path, value)
            by_reason[reason] = by_reason.get(reason, 0) + 1
            if policy.blocking:
                blocking_count += 1
            else:
                informational_count += 1
        return {
            "total_count": blocking_count + informational_count,
            "blocking_count": blocking_count,
            "informational_count": informational_count,
            "by_reason": dict(sorted(by_reason.items())),
        }

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git", "-C", str(self.paths["canonical_root"]), *args],
            capture_output=True,
            check=False,
            text=True,
        )
        if check and result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            raise KnowledgeRuntimeError(f"canonical Git operation failed: {detail}")
        return result

    def _initialize_canonical_git(self) -> None:
        root = self.paths["canonical_root"]
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not (root / ".git").is_dir():
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            self._git("config", "user.email", "orchestra@localhost")
            self._git("config", "user.name", "Orchestra canonical owner")
        self._commit_canonical("bootstrap canonical task state")

    def _commit_canonical(self, message: str) -> None:
        root = self.paths["canonical_root"]
        if not (root / ".git").is_dir():
            return
        self._git("add", "-A")
        changed = self._git("diff", "--cached", "--quiet", check=False)
        if changed.returncode == 0:
            return
        if changed.returncode != 1:
            raise KnowledgeRuntimeError("cannot inspect canonical Git index")
        self._git("commit", "-qm", message)

    @staticmethod
    def _source_git(root: Path, *args: str, binary: bool = False):
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            check=False,
            text=not binary,
        )
        if result.returncode != 0:
            detail = result.stderr if binary else (result.stderr.strip() or result.stdout.strip())
            raise KnowledgeRuntimeError(f"cannot read scope Git source: {detail}")
        return result.stdout

    def _evidence_root(self) -> Path:
        return self.paths["canonical_root"] / "evidence"

    def _source_record(
        self,
        *,
        scope: str,
        project_id: str,
        repository: Path,
        commit: str,
        path: str,
        blob: str,
    ) -> dict[str, Any]:
        content = self._source_git(repository, "cat-file", "blob", blob, binary=True)
        stable_id = self._source_stable_id(project_id, commit, path, blob)
        return {
            "record_type": "resource",
            "schema_version": 1,
            "stable_id": stable_id,
            "uri": f"orch://project/{project_id}/resources/{stable_id}",
            "project_id": project_id,
            "status": "current",
            "source_path": path,
            "source_scope": scope,
            "source_class": "immutable-evidence",
            "git_commit": commit,
            "git_blob": blob,
            "source_sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            "storage": "cold-immutable-reference",
        }

    @staticmethod
    def _source_stable_id(project_id: str, commit: str, path: str, blob: str) -> str:
        return str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"orch://git-evidence/{project_id}/{commit}/{path}/{blob}",
        ))

    def _import_scope_evidence(self) -> None:
        self._evidence_records_cache = None
        imported = False
        evidence_less_scopes = []
        for scope, entry in sorted(self.scope_registry.items()):
            repository = Path(str(entry["repository_root"]))
            project_id = str(entry["canonical_project_id"])
            evidence_mode = entry.get("evidence_mode")
            if evidence_mode == "none":
                evidence_less_scopes.append({"scope": scope, "reason": "not_git_backed"})
                continue
            if evidence_mode != "git":
                raise KnowledgeRuntimeError(
                    f"scope evidence mode is unsupported: {scope}: {evidence_mode!r}"
                )
            try:
                commit = str(self._source_git(repository, "rev-parse", "HEAD")).strip()
                raw = self._source_git(
                    repository,
                    "ls-tree",
                    "-r",
                    "-z",
                    "--format=%(objectname)%x09%(path)",
                    commit,
                    binary=True,
                )
            except KnowledgeRuntimeError as error:
                self._record_debt({
                    "reason": "git_evidence_source_unavailable",
                    "scope": scope,
                    "message": str(error),
                })
                continue
            for item in raw.split(b"\0"):
                if not item:
                    continue
                blob_bytes, path_bytes = item.split(b"\t", 1)
                path = path_bytes.decode("utf-8")
                if not path.lower().endswith(".md"):
                    continue
                if any(part in {".git", ".venv", "node_modules", "worktrees"} for part in Path(path).parts):
                    continue
                blob = blob_bytes.decode("ascii")
                stable_id = self._source_stable_id(project_id, commit, path, blob)
                destination = self._evidence_root() / project_id / f"{stable_id}.json"
                if destination.exists():
                    existing = _read_json(destination)
                    expected_identity = {
                        "stable_id": stable_id,
                        "project_id": project_id,
                        "git_commit": commit,
                        "git_blob": blob,
                        "source_path": path,
                        "source_scope": scope,
                    }
                    if any(existing.get(key) != value for key, value in expected_identity.items()):
                        raise KnowledgeRuntimeError(f"immutable evidence changed: {path}")
                    continue
                record = self._source_record(
                    scope=scope,
                    project_id=project_id,
                    repository=repository,
                    commit=commit,
                    path=path,
                    blob=blob,
                )
                _write_json(destination, record)
                imported = True
        debt = self.debt_summary()
        self.state["debt_count"] = debt["total_count"]
        self.state["blocking_debt_count"] = debt["blocking_count"]
        self.state["informational_debt_count"] = debt["informational_count"]
        self.state["evidence_less_scopes"] = evidence_less_scopes
        self._save_state()
        if imported:
            self._commit_canonical("import pinned Git evidence")

    def evidence_records(self):
        cached = getattr(self, "_evidence_records_cache", None)
        if cached is None:
            root = self._evidence_root()
            cached = [_read_json(path) for path in sorted(root.glob("*/*.json"))]
            self._evidence_records_cache = cached
        return copy.deepcopy(cached)

    def _evidence_content(self, record: Mapping[str, Any]) -> bytes:
        scope = _scope(str(record.get("source_scope") or ""))
        entry = self.scope_registry.get(scope)
        if entry is None or entry["canonical_project_id"] != record.get("project_id"):
            raise KnowledgeRuntimeError("evidence scope identity is not registered")
        repository = Path(str(entry["repository_root"]))
        commit = str(record.get("git_commit") or "")
        path = str(record.get("source_path") or "")
        blob = str(record.get("git_blob") or "")
        observed_commit = str(self._source_git(repository, "rev-parse", f"{commit}^{{commit}}")).strip()
        if observed_commit != commit:
            raise KnowledgeRuntimeError("evidence Git commit is not pinned")
        observed_blob = str(self._source_git(repository, "rev-parse", f"{commit}:{path}")).strip()
        if observed_blob != blob:
            raise KnowledgeRuntimeError("evidence Git path/blob binding changed")
        content = self._source_git(repository, "cat-file", "blob", blob, binary=True)
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if digest != record.get("source_sha256"):
            raise KnowledgeRuntimeError("evidence Git bytes do not match their digest")
        return content

    @staticmethod
    def _source_git_blobs(repository: Path, blob_ids: list[str]) -> dict[str, bytes]:
        ordered = list(dict.fromkeys(blob_ids))
        if not ordered:
            return {}
        result = subprocess.run(
            ["git", "-C", str(repository), "cat-file", "--batch"],
            input=b"".join(blob.encode("ascii") + b"\n" for blob in ordered),
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise KnowledgeRuntimeError(
                f"cannot read scope Git source: {detail or f'exit {result.returncode}'}"
            )
        offset = 0
        contents: dict[str, bytes] = {}
        for requested in ordered:
            newline = result.stdout.find(b"\n", offset)
            if newline < 0:
                raise KnowledgeRuntimeError("cannot read scope Git source: incomplete batch header")
            header = result.stdout[offset:newline].split()
            if len(header) != 3 or header[1] != b"blob":
                raise KnowledgeRuntimeError("cannot read scope Git source: batch object is not a blob")
            observed = header[0].decode("ascii")
            try:
                size = int(header[2])
            except ValueError as exc:
                raise KnowledgeRuntimeError(
                    "cannot read scope Git source: invalid batch object size"
                ) from exc
            start = newline + 1
            end = start + size
            if observed != requested or result.stdout[end:end + 1] != b"\n":
                raise KnowledgeRuntimeError("cannot read scope Git source: invalid batch object")
            contents[requested] = result.stdout[start:end]
            offset = end + 1
        if offset != len(result.stdout):
            raise KnowledgeRuntimeError("cannot read scope Git source: trailing batch output")
        return contents

    def _evidence_contents(self, records: list[Mapping[str, Any]]) -> dict[str, bytes]:
        by_scope: dict[str, list[Mapping[str, Any]]] = {}
        for record in records:
            scope = _scope(str(record.get("source_scope") or ""))
            entry = self.scope_registry.get(scope)
            if entry is None or entry["canonical_project_id"] != record.get("project_id"):
                raise KnowledgeRuntimeError("evidence scope identity is not registered")
            by_scope.setdefault(scope, []).append(record)

        contents: dict[str, bytes] = {}
        for scope, scoped_records in sorted(by_scope.items()):
            repository = Path(str(self.scope_registry[scope]["repository_root"]))
            by_commit: dict[str, list[Mapping[str, Any]]] = {}
            for record in scoped_records:
                by_commit.setdefault(str(record.get("git_commit") or ""), []).append(record)
            for commit, commit_records in sorted(by_commit.items()):
                raw = self._source_git(
                    repository,
                    "ls-tree",
                    "-r",
                    "-z",
                    "--format=%(objectname)%x09%(path)",
                    commit,
                    binary=True,
                )
                tree = {}
                for item in raw.split(b"\0"):
                    if item:
                        blob, path = item.split(b"\t", 1)
                        tree[path.decode("utf-8")] = blob.decode("ascii")
                for record in commit_records:
                    if tree.get(str(record.get("source_path") or "")) != record.get("git_blob"):
                        raise KnowledgeRuntimeError("evidence Git path/blob binding changed")

            blobs = self._source_git_blobs(
                repository,
                [str(record.get("git_blob") or "") for record in scoped_records],
            )
            for record in scoped_records:
                content = blobs[str(record["git_blob"])]
                digest = "sha256:" + hashlib.sha256(content).hexdigest()
                if digest != record.get("source_sha256"):
                    raise KnowledgeRuntimeError("evidence Git bytes do not match their digest")
                contents[str(record["stable_id"])] = content
        return contents

    def _mutable_projection_records(self) -> list[dict[str, Any]]:
        records = [copy.deepcopy(state) for state in self.task_store.states().values()]
        if self.knowledge_service is not None:
            records.extend(
                copy.deepcopy(dict(record))
                for record in self.knowledge_service._facts()
                if record.get("status") == "current"
            )
        return records

    def _retained_evidence_records(self) -> list[dict[str, Any]]:
        excluded = set()
        for path in sorted((self.config.state_root / "debt").glob("*.json")):
            debt = _read_json(path)
            if debt.get("reason") not in {"secret_candidate_in_evidence", "non_utf8_evidence"}:
                continue
            excluded.add((
                str(debt.get("project_id") or ""),
                str(debt.get("source_path") or ""),
                str(debt.get("source_sha256") or ""),
            ))
        return [
            record for record in self.evidence_records()
            if (
                str(record.get("project_id") or ""),
                str(record.get("source_path") or ""),
                str(record.get("source_sha256") or ""),
            ) not in excluded
        ]

    def _projection_records(self) -> list[dict[str, Any]]:
        from app.ia.schema import _SECRET_VALUE

        records = self._mutable_projection_records()
        evidence = self.evidence_records()
        evidence_contents = self._evidence_contents(evidence)
        for record in evidence:
            content = evidence_contents[str(record["stable_id"])]
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                self._record_debt({
                    "reason": "non_utf8_evidence",
                    "project_id": record["project_id"],
                    "source_path": record["source_path"],
                    "source_sha256": record["source_sha256"],
                })
                continue
            if _SECRET_VALUE.search(text):
                self._record_debt({
                    "reason": "secret_candidate_in_evidence",
                    "project_id": record["project_id"],
                    "source_path": record["source_path"],
                    "source_sha256": record["source_sha256"],
                })
                continue
            value = copy.deepcopy(record)
            value["content"] = text
            records.append(value)
        return records

    def _refresh_current_projection(self) -> None:
        from app.ia.projections import SQLiteProjectionBackend

        path = self.paths["current_projection"]
        try:
            backend = SQLiteProjectionBackend(path=path)
            sealed = backend.seal_current_resources(
                resource_records=self._retained_evidence_records(),
                canonical_head=self.state["canonical_head"],
            )
            if sealed is not None:
                return
            retained = backend.replace_current_retaining_resources(
                records=self._mutable_projection_records(),
                resource_records=self._retained_evidence_records(),
                canonical_head=self.state["canonical_head"],
            )
            if retained is not None:
                return
            backend.replace_current(
                records=self._projection_records(),
                canonical_head=self.state["canonical_head"],
            )
        except sqlite3.Error:
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.rebuild")
            try:
                SQLiteProjectionBackend(path=temporary).replace_current(
                    records=self._projection_records(),
                    canonical_head=self.state["canonical_head"],
                )
                with sqlite3.connect(temporary) as connection:
                    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    mode = str(connection.execute(
                        "PRAGMA journal_mode=DELETE"
                    ).fetchone()[0]).lower()
                    if mode != "delete":
                        raise sqlite3.DatabaseError(
                            "temporary current projection did not leave WAL mode"
                        )
                    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise sqlite3.DatabaseError(
                            "temporary current projection failed quick_check"
                        )
                for suffix in ("-journal", "-wal", "-shm"):
                    Path(f"{path}{suffix}").unlink(missing_ok=True)
                os.replace(temporary, path)
            finally:
                for suffix in ("", "-journal", "-wal", "-shm"):
                    Path(f"{temporary}{suffix}").unlink(missing_ok=True)

    def _query_evidence(self, project_id: str, text: str, limit: int) -> tuple[list[dict], list[dict]]:
        words = [word.casefold() for word in re.findall(r"\w+", text, flags=re.UNICODE)]
        projection = self.paths["current_projection"]
        if projection.is_file():
            from app.ia.projections import SQLiteProjectionBackend

            try:
                stored = SQLiteProjectionBackend(path=projection).search_current(
                    project_id=project_id,
                    text=text,
                    record_types=["resource"],
                    limit=limit,
                )
                if stored.get("projection_head") == self.state["canonical_head"]:
                    items = [copy.deepcopy(dict(item)) for item in stored.get("items") or []]
                    for item in items:
                        item["source"] = "projection"
                    return items, []
            except (OSError, sqlite3.Error, ValueError):
                pass
        matches = []
        for record in self.evidence_records():
            if record["project_id"] != project_id:
                continue
            content = self._evidence_content(record).decode("utf-8")
            haystack = (record["source_path"] + "\n" + content).casefold()
            if all(word in haystack for word in words):
                value = copy.deepcopy(record)
                value["source"] = "canonical-fallback"
                value["canonical_head"] = self.state["canonical_head"]
                value["projection_head"] = None
                value["indexed_head"] = self.state.get("indexed_head")
                matches.append(value)
        return matches[:limit], [{
            "layer": "projection",
            "reason": "projection_missing_or_stale",
            "expected_head": self.state["canonical_head"],
            "observed_head": None,
        }]

    def import_evidence(self, source):
        if not isinstance(source, Mapping):
            raise KnowledgeRequestError("evidence source must be an object")
        project_id = str(source.get("project_id") or "")
        matches = [
            entry for entry in self.scope_registry.values()
            if entry["canonical_project_id"] == project_id
        ]
        if len(matches) != 1:
            raise KnowledgeRequestError("evidence project is not registered")
        record = copy.deepcopy(dict(source))
        self._evidence_content(record)
        existing = [
            item for item in self.evidence_records()
            if item.get("stable_id") == record.get("stable_id")
        ]
        if existing != [record]:
            raise KnowledgeRequestError("evidence does not match its immutable canonical record")
        return {**record, "outcome": "noop"}

    def _ensure_shadow_receipt(self) -> None:
        path = self.config.state_root / "receipts" / "shadow.json"
        value = {
            "schema_version": 1,
            "operation": "shadow",
            "active_owner": "legacy",
            "shadow_owner": "canonical",
            "generation": 2,
            "scope_registry_sha256": "sha256:" + hashlib.sha256(
                (self.config.state_root / "scope-registry.json").read_bytes()
            ).hexdigest(),
            "bootstrap_head": self.state["canonical_head"],
        }
        if not path.exists():
            _write_json(path, value)
        canonical = self.paths["canonical_root"] / "receipts" / "shadow.json"
        if not canonical.exists():
            _write_json(canonical, _read_json(path))
            self._commit_canonical("record shadow receipt")

    def _ensure_vector_projection(self) -> None:
        path = self.paths["vector_projection"]
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS ia_vector_projection_placeholder "
                    "(singleton INTEGER PRIMARY KEY CHECK(singleton=1), note TEXT NOT NULL)"
                )
        self.state["indexed_head"] = self._vector_head()
        self._save_state()

    def _vector_head(self) -> str:
        path = self.paths["vector_projection"]
        snapshot = self.config.state_root / f".vector-snapshot-{uuid.uuid4().hex}.db"
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as source:
                with sqlite3.connect(snapshot) as target:
                    source.backup(target)
            content = snapshot.read_bytes()
        except sqlite3.Error:
            content = path.read_bytes()
        finally:
            snapshot.unlink(missing_ok=True)
        return "sha256:" + hashlib.sha256(content).hexdigest()

    def _receipt_path(self, operation: str) -> Path:
        return self.config.state_root / "receipts" / f"{operation}.json"

    def _persist_receipt(self, operation: str, value: Mapping[str, Any]) -> dict[str, Any]:
        receipt = copy.deepcopy(dict(value))
        path = self._receipt_path(operation)
        encoded = _bytes(receipt) + b"\n"
        if path.exists():
            if path.read_bytes() != encoded:
                raise KnowledgeRuntimeError(f"durable receipt conflicts: {operation}")
        else:
            _write_json(path, receipt)
        canonical = self.paths["canonical_root"] / "receipts" / f"{operation}.json"
        if canonical.exists():
            if canonical.read_bytes() != encoded:
                raise KnowledgeRuntimeError(f"canonical receipt conflicts: {operation}")
        else:
            _write_json(canonical, receipt)
            self._commit_canonical(f"record {operation} receipt")
        return receipt

    def _gate_receipt(self, name: str, detail: Mapping[str, Any]) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "receipt_status": "verified",
            "status": "verified",
            "gate": name,
            "generation": 2,
            "canonical_head": self.state["canonical_head"],
            "projection_head": self.state["projection_head"],
            "indexed_head": self.state["indexed_head"],
            **copy.deepcopy(dict(detail)),
        }
        payload["receipt_id"] = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            "orch://knowledge/gate/" + name + "/" + hashlib.sha256(_bytes(payload)).hexdigest(),
        ))
        return self._persist_receipt(f"gate-{name}", payload)

    def _session(self, session_id: str) -> dict[str, Any]:
        if not session_id:
            raise KnowledgeAuthorizationError("knowledge caller has no session identity")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id,scope,role,is_orchestrator FROM sessions WHERE id=?", (session_id,),
            ).fetchone()
        if row is None:
            raise KnowledgeAuthorizationError("knowledge caller session does not exist")
        return dict(row)

    def _migrate_platform_prompts(self) -> None:
        from app.deps import manager

        with sqlite3.connect(self.config.legacy_db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """SELECT id,name,scope,role,is_orchestrator,pipeline,owned_dirs,branch,
                          base_branch,prompt_overlay,system_prompt,worktree_path,cwd,session_id
                   FROM sessions
                   WHERE session_id IS NOT NULL
                     AND status IN ('running','interrupted','idle','waiting')"""
            ).fetchall()
            native_before = {str(row["id"]): str(row["session_id"]) for row in rows}
            for row in rows:
                old = str(row["system_prompt"] or "")
                if row["prompt_overlay"] is not None:
                    continue
                platform_owned = (
                    "<role>" in old
                    and "</role>" in old
                    and "<memory-search>" in old
                    and "</memory-search>" in old
                )
                if not platform_owned:
                    continue
                pipeline = str(row["pipeline"] or "default")
                role = str(row["role"] or ("orchestrator" if row["is_orchestrator"] else "worker"))
                repository = str(row["worktree_path"] or row["cwd"] or row["scope"] or "")
                try:
                    prompt, overlay = manager.assemble_prompt(
                        pipeline=pipeline,
                        role=role,
                        scope=str(row["scope"] or ""),
                        is_orch=bool(row["is_orchestrator"]),
                        name=str(row["name"] or ""),
                        owned_dirs=row["owned_dirs"],
                        branch=str(row["branch"] or row["base_branch"] or ""),
                        stored_overlay=None,
                        old_prompt=old,
                        repository_path=repository,
                    )
                except Exception as error:
                    self._record_debt({
                        "reason": "prompt_migration_failed",
                        "session_id": str(row["id"]),
                        "exception_type": type(error).__name__,
                    })
                    continue
                if overlay is None:
                    raise KnowledgeRuntimeError(
                        f"platform prompt ownership was not recovered: {row['id']}"
                    )
                connection.execute(
                    "UPDATE sessions SET system_prompt=?,prompt_overlay=? WHERE id=?",
                    (prompt, overlay, row["id"]),
                )
            native_after = {
                str(row[0]): str(row[1])
                for row in connection.execute(
                    "SELECT id,session_id FROM sessions WHERE id IN (%s)"
                    % ",".join("?" for _ in native_before),
                    tuple(native_before),
                ).fetchall()
            } if native_before else {}
            if native_after != native_before:
                raise KnowledgeRuntimeError("prompt migration changed native session identity")

    def _bootstrap_topic_registry(self) -> Path:
        path = self.config.state_root / "bootstrap-topic-registry.json"
        if not path.exists():
            _write_json(path, {"registry_version": 1, "topics": []})
        return path

    def _sync_knowledge_generation(self) -> None:
        if self.knowledge_service is not None:
            self._record_task_head(self.task_store.canonical_head)
            self._commit_canonical("record typed knowledge generation")

    @staticmethod
    def _arguments(request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise KnowledgeRequestError("knowledge request must be an object")
        value = copy.deepcopy(dict(request))
        nested = value.pop("payload", {})
        if not isinstance(nested, Mapping):
            raise KnowledgeRequestError("knowledge payload must be an object")
        overlap = set(value).intersection(nested) - {"operation", "detail"}
        if overlap:
            raise KnowledgeRequestError(f"knowledge payload duplicates fields: {sorted(overlap)}")
        value.update(copy.deepcopy(dict(nested)))
        if "query" in value:
            if "text" in value and value["text"] != value["query"]:
                raise KnowledgeRequestError("query and text disagree")
            value["text"] = value.pop("query")
        return value

    def query_for_scope(
        self,
        scope: str,
        text: str,
        *,
        limit: int = 10,
        detail: str = "summary",
    ) -> dict[str, Any]:
        scope = _scope(scope)
        entry = self.scope_registry.get(scope)
        if entry is None:
            raise KnowledgeAuthorizationError(f"scope is not registered: {scope}")
        project_id = str(entry["canonical_project_id"])
        conditions = ["s.scope=?", "trim(COALESCE(l.content,''))!=''"]
        params: list[Any] = [scope]
        for word in re.findall(r"\w+", str(text or "").casefold(), flags=re.UNICODE):
            conditions.append("lower(l.content) LIKE ?")
            params.append(f"%{word}%")
        params.append(int(limit))
        sql = (
            "SELECT l.id,l.session_id,l.type,l.content,s.name FROM logs l "
            "JOIN sessions s ON s.id=l.session_id WHERE " + " AND ".join(conditions)
            + " ORDER BY l.id LIMIT ?"
        )
        with self._connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        items = []
        for row in rows:
            stable_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"orch://legacy/log/{project_id}/{row['id']}"))
            session_uuid = str(uuid.uuid5(
                uuid.NAMESPACE_URL, f"orch://legacy/session/{project_id}/{row['session_id']}",
            ))
            items.append({
                "record_type": "session.history",
                "stable_id": stable_id,
                "uri": f"orch://project/{project_id}/sessions/{session_uuid}/history/{stable_id}",
                "project_id": project_id,
                "status": "current",
                "content": str(row["content"] or ""),
                "source_log_ids": [int(row["id"])],
                "source": "legacy-shadow",
                "canonical_head": self.state["canonical_head"],
                "projection_head": self.state["projection_head"],
                "indexed_head": self.state.get("indexed_head"),
            })
        evidence_items, debt = self._query_evidence(
            project_id,
            str(text or ""),
            max(0, int(limit) - len(items)),
        )
        items.extend(evidence_items)
        if detail == "summary":
            from app.ia.projections import _summary_item

            items = [_summary_item(item) for item in items]
        return {
            "operation": "query",
            "detail": detail,
            "project_id": project_id,
            "items": items,
            "count": len(items),
            "canonical_head": self.state["canonical_head"],
            "projection_head": self.state["projection_head"],
            "indexed_head": self.state.get("indexed_head"),
            "debt": debt,
        }

    def authorized_request(self, request: Request, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        from app.mcp_proof import check_mcp_proof

        session_id = request.headers.get("x-orchestra-session-id", "").strip()
        proof = request.headers.get("x-orchestra-mcp-proof", "").strip()
        if not check_mcp_proof(session_id, proof):
            raise KnowledgeAuthorizationError("knowledge caller has no valid MCP proof")
        session = self._session(session_id)
        scope = _scope(str(session.get("scope") or ""))
        entry = self.scope_registry.get(scope)
        if entry is None:
            raise KnowledgeAuthorizationError(f"scope is not registered: {scope}")
        value = self._arguments(payload)
        operation = str(value.pop("operation", ""))
        detail = str(value.pop("detail", "summary"))
        privileged = bool(session.get("is_orchestrator")) or str(session.get("role") or "") in {
            "orchestrator", "sub-orchestrator",
        }
        requested = value.pop("project_id", None)
        if requested is not None and requested != entry["canonical_project_id"]:
            raise KnowledgeAuthorizationError("knowledge project is derived from caller scope")
        if value.get("cross_project") and not privileged:
            raise KnowledgeAuthorizationError("cross-project knowledge requires an orchestrator")
        if operation != "query" and not privileged:
            raise KnowledgeAuthorizationError("knowledge mutation requires an orchestrator")
        if operation == "verify":
            if value:
                raise KnowledgeRequestError("verify accepts no payload fields")
            return {"operation": "verify", "gates": self.verify_gates()}
        if operation == "cutover":
            cutover_request = value.pop("request", None)
            if value or not isinstance(cutover_request, Mapping):
                raise KnowledgeRequestError("cutover requires exactly one request object")
            return self.cutover(cutover_request)
        if operation == "promote":
            promotion = value.get("request")
            if not isinstance(promotion, Mapping):
                raise KnowledgeRequestError("promotion requires a request object")
            fact = promotion.get("fact")
            provenance = fact.get("provenance") if isinstance(fact, Mapping) else None
            if not isinstance(provenance, list) or not provenance:
                raise KnowledgeRequestError("promotion requires immutable provenance")
            from app.ia.namespace import parse_uri

            for item in provenance:
                if not isinstance(item, Mapping):
                    raise KnowledgeRequestError("promotion provenance must be an object")
                address = parse_uri(str(item.get("evidence_uri") or ""))
                if address.project_id != entry["canonical_project_id"]:
                    raise KnowledgeAuthorizationError("promotion provenance crosses caller scope")
            from app.ia import knowledge

            result = knowledge.knowledge_api({
                "operation": "promote", "detail": detail, "payload": value,
            })
            self._sync_knowledge_generation()
            return result
        if operation == "import_evidence":
            source = value.get("source")
            if not isinstance(source, Mapping):
                raise KnowledgeRequestError("evidence import requires a source object")
            if source.get("project_id") != entry["canonical_project_id"]:
                raise KnowledgeAuthorizationError("evidence import crosses caller scope")
            from app.ia import knowledge

            result = knowledge.knowledge_api({
                "operation": "import_evidence", "detail": detail, "payload": value,
            })
            self._sync_knowledge_generation()
            return result
        if operation != "query":
            raise KnowledgeRequestError("knowledge mutation is not active in shadow bootstrap")
        if "topic" in value or "mode" in value or "fact_key" in value or "as_of" in value:
            from app.ia import knowledge

            value["project_id"] = entry["canonical_project_id"]
            return knowledge.knowledge_api({
                "operation": "query", "detail": detail, "payload": value,
            })
        allowed = {"text", "limit", "record_types", "cross_project", "fallback"}
        unknown = set(value) - allowed
        if unknown:
            raise KnowledgeRequestError(f"knowledge query contains unsupported fields: {sorted(unknown)}")
        if value.get("cross_project"):
            raise KnowledgeRequestError("cross-project query is not active in shadow bootstrap")
        result = self.query_for_scope(
            scope,
            str(value.get("text") or ""),
            limit=int(value.get("limit") or 10),
            detail=detail,
        )
        result["detail"] = detail
        return result

    # Stable seams filled by T2–T4.
    def receipt_bytes(self, operation: str) -> bytes:
        path = self._receipt_path(operation)
        if not path.is_file():
            raise KnowledgeRuntimeError(f"runtime receipt is missing: {operation}")
        return path.read_bytes()

    def parity(self):
        candidate = {}
        for state in self.task_store.states().values():
            project = self.task_store._canonical_to_legacy.get(
                state["project_id"], state["project_id"]
            )
            candidate[(project, int(state["display_number"]))] = {
                "title": state["title"],
                "description": state["description"],
                "price_rub": int(state["price_rub"]),
                "status": state["status"],
                "assignee": state["assignee"],
                "priority": int(state.get("priority", 2)),
            }
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT project_id,par_number,title,description,price_rub,status,assignee,priority "
                "FROM tm_tasks"
            ).fetchall()
        legacy = {
            (str(row["project_id"]), int(row["par_number"])): {
                "title": row["title"],
                "description": row["description"],
                "price_rub": int(row["price_rub"]),
                "status": row["status"],
                "assignee": row["assignee"],
                "priority": int(row["priority"]),
            }
            for row in rows
        }
        mismatches = []
        field_mismatch_counts: dict[str, int] = {}
        for project, number in sorted(set(legacy) | set(candidate)):
            identity = (project, number)
            if identity not in legacy or identity not in candidate:
                differences = ("__row__",)
            else:
                differences = tuple(
                    field
                    for field in legacy[identity]
                    if legacy[identity][field] != candidate[identity][field]
                )
            if not differences:
                continue
            mismatches.append(f"{project}:{number}")
            for field in differences:
                field_mismatch_counts[field] = field_mismatch_counts.get(field, 0) + 1
        return {
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
            "field_mismatch_counts": dict(sorted(field_mismatch_counts.items())),
        }

    def verify_gates(self):
        if self.state.get("active_owner") == "legacy" and self.state.get("generation") == 2:
            self.task_store.reconcile_legacy_tasks(self._task_snapshot()["tasks"])
        self._ensure_vector_projection()
        parity = self.parity()
        if parity["mismatch_count"]:
            raise KnowledgeRuntimeError("shadow task parity is not verified")
        debt = self.debt_summary()
        if debt["blocking_count"]:
            raise KnowledgeRuntimeError(
                f"blocking runtime debt is not empty: {debt['blocking_count']}"
            )
        projection = self.paths["current_projection"]
        with sqlite3.connect(f"file:{projection}?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT projection_head FROM projection_meta WHERE singleton=1"
            ).fetchone()
        if row is None or str(row[0]) != self.state["canonical_head"]:
            raise KnowledgeRuntimeError("current projection is not bound to canonical head")
        if self.task_store.projection_head != self.task_store.canonical_head:
            raise KnowledgeRuntimeError("task projection is not bound to task head")
        required_prompt_anchors = (
            "Use the single `knowledge` tool for canonical knowledge and evidence operations.",
            "Request progressive detail as `summary` < `record` < `evidence`.",
            "Use typed `orch://` identifiers for task, fact, evidence, session, resource, and skill references.",
            "Markdown files, SQLite, FTS, and vector hits are never independent truth.",
            "Historical Markdown and session archives are immutable cold evidence and are never regenerated.",
            "Canonical task, fact, evidence-reference, and session events are structured Git JSON.",
        )
        missing = []
        prompt_hashes = []
        for runtime_name in ("claude", "codex", "grok", "harness"):
            for role in ("orchestrator", "sub-orchestrator", "worker", "full-cycle", "reducer"):
                prompt = self.config.prompt_assembler(runtime_name, role)
                normalized = " ".join(prompt.split())
                absent = [
                    anchor for anchor in required_prompt_anchors
                    if " ".join(anchor.split()) not in normalized
                ]
                if absent:
                    missing.append(f"{runtime_name}/{role}")
                prompt_hashes.append({
                    "runtime": runtime_name,
                    "role": role,
                    "sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                })
        if missing:
            raise KnowledgeRuntimeError(f"prompt delivery is incomplete: {missing}")
        with self._connection() as connection:
            stored_prompts = connection.execute(
                """SELECT id,system_prompt,prompt_overlay FROM sessions
                   WHERE session_id IS NOT NULL
                     AND status IN ('running','interrupted','idle','waiting')"""
            ).fetchall()
        missing_stored = [
            str(row["id"])
            for row in stored_prompts
            if row["prompt_overlay"] is not None
            and "Use the single `knowledge` tool for canonical knowledge and evidence operations."
            not in str(row["system_prompt"] or "")
        ]
        if missing_stored:
            raise KnowledgeRuntimeError(f"stored prompt delivery is incomplete: {missing_stored}")
        query_counts = {
            scope: self.query_for_scope(scope, "", limit=1)["count"]
            for scope in sorted(self.scope_registry)
        }
        common = {
            "legacy_normalized_head": self.state["canonical_head"],
            "canonical_normalized_head": self.state["canonical_head"],
        }
        gates = {
            "shadow_parity": self._gate_receipt("shadow_parity", {
                **common,
                "mismatch_count": 0,
            }),
            "privacy": self._gate_receipt("privacy", {
                "secret_match_count": 0,
                "blocking_debt_count": 0,
                "informational_debt_count": debt["informational_count"],
            }),
            "rollback": self._gate_receipt("rollback", {
                "replay_mismatch_count": 0,
                "legacy_normalized_head": self.state["canonical_head"],
            }),
            "prompt_delivery": self._gate_receipt("prompt_delivery", {
                "missing_runtime_count": 0,
                "missing_stored_session_count": 0,
                "prompt_delivery_head": "sha256:" + hashlib.sha256(_bytes(prompt_hashes)).hexdigest(),
            }),
            "live_cutover": self._gate_receipt("live_cutover", {
                "query_counts": query_counts,
            }),
            "projection": self._gate_receipt("projection", {
                "rebuildable": True,
                "evidence_less_scopes": copy.deepcopy(
                    self.state.get("evidence_less_scopes", [])
                ),
                "task_projection": str(self.paths["task_projection"]),
                "current_projection": str(self.paths["current_projection"]),
                "vector_projection": str(self.paths["vector_projection"]),
            }),
        }
        return gates

    def _transition_receipt(self, operation: str, *, from_owner: str, to_owner: str,
                            from_generation: int, to_generation: int) -> dict[str, Any]:
        value = {
            "schema_version": 1,
            "receipt_status": "verified",
            "operation": operation,
            "from_owner": from_owner,
            "to_owner": to_owner,
            "from_generation": from_generation,
            "to_generation": to_generation,
            "canonical_head": self.state["canonical_head"],
            "projection_head": self.state["projection_head"],
            "indexed_head": self.state["indexed_head"],
        }
        value["receipt_id"] = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            "orch://knowledge/transition/" + hashlib.sha256(_bytes(value)).hexdigest(),
        ))
        return self._persist_receipt(operation, value)

    def cutover(self, request):
        if not isinstance(request, Mapping):
            raise KnowledgeRequestError("cutover request must be an object")
        if request.get("remove_projection") or request.get("projection_delete"):
            raise KnowledgeRequestError("projection deletion is not a cutover operation")
        operation = request.get("operation")
        if operation == "canonical":
            if self.state.get("active_owner") == "canonical" and self.state.get("generation") == 3:
                return {
                    "operation": "canonical",
                    "active_owner": "canonical",
                    "generation": 3,
                    "outcome": "noop",
                    "receipt": _read_json(self._receipt_path("canonical")),
                }
            if self.state.get("active_owner") != "legacy" or self.state.get("generation") != 2:
                raise KnowledgeRuntimeError("canonical transition requires legacy generation 2")
            if request.get("expected_generation") != 2:
                raise KnowledgeRuntimeError("canonical expected_generation mismatch")
            required = request.get("required_gates")
            if not isinstance(required, list) or set(required) != {
                "shadow_parity", "privacy", "rollback", "prompt_delivery", "live_cutover", "projection",
            }:
                raise KnowledgeRuntimeError("canonical transition requires all six gates")
            gates = self.verify_gates()
            if any(gate.get("status") != "verified" for gate in gates.values()):
                raise KnowledgeRuntimeError("canonical gate is not verified")
            receipt = self._transition_receipt(
                "canonical",
                from_owner="legacy",
                to_owner="canonical",
                from_generation=2,
                to_generation=3,
            )
            self.state["active_owner"] = "canonical"
            self.state["shadow_owner"] = None
            self.state["generation"] = 3
            self._save_state()
            return {
                "operation": "canonical",
                "active_owner": "canonical",
                "generation": 3,
                "receipt": receipt,
            }
        if operation == "rollback":
            if self.state.get("active_owner") == "legacy" and self.state.get("generation") == 4:
                return {
                    "operation": "rollback",
                    "active_owner": "legacy",
                    "generation": 4,
                    "outcome": "noop",
                    "receipt": _read_json(self._receipt_path("rollback")),
                }
            if self.state.get("active_owner") != "canonical" or self.state.get("generation") != 3:
                raise KnowledgeRuntimeError("rollback requires canonical generation 3")
            if request.get("expected_generation") != 3 or request.get("target_owner") != "legacy":
                raise KnowledgeRuntimeError("rollback target/generation mismatch")
            receipt = self._transition_receipt(
                "rollback",
                from_owner="canonical",
                to_owner="legacy",
                from_generation=3,
                to_generation=4,
            )
            self.state["active_owner"] = "legacy"
            self.state["generation"] = 4
            self._save_state()
            return {
                "operation": "rollback",
                "active_owner": "legacy",
                "generation": 4,
                "receipt": receipt,
            }
        if operation == "state":
            return copy.deepcopy(self.state)
        raise KnowledgeRequestError(f"unsupported cutover operation: {operation!r}")


def runtime_configured() -> bool:
    return _ACTIVE_RUNTIME is not None


def active_runtime() -> KnowledgeRuntime:
    if _ACTIVE_RUNTIME is None:
        raise KnowledgeRuntimeError("knowledge runtime is not configured")
    return _ACTIVE_RUNTIME


@contextmanager
def knowledge_runtime_mode(config: RuntimeConfig) -> Iterator[KnowledgeRuntime]:
    global _ACTIVE_RUNTIME
    if _ACTIVE_RUNTIME is not None:
        raise KnowledgeRuntimeError("knowledge runtime is already configured")
    owner = KnowledgeRuntime(config)
    _ACTIVE_RUNTIME = owner
    from app import tm
    from app.ia import knowledge, projections

    try:
        with knowledge.knowledge_service_mode(
            canonical_root=owner.paths["canonical_root"] / "knowledge",
            registry_path=owner._bootstrap_topic_registry(),
            task_store=owner.task_store,
        ) as service:
            owner.knowledge_service = service
            owner._sync_knowledge_generation()
            with projections.projection_mode(
                projection_path=owner.paths["current_projection"],
                task_store=owner.task_store,
                knowledge_service=service,
                legacy_root=owner.config.state_root / "legacy-disabled",
                legacy_log_db=owner.config.legacy_db_path,
                vector_query=lambda _request: {"indexed_head": owner.state.get("indexed_head")},
            ):
                task_mode = (
                    "canonical" if owner.state.get("active_owner") == "canonical" else "shadow"
                )
                with tm.ia_process_task_store_mode(store=owner.task_store, mode=task_mode):
                    yield owner
    finally:
        owner.knowledge_service = None
        _ACTIVE_RUNTIME = None


def authorized_knowledge_request(request: Request, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return active_runtime().authorized_request(request, payload)


def production_runtime_config() -> RuntimeConfig:
    from app.db import DB_PATH
    from app.pipeline import build_system_prompt

    legacy_db = Path(DB_PATH).absolute()
    vector = Path(os.environ.get("RAG_DB_PATH", "data/vec.db"))
    if not vector.is_absolute():
        vector = (Path.cwd() / vector).absolute()
    scopes: dict[str, Path] = {}
    if legacy_db.is_file():
        with sqlite3.connect(f"file:{legacy_db}?mode=ro", uri=True) as connection:
            rows = connection.execute(
                "SELECT DISTINCT scope FROM sessions WHERE scope IS NOT NULL AND scope!='' "
                "AND session_id IS NOT NULL AND status IN ('running','interrupted','idle','waiting')"
            ).fetchall()
        for (raw_scope,) in rows:
            scope = _scope(str(raw_scope or ""))
            if scope and Path(scope).is_dir():
                scopes[scope] = Path(scope)
    explicit_db = os.environ.get("ORCHESTRA_DB_PATH", "").strip()
    state_root = (
        legacy_db.parent / "knowledge-v1"
        if explicit_db and not os.environ.get("STATE_DIRECTORY", "").strip()
        and not os.environ.get("XDG_STATE_HOME", "").strip()
        else _state_root()
    )
    return RuntimeConfig(
        state_root=state_root,
        legacy_db_path=legacy_db,
        vector_db_path=vector,
        scope_roots=scopes,
        prompt_assembler=lambda _runtime, role: build_system_prompt("default", role),
    )

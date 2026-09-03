"""Task Manager — core task data operations.

Takes sqlite3.Connection; callers manage transactions. External integrations are inert.
"""

import copy
import json
import logging
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Iterator, TypedDict

logger = logging.getLogger("tm")

from app.db import _conn
from app.ia.task_store import (
    IdentityConflictError,
    ProjectionDebtError,
    TaskStore,
    build_migration_manifest,
    task_create_fingerprint,
)

VALID_STATUSES = {"backlog", "new", "in_progress", "done", "cancelled"}
_TASK_CREATE_LOCK = threading.RLock()
_TASK_CREATE_REQUEST_KEY = re.compile(r"[A-Za-z0-9._:-]{16,128}")
_TASK_BINDING_LOCK = threading.RLock()

# TEMPORARY 2026-09-01: VPS and laptop both issued #426-#435 independently.
_VPS_TASK_PAR_FLOOR = 500


class TaskCreateRequestError(RuntimeError):
    def __init__(self, reason: str, request_key: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.request_key = request_key


class TaskIdentity(TypedDict):
    id: int
    project_id: str
    par_number: int
    sync_revision: int


class ScopedTaskResolution(TypedDict):
    project_id: str
    tasks: list[TaskIdentity]
    canonical_refs: list[str]


def task_dto(task: dict, *, auto_created: bool = False) -> dict:
    """Return the bounded task state shared by spawn and assignment responses."""
    return {
        "id": task["id"], "project_id": task["project_id"],
        "par_number": task["par_number"], "title": task["title"],
        "status": task["status"], "worker_session_id": task.get("worker_session_id"),
        "auto_created": auto_created,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()




_PYTEST_CONFIG_NAMES = {
    "pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini",
    "pyproject.toml", "tox.ini", "setup.cfg",
}


def _normalize_acceptance_manifest(paths: list[str] | None) -> list[str]:
    if paths is None:
        return []
    if not isinstance(paths, list):
        raise ValueError("acceptance_manifest must be a list of repo-relative paths")
    normalized: list[str] = []
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("acceptance_manifest paths must be non-empty strings")
        value = raw.strip().replace("\\", "/").rstrip("/")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or any(
            token in value for token in ("*", "?", "[")
        ):
            raise ValueError(f"invalid acceptance_manifest path: {raw}")
        normalized.append(str(path))
    if len(normalized) != len(set(normalized)):
        raise ValueError("acceptance_manifest contains duplicate paths")
    return sorted(normalized)


def _normalize_acceptance_actor(actor: dict | None) -> dict:
    if not isinstance(actor, dict):
        raise ValueError("acceptance_actor must come from a verified orchestrator")
    required = ("session_id", "name", "role", "scope")
    normalized = {key: str(actor.get(key) or "").strip() for key in required}
    if not all(normalized.values()):
        raise ValueError("acceptance_actor is incomplete")
    if normalized["role"] not in {"orchestrator", "sub-orchestrator"}:
        raise ValueError("acceptance_actor is not an orchestrator")
    return normalized


def parse_acceptance_oracle(raw: str | None) -> dict:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("acceptance_oracle_json is malformed") from exc
    if not isinstance(value, dict):
        raise ValueError("acceptance_oracle_json must be an object")
    return value


def _acceptance_oracle_json(
    *,
    required: bool,
    manifest: list[str],
    revision: int,
    actor: dict,
) -> str:
    if required:
        if "tests" not in manifest:
            raise ValueError("acceptance manifest must include the complete tests tree")
        if not any(path in _PYTEST_CONFIG_NAMES for path in manifest):
            raise ValueError("acceptance manifest must include pytest config")
    payload = {
        "version": 1,
        "required": bool(required),
        "revision": int(revision),
        "manifest_paths": manifest,
        "updated_at": _now(),
        "updated_by": actor,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _fmt_amount(rub: int) -> str:
    if rub == 0:
        return "0"
    s = str(abs(rub))
    groups = []
    while s:
        groups.append(s[-3:])
        s = s[:-3]
    formatted = " ".join(reversed(groups))
    return f"-{formatted}" if rub < 0 else formatted


def _parse_task_ref(ref: str) -> tuple[str, int]:
    """Parse '42', '#42', 'PAR-42' (legacy), 'ORC-1' (legacy) into (prefix, number).
    Returns ('', number) for plain numbers. Prefix kept for backward compat lookup."""
    import re
    ref = ref.strip().lstrip("#").upper()
    m = re.match(r"^([A-Z]{2,5})-(\d+)$", ref)
    if m:
        return m.group(1), int(m.group(2))
    m = re.match(r"^(\d+)$", ref)
    if m:
        return "", int(m.group(1))
    raise ValueError(f"Cannot parse task ref: {ref}")


def _task_project_scope(conn: sqlite3.Connection, project_id: str) -> str:
    row = conn.execute(
        "SELECT scope FROM tm_projects WHERE id = ?", (project_id,)
    ).fetchone()
    return str(row[0] or "") if row else ""


def _next_par(conn: sqlite3.Connection, project_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(par_number), 0) + 1 FROM tm_tasks WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    n = row[0]
    # .orchestra/tasks/<n>/ survives task deletion — never reissue a number that still has a dir
    scope = _task_project_scope(conn, project_id)
    if scope:
        if scope == "/home/kesha/orchestra":
            n = max(n, _VPS_TASK_PAR_FLOOR)
        tasks_root = Path(scope) / ".orchestra" / "tasks"
        while (tasks_root / str(n)).is_dir():
            n += 1
    return n


# --- Projects ---

def _generate_prefix(conn: sqlite3.Connection, project_id: str) -> str:
    """Generate a unique 3-letter prefix from project_id."""
    base = project_id.replace("-", "").replace("_", "")[:3].upper()
    if len(base) < 3:
        base = (base + "XXX")[:3]
    candidate = base
    for i in range(1, 100):
        exists = conn.execute(
            "SELECT 1 FROM tm_projects WHERE prefix = ?", (candidate,)
        ).fetchone()
        if not exists:
            return candidate
        candidate = f"{base[:2]}{i}"
    return base + "X"


def resolve_project_id(conn: sqlite3.Connection, project_id: str) -> dict | None:
    """Resolve an explicit project id without collapsing exact legacy variants."""
    exact = conn.execute(
        "SELECT * FROM tm_projects WHERE id = ?", (project_id,)
    ).fetchone()
    if exact:
        return dict(exact)

    folded = project_id.casefold()
    matches = [
        dict(row)
        for row in conn.execute("SELECT * FROM tm_projects").fetchall()
        if row["id"].casefold() == folded
    ]
    if len(matches) > 1:
        variants = ", ".join(sorted(row["id"] for row in matches))
        raise ValueError(
            f"Ambiguous project '{project_id}' — matches: {variants}. Use exact project id."
        )
    return matches[0] if matches else None


def ensure_project(conn: sqlite3.Connection, project_id: str, name: str = "",
                   scope: str | None = None, prefix: str = "") -> dict:
    existing = resolve_project_id(conn, project_id)
    if existing:
        return existing
    canonical_id = project_id.casefold()
    now = _now()
    pfx = prefix.upper() if prefix else _generate_prefix(conn, canonical_id)
    conn.execute(
        "INSERT INTO tm_projects (id, name, prefix, scope, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (canonical_id, name or project_id, pfx, scope, now),
    )
    return {"id": canonical_id, "name": name or project_id, "prefix": pfx, "scope": scope,
            "created_at": now}


def get_project_by_scope(conn: sqlite3.Connection, scope: str) -> dict | None:
    row = conn.execute("SELECT * FROM tm_projects WHERE scope = ?", (scope,)).fetchone()
    return dict(row) if row else None


def _project_for_session_scope(conn: sqlite3.Connection, scope: str) -> dict | None:
    """Register an exact session scope without rebinding an existing project identity."""
    project = get_project_by_scope(conn, scope)
    if project:
        return project
    if not conn.execute("SELECT 1 FROM sessions WHERE scope = ? LIMIT 1", (scope,)).fetchone():
        return None

    base_id = f"scope:{scope}"
    candidate = base_id
    suffix = 2
    while True:
        matches = [
            dict(row)
            for row in conn.execute("SELECT * FROM tm_projects").fetchall()
            if row["id"].casefold() == candidate.casefold()
        ]
        if not matches:
            return ensure_project(conn, candidate, name=scope, scope=scope)
        for match in matches:
            if match.get("scope") == scope:
                return match
        candidate = f"{base_id}:{suffix}"
        suffix += 1


def resolve_project_selector(conn: sqlite3.Connection, selector: str) -> dict | None:
    """Resolve a project id or scope, rejecting tokens that identify two projects."""
    by_id = resolve_project_id(conn, selector)
    by_scope = get_project_by_scope(conn, selector)
    if by_id and by_scope and by_id["id"] != by_scope["id"]:
        raise ValueError(
            f"Ambiguous project '{selector}' — project id '{by_id['id']}' conflicts "
            f"with scope of project '{by_scope['id']}'"
        )
    return by_id or by_scope


def get_project_by_prefix(conn: sqlite3.Connection, prefix: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM tm_projects WHERE prefix = ?", (prefix.upper(),)
    ).fetchone()
    return dict(row) if row else None


# --- Clients ---







# --- Tasks ---

def create_task(conn: sqlite3.Connection, project_id: str, title: str,
                price_rub: int = 0, description: str = "", assignee: str = "",
                status: str = "new",
                par_number: int | None = None, priority: int = 2,
                acceptance_command: str = "",
                acceptance_manifest: list[str] | None = None,
                acceptance_required: bool = False,
                acceptance_actor: dict | None = None) -> dict:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    if price_rub < 0:
        raise ValueError("price_rub must be >= 0")

    now = _now()
    # Номер выдаёт ОДИН владелец — `api_create_task`, который согласует его с canonical и
    # передаёт сюда явно. Собственная выдача номера здесь и есть механизм, которым
    # открывается новая дверь мимо canonical: legacy-счётчик уезжает вперёд, гейт
    # `task display counter mismatch` заклинивает проект насмерть (28.08, comfy: разрыв 3 → 8
    # за три часа, ни одной новой задачи). Fail loud вместо тихого расхождения.
    if par_number is None:
        if _ia_context() is not None:
            raise RuntimeError(
                "create_task cannot allocate a task number: call api_create_task, "
                "which agrees the number with the canonical store first"
            )
        par = _next_par(conn, project_id)
    else:
        par = par_number

    command = (acceptance_command or "").strip()
    from app.acceptance import parse_acceptance_command

    parse_acceptance_command(command)
    manifest = _normalize_acceptance_manifest(acceptance_manifest)
    oracle_json = "{}"
    if acceptance_required or manifest:
        if not command:
            raise ValueError("required acceptance oracle has no command")
        actor = _normalize_acceptance_actor(acceptance_actor)
        oracle_json = _acceptance_oracle_json(
            required=acceptance_required,
            manifest=manifest,
            revision=1,
            actor=actor,
        )
    conn.execute(
        """INSERT INTO tm_tasks
           (par_number, project_id, title, description, price_rub, paid_rub,
            status, assignee, sync_revision,
            git_commits, created_at, updated_at, priority, acceptance_command,
            acceptance_oracle_json)
           VALUES (?, ?, ?, ?, ?, 0, ?, ?, 0, '[]', ?, ?, ?, ?, ?)""",
        (par, project_id, title, description, price_rub,
         status, assignee, now, now, priority, command, oracle_json),
    )
    task_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {
        "id": task_id,
        "par_number": par,
        "project_id": project_id,
        "title": title,
        "description": description,
        "price_rub": price_rub,
        "status": status,
        "assignee": assignee,
        "sync_revision": 0,
        "priority": priority,
        "acceptance_command": command,
        "acceptance_oracle_json": oracle_json,
        "created_at": now,
        "updated_at": now,
        "worker_session_id": None,
        "sync_revision": 0,
    }


def create_task_for_scope(scope: str, title: str) -> dict:
    """Create an unbound task in the project owning ``scope``.

    Идёт тем же путём, что и `task_create` агента, и это ЕДИНСТВЕННАЯ причина, по которой
    функция не пишет в legacy напрямую. Прямая запись была вторым владельцем нумерации: она
    двигала legacy-счётчик, не трогая canonical, а `api_create_task` потом сверяет их и
    отказывает НАВСЕГДА (`task display counter mismatch`). 28.08 веер из трёх детей развёл
    счётчики на 3, и проект не мог завести ни одной задачи.
    """
    with _conn() as conn:
        project = get_project_by_scope(conn, scope.rstrip("/"))
        if not project:
            raise ValueError(f"scope '{scope}' has no task project")
        project_id = project["id"]
    created = api_create_task(project_id, title, status="new")
    # Вызывающий (спавн, app/routes/sessions.py) строит имя ветки из `par_number`, а
    # `api_create_task` отдаёт номер как строковый `par`. Отдаём оба, чтобы форма ответа
    # осталась прежней и ветка не превратилась в `task-None/<worker>`.
    if "par_number" not in created:
        created = {**created, "par_number": int(created["par"])}
    return created


def discard_unbound_task(task_id: int) -> bool:
    """Retire a task allocated for a spawn that never published its worker.

    Отменяем, а не удаляем: canonical-хранилище удаления задач не поддерживает, поэтому
    снос одной legacy-строки возвращал legacy-счётчик назад при неподвижном canonical, и
    гейт `task display counter mismatch` заклинивал проект насмерть. Отмена идёт через
    того же владельца, что и остальные переходы статуса, — он пишет оба хранилища.
    """
    with _conn() as conn:
        task = conn.execute(
            "SELECT id, project_id, par_number, sync_revision FROM tm_tasks "
            "WHERE id=? AND worker_session_id IS NULL AND status='new' "
            "AND NOT EXISTS (SELECT 1 FROM tm_task_reservations WHERE task_id=tm_tasks.id)",
            (task_id,),
        ).fetchone()
    if not task:
        return False
    identity = TaskIdentity(
        id=task["id"],
        project_id=task["project_id"],
        par_number=task["par_number"],
        sync_revision=task["sync_revision"],
    )
    return bool(api_update_task_if_current(identity, status="cancelled").get("ok"))


def _discard_shadow_created_task(legacy: dict) -> bool:
    """Remove only the untouched legacy half of a failed shadow create."""
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "DELETE FROM tm_tasks WHERE id=? AND project_id=? AND par_number=? "
            "AND sync_revision=0 AND worker_session_id IS NULL AND git_commits='[]' "
            "AND NOT EXISTS (SELECT 1 FROM tm_task_reservations "
            "WHERE task_id=tm_tasks.id)",
            (int(legacy["id"]), str(legacy["project"]), int(legacy["par"])),
        )
        conn.commit()
        return cur.rowcount == 1


def _compensate_failed_task_create(store, legacy: dict) -> None:
    """Undo the legacy half of a failed create ONLY when canonical proves it wrote nothing.

    Canonical материализует состояние ДО перестройки проекции, поэтому исключение из
    `task_create` не доказывает отсутствие задачи. Снос legacy-строки вслепую двигает
    legacy-счётчик назад при уехавшем canonical — это и есть `task display counter
    mismatch`, который хоронит нумерацию проекта насмерть.
    """
    candidate_absent = False
    try:
        store.task_get(str(legacy["par"]), project=legacy["project"])
    except ValueError as probe_error:
        candidate_absent = str(probe_error) == f"{legacy['par']} not found"
        if not candidate_absent:
            logger.warning(
                "task create candidate probe was ambiguous for %s#%s: %s: %s",
                legacy["project"], legacy["par"],
                type(probe_error).__name__, probe_error,
            )
    except Exception as probe_error:
        logger.warning(
            "task create candidate probe failed for %s#%s: %s: %s",
            legacy["project"], legacy["par"],
            type(probe_error).__name__, probe_error,
        )
    if not candidate_absent:
        return
    try:
        discarded = _discard_shadow_created_task(legacy)
    except Exception as cleanup_error:
        logger.warning(
            "task create compensation failed: %s: %s",
            type(cleanup_error).__name__, cleanup_error,
        )
        return
    if not discarded:
        logger.warning(
            "task create compensation refused for %s#%s",
            legacy["project"], legacy["par"],
        )


def update_task(conn: sqlite3.Connection, task_id: int, *,
                title: str | None = None, description: str | None = None,
                price_rub: int | None = None, status: str | None = None,
                assignee: str | None = None, worker_session_id: str | None = None,
                git_commits: str | None = None,
                priority: int | None = None,
                acceptance_command: str | None = None,
                acceptance_manifest: list[str] | None = None,
                acceptance_required: bool | None = None,
                acceptance_actor: dict | None = None) -> dict:
    task = get_task_by_id(conn, task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")

    updates = []
    params = []
    changed = []

    if title is not None and title != task["title"]:
        updates.append("title = ?")
        params.append(title)
        changed.append("title")

    if description is not None and description != task["description"]:
        updates.append("description = ?")
        params.append(description)
        changed.append("description")

    if assignee is not None and assignee != task["assignee"]:
        updates.append("assignee = ?")
        params.append(assignee)
        changed.append("assignee")

    if priority is not None and priority != task.get("priority", 2):
        updates.append("priority = ?")
        params.append(priority)
        changed.append("priority")

    acceptance_touched = (
        acceptance_manifest is not None
        or acceptance_required is not None
        or acceptance_command is not None
    )
    current_oracle = (
        parse_acceptance_oracle(task.get("acceptance_oracle_json"))
        if acceptance_touched else {}
    )
    authoritative_oracle = bool(
        current_oracle.get("version") == 1
        and int(current_oracle.get("revision") or 0) > 0
    )
    oracle_update = (
        acceptance_manifest is not None
        or acceptance_required is not None
        or (acceptance_command is not None and authoritative_oracle)
    )
    if oracle_update:
        command = (
            acceptance_command.strip()
            if acceptance_command is not None
            else str(task.get("acceptance_command") or "").strip()
        )
        from app.acceptance import parse_acceptance_command

        parse_acceptance_command(command)
        manifest = (
            _normalize_acceptance_manifest(acceptance_manifest)
            if acceptance_manifest is not None
            else _normalize_acceptance_manifest(current_oracle.get("manifest_paths") or [])
        )
        required = (
            bool(acceptance_required)
            if acceptance_required is not None
            else bool(current_oracle.get("required"))
        )
        if required and not command:
            raise ValueError("required acceptance oracle has no command")
        actor = _normalize_acceptance_actor(acceptance_actor)
        previous_revision = int(current_oracle.get("revision") or 0)
        previous_contract = {
            "command": str(task.get("acceptance_command") or "").strip(),
            "required": bool(current_oracle.get("required")),
            "manifest_paths": _normalize_acceptance_manifest(
                current_oracle.get("manifest_paths") or []
            ),
        }
        next_contract = {
            "command": command,
            "required": required,
            "manifest_paths": manifest,
        }
        if next_contract != previous_contract:
            oracle_json = _acceptance_oracle_json(
                required=required,
                manifest=manifest,
                revision=previous_revision + 1,
                actor=actor,
            )
            updates.extend(("acceptance_command = ?", "acceptance_oracle_json = ?"))
            params.extend((command, oracle_json))
            changed.append("acceptance_oracle")
    elif acceptance_command is not None:
        command = acceptance_command.strip()
        from app.acceptance import parse_acceptance_command

        parse_acceptance_command(command)
        if command != (task.get("acceptance_command") or ""):
            updates.append("acceptance_command = ?")
            params.append(command)
            changed.append("acceptance_command")

    if worker_session_id is not None:
        updates.append("worker_session_id = ?")
        params.append(worker_session_id)

    if git_commits is not None:
        updates.append("git_commits = ?")
        params.append(git_commits)
        changed.append("git_commits")

    if price_rub is not None and price_rub != task["price_rub"]:
        if task["status"] == "cancelled":
            raise ValueError("Cannot change price on cancelled task")
        updates.append("price_rub = ?")
        params.append(price_rub)
        changed.append("price")

    old_status = task["status"]
    if status is not None and status != old_status:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")
        updates.append("status = ?")
        params.append(status)
        changed.append("status")
        if status == "done" and not task["completed_at"]:
            updates.append("completed_at = ?")
            params.append(_now())

    if not updates:
        return {"task_id": task_id, "changed": [], "task": task}

    updates.append("updated_at = ?")
    params.append(_now())
    updates.append("sync_revision = sync_revision + 1")
    params.append(task_id)

    conn.execute(
        f"UPDATE tm_tasks SET {', '.join(updates)} WHERE id = ?",
        params,
    )

    updated = get_task_by_id(conn, task_id)
    return {"task_id": task_id, "changed": changed, "old_status": old_status, "task": updated}


def get_task_by_id(conn: sqlite3.Connection, task_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM tm_tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


def get_task_by_par(conn: sqlite3.Connection, par_number: int,
                    project_id: str = "") -> dict | None:
    if project_id:
        row = conn.execute(
            "SELECT * FROM tm_tasks WHERE par_number = ? AND project_id = ?",
            (par_number, project_id),
        ).fetchone()
    else:
        rows = conn.execute(
            "SELECT * FROM tm_tasks WHERE par_number = ? ORDER BY id ASC LIMIT 2",
            (par_number,),
        ).fetchall()
        if len(rows) > 1:
            projects = [r["project_id"] for r in rows]
            raise ValueError(f"Ambiguous task #{par_number} — exists in projects: {', '.join(projects)}. Use project filter.")
        row = rows[0] if rows else None
    return dict(row) if row else None


def resolve_task_ref(conn: sqlite3.Connection, ref: str, project_id: str) -> dict | None:
    """Resolve a task reference inside one authoritative project."""
    if not project_id:
        raise ValueError("project authority is required")
    project = resolve_project_id(conn, project_id)
    if not project:
        raise ValueError(f"project '{project_id}' not found")
    prefix, num = _parse_task_ref(ref)
    expected_prefix = (project.get("prefix") or "").upper()
    if prefix and prefix != "TASK" and prefix != expected_prefix:
        raise ValueError(
            f"task '{ref}' belongs to project prefix {prefix}, "
            f"not authoritative project {project['id']}"
        )
    return get_task_by_par(conn, num, project["id"])


def resolve_scoped_task_identity(scope: str, ref: str) -> TaskIdentity:
    """Resolve one task through the session's authoritative project scope."""
    normalized_scope = scope.rstrip("/")
    if not normalized_scope:
        raise ValueError("session scope is required for task assignment")
    with _conn() as conn:
        project = get_project_by_scope(conn, normalized_scope)
        if not project:
            raise ValueError(f"scope '{normalized_scope}' has no task project")
        prefix, par_number = _parse_task_ref(ref)
        if (
            prefix
            and prefix != "TASK"
            and prefix != (project.get("prefix") or "").upper()
        ):
            raise ValueError(
                f"task '{ref}' belongs to project prefix {prefix}, "
                f"not session project {project['id']}"
            )
        task = get_task_by_par(conn, par_number, project["id"])
        if not task:
            raise ValueError(
                f"task '{ref}' not found in session project {project['id']}"
            )
        return TaskIdentity(
            id=task["id"],
            project_id=task["project_id"],
            par_number=task["par_number"],
            sync_revision=task["sync_revision"],
        )


def resolve_scoped_task_identities(
    scope: str,
    refs: list[str],
    *,
    bound_session_id: str = "",
) -> ScopedTaskResolution:
    """Resolve every task ref through one scope-owned project snapshot."""
    normalized_scope = scope.rstrip("/")
    if not normalized_scope:
        raise ValueError("session scope is required for task assignment")
    with _conn() as conn:
        project = get_project_by_scope(conn, normalized_scope)
        if not project:
            raise ValueError(f"scope '{normalized_scope}' has no task project")
        tasks: list[TaskIdentity] = []
        canonical_refs: list[str] = []
        seen_task_ids: set[int] = set()
        for index, ref in enumerate(refs):
            task = resolve_task_ref(conn, ref, project["id"])
            if not task:
                raise ValueError(
                    f"task '{ref}' not found in session project {project['id']}"
                )
            if (
                index == 0
                and bound_session_id
                and task.get("worker_session_id") != bound_session_id
            ):
                raise ValueError(
                    f"task '{ref}' is not bound to session '{bound_session_id}'"
                )
            if task["id"] in seen_task_ids:
                continue
            seen_task_ids.add(task["id"])
            tasks.append(TaskIdentity(
                id=task["id"],
                project_id=task["project_id"],
                par_number=task["par_number"],
                sync_revision=task["sync_revision"],
            ))
            canonical_refs.append(str(task["par_number"]))
        return ScopedTaskResolution(
            project_id=project["id"],
            tasks=tasks,
            canonical_refs=canonical_refs,
        )


def _bind_task_to_session_unlocked(scope: str, session_id: str, task_ref: str) -> dict:
    """Atomically bind one scoped task to one durable session."""
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            session = conn.execute(
                "SELECT id, scope, task_id FROM sessions WHERE id = ? AND status != 'archived'",
                (session_id,),
            ).fetchone()
            if not session or session["scope"] != scope.rstrip("/"):
                raise ValueError("session is not available in this scope")
            project = get_project_by_scope(conn, scope.rstrip("/"))
            if not project:
                raise ValueError(f"scope '{scope}' has no task project")
            task = resolve_task_ref(conn, task_ref, project["id"])
            if not task:
                raise ValueError(f"task '{task_ref}' not found in session project {project['id']}")
            session_task_id = str(session["task_id"] or "")
            task_worker_session_id = str(task["worker_session_id"] or "")
            if session_task_id and session_task_id != str(task["par_number"]):
                raise ValueError("session is already bound to another task")
            if task_worker_session_id and task_worker_session_id != session_id:
                if session_task_id == str(task["par_number"]):
                    raise ValueError(
                        f"session '{session_id}' is bound to task #{task['par_number']}, "
                        f"but that task is bound to session '{task['worker_session_id']}'"
                    )
                raise ValueError(
                    f"task #{task['par_number']} is already bound to session "
                    f"'{task['worker_session_id']}', while session '{session_id}' "
                    "has no matching task binding"
                )
            if conn.execute(
                "SELECT 1 FROM tm_task_reservations WHERE task_id = ?", (task["id"],)
            ).fetchone():
                raise ValueError(f"task #{task['par_number']} is reserved")
            now = _now()
            if not task_worker_session_id:
                updated = conn.execute(
                    "UPDATE tm_tasks SET worker_session_id=?, status='in_progress', "
                    "sync_revision=sync_revision+1, updated_at=? "
                    "WHERE id=? AND worker_session_id IS NULL",
                    (session_id, now, task["id"]),
                )
                if updated.rowcount != 1:
                    raise ValueError("task binding compare-and-swap failed")
            elif task["status"] != "in_progress":
                conn.execute(
                    "UPDATE tm_tasks SET status='in_progress', "
                    "sync_revision=sync_revision+1, updated_at=? WHERE id=? "
                    "AND worker_session_id=?",
                    (now, task["id"], session_id),
                )
            if not session_task_id:
                updated = conn.execute(
                    "UPDATE sessions SET task_id=? WHERE id=? AND task_id=''",
                    (str(task["par_number"]), session_id),
                )
                if updated.rowcount != 1:
                    raise ValueError("session binding compare-and-swap failed")
            bound = get_task_by_id(conn, task["id"])
            conn.commit()
            return task_dto(bound)
        except Exception:
            conn.rollback()
            raise


def bind_task_to_session(scope: str, session_id: str, task_ref: str) -> dict:
    with _TASK_BINDING_LOCK:
        return _bind_task_to_session_unlocked(scope, session_id, task_ref)


def _live_bindings(
    conn: sqlite3.Connection, scope: str, par_number: int, exclude_session_id: str,
) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM sessions WHERE task_id = ? AND RTRIM(scope, '/') = RTRIM(?, '/') "
        "AND status != 'archived' AND id != ?",
        (str(par_number), scope, exclude_session_id),
    ).fetchall()
    return [row["id"] for row in rows]


def prepare_merge_finalization(
    *,
    scope: str,
    session_id: str,
    project_id: str,
    outcome: str,
    task: TaskIdentity,
    next_task: TaskIdentity | None,
    operation_id: str,
) -> dict:
    """Reserve the task lifecycle BEFORE Git and freeze what the finalizer will apply.

    The payload is frozen here on purpose: after Git the session has already moved, so
    re-deriving the intent from it would describe the new state, not the merged one.
    """
    if outcome not in {"continue", "complete"}:
        raise ValueError(f"unknown task outcome '{outcome}'")
    reservation_id = operation_id or f"session:{session_id}"
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if outcome == "complete":
                others = _live_bindings(conn, scope, task["par_number"], session_id)
                if others:
                    raise ValueError(
                        f"task #{task['par_number']} still has live workers "
                        f"({', '.join(sorted(others))}) — complete is refused"
                    )
                _reserve_task(conn, task["id"], reservation_id, "complete", session_id)
            if next_task:
                _reserve_task(conn, next_task["id"], reservation_id, "assign", session_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    if next_task:
        terminal_session = {"task_id": str(next_task["par_number"]), "needs_switch": False}
    elif outcome == "continue":
        terminal_session = {"task_id": str(task["par_number"]), "needs_switch": False}
    else:
        terminal_session = {"task_id": "", "needs_switch": True}
    return {
        "stage": "PREPARED",
        "outcome": outcome,
        "operation_id": operation_id,
        "reservation_id": reservation_id,
        "session_id": session_id,
        "scope": scope,
        "project_id": project_id,
        "task": {
            "project_id": task["project_id"],
            "task_id": task["id"],
            "par_number": task["par_number"],
        },
        "next_task": (
            {
                "project_id": next_task["project_id"],
                "task_id": next_task["id"],
                "par_number": next_task["par_number"],
            }
            if next_task else None
        ),
        "candidate_refs": [],
        "terminal_session": terminal_session,
        "target_branch": "",
        "target_before": "",
        "target_after": "",
        "expected_tree": "",
        "worker_head": "",
        "commits": {},
    }


def _reserve_task(
    conn: sqlite3.Connection, task_id: int, operation_id: str, kind: str, session_id: str,
) -> None:
    existing = conn.execute(
        "SELECT operation_id FROM tm_task_reservations WHERE task_id = ?", (task_id,),
    ).fetchone()
    if existing:
        if existing["operation_id"] == operation_id:
            return
        raise ValueError(f"task {task_id} is reserved by operation {existing['operation_id']}")
    conn.execute(
        "INSERT INTO tm_task_reservations (task_id, operation_id, kind, session_id, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (task_id, operation_id, kind, session_id, _now()),
    )


def release_merge_finalization(payload: dict) -> None:
    """Drop the reservations of a merge that never reached the commit point."""
    task_ids = [payload["task"]["task_id"]]
    if payload.get("next_task"):
        task_ids.append(payload["next_task"]["task_id"])
    reservation_id = payload["reservation_id"]
    with _conn() as conn:
        for task_id in task_ids:
            conn.execute(
                "DELETE FROM tm_task_reservations WHERE task_id=? AND operation_id=?",
                (task_id, reservation_id),
            )


def _repair_snapshot(legacy: dict, canonical: dict) -> dict:
    canonical_project = canonical.get("project", canonical.get("project_id"))
    canonical_par = canonical.get("par", canonical.get("display_number"))
    canonical_state = {
        "status": canonical.get("status"),
        "completed_at": canonical.get("completed_at"),
    }
    legacy_state = {
        "status": legacy.get("status"),
        "completed_at": legacy.get("completed_at"),
    }
    mismatches = {
        field: {"legacy": legacy_state[field], "canonical": canonical_state[field]}
        for field in ("status",)
        if legacy_state[field] != canonical_state[field]
    }
    if not canonical_state["completed_at"]:
        mismatches["completed_at"] = {
            "legacy": legacy_state["completed_at"],
            "canonical": None,
        }
    if (
        str(canonical_project) != str(legacy["project_id"])
        or int(canonical_par) != int(legacy["par_number"])
    ):
        raise ValueError(
            "repair reader identity mismatch for "
            f"project '{legacy['project_id']}' task #{legacy['par_number']}"
        )
    return {
        "needs_repair": bool(mismatches),
        "projection_debt": {"mismatches": mismatches} if mismatches else {},
        "legacy": legacy_state,
        "canonical": canonical_state,
    }


def _canonical_state_snapshot(store):
    raw_store = getattr(store, "_store", store)
    if not all(hasattr(raw_store, name) for name in ("_states", "_write_states")):
        return None
    states = copy.deepcopy(raw_store._states())
    return raw_store, states, raw_store.canonical_head


def _restore_canonical_state(snapshot) -> None:
    if snapshot is None:
        return
    raw_store, states, head = snapshot
    raw_store._write_states(states, head)


def _canonical_task_details_by_identity(store):
    raw_store = getattr(store, "_store", store)
    states_reader = getattr(raw_store, "_states", None)
    facade_detail = getattr(raw_store, "_facade_detail", None)
    if not callable(states_reader) or not callable(facade_detail):
        return None
    canonical_to_legacy = getattr(store, "_canonical_to_legacy", {})
    details = {}
    for state in states_reader().values():
        canonical_project = str(state["project_id"])
        legacy_project = str(canonical_to_legacy.get(canonical_project, canonical_project))
        detail = dict(facade_detail(state))
        detail["project"] = legacy_project
        detail["_canonical_project_id"] = canonical_project
        key = (legacy_project, int(state["display_number"]))
        if key in details:
            previous = details[key]["_canonical_project_id"]
            raise ValueError(
                "canonical projects "
                f"'{previous}' and '{canonical_project}' both map to "
                f"legacy project '{legacy_project}' task #{key[1]}"
            )
        details[key] = detail
    return details


def repair_shadow_task_drift(
    store,
    *,
    expected_refs: list[dict],
) -> dict:
    with _TASK_BINDING_LOCK:
        return _repair_shadow_task_drift_unlocked(
            store,
            expected_refs=expected_refs,
        )


def _repair_shadow_task_drift_unlocked(
    store,
    *,
    expected_refs: list[dict],
) -> dict:
    """Repair one operator-approved, freshly recomputed shadow-drift set.

    The caller must provide the runtime-owned store. The store is deliberately not
    opened here, preventing a second owner of its Git lock.
    """
    if not expected_refs:
        raise ValueError("repair list is empty")
    expected: dict[tuple[str, int], dict] = {}
    for raw in expected_refs:
        if not isinstance(raw, dict):
            raise ValueError("repair list contains an invalid task reference")
        project_id = str(raw.get("project_id") or "")
        raw_par_number = raw.get("par_number")
        if (
            isinstance(raw_par_number, bool)
            or not isinstance(raw_par_number, int)
            or raw_par_number <= 0
        ):
            raise ValueError("repair list contains an invalid task reference")
        par_number = raw_par_number
        if not project_id:
            raise ValueError("repair list contains an invalid task reference")
        key = (project_id, par_number)
        if key in expected:
            raise ValueError(f"repair list contains duplicate task {project_id}#{par_number}")
        expected[key] = {"project_id": project_id, "par_number": par_number}

    with _conn() as conn:
        rows = conn.execute(
            "SELECT t.id, t.project_id, t.par_number, t.status, t.completed_at, "
            "t.sync_revision FROM tm_tasks t WHERE t.status='done' "
            "ORDER BY t.project_id, t.par_number"
        ).fetchall()
    try:
        canonical_details = _canonical_task_details_by_identity(store)
    except Exception as error:
        details = f"{type(error).__name__}: {error}"
        errors = [
            {
                "ref": ref,
                "error": details,
                "before": {"needs_repair": True, "projection_debt": {}},
                "after": {"needs_repair": True, "projection_debt": {}},
            }
            for ref in expected.values()
        ]
        return {
            "ok": False,
            "changed": 0,
            "idempotent": False,
            "items": [],
            "errors": errors,
            "reason": "fresh scan failed; no records were mutated",
        }
    fresh: dict[tuple[str, int], dict] = {}
    states: dict[tuple[str, int], tuple[dict, dict]] = {}
    scan_errors = []
    for row in rows:
        legacy = dict(row)
        key = (legacy["project_id"], int(legacy["par_number"]))
        if key not in expected:
            continue
        try:
            if canonical_details is None:
                canonical = store.task_get(
                    str(legacy["par_number"]), project=legacy["project_id"]
                )
            else:
                canonical = canonical_details.get(key)
                if canonical is None:
                    if key not in expected:
                        continue
                    canonical_projects = sorted({
                        str(detail.get("_canonical_project_id") or detail.get("project"))
                        for (project, number), detail in canonical_details.items()
                        if number == key[1]
                    })
                    suffix = (
                        "; canonical project ids: " + ", ".join(canonical_projects)
                        if canonical_projects else ""
                    )
                    raise ValueError(
                        f"{legacy['par_number']} not found in project {legacy['project_id']}"
                        f"{suffix}"
                    )
            snapshot = _repair_snapshot(legacy, canonical)
        except Exception as error:
            scan_errors.append({
                "ref": {"project_id": key[0], "par_number": key[1]},
                "error": f"{type(error).__name__}: {error}",
                "before": {"needs_repair": True, "projection_debt": {}},
                "after": {"needs_repair": True, "projection_debt": {}},
            })
            continue
        states[key] = (legacy, snapshot)
        if snapshot["needs_repair"]:
            fresh[key] = expected.get(key, {"project_id": key[0], "par_number": key[1]})

    if scan_errors:
        return {
            "ok": False,
            "changed": 0,
            "idempotent": False,
            "items": [],
            "errors": scan_errors,
            "reason": "fresh scan failed; no records were mutated",
        }

    if not fresh:
        if set(expected).issubset(states) and all(
            not states[key][1]["needs_repair"] for key in expected
        ):
            return {"ok": True, "changed": 0, "idempotent": True, "items": []}
        if not set(expected).issubset(states):
            raise ValueError(
                "repair drift list changed: "
                f"expected={sorted(expected)} fresh=[]"
            )
        raise ValueError("fresh repair drift list is empty")
    if set(fresh) != set(expected):
        raise ValueError(
            "repair drift list changed: "
            f"expected={sorted(expected)} fresh={sorted(fresh)}"
        )

    items = []
    errors = []
    changed = 0
    for key in sorted(fresh):
        legacy, before = states[key]
        ref = expected[key]
        canonical_state_before = None
        try:
            canonical_state_before = _canonical_state_snapshot(store)
            store.task_update(
                str(key[1]),
                project=key[0],
                status="done",
                completed_at=legacy.get("completed_at"),
            )
            canonical = store.task_get(str(key[1]), project=key[0])
            with _conn() as conn:
                repaired_legacy = dict(conn.execute(
                    "SELECT project_id, par_number, status, completed_at, sync_revision "
                    "FROM tm_tasks WHERE id=?", (legacy["id"],)
                ).fetchone())
            after = _repair_snapshot(repaired_legacy, canonical)
            item = {"ref": ref, "before": before, "after": after}
            if after["needs_repair"]:
                errors.append({
                    "ref": ref,
                    "error": "post-repair verification failed",
                    "state": "committed_unknown",
                    "before": before,
                    "after": after,
                })
                continue
            changed += 1
            items.append(item)
        except Exception as error:
            restore_error = (
                "canonical rollback unavailable"
                if canonical_state_before is None else None
            )
            try:
                _restore_canonical_state(canonical_state_before)
            except Exception as rollback_error:
                restore_error = f"{type(rollback_error).__name__}: {rollback_error}"
            try:
                with _conn() as conn:
                    current_legacy = dict(conn.execute(
                        "SELECT project_id, par_number, status, completed_at, sync_revision "
                        "FROM tm_tasks WHERE id=?", (legacy["id"],)
                    ).fetchone())
                current_canonical = store.task_get(str(key[1]), project=key[0])
                after = _repair_snapshot(current_legacy, current_canonical)
            except Exception as snapshot_error:
                after = {
                    "needs_repair": True,
                    "projection_debt": {
                        "error": f"{type(snapshot_error).__name__}: {snapshot_error}"
                    },
                }
            errors.append({
                "ref": ref,
                "error": f"{type(error).__name__}: {error}",
                "state": "rolled_back" if restore_error is None else "committed_unknown",
                "before": before,
                "after": after,
            })
            if restore_error is not None:
                errors[-1]["rollback_error"] = restore_error
    return {
        "ok": not errors,
        "changed": changed,
        "idempotent": False,
        "items": items,
        "errors": errors,
    }


def _finalization_task_identity(task_id: int) -> TaskIdentity:
    with _conn() as conn:
        task = get_task_by_id(conn, task_id)
    if not task:
        raise ValueError(f"task {task_id} disappeared before finalization")
    return {
        "id": task["id"],
        "project_id": task["project_id"],
        "par_number": task["par_number"],
        "sync_revision": task["sync_revision"],
    }


def _apply_finalization_task_update(
    payload: dict,
    task_id: int,
    *,
    status: str,
    worker_session_id: str | None = None,
) -> dict:
    identity = _finalization_task_identity(task_id)
    try:
        result = api_update_task_if_current(
            identity,
            status=status,
            worker_session_id=worker_session_id,
            _canonical_first=True,
        )
    except Exception as error:
        detail = f"{type(error).__name__}: {error}"
        payload["task_status"] = {"ok": False, "error": detail}
        raise RuntimeError(f"task finalization failed: {detail}") from error
    debt = result.get("projection_debt") or {}
    mismatches = debt.get("mismatches") or {}
    replay_match = (
        result.get("shadow_match") is False
        and mismatches
        and set(mismatches) <= {"updated", "sync_revision"}
        and result.get("new_status") == status
    )
    if not result.get("ok") or (result.get("shadow_match") is False and not replay_match):
        if mismatches:
            detail = "; ".join(
                f"{field}: canonical={values.get('canonical')!r}, "
                f"legacy={values.get('legacy')!r}"
                for field, values in mismatches.items()
            )
        else:
            detail = str(debt.get("message") or result.get("error") or "task update failed")
        payload["task_status"] = {
            "ok": False,
            "error": detail,
            "result": result,
        }
        raise RuntimeError(f"canonical task finalization failed: {detail}")
    payload["task_status"] = {"ok": True, "result": result}
    return result


def finalize_merge_outcome(payload: dict) -> dict:
    """Apply the whole post-commit tracker stage of one merge. Safe to run twice.

    Commit links come first and each ref links on its own: after the commit point a
    vanished ref must not discard the links that do resolve. The status stage that
    follows — close current, bind next, drop reservations — is one transaction, so a
    handoff never leaves a taskless worker behind.
    """
    project_id = payload["project_id"] or payload["task"]["project_id"]
    task_db_id = payload["task"]["task_id"]
    links = {
        str(ref): link_commits_to_task(str(ref), commits, project_id)
        for ref, commits in (payload.get("commits") or {}).items()
    }
    # Commit links are durable before the lifecycle transaction below. Keep their
    # results on the payload so a later failure cannot make an applied link look
    # like it was never attempted.
    payload["links"] = links
    outcome = payload["outcome"]
    next_task = payload.get("next_task")
    reservation_id = payload["reservation_id"]
    if outcome == "complete":
        _apply_finalization_task_update(payload, task_db_id, status="done")
    if next_task:
        _apply_finalization_task_update(
            payload,
            next_task["task_id"],
            status="in_progress",
            worker_session_id=payload["session_id"],
        )
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if outcome == "complete":
                conn.execute(
                    "UPDATE tm_tasks SET worker_session_id=NULL, "
                    "sync_revision=sync_revision+1, updated_at=? WHERE id=?",
                    (_now(), task_db_id),
                )
                conn.execute(
                    "DELETE FROM tm_task_reservations WHERE task_id=? AND operation_id=?",
                    (task_db_id, reservation_id),
                )
            if next_task:
                conn.execute(
                    "DELETE FROM tm_task_reservations WHERE task_id=? AND operation_id=?",
                    (next_task["task_id"], reservation_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"ok": True, "links": links}


def release_session_task_binding(conn: sqlite3.Connection, session_id: str) -> None:
    """Recompute every binding an archived session held: elect an heir or requeue.

    Liveness of a worker is a platform fact, so the last worker leaving an unfinished
    task returns it to the queue. Any other live worker on the same task keeps it
    `in_progress` — blind requeueing would abandon work that is still running.
    """
    rows = conn.execute(
        "SELECT t.id, t.par_number, t.status, p.scope FROM tm_tasks t "
        "JOIN tm_projects p ON p.id = t.project_id WHERE t.worker_session_id = ?",
        (session_id,),
    ).fetchall()
    now = _now()
    for row in rows:
        heir = conn.execute(
            "SELECT id FROM sessions WHERE task_id = ? AND RTRIM(scope, '/') = RTRIM(?, '/') "
            "AND status != 'archived' AND id != ? ORDER BY created_at LIMIT 1",
            (str(row["par_number"]), row["scope"], session_id),
        ).fetchone()
        if heir:
            conn.execute(
                "UPDATE tm_tasks SET worker_session_id=?, sync_revision=sync_revision+1, "
                "updated_at=? WHERE id=?",
                (heir["id"], now, row["id"]),
            )
            continue
        status = "new" if row["status"] == "in_progress" else row["status"]
        conn.execute(
            "UPDATE tm_tasks SET worker_session_id=NULL, status=?, "
            "sync_revision=sync_revision+1, updated_at=? WHERE id=?",
            (status, now, row["id"]),
        )


def format_task_ref(conn: sqlite3.Connection, task: dict) -> str:
    """Format task as plain number string."""
    return str(task["par_number"])


def _link_commits_to_task(
    conn: sqlite3.Connection, task_ref: str, commits: list[dict], project_id: str,
) -> dict:
    task = resolve_task_ref(conn, task_ref, project_id)
    if not task:
        return {
            "ok": False,
            "added": 0,
            "reason": "TASK_NOT_FOUND",
            "error": f"task '{task_ref}' not found",
        }
    existing = json.loads(task["git_commits"]) if task["git_commits"] else []
    existing_hashes = {c["hash"] if isinstance(c, dict) else c for c in existing}
    new_commits = []
    for commit in commits:
        commit_hash = commit["hash"] if isinstance(commit, dict) else commit
        if commit_hash not in existing_hashes:
            new_commits.append(commit)
            existing_hashes.add(commit_hash)
    if not new_commits:
        return {"ok": True, "added": 0, "task_id": task["id"]}
    conn.execute(
        "UPDATE tm_tasks SET git_commits = ?, updated_at = ?, "
        "sync_revision = sync_revision + 1 WHERE id = ?",
        (json.dumps(existing + new_commits), _now(), task["id"]),
    )
    return {"ok": True, "added": len(new_commits), "task_id": task["id"]}


def link_commits_to_task(task_ref: str, commits: list[dict], project_id: str) -> dict:
    """Link one commit group while preserving the legacy stable result DTO."""
    if not project_id:
        raise ValueError("project authority is required for commit linking")
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = _link_commits_to_task(conn, task_ref, commits, project_id)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise




def list_tasks(conn: sqlite3.Connection, project_id: str = "",
               status: str = "", assignee: str = "") -> list[dict]:
    query = "SELECT * FROM tm_tasks WHERE 1=1"
    params: list = []
    if project_id:
        query += " AND project_id = ?"
        params.append(project_id)
    if status:
        query += " AND status = ?"
        params.append(status)
    if assignee:
        query += " AND assignee = ?"
        params.append(assignee)
    query += " ORDER BY priority ASC, par_number DESC"
    return [dict(r) for r in conn.execute(query, params).fetchall()]


# --- Payments ---












# --- High-level API for routes/MCP ---

def api_create_task(project_id: str, title: str, price: int = 0,
                    description: str = "", assignee: str = "",
                    status: str = "new", scope: str = "",
                    priority: int = 2, acceptance_command: str = "",
                    acceptance_manifest: list[str] | None = None,
                    acceptance_required: bool = False,
                    acceptance_actor: dict | None = None,
                    _canonical_par_number: int | None = None) -> dict:
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            project = None
            if project_id:
                project = resolve_project_selector(conn, project_id)
            elif scope:
                project = _project_for_session_scope(conn, scope)

            if not project or not str(project.get("scope") or "").strip():
                allowed = sorted(
                    row["scope"]
                    for row in conn.execute(
                        "SELECT scope FROM tm_projects "
                        "WHERE NULLIF(TRIM(scope), '') IS NOT NULL"
                    ).fetchall()
                )
                requested = project_id or scope
                allowed_text = ", ".join(allowed) or "none"
                raise ValueError(
                    f"project '{requested}' is not registered; "
                    f"allowed project scopes: {allowed_text}"
                )

            resolved_project_id = project["id"]
            legacy_next = _next_par(conn, resolved_project_id)
            if (
                _canonical_par_number is not None
                and legacy_next != _canonical_par_number
            ):
                raise IdentityConflictError(
                    f"task display counter mismatch in {resolved_project_id}: "
                    f"canonical={_canonical_par_number}, legacy={legacy_next}"
                )
            task = create_task(
                conn, resolved_project_id, title,
                price_rub=price,
                description=description,
                assignee=assignee,
                status=status,
                priority=priority,
                acceptance_command=acceptance_command,
                acceptance_manifest=acceptance_manifest,
                acceptance_required=acceptance_required,
                acceptance_actor=acceptance_actor,
                par_number=_canonical_par_number,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {
        "par": str(task["par_number"]),
        "id": task["id"],
        "title": task["title"],
        "project": resolved_project_id,
        "price_rub": task["price_rub"],
        "status": task["status"],
    }


def api_update_task(par: str, title: str | None = None,
                    description: str | None = None,
                    price: int | None = None,
                    status: str | None = None,
                    assignee: str | None = None,
                    project: str = "",
                    priority: int | None = None,
                    acceptance_command: str | None = None,
                    acceptance_manifest: list[str] | None = None,
                    acceptance_required: bool | None = None,
                    acceptance_actor: dict | None = None) -> dict:
    task_id = None
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            task = resolve_task_ref(conn, par, project)
            if not task:
                raise ValueError(f"{par} not found")
            task_id = task["id"]

            price_rub = price if price is not None else None
            result = update_task(
                conn, task_id,
                title=title, description=description,
                price_rub=price_rub, status=status,
                assignee=assignee, priority=priority,
                acceptance_command=acceptance_command,
                acceptance_manifest=acceptance_manifest,
                acceptance_required=acceptance_required,
                acceptance_actor=acceptance_actor,
            )

            updated = get_task_by_id(conn, task_id)
            task_ref = format_task_ref(conn, updated)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    response = {
        "par": task_ref,
        "project": updated["project_id"],
        "updated": result["changed"],
    }
    if result["changed"] in (["acceptance_command"], ["acceptance_oracle"]):
        return response
    return {
        **response,
        "old_status": result.get("old_status", updated["status"]),
        "new_status": updated["status"],
        "price_rub": updated["price_rub"],
    }


def _infer_task_worker_session(
    identity: TaskIdentity,
    *,
    status: str,
    worker_session_id: str | None,
) -> str | None:
    """Recover the session side published by a branch switch before task update."""
    if status != "in_progress" or worker_session_id is not None:
        return worker_session_id
    with _conn() as conn:
        task = get_task_by_id(conn, identity["id"])
        if not task:
            return None
        project = conn.execute(
            "SELECT scope FROM tm_projects WHERE id = ?", (task["project_id"],)
        ).fetchone()
        if not project:
            return None
        rows = conn.execute(
            "SELECT id FROM sessions WHERE task_id = ? "
            "AND RTRIM(scope, '/') = RTRIM(?, '/') "
            "AND status != 'archived' ORDER BY id",
            (str(task["par_number"]), project["scope"]),
        ).fetchall()
    if len(rows) > 1:
        owners = ", ".join(row["id"] for row in rows)
        raise ValueError(
            f"task #{task['par_number']} has multiple session bindings: {owners}"
        )
    task_worker_session_id = str(task["worker_session_id"] or "")
    if task_worker_session_id:
        if rows and rows[0]["id"] != task_worker_session_id:
            raise ValueError(
                f"task #{task['par_number']} is bound to session "
                f"'{task_worker_session_id}', but session '{rows[0]['id']}' "
                "is bound to that task"
            )
        return None
    return rows[0]["id"] if rows else None


def _validate_inferred_task_worker(
    conn: sqlite3.Connection,
    task: dict,
    worker_session_id: str,
) -> None:
    """Reject a stale session-side owner while the task write lock is held."""
    current_worker = str(task["worker_session_id"] or "")
    if current_worker and current_worker != worker_session_id:
        raise ValueError(
            f"task #{task['par_number']} worker binding changed to "
            f"'{task['worker_session_id']}' before status update"
        )
    project = conn.execute(
        "SELECT scope FROM tm_projects WHERE id = ?", (task["project_id"],)
    ).fetchone()
    if not project:
        raise ValueError(
            f"task #{task['par_number']} project disappeared before status update"
        )
    rows = conn.execute(
        "SELECT id FROM sessions WHERE task_id = ? "
        "AND RTRIM(scope, '/') = RTRIM(?, '/') "
        "AND status != 'archived' ORDER BY id",
        (str(task["par_number"]), project["scope"]),
    ).fetchall()
    if len(rows) != 1 or rows[0]["id"] != worker_session_id:
        owners = ", ".join(row["id"] for row in rows) or "none"
        raise ValueError(
            f"task #{task['par_number']} session binding changed before status update: "
            f"expected '{worker_session_id}', found {owners}"
        )


def _task_claim_precondition_error(
    conn: sqlite3.Connection,
    task: dict,
    *,
    expected_status: str,
    require_unreserved: bool,
) -> str:
    if expected_status and task["status"] != expected_status:
        return (
            f"promotion target must be {expected_status} "
            f"(found {task['status']})"
        )
    if expected_status and task.get("worker_session_id"):
        return (
            f"promotion target task #{task['par_number']} is already owned by "
            f"session '{task['worker_session_id']}'"
        )
    if require_unreserved:
        reservation = conn.execute(
            "SELECT operation_id FROM tm_task_reservations WHERE task_id=?",
            (task["id"],),
        ).fetchone()
        if reservation:
            return (
                f"promotion target task #{task['par_number']} is reserved by "
                f"operation {reservation['operation_id']}"
            )
    return ""


def validate_task_promotion_target(
    identity: TaskIdentity,
    *,
    scope: str,
    session_id: str,
    expected_branch: str,
) -> None:
    """Fail early for UX; the mutation owner repeats these checks transactionally."""
    with _TASK_BINDING_LOCK, _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            session = conn.execute(
                "SELECT id, scope, status, task_id, needs_switch, branch FROM sessions "
                "WHERE id=?",
                (session_id,),
            ).fetchone()
            if not session or session["status"] == "archived":
                raise ValueError("session is not available for promotion")
            if session["scope"].rstrip("/") != scope.rstrip("/"):
                raise ValueError("session promotion scope changed")
            if str(session["task_id"] or ""):
                raise ValueError("session is already bound to a task")
            if bool(session["needs_switch"]):
                raise ValueError("normal completed session cannot promote its previous branch")
            if str(session["branch"] or "") != expected_branch:
                raise ValueError("session branch changed before promotion")
            project = get_project_by_scope(conn, scope.rstrip("/"))
            if not project or project["id"] != identity["project_id"]:
                raise ValueError("promotion target is outside the session project")
            task = get_task_by_id(conn, identity["id"])
            if not task:
                raise ValueError("promotion target disappeared")
            if (
                task["project_id"] != identity["project_id"]
                or task["par_number"] != identity["par_number"]
                or task["sync_revision"] != identity["sync_revision"]
            ):
                raise ValueError("promotion target identity changed")
            error = _task_claim_precondition_error(
                conn, task, expected_status="new", require_unreserved=True,
            )
            if error:
                raise ValueError(error)
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def task_binding_requires_quarantine(
    scope: str, session_id: str, task_ref: str,
) -> bool:
    """Distinguish incomplete live ownership from a stale completed-task binding."""
    with _conn() as conn:
        project = get_project_by_scope(conn, scope.rstrip("/"))
        if not project:
            # Pre-task-tracker sessions legitimately carry stale task ids; their established
            # auto-switch path is the only recovery and has no task row to protect.
            return False
        task = resolve_task_ref(conn, task_ref, project["id"])
        if not task:
            return True
        return not (
            task["status"] == "done"
            and not task.get("worker_session_id")
        )


def api_update_task_if_current(
    identity: TaskIdentity,
    *,
    status: str,
    worker_session_id: str | None = None,
    expected_status: str = "",
    require_unreserved: bool = False,
) -> dict:
    """Update a prevalidated task only while its immutable identity/version matches."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    binding_inferred = worker_session_id is None and status == "in_progress"
    worker_session_id = _infer_task_worker_session(
        identity, status=status, worker_session_id=worker_session_id,
    )
    task_id = identity["id"]
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            task = get_task_by_id(conn, task_id)
            if not task:
                conn.rollback()
                return {
                    "ok": False,
                    "task_id": task_id,
                    "error": "prevalidated task no longer exists",
                }
            if (
                task["project_id"] != identity["project_id"]
                or task["par_number"] != identity["par_number"]
            ):
                conn.rollback()
                return {
                    "ok": False,
                    "task_id": task_id,
                    "error": "prevalidated task identity changed before status update",
                }
            if task["sync_revision"] != identity["sync_revision"]:
                conn.rollback()
                return {
                    "ok": False,
                    "task_id": task_id,
                    "error": (
                        "prevalidated task revision changed before status update: "
                        f"expected {identity['sync_revision']}, "
                        f"found {task['sync_revision']}"
                    ),
                }
            claim_error = _task_claim_precondition_error(
                conn,
                task,
                expected_status=expected_status,
                require_unreserved=require_unreserved,
            )
            if claim_error:
                conn.rollback()
                return {"ok": False, "task_id": task_id, "error": claim_error}
            if binding_inferred and worker_session_id:
                _validate_inferred_task_worker(conn, task, worker_session_id)
            result = update_task(
                conn,
                task_id,
                status=status,
                worker_session_id=worker_session_id,
            )
            updated = get_task_by_id(conn, task_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {
        "ok": True,
        "task_id": task_id,
        "par": str(identity["par_number"]),
        "updated": result["changed"],
        "new_status": updated["status"],
        "sync_revision": updated["sync_revision"],
    }


def api_list_tasks(project: str = "", status: str = "",
                   assignee: str = "") -> dict:
    with _conn() as conn:
        resolved_project = ""
        if project:
            project_row = resolve_project_id(conn, project)
            if not project_row:
                raise ValueError(f"project '{project}' not found")
            resolved_project = project_row["id"]
        tasks = list_tasks(
            conn, project_id=resolved_project, status=status, assignee=assignee,
        )

    return {
        "tasks": [
            {
                "par": str(t["par_number"]),
                "title": t["title"],
                "project": t["project_id"],
                "price": _fmt_amount(t["price_rub"]),
                "status": t["status"],
                "assignee": t["assignee"],
                "priority": t.get("priority", 2),
            }
            for t in tasks
        ],
        "count": len(tasks),
    }


def api_get_task(par: str, project: str = "") -> dict:
    with _conn() as conn:
        task = resolve_task_ref(conn, par, project)
        if not task:
            raise ValueError(f"{par} not found")

        task_ref = format_task_ref(conn, task)

    commits = json.loads(task["git_commits"]) if task["git_commits"] else []

    return {
        "par": task_ref,
        "title": task["title"],
        "description": task["description"],
        "project": task["project_id"],
        "price_rub": task["price_rub"],
        "status": task["status"],
        "assignee": task["assignee"],
        "priority": task.get("priority", 2),
        "created_at": task["created_at"],
        "completed_at": task["completed_at"],
        "commits": commits,
        "sync_revision": task["sync_revision"],
    }


# The legacy functions above remain the exact default path.  The aliases make
# the opt-in adapter explicit and keep routes/MCP on the existing public owner.
_legacy_resolve_scoped_task_identity = resolve_scoped_task_identity
_legacy_link_commits_to_task = link_commits_to_task
_legacy_api_create_task = api_create_task
_legacy_api_update_task = api_update_task
_legacy_api_update_task_if_current = api_update_task_if_current
_legacy_api_list_tasks = api_list_tasks
_legacy_api_get_task = api_get_task


@dataclass(frozen=True)
class _IATaskStoreContext:
    mode: str
    store: TaskStore | None


_IA_TASK_STORE_CONTEXT: ContextVar[_IATaskStoreContext | None] = ContextVar(
    "ia_task_store_context",
    default=None,
)
_IA_PROCESS_TASK_STORE_CONTEXT: _IATaskStoreContext | None = None


def _ia_context() -> _IATaskStoreContext | None:
    context = _IA_TASK_STORE_CONTEXT.get()
    if context is None:
        context = _IA_PROCESS_TASK_STORE_CONTEXT
    if context is None or context.mode == "legacy":
        return None
    return context


@contextmanager
def ia_process_task_store_mode(*, store: TaskStore, mode: str = "shadow"):
    """Configure the task candidate for all HTTP/background execution contexts.

    Lifespan ContextVars do not propagate into Uvicorn request tasks. The production owner is one
    process-global store; its adapter supplies the serialization policy.
    """

    if mode not in {"shadow", "canonical"}:
        raise ValueError(f"unsupported IA task store mode: {mode}")
    global _IA_PROCESS_TASK_STORE_CONTEXT
    if _IA_PROCESS_TASK_STORE_CONTEXT is not None:
        raise RuntimeError("process task store is already configured")
    _IA_PROCESS_TASK_STORE_CONTEXT = _IATaskStoreContext(mode=mode, store=store)
    try:
        yield store
    finally:
        _IA_PROCESS_TASK_STORE_CONTEXT = None


def _legacy_task_snapshot(*, cutoff: str, source_head: str) -> dict:
    """Read one transactionally consistent legacy snapshot for an opt-in store."""

    with _conn() as conn:
        conn.execute("BEGIN")
        try:
            projects = [dict(row) for row in conn.execute(
                "SELECT * FROM tm_projects ORDER BY id"
            ).fetchall()]
            tasks = []
            for row in conn.execute("SELECT * FROM tm_tasks ORDER BY id").fetchall():
                task = dict(row)
                task["git_commits"] = json.loads(task.get("git_commits") or "[]")
                task["acceptance_oracle_json"] = parse_acceptance_oracle(
                    task.get("acceptance_oracle_json")
                )
                tasks.append(task)
            clients = [dict(row) for row in conn.execute(
                "SELECT * FROM tm_clients ORDER BY id"
            ).fetchall()]
            payments = [dict(row) for row in conn.execute(
                "SELECT * FROM tm_payments ORDER BY id"
            ).fetchall()]
            allocations = [dict(row) for row in conn.execute(
                "SELECT * FROM tm_payment_allocations ORDER BY id"
            ).fetchall()]
            sync_rows = [dict(row) for row in conn.execute(
                "SELECT * FROM tm_sync_log ORDER BY id"
            ).fetchall()]
            schema = {
                table: [tuple(row) for row in conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()]
                for table in ("tm_projects", "tm_tasks")
            }
            conn.rollback()
        except Exception:
            conn.rollback()
            raise
    schema_bytes = json.dumps(
        schema,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "source": {
            "cutoff": cutoff,
            "source_head": source_head,
            "source_schema_sha256": f"sha256:{sha256(schema_bytes).hexdigest()}",
        },
        "projects": projects,
        "tasks": tasks,
        "evidence": [],
        "clients": clients,
        "payments": payments,
        "payment_allocations": allocations,
        "sync_log": sync_rows,
    }


@contextmanager
def ia_task_store_mode(
    *,
    mode: str = "legacy",
    canonical_root: Path | None = None,
    projection_path: Path | None = None,
    cutoff: str = "",
    source_head: str = "",
) -> Iterator[TaskStore | None]:
    """Temporarily select legacy, synchronous shadow, or canonical task ownership."""

    if mode not in {"legacy", "shadow", "canonical"}:
        raise ValueError(f"unsupported IA task store mode: {mode}")
    store = None
    if mode != "legacy":
        if canonical_root is None or projection_path is None:
            raise ValueError("canonical_root and projection_path are required")
        if not cutoff or not source_head:
            raise ValueError("cutoff and source_head are required")
        store = TaskStore(
            canonical_root=Path(canonical_root),
            projection_path=Path(projection_path),
        )
        manifest = build_migration_manifest(
            _legacy_task_snapshot(cutoff=cutoff, source_head=source_head)
        )
        store.migrate(manifest)
    token = _IA_TASK_STORE_CONTEXT.set(_IATaskStoreContext(mode=mode, store=store))
    try:
        yield store
    finally:
        _IA_TASK_STORE_CONTEXT.reset(token)


def _candidate_receipts(candidate: dict, context: _IATaskStoreContext) -> dict:
    store = context.store
    assert store is not None
    return {
        "ia_mode": context.mode,
        "stable_id": candidate["stable_id"],
        "canonical_head": candidate.get("canonical_head") or store.canonical_head,
        "projection_head": candidate.get("projection_head") or store.projection_head,
        "evidence_refs": list(candidate.get("evidence_refs") or []),
    }


def _candidate_rejection_debt(candidate: dict) -> dict:
    """Describe a store rejection, which carries no receipts to report."""
    return {
        "reason": "candidate_update_rejected",
        "message": str(candidate.get("error") or "canonical task update rejected"),
    }


def _list_receipts(context: _IATaskStoreContext) -> dict:
    store = context.store
    assert store is not None
    return {
        "ia_mode": context.mode,
        "canonical_head": store.canonical_head,
        "projection_head": store.projection_head,
    }


_CREATE_COMPARE_FIELDS = ("par", "title", "project", "price_rub", "status")
_GET_COMPARE_FIELDS = (
    "par",
    "title",
    "description",
    "project",
    "price_rub",
    "status",
    "assignee",
    "priority",
    "created_at",
    "completed_at",
    "commits",
    "sync_revision",
)
_UPDATE_COMPARE_FIELDS = (
    "par",
    "project",
    "updated",
    "old_status",
    "new_status",
    "price_rub",
)


def _comparison_debt(legacy: dict, candidate: dict, fields: tuple[str, ...]) -> dict:
    differences = {
        field: {"legacy": legacy.get(field), "canonical": candidate.get(field)}
        for field in fields
        if legacy.get(field) != candidate.get(field)
    }
    return {"mismatches": differences} if differences else {}


def _shadow_result(
    legacy: dict,
    candidate: dict,
    context: _IATaskStoreContext,
    fields: tuple[str, ...],
) -> dict:
    debt = _comparison_debt(legacy, candidate, fields)
    additive = {
        field: candidate[field]
        for field in ("acceptance", "display_ref", "worker_session_id")
        if field in candidate
    }
    return {
        **legacy,
        **additive,
        **_candidate_receipts(candidate, context),
        "shadow_match": not debt,
        "projection_debt": debt,
    }


def _shadow_failure(
    legacy: dict,
    context: _IATaskStoreContext,
    error: BaseException,
) -> dict:
    store = context.store
    assert store is not None
    debt = {
        "reason": "candidate_write_failed",
        "exception_type": type(error).__name__,
        "message": str(error),
    }
    recorder = getattr(store, "record_debt", None)
    if callable(recorder):
        recorder(debt)
    try:
        canonical_head = store.canonical_head
    except Exception:
        canonical_head = ""
    try:
        projection_head = store.projection_head
    except Exception:
        projection_head = ""
    return {
        **legacy,
        "ia_mode": context.mode,
        "canonical_head": canonical_head,
        "projection_head": projection_head,
        "shadow_match": False,
        "projection_debt": debt,
    }


def _canonical_result(
    candidate: dict,
    legacy: dict,
    context: _IATaskStoreContext,
    fields: tuple[str, ...],
) -> dict:
    debt = _comparison_debt(legacy, candidate, fields)
    return {
        **candidate,
        **_candidate_receipts(candidate, context),
        "projection_debt": debt,
    }


def _merge_canonical_task_identity(
    legacy: TaskIdentity,
    detail: dict,
) -> TaskIdentity:
    """Require canonical and legacy readers to identify the same task."""
    stable_id = str(detail.get("stable_id") or "")
    project_id = str(detail.get("project") or detail.get("project_id") or "")
    raw_par = detail.get("par", detail.get("display_number"))
    try:
        par_number = int(raw_par)
    except (TypeError, ValueError):
        par_number = 0
    if not stable_id:
        raise ValueError(
            "canonical task identity missing stable_id for "
            f"project '{legacy['project_id']}' task #{legacy['par_number']}"
        )
    if (
        project_id != str(legacy["project_id"])
        or par_number != int(legacy["par_number"])
        or (
            legacy.get("stable_id")
            and str(legacy["stable_id"]) != stable_id
        )
    ):
        raise ValueError(
            "canonical task identity mismatch for "
            f"project '{legacy['project_id']}' task #{legacy['par_number']}: "
            f"reader returned project '{project_id}' task #{par_number} "
            f"stable_id '{stable_id}'"
        )
    merged = dict(legacy)
    merged.pop("canonical_head", None)
    merged["stable_id"] = stable_id
    return merged


def resolve_scoped_task_identity(scope: str, ref: str) -> TaskIdentity:
    legacy = _legacy_resolve_scoped_task_identity(scope, ref)
    context = _ia_context()
    if context is None:
        return legacy
    store = context.store
    assert store is not None
    try:
        candidate = store.task_get(str(legacy["par_number"]), project=legacy["project_id"])
    except (KeyError, ValueError) as error:
        raise ValueError(
            "canonical task identity unavailable for "
            f"project '{legacy['project_id']}' task #{legacy['par_number']}: {error}"
        ) from error
    return _merge_canonical_task_identity(legacy, candidate)


def normalize_task_create_request_key(value: str = "") -> str:
    request_key = str(value or "").strip() or uuid.uuid4().hex
    if _TASK_CREATE_REQUEST_KEY.fullmatch(request_key) is None:
        raise TaskCreateRequestError(
            "INVALID_IDEMPOTENCY_KEY",
            request_key,
            "idempotency key must be 16-128 ASCII letters, digits, '.', '_', ':', or '-'",
        )
    return request_key


def _resolve_task_create_project(project_id: str, scope: str) -> str:
    with _conn() as conn:
        project = resolve_project_selector(conn, project_id) if project_id else None
        if project is None and scope:
            project = _project_for_session_scope(conn, scope)
        if project and str(project.get("scope") or "").strip():
            return str(project["id"])
        allowed = sorted(
            row["scope"]
            for row in conn.execute(
                "SELECT scope FROM tm_projects "
                "WHERE NULLIF(TRIM(scope), '') IS NOT NULL"
            ).fetchall()
        )
    requested = project_id or scope
    raise ValueError(
        f"project '{requested}' is not registered; "
        f"allowed project scopes: {', '.join(allowed) or 'none'}"
    )


def _task_create_request_row(
    conn: sqlite3.Connection,
    project_id: str,
    request_key: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM tm_task_create_requests WHERE project_id=? AND request_key=?",
        (project_id, request_key),
    ).fetchone()


def _task_create_replay(row: sqlite3.Row) -> dict | None:
    raw = str(row["response_json"] or "")
    if not raw:
        return None
    response = json.loads(raw)
    if not isinstance(response, dict):
        raise RuntimeError("task-create receipt response is not an object")
    response["request_key"] = str(row["request_key"])
    response["replayed"] = True
    return response


def _raise_task_create_conflict(row: sqlite3.Row, fingerprint: str) -> None:
    if str(row["fingerprint"]) != fingerprint:
        raise TaskCreateRequestError(
            "IDEMPOTENCY_FINGERPRINT_MISMATCH",
            str(row["request_key"]),
            "idempotency key was already used with a different task body",
        )


def _legacy_task_create_response(
    task: dict,
    *,
    request_key: str,
    replayed: bool,
) -> dict:
    return {
        "par": str(task["par_number"]),
        "id": task["id"],
        "title": task["title"],
        "project": task["project_id"],
        "price_rub": task["price_rub"],
        "status": task["status"],
        "request_key": request_key,
        "replayed": replayed,
    }


def _legacy_create_idempotent(
    *,
    project_id: str,
    request_key: str,
    fingerprint: str,
    final_state: str,
    title: str,
    price: int,
    description: str,
    assignee: str,
    status: str,
    priority: int,
    acceptance_command: str,
    acceptance_manifest: list[str] | None,
    acceptance_required: bool,
    acceptance_actor: dict | None,
) -> tuple[dict, bool]:
    now = _now()
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = _task_create_request_row(conn, project_id, request_key)
            if row is not None:
                _raise_task_create_conflict(row, fingerprint)
                replay = _task_create_replay(row)
                if replay is None:
                    raise TaskCreateRequestError(
                        "IDEMPOTENCY_REQUEST_PENDING",
                        request_key,
                        "task-create request is still pending",
                    )
                conn.commit()
                return replay, True
            conn.execute(
                "INSERT INTO tm_task_create_requests("
                "project_id,request_key,fingerprint,active_owner,generation,state,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    project_id,
                    request_key,
                    fingerprint,
                    "legacy",
                    1,
                    "PENDING",
                    now,
                    now,
                ),
            )
            task = create_task(
                conn,
                project_id,
                title,
                price_rub=price,
                description=description,
                assignee=assignee,
                status=status,
                priority=priority,
                acceptance_command=acceptance_command,
                acceptance_manifest=acceptance_manifest,
                acceptance_required=acceptance_required,
                acceptance_actor=acceptance_actor,
            )
            response = _legacy_task_create_response(
                task,
                request_key=request_key,
                replayed=False,
            )
            conn.execute(
                "UPDATE tm_task_create_requests SET state=?,task_id=?,par_number=?,"
                "response_json=?,updated_at=? WHERE project_id=? AND request_key=?",
                (
                    final_state,
                    task["id"],
                    task["par_number"],
                    json.dumps(response, ensure_ascii=False, sort_keys=True),
                    _now(),
                    project_id,
                    request_key,
                ),
            )
            conn.commit()
            return response, False
        except Exception:
            conn.rollback()
            raise


def _reserve_canonical_create(
    project_id: str,
    request_key: str,
    fingerprint: str,
) -> tuple[bool, dict | None]:
    now = _now()
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = _task_create_request_row(conn, project_id, request_key)
            if row is not None:
                _raise_task_create_conflict(row, fingerprint)
                replay = _task_create_replay(row)
                conn.commit()
                return False, replay
            conn.execute(
                "INSERT INTO tm_task_create_requests("
                "project_id,request_key,fingerprint,active_owner,generation,state,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    project_id,
                    request_key,
                    fingerprint,
                    "canonical",
                    1,
                    "PENDING",
                    now,
                    now,
                ),
            )
            conn.commit()
            return True, None
        except Exception:
            conn.rollback()
            raise


def _save_task_create_request(
    *,
    project_id: str,
    request_key: str,
    fingerprint: str,
    state: str,
    task_id: str | int,
    par_number: int,
    response: dict,
    error: BaseException | None = None,
) -> None:
    error_json = ""
    if error is not None:
        error_json = json.dumps(
            {"exception_type": type(error).__name__, "message": str(error)},
            ensure_ascii=False,
            sort_keys=True,
        )
    with _conn() as conn:
        updated = conn.execute(
            "UPDATE tm_task_create_requests SET state=?,task_id=?,par_number=?,"
            "response_json=?,error_json=?,updated_at=? "
            "WHERE project_id=? AND request_key=? AND fingerprint=?",
            (
                state,
                task_id,
                par_number,
                json.dumps(response, ensure_ascii=False, sort_keys=True),
                error_json,
                _now(),
                project_id,
                request_key,
                fingerprint,
            ),
        )
        if updated.rowcount != 1:
            raise RuntimeError("task-create receipt disappeared during commit")
        conn.commit()


def _delete_pending_task_create_request(
    *,
    project_id: str,
    request_key: str,
    fingerprint: str,
) -> None:
    with _conn() as conn:
        conn.execute(
            "DELETE FROM tm_task_create_requests "
            "WHERE project_id=? AND request_key=? AND fingerprint=? AND state='PENDING'",
            (project_id, request_key, fingerprint),
        )
        conn.commit()


def _legacy_mirror_canonical_create(
    *,
    project_id: str,
    display_number: int,
    request_key: str,
    title: str,
    price: int,
    description: str,
    assignee: str,
    status: str,
    priority: int,
    acceptance_command: str,
    acceptance_manifest: list[str] | None,
    acceptance_required: bool,
    acceptance_actor: dict | None,
) -> dict:
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            stored = conn.execute(
                "SELECT * FROM tm_tasks WHERE project_id=? AND par_number=?",
                (project_id, display_number),
            ).fetchone()
            if stored is not None:
                task = dict(stored)
                expected = (
                    title,
                    description,
                    price,
                    status,
                    assignee,
                    priority,
                )
                observed = tuple(task[field] for field in (
                    "title",
                    "description",
                    "price_rub",
                    "status",
                    "assignee",
                    "priority",
                ))
                if observed != expected:
                    raise IdentityConflictError(
                        f"legacy mirror #{display_number} has different task content"
                    )
            else:
                legacy_next = _next_par(conn, project_id)
                if legacy_next != display_number:
                    raise IdentityConflictError(
                        f"task display counter mismatch in {project_id}: "
                        f"canonical={display_number}, legacy={legacy_next}"
                    )
                task = create_task(
                    conn,
                    project_id,
                    title,
                    price_rub=price,
                    description=description,
                    assignee=assignee,
                    status=status,
                    par_number=display_number,
                    priority=priority,
                    acceptance_command=acceptance_command,
                    acceptance_manifest=acceptance_manifest,
                    acceptance_required=acceptance_required,
                    acceptance_actor=acceptance_actor,
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return _legacy_task_create_response(task, request_key=request_key, replayed=False)


def api_task_create_status(
    request_key: str,
    *,
    project_id: str = "",
    scope: str = "",
) -> dict:
    request_key = normalize_task_create_request_key(request_key)
    resolved_project_id = _resolve_task_create_project(project_id, scope)
    with _conn() as conn:
        row = _task_create_request_row(conn, resolved_project_id, request_key)
    if row is None:
        raise ValueError("task-create request not found")
    response = _task_create_replay(row) or {}
    task_id: str | int | None = response.get("id") or response.get("task_id") or row["task_id"]
    if isinstance(task_id, str) and task_id.isdigit():
        task_id = int(task_id)
    return {
        "project": resolved_project_id,
        "request_key": request_key,
        "fingerprint": row["fingerprint"],
        "active_owner": row["active_owner"],
        "generation": row["generation"],
        "state": row["state"],
        "task_id": task_id,
        "par_number": row["par_number"],
        "result": response or None,
        "error": json.loads(row["error_json"]) if row["error_json"] else None,
    }


def api_create_task(project_id: str, title: str, price: int = 0,
                    description: str = "", assignee: str = "",
                    status: str = "new", scope: str = "",
                    priority: int = 2, acceptance_command: str = "",
                    acceptance_manifest: list[str] | None = None,
                    acceptance_required: bool = False,
                    acceptance_actor: dict | None = None,
                    request_key: str = "") -> dict:
    # A caller-held key makes an ambiguous shadow result replayable. Internal allocations have
    # no key to retry with, so they must compensate a proven legacy-only row and fail loudly.
    durable_request = bool(str(request_key or "").strip())
    request_key = normalize_task_create_request_key(request_key)
    resolved_project_id = _resolve_task_create_project(project_id, scope)
    fingerprint = task_create_fingerprint(
        project_id=resolved_project_id,
        title=title,
        price=price,
        description=description,
        assignee=assignee,
        status=status,
        priority=priority,
        acceptance_command=acceptance_command,
        acceptance_manifest=acceptance_manifest,
        acceptance_required=acceptance_required,
    )
    context = _ia_context()
    if context is None:
        result, _replayed = _legacy_create_idempotent(
            project_id=resolved_project_id,
            request_key=request_key,
            fingerprint=fingerprint,
            final_state="MIRRORS_COMMITTED",
            title=title,
            price=price,
            description=description,
            assignee=assignee,
            status=status,
            priority=priority,
            acceptance_command=acceptance_command,
            acceptance_manifest=acceptance_manifest,
            acceptance_required=acceptance_required,
            acceptance_actor=acceptance_actor,
        )
        return result
    store = context.store
    assert store is not None

    if context.mode == "shadow":
        if not durable_request:
            with _TASK_CREATE_LOCK:
                with ia_task_store_mode(mode="legacy"):
                    legacy = _legacy_api_create_task(
                        resolved_project_id, title, price, description, assignee, status,
                        priority=priority,
                        acceptance_command=acceptance_command,
                        acceptance_manifest=acceptance_manifest,
                        acceptance_required=acceptance_required,
                        acceptance_actor=acceptance_actor,
                    )
                try:
                    candidate = store.task_create(
                        project_id=legacy["project"],
                        title=title,
                        price=price,
                        description=description,
                        assignee=assignee,
                        status=status,
                        priority=priority,
                        acceptance_command=acceptance_command,
                        acceptance_manifest=acceptance_manifest,
                        acceptance_required=acceptance_required,
                        display_number=int(legacy["par"]),
                        expected_head=store.canonical_head,
                    )
                except Exception as error:
                    _compensate_failed_task_create(store, legacy)
                    try:
                        _shadow_failure(legacy, context, error)
                    except Exception as debt_error:
                        logger.warning(
                            "shadow task create debt recording failed: %s: %s",
                            type(debt_error).__name__, debt_error,
                        )
                    raise RuntimeError(
                        "shadow task creation failed: "
                        f"{type(error).__name__}: {error}"
                    ) from error
                return _shadow_result(legacy, candidate, context, _CREATE_COMPARE_FIELDS)

        with _TASK_CREATE_LOCK:
            with ia_task_store_mode(mode="legacy"):
                legacy, replayed = _legacy_create_idempotent(
                    project_id=resolved_project_id,
                    request_key=request_key,
                    fingerprint=fingerprint,
                    final_state="ACTIVE_COMMITTED",
                    title=title,
                    price=price,
                    description=description,
                    assignee=assignee,
                    status=status,
                    priority=priority,
                    acceptance_command=acceptance_command,
                    acceptance_manifest=acceptance_manifest,
                    acceptance_required=acceptance_required,
                    acceptance_actor=acceptance_actor,
                )
            if replayed:
                return legacy
            try:
                candidate = store.task_create(
                    project_id=legacy["project"],
                    title=title,
                    price=price,
                    description=description,
                    assignee=assignee,
                    status=status,
                    priority=priority,
                    acceptance_command=acceptance_command,
                    acceptance_manifest=acceptance_manifest,
                    acceptance_required=acceptance_required,
                    display_number=int(legacy["par"]),
                    expected_head=store.canonical_head,
                    request_key=request_key,
                )
            except Exception as error:
                result = _shadow_failure(legacy, context, error)
                _save_task_create_request(
                    project_id=resolved_project_id,
                    request_key=request_key,
                    fingerprint=fingerprint,
                    state="ACTIVE_COMMITTED",
                    task_id=legacy["id"],
                    par_number=int(legacy["par"]),
                    response=result,
                    error=error,
                )
                return result
            result = _shadow_result(legacy, candidate, context, _CREATE_COMPARE_FIELDS)
            _save_task_create_request(
                project_id=resolved_project_id,
                request_key=request_key,
                fingerprint=fingerprint,
                state="MIRRORS_COMMITTED",
                task_id=legacy["id"],
                par_number=int(legacy["par"]),
                response=result,
            )
            return result

    if not durable_request:
        with _TASK_CREATE_LOCK:
            with _conn() as conn:
                legacy_next = _next_par(conn, resolved_project_id)
                vps_task_range = (
                    _task_project_scope(conn, resolved_project_id)
                    == "/home/kesha/orchestra"
                )
            canonical_next = int(
                store.task_list(project=resolved_project_id)["next_display_number"]
            )
            if (
                vps_task_range
                and canonical_next < _VPS_TASK_PAR_FLOOR
            ):
                canonical_next = legacy_next
            if canonical_next != legacy_next:
                raise IdentityConflictError(
                    f"task display counter mismatch in {resolved_project_id}: "
                    f"canonical={canonical_next}, legacy={legacy_next}"
                )
            legacy = _legacy_api_create_task(
                resolved_project_id, title, price, description, assignee, status,
                priority=priority,
                acceptance_command=acceptance_command,
                acceptance_manifest=acceptance_manifest,
                acceptance_required=acceptance_required,
                acceptance_actor=acceptance_actor,
                _canonical_par_number=canonical_next,
            )
            try:
                candidate = store.task_create(
                    project_id=resolved_project_id,
                    title=title,
                    price=price,
                    description=description,
                    assignee=assignee,
                    status=status,
                    priority=priority,
                    acceptance_command=acceptance_command,
                    acceptance_manifest=acceptance_manifest,
                    acceptance_required=acceptance_required,
                    display_number=canonical_next,
                    expected_head=store.canonical_head,
                )
            except Exception:
                _compensate_failed_task_create(store, legacy)
                raise
        candidate["id"] = legacy["id"]
        return _canonical_result(candidate, legacy, context, _CREATE_COMPARE_FIELDS)

    new_request, replay = _reserve_canonical_create(
        resolved_project_id,
        request_key,
        fingerprint,
    )
    if replay is not None:
        return replay
    candidate = None
    if not new_request:
        lookup = getattr(store, "task_create_request", None)
        if callable(lookup):
            candidate = lookup(
                project_id=resolved_project_id,
                request_key=request_key,
            )
        if candidate is None:
            raise TaskCreateRequestError(
                "IDEMPOTENCY_REQUEST_PENDING",
                request_key,
                "task-create request is still pending",
            )
        if candidate.get("request_fingerprint") != fingerprint:
            raise TaskCreateRequestError(
                "IDEMPOTENCY_FINGERPRINT_MISMATCH",
                request_key,
                "canonical request identity has a different task body",
            )

    with _TASK_CREATE_LOCK:
        legacy = None
        if candidate is None:
            try:
                with _conn() as conn:
                    legacy_next = _next_par(conn, resolved_project_id)
                    vps_task_range = (
                        _task_project_scope(conn, resolved_project_id)
                        == "/home/kesha/orchestra"
                    )
                canonical_next = int(
                    store.task_list(project=resolved_project_id)["next_display_number"]
                )
                if (
                    vps_task_range
                    and canonical_next < _VPS_TASK_PAR_FLOOR
                ):
                    canonical_next = legacy_next
                if canonical_next != legacy_next:
                    raise IdentityConflictError(
                        f"task display counter mismatch in {resolved_project_id}: "
                        f"canonical={canonical_next}, legacy={legacy_next}"
                    )
                legacy = _legacy_mirror_canonical_create(
                    project_id=resolved_project_id,
                    display_number=canonical_next,
                    request_key=request_key,
                    title=title,
                    price=price,
                    description=description,
                    assignee=assignee,
                    status=status,
                    priority=priority,
                    acceptance_command=acceptance_command,
                    acceptance_manifest=acceptance_manifest,
                    acceptance_required=acceptance_required,
                    acceptance_actor=acceptance_actor,
                )
                candidate = store.task_create(
                    project_id=resolved_project_id,
                    title=title,
                    price=price,
                    description=description,
                    assignee=assignee,
                    status=status,
                    priority=priority,
                    acceptance_command=acceptance_command,
                    acceptance_manifest=acceptance_manifest,
                    acceptance_required=acceptance_required,
                    display_number=canonical_next,
                    expected_head=store.canonical_head,
                    request_key=request_key,
                )
            except Exception as error:
                lookup = getattr(store, "task_create_request", None)
                try:
                    recovered = (
                        lookup(
                            project_id=resolved_project_id,
                            request_key=request_key,
                        )
                        if callable(lookup)
                        else None
                    )
                except Exception:
                    raise error
                if recovered is None:
                    if legacy is not None:
                        _compensate_failed_task_create(store, legacy)
                    _delete_pending_task_create_request(
                        project_id=resolved_project_id,
                        request_key=request_key,
                        fingerprint=fingerprint,
                    )
                    raise error
                if recovered.get("request_fingerprint") != fingerprint:
                    raise TaskCreateRequestError(
                        "IDEMPOTENCY_FINGERPRINT_MISMATCH",
                        request_key,
                        "canonical request identity has a different task body",
                    )
                candidate = recovered

        canonical_next = int(candidate["par"])
        candidate.setdefault("request_key", request_key)
        candidate.setdefault("request_fingerprint", fingerprint)
        candidate.setdefault("replayed", False)
        _save_task_create_request(
            project_id=resolved_project_id,
            request_key=request_key,
            fingerprint=fingerprint,
            state="ACTIVE_COMMITTED",
            task_id=candidate["task_id"],
            par_number=canonical_next,
            response=candidate,
        )
        try:
            if legacy is None:
                legacy = _legacy_mirror_canonical_create(
                    project_id=resolved_project_id,
                    display_number=canonical_next,
                    request_key=request_key,
                    title=title,
                    price=price,
                    description=description,
                    assignee=assignee,
                    status=status,
                    priority=priority,
                    acceptance_command=acceptance_command,
                    acceptance_manifest=acceptance_manifest,
                    acceptance_required=acceptance_required,
                    acceptance_actor=acceptance_actor,
                )
        except Exception as error:
            result = {**candidate, **_candidate_receipts(candidate, context)}
            _save_task_create_request(
                project_id=resolved_project_id,
                request_key=request_key,
                fingerprint=fingerprint,
                state="ACTIVE_COMMITTED",
                task_id=candidate["task_id"],
                par_number=canonical_next,
                response=result,
                error=error,
            )
            return result

    candidate["id"] = legacy["id"]
    result = _canonical_result(candidate, legacy, context, _CREATE_COMPARE_FIELDS)
    _save_task_create_request(
        project_id=resolved_project_id,
        request_key=request_key,
        fingerprint=fingerprint,
        state="MIRRORS_COMMITTED",
        task_id=candidate["task_id"],
        par_number=canonical_next,
        response=result,
    )
    return result


def api_update_task(par: str, title: str | None = None,
                    description: str | None = None,
                    price: int | None = None,
                    status: str | None = None,
                    assignee: str | None = None,
                    project: str = "",
                    priority: int | None = None,
                    acceptance_command: str | None = None,
                    acceptance_manifest: list[str] | None = None,
                    acceptance_required: bool | None = None,
                    acceptance_actor: dict | None = None) -> dict:
    context = _ia_context()
    if context is None:
        return _legacy_api_update_task(
            par, title, description, price, status, assignee, project, priority,
            acceptance_command, acceptance_manifest, acceptance_required,
            acceptance_actor,
        )
    store = context.store
    assert store is not None
    candidate_args = {
        "project": project,
        "title": title,
        "description": description,
        "price": price,
        "status": status,
        "assignee": assignee,
        "priority": priority,
        "acceptance_command": acceptance_command,
        "acceptance_manifest": acceptance_manifest,
        "acceptance_required": acceptance_required,
    }
    legacy_args = (
        par, title, description, price, status, assignee, project, priority,
        acceptance_command, acceptance_manifest, acceptance_required,
        acceptance_actor,
    )
    if context.mode == "shadow":
        legacy = _legacy_api_update_task(*legacy_args)
        try:
            candidate = store.task_update(
                par,
                **candidate_args,
                expected_head=store.canonical_head,
            )
        except Exception as error:
            return _shadow_failure(legacy, context, error)
        return _shadow_result(legacy, candidate, context, _UPDATE_COMPARE_FIELDS)
    # Тот же порядок, что и в создании: валидирующее хранилище идёт ПЕРВЫМ. Приёмочный
    # оракул, актора и манифест проверяет только legacy (`acceptance_actor` в canonical не
    # передаётся вовсе), а отменить canonical-обновление нечем — валидация после коммита
    # оставляла бы canonical с правкой, которую вызывающий получил как 400.
    legacy = _legacy_api_update_task(*legacy_args)
    candidate = store.task_update(
        par,
        **candidate_args,
        expected_head=store.canonical_head,
    )
    return _canonical_result(candidate, legacy, context, _UPDATE_COMPARE_FIELDS)


def _api_update_task_if_current_unlocked(
    identity: TaskIdentity,
    *,
    status: str,
    worker_session_id: str | None = None,
    _canonical_first: bool = False,
    expected_status: str = "",
    require_unreserved: bool = False,
) -> dict:
    binding_inferred = worker_session_id is None and status == "in_progress"
    worker_session_id = _infer_task_worker_session(
        identity, status=status, worker_session_id=worker_session_id,
    )
    if binding_inferred and worker_session_id:
        with _conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = get_task_by_id(conn, identity["id"])
            if not task:
                conn.rollback()
                return {
                    "ok": False,
                    "task_id": identity["id"],
                    "error": "prevalidated task no longer exists",
                }
            claim_error = _task_claim_precondition_error(
                conn,
                task,
                expected_status=expected_status,
                require_unreserved=require_unreserved,
            )
            if claim_error:
                conn.rollback()
                return {"ok": False, "task_id": identity["id"], "error": claim_error}
            _validate_inferred_task_worker(conn, task, worker_session_id)
            conn.commit()
    context = _ia_context()
    if context is None:
        return _legacy_api_update_task_if_current(
            identity,
            status=status,
            worker_session_id=worker_session_id,
            expected_status=expected_status,
            require_unreserved=require_unreserved,
        )
    store = context.store
    assert store is not None
    try:
        detail = store.task_get(
            str(identity["par_number"]),
            project=identity["project_id"],
        )
    except (KeyError, ValueError) as error:
        raise ValueError(
            "canonical task identity unavailable for "
            f"project '{identity['project_id']}' task #{identity['par_number']}: {error}"
        ) from error
    candidate_identity = _merge_canonical_task_identity(identity, detail)
    # У каждого хранилища СВОЙ счётчик ревизий: legacy двигают привязки воркеров
    # (`bind_task_to_session`, requeue, финализация), canonical их не видит. Прогонять
    # legacy-ревизию через canonical CAS — сравнение разных величин: любая задача, которую
    # хоть раз привязывали, отказывается навсегда.
    candidate_identity["sync_revision"] = int(
        detail.get("sync_revision", candidate_identity["sync_revision"])
    )
    if expected_status and detail.get("status") != expected_status:
        return {
            "ok": False,
            "error": (
                f"promotion target must be {expected_status} "
                f"(canonical found {detail.get('status')})"
            ),
            "ia_mode": context.mode,
            "projection_debt": {},
        }
    if expected_status and detail.get("worker_session_id"):
        return {
            "ok": False,
            "error": "canonical promotion target is already owned",
            "ia_mode": context.mode,
            "projection_debt": {},
        }
    if context.mode == "shadow":
        if _canonical_first:
            try:
                candidate = store.task_update_if_current(
                    candidate_identity,
                    status=status,
                    worker_session_id=worker_session_id,
                )
            except Exception:
                raise
            if not candidate.get("ok"):
                return {
                    **candidate,
                    "ia_mode": context.mode,
                    "shadow_match": False,
                    "projection_debt": _candidate_rejection_debt(candidate),
                }
            legacy = _legacy_api_update_task_if_current(
                identity,
                status=status,
                worker_session_id=worker_session_id,
                expected_status=expected_status,
                require_unreserved=require_unreserved,
            )
            return _shadow_result(
                legacy,
                candidate,
                context,
                ("ok", "par", "updated", "new_status", "sync_revision"),
            )
        legacy = _legacy_api_update_task_if_current(
            identity,
            status=status,
            worker_session_id=worker_session_id,
            expected_status=expected_status,
            require_unreserved=require_unreserved,
        )
        if not legacy.get("ok"):
            return legacy
        try:
            candidate = store.task_update_if_current(
                candidate_identity,
                status=status,
                worker_session_id=worker_session_id,
            )
        except Exception as error:
            return _shadow_failure(legacy, context, error)
        if not candidate.get("ok"):
            return {
                **legacy,
                "ia_mode": context.mode,
                "shadow_match": False,
                "projection_debt": _candidate_rejection_debt(candidate),
            }
        return _shadow_result(
            legacy,
            candidate,
            context,
            ("ok", "par", "updated", "new_status", "sync_revision"),
        )
    candidate = store.task_update_if_current(
        candidate_identity,
        status=status,
        worker_session_id=worker_session_id,
    )
    # Отказ canonical обязан остановить ход ДО записи в legacy: иначе legacy уже
    # мутирован, а вызывающий получает исключение и снимает привязку сессии.
    if not candidate.get("ok"):
        return {
            **candidate,
            "ia_mode": context.mode,
            "projection_debt": _candidate_rejection_debt(candidate),
        }
    legacy = _legacy_api_update_task_if_current(
        identity,
        status=status,
        worker_session_id=worker_session_id,
        expected_status=expected_status,
        require_unreserved=require_unreserved,
    )
    # Legacy-CAS — единственный оставшийся детектор устаревшей ревизии, и его отказ обязан
    # дойти до вызывающего отказом: иначе canonical переведён в in_progress с привязкой, а
    # `tm_tasks` остался `new`/NULL — то невозможное состояние, на котором гейт мержа
    # отказывает навсегда («task 'N' is not bound to session»).
    if not legacy.get("ok"):
        return {
            **legacy,
            **_candidate_receipts(candidate, context),
            "projection_debt": {
                "reason": "legacy_update_rejected",
                "message": str(legacy.get("error") or "legacy task update rejected"),
                "canonical_applied": True,
            },
        }
    return _canonical_result(
        candidate,
        legacy,
        context,
        ("ok", "par", "updated", "new_status", "sync_revision"),
    )


def api_update_task_if_current(
    identity: TaskIdentity,
    *,
    status: str,
    worker_session_id: str | None = None,
    _canonical_first: bool = False,
    expected_status: str = "",
    require_unreserved: bool = False,
) -> dict:
    with _TASK_BINDING_LOCK:
        return _api_update_task_if_current_unlocked(
            identity,
            status=status,
            worker_session_id=worker_session_id,
            _canonical_first=_canonical_first,
            expected_status=expected_status,
            require_unreserved=require_unreserved,
        )


def api_list_tasks(project: str = "", status: str = "",
                   assignee: str = "") -> dict:
    context = _ia_context()
    if context is None:
        return _legacy_api_list_tasks(project, status, assignee)
    store = context.store
    assert store is not None
    if context.mode == "canonical":
        candidate = store.task_list(project=project, status=status, assignee=assignee)
        return {
            **candidate,
            **_list_receipts(context),
            "projection_debt": [],
        }
    legacy = _legacy_api_list_tasks(project, status, assignee)
    try:
        candidate = store.task_list(project=project, status=status, assignee=assignee)
    except Exception as error:
        if context.mode == "shadow":
            return _shadow_failure(legacy, context, error)
        raise
    debt = _comparison_debt(legacy, candidate, ("tasks", "count"))
    if context.mode == "shadow":
        return {
            **legacy,
            **_list_receipts(context),
            "shadow_match": not debt,
            "projection_debt": debt,
        }
    return {
        **candidate,
        **_list_receipts(context),
        "projection_debt": debt,
    }


def api_get_task(par: str, project: str = "") -> dict:
    context = _ia_context()
    if context is None:
        return _legacy_api_get_task(par, project)
    store = context.store
    assert store is not None
    if context.mode == "canonical":
        candidate = store.task_get(par, project=project)
        return {
            **candidate,
            "ia_mode": context.mode,
            "canonical_head": candidate.get("canonical_head") or store.canonical_head,
            "projection_head": candidate.get("projection_head") or store.projection_head,
            "projection_debt": list(candidate.get("projection_debt") or []),
        }
    legacy = _legacy_api_get_task(par, project)
    try:
        candidate = store.task_get(par, project=project)
    except Exception as error:
        if context.mode == "shadow":
            return _shadow_failure(legacy, context, error)
        raise
    if context.mode == "shadow":
        return _shadow_result(legacy, candidate, context, _GET_COMPARE_FIELDS)
    return _canonical_result(candidate, legacy, context, _GET_COMPARE_FIELDS)


def link_commits_to_task(task_ref: str, commits: list[dict], project_id: str) -> dict:
    context = _ia_context()
    if context is None:
        return _legacy_link_commits_to_task(task_ref, commits, project_id)
    store = context.store
    assert store is not None
    if context.mode == "shadow":
        legacy = _legacy_link_commits_to_task(task_ref, commits, project_id)
        if not legacy.get("ok"):
            return legacy
        try:
            candidate = store.link_commits_to_task(
                task_ref,
                commits,
                project_id,
                expected_head=store.canonical_head,
            )
        except Exception as error:
            return _shadow_failure(legacy, context, error)
        return _shadow_result(legacy, candidate, context, ("ok", "added"))
    # Legacy впереди по той же причине, что и в обновлении, плюс его отказ обязан
    # остановить связывание: canonical нашёл задачу, а legacy — нет, и тихий `ok=True`
    # из canonical объявил бы успехом коммиты, которых в `tm_tasks` нет.
    legacy = _legacy_link_commits_to_task(task_ref, commits, project_id)
    if not legacy.get("ok"):
        return legacy
    candidate = store.link_commits_to_task(
        task_ref,
        commits,
        project_id,
        expected_head=store.canonical_head,
    )
    return _canonical_result(candidate, legacy, context, ("ok", "added"))

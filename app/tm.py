"""Task Manager — core task data operations.

Takes sqlite3.Connection; callers manage transactions. External integrations are inert.
"""

import json
import logging
import sqlite3
import threading
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
)

VALID_STATUSES = {"backlog", "new", "in_progress", "done", "cancelled"}
_TASK_CREATE_LOCK = threading.RLock()
_TASK_BINDING_LOCK = threading.RLock()


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


def _next_par(conn: sqlite3.Connection, project_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(par_number), 0) + 1 FROM tm_tasks WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    n = row[0]
    # docs/tasks/<n>/ survives task deletion — never reissue a number that still has a dir
    scope_row = conn.execute(
        "SELECT scope FROM tm_projects WHERE id = ?", (project_id,)
    ).fetchone()
    scope = scope_row[0] if scope_row else None
    if scope:
        tasks_root = Path(scope) / "docs" / "tasks"
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
    """Remove a task allocated for a spawn that never published its worker."""
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "DELETE FROM tm_tasks WHERE id=? AND worker_session_id IS NULL AND status='new' "
            "AND NOT EXISTS (SELECT 1 FROM tm_task_reservations WHERE task_id=tm_tasks.id)",
            (task_id,),
        )
        conn.commit()
        return cur.rowcount == 1


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
        and set(mismatches) == {"updated"}
        and result.get("new_status") == status
    )
    if not result.get("ok") or (result.get("shadow_match") is False and not replay_match):
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


def api_update_task_if_current(
    identity: TaskIdentity,
    *,
    status: str,
    worker_session_id: str | None = None,
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


def api_create_task(project_id: str, title: str, price: int = 0,
                    description: str = "", assignee: str = "",
                    status: str = "new", scope: str = "",
                    priority: int = 2, acceptance_command: str = "",
                    acceptance_manifest: list[str] | None = None,
                    acceptance_required: bool = False,
                    acceptance_actor: dict | None = None) -> dict:
    context = _ia_context()
    if context is None:
        return _legacy_api_create_task(
            project_id, title, price, description, assignee, status,
            scope=scope, priority=priority,
            acceptance_command=acceptance_command,
            acceptance_manifest=acceptance_manifest,
            acceptance_required=acceptance_required,
            acceptance_actor=acceptance_actor,
        )
    store = context.store
    assert store is not None

    if context.mode == "shadow":
        with _TASK_CREATE_LOCK:
            # The shadow adapter owns the legacy write; let its internal allocator run
            # under an explicit legacy context without disabling the process-wide adapter
            # for concurrent HTTP requests. Keep the projection in this lock too, so its
            # display number and expected canonical head stay paired with that write.
            with ia_task_store_mode(mode="legacy"):
                legacy = _legacy_api_create_task(
                    project_id, title, price, description, assignee, status,
                    scope=scope, priority=priority,
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
                return _shadow_failure(legacy, context, error)
            return _shadow_result(legacy, candidate, context, _CREATE_COMPARE_FIELDS)

    with _TASK_CREATE_LOCK:
        with _conn() as conn:
            project = resolve_project_selector(conn, project_id) if project_id else None
            if project is None and scope:
                project = _project_for_session_scope(conn, scope)
            if not project or not str(project.get("scope") or "").strip():
                raise ValueError(f"project '{project_id or scope}' is not registered")
            resolved_project_id = project["id"]
            legacy_next = _next_par(conn, resolved_project_id)
        canonical_next = int(
            store.task_list(project=resolved_project_id)["next_display_number"]
        )
        if canonical_next != legacy_next:
            raise IdentityConflictError(
                f"task display counter mismatch in {resolved_project_id}: "
                f"canonical={canonical_next}, legacy={legacy_next}"
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
    candidate["id"] = legacy["id"]
    return _canonical_result(candidate, legacy, context, _CREATE_COMPARE_FIELDS)


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
    candidate = store.task_update(
        par,
        **candidate_args,
        expected_head=store.canonical_head,
    )
    legacy = _legacy_api_update_task(*legacy_args)
    return _canonical_result(candidate, legacy, context, _UPDATE_COMPARE_FIELDS)


def _api_update_task_if_current_unlocked(
    identity: TaskIdentity,
    *,
    status: str,
    worker_session_id: str | None = None,
    _canonical_first: bool = False,
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
            _validate_inferred_task_worker(conn, task, worker_session_id)
            conn.commit()
    context = _ia_context()
    if context is None:
        return _legacy_api_update_task_if_current(
            identity,
            status=status,
            worker_session_id=worker_session_id,
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
    if _canonical_first:
        candidate_identity["sync_revision"] = int(
            detail.get("sync_revision", candidate_identity["sync_revision"])
        )
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
                    "projection_debt": {
                        "reason": "candidate_update_rejected",
                        "message": str(candidate.get("error") or "canonical task update rejected"),
                    },
                }
            legacy = _legacy_api_update_task_if_current(
                identity,
                status=status,
                worker_session_id=worker_session_id,
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
    legacy = _legacy_api_update_task_if_current(
        identity,
        status=status,
        worker_session_id=worker_session_id,
    )
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
) -> dict:
    with _TASK_BINDING_LOCK:
        return _api_update_task_if_current_unlocked(
            identity,
            status=status,
            worker_session_id=worker_session_id,
            _canonical_first=_canonical_first,
        )


def api_list_tasks(project: str = "", status: str = "",
                   assignee: str = "") -> dict:
    context = _ia_context()
    if context is None:
        return _legacy_api_list_tasks(project, status, assignee)
    store = context.store
    assert store is not None
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
    candidate = store.link_commits_to_task(
        task_ref,
        commits,
        project_id,
        expected_head=store.canonical_head,
    )
    legacy = _legacy_link_commits_to_task(task_ref, commits, project_id)
    return _canonical_result(candidate, legacy, context, ("ok", "added"))

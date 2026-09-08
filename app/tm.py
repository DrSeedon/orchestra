"""Task Manager — core task data operations.

Git owns portable task state; SQLite holds its projection and local worker bindings.
"""

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import TypedDict

from app.acceptance import PYTEST_CONFIG_NAMES
from app.db import _conn, task_run_receipt_finish, task_run_receipt_open
from app.task_runtime import active_runtime
from app.task_refs import project_key

VALID_STATUSES = frozenset({'backlog', 'new', 'in_progress', 'done', 'cancelled'})

from app.task_refs import task_ref as public_task_ref

_TASK_CREATE_REQUEST_KEY = re.compile(r"[A-Za-z0-9._:-]{16,128}")



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
    ref_prefix: str
    stable_id: str
    task_snapshot_ref: str


class ScopedTaskResolution(TypedDict):
    project_id: str
    tasks: list[TaskIdentity]
    canonical_refs: list[str]
    unresolved_refs: list[str]


def task_dto(task: dict, *, auto_created: bool = False) -> dict:
    """Return the bounded task state shared by spawn and assignment responses."""
    return {
        "id": task["id"], "project_id": task["project_id"],
        "par_number": task["par_number"], "title": task["title"],
        **({"ref": public_task_ref(task), "ref_prefix": task["ref_prefix"]} if task.get("ref_prefix") else {}),
        "status": task["status"], "worker_session_id": task.get("worker_session_id"),
        "auto_created": auto_created,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()




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
        if not any(path in PYTEST_CONFIG_NAMES for path in manifest):
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
    m = re.match(r"^([A-Z]{1,5})-(\d+)$", ref)
    if m:
        return m.group(1), int(m.group(2))
    m = re.match(r"^(\d+)$", ref)
    if m:
        return "", int(m.group(1))
    raise ValueError(f"Cannot parse task ref: {ref}")


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
        "INSERT INTO tm_projects (id, name, prefix, scope, created_at, canonical_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (canonical_id, name or project_id, pfx, scope, now, project_key(canonical_id)),
    )
    return {"id": canonical_id, "name": name or project_id, "prefix": pfx, "scope": scope,
            "created_at": now, "canonical_id": project_key(canonical_id)}


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

def create_task_for_scope(scope: str, title: str) -> dict:
    """Create through the Git owner using the scope's registered project."""
    with _conn() as conn:
        project = get_project_by_scope(conn, scope.rstrip("/"))
        if not project:
            raise ValueError(f"scope '{scope}' has no task project")
        project_id = project["id"]
    created = api_create_task(project_id, title, status="new")
    return created


def discard_unbound_task(task_id: int) -> bool:
    """Cancel an unpublished allocation without reusing its task number."""
    with _conn() as conn:
        task = conn.execute(
            "SELECT * FROM tm_tasks "
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
        sync_revision=task["sync_revision"], ref_prefix=task["ref_prefix"],
        stable_id=task["stable_id"], task_snapshot_ref=_task_run_refs(dict(task))[1],
    )
    return bool(api_update_task_if_current(identity, status="cancelled").get("ok"))


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
                    project_id: str = "", *, ref_prefix: str | None = None) -> dict | None:
    if project_id:
        rows = conn.execute(
            "SELECT * FROM tm_tasks WHERE par_number = ? AND project_id = ? "
            "AND (? IS NULL OR ref_prefix = ?) LIMIT 2",
            (par_number, project_id, ref_prefix, ref_prefix),
        ).fetchall()
        if len(rows) > 1:
            raise ValueError(f"Ambiguous task #{par_number}; use its full reference")
        row = rows[0] if rows else None
    else:
        rows = conn.execute(
            "SELECT * FROM tm_tasks WHERE par_number = ? AND (? IS NULL OR ref_prefix = ?) ORDER BY id ASC LIMIT 2",
            (par_number, ref_prefix, ref_prefix),
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
    task = get_task_by_par(conn, num, project['id'], ref_prefix='V' if prefix == 'V' else '')
    if not task:
        return None
    task_prefix = str(task.get('ref_prefix') or '')
    expected_prefix = (project.get('prefix') or '').upper()
    if prefix == 'V':
        if task_prefix != 'V':
            return None
    elif task_prefix:
        return None
    elif prefix and prefix not in {'TASK', expected_prefix}:
        raise ValueError(f"task '{ref}' belongs to project prefix {prefix}, not authoritative project {project['id']}")
    return task


def resolve_scoped_task_identity(scope: str, ref: str) -> TaskIdentity:
    """Resolve one task through the session's authoritative project scope."""
    with active_runtime().operation():
        normalized_scope = scope.rstrip("/")
        if not normalized_scope:
            raise ValueError("session scope is required for task assignment")
        with _conn() as conn:
            project = get_project_by_scope(conn, normalized_scope)
            if not project:
                raise ValueError(f"scope '{normalized_scope}' has no task project")
            task = resolve_task_ref(conn, ref, project['id'])
            if not task:
                raise ValueError(
                    f"task '{ref}' not found in session project {project['id']}"
                )
            return TaskIdentity(
                id=task["id"],
                project_id=task["project_id"],
                par_number=task["par_number"],
                sync_revision=task["sync_revision"],
                ref_prefix=task["ref_prefix"], stable_id=task["stable_id"],
                task_snapshot_ref=_task_run_refs(task)[1],
            )


def resolve_scoped_task_identities(
    scope: str,
    refs: list[str],
    *,
    bound_session_id: str = "",
    skip_unknown: bool = False,
) -> ScopedTaskResolution:
    """Resolve every task ref through one scope-owned project snapshot.

    `skip_unknown=True` — для ссылок, ВЫЧИТАННЫХ из сообщений коммитов: репозиторий может
    нести собственную нумерацию (переехал с другой площадки), и незнакомый `#N` там не
    ошибка вызывающего, а факт чужой истории. Такой ref не привязывается, но ОСТАЁТСЯ в
    `canonical_refs`: тема squash-коммита строится из тех же сообщений и сверяется с этим
    списком, поэтому выбросить ref значило бы уронить проверку темы. Непривязанные
    возвращаются в `unresolved_refs` — вызывающий обязан показать их предупреждением.
    Замер 06.09 (comfy-image-pipeline): коммит `#110: …` в проекте с нумерацией от #3 валил
    ВСЮ операцию до git-шага с `NO_COMMITS_MERGED`, блокируя работу трёх воркеров.
    """
    with active_runtime().operation():
        normalized_scope = scope.rstrip("/")
        if not normalized_scope:
            raise ValueError("session scope is required for task assignment")
        with _conn() as conn:
            project = get_project_by_scope(conn, normalized_scope)
            if not project:
                raise ValueError(f"scope '{normalized_scope}' has no task project")
            tasks: list[TaskIdentity] = []
            canonical_refs: list[str] = []
            unresolved: list[str] = []
            seen_task_ids: set[int] = set()
            for index, ref in enumerate(refs):
                task = resolve_task_ref(conn, ref, project["id"])
                if not task and skip_unknown:
                    unresolved.append(str(ref))
                    canonical_refs.append(str(ref).lstrip("#"))
                    continue
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
                    ref_prefix=task["ref_prefix"], stable_id=task["stable_id"],
                task_snapshot_ref=_task_run_refs(task)[1],
                ))
                canonical_refs.append(public_task_ref(task))
            return ScopedTaskResolution(
                project_id=project["id"],
                tasks=tasks,
                canonical_refs=canonical_refs,
                unresolved_refs=unresolved,
            )


def _bind_task_to_session_unlocked(scope: str, session_id: str, task_ref: str) -> dict:
    """Atomically bind one scoped task to one durable session."""
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            session = conn.execute(
                "SELECT id, name, scope, task_id, template_hash FROM sessions "
                "WHERE id = ? AND status != 'archived'",
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
            if session_task_id and session_task_id != public_task_ref(task):
                raise ValueError("session is already bound to another task")
            if task_worker_session_id and task_worker_session_id != session_id:
                if session_task_id == public_task_ref(task):
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
                    (public_task_ref(task), session_id),
                )
                if updated.rowcount != 1:
                    raise ValueError("session binding compare-and-swap failed")
            active_runtime().publish(conn, task['id'])
            task = get_task_by_id(conn, task['id'])
            _open_task_run_for_task(conn, task, session_id)
            bound = get_task_by_id(conn, task["id"])
            conn.commit()
            return task_dto(bound)
        except Exception:
            conn.rollback()
            raise


def bind_task_to_session(scope: str, session_id: str, task_ref: str) -> dict:
    with active_runtime().operation():
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


def _task_run_refs(task: dict) -> tuple[str, str]:
    stable_id = str(task.get('stable_id') or '')
    head = str(task.get('task_commit') or '')
    return stable_id, f'git-task:{stable_id}@{head}' if stable_id and head else ''


def _open_task_run_for_task(
    conn: sqlite3.Connection,
    task: dict,
    session_id: str,
) -> dict:
    existing = conn.execute(
        "SELECT * FROM review_receipts WHERE subject_kind='task_run' "
        "AND session_id=? AND task_id=? AND status='requested'",
        (session_id, public_task_ref(task)),
    ).fetchone()
    if existing is not None:
        return dict(existing)
    session = conn.execute(
        "SELECT id,name,scope,template_hash FROM sessions WHERE id=?",
        (session_id,),
    ).fetchone()
    if session is None:
        raise ValueError(f"session '{session_id}' disappeared before task-run receipt")
    stable_id, snapshot_ref = _task_run_refs(task)
    return task_run_receipt_open(
        session_id=session_id,
        worker_name=session["name"],
        scope=session["scope"],
        task_id=public_task_ref(task),
        task_stable_id=stable_id,
        task_snapshot_ref=snapshot_ref,
        prompt_template_start=str(session["template_hash"] or ""),
        task_source=("canonical" if stable_id and snapshot_ref else "legacy"),
        connection=conn,
    )


def _finish_task_run_for_task(
    conn: sqlite3.Connection,
    task: dict,
    session_id: str,
    *,
    status: str,
    failure_code: str = "",
    terminal_operation_id: str = "",
) -> dict | None:
    exists = conn.execute(
        "SELECT 1 FROM review_receipts WHERE subject_kind='task_run' "
        "AND session_id=? AND task_id=? AND status='requested'",
        (session_id, public_task_ref(task)),
    ).fetchone()
    if exists is None:
        return None
    session = conn.execute(
        "SELECT template_hash FROM sessions WHERE id=?", (session_id,),
    ).fetchone()
    return task_run_receipt_finish(
        session_id=session_id,
        task_id=public_task_ref(task),
        status=status,
        prompt_template_end=str(session["template_hash"] or "") if session else "",
        terminal_operation_id=terminal_operation_id,
        failure_code=failure_code,
        connection=conn,
    )


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
    with active_runtime().operation():
        if outcome not in {"continue", "complete"}:
            raise ValueError(f"unknown task outcome '{outcome}'")
        reservation_id = operation_id or f"session:{session_id}"
        with _conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if outcome == "complete":
                    others = _live_bindings(conn, scope, public_task_ref(task), session_id)
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
            terminal_session = {"task_id": public_task_ref(next_task), "needs_switch": False}
        elif outcome == "continue":
            terminal_session = {"task_id": public_task_ref(task), "needs_switch": False}
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
    with active_runtime().operation():
        with _conn() as conn:
            task = get_task_by_id(conn, task_id)
        if not task:
            raise ValueError(f"task {task_id} disappeared before finalization")
        return {
            "id": task["id"],
            "project_id": task["project_id"],
            "par_number": task["par_number"],
            "sync_revision": task["sync_revision"], "ref_prefix": task["ref_prefix"],
            "stable_id": task["stable_id"], "task_snapshot_ref": _task_run_refs(task)[1],
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
        )
    except Exception as error:
        detail = f"{type(error).__name__}: {error}"
        payload["task_status"] = {"ok": False, "error": detail}
        raise RuntimeError(f"task finalization failed: {detail}") from error
    if not result.get('ok'):
        detail = str(result.get('error') or 'task update failed')
        payload['task_status'] = {'ok': False, 'error': detail, 'result': result}
        raise RuntimeError(f'task finalization failed: {detail}')
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
        with _conn() as conn:
            task = get_task_by_id(conn, task_db_id)
            if task:
                _finish_task_run_for_task(
                    conn,
                    task,
                    payload["session_id"],
                    status="completed",
                    terminal_operation_id=payload.get("operation_id", ""),
                )
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
        "SELECT t.*, p.scope FROM tm_tasks t "
        "JOIN tm_projects p ON p.id = t.project_id WHERE t.worker_session_id = ?",
        (session_id,),
    ).fetchall()
    now = _now()
    session = conn.execute(
        "SELECT status FROM sessions WHERE id=?", (session_id,),
    ).fetchone()
    release_code = (
        "session_archived"
        if session and session["status"] == "archived"
        else "binding_released"
    )
    for row in rows:
        heir = conn.execute(
            "SELECT id FROM sessions WHERE task_id = ? AND RTRIM(scope, '/') = RTRIM(?, '/') "
            "AND status != 'archived' AND id != ? ORDER BY created_at LIMIT 1",
            (public_task_ref(row), row["scope"], session_id),
        ).fetchone()
        if heir:
            _finish_task_run_for_task(
                conn,
                dict(row),
                session_id,
                status="interrupted",
                failure_code="binding_released",
            )
            conn.execute(
                "UPDATE tm_tasks SET worker_session_id=?, sync_revision=sync_revision+1, "
                "updated_at=? WHERE id=?",
                (heir["id"], now, row["id"]),
            )
            inherited = get_task_by_id(conn, row["id"])
            if inherited:
                _open_task_run_for_task(conn, inherited, heir["id"])
            continue
        status = "new" if row["status"] == "in_progress" else row["status"]
        if row["status"] == "in_progress":
            _finish_task_run_for_task(
                conn,
                dict(row),
                session_id,
                status="interrupted",
                failure_code=release_code,
            )
        conn.execute(
            "UPDATE tm_tasks SET worker_session_id=NULL, status=?, "
            "sync_revision=sync_revision+1, updated_at=? WHERE id=?",
            (status, now, row["id"]),
        )
        active_runtime().publish(conn, row['id'])


def format_task_ref(conn: sqlite3.Connection, task: dict) -> str:
    """Format the persisted task namespace and number."""
    return public_task_ref(task)


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
    """Publish one commit group and update its local task projection."""
    if not project_id:
        raise ValueError("project authority is required for commit linking")
    with active_runtime().operation():
        with _conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = _link_commits_to_task(conn, task_ref, commits, project_id)
                if result.get('added'):
                    active_runtime().publish(conn, result['task_id'])
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
                    description: str = '', assignee: str = '', status: str = 'new',
                    scope: str = '', priority: int = 2, acceptance_command: str = '',
                    acceptance_manifest: list[str] | None = None,
                    acceptance_required: bool = False, acceptance_actor: dict | None = None,
                    request_key: str = '') -> dict:
    from app.acceptance import parse_acceptance_command
    request_key = normalize_task_create_request_key(request_key)
    if status not in VALID_STATUSES:
        raise ValueError(f'Invalid status: {status}')
    command = (acceptance_command or '').strip()
    parse_acceptance_command(command)
    manifest = _normalize_acceptance_manifest(acceptance_manifest)
    acceptance = {'command': command, 'manifest_paths': manifest, 'required': acceptance_required}
    if acceptance_required or manifest:
        if not command:
            raise ValueError('required acceptance oracle has no command')
        acceptance.update(json.loads(_acceptance_oracle_json(
            required=acceptance_required, manifest=manifest, revision=1,
            actor=_normalize_acceptance_actor(acceptance_actor))))
    runtime = active_runtime()
    with runtime.operation():
        resolved = _resolve_task_create_project(project_id, scope)
        with _conn() as conn:
            project = resolve_project_id(conn, resolved)
        task = runtime.create(project, title, request_key=request_key, description=description,
            status=status, assignee=assignee, priority=priority, price_rub=price, acceptance=acceptance)
        return {'par': public_task_ref(task), 'par_number': task['par_number'],
                'ref_prefix': task['ref_prefix'], 'id': task['id'], 'stable_id': task['stable_id'],
                'title': task['title'], 'project': task['project_id'], 'price_rub': task['price_rub'],
                'status': task['status'], 'request_key': request_key}


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
    with active_runtime().operation():
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
                if status == "cancelled" and task.get("worker_session_id"):
                    _finish_task_run_for_task(
                        conn,
                        task,
                        str(task["worker_session_id"]),
                        status="interrupted",
                        failure_code="task_cancelled",
                    )

                active_runtime().publish(conn, task_id)
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
            (public_task_ref(task), project["scope"]),
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
        (public_task_ref(task), project["scope"]),
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
    with active_runtime().operation(), _conn() as conn:
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


def validate_task_binding_repair(
    scope: str, session_id: str, task_ref: str,
) -> dict:
    """Validate the existing live binding without changing either owner."""
    with active_runtime().operation(), _conn() as conn:
        session = conn.execute(
            "SELECT task_id FROM sessions WHERE id=? AND status!='archived'",
            (session_id,),
        ).fetchone()
        if not session or str(session["task_id"] or "") != str(task_ref):
            raise ValueError(
                f"session '{session_id}' is not bound to task #{task_ref}"
            )
        project = get_project_by_scope(conn, scope.rstrip("/"))
        task = resolve_task_ref(conn, task_ref, project["id"]) if project else None
        if not task:
            raise ValueError(f"task '{task_ref}' is not available in scope '{scope}'")
        if str(task.get("worker_session_id") or "") != session_id:
            raise ValueError(
                f"task #{task['par_number']} is not bound to session '{session_id}'"
            )
        if task["status"] != "in_progress":
            raise ValueError(
                f"task #{task['par_number']} is {task['status']}, not in_progress"
            )
        return task_dto(task)


def api_update_task_if_current(
    identity: TaskIdentity,
    *,
    status: str,
    worker_session_id: str | None = None,
    expected_status: str = "",
    require_unreserved: bool = False,
) -> dict:
    """Update a prevalidated task only while its immutable identity/version matches."""
    with active_runtime().operation():
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
                    or task['ref_prefix'] != identity.get('ref_prefix', '')
                    or (identity.get('stable_id') and task['stable_id'] != identity['stable_id'])
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
                active_runtime().publish(conn, task_id)
                updated = get_task_by_id(conn, task_id)
                if status == "in_progress" and worker_session_id:
                    _open_task_run_for_task(conn, updated, worker_session_id)
                elif status == "cancelled" and task.get("worker_session_id"):
                    _finish_task_run_for_task(
                        conn,
                        task,
                        str(task["worker_session_id"]),
                        status="interrupted",
                        failure_code="task_cancelled",
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        return {
            "ok": True,
            "task_id": task_id,
            "par": public_task_ref(identity),
            "updated": result["changed"],
            "new_status": updated["status"],
            "sync_revision": updated["sync_revision"],
        }


def api_list_tasks(project: str = "", status: str = "",
                   assignee: str = "") -> dict:
    with active_runtime().operation():
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
                    "par": public_task_ref(t),
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
    with active_runtime().operation():
        with _conn() as conn:
            task = resolve_task_ref(conn, par, project)
            if not task:
                raise ValueError(f"{par} not found")

            task_ref = format_task_ref(conn, task)

        commits = json.loads(task["git_commits"]) if task["git_commits"] else []

        return {
            "id": task['id'], "stable_id": task['stable_id'],
            "ref_prefix": task['ref_prefix'], "task_revision": task['task_revision'],
            "task_snapshot_ref": _task_run_refs(task)[1],
            "acceptance_command": task['acceptance_command'],
            "acceptance": parse_acceptance_oracle(task['acceptance_oracle_json']),
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
            "sync_revision": task["sync_revision"], "ref_prefix": task["ref_prefix"],
            "stable_id": task["stable_id"], "task_snapshot_ref": _task_run_refs(task)[1],
        }


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




def api_task_create_status(request_key: str, *, project_id: str = '', scope: str = '') -> dict:
    request_key = normalize_task_create_request_key(request_key)
    runtime = active_runtime()
    with runtime.operation():
        project_id = _resolve_task_create_project(project_id, scope)
        with _conn() as connection:
            project = resolve_project_id(connection, project_id)
        records = [r for r in runtime.store.list(project['canonical_id']) if r['creation_key'] == request_key]
        if len(records) != 1:
            raise ValueError('task-create request is missing or ambiguous')
        record = records[0]
        with _conn() as connection:
            row = connection.execute('SELECT id FROM tm_tasks WHERE stable_id=?', (record['id'],)).fetchone()
        return {'project': project_id, 'request_key': request_key, 'state': 'COMMITTED',
                'task_id': row['id'], 'par_number': record['number'],
                'result': {'id': row['id'], 'par': record['ref'], 'stable_id': record['id']}, 'error': None}

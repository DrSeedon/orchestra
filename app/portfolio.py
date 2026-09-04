"""Authoritative human projects layered over the technical task namespace."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from app import db, tm


MAX_STAGE_LABELS = 7
MAX_STAGE_LABEL_LENGTH = 64


class PortfolioError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _timestamp(value: str | datetime | None = None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, datetime):
        current = value
    else:
        try:
            current = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PortfolioError(422, "invalid ISO timestamp") from exc
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    if value is not None and current > datetime.now(timezone.utc) + timedelta(seconds=1):
        raise PortfolioError(422, "future timestamps are not accepted")
    return current.isoformat()


def _session(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM sessions WHERE id=? AND status!='archived'", (session_id,)
    ).fetchone()
    if row is None:
        raise PortfolioError(403, "session is not active")
    return row


def _root_owner_session(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    row = _session(conn, session_id)
    if row["role"] != "orchestrator" or str(row["parent_id"] or "").strip():
        raise PortfolioError(422, "project owner must be a root orchestrator")
    return row


def _project(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM portfolio_projects WHERE id=? AND archived_at IS NULL",
        (project_id,),
    ).fetchone()
    if row is None:
        raise PortfolioError(404, f"portfolio project '{project_id}' not found")
    return row


def _stage_order(project: sqlite3.Row | dict) -> list[str]:
    try:
        raw = json.loads(str(project["stage_order_json"] or "[]"))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raw = []
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw if isinstance(value, str)]


def _normalize_stage_label(value: str) -> str:
    label = " ".join(str(value).split())
    if not label:
        raise PortfolioError(422, "stage label is required")
    if len(label) > MAX_STAGE_LABEL_LENGTH:
        raise PortfolioError(
            422, f"stage label must not exceed {MAX_STAGE_LABEL_LENGTH} characters"
        )
    return label


def _task_namespace_for_actor(
    conn: sqlite3.Connection, actor: sqlite3.Row
) -> str:
    rows = conn.execute(
        """SELECT id FROM tm_projects
           WHERE RTRIM(scope,'/')=RTRIM(?,'/') ORDER BY id""",
        (actor["scope"],),
    ).fetchall()
    if not rows:
        raise PortfolioError(403, "owner scope has no technical task project")
    if len(rows) != 1:
        raise PortfolioError(409, "owner scope maps to multiple technical task projects")
    return str(rows[0]["id"])


def _owner(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = conn.execute(
        """SELECT s.* FROM portfolio_members m
           JOIN sessions s ON s.id=m.session_id
           WHERE m.project_id=? AND m.role='owner' AND m.revoked_at IS NULL
             AND s.status!='archived'""",
        (project_id,),
    ).fetchone()
    if row is None or row["role"] != "orchestrator" or str(row["parent_id"] or "").strip():
        raise PortfolioError(409, "project has no valid owner")
    return row


def _ancestry_reaches(
    conn: sqlite3.Connection, session: sqlite3.Row, owner_id: str
) -> bool:
    if session["role"] != "sub-orchestrator":
        return False
    current = str(session["parent_id"] or "").strip()
    visited = {str(session["id"])}
    while current and current not in visited:
        if current == owner_id:
            return True
        visited.add(current)
        parent = conn.execute(
            "SELECT id,parent_id,status FROM sessions WHERE id=?", (current,)
        ).fetchone()
        if parent is None or parent["status"] == "archived":
            return False
        current = str(parent["parent_id"] or "").strip()
    return False


def authorize(
    conn: sqlite3.Connection,
    project_id: str,
    session_id: str,
    *,
    owner_only: bool = False,
) -> tuple[sqlite3.Row, sqlite3.Row, str]:
    project = _project(conn, project_id)
    actor = _session(conn, session_id)
    member = conn.execute(
        """SELECT role FROM portfolio_members
           WHERE project_id=? AND session_id=? AND revoked_at IS NULL""",
        (project_id, session_id),
    ).fetchone()
    if member is None:
        raise PortfolioError(403, "session is not a project member")
    role = str(member["role"])
    owner = _owner(conn, project_id)
    if role == "owner":
        if actor["id"] != owner["id"]:
            raise PortfolioError(403, "owner membership is stale")
    elif not _ancestry_reaches(conn, actor, str(owner["id"])):
        raise PortfolioError(403, "contributor is outside the owner ancestry")
    if owner_only and role != "owner":
        raise PortfolioError(403, "only the project owner may change this policy")
    return project, actor, role


def _goal_row(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT * FROM portfolio_goals WHERE project_id=?
           ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,
                    created_at DESC LIMIT 1""",
        (project_id,),
    ).fetchone()


def _member_payload(row: sqlite3.Row) -> dict:
    return {"session_id": row["id"], "name": row["name"]}


def _goal_payload(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    result["watchdog_enabled"] = bool(result["watchdog_enabled"])
    return result


def _task_payloads(conn: sqlite3.Connection, project_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT t.*, t.project_id AS task_namespace_id,
                  t.par_number AS task_display_number,
                  l.task_stable_id, l.stage_label
           FROM portfolio_projects p
           JOIN tm_tasks t ON (
               t.project_id=p.task_namespace_id OR EXISTS (
                   SELECT 1 FROM portfolio_task_links x
                   WHERE x.project_id=p.id AND x.task_row_id=t.id
                     AND x.removed_at IS NULL
               )
           )
           LEFT JOIN portfolio_task_links l
             ON l.project_id=p.id AND l.task_row_id=t.id AND l.removed_at IS NULL
           WHERE p.id=? AND p.archived_at IS NULL
           ORDER BY t.created_at, t.id""",
        (project_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _wait_payloads(conn: sqlite3.Connection, project_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT w.*,d.state AS response_delivery_state,
                  d.error_json AS response_delivery_error_json
           FROM portfolio_waits w
           LEFT JOIN message_deliveries d ON d.delivery_id=w.response_delivery_id
           WHERE w.project_id=? ORDER BY w.opened_at,w.id""",
        (project_id,),
    ).fetchall()
    result = []
    for row in rows:
        payload = dict(row)
        raw_error = payload.pop("response_delivery_error_json", None)
        try:
            payload["response_delivery_error"] = (
                json.loads(raw_error) if raw_error else None
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            payload["response_delivery_error"] = {"message": str(raw_error)}
        result.append(payload)
    return result


def _project_payload(conn: sqlite3.Connection, project_id: str) -> dict:
    project = _project(conn, project_id)
    owner = _owner(conn, project_id)
    contributors = []
    for row in conn.execute(
        """SELECT s.* FROM portfolio_members m JOIN sessions s ON s.id=m.session_id
           WHERE m.project_id=? AND m.role='contributor' AND m.revoked_at IS NULL
           ORDER BY m.created_at""",
        (project_id,),
    ).fetchall():
        if row["status"] != "archived" and _ancestry_reaches(conn, row, str(owner["id"])):
            contributors.append(_member_payload(row))
    result = dict(project)
    result["stage_order"] = _stage_order(project)
    result.pop("stage_order_json", None)
    result.update(
        {
            "scope": None,
            "owner_session_id": owner["id"],
            "owner": _member_payload(owner),
            "contributors": contributors,
            "goal": _goal_payload(_goal_row(conn, project_id)),
            "tasks": _task_payloads(conn, project_id),
            "waits": _wait_payloads(conn, project_id),
        }
    )
    return result


def create_project(session_id: str, project_id: str, name: str) -> dict:
    project_id = project_id.strip().casefold()
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", project_id) is None:
        raise PortfolioError(422, "project id must be a lowercase slug")
    name = name.strip()
    if not name:
        raise PortfolioError(422, "project name is required")
    now = _timestamp()
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _root_owner_session(conn, session_id)
        try:
            conn.execute(
                """INSERT INTO portfolio_projects(id,name,created_at,updated_at)
                   VALUES(?,?,?,?)""",
                (project_id, name, now, now),
            )
            conn.execute(
                """INSERT INTO portfolio_members(project_id,session_id,role,created_at)
                   VALUES(?,?,'owner',?)""",
                (project_id, session_id, now),
            )
        except sqlite3.IntegrityError as exc:
            raise PortfolioError(409, f"portfolio project '{project_id}' already exists") from exc
        return _project_payload(conn, project_id)


def list_projects(session_id: str = "", *, agent_filter: str = "") -> dict:
    """`session_id` — права актора, `agent_filter` — срез дашборда по выбранному агенту.

    Фильтр действует ТОЛЬКО у оператора без агентской сессии: у агента права уже
    сужены до его членства, и расширять их параметром запроса нельзя (#472).
    """
    with db._conn() as conn:
        if session_id:
            _session(conn, session_id)
            ids = [
                row["project_id"]
                for row in conn.execute(
                    """SELECT project_id FROM portfolio_members
                       WHERE session_id=? AND revoked_at IS NULL""",
                    (session_id,),
                ).fetchall()
            ]
        elif agent_filter:
            ids = [
                row["id"]
                for row in conn.execute(
                    """SELECT p.id FROM portfolio_projects p
                       JOIN portfolio_members m ON m.project_id=p.id
                       WHERE m.session_id=? AND m.revoked_at IS NULL
                         AND p.archived_at IS NULL
                       ORDER BY p.created_at""",
                    (agent_filter,),
                ).fetchall()
            ]
        else:
            ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM portfolio_projects WHERE archived_at IS NULL ORDER BY created_at"
                ).fetchall()
            ]
        projects = []
        for project_id in ids:
            try:
                if session_id:
                    authorize(conn, project_id, session_id)
                projects.append(_project_payload(conn, project_id))
            except PortfolioError as exc:
                if exc.status_code not in {403, 409}:
                    raise
        return {"projects": projects}


def get_project(session_id: str, project_id: str) -> dict:
    with db._conn() as conn:
        authorize(conn, project_id, session_id)
        return _project_payload(conn, project_id)


def add_member(session_id: str, project_id: str, target_session_id: str, role: str) -> dict:
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        authorize(conn, project_id, session_id, owner_only=True)
        target = _session(conn, target_session_id)
        if role == "owner":
            if target["role"] == "sub-orchestrator":
                raise PortfolioError(422, "a sub-orchestrator cannot own a project")
            raise PortfolioError(409, "project already has one owner")
        if role != "contributor" or target["role"] != "sub-orchestrator":
            raise PortfolioError(422, "only a sub-orchestrator may be a contributor")
        owner = _owner(conn, project_id)
        if not _ancestry_reaches(conn, target, str(owner["id"])):
            raise PortfolioError(422, "contributor must descend from the project owner")
        now = _timestamp()
        try:
            conn.execute(
                """INSERT INTO portfolio_members(project_id,session_id,role,created_at)
                   VALUES(?,?,'contributor',?)""",
                (project_id, target_session_id, now),
            )
        except sqlite3.IntegrityError as exc:
            raise PortfolioError(409, "session is already an active member") from exc
        return {"project_id": project_id, "session_id": target_session_id, "role": role}


def set_task_source(session_id: str, project_id: str, task_project: str) -> dict:
    task_project = task_project.strip()
    if not task_project:
        raise PortfolioError(422, "task_project is required")
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        project, actor, _role = authorize(conn, project_id, session_id, owner_only=True)
        mapped = _task_namespace_for_actor(conn, actor)
        if mapped != task_project:
            raise PortfolioError(403, "task source must match the owner's technical scope")
        current = str(project["task_namespace_id"] or "")
        if current == task_project:
            return _project_payload(conn, project_id)
        if current:
            raise PortfolioError(409, "project task source is already bound")
        try:
            conn.execute(
                """UPDATE portfolio_projects
                   SET task_namespace_id=?,revision=revision+1,updated_at=?
                   WHERE id=? AND task_namespace_id IS NULL""",
                (task_project, _timestamp(), project_id),
            )
        except sqlite3.IntegrityError as exc:
            raise PortfolioError(409, "technical task source is already in use") from exc
        return _project_payload(conn, project_id)


def set_stage_order(
    session_id: str,
    project_id: str,
    stages: list[str],
    renames: dict[str, str] | None = None,
) -> dict:
    if len(stages) > MAX_STAGE_LABELS:
        raise PortfolioError(422, f"a project may have at most {MAX_STAGE_LABELS} stages")
    normalized = [_normalize_stage_label(value) for value in stages]
    by_key = {label.casefold(): label for label in normalized}
    if len(by_key) != len(normalized):
        raise PortfolioError(422, "stage labels must be unique ignoring case and whitespace")

    rename_map: dict[str, str] = {}
    for old, new in (renames or {}).items():
        old_label = _normalize_stage_label(old)
        new_label = _normalize_stage_label(new)
        old_key = old_label.casefold()
        if old_key in rename_map:
            raise PortfolioError(422, "duplicate stage rename source")
        canonical_new = by_key.get(new_label.casefold())
        if canonical_new is None:
            raise PortfolioError(422, "renamed stage must appear in the final order")
        rename_map[old_key] = canonical_new

    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        project, _actor_row, _role = authorize(
            conn, project_id, session_id, owner_only=True
        )
        current = _stage_order(project)
        current_keys = {label.casefold() for label in current}
        if not set(rename_map).issubset(current_keys):
            raise PortfolioError(422, "rename source is not in the current stage order")

        links = conn.execute(
            """SELECT rowid AS link_rowid,stage_label FROM portfolio_task_links
               WHERE project_id=? AND removed_at IS NULL AND stage_label IS NOT NULL""",
            (project_id,),
        ).fetchall()
        updates: list[tuple[str, int]] = []
        for link in links:
            key = str(link["stage_label"]).casefold()
            target = rename_map.get(key) or by_key.get(key)
            if target is None:
                raise PortfolioError(422, "stage order cannot omit a label still used by tasks")
            if target != link["stage_label"]:
                updates.append((target, int(link["link_rowid"])))

        encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        if current == normalized and not updates:
            return _project_payload(conn, project_id)
        for label, rowid in updates:
            conn.execute(
                "UPDATE portfolio_task_links SET stage_label=? WHERE rowid=?",
                (label, rowid),
            )
        conn.execute(
            """UPDATE portfolio_projects
               SET stage_order_json=?,revision=revision+1,updated_at=? WHERE id=?""",
            (encoded, _timestamp(), project_id),
        )
        return _project_payload(conn, project_id)


def _resolve_project_task(
    conn: sqlite3.Connection,
    project: sqlite3.Row,
    task_ref: str,
    task_project: str = "",
) -> sqlite3.Row:
    namespaces: list[str] = []
    if task_project:
        namespaces.append(task_project)
    else:
        source = str(project["task_namespace_id"] or "")
        if source:
            namespaces.append(source)
        namespaces.extend(
            str(row["task_namespace_id"])
            for row in conn.execute(
                """SELECT DISTINCT task_namespace_id FROM portfolio_task_links
                   WHERE project_id=? AND removed_at IS NULL
                   ORDER BY task_namespace_id""",
                (project["id"],),
            ).fetchall()
            if str(row["task_namespace_id"]) not in namespaces
        )

    matches: dict[int, sqlite3.Row] = {}
    for namespace in namespaces:
        try:
            task = tm.resolve_task_ref(conn, task_ref, namespace)
        except ValueError:
            continue
        if task is None:
            continue
        allowed = namespace == str(project["task_namespace_id"] or "") or conn.execute(
            """SELECT 1 FROM portfolio_task_links
               WHERE project_id=? AND task_row_id=? AND removed_at IS NULL""",
            (project["id"], task["id"]),
        ).fetchone() is not None
        if allowed:
            matches[int(task["id"])] = task
    if not matches:
        raise PortfolioError(404, f"task '{task_ref}' is not on this project road")
    if len(matches) != 1:
        raise PortfolioError(409, "task reference is ambiguous; provide task_project")
    return next(iter(matches.values()))


def set_task_stage(
    session_id: str,
    project_id: str,
    task_ref: str,
    stage: str | None,
    *,
    task_project: str = "",
) -> dict:
    requested = _normalize_stage_label(stage) if stage is not None else None
    pending_stable_id: str | None = None
    expected_task_id: int | None = None
    with db._conn() as conn:
        project, _actor_row, _role = authorize(
            conn, project_id, session_id, owner_only=True
        )
        order = _stage_order(project)
        canonical = None
        if requested is not None:
            canonical = next(
                (label for label in order if label.casefold() == requested.casefold()),
                None,
            )
            if canonical is None:
                raise PortfolioError(422, "task stage must appear in the project stage order")
        task = _resolve_project_task(conn, project, task_ref, task_project.strip())
        namespace = str(task["project_id"])
        existing = conn.execute(
            """SELECT task_stable_id FROM portfolio_task_links
               WHERE project_id=? AND task_row_id=? AND removed_at IS NULL""",
            (project_id, task["id"]),
        ).fetchone()
        if canonical is not None and existing is None:
            # Only primary-source rows may reach this branch. Explicit foreign
            # rows already have a saved link authorizing their metadata.
            if namespace != str(project["task_namespace_id"] or ""):
                raise PortfolioError(409, "foreign task has no active project link")
            expected_task_id = int(task["id"])

    if expected_task_id is not None:
        try:
            detail = tm.api_get_task(task_ref, project=namespace)
        except (ValueError, RuntimeError) as exc:
            raise PortfolioError(409, f"canonical task resolution failed: {exc}") from exc
        pending_stable_id = str(
            detail.get("stable_id") or f"legacy:{namespace}:{expected_task_id}"
        )

    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        project, _actor_row, _role = authorize(
            conn, project_id, session_id, owner_only=True
        )
        order = _stage_order(project)
        if requested is not None:
            canonical = next(
                (label for label in order if label.casefold() == requested.casefold()),
                None,
            )
            if canonical is None:
                raise PortfolioError(422, "task stage must appear in the project stage order")
        task = _resolve_project_task(conn, project, task_ref, task_project.strip())
        if expected_task_id is not None and int(task["id"]) != expected_task_id:
            raise PortfolioError(409, "task identity changed during stage assignment")
        link = conn.execute(
            """SELECT * FROM portfolio_task_links
               WHERE project_id=? AND task_row_id=? AND removed_at IS NULL""",
            (project_id, task["id"]),
        ).fetchone()
        if link is not None:
            conn.execute(
                """UPDATE portfolio_task_links SET stage_label=?
                   WHERE project_id=? AND task_row_id=? AND removed_at IS NULL""",
                (canonical, project_id, task["id"]),
            )
            stable_id = link["task_stable_id"]
        elif canonical is not None and pending_stable_id is not None:
            try:
                conn.execute(
                    """INSERT INTO portfolio_task_links(
                           project_id,task_stable_id,task_row_id,task_namespace_id,
                           task_display_number,linked_by_session_id,stage_label,created_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        project_id,
                        pending_stable_id,
                        int(task["id"]),
                        str(task["project_id"]),
                        int(task["par_number"]),
                        session_id,
                        canonical,
                        _timestamp(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise PortfolioError(409, "task already has an active portfolio link") from exc
            stable_id = pending_stable_id
        else:
            stable_id = None
        return {
            "project_id": project_id,
            "task_stable_id": stable_id,
            "task_row_id": int(task["id"]),
            "task_namespace_id": str(task["project_id"]),
            "task_display_number": int(task["par_number"]),
            "stage_label": canonical,
        }


def _resolve_scoped_task(
    conn: sqlite3.Connection, actor: sqlite3.Row, task_project: str, task_ref: str
) -> sqlite3.Row:
    mapped = _task_namespace_for_actor(conn, actor)
    if mapped != task_project:
        raise PortfolioError(403, "task must belong to the caller's technical scope")
    try:
        task = tm.resolve_task_ref(conn, task_ref, task_project)
    except ValueError as exc:
        raise PortfolioError(422, str(exc)) from exc
    if task is None:
        raise PortfolioError(404, f"task '{task_ref}' not found")
    return task


def link_task(
    session_id: str, project_id: str, task_project: str, task_ref: str
) -> dict:
    with db._conn() as conn:
        _project_row, actor, _role = authorize(conn, project_id, session_id)
        task = _resolve_scoped_task(conn, actor, task_project, task_ref)
        task_row_id = int(task["id"])
        task_number = int(task["par_number"])
    try:
        detail = tm.api_get_task(task_ref, project=task_project)
    except (ValueError, RuntimeError) as exc:
        raise PortfolioError(409, f"canonical task resolution failed: {exc}") from exc
    stable_id = str(detail.get("stable_id") or f"legacy:{task_project}:{task_row_id}")
    now = _timestamp()
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _project_row, actor, _role = authorize(conn, project_id, session_id)
        current = _resolve_scoped_task(conn, actor, task_project, task_ref)
        if int(current["id"]) != task_row_id or int(current["par_number"]) != task_number:
            raise PortfolioError(409, "task identity changed while linking")
        try:
            conn.execute(
                """INSERT INTO portfolio_task_links(
                       project_id,task_stable_id,task_row_id,task_namespace_id,
                       task_display_number,linked_by_session_id,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    project_id,
                    stable_id,
                    task_row_id,
                    task_project,
                    task_number,
                    session_id,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise PortfolioError(409, "task already has an active portfolio link") from exc
        return {
            "project_id": project_id,
            "task_stable_id": stable_id,
            "task_row_id": task_row_id,
            "task_namespace_id": task_project,
            "task_display_number": task_number,
        }


def unlink_task(session_id: str, project_id: str, task_project: str, task_ref: str) -> dict:
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _project_row, actor, _role = authorize(conn, project_id, session_id)
        task = _resolve_scoped_task(conn, actor, task_project, task_ref)
        changed = conn.execute(
            """UPDATE portfolio_task_links SET removed_at=?
               WHERE project_id=? AND task_row_id=? AND removed_at IS NULL""",
            (_timestamp(), project_id, task["id"]),
        ).rowcount
        if changed != 1:
            raise PortfolioError(404, "active portfolio task link not found")
        return {"ok": True, "project_id": project_id, "task_row_id": task["id"]}


def list_tasks(session_id: str, project_id: str) -> dict:
    with db._conn() as conn:
        authorize(conn, project_id, session_id)
        return {"tasks": _task_payloads(conn, project_id)}


def get_goal(session_id: str, project_id: str) -> dict:
    with db._conn() as conn:
        authorize(conn, project_id, session_id)
        return {"goal": _goal_payload(_goal_row(conn, project_id))}


def create_goal(
    session_id: str,
    project_id: str,
    objective: str,
    *,
    watchdog_enabled: bool = False,
    stall_after_seconds: int = 1800,
    now: str | datetime | None = None,
) -> dict:
    objective = objective.strip()
    if not 1 <= len(objective) <= 4000:
        raise PortfolioError(422, "goal objective must contain 1..4000 characters")
    if stall_after_seconds < 60:
        raise PortfolioError(422, "stall_after_seconds must be at least 60")
    timestamp = _timestamp(now)
    goal_id = str(uuid.uuid4())
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        authorize(conn, project_id, session_id, owner_only=True)
        try:
            conn.execute(
                """INSERT INTO portfolio_goals(
                       id,project_id,objective,status,watchdog_enabled,stall_after_seconds,
                       last_progress_at,created_by_session_id,created_at,updated_at)
                   VALUES(?,?,?,'active',?,?,?,?,?,?)""",
                (
                    goal_id,
                    project_id,
                    objective,
                    int(watchdog_enabled),
                    stall_after_seconds,
                    timestamp,
                    session_id,
                    timestamp,
                    timestamp,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise PortfolioError(409, "project already has an active goal") from exc
        return _goal_payload(
            conn.execute("SELECT * FROM portfolio_goals WHERE id=?", (goal_id,)).fetchone()
        )


def update_goal(
    session_id: str,
    project_id: str,
    goal_id: str,
    *,
    objective: str | None = None,
    watchdog_enabled: bool | None = None,
    stall_after_seconds: int | None = None,
    status: str | None = None,
    now: str | datetime | None = None,
) -> dict:
    fields: list[str] = []
    values: list[object] = []
    if objective is not None:
        objective = objective.strip()
        if not 1 <= len(objective) <= 4000:
            raise PortfolioError(422, "goal objective must contain 1..4000 characters")
        fields.append("objective=?")
        values.append(objective)
    if watchdog_enabled is not None:
        fields.append("watchdog_enabled=?")
        values.append(int(watchdog_enabled))
    if stall_after_seconds is not None:
        if stall_after_seconds < 60:
            raise PortfolioError(422, "stall_after_seconds must be at least 60")
        fields.append("stall_after_seconds=?")
        values.append(stall_after_seconds)
    if status is not None:
        if status not in {"active", "paused", "completed", "cancelled"}:
            raise PortfolioError(422, "invalid goal status")
        fields.append("status=?")
        values.append(status)
        if status in {"completed", "cancelled"}:
            fields.append("completed_at=?")
            values.append(_timestamp(now))
    if not fields:
        raise PortfolioError(422, "no goal fields supplied")
    timestamp = _timestamp(now)
    fields.extend(["revision=revision+1", "updated_at=?"])
    values.extend([timestamp, goal_id, project_id])
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        authorize(conn, project_id, session_id, owner_only=True)
        current = conn.execute(
            "SELECT * FROM portfolio_goals WHERE id=? AND project_id=?",
            (goal_id, project_id),
        ).fetchone()
        if current is None:
            raise PortfolioError(404, "goal not found")
        unchanged = (
            (objective is None or objective == current["objective"])
            and (
                watchdog_enabled is None
                or bool(watchdog_enabled) == bool(current["watchdog_enabled"])
            )
            and (
                stall_after_seconds is None
                or stall_after_seconds == current["stall_after_seconds"]
            )
            and (status is None or status == current["status"])
        )
        if unchanged:
            return _goal_payload(current)
        changed = conn.execute(
            f"UPDATE portfolio_goals SET {', '.join(fields)} WHERE id=? AND project_id=?",
            values,
        ).rowcount
        if changed != 1:
            raise PortfolioError(404, "goal not found")
        return _goal_payload(
            conn.execute("SELECT * FROM portfolio_goals WHERE id=?", (goal_id,)).fetchone()
        )


def _bump_progress(
    conn: sqlite3.Connection,
    project_id: str,
    goal_id: str,
    session_id: str,
    timestamp: str,
) -> None:
    changed = conn.execute(
        """UPDATE portfolio_goals
           SET last_progress_at=?,stall_generation=stall_generation+1,
               revision=revision+1,updated_at=?
           WHERE id=? AND project_id=?""",
        (timestamp, timestamp, goal_id, project_id),
    ).rowcount
    if changed != 1:
        raise PortfolioError(404, "goal not found")
    expires = (
        datetime.fromisoformat(timestamp).astimezone(timezone.utc) + timedelta(minutes=10)
    ).isoformat()
    conn.execute(
        """INSERT INTO portfolio_activity_leases(
               project_id,goal_id,session_id,heartbeat_at,lease_expires_at)
           VALUES(?,?,?,?,?)
           ON CONFLICT(project_id,goal_id,session_id) DO UPDATE SET
               heartbeat_at=excluded.heartbeat_at,
               lease_expires_at=excluded.lease_expires_at""",
        (project_id, goal_id, session_id, timestamp, expires),
    )


def record_progress(
    session_id: str,
    project_id: str,
    goal_id: str,
    note: str = "",
    *,
    now: str | datetime | None = None,
) -> dict:
    note = " ".join(note.split()) or "Progress recorded"
    timestamp = _timestamp(now)
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        authorize(conn, project_id, session_id)
        current_goal = conn.execute(
            "SELECT * FROM portfolio_goals WHERE id=? AND project_id=?",
            (goal_id, project_id),
        ).fetchone()
        if current_goal is None:
            raise PortfolioError(404, "goal not found")
        existing = conn.execute(
            """SELECT * FROM portfolio_goal_progress
               WHERE goal_id=? AND session_id=? AND note=?
               ORDER BY stall_generation DESC,id DESC LIMIT 1""",
            (goal_id, session_id, note),
        ).fetchone()
        if (
            existing is not None
            and existing["stall_generation"] == current_goal["stall_generation"]
        ):
            return {
                "goal": _goal_payload(current_goal),
                "note": note,
                "replayed": True,
            }
        claim_key = hashlib.sha256(
            "\0".join(
                (
                    goal_id,
                    session_id,
                    note.casefold(),
                    str(current_goal["stall_generation"]),
                )
            ).encode("utf-8")
        ).hexdigest()
        _bump_progress(conn, project_id, goal_id, session_id, timestamp)
        goal = conn.execute("SELECT * FROM portfolio_goals WHERE id=?", (goal_id,)).fetchone()
        conn.execute(
            """INSERT INTO portfolio_goal_progress(
                   id,claim_key,goal_id,session_id,note,stall_generation,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()),
                claim_key,
                goal_id,
                session_id,
                note,
                goal["stall_generation"],
                timestamp,
            ),
        )
        return {"goal": _goal_payload(goal), "note": note, "replayed": False}


def _normalize_question(question: str) -> str:
    return " ".join(question.split())


def open_wait(
    session_id: str,
    project_id: str,
    question: str,
    *,
    task_ref: str = "",
    now: str | datetime | None = None,
) -> tuple[dict, bool]:
    question = _normalize_question(question)
    if not question:
        raise PortfolioError(422, "wait question is required")
    timestamp = _timestamp(now)
    wait_id = str(uuid.uuid4())
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        authorize(conn, project_id, session_id)
        goal = _goal_row(conn, project_id)
        if goal is None or goal["status"] not in {"active", "paused"}:
            raise PortfolioError(409, "project has no active goal")
        task_stable_id = ""
        if task_ref:
            linked = conn.execute(
                """SELECT task_stable_id FROM portfolio_task_links
                   WHERE project_id=? AND task_stable_id=? AND removed_at IS NULL""",
                (project_id, task_ref),
            ).fetchone()
            if linked is None:
                raise PortfolioError(422, "wait task must already be linked to the project")
            task_stable_id = str(linked["task_stable_id"])
        claim_source = "\0".join(
            (
                str(goal["id"]),
                str(goal["stall_generation"]),
                session_id,
                question.casefold(),
                task_stable_id,
            )
        )
        claim_key = hashlib.sha256(claim_source.encode("utf-8")).hexdigest()
        open_key = hashlib.sha256(
            "\0".join(
                (str(goal["id"]), session_id, question.casefold(), task_stable_id)
            ).encode("utf-8")
        ).hexdigest()
        existing_open = conn.execute(
            "SELECT * FROM portfolio_waits WHERE open_key=? AND status='open'",
            (open_key,),
        ).fetchone()
        if existing_open is not None:
            return dict(existing_open), False
        inserted = conn.execute(
            """INSERT OR IGNORE INTO portfolio_waits(
                   id,claim_key,open_key,project_id,goal_id,opened_by_session_id,question,
                   task_stable_id,status,opened_at)
               VALUES(?,?,?,?,?,?,?,?,'open',?)""",
            (
                wait_id,
                claim_key,
                open_key,
                project_id,
                goal["id"],
                session_id,
                question,
                task_stable_id or None,
                timestamp,
            ),
        ).rowcount == 1
        row = conn.execute(
            """SELECT * FROM portfolio_waits
               WHERE claim_key=? OR (open_key=? AND status='open')
               ORDER BY CASE WHEN claim_key=? THEN 0 ELSE 1 END LIMIT 1""",
            (claim_key, open_key, claim_key),
        ).fetchone()
        return dict(row), inserted


def list_waits(session_id: str, project_id: str) -> dict:
    with db._conn() as conn:
        authorize(conn, project_id, session_id)
        return {"waits": _wait_payloads(conn, project_id)}


def wait_payload(project_id: str, wait_id: str) -> dict:
    with db._conn() as conn:
        _project(conn, project_id)
        waits = _wait_payloads(conn, project_id)
        row = next((wait for wait in waits if wait["id"] == wait_id), None)
        if row is None:
            raise PortfolioError(404, "wait not found")
        return row


def _wait_response_delivery_id(wait_id: str, attempt: int) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"orchestra:portfolio-wait-answer:{wait_id}:{attempt}",
        )
    )


def prepare_wait_response(project_id: str, wait_id: str, response: str) -> dict:
    response = response.strip()
    if not 1 <= len(response) <= 4000:
        raise PortfolioError(422, "wait response must contain 1..4000 characters")
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT w.*,p.name AS project_name,
                      s.name AS target_name,s.scope AS target_scope,
                      s.task_id AS target_task_id,s.branch AS target_branch,
                      s.needs_switch AS target_needs_switch,s.status AS target_status,
                      l.task_display_number
               FROM portfolio_waits w
               JOIN portfolio_projects p ON p.id=w.project_id
               LEFT JOIN sessions s ON s.id=w.opened_by_session_id
               LEFT JOIN portfolio_task_links l
                 ON l.project_id=w.project_id AND l.task_stable_id=w.task_stable_id
                AND l.removed_at IS NULL
               WHERE w.id=? AND w.project_id=?""",
            (wait_id, project_id),
        ).fetchone()
        if row is None:
            raise PortfolioError(404, "wait not found")
        existing_text = str(row["response_text"] or "")
        if existing_text and existing_text != response:
            raise PortfolioError(409, "wait already has a different response")
        if row["status"] == "cancelled":
            raise PortfolioError(409, "wait is already cancelled")

        delivery = None
        delivery_id = str(row["response_delivery_id"] or "")
        if delivery_id:
            delivery = conn.execute(
                "SELECT * FROM message_deliveries WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
        if row["status"] == "resolved":
            if not existing_text or existing_text != response or delivery is None:
                raise PortfolioError(409, "wait is already resolved")
            return {"delivery_id": delivery_id, "existing": True}

        # An open/pending response always remains addressed to the exact opener.
        # Cached manager state is insufficient: archived sessions stay hydrated.
        if row["target_name"] is None or row["target_status"] == "archived":
            raise PortfolioError(409, "wait opener is archived or missing")

        if delivery is not None and delivery["state"] != "FAILED_BEFORE_SUBMIT":
            return {"delivery_id": delivery_id, "existing": True}

        if delivery is not None:
            attempt = int(row["response_attempt"] or 0) + 1
            delivery_id = _wait_response_delivery_id(wait_id, attempt)
        elif delivery_id:
            # Crash after reservation and before receipt: preserve the frozen id.
            attempt = max(1, int(row["response_attempt"] or 0))
        else:
            attempt = 1
            delivery_id = _wait_response_delivery_id(wait_id, attempt)

        conn.execute(
            """UPDATE portfolio_waits
               SET response_text=?,response_delivery_id=?,response_attempt=?
               WHERE id=? AND project_id=? AND status='open'""",
            (response, delivery_id, attempt, wait_id, project_id),
        )
        task_number = row["task_display_number"]
        if task_number is not None:
            message = f"Пользователь ответил по задаче #{task_number}: {response}"
        else:
            message = f"Пользователь ответил по проекту {row['project_name']}: {response}"
        target_generation = (
            f"session={row['opened_by_session_id']}|task={row['target_task_id'] or ''}|"
            f"branch={row['target_branch'] or ''}|"
            f"needs_switch={int(bool(row['target_needs_switch']))}"
        )
        return {
            "delivery_id": delivery_id,
            "existing": False,
            "target_session_id": str(row["opened_by_session_id"]),
            "target_name": str(row["target_name"]),
            "target_scope": str(row["target_scope"] or ""),
            "target_task_id": str(row["target_task_id"] or ""),
            "target_generation": target_generation,
            "message": message,
        }


def validate_wait_response_delivery(
    project_id: str,
    wait_id: str,
    delivery_id: str,
    target_session_id: str,
) -> None:
    """Recheck the durable wait/target immediately before receipt acceptance."""
    with db._conn() as conn:
        row = conn.execute(
            """SELECT w.status,w.response_delivery_id,s.status AS target_status
               FROM portfolio_waits w
               LEFT JOIN sessions s ON s.id=w.opened_by_session_id
               WHERE w.id=? AND w.project_id=? AND w.opened_by_session_id=?""",
            (wait_id, project_id, target_session_id),
        ).fetchone()
        if row is None:
            raise PortfolioError(409, "wait or opener changed before delivery")
        if row["status"] != "open" or row["response_delivery_id"] != delivery_id:
            raise PortfolioError(409, "wait changed before delivery acceptance")
        if row["target_status"] is None or row["target_status"] == "archived":
            raise PortfolioError(409, "wait opener is archived or missing")


def close_wait(
    session_id: str,
    project_id: str,
    wait_id: str,
    status: str,
    *,
    now: str | datetime | None = None,
) -> dict:
    if status not in {"resolved", "cancelled"}:
        raise PortfolioError(422, "wait status must be resolved or cancelled")
    timestamp = _timestamp(now)
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        authorize(conn, project_id, session_id)
        row = conn.execute(
            """SELECT * FROM portfolio_waits
               WHERE id=? AND project_id=?""",
            (wait_id, project_id),
        ).fetchone()
        if row is None:
            raise PortfolioError(404, "wait not found")
        if row["status"] == status:
            return dict(row)
        if row["status"] != "open":
            raise PortfolioError(409, f"wait is already {row['status']}")
        if row["response_delivery_id"]:
            raise PortfolioError(409, "wait response delivery is already pending")
        conn.execute(
            "UPDATE portfolio_waits SET status=?,resolved_at=? WHERE id=?",
            (status, timestamp, wait_id),
        )
        _bump_progress(conn, project_id, row["goal_id"], session_id, timestamp)
        return dict(
            conn.execute("SELECT * FROM portfolio_waits WHERE id=?", (wait_id,)).fetchone()
        )


def create_attention(
    session_id: str,
    reason: str,
    *,
    kind: str = "legacy",
    project_id: str = "",
) -> dict:
    reason = reason.strip()
    if not reason:
        raise PortfolioError(422, "attention reason is required")
    if kind not in {"legacy", "incident", "reversal", "plan_change"}:
        raise PortfolioError(422, "attention kind must be legacy|incident|reversal|plan_change")
    event_id = str(uuid.uuid4())
    created_at = _timestamp()
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        actor = _session(conn, session_id)
        if actor["role"] not in {"orchestrator", "sub-orchestrator"}:
            raise PortfolioError(403, "attention is orchestrator-only")
        if project_id:
            authorize(conn, project_id, session_id)
        conn.execute(
            """INSERT INTO portfolio_attention_events(
                   id,kind,reason,source_session_id,project_id,created_at)
               VALUES(?,?,?,?,?,?)""",
            (event_id, kind, reason, session_id, project_id or None, created_at),
        )
    return {
        "ok": True,
        "event_id": event_id,
        "kind": kind,
        "reason": reason,
        "project_id": project_id or None,
        "created_at": created_at,
    }


def get_attention_event(event_id: str) -> dict | None:
    with db._conn() as conn:
        row = conn.execute(
            "SELECT * FROM portfolio_attention_events WHERE id=?", (event_id,)
        ).fetchone()
        return dict(row) if row else None

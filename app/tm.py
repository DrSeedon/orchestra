"""Task Manager — core business logic.

Pure data operations. Takes sqlite3.Connection, caller manages transactions.
No HTTP, no YouGile, no TG — those are triggered by callers.
"""

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, date, timezone
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger("tm")

from app.db import _conn

VALID_STATUSES = {"backlog", "new", "in_progress", "done", "paid", "cancelled"}


class TaskIdentity(TypedDict):
    id: int
    project_id: str
    par_number: int
    sync_revision: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return date.today().isoformat()


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
                   scope: str | None = None, yougile_project_id: str = "",
                   yougile_board_id: str = "",
                   yougile_enabled: bool = False,
                   prefix: str = "") -> dict:
    existing = resolve_project_id(conn, project_id)
    if existing:
        return existing
    canonical_id = project_id.casefold()
    now = _now()
    pfx = prefix.upper() if prefix else _generate_prefix(conn, canonical_id)
    conn.execute(
        "INSERT INTO tm_projects (id, name, prefix, scope, yougile_project_id, yougile_board_id, yougile_enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (canonical_id, name or project_id, pfx, scope, yougile_project_id, yougile_board_id, int(yougile_enabled), now),
    )
    return {"id": canonical_id, "name": name or project_id, "prefix": pfx, "scope": scope,
            "yougile_enabled": yougile_enabled, "created_at": now}


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

def ensure_client(conn: sqlite3.Connection, client_id: str, name: str,
                  project_id: str) -> dict:
    existing = conn.execute("SELECT * FROM tm_clients WHERE id = ?", (client_id,)).fetchone()
    if existing:
        return dict(existing)
    now = _now()
    conn.execute(
        "INSERT INTO tm_clients (id, name, project_id, balance_rub, created_at) VALUES (?, ?, ?, 0, ?)",
        (client_id, name, project_id, now),
    )
    return {"id": client_id, "name": name, "project_id": project_id, "balance_rub": 0}


def get_client(conn: sqlite3.Connection, client_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM tm_clients WHERE id = ?", (client_id,)).fetchone()
    return dict(row) if row else None


def get_client_for_project(conn: sqlite3.Connection, project_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM tm_clients WHERE project_id = ? LIMIT 1", (project_id,)
    ).fetchone()
    return dict(row) if row else None


# --- Tasks ---

def create_task(conn: sqlite3.Connection, project_id: str, title: str,
                price_rub: int = 0, description: str = "", assignee: str = "",
                status: str = "new", yougile_task_id: str | None = None,
                par_number: int | None = None, priority: int = 2,
                acceptance_command: str = "") -> dict:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    if price_rub < 0:
        raise ValueError("price_rub must be >= 0")

    now = _now()
    par = par_number if par_number is not None else _next_par(conn, project_id)

    command = (acceptance_command or "").strip()
    from app.acceptance import parse_acceptance_command

    parse_acceptance_command(command)
    conn.execute(
        """INSERT INTO tm_tasks
           (par_number, project_id, title, description, price_rub, paid_rub,
            status, assignee, yougile_task_id, sync_revision,
            git_commits, created_at, updated_at, priority, acceptance_command)
           VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 0, '[]', ?, ?, ?, ?)""",
        (par, project_id, title, description, price_rub,
         status, assignee, yougile_task_id, now, now, priority, command),
    )
    task_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {
        "id": task_id,
        "par_number": par,
        "project_id": project_id,
        "title": title,
        "description": description,
        "price_rub": price_rub,
        "paid_rub": 0,
        "status": status,
        "assignee": assignee,
        "yougile_task_id": yougile_task_id,
        "sync_revision": 0,
        "priority": priority,
        "acceptance_command": command,
        "created_at": now,
        "updated_at": now,
    }


def update_task(conn: sqlite3.Connection, task_id: int, *,
                title: str | None = None, description: str | None = None,
                price_rub: int | None = None, status: str | None = None,
                assignee: str | None = None, worker_session_id: str | None = None,
                git_commits: str | None = None,
                yougile_task_id: str | None = None,
                priority: int | None = None,
                acceptance_command: str | None = None) -> dict:
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

    if acceptance_command is not None:
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

    if yougile_task_id is not None:
        updates.append("yougile_task_id = ?")
        params.append(yougile_task_id)

    if price_rub is not None and price_rub != task["price_rub"]:
        if task["status"] == "cancelled":
            raise ValueError("Cannot change price on cancelled task")
        if price_rub < task["paid_rub"]:
            raise ValueError(f"Cannot lower price below paid_rub ({task['paid_rub']})")
        updates.append("price_rub = ?")
        params.append(price_rub)
        changed.append("price")
        if task["status"] == "paid" and price_rub > task["paid_rub"]:
            # Price raised above what was paid — reopen to 'done' so the debt
            # shows up in the next payment distribution
            updates.append("status = 'done'")
            updates.append("paid_at = NULL")
            changed.append("status")

    old_status = task["status"]
    if status is not None and status != old_status:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")
        if status == "paid":
            raise ValueError("Cannot manually set status to 'paid' — use payment_receive")
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


def format_task_ref(conn: sqlite3.Connection, task: dict) -> str:
    """Format task as plain number string."""
    return str(task["par_number"])


def link_commits_to_task(task_ref: str, commits: list[dict], project_id: str) -> dict:
    """Link commits to a task by ref (e.g. '192', '#192', or 'PAR-192' legacy).
    commits: list of dicts with at least 'hash' key. Deduplicates by hash.
    project_id: authoritative project for every task reference.
    Returns a stable result DTO for merge/MCP callers."""
    if not project_id:
        raise ValueError("project authority is required for commit linking")
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            task = resolve_task_ref(conn, task_ref, project_id)
            if not task:
                conn.rollback()
                return {
                    "ok": False,
                    "added": 0,
                    # «Номера не существует» — это про ИСТОРИЮ коммитов, чинить нечего;
                    # маркер отличает его от «номер есть, но привязка не удалась».
                    "reason": "TASK_NOT_FOUND",
                    "error": f"task '{task_ref}' not found",
                }
            existing = json.loads(task["git_commits"]) if task["git_commits"] else []
            existing_hashes = {c["hash"] if isinstance(c, dict) else c for c in existing}
            new_commits = []
            for c in commits:
                h = c["hash"] if isinstance(c, dict) else c
                if h not in existing_hashes:
                    new_commits.append(c)
                    existing_hashes.add(h)
            if not new_commits:
                conn.rollback()
                return {"ok": True, "added": 0, "task_id": task["id"]}
            all_commits = existing + new_commits
            conn.execute(
                "UPDATE tm_tasks SET git_commits = ?, updated_at = ?, sync_revision = sync_revision + 1 WHERE id = ?",
                (json.dumps(all_commits), _now(), task["id"]),
            )
            conn.commit()
            return {
                "ok": True,
                "added": len(new_commits),
                "task_id": task["id"],
            }
        except Exception:
            conn.rollback()
            raise


def get_task_by_yougile_id(conn: sqlite3.Connection, yougile_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM tm_tasks WHERE yougile_task_id = ?", (yougile_id,)
    ).fetchone()
    return dict(row) if row else None


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

def receive_payment(conn: sqlite3.Connection, client_id: str, amount_rub: int,
                    payment_date: str = "", note: str = "") -> dict:
    if amount_rub <= 0:
        raise ValueError("amount_rub must be > 0")
    client = get_client(conn, client_id)
    if not client:
        raise ValueError(f"Client {client_id} not found")

    now = _now()
    d = payment_date or _today()

    cur = conn.execute(
        "INSERT INTO tm_payments (client_id, amount_rub, date, note, created_at) VALUES (?, ?, ?, ?, ?)",
        (client_id, amount_rub, d, note, now),
    )
    payment_id = cur.lastrowid

    result = _distribute_payment(conn, payment_id, client_id, amount_rub)

    now = _now()
    zero_price_closed = conn.execute(
        """UPDATE tm_tasks SET status = 'paid', paid_at = ?, updated_at = ?, sync_revision = sync_revision + 1
           WHERE status = 'done' AND price_rub = 0
             AND project_id IN (SELECT project_id FROM tm_clients WHERE id = ?)
           RETURNING par_number""",
        (now, now, client_id),
    ).fetchall()

    _sanity_check(conn, client_id, payment_id)

    tasks_closed = sum(1 for d in result["distributions"] if d["now_paid"]) + len(zero_price_closed)
    new_balance = conn.execute(
        "SELECT balance_rub FROM tm_clients WHERE id = ?", (client_id,)
    ).fetchone()[0]
    total_debt = conn.execute(
        """SELECT COALESCE(SUM(price_rub - paid_rub), 0) FROM tm_tasks
           WHERE status = 'done' AND price_rub > 0 AND paid_rub < price_rub
             AND project_id IN (SELECT project_id FROM tm_clients WHERE id = ?)""",
        (client_id,),
    ).fetchone()[0]

    return {
        "payment_id": payment_id,
        "amount_rub": amount_rub,
        "date": d,
        "distributions": result["distributions"],
        "tasks_closed": tasks_closed,
        "remainder_to_balance": result["remainder_to_balance"],
        "new_balance": new_balance,
        "total_debt_remaining": total_debt,
    }


def _distribute_payment(conn: sqlite3.Connection, payment_id: int,
                        client_id: str, amount_rub: int) -> dict:
    # Greedy distribution: smallest debt first → closes the most tasks per payment.
    # Unallocated remainder lands in client balance for future tasks.
    tasks = conn.execute(
        """SELECT * FROM tm_tasks
           WHERE status = 'done' AND price_rub > 0
             AND project_id IN (SELECT project_id FROM tm_clients WHERE id = ?)
             AND paid_rub < price_rub
           ORDER BY (price_rub - paid_rub) ASC, par_number ASC""",
        (client_id,),
    ).fetchall()

    remainder = amount_rub
    distributions = []
    now = _now()

    for task in tasks:
        if remainder <= 0:
            break
        debt = task["price_rub"] - task["paid_rub"]
        allocated = min(debt, remainder)

        conn.execute(
            "INSERT INTO tm_payment_allocations (payment_id, task_id, amount_rub, created_at) "
            "VALUES (?, ?, ?, ?)",
            (payment_id, task["id"], allocated, now),
        )
        new_paid = task["paid_rub"] + allocated
        new_status = "paid" if new_paid == task["price_rub"] else "done"
        conn.execute(
            """UPDATE tm_tasks
               SET paid_rub = ?, status = ?, paid_at = ?,
                   updated_at = ?, sync_revision = sync_revision + 1
               WHERE id = ?""",
            (new_paid, new_status, now if new_status == "paid" else None, now, task["id"]),
        )
        distributions.append({
            "par": format_task_ref(conn, dict(task)),
            "title": task["title"],
            "allocated": allocated,
            "was_debt": debt,
            "now_paid": new_status == "paid",
            "task_id": task["id"],
        })
        remainder -= allocated

    if remainder > 0:
        conn.execute(
            "UPDATE tm_clients SET balance_rub = balance_rub + ? WHERE id = ?",
            (remainder, client_id),
        )

    return {"distributions": distributions, "remainder_to_balance": remainder}


def auto_deduct_prepayment(conn: sqlite3.Connection, task_id: int) -> dict | None:
    task = get_task_by_id(conn, task_id)
    if not task:
        return None
    client = get_client_for_project(conn, task["project_id"])
    if not client or client["balance_rub"] <= 0:
        return None

    debt = task["price_rub"] - task["paid_rub"]
    if debt <= 0:
        return None

    deduct = min(debt, client["balance_rub"])
    remaining_deduct = deduct
    now = _now()

    payments = conn.execute(
        """SELECT p.id, p.amount_rub,
                  COALESCE(SUM(a.amount_rub), 0) as allocated
           FROM tm_payments p
           LEFT JOIN tm_payment_allocations a ON a.payment_id = p.id
           WHERE p.client_id = ?
           GROUP BY p.id
           HAVING p.amount_rub > COALESCE(SUM(a.amount_rub), 0)
           ORDER BY p.id ASC""",
        (client["id"],),
    ).fetchall()

    for payment in payments:
        if remaining_deduct <= 0:
            break
        available = payment["amount_rub"] - payment["allocated"]
        take = min(available, remaining_deduct)
        conn.execute(
            "INSERT INTO tm_payment_allocations (payment_id, task_id, amount_rub, created_at) "
            "VALUES (?, ?, ?, ?)",
            (payment["id"], task_id, take, now),
        )
        remaining_deduct -= take

    new_paid = task["paid_rub"] + deduct
    new_status = "paid" if new_paid == task["price_rub"] else "done"
    conn.execute(
        """UPDATE tm_tasks SET paid_rub=?, status=?, paid_at=?,
                updated_at=?, sync_revision = sync_revision + 1
           WHERE id=?""",
        (new_paid, new_status, now if new_status == "paid" else None, now, task_id),
    )
    conn.execute(
        "UPDATE tm_clients SET balance_rub = balance_rub - ? WHERE id=?",
        (deduct, client["id"]),
    )

    _sanity_check(conn, client["id"])

    return {
        "deducted": deduct,
        "new_paid": new_paid,
        "new_status": new_status,
        "task_id": task_id,
    }


def get_payment_status(conn: sqlite3.Connection, client_id: str) -> dict:
    client = get_client(conn, client_id)
    if not client:
        raise ValueError(f"Client {client_id} not found")

    total_debt = conn.execute(
        """SELECT COALESCE(SUM(price_rub - paid_rub), 0) FROM tm_tasks
           WHERE status = 'done' AND price_rub > 0 AND paid_rub < price_rub
             AND project_id = ?""",
        (client["project_id"],),
    ).fetchone()[0]

    tasks_with_debt = conn.execute(
        """SELECT par_number, title, price_rub, paid_rub FROM tm_tasks
           WHERE status = 'done' AND price_rub > 0 AND paid_rub < price_rub
             AND project_id = ?
           ORDER BY (price_rub - paid_rub) ASC""",
        (client["project_id"],),
    ).fetchall()

    recent_payments = conn.execute(
        "SELECT * FROM tm_payments WHERE client_id = ? ORDER BY id DESC LIMIT 10",
        (client_id,),
    ).fetchall()

    return {
        "client": client["name"],
        "balance_rub": client["balance_rub"],
        "balance_display": _fmt_amount(client["balance_rub"]),
        "total_debt_rub": total_debt,
        "total_debt_display": _fmt_amount(total_debt),
        "net_position": client["balance_rub"] - total_debt,
        "tasks_with_debt": [
            {"par": str(t["par_number"]),
             "title": t["title"],
             "debt": _fmt_amount(t["price_rub"] - t["paid_rub"])}
            for t in tasks_with_debt
        ],
        "recent_payments": [
            {"id": p["id"], "date": p["date"], "amount": _fmt_amount(p["amount_rub"]),
             "note": p["note"]}
            for p in recent_payments
        ],
    }


def _sanity_check(conn: sqlite3.Connection, client_id: str,
                  payment_id: int | None = None) -> None:
    if payment_id is not None:
        row = conn.execute(
            """SELECT COALESCE(SUM(amount_rub), 0) as total FROM tm_payment_allocations
               WHERE payment_id = ?""",
            (payment_id,),
        ).fetchone()
        payment = conn.execute(
            "SELECT amount_rub FROM tm_payments WHERE id = ?", (payment_id,)
        ).fetchone()
        if payment and row["total"] > payment["amount_rub"]:
            raise RuntimeError(
                f"Over-allocation: payment {payment_id} has {payment['amount_rub']}, "
                f"allocated {row['total']}"
            )

    bad_tasks = conn.execute(
        """SELECT id, par_number, paid_rub, price_rub,
                  (SELECT COALESCE(SUM(amount_rub), 0) FROM tm_payment_allocations WHERE task_id = tm_tasks.id) as computed_paid
           FROM tm_tasks
           WHERE project_id IN (SELECT project_id FROM tm_clients WHERE id = ?)
             AND paid_rub != (SELECT COALESCE(SUM(amount_rub), 0) FROM tm_payment_allocations WHERE task_id = tm_tasks.id)
             AND paid_rub > 0""",
        (client_id,),
    ).fetchall()
    if bad_tasks:
        details = "; ".join(
            f"#{t['par_number']}: paid_rub={t['paid_rub']}, computed={t['computed_paid']}, price={t['price_rub']}"
            for t in bad_tasks
        )
        logger.warning(f"Task payment mismatch (stale allocations?): {details}")

    computed = conn.execute(
        """SELECT
              (SELECT COALESCE(SUM(amount_rub), 0) FROM tm_payments WHERE client_id = ?)
              -
              (SELECT COALESCE(SUM(a.amount_rub), 0) FROM tm_payment_allocations a
               JOIN tm_payments p ON a.payment_id = p.id WHERE p.client_id = ?)
           AS bal""",
        (client_id, client_id),
    ).fetchone()["bal"]
    actual = conn.execute(
        "SELECT balance_rub FROM tm_clients WHERE id = ?", (client_id,)
    ).fetchone()["balance_rub"]
    if computed != actual:
        logger.warning(
            f"Balance mismatch for {client_id}: computed={computed}, stored={actual}. "
            f"Likely caused by external task deletion without allocation cleanup."
        )
    if actual < 0:
        logger.warning(f"Negative balance for {client_id}: {actual}")



# --- Sync log helpers ---

def log_sync(conn: sqlite3.Connection, task_id: int | None, action: str,
             sync_revision: int | None, status: str, error: str = "",
             payload: str = "") -> int:
    now = _now()
    completed = now if status in ("ok", "skipped") else None
    cur = conn.execute(
        """INSERT INTO tm_sync_log
           (task_id, direction, action, sync_revision, payload, status, error, created_at, completed_at)
           VALUES (?, 'push', ?, ?, ?, ?, ?, ?, ?)""",
        (task_id, action, sync_revision, payload, status, error or None, now, completed),
    )
    return cur.lastrowid


# --- Sync helpers (fire-and-forget after commit) ---

def _is_yougile_enabled(task_id: int) -> bool:
    with _conn() as conn:
        row = conn.execute(
            """SELECT p.yougile_enabled FROM tm_projects p
               JOIN tm_tasks t ON t.project_id = p.id
               WHERE t.id = ?""",
            (task_id,),
        ).fetchone()
        return bool(row and row[0])


# Captured app loop: fire-helpers are called from asyncio.to_thread workers (routes/tm),
# where get_running_loop() raises and sync would silently no-op without this.
_MAIN_LOOP: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Capture the app event loop (called from main.py lifespan) so YouGile sync
    fired from worker threads still lands on the loop."""
    global _MAIN_LOOP
    _MAIN_LOOP = loop


def _schedule(coro) -> None:
    """Schedule coro on the current running loop, or threadsafe on the captured main loop."""
    try:
        asyncio.get_running_loop().create_task(coro)
        return
    except RuntimeError:
        pass
    if _MAIN_LOOP is not None and not _MAIN_LOOP.is_closed():
        asyncio.run_coroutine_threadsafe(coro, _MAIN_LOOP)
        return
    coro.close()  # suppress "never awaited" warning in CLI context
    raise RuntimeError("no event loop")


# Wired callbacks: registered by tm_yougile at import (cycle cut — tm no longer
# imports tm_yougile). main.py lifespan imports tm_yougile to guarantee registration.
on_task_synced = None       # async (task_id: int) -> str
on_payment_changed = None   # async (payment_result: dict, client_id: str) -> str


def _fire_async(coro, what: str) -> None:
    """Fire-and-forget a sync coroutine; tolerate CLI contexts with no loop."""
    try:
        _schedule(coro)
    except RuntimeError:
        logger.debug("No event loop for %s, skipping (CLI context)", what)
    except Exception as e:
        logger.error("%s fire failed: %s", what, e)


def _fire_sync(task_id: int) -> None:
    if on_task_synced is None or not _is_yougile_enabled(task_id):
        return
    with _conn() as conn:
        task = get_task_by_id(conn, task_id)
        rev = task["sync_revision"] if task else 0
        action = "update" if task and task.get("yougile_task_id") else "create"
        sync_log_id = log_sync(conn, task_id, action, rev, "pending")

    async def _do():
        try:
            await on_task_synced(task_id)
            with _conn() as c:
                c.execute(
                    "UPDATE tm_sync_log SET status = 'ok', completed_at = ? WHERE id = ? AND status = 'pending'",
                    (_now(), sync_log_id),
                )
        except Exception as e:
            logger.error("YouGile sync failed for task %d: %s", task_id, e)
            with _conn() as c:
                c.execute(
                    "UPDATE tm_sync_log SET status = 'error', completed_at = ? WHERE id = ? AND status = 'pending'",
                    (_now(), sync_log_id),
                )

    _fire_async(_do(), f"task #{task_id} sync")


def _fire_journal_sync(payment_result: dict, client_id: str) -> None:
    if on_payment_changed is None:
        return
    task_ids = [d["task_id"] for d in payment_result.get("distributions", []) if d.get("task_id")]
    if task_ids and not _is_yougile_enabled(task_ids[0]):
        return
    with _conn() as conn:
        sync_log_id = log_sync(conn, None, "journal_update", None, "pending",
                               payload=str(payment_result.get("payment_id", "")))

    async def _do():
        try:
            result = await on_payment_changed(payment_result, client_id)
            status = "ok" if result == "ok" else "error"
            with _conn() as c:
                c.execute(
                    "UPDATE tm_sync_log SET status = ?, error = ?, completed_at = ? WHERE id = ?",
                    (status, result if status == "error" else None, _now(), sync_log_id),
                )
        except Exception as e:
            logger.error("Journal sync failed: %s", e)
            with _conn() as c:
                c.execute(
                    "UPDATE tm_sync_log SET status = 'error', error = ?, completed_at = ? WHERE id = ?",
                    (str(e), _now(), sync_log_id),
                )

    _fire_async(_do(), "journal sync")


# --- High-level API for routes/MCP ---

def api_create_task(project_id: str, title: str, price: int = 0,
                    description: str = "", assignee: str = "",
                    status: str = "new", scope: str = "",
                    priority: int = 2, acceptance_command: str = "") -> dict:
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
            task = create_task(
                conn, resolved_project_id, title,
                price_rub=price,
                description=description,
                assignee=assignee,
                status=status,
                priority=priority,
                acceptance_command=acceptance_command,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    _fire_sync(task["id"])
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
                    acceptance_command: str | None = None) -> dict:
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
            )

            if status == "done":
                auto_deduct_prepayment(conn, task_id)

            updated = get_task_by_id(conn, task_id)
            task_ref = format_task_ref(conn, updated)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    _fire_sync(task_id)
    response = {
        "par": task_ref,
        "project": updated["project_id"],
        "updated": result["changed"],
    }
    if result["changed"] == ["acceptance_command"]:
        return response
    return {
        **response,
        "old_status": result.get("old_status", updated["status"]),
        "new_status": updated["status"],
        "price_rub": updated["price_rub"],
        "paid_rub": updated["paid_rub"],
    }


def api_update_task_if_current(
    identity: TaskIdentity,
    *,
    status: str,
    worker_session_id: str | None = None,
) -> dict:
    """Update a prevalidated task only while its immutable identity/version matches."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")
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

    _fire_sync(task_id)
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

    total_debt = sum(
        t["price_rub"] - t["paid_rub"]
        for t in tasks
        if t["status"] == "done" and t["price_rub"] > 0 and t["paid_rub"] < t["price_rub"]
    )

    return {
        "tasks": [
            {
                "par": str(t["par_number"]),
                "title": t["title"],
                "project": t["project_id"],
                "price": _fmt_amount(t["price_rub"]),
                "paid": _fmt_amount(t["paid_rub"]),
                "debt": _fmt_amount(t["price_rub"] - t["paid_rub"]),
                "status": t["status"],
                "assignee": t["assignee"],
                "priority": t.get("priority", 2),
            }
            for t in tasks
        ],
        "count": len(tasks),
        "total_debt": _fmt_amount(total_debt),
    }


def api_get_task(par: str, project: str = "") -> dict:
    with _conn() as conn:
        task = resolve_task_ref(conn, par, project)
        if not task:
            raise ValueError(f"{par} not found")

        task_ref = format_task_ref(conn, task)

        payments = conn.execute(
            """SELECT a.amount_rub, a.created_at, p.id as payment_id, p.date
               FROM tm_payment_allocations a
               JOIN tm_payments p ON a.payment_id = p.id
               WHERE a.task_id = ?
               ORDER BY a.id ASC""",
            (task["id"],),
        ).fetchall()

    commits = json.loads(task["git_commits"]) if task["git_commits"] else []

    return {
        "par": task_ref,
        "title": task["title"],
        "description": task["description"],
        "project": task["project_id"],
        "price_rub": task["price_rub"],
        "paid_rub": task["paid_rub"],
        "debt_rub": task["price_rub"] - task["paid_rub"],
        "status": task["status"],
        "assignee": task["assignee"],
        "priority": task.get("priority", 2),
        "created_at": task["created_at"],
        "completed_at": task["completed_at"],
        "payments": [
            {"date": p["date"], "amount": p["amount_rub"], "payment_id": p["payment_id"]}
            for p in payments
        ],
        "commits": commits,
        "yougile_id": task["yougile_task_id"],
        "sync_revision": task["sync_revision"],
    }


def api_receive_payment(amount: int, client: str = "aleksandr-kislinskiy",
                        payment_date: str = "", note: str = "") -> dict:
    amount_rub = amount
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = receive_payment(conn, client, amount_rub, payment_date, note)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    for d in result.get("distributions", []):
        _fire_sync(d["task_id"])
    _fire_journal_sync(result, client)

    result["sync_status"] = "pending"
    return result


def api_payment_status(client: str = "aleksandr-kislinskiy") -> dict:
    with _conn() as conn:
        return get_payment_status(conn, client)

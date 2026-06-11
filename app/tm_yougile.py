"""YouGile sync — one-way push from Orchestra to YouGile.

Orchestra is source of truth. YouGile is a read-only mirror for the client.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import httpx
import markdown

from app import tm

logger = logging.getLogger("tm-yougile")

YOUGILE_API = "https://yougile.com/api-v2"


def _get_yougile_token() -> str:
    return os.environ.get("YOUGILE_SEEDON_TOKEN", "")
YOUGILE_BOARD_ID = "93007367-153b-4aec-8dd7-96dda1fd1f27"
DONE_COLUMN_ID = "caf3e21c-7ec8-4dce-b70c-0019290019ea"

STATUS_TO_COLUMN = {
    "backlog":     "0096a255-f3b9-4da0-a07d-070599a1bc9e",
    "new":         "c6c65162-fac6-4d9d-915a-18036d22dfc0",
    "in_progress": "7bca2e03-971c-4adc-8ad6-9c0d3f2a85cb",
    "done":        "caf3e21c-7ec8-4dce-b70c-0019290019ea",
    "paid":        "7d179d60-20a3-4ba3-a2b0-d9011db6e300",
    "cancelled":   "fff16786-0ed9-4f53-a779-3809d3911565",
}

COLUMN_TO_STATUS = {
    "0096a255-f3b9-4da0-a07d-070599a1bc9e": "backlog",
    "4a73449b-0a5a-4b41-82c1-d0e7c5033d89": "backlog",
    "c6c65162-fac6-4d9d-915a-18036d22dfc0": "new",
    "7bca2e03-971c-4adc-8ad6-9c0d3f2a85cb": "in_progress",
    "74d765bc-a703-4011-abe4-83c3e3433c56": "in_progress",
    "caf3e21c-7ec8-4dce-b70c-0019290019ea": "done",
    "7d179d60-20a3-4ba3-a2b0-d9011db6e300": "paid",
    "fff16786-0ed9-4f53-a779-3809d3911565": "cancelled",
}

MAX_RETRIES = 3


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_yougile_token()}",
        "Content-Type": "application/json",
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_yougile_title(task: dict) -> str:
    if task["price_rub"] > 0:
        x = task["paid_rub"] // 1000
        y = task["price_rub"] // 1000
        return f"{task['title']} | {x}/{y}k ₽"
    return task["title"]


def md_to_html(md_text: str) -> str:
    if not md_text:
        return ""
    return markdown.markdown(md_text)


async def _yougile_request(method: str, path: str, body: dict | None = None) -> dict | None:
    if not _get_yougile_token():
        logger.warning("YOUGILE_SEEDON_TOKEN not set, skipping sync")
        return None
    async with httpx.AsyncClient(timeout=15) as client:
        url = f"{YOUGILE_API}{path}"
        resp = await client.request(method, url, headers=_headers(), json=body)
        if resp.status_code in (200, 201):
            return resp.json()
        logger.error("YouGile API error: %s %s → %d %s", method, path, resp.status_code, resp.text[:200])
        return {"error": f"HTTP {resp.status_code}"}


async def yougile_find_by_par(par_label: str) -> dict | None:
    for col_id in STATUS_TO_COLUMN.values():
        offset = 0
        while True:
            result = await _yougile_request("GET", f"/tasks?columnId={col_id}&offset={offset}&limit=50")
            if not result or "content" not in result:
                break
            content = result["content"]
            for t in content:
                if t.get("idTaskProject") == par_label:
                    return t
            if len(content) < 50:
                break
            offset += 50
    return None


# SQLite never touches the event loop: each helper below opens its own connection,
# runs one whole transaction, and closes — called via asyncio.to_thread.

def _db_get_task(task_id: int) -> dict | None:
    conn = tm._conn()
    try:
        return tm.get_task_by_id(conn, task_id)
    finally:
        conn.close()


def _db_set_yougile_id_and_log(task_id: int, yougile_id: str, revision: int) -> None:
    conn = tm._conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "UPDATE tm_tasks SET yougile_task_id = ? WHERE id = ?",
                (yougile_id, task_id),
            )
            tm.log_sync(conn, task_id, "create", revision, "ok")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def _db_log_sync(task_id: int, op: str, revision: int, status: str, error: str = "") -> None:
    conn = tm._conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            tm.log_sync(conn, task_id, op, revision, status, error=error)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def _db_log_update_and_skip_stale(task_id: int, revision: int, status: str, error: str) -> None:
    conn = tm._conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            tm.log_sync(conn, task_id, "update", revision, status, error=error)
            conn.execute(
                "UPDATE tm_sync_log SET status = 'skipped' "
                "WHERE task_id = ? AND status = 'pending' AND sync_revision < ?",
                (task_id, revision),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


async def yougile_sync_task(task_id: int) -> str:
    task = await asyncio.to_thread(_db_get_task, task_id)
    if not task:
        return "task not found"

    if not task["yougile_task_id"]:
        existing = await yougile_find_by_par(str(task['par_number'])) or await yougile_find_by_par(f"PAR-{task['par_number']}")
        if existing:
            await asyncio.to_thread(
                _db_set_yougile_id_and_log, task_id, existing["id"], task["sync_revision"])
            task = await asyncio.to_thread(_db_get_task, task_id)
            await _yougile_push_update(task)
            if task["status"] == "done":
                await _update_done_column_title(task.get("project_id", ""))
            return "backfilled + updated"

        result = await _yougile_push_create(task)
        if result and not result.get("error") and result.get("id"):
            await asyncio.to_thread(
                _db_set_yougile_id_and_log, task_id, result["id"], task["sync_revision"])
            return "created"
        error = str(result) if result else "no response"
        await asyncio.to_thread(
            _db_log_sync, task_id, "create", task["sync_revision"], "error", error)
        return f"create failed: {error}"

    fresh = await asyncio.to_thread(_db_get_task, task_id)
    if fresh and fresh["sync_revision"] > task["sync_revision"]:
        task = fresh

    result = await _yougile_push_update(task)
    status = "ok" if result and not result.get("error") else "error"
    error = str(result) if status == "error" else ""
    await asyncio.to_thread(
        _db_log_update_and_skip_stale, task_id, task["sync_revision"], status, error)
    if status == "ok" and task["status"] == "done":
        await _update_done_column_title(task.get("project_id", ""))
    return status


async def _yougile_push_create(task: dict) -> dict | None:
    body = {
        "title": format_yougile_title(task),
        "description": md_to_html(task["description"]),
        "columnId": STATUS_TO_COLUMN.get(task["status"], STATUS_TO_COLUMN["new"]),
        "idTaskProject": str(task['par_number']),
    }
    return await _yougile_request("POST", "/tasks", body)


async def _yougile_push_update(task: dict) -> dict | None:
    if not task.get("yougile_task_id"):
        return {"error": "no yougile_task_id"}
    body = {
        "title": format_yougile_title(task),
        "description": md_to_html(task.get("description", "")),
        "columnId": STATUS_TO_COLUMN.get(task["status"], STATUS_TO_COLUMN["new"]),
        "completed": task["price_rub"] > 0 and task["paid_rub"] == task["price_rub"],
    }
    return await _yougile_request("PUT", f"/tasks/{task['yougile_task_id']}", body)


def _db_total_debt(project_id: str = "") -> int:
    conn = tm._conn()
    try:
        if project_id:
            return conn.execute(
                "SELECT COALESCE(SUM(price_rub - paid_rub), 0) FROM tm_tasks "
                "WHERE status = 'done' AND price_rub > 0 AND paid_rub < price_rub "
                "AND project_id = ?", (project_id,)
            ).fetchone()[0]
        return conn.execute(
            "SELECT COALESCE(SUM(price_rub - paid_rub), 0) FROM tm_tasks "
            "WHERE status = 'done' AND price_rub > 0 AND paid_rub < price_rub"
        ).fetchone()[0]
    finally:
        conn.close()


async def _update_done_column_title(project_id: str = "") -> None:
    """Recalculate and update the 'Сделано' column title with total debt from DB."""
    total_debt = await asyncio.to_thread(_db_total_debt, project_id)
    total_debt_k = total_debt // 1000
    await _yougile_request("PUT", f"/columns/{DONE_COLUMN_ID}", {
        "title": f"Сделано → {total_debt_k}k ₽",
    })


def _fmt_k(rub: int) -> str:
    if rub >= 1000:
        return f"{rub // 1000}k"
    return str(rub)


def _db_get_client(client_id: str) -> dict | None:
    conn = tm._conn()
    try:
        return tm.get_client(conn, client_id)
    finally:
        conn.close()


def _db_set_journal_id(client_id: str, yid: str) -> None:
    conn = tm._conn()
    try:
        conn.execute("UPDATE tm_clients SET journal_yougile_id=? WHERE id=?", (yid, client_id))
        conn.commit()
    finally:
        conn.close()


async def _ensure_journal_task(client_id: str) -> str | None:
    client = await asyncio.to_thread(_db_get_client, client_id)
    if not client:
        return None
    yid = client.get("journal_yougile_id") or ""
    if yid:
        check = await _yougile_request("GET", f"/tasks/{yid}")
        if check and not check.get("error"):
            return yid
    result = await _yougile_request("POST", "/tasks", {
        "title": f"Журнал оплат — {client['name']}",
        "description": "",
        "columnId": STATUS_TO_COLUMN["new"],
    })
    if not result or result.get("error") or not result.get("id"):
        logger.error("Failed to create journal task: %s", result)
        return None
    yid = result["id"]
    await asyncio.to_thread(_db_set_journal_id, client_id, yid)
    logger.info("Created journal task %s for client %s", yid, client_id)
    return yid


async def update_payment_journal(payment_result: dict, client_id: str) -> str:
    errors = []

    journal_id = await _ensure_journal_task(client_id)
    if not journal_id:
        return "journal task not available"

    amount_rub = payment_result["amount_rub"]
    payment_date = payment_result["date"]
    balance = payment_result.get("new_balance", 0)
    distributions = payment_result.get("distributions", [])

    dist_lines = []
    for d in distributions:
        status_mark = ' ✅ → "Оплачено"' if d["now_paid"] else ' → остаётся в "Сделано"'
        dist_lines.append(
            f"• #{d['par']} {d['title']} — {_fmt_k(d['allocated'])} ₽{status_mark}"
        )
    block_parts = [
        f"<b>💰 Распределение оплаты {amount_rub:,} ₽ от {payment_date}</b><br /><br />",
        f"Получено: <b>{amount_rub:,} ₽</b><br /><br />",
    ]
    if dist_lines:
        block_parts.append("<b>Распределение:</b><br />")
        block_parts.append("<br />".join(dist_lines))
        block_parts.append("<br /><br />")
    block_parts.append(f"<b>Баланс предоплаты: {_fmt_k(balance)} ₽</b>")
    new_block = "".join(block_parts)

    current = await _yougile_request("GET", f"/tasks/{journal_id}")
    if not current or current.get("error"):
        errors.append(f"read task: {current}")
    else:
        desc = current.get("description", "") or ""
        if desc:
            desc += "<br /><hr /><br />"
        desc += new_block
        r = await _yougile_request("PUT", f"/tasks/{journal_id}", {"description": desc})
        if not r or r.get("error"):
            errors.append(f"description: {r}")

    r = await _yougile_request("PUT", f"/tasks/{journal_id}", {
        "title": f"Журнал оплат | {_fmt_k(balance)} баланс",
    })
    if not r or r.get("error"):
        errors.append(f"title: {r}")

    debt_k = payment_result.get("total_debt_remaining", 0) // 1000
    r = await _yougile_request("PUT", f"/columns/{DONE_COLUMN_ID}", {
        "title": f"Сделано → {debt_k}k ₽",
    })
    if not r or r.get("error"):
        errors.append(f"column title: {r}")

    if errors:
        return f"partial failure: {'; '.join(errors)}"
    return "ok"

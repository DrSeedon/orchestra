"""Task Manager API routes."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import tm as _tm

router = APIRouter(prefix="/api/tm", tags=["task-manager"])


class TmTaskCreate(BaseModel):
    title: str
    project: str
    price: int = 0
    description: str = ""
    assignee: str = ""
    status: str = "new"
    scope: str = ""
    priority: int = 2


class TmTaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    price: int | None = None
    status: str | None = None
    assignee: str | None = None
    priority: int | None = None


class TmPaymentReceive(BaseModel):
    amount: int
    client: str = ""
    scope: str = ""
    date: str = ""
    note: str = ""


def _resolve_client_id(client: str, scope: str) -> str:
    if client:
        return client
    if scope:
        with _tm._conn() as conn:
            proj = _tm.get_project_by_scope(conn, scope)
            if proj:
                cl = _tm.get_client_for_project(conn, proj["id"])
                if cl:
                    return cl["id"]
    raise ValueError("No client specified and no client found for project scope")


@router.post("/tasks")
async def tm_create_task(req: TmTaskCreate):
    try:
        return _tm.api_create_task(
            req.project, req.title, req.price, req.description, req.assignee, req.status,
            scope=req.scope, priority=req.priority,
        )
    except (ValueError, RuntimeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/tasks")
async def tm_list_tasks(project: str = "", status: str = "", assignee: str = "",
                        scope: str = ""):
    proj = project
    if not proj and scope:
        with _tm._conn() as conn:
            p = _tm.get_project_by_scope(conn, scope)
            if p:
                proj = p["id"]
            else:
                return {"tasks": [], "count": 0, "total_debt": "0"}
    return _tm.api_list_tasks(proj, status, assignee)


@router.get("/tasks/{par}")
async def tm_get_task(par: str, scope: str = ""):
    try:
        project = ""
        if scope:
            with _tm._conn() as conn:
                p = _tm.get_project_by_scope(conn, scope)
                if p:
                    project = p["id"]
        return _tm.api_get_task(par, project=project)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.put("/tasks/{par}")
async def tm_update_task(par: str, req: TmTaskUpdate, scope: str = ""):
    try:
        project = ""
        if scope:
            with _tm._conn() as conn:
                p = _tm.get_project_by_scope(conn, scope)
                if p:
                    project = p["id"]
        return _tm.api_update_task(
            par, req.title, req.description, req.price, req.status, req.assignee,
            project=project, priority=req.priority,
        )
    except (ValueError, RuntimeError) as e:
        code = 404 if "not found" in str(e).lower() else 400
        return JSONResponse({"error": str(e)}, status_code=code)


@router.post("/payments")
async def tm_receive_payment(req: TmPaymentReceive):
    try:
        client_id = _resolve_client_id(req.client, req.scope)
        return _tm.api_receive_payment(req.amount, client_id, req.date, req.note)
    except (ValueError, RuntimeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/payments/status")
async def tm_payment_status(client: str = "", scope: str = ""):
    try:
        client_id = _resolve_client_id(client, scope)
        return _tm.api_payment_status(client_id)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.get("/payments/history")
async def tm_payment_history(client: str = "", scope: str = ""):
    try:
        client_id = _resolve_client_id(client, scope)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    with _tm._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tm_payments WHERE client_id = ? ORDER BY id DESC LIMIT 50",
            (client_id,),
        ).fetchall()
    return {
        "payments": [
            {"id": r["id"], "amount_rub": r["amount_rub"], "date": r["date"],
             "note": r["note"], "created_at": r["created_at"]}
            for r in rows
        ]
    }


@router.get("/sync/log")
async def tm_sync_log(limit: int = 50):
    limit = min(limit, 200)
    with _tm._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tm_sync_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"entries": [dict(r) for r in rows]}


@router.post("/sync/retry/{sync_id}")
async def tm_sync_retry(sync_id: int):
    with _tm._conn() as conn:
        row = conn.execute("SELECT * FROM tm_sync_log WHERE id = ?", (sync_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "sync entry not found"}, status_code=404)
        entry = dict(row)
        if entry["status"] not in ("error", "pending"):
            return {"message": "nothing to retry", "status": entry["status"]}
        task_id = entry["task_id"]

    if task_id:
        from app.tm_yougile import yougile_sync_task
        result = await yougile_sync_task(task_id)
        return {"retried": True, "task_id": task_id, "result": result}
    return {"error": "no task_id on sync entry"}

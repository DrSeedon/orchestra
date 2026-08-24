"""Task Manager API routes."""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import tm as _tm
from app.tm_yougile import yougile_sync_task

router = APIRouter(prefix="/api/tm", tags=["task-manager"])


class TmTaskCreate(BaseModel):
    title: str
    project: str = ""
    price: int = 0
    description: str = ""
    assignee: str = ""
    status: str = "new"
    scope: str = ""
    priority: int = 2
    acceptance_command: str = ""
    acceptance_manifest: list[str] = Field(default_factory=list)
    acceptance_required: bool = False


class TmTaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    price: int | None = None
    status: str | None = None
    assignee: str | None = None
    priority: int | None = None
    acceptance_command: str | None = None
    acceptance_manifest: list[str] | None = None
    acceptance_required: bool | None = None
    clear_acceptance_command: bool = False
    clear_acceptance_oracle: bool = False


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


def _resolve_scope_project_id(scope: str) -> str:
    with _tm._conn() as conn:
        p = _tm.get_project_by_scope(conn, scope)
        return p["id"] if p else ""


def _resolve_task_project_id(project: str, scope: str) -> str:
    if project:
        with _tm._conn() as conn:
            resolved = _tm.resolve_project_selector(conn, project)
        if not resolved:
            raise ValueError(f"project '{project}' not found")
        return resolved["id"]
    if not scope:
        raise ValueError("explicit project or mapped scope is required")
    resolved = _resolve_scope_project_id(scope)
    if not resolved:
        raise ValueError(f"scope '{scope}' has no task project")
    return resolved


def _acceptance_actor(request: Request) -> tuple[dict, str]:
    session_id = request.headers.get("x-orchestra-session-id", "").strip()
    if not session_id:
        raise ValueError("acceptance oracle caller has no session identity")
    from app.db import get_session

    caller = get_session(session_id)
    caller_scope = str((caller or {}).get("scope") or "").strip()
    if not caller_scope:
        raise ValueError("acceptance oracle caller has no project scope")
    actor = {
        "session_id": session_id,
        "name": str((caller or {}).get("name") or "").strip(),
        "role": str((caller or {}).get("role") or "").strip(),
        "scope": caller_scope,
    }
    return actor, caller_scope


@router.post("/tasks")
async def tm_create_task(req: TmTaskCreate, request: Request):
    command = (req.acceptance_command or "").strip()
    caller_scope = ""
    actor = None
    oracle_requested = bool(req.acceptance_required or req.acceptance_manifest)
    if command or oracle_requested:
        from app.mcp_proof import caller_may_use_orchestrator_privilege

        if not caller_may_use_orchestrator_privilege(request):
            return JSONResponse(
                {"error": "acceptance_command is orchestrator-only"},
                status_code=403,
            )
        if oracle_requested:
            try:
                actor, caller_scope = _acceptance_actor(request)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=403)
        else:
            session_id = request.headers.get("x-orchestra-session-id", "").strip()
            if session_id:
                from app.db import get_session

                caller = get_session(session_id)
                caller_scope = str((caller or {}).get("scope") or "").strip()
                if not caller_scope:
                    return JSONResponse(
                        {"error": "acceptance_command caller has no project scope"},
                        status_code=403,
                    )
    try:
        def _do():
            project = req.project
            scope = req.scope
            if command and caller_scope:
                resolved_project = _resolve_task_project_id("", caller_scope)
                if project and _resolve_task_project_id(project, "") != resolved_project:
                    raise ValueError(
                        "acceptance_command create is limited to caller's project"
                    )
                if scope and _resolve_task_project_id("", scope) != resolved_project:
                    raise ValueError(
                        "acceptance_command create is limited to caller's project"
                    )
                project = resolved_project
                scope = ""
            return _tm.api_create_task(
                project, req.title, req.price, req.description, req.assignee, req.status,
                scope=scope, priority=req.priority,
                acceptance_command=command,
                acceptance_manifest=req.acceptance_manifest,
                acceptance_required=req.acceptance_required,
                acceptance_actor=actor,
            )
        return await asyncio.to_thread(_do)
    except (ValueError, RuntimeError) as e:
        payload = {"error": str(e)}
        reason = getattr(e, "reason", "")
        if reason:
            payload["reason"] = reason
        return JSONResponse(payload, status_code=400)


@router.get("/tasks")
async def tm_list_tasks(project: str = "", status: str = "", assignee: str = "",
                        scope: str = ""):
    try:
        def _do():
            proj = project
            if project:
                proj = _resolve_task_project_id(project, "")
            elif scope:
                proj = _resolve_scope_project_id(scope)
                if not proj:
                    return {"tasks": [], "count": 0, "total_debt": "0"}
            return _tm.api_list_tasks(proj, status, assignee)
        return await asyncio.to_thread(_do)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/tasks/{par}")
async def tm_get_task(par: str, project: str = "", scope: str = ""):
    try:
        def _do():
            resolved_project = _resolve_task_project_id(project, scope)
            return _tm.api_get_task(par, project=resolved_project)
        return await asyncio.to_thread(_do)
    except ValueError as e:
        code = 404 if "not found" in str(e).lower() else 400
        return JSONResponse({"error": str(e)}, status_code=code)


@router.put("/tasks/{par}")
async def tm_update_task(
    par: str,
    req: TmTaskUpdate,
    request: Request,
    project: str = "",
    scope: str = "",
):
    try:
        caller_scope = ""
        requested_command = (req.acceptance_command or "").strip()
        if (req.clear_acceptance_command or req.clear_acceptance_oracle) and requested_command:
            raise ValueError(
                "acceptance_command and clear_acceptance_command are mutually exclusive"
            )
        command_update = (
            "" if (req.clear_acceptance_command or req.clear_acceptance_oracle)
            else (requested_command or None)
        )
        manifest_update = [] if req.clear_acceptance_oracle else req.acceptance_manifest
        required_update = False if req.clear_acceptance_oracle else req.acceptance_required
        oracle_update = manifest_update is not None or required_update is not None
        actor = None
        if command_update is not None or oracle_update:
            from app.mcp_proof import caller_may_use_orchestrator_privilege

            if not caller_may_use_orchestrator_privilege(request):
                return JSONResponse(
                    {"error": "acceptance_command is orchestrator-only"},
                    status_code=403,
                )
            session_id = request.headers.get("x-orchestra-session-id", "").strip()
            if oracle_update:
                try:
                    actor, caller_scope = _acceptance_actor(request)
                except ValueError as exc:
                    return JSONResponse({"error": str(exc)}, status_code=403)
            elif session_id:
                try:
                    actor, caller_scope = _acceptance_actor(request)
                except ValueError as exc:
                    return JSONResponse({"error": str(exc)}, status_code=403)

        def _do():
            if (command_update is not None or oracle_update) and caller_scope:
                resolved_project = _resolve_task_project_id("", caller_scope)
                if project and _resolve_task_project_id(project, "") != resolved_project:
                    raise ValueError(
                        "acceptance_command update is limited to caller's project"
                    )
                if scope and _resolve_task_project_id("", scope) != resolved_project:
                    raise ValueError(
                        "acceptance_command update is limited to caller's project"
                    )
            else:
                resolved_project = _resolve_task_project_id(project, scope)
            return _tm.api_update_task(
                par, req.title, req.description, req.price, req.status, req.assignee,
                project=resolved_project, priority=req.priority,
                acceptance_command=command_update,
                acceptance_manifest=manifest_update,
                acceptance_required=required_update,
                acceptance_actor=actor,
            )
        return await asyncio.to_thread(_do)
    except (ValueError, RuntimeError) as e:
        code = 404 if "not found" in str(e).lower() else 400
        payload = {"error": str(e)}
        reason = getattr(e, "reason", "")
        if reason:
            payload["reason"] = reason
        return JSONResponse(payload, status_code=code)


@router.post("/payments")
async def tm_receive_payment(req: TmPaymentReceive):
    try:
        def _do():
            client_id = _resolve_client_id(req.client, req.scope)
            return _tm.api_receive_payment(req.amount, client_id, req.date, req.note)
        return await asyncio.to_thread(_do)
    except (ValueError, RuntimeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/payments/status")
async def tm_payment_status(client: str = "", scope: str = ""):
    try:
        def _do():
            client_id = _resolve_client_id(client, scope)
            return _tm.api_payment_status(client_id)
        return await asyncio.to_thread(_do)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.get("/payments/history")
async def tm_payment_history(client: str = "", scope: str = ""):
    def _do():
        client_id = _resolve_client_id(client, scope)
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
    try:
        return await asyncio.to_thread(_do)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/sync/log")
async def tm_sync_log(limit: int = 50):
    limit_n = min(limit, 200)

    def _do():
        with _tm._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tm_sync_log ORDER BY id DESC LIMIT ?", (limit_n,)
            ).fetchall()
        return {"entries": [dict(r) for r in rows]}
    return await asyncio.to_thread(_do)


@router.post("/sync/retry/{sync_id}")
async def tm_sync_retry(sync_id: int):
    def _read_entry():
        with _tm._conn() as conn:
            row = conn.execute("SELECT * FROM tm_sync_log WHERE id = ?", (sync_id,)).fetchone()
            return dict(row) if row else None

    entry = await asyncio.to_thread(_read_entry)
    if not entry:
        return JSONResponse({"error": "sync entry not found"}, status_code=404)
    if entry["status"] not in ("error", "pending"):
        return {"message": "nothing to retry", "status": entry["status"]}
    task_id = entry["task_id"]

    if task_id:
        result = await yougile_sync_task(task_id)
        return {"retried": True, "task_id": task_id, "result": result}
    return {"error": "no task_id on sync entry"}

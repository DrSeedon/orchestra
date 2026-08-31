"""HTTP surface for authoritative portfolio projects."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import portfolio


router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class ProjectCreate(BaseModel):
    id: str
    name: str


class MemberCreate(BaseModel):
    session_id: str
    role: str


class TaskLinkCreate(BaseModel):
    task_project: str
    task_ref: str


class ProjectSourceUpdate(BaseModel):
    task_project: str


class StageOrderUpdate(BaseModel):
    stages: list[str]
    renames: dict[str, str] = Field(default_factory=dict)


class TaskStageUpdate(BaseModel):
    stage: str | None = None
    task_project: str = ""


class GoalCreate(BaseModel):
    objective: str
    watchdog_enabled: bool = False
    stall_after_seconds: int = 1800
    now: str | None = None


class GoalUpdate(BaseModel):
    objective: str | None = None
    watchdog_enabled: bool | None = None
    stall_after_seconds: int | None = None
    status: str | None = None
    now: str | None = None


class GoalProgress(BaseModel):
    note: str = ""
    now: str | None = None


class WaitCreate(BaseModel):
    question: str
    task_ref: str = ""
    now: str | None = None


class WaitClose(BaseModel):
    now: str | None = None


class WaitResolve(BaseModel):
    response: str | None = None
    now: str | None = None


class AttentionCreate(BaseModel):
    reason: str
    kind: str = "legacy"


def _actor(request: Request, *, required: bool = True) -> str:
    session_id = request.headers.get("x-orchestra-session-id", "").strip()
    if required and not session_id:
        raise portfolio.PortfolioError(403, "x-orchestra-session-id is required")
    return session_id


def _project_list_actor(request: Request) -> str:
    session_id = _actor(request, required=False)
    if session_id:
        return session_id
    from app.auth import is_auth_enabled, validate_session

    if not is_auth_enabled():
        return ""
    if validate_session(request.cookies.get("session", "")):
        return ""
    raise portfolio.PortfolioError(403, "dashboard session or agent session is required")


def _dashboard_operator(request: Request) -> bool:
    from app.auth import is_auth_enabled, validate_session

    return bool(
        is_auth_enabled() and validate_session(request.cookies.get("session", ""))
    )


def _call(action: Callable[[], object], *, status_code: int = 200):
    try:
        result = action()
    except portfolio.PortfolioError as exc:
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    if status_code == 200:
        return result
    return JSONResponse(result, status_code=status_code)


@router.post("/projects")
def create_project(req: ProjectCreate, request: Request):
    return _call(
        lambda: portfolio.create_project(_actor(request), req.id, req.name),
        status_code=201,
    )


@router.get("/projects")
def list_projects(request: Request):
    result = _call(lambda: portfolio.list_projects(_project_list_actor(request)))
    if isinstance(result, dict) and _dashboard_operator(request):
        from app.auth import create_csrf_token

        result["csrf_token"] = create_csrf_token(os.environ.get("DASHBOARD_USER", ""))
    return result


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request):
    return _call(lambda: portfolio.get_project(_actor(request), project_id))


@router.post("/projects/{project_id}/members")
def add_member(project_id: str, req: MemberCreate, request: Request):
    return _call(
        lambda: portfolio.add_member(
            _actor(request), project_id, req.session_id, req.role
        ),
        status_code=201,
    )


@router.put("/projects/{project_id}/source")
def set_project_task_source(
    project_id: str, req: ProjectSourceUpdate, request: Request
):
    return _call(
        lambda: portfolio.set_task_source(
            _actor(request), project_id, req.task_project
        )
    )


@router.put("/projects/{project_id}/stages")
def set_project_stage_order(
    project_id: str, req: StageOrderUpdate, request: Request
):
    return _call(
        lambda: portfolio.set_stage_order(
            _actor(request), project_id, req.stages, req.renames
        )
    )


@router.post("/projects/{project_id}/tasks")
def link_task(project_id: str, req: TaskLinkCreate, request: Request):
    return _call(
        lambda: portfolio.link_task(
            _actor(request), project_id, req.task_project, req.task_ref
        ),
        status_code=201,
    )


@router.delete("/projects/{project_id}/tasks/{task_ref}")
def unlink_task(
    project_id: str, task_ref: str, task_project: str, request: Request
):
    return _call(
        lambda: portfolio.unlink_task(
            _actor(request), project_id, task_project, task_ref
        )
    )


@router.put("/projects/{project_id}/tasks/{task_ref}/stage")
def set_task_stage(
    project_id: str, task_ref: str, req: TaskStageUpdate, request: Request
):
    return _call(
        lambda: portfolio.set_task_stage(
            _actor(request),
            project_id,
            task_ref,
            req.stage,
            task_project=req.task_project,
        )
    )


@router.get("/projects/{project_id}/tasks")
def list_tasks(project_id: str, request: Request):
    return _call(lambda: portfolio.list_tasks(_actor(request), project_id))


@router.get("/projects/{project_id}/goal")
def get_goal(project_id: str, request: Request):
    return _call(lambda: portfolio.get_goal(_actor(request), project_id))


@router.post("/projects/{project_id}/goals")
def create_goal(project_id: str, req: GoalCreate, request: Request):
    return _call(
        lambda: portfolio.create_goal(
            _actor(request),
            project_id,
            req.objective,
            watchdog_enabled=req.watchdog_enabled,
            stall_after_seconds=req.stall_after_seconds,
            now=req.now,
        ),
        status_code=201,
    )


@router.patch("/projects/{project_id}/goals/{goal_id}")
@router.put("/projects/{project_id}/goals/{goal_id}")
def update_goal(project_id: str, goal_id: str, req: GoalUpdate, request: Request):
    return _call(
        lambda: portfolio.update_goal(
            _actor(request),
            project_id,
            goal_id,
            objective=req.objective,
            watchdog_enabled=req.watchdog_enabled,
            stall_after_seconds=req.stall_after_seconds,
            status=req.status,
            now=req.now,
        )
    )


@router.post("/projects/{project_id}/goals/{goal_id}/progress")
def record_progress(
    project_id: str, goal_id: str, req: GoalProgress, request: Request
):
    return _call(
        lambda: portfolio.record_progress(
            _actor(request), project_id, goal_id, req.note, now=req.now
        )
    )


@router.post("/projects/{project_id}/waits")
def open_wait(project_id: str, req: WaitCreate, request: Request):
    try:
        result, inserted = portfolio.open_wait(
            _actor(request),
            project_id,
            req.question,
            task_ref=req.task_ref,
            now=req.now,
        )
    except portfolio.PortfolioError as exc:
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    return JSONResponse(result, status_code=201 if inserted else 200)


@router.get("/projects/{project_id}/waits")
def list_waits(project_id: str, request: Request):
    return _call(lambda: portfolio.list_waits(_actor(request), project_id))


@router.post("/projects/{project_id}/waits/{wait_id}/resolve")
async def resolve_wait(
    project_id: str, wait_id: str, req: WaitResolve, request: Request
):
    if req.response is None:
        try:
            return await asyncio.to_thread(
                portfolio.close_wait,
                _actor(request),
                project_id,
                wait_id,
                "resolved",
                now=req.now,
            )
        except portfolio.PortfolioError as exc:
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    from app.auth import require_operator_csrf

    require_operator_csrf(request)
    try:
        prepared = await asyncio.to_thread(
            portfolio.prepare_wait_response, project_id, wait_id, req.response
        )
    except portfolio.PortfolioError as exc:
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    from app import message_deliveries

    existing = message_deliveries._row(prepared["delivery_id"])
    if prepared["existing"]:
        if existing is None:
            return JSONResponse(
                {"error": "reserved wait delivery is missing"}, status_code=409
            )
        delivery = message_deliveries._resource(
            existing, acceptance="ALREADY_ACCEPTED"
        )
    else:
        from app.deps import manager

        await manager.preflight_message_delivery(prepared["target_session_id"])
        try:
            await asyncio.to_thread(
                portfolio.validate_wait_response_delivery,
                project_id,
                wait_id,
                prepared["delivery_id"],
                prepared["target_session_id"],
            )
        except portfolio.PortfolioError as exc:
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
        delivery, _status_code = await message_deliveries.accept_message_delivery(
            delivery_id=prepared["delivery_id"],
            source_session_id=None,
            source_principal=f"operator:{os.environ.get('DASHBOARD_USER', '')}",
            source_name="dashboard-user",
            source_scope="",
            source_task_id="",
            target_session_id=prepared["target_session_id"],
            target_name=prepared["target_name"],
            target_scope=prepared["target_scope"],
            target_task_id=prepared["target_task_id"],
            target_generation=prepared["target_generation"],
            message=prepared["message"],
            rendered_message=prepared["message"],
            message_kind="portfolio_wait_answer",
            wake=True,
        )
    wait = await asyncio.to_thread(portfolio.wait_payload, project_id, wait_id)
    return {"wait": wait, "delivery": delivery}


@router.post("/projects/{project_id}/waits/{wait_id}/cancel")
def cancel_wait(project_id: str, wait_id: str, req: WaitClose, request: Request):
    return _call(
        lambda: portfolio.close_wait(
            _actor(request), project_id, wait_id, "cancelled", now=req.now
        )
    )


@router.post("/attention")
def create_projectless_attention(req: AttentionCreate, request: Request):
    return _call(
        lambda: portfolio.create_attention(
            _actor(request), req.reason, kind=req.kind
        ),
        status_code=201,
    )


@router.post("/projects/{project_id}/attention")
def create_project_attention(
    project_id: str, req: AttentionCreate, request: Request
):
    return _call(
        lambda: portfolio.create_attention(
            _actor(request), req.reason, kind=req.kind, project_id=project_id
        ),
        status_code=201,
    )

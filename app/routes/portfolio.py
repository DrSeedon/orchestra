"""HTTP surface for authoritative portfolio projects."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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
    return _call(lambda: portfolio.list_projects(_project_list_actor(request)))


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
def resolve_wait(project_id: str, wait_id: str, req: WaitClose, request: Request):
    return _call(
        lambda: portfolio.close_wait(
            _actor(request), project_id, wait_id, "resolved", now=req.now
        )
    )


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

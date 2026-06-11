"""Background Jobs API routes."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.deps import manager

router = APIRouter(prefix="/api/bg", tags=["bg-jobs"])


class BgJobCreateRequest(BaseModel):
    type: str
    config: dict = {}
    message: str = ""
    target_name: str = ""
    target_scope: str = ""
    timeout_seconds: int = 3600
    created_by: str = ""


@router.post("/jobs")
async def bg_job_create(req: BgJobCreateRequest):
    from app.bg_jobs import bg_manager
    scope = req.target_scope.rstrip("/")
    name = req.target_name
    if not scope or not name:
        return JSONResponse({"error": "target_name and target_scope required"}, status_code=400)
    session = manager.get_by_name(name, scope)
    if not session:
        return JSONResponse({"error": f"session '{name}' not found in scope"}, status_code=404)
    session_id = session.id
    result = await bg_manager.create(
        job_type=req.type, config=req.config, message=req.message,
        target_session_id=session_id, target_name=name, target_scope=scope,
        created_by=req.created_by, timeout_seconds=req.timeout_seconds,
    )
    if result.get("error"):
        return JSONResponse(result, status_code=400)
    return result


@router.get("/jobs")
async def bg_job_list(scope: str = "", session_id: str = ""):
    from app.db import bg_get_jobs
    return bg_get_jobs(scope=scope or None, session_id=session_id or None)


@router.delete("/jobs/{job_id}")
async def bg_job_cancel(job_id: str):
    from app.bg_jobs import bg_manager
    result = await bg_manager.cancel(job_id)
    if result.get("error"):
        return JSONResponse(result, status_code=404)
    return result

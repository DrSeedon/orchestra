"""Background Jobs API routes."""

from fastapi import APIRouter, Request
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
    receipt_id: str = ""


@router.post("/jobs")
async def bg_job_create(req: BgJobCreateRequest, request: Request = None):
    from app.bg_jobs import bg_manager
    scope = req.target_scope.rstrip("/")
    name = req.target_name
    if not scope or not name:
        return JSONResponse({"error": "target_name and target_scope required"}, status_code=400)
    session = manager.get_by_name(name, scope)
    if not session:
        return JSONResponse({"error": f"session '{name}' not found in scope"}, status_code=404)
    session_id = session.id
    if not str(session_id or "").strip():
        # Раньше пустой id уезжал в джоб и всплывал как 500 где-то ниже (#54).
        # Отказ на границе: 400 с причиной, которую видно вызывающему агенту.
        return JSONResponse(
            {"error": f"session '{name}' has no id — it cannot be a background job target; "
                      f"respawn the worker"},
            status_code=400,
        )
    from app.db import get_session, review_receipt_get, review_receipt_finish, bg_get_jobs
    from app.work_review import assignment, is_advisory, _task_reviews, MAX_REVIEW_REQUESTS
    from app.db import _conn
    import json
    target = get_session(session_id) or {}
    run = assignment(scope, session_id, str(target.get("task_id") or ""))
    config = dict(req.config)
    config.pop("review_advisory", None)
    config.pop("review_receipt_id", None)
    receipt = review_receipt_get(req.receipt_id) if req.receipt_id else None
    advisory = (is_advisory(run) or bool(receipt and int(receipt.get("schema_version") or 1) >= 3)) and req.type == "run" and bool(req.receipt_id or config.get("success_file"))
    if advisory:
        from app.mcp_proof import check_mcp_proof, PROOF_HEADER
        caller = request.headers.get("x-orchestra-session-id", "") if request else ""
        proof = request.headers.get(PROOF_HEADER, "") if request else ""
        if caller != session_id or not check_mcp_proof(caller, proof) or target.get("role") not in {"worker", "full-cycle"} or target.get("is_orchestrator"):
            return JSONResponse({"error": "review_requester_forbidden"}, status_code=403)
        if not receipt or int(receipt.get("schema_version") or 1) < 3 or receipt["session_id"] != session_id or receipt["scope"] != scope:
            return JSONResponse({"error": "review_protocol_upgrade_required: reconnect MCP before requesting review"}, status_code=409)
        if config.get("success_file") != receipt["artifact_path"]:
            return JSONResponse({"error": "review_artifact_mismatch"}, status_code=409)
        # Run jobs do not await between lookup, save and start. Replay returns the saved job,
        # including the crash gap before the MCP process linked its receipt to the job.
        for job in bg_get_jobs(session_id=session_id):
            previous = json.loads(job["config"])
            if previous.get("review_receipt_id") == req.receipt_id:
                if previous.get("command") != config.get("command"):
                    return JSONResponse({"error": "review_job_payload_changed"}, status_code=409)
                return {"id": job["id"], "type": "run", "status": job["status"]}
        if not is_advisory(run) or run["status"] != "requested" or receipt["task_id"] != str(target.get("task_id") or ""):
            return JSONResponse({"error": "review_task_not_active"}, status_code=409)
        with _conn() as connection:
            rows = _task_reviews(connection, run)
        if receipt["status"] != "requested" or len(rows) > MAX_REVIEW_REQUESTS or any(r["status"] == "requested" and r["receipt_id"] != req.receipt_id for r in rows):
            return JSONResponse({"error": "review_budget_or_active_request_conflict"}, status_code=409)
        config.update(review_advisory=True, review_receipt_id=req.receipt_id)
    result = await bg_manager.create(
        job_type=req.type, config=config, message=req.message,
        target_session_id=session_id, target_name=name, target_scope=scope,
        created_by=str(target.get("name") or name) if advisory else req.created_by, timeout_seconds=req.timeout_seconds,
    )
    if result.get("error"):
        return JSONResponse(result, status_code=400)
    if advisory and result.get("id"):
        review_receipt_finish(req.receipt_id, {"job_id": result["id"]})
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

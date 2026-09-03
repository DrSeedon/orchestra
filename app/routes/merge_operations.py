"""HTTP adapter for durable merge operations."""

import asyncio
import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.merge_operations import (
    accept_merge_operation,
    ensure_operation_runner,
    get_operation_record,
    operation_not_found_result,
    resolve_operation,
)

router = APIRouter(prefix="/api/merge-operations", tags=["merge-operations"])


def _response(result: dict, status_code: int = 200) -> JSONResponse:
    top_error = (
        result.get("error")
        if status_code >= 400 or result.get("operation_state") in {"FAILED", "UNKNOWN"}
        else None
    )
    return JSONResponse(
        {"result": result, "error": top_error},
        status_code=status_code,
    )


@router.get("/capabilities")
async def merge_operation_capabilities():
    # `capability`/`schema_version` остаются на operation-v1: это контракт, по которому
    # СТАРЫЙ клиент узнаёт знакомый сервер. Про task-lifecycle-v2 новый клиент узнаёт из
    # `capabilities` + `merge_schema_version` — именно эту пару он и читает перед POST.
    return {
        "capability": "operation-v1",
        "schema_version": 1,
        "capabilities": ["operation-v1", "task-lifecycle-v2"],
        "merge_schema_version": 2,
    }


@router.post("")
async def create_merge_operation(req: dict, request: Request = None):
    from app.diff_budget import request_may_waive_diff_budget

    waive = bool(req.get("waive_diff_budget"))
    if waive and (request is None or not request_may_waive_diff_budget(request)):
        return _response(
            {
                "operation_state": "FAILED",
                "error": {
                    "code": "DIFF_BUDGET_WAIVE_FORBIDDEN",
                    "message": (
                        "waive_diff_budget is orchestrator-only; "
                        "the executor cannot skip the review ceiling"
                    ),
                },
            },
            403,
        )
    result, status_code = await accept_merge_operation(
        operation_id=str(req.get("operation_id") or ""),
        name=str(req.get("name") or ""),
        scope=str(req.get("scope") or ""),
        target=str(req.get("target") or ""),
        next_task_id=str(req.get("next_task_id") or ""),
        waive_diff_budget=waive,
        waived_by=str(req.get("waived_by") or ""),
        task_outcome=str(req.get("task_outcome") or ""),
        merge_schema_version=(
            int(req["merge_schema_version"])
            if req.get("merge_schema_version") is not None else None
        ),
    )
    return _response(result, status_code)


@router.post("/review-skip")
async def record_review_skip(req: dict, request: Request = None):
    from app.db import (
        get_session,
        get_session_by_name,
        review_receipt_record_skip,
    )
    from app.mcp_proof import caller_may_use_orchestrator_privilege
    from app.review_coverage import current_policy_ref, resolve_implementation_subject

    if request is None or not caller_may_use_orchestrator_privilege(request):
        return JSONResponse(
            {"error": {"code": "review_skip_forbidden", "message": "review skip is orchestrator-only"}},
            status_code=403,
        )
    decision_id = str(req.get("decision_id") or "").strip()
    target_worker = str(req.get("target_worker") or "").strip()
    scope = str(req.get("scope") or "").rstrip("/")
    evidence = str(req.get("outcome_evidence_ref") or "").strip()
    if not decision_id or len(decision_id) > 128 or not target_worker or not scope or not evidence:
        return JSONResponse(
            {"error": {"code": "invalid_argument", "message": (
                "decision_id, target_worker, scope, and outcome_evidence_ref are required"
            )}},
            status_code=400,
        )
    target = get_session_by_name(target_worker, scope)
    if not target:
        return JSONResponse(
            {"error": {"code": "target_worker_not_found", "message": "target worker not found"}},
            status_code=404,
        )
    try:
        subject = resolve_implementation_subject(
            str(target.get("worktree_path") or ""),
            str(target.get("base_branch") or "main"),
        )
    except ValueError as error:
        return JSONResponse(
            {"error": {"code": "review_subject_invalid", "message": str(error)}},
            status_code=409,
        )
    actor_session_id = request.headers.get("x-orchestra-session-id", "").strip()
    actor = get_session(actor_session_id) or {}
    now = datetime.now(timezone.utc).isoformat()
    receipt_id = "review-skip:" + hashlib.sha256(
        f"{scope}\0{decision_id}".encode()
    ).hexdigest()
    receipt = {
        "receipt_id": receipt_id,
        "schema_version": 1,
        "runtime": "none",
        "reviewer_model": "",
        "model_source": "direct",
        "session_id": str(target["id"]),
        "worker_name": str(target["name"]),
        "scope": scope,
        "task_id": str(target.get("task_id") or ""),
        "task_source": "session_lookup",
        "artifact_path": "",
        "mode": "skip",
        "round": None,
        "job_id": "",
        "usage_event_id": "",
        "requested_at": now,
        "completed_at": now,
        "status": "completed",
        "return_code": None,
        "failure_code": "",
        "artifact_exists": 0,
        "artifact_bytes": 0,
        "artifact_sha256": "",
        "verdict_present": 0,
        "verdict_value": "",
        "jsonl_response_present": 0,
        "recovery_source": "",
        "author_outcome": "unknown",
        "outcome_source": "direct",
        "outcome_evidence_ref": evidence,
        "notification_event_id": "",
        "subject_kind": "implementation",
        **subject,
        "coverage_outcome": "skipped",
        "policy_ref": current_policy_ref(),
        "decision_actor": str(actor.get("name") or actor_session_id),
    }
    try:
        saved = review_receipt_record_skip(receipt)
    except ValueError as error:
        return JSONResponse(
            {"error": {"code": "review_skip_conflict", "message": str(error)}},
            status_code=409,
        )
    return JSONResponse({"result": saved, "error": None})


@router.post("/{operation_id}/resolve")
async def resolve_merge_operation(operation_id: str, req: dict):
    result, status_code = await asyncio.to_thread(
        resolve_operation,
        operation_id,
        reason=str(req.get("reason") or ""),
        actor=str(req.get("actor") or ""),
    )
    return _response(result, status_code)


@router.get("/{operation_id}")
async def get_merge_operation(operation_id: str):
    record = await asyncio.to_thread(get_operation_record, operation_id)
    if not record:
        return _response(operation_not_found_result(operation_id), 404)
    if record["state"] == "PENDING":
        ensure_operation_runner(operation_id)
    return _response(record["result"])

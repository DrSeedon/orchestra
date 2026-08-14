"""HTTP adapter for durable merge operations."""

import asyncio

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
    return {"capability": "operation-v1", "schema_version": 1}


@router.post("")
async def create_merge_operation(req: dict, request: Request):
    from app.diff_budget import request_may_waive_diff_budget

    waive = bool(req.get("waive_diff_budget"))
    if waive and not request_may_waive_diff_budget(request):
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
    )
    return _response(result, status_code)


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

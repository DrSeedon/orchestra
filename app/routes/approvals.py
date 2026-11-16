from typing import Literal
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from app import approvals
from app.deps import manager
from app.routes.always_on import address, owned, operator, validated

router = APIRouter(prefix="/api/approvals",tags=["approvals"])


class ApprovalCreate(BaseModel):
    recipient: str
    scope: str
    action: str
    summary: str
    payload: dict = Field(default_factory=dict)
    risk_level: str = "medium"
    context_note: str = ""
    expires_in_seconds: float = 86400
    idempotency_key: str = ""


class ApprovalResolve(BaseModel):
    decision: Literal["approved","rejected"]
    note: str = ""
    decided_by: str = "owner"


@router.post("")
def create(req: ApprovalCreate,request: Request):
    address(request,req.recipient,req.scope)
    return validated(lambda: approvals.request_approval(**req.model_dump()))


@router.get("")
def listing(request: Request,recipient: str | None=None,scope: str | None=None):
    recipient,scope = address(request,recipient,scope)
    return approvals.list_approvals(recipient,scope)


@router.post("/{approval_id}/cancel")
def cancel(approval_id: str,request: Request):
    owned(request,"deferred_approvals",approval_id)
    return {"cancelled":approvals.cancel_approval(approval_id)}


@router.post("/{approval_id}/resolve")
async def resolve(approval_id: str,req: ApprovalResolve,request: Request):
    operator(request)
    owned(request,"deferred_approvals",approval_id)
    return await approvals.resolve_approval(approval_id,**req.model_dump(),manager=manager)

"""Operator-only native RPC cards, isolated from deferred mailbox approvals."""
import os
from fastapi import APIRouter,Request,HTTPException
from pydantic import BaseModel
from app import db,native_requests
from app.auth import require_operator_session,require_operator_csrf,create_csrf_token

router=APIRouter(prefix="/api/native-requests",tags=["native requests"])


class Answer(BaseModel):
    owner_id:str
    binding:str
    option_id:str|None=None
    cancel:bool=False


@router.get("")
async def listing(request:Request,owner_id:str):
    require_operator_session(request)
    if db.get_session(owner_id) is None:raise HTTPException(404,"Session not found")
    return native_requests.pending_for(owner_id)


@router.get("/csrf")
async def csrf(request:Request):
    require_operator_session(request)
    return {"token":create_csrf_token(os.environ.get("DASHBOARD_USER",""))}


@router.get("/capabilities")
async def capabilities(request:Request):
    require_operator_session(request)
    from app.backend_antigravity import AntigravityBackend
    return AntigravityBackend.foreground_capabilities


@router.post("/{request_id}/respond")
async def respond(request_id:str,req:Answer,request:Request):
    require_operator_csrf(request)
    try:return native_requests.resolve(request_id,**req.model_dump())
    except KeyError:raise HTTPException(404,"Native request not found")
    except PermissionError:raise HTTPException(403,"Native request owner mismatch")
    except ValueError as error:raise HTTPException(409,str(error))
